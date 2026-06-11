// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, serverError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAdminRole } from "../../middleware.js";
import { getRedis } from "../../redis.js";
import { cached, healthKey } from "../../redisCache.js";
import { getSupabase } from "../../supabase.js";

export default withAdminRole(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		// #671: Rate limit admin health endpoint
		const { checkRateLimit } = await import("../../rateLimiter.js");
		const rl = await checkRateLimit({
			key: `admin-health:${user.id}`,
			limit: 30,
			windowSeconds: 60,
			failMode: "open",
		});
		if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

		const supabase = getSupabase();

		// Check subscription tier
		const { data: profile } = await supabase
			.from("profiles")
			.select("subscription_tier")
			.eq("id", user.id)
			.maybeSingle();

		if (!profile || profile.subscription_tier === "free") {
			return apiError(res, 403, "Pro or Empire subscription required");
		}

		try {
			// Cache health data for 30 seconds (frontend polls every 60s)
			const healthData = await cached(healthKey(), 30, async () => {
				const twentyFourHoursAgo = new Date(
					Date.now() - 24 * 60 * 60 * 1000,
				).toISOString();

				// Fetch cron runs, locks, errors, and queue health in parallel
				const [
					{ data: cronRuns },
					{ data: locks },
					{ data: recentErrors },
					{ count: pendingThreadsWebhooks },
					{ count: pendingIgWebhooks },
					{ count: pendingContainers },
				] = await Promise.all([
					supabase
						.from("cron_runs")
						.select(
							"job_name, status, started_at, finished_at, items_processed, error",
						)
						.gte("started_at", twentyFourHoursAgo)
						.order("started_at", { ascending: false }),
					supabase
						.from("cron_locks")
						.select("job_name, locked_by, locked_at, expires_at")
						.gt("expires_at", new Date().toISOString()),
					supabase
						.from("cron_runs")
						.select("job_name, error, started_at")
						.eq("status", "failed")
						.not("error", "is", null)
						.order("started_at", { ascending: false })
						.limit(20),
					supabase
						.from("threads_webhook_events")
						.select("id", { count: "exact", head: true })
						.eq("processed", false)
						.or("dead_letter.is.null,dead_letter.eq.false"),
					supabase
						.from("ig_webhook_events")
						.select("id", { count: "exact", head: true })
						.eq("processed", false)
						.or("dead_letter.is.null,dead_letter.eq.false"),
					supabase
						.from("ig_pending_containers")
						.select("id", { count: "exact", head: true })
						.in("status", ["pending", "ready"]),
				]);

				// Aggregate cron stats by job
				const jobStats: Record<
					string,
					{
						runs: number;
						failed: number;
						totalDurationMs: number;
						lastRun: string | null;
						itemsProcessed: number;
					}
				> = {};

				for (const run of cronRuns || []) {
					if (!jobStats[run.job_name]) {
						jobStats[run.job_name] = {
							runs: 0,
							failed: 0,
							totalDurationMs: 0,
							lastRun: null,
							itemsProcessed: 0,
						};
					}
					const s = jobStats[run.job_name];
					s!.runs++;
					if (run.status === "failed") s!.failed++;
					if (run.finished_at && run.started_at) {
						const duration =
							new Date(run.finished_at).getTime() -
							new Date(run.started_at).getTime();
						if (duration > 0) s!.totalDurationMs += duration;
					}
					if (run.items_processed) s!.itemsProcessed += run.items_processed;
					if (!s!.lastRun || run.started_at > s!.lastRun)
						s!.lastRun = run.started_at;
				}

				const cronJobStats = Object.entries(jobStats).map(([name, stats]) => ({
					name,
					runs24h: stats.runs,
					failed: stats.failed,
					avgDurationMs:
						stats.runs > 0 ? Math.round(stats.totalDurationMs / stats.runs) : 0,
					successRate:
						stats.runs > 0
							? (((stats.runs - stats.failed) / stats.runs) * 100).toFixed(1)
							: "0",
					lastRun: stats.lastRun,
					itemsProcessed: stats.itemsProcessed,
				}));

				// ----------------------------------------------------------------
				// Redis connectivity check
				// ----------------------------------------------------------------
				let redisStatus: {
					connected: boolean;
					latencyMs: number | null;
					error?: string | undefined;
				} = {
					connected: false,
					latencyMs: null,
				};
				try {
					const redis = getRedis();
					const start = Date.now();
					await redis.ping();
					redisStatus = { connected: true, latencyMs: Date.now() - start };
				} catch (redisErr: unknown) {
					redisStatus = {
						connected: false,
						latencyMs: null,
						error:
							redisErr instanceof Error
								? redisErr.message
								: "Redis ping failed",
					};
				}

				// ----------------------------------------------------------------
				// Rate limits + Dead letter queues (all independent, run in parallel)
				// ----------------------------------------------------------------
				const todayStart = new Date();
				todayStart.setUTCHours(0, 0, 0, 0);
				const todayISO = todayStart.toISOString();

				type RateLimitRow = {
					account_id: string;
					hourly_count: number;
					daily_count: number;
					last_reset_at: string;
				};
				type IgRateLimitRow = {
					account_id: string;
					daily_count: number;
					last_reset_at: string;
				};
				const [
					{ data: threadsRateLimitsRaw },
					{ data: igRateLimitsRaw },
					{ count: dlqAutoPost },
					{ count: dlqIgWebhook },
					{ count: dlqThreadsWebhook },
					{ count: dlqIgContainers },
				] = await Promise.all([
					supabase
						.from("rate_limit_tracking")
						.select("account_id, hourly_count, daily_count, last_reset_at")
						.gte("last_reset_at", todayISO),
					supabase
						.from("ig_rate_limit_tracking")
						.select("account_id, daily_count, last_reset_at")
						.gte("last_reset_at", todayISO),
					supabase
						.from("auto_post_queue")
						.select("id", { count: "exact", head: true })
						.eq("status", "dead_letter"),
					// biome-ignore lint/suspicious/noExplicitAny: Supabase type instantiation depth
					(supabase as any)
						.from("ig_webhook_events")
						.select("id", { count: "exact", head: true })
						.eq("dead_letter", true),
					// biome-ignore lint/suspicious/noExplicitAny: Supabase type instantiation depth
					(supabase as any)
						.from("threads_webhook_events")
						.select("id", { count: "exact", head: true })
						.eq("dead_letter", true),
					supabase
						.from("ig_pending_containers")
						.select("id", { count: "exact", head: true })
						.eq("dead_letter", true),
				]);

				const threadsRateLimits = threadsRateLimitsRaw as unknown as
					| RateLimitRow[]
					| null;
				const igRateLimits = igRateLimitsRaw as unknown as
					| IgRateLimitRow[]
					| null;

				// ----------------------------------------------------------------
				// #585: Meta API health check via rate_limit_tracking staleness
				// ----------------------------------------------------------------
				const twoHoursAgo = new Date(
					Date.now() - 2 * 60 * 60 * 1000,
				).toISOString();
				const metaApiHealth: {
					threads: { healthy: boolean; staleAccounts: string[] };
					instagram: { healthy: boolean; staleAccounts: string[] };
				} = {
					threads: { healthy: true, staleAccounts: [] },
					instagram: { healthy: true, staleAccounts: [] },
				};

				// Check Threads rate limit staleness — accounts active today but last_reset_at > 2h old
				const staleThreadsAccounts = (threadsRateLimits || []).filter(
					(r: { last_reset_at: string | null; daily_count: number }) =>
						r.last_reset_at &&
						r.last_reset_at < twoHoursAgo &&
						r.daily_count > 0,
				);
				if (staleThreadsAccounts.length > 0) {
					metaApiHealth.threads.healthy = false;
					metaApiHealth.threads.staleAccounts = staleThreadsAccounts.map(
						(r: { account_id: string }) => r.account_id,
					);
				}

				// Check Instagram rate limit staleness
				const staleIgAccounts = (igRateLimits || []).filter(
					(r: { last_reset_at: string | null; daily_count: number }) =>
						r.last_reset_at &&
						r.last_reset_at < twoHoursAgo &&
						r.daily_count > 0,
				);
				if (staleIgAccounts.length > 0) {
					metaApiHealth.instagram.healthy = false;
					metaApiHealth.instagram.staleAccounts = staleIgAccounts.map(
						(r: { account_id: string }) => r.account_id,
					);
				}

				const { getAccountSyncHealth } = await import("../../syncHealth.js");
				const accountSyncHealth = await getAccountSyncHealth(supabase, {
					limitIssues: 100,
				});

				// ----------------------------------------------------------------
				// #592: Integrate crisis detection into health dashboard
				// ----------------------------------------------------------------
				let activeCrises: Array<{
					id: string;
					severity: string;
					trigger_type: string;
					created_at: string;
					user_id: string;
				}> = [];
				let recentAnomalies: Array<{
					id: string;
					alert_type: string;
					severity: string;
					platform: string;
					created_at: string | null;
				}> = [];
				try {
					const fortyEightHoursAgo = new Date(
						Date.now() - 48 * 60 * 60 * 1000,
					).toISOString();

					const [{ data: crises }, { data: anomalies }] = await Promise.all([
						supabase
							.from("crisis_events")
							.select("id, severity, trigger_type, created_at, user_id")
							.is("resolved_at", null)
							.order("created_at", { ascending: false })
							.limit(20),
						supabase
							.from("anomaly_alerts")
							.select("id, alert_type, severity, platform, created_at")
							.gte("created_at", fortyEightHoursAgo)
							.in("severity", ["high", "critical"])
							.order("created_at", { ascending: false })
							.limit(20),
					]);
					activeCrises = (crises as unknown as typeof activeCrises) || [];
					recentAnomalies = anomalies || [];
				} catch (crisisErr) {
					logger.error("Failed to fetch crisis data for health dashboard", {
						error: String(crisisErr),
					});
				}

				// ----------------------------------------------------------------
				// #590: Compute health score for historical tracking
				// ----------------------------------------------------------------
				const totalCronJobs = cronJobStats.length;
				const failedCronJobs = cronJobStats.filter((j) => j.failed > 0).length;
				const cronHealthPct =
					totalCronJobs > 0
						? Math.round(
								((totalCronJobs - failedCronJobs) / totalCronJobs) * 100,
							)
						: 100;
				const dlqTotal =
					(dlqAutoPost || 0) +
					(dlqIgWebhook || 0) +
					(dlqThreadsWebhook || 0) +
					(dlqIgContainers || 0);
				const dlqPenalty = Math.min(dlqTotal * 2, 20); // Max 20% penalty from DLQ
				const redisPenalty = redisStatus.connected ? 0 : 15;
				const metaPenalty =
					(!metaApiHealth.threads.healthy ? 5 : 0) +
					(!metaApiHealth.instagram.healthy ? 5 : 0);
				const syncPenalty = Math.min(
					accountSyncHealth.staleSyncAccounts * 2 +
						accountSyncHealth.webhookRegressionAccounts * 3 +
						accountSyncHealth.missingCredentialAccounts * 5,
					20,
				);
				// #592: Factor crisis events into health score
				const crisisPenalty = activeCrises.reduce((sum, c) => {
					return sum + (c.severity === "severe" ? 15 : 5);
				}, 0);
				const anomalyPenalty = Math.min(recentAnomalies.length * 3, 15);
				const healthScore = Math.max(
					0,
					Math.min(
						100,
						cronHealthPct -
							dlqPenalty -
							redisPenalty -
							metaPenalty -
							syncPenalty -
							crisisPenalty -
							anomalyPenalty,
					),
				);

				return {
					cronJobs: cronJobStats,
					activeLocks: locks || [],
					recentErrors: recentErrors || [],
					queues: {
						threadsWebhooksPending: pendingThreadsWebhooks || 0,
						igWebhooksPending: pendingIgWebhooks || 0,
						igContainersPending: pendingContainers || 0,
					},
					redis: redisStatus,
					rateLimits: {
						threads: (threadsRateLimits || []).map(
							(r: {
								account_id: string;
								hourly_count: number;
								daily_count: number;
								last_reset_at: string;
							}) => ({
								accountId: r.account_id,
								hourlyCount: r.hourly_count,
								dailyCount: r.daily_count,
								lastResetAt: r.last_reset_at,
							}),
						),
						instagram: (igRateLimits || []).map(
							(r: {
								account_id: string;
								daily_count: number;
								last_reset_at: string;
							}) => ({
								accountId: r.account_id,
								dailyCount: r.daily_count,
								lastResetAt: r.last_reset_at,
							}),
						),
					},
					metaApiHealth,
					accountSyncHealth,
					deadLetterQueues: {
						autoPost: dlqAutoPost || 0,
						igWebhooks: dlqIgWebhook || 0,
						threadsWebhooks: dlqThreadsWebhook || 0,
						igContainers: dlqIgContainers || 0,
						total: dlqTotal,
					},
					// #592: Crisis detection integration
					crisisStatus: {
						activeCrises: activeCrises.map((c) => ({
							id: c.id,
							severity: c.severity,
							triggerType: c.trigger_type,
							createdAt: c.created_at,
						})),
						recentAnomalies: recentAnomalies.map((a) => ({
							id: a.id,
							alertType: a.alert_type,
							severity: a.severity,
							platform: a.platform,
							createdAt: a.created_at,
						})),
						hasCrisis: activeCrises.length > 0,
						crisisLevel: activeCrises.some((c) => c.severity === "severe")
							? "severe"
							: activeCrises.length > 0
								? "warning"
								: "normal",
					},
					healthScore,
					generatedAt: new Date().toISOString(),

					// Token expiry forecast — tokens expiring within 7 days
					tokenExpiryForecast: await (async () => {
						try {
							const sevenDaysFromNow = new Date(
								Date.now() + 7 * 24 * 60 * 60 * 1000,
							).toISOString();

							const [{ count: expiringThreads }, { count: expiringIG }] =
								await Promise.all([
									supabase
										.from("accounts")
										.select("*", { count: "exact", head: true })
										.eq("is_active", true)
										.lte("token_expires_at", sevenDaysFromNow),
									supabase
										.from("instagram_accounts")
										.select("*", { count: "exact", head: true })
										.eq("is_active", true)
										.lte("token_expires_at", sevenDaysFromNow),
								]);

							return {
								threads: expiringThreads || 0,
								instagram: expiringIG || 0,
								total: (expiringThreads || 0) + (expiringIG || 0),
							};
						} catch (tokenErr) {
							logger.error("Failed to fetch token expiry forecast", {
								error: String(tokenErr),
							});
							return { threads: 0, instagram: 0, total: 0 };
						}
					})(),
				};
			});

			// ----------------------------------------------------------------
			// #590: Store daily health score in Redis and return 7-day history
			// ----------------------------------------------------------------
			const redis = getRedis();
			const today = new Date().toISOString().slice(0, 10); // YYYY-MM-DD
			const healthScoreKey = `health:daily:${user.id}:${today}`;

			// Store today's score (expires after 30 days)
			if (healthData.healthScore !== undefined) {
				await redis
					.set(
						healthScoreKey,
						JSON.stringify({
							score: healthData.healthScore,
							timestamp: healthData.generatedAt,
						}),
						{ ex: 30 * 24 * 60 * 60 },
					)
					.catch((err: unknown) => {
						logger.error("Failed to store daily health score", {
							error: String(err),
						});
					});
			}

			// Read last 7 days of scores
			const history: Array<{ date: string; score: number; timestamp: string }> =
				[];
			for (let i = 6; i >= 0; i--) {
				const d = new Date();
				d.setDate(d.getDate() - i);
				const dateStr = d.toISOString().slice(0, 10);
				const key = `health:daily:${user.id}:${dateStr}`;
				try {
					const val = await redis.get(key);
					if (val) {
						const parsed = typeof val === "string" ? JSON.parse(val) : val;
						history.push({
							date: dateStr,
							score: parsed.score,
							timestamp: parsed.timestamp,
						});
					}
				} catch {
					// Skip corrupted entries
				}
			}

			return apiSuccess(res, { ...healthData, history });
		} catch (error: unknown) {
			logger.error("Health check failed", { error: String(error) });
			return serverError(res, "Health check failed");
		}
	},
);
