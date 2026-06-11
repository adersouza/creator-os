/**
 * Health Monitor — Consolidated Cron Job
 *
 * Merges three former cron jobs into a single handler:
 *   Phase 1: Deploy Impact checks (~5s, every invocation)
 *   Phase 2: Crisis Check (~30-120s, every invocation)
 *   Phase 3: Canary Check (~10s, every 6h — when UTCHours % 6 === 0)
 *
 * Runs every 2 hours via Vercel cron. maxDuration = 300s.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { AlertLevel, alert, alertCronFailure } from "../_lib/alerting.js";
import { createNotification } from "../_lib/createNotification.js";
import { trackCronRun, withCronLock } from "../_lib/cronUtils.js";
import { logger } from "../_lib/logger.js";
import { getRedis } from "../_lib/redis.js";
import { getSupabase, getSupabaseAny } from "../_lib/supabase.js";

export const config = {
	maxDuration: 300,
};

const JOB_NAME = "health-monitor";
const MAX_EXECUTION_TIME = 290000; // 290s — leave 10s headroom

// ============================================================================
// Shared Types
// ============================================================================

interface CanaryResult {
	metric: string;
	healthy: boolean;
	value: string;
	threshold: string;
}

interface DeployBreach {
	metric: string;
	current: number;
	baseline: number;
	detail: string;
}

interface PhaseResult {
	ran: boolean;
	skippedReason?: string | undefined;
	error?: string | undefined;
	[key: string]: unknown;
}

// ============================================================================
// Time Budget Helper
// ============================================================================

function hasTimeBudget(startTime: number, reserveMs = 10000): boolean {
	return Date.now() - startTime < MAX_EXECUTION_TIME - reserveMs;
}

// ============================================================================
// Phase 1: Deploy Impact Checks
// ============================================================================

async function runDeployImpact(
	supabase: ReturnType<typeof getSupabase>,
): Promise<PhaseResult> {
	const now = new Date();
	const breaches: DeployBreach[] = [];

	// ---- 1. Error rate comparison ----
	const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000).toISOString();
	const twentyFourHoursAgo = new Date(
		now.getTime() - 24 * 60 * 60 * 1000,
	).toISOString();

	const [{ count: errorsLastHour }, { count: errors24h }] = await Promise.all([
		supabase
			.from("cron_runs")
			.select("*", { count: "exact", head: true })
			.eq("status", "failed")
			.gte("started_at", oneHourAgo)
			.then((r) => ({ count: r.count ?? 0 })),
		supabase
			.from("cron_runs")
			.select("*", { count: "exact", head: true })
			.eq("status", "failed")
			.gte("started_at", twentyFourHoursAgo)
			.lt("started_at", oneHourAgo)
			.then((r) => ({ count: r.count ?? 0 })),
	]);

	const avgErrorsPerHour = errors24h / 23;

	if (avgErrorsPerHour > 0 && errorsLastHour > avgErrorsPerHour * 2) {
		breaches.push({
			metric: "Error Rate Spike",
			current: errorsLastHour,
			baseline: Math.round(avgErrorsPerHour * 100) / 100,
			detail: `${errorsLastHour} failures in last 1h vs ${avgErrorsPerHour.toFixed(1)}/h average (24h)`,
		});
	} else if (errorsLastHour >= 5 && avgErrorsPerHour === 0) {
		breaches.push({
			metric: "Error Rate Spike",
			current: errorsLastHour,
			baseline: 0,
			detail: `${errorsLastHour} failures in last 1h with no recent failure history`,
		});
	}

	// ---- 2. Feature usage comparison ----
	const yesterdaySameHourStart = new Date(now.getTime() - 24 * 60 * 60 * 1000);
	yesterdaySameHourStart.setUTCMinutes(0, 0, 0);
	const yesterdaySameHourEnd = new Date(
		yesterdaySameHourStart.getTime() + 60 * 60 * 1000,
	);

	const [{ count: usageLastHour }, { count: usageYesterday }] =
		await Promise.all([
			supabase
				.from("feature_usage")
				.select("*", { count: "exact", head: true })
				.gte("created_at", oneHourAgo)
				.then((r: { count: number | null }) => ({ count: r.count ?? 0 })),
			supabase
				.from("feature_usage")
				.select("*", { count: "exact", head: true })
				.gte("created_at", yesterdaySameHourStart.toISOString())
				.lt("created_at", yesterdaySameHourEnd.toISOString())
				.then((r: { count: number | null }) => ({ count: r.count ?? 0 })),
		]);

	if (usageYesterday > 10 && usageLastHour < usageYesterday * 0.8) {
		const dropPct = Math.round((1 - usageLastHour / usageYesterday) * 100);
		breaches.push({
			metric: "Feature Usage Drop",
			current: usageLastHour,
			baseline: usageYesterday,
			detail: `${dropPct}% drop: ${usageLastHour} events vs ${usageYesterday} same hour yesterday`,
		});
	}

	// ---- 3. Sync health (cohort-aware) ----
	// Only hot + warm cohorts are expected to sync within 6h.
	// Cold (12h) and dormant (24h) cohorts sync less frequently by design.
	const sixHoursAgo = new Date(
		now.getTime() - 6 * 60 * 60 * 1000,
	).toISOString();

	const [
		{ count: expectedThreads },
		{ count: syncedThreads },
		{ count: expectedIg },
		{ count: syncedIg },
	] = await Promise.all([
		// Expected: only hot + warm accounts (cohort threshold ≤ 4h)
		supabase
			.from("accounts")
			.select("*", { count: "exact", head: true })
			.not("threads_access_token_encrypted", "is", null)
			.in("sync_cohort", ["hot", "warm"])
			.then((r) => ({ count: r.count ?? 0 })),
		supabase
			.from("accounts")
			.select("*", { count: "exact", head: true })
			.not("threads_access_token_encrypted", "is", null)
			.in("sync_cohort", ["hot", "warm"])
			.gte("last_synced_at", sixHoursAgo)
			.then((r) => ({ count: r.count ?? 0 })),
		supabase
			.from("instagram_accounts")
			.select("*", { count: "exact", head: true })
			.not("instagram_access_token_encrypted", "is", null)
			.in("sync_cohort", ["hot", "warm"])
			.then((r) => ({ count: r.count ?? 0 })),
		supabase
			.from("instagram_accounts")
			.select("*", { count: "exact", head: true })
			.not("instagram_access_token_encrypted", "is", null)
			.in("sync_cohort", ["hot", "warm"])
			.gte("last_synced_at", sixHoursAgo)
			.then((r) => ({ count: r.count ?? 0 })),
	]);

	const totalExpected = expectedThreads + expectedIg;
	const syncedAccounts = syncedThreads + syncedIg;

	// Only alert if hot+warm accounts aren't syncing (cold/dormant are intentionally slower)
	if (totalExpected > 0 && syncedAccounts < totalExpected * 0.5) {
		const pct = Math.round((syncedAccounts / totalExpected) * 100);
		breaches.push({
			metric: "Sync Health Degraded",
			current: syncedAccounts,
			baseline: totalExpected,
			detail: `Only ${pct}% of hot+warm accounts synced in last 6h (${syncedAccounts}/${totalExpected})`,
		});
	}

	// ---- Alert or update baselines ----
	if (breaches.length > 0) {
		const fields = breaches.map(
			(b) =>
				`**${b.metric}**\n${b.detail}\nCurrent: ${b.current} | Baseline: ${b.baseline}`,
		);
		await alert(AlertLevel.WARN, "Deploy Impact Alert", {
			breaches: fields.join("\n\n"),
			timestamp: now.toISOString(),
			action: "Check latest deploy — something may have broken",
		});
		logger.warn("Deploy impact breaches detected", { breaches });
	} else {
		try {
			const redis = getRedis();
			const baselines = {
				errorRate24hAvg: avgErrorsPerHour,
				featureUsageSameHour: usageLastHour,
				totalAccounts: totalExpected,
				updatedAt: now.toISOString(),
			};
			await redis.set("deploy:baselines", JSON.stringify(baselines), {
				ex: 86400,
			});
		} catch (err) {
			logger.debug("Failed to update deploy baselines in Redis", {
				error: String(err),
			});
		}
		logger.info("Deploy impact check passed, baselines updated");
	}

	return { ran: true, breachCount: breaches.length, breaches };
}

// ============================================================================
// Phase 0: Zombie Cleanup — mark stale "running" rows as "error"
// Runs every invocation (fast: single UPDATE). Safe threshold is 10 min
// since max Vercel cron duration is 300s.
// ============================================================================

async function runZombieCleanup(
	supabase: ReturnType<typeof getSupabase>,
): Promise<{ recovered: number }> {
	const { data, error } = await supabase
		.from("cron_runs")
		.update({
			status: "error",
			finished_at: new Date().toISOString(),
			error:
				"Orphaned: Vercel function timed out. Auto-recovered by health-monitor.",
		})
		.eq("status", "running")
		.lt("started_at", new Date(Date.now() - 10 * 60 * 1000).toISOString())
		.select("job_name");

	if (error) {
		logger.warn("[health-monitor] Zombie cleanup query failed", {
			error: error.message,
		});
		return { recovered: 0 };
	}

	const recovered = data?.length ?? 0;
	if (recovered > 0) {
		logger.warn("[health-monitor] Recovered zombie cron_runs rows", {
			recovered,
			jobs: data?.map((r: { job_name: string }) => r.job_name),
		});
	}
	return { recovered };
}

// ============================================================================
// Phase 2: Crisis Check
// ============================================================================

async function runCrisisCheck(
	supabase: ReturnType<typeof getSupabase>,
	startTime: number,
): Promise<PhaseResult> {
	let crisisCount = 0;

	// Get all accounts with their user_ids
	const { data: accounts } = await supabase
		.from("accounts")
		.select("id, user_id, username");

	const { data: igAccounts } = await supabase
		.from("instagram_accounts")
		.select("id, user_id, username");

	const allAccounts = [
		...(accounts || []).map((a) => ({ ...a, platform: "threads" })),
		...(igAccounts || []).map((a) => ({ ...a, platform: "instagram" })),
	];

	// Check last 48h posts
	const cutoff48h = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();

	for (const account of allAccounts) {
		// Check time budget before each account
		if (!hasTimeBudget(startTime, 30000)) {
			logger.warn(
				"[health-monitor] Crisis check stopping early — time budget exhausted",
				{
					processedAccounts: allAccounts.indexOf(account),
					totalAccounts: allAccounts.length,
				},
			);
			break;
		}

		try {
			// Get recent posts
			const { data: posts } = await supabase
				.from("posts")
				.select(
					"id, account_id, content, published_at, views_count, likes_count, replies_count",
				)
				.eq("account_id", account.id)
				.gte("published_at", cutoff48h)
				.eq("status", "published");

			if (!posts?.length) continue;

			for (const post of posts) {
				let negativeCount = 0;
				let toxicCount = 0;
				let totalCount = 0;

				if (account.platform === "instagram") {
					const { data: comments } = await supabase
						.from("ig_comments")
						.select("id, sentiment")
						.eq("media_id", post.id);

					if (comments?.length) {
						totalCount = comments.length;
						for (const c of comments as unknown as {
							id: string;
							sentiment: string | null;
						}[]) {
							if (c.sentiment === "negative") negativeCount++;
							if (c.sentiment === "toxic") toxicCount++;
						}
					}
				}

				if (account.platform === "threads") {
					const { data: replies } = await getSupabaseAny()
						.from("threads_webhook_events")
						.select("id, payload")
						.eq("account_id", account.id)
						.eq("event_type", "reply")
						.eq("status", "processed");

					const postReplies = (
						(replies || []) as unknown as {
							payload?: Record<string, unknown> | undefined;
						}[]
					).filter(
						(r) =>
							r.payload?.post_id === post.id || r.payload?.media_id === post.id,
					);

					if (postReplies.length) {
						totalCount += postReplies.length;
						for (const r of postReplies) {
							if (
								(r.payload as Record<string, unknown>)?.sentiment === "negative"
							)
								negativeCount++;
							if ((r.payload as Record<string, unknown>)?.sentiment === "toxic")
								toxicCount++;
						}
					}
				}

				if (totalCount === 0) continue;

				const negativeRatio = negativeCount / totalCount;
				const toxicRatio = toxicCount / totalCount;

				// #550: Adaptive thresholds — require more responses on small accounts
				// to avoid false positives from 1-2 negative comments
				const minToxicCount = Math.max(3, Math.ceil(totalCount * 0.1));
				const minNegativeCount = Math.max(5, Math.ceil(totalCount * 0.15));

				// Check triggers
				let triggerReason: string | null = null;
				let severity: "warning" | "severe" = "warning";

				if (toxicRatio > 0.15 && toxicCount >= minToxicCount) {
					triggerReason = "toxic_surge";
					severity = "severe";
				} else if (negativeRatio > 0.3 && negativeCount >= minNegativeCount) {
					triggerReason = "negative_spike";
					severity = negativeRatio > 0.5 ? "severe" : "warning";
				}

				if (triggerReason) {
					// Check if crisis already exists for this post
					const { data: existing } = await supabase
						.from("crisis_events")
						.select("id")
						.eq("post_id", post.id)
						.is("resolved_at", null)
						.limit(1);

					if (existing?.length) continue; // Already tracked

					// Insert crisis event
					await supabase.from("crisis_events").insert({
						user_id: account.user_id,
						post_id: post.id,
						severity,
						trigger_reason: triggerReason,
						negative_count: negativeCount,
						total_count: totalCount,
						negative_ratio: negativeRatio,
					});

					// Notify user
					await createNotification({
						userId: account.user_id,
						type: "crisis_alert",
						title: `Crisis Alert: ${severity === "severe" ? "SEVERE" : "Warning"}`,
						message: `${triggerReason === "toxic_surge" ? "Toxic content surge" : "Negative sentiment spike"} detected on a recent post (${negativeCount}/${totalCount} negative)`,
						data: { postId: post.id, severity, triggerReason },
					});

					crisisCount++;
				}
			}

			// Auto-resolve: check active crises with improved ratios
			const { data: activeCrises } = await supabase
				.from("crisis_events")
				.select("id, post_id")
				.eq("user_id", account.user_id)
				.is("resolved_at", null);

			for (const crisis of activeCrises || []) {
				if (!crisis.post_id) continue;

				let currentNeg = 0;
				let currentTotal = 0;

				if (account.platform === "instagram") {
					const { data: comments } = await supabase
						.from("ig_comments")
						.select("id, sentiment")
						.eq("media_id", crisis.post_id);

					currentTotal = (comments || []).length;
					currentNeg = (
						(comments || []) as unknown as { sentiment?: string | undefined }[]
					).filter(
						(c) => c.sentiment === "negative" || c.sentiment === "toxic",
					).length;
				}

				if (currentTotal > 0 && currentNeg / currentTotal < 0.15) {
					await supabase
						.from("crisis_events")
						.update({ resolved_at: new Date().toISOString() })
						.eq("id", crisis.id);
				}
			}
		} catch (err) {
			logger.error("[health-monitor] Crisis check — account check failed", {
				accountId: account.id,
				error: String(err),
			});
		}
	}

	return { ran: true, crisisCount, accountsChecked: allAccounts.length };
}

// ============================================================================
// Phase 3: Canary Check (sub-functions)
// ============================================================================

async function checkStaleAccounts(
	supabase: ReturnType<typeof getSupabase>,
): Promise<CanaryResult> {
	const cutoff = new Date(Date.now() - 36 * 60 * 60 * 1000).toISOString();

	const { count: totalCount } = await supabase
		.from("accounts")
		.select("id", { count: "exact", head: true })
		.eq("is_active", true)
		.eq("is_retired", false)
		.eq("needs_reauth", false)
		.not("threads_access_token_encrypted", "is", null);

	const { count: staleCount } = await supabase
		.from("accounts")
		.select("id", { count: "exact", head: true })
		.eq("is_active", true)
		.eq("is_retired", false)
		.eq("needs_reauth", false)
		.not("threads_access_token_encrypted", "is", null)
		.lt("last_synced_at", cutoff);

	const total = totalCount ?? 0;
	const stale = staleCount ?? 0;
	const pct = total > 0 ? (stale / total) * 100 : 0;

	return {
		metric: "Stale accounts (last_synced_at > 36h)",
		healthy: pct <= 10,
		value: `${pct.toFixed(1)}% (${stale}/${total})`,
		threshold: "<=10%",
	};
}

async function checkDailyOrchestratorRate(
	supabase: ReturnType<typeof getSupabase>,
): Promise<CanaryResult> {
	const sevenDaysAgo = new Date(
		Date.now() - 7 * 24 * 60 * 60 * 1000,
	).toISOString();

	const { data: runs } = await supabase
		.from("cron_runs")
		.select("status")
		.eq("job_name", "daily-orchestrator")
		.gte("started_at", sevenDaysAgo);

	const total = runs?.length ?? 0;
	const successes =
		runs?.filter((r: { status: string }) => r.status === "success").length ?? 0;
	const rate = total > 0 ? (successes / total) * 100 : 100;

	return {
		metric: "Daily orchestrator success rate (7-day)",
		healthy: rate >= 95,
		value: `${rate.toFixed(1)}% (${successes}/${total})`,
		threshold: ">=95%",
	};
}

async function checkWebhookLag(
	_supabase: ReturnType<typeof getSupabase>,
): Promise<CanaryResult> {
	const { getWebhookEventStats } = await import(
		"../_lib/unifiedWebhookEvent.js"
	);
	const stats = await getWebhookEventStats();

	const threadsPending = stats.threads.pending + stats.threads.failed;
	const igPending = stats.instagram.pending + stats.instagram.failed;
	const totalPending = threadsPending + igPending;
	const totalDeadLetter = stats.threads.deadLetter + stats.instagram.deadLetter;

	// Alert if dead letter queue is growing (threshold: 10+)
	if (totalDeadLetter >= 10) {
		const { alertDeadLetterThreshold } = await import("../_lib/alerting.js");
		if (stats.threads.deadLetter > 0) {
			await alertDeadLetterThreshold(
				stats.threads.deadLetter,
				"threads_webhook_events",
			);
		}
		if (stats.instagram.deadLetter > 0) {
			await alertDeadLetterThreshold(
				stats.instagram.deadLetter,
				"ig_webhook_events",
			);
		}
	}

	// --- Signature failure rate (O2) ---
	// Check the last 3 hours of Redis hourly counters set by both webhook handlers.
	let totalSigFailures = 0;
	try {
		const redis = getRedis();
		const now = Date.now();
		const hours = [0, 1, 2].map((h) =>
			new Date(now - h * 3600 * 1000).toISOString().slice(0, 13),
		);
		const counts = await Promise.all([
			...hours.map((h) => redis.get(`webhook:sig-fail:threads:${h}`)),
			...hours.map((h) => redis.get(`webhook:sig-fail:instagram:${h}`)),
		]);
		totalSigFailures = counts.reduce<number>(
			(sum, v) => sum + (v ? parseInt(String(v), 10) : 0),
			0,
		);
		if (totalSigFailures >= 20) {
			logger.warn(
				"[health-monitor] High webhook signature failure rate — possible key rotation issue or probe attack",
				{ totalSigFailures, windowHours: 3 },
			);
		}
	} catch {
		// Non-blocking — Redis may be unavailable
	}

	// --- Processing latency p95 (O3) ---
	// Use received_at / processed_at on recently-processed events to detect backlogs.
	let latencyNote = "";
	try {
		const cutoff1h = new Date(Date.now() - 60 * 60 * 1000).toISOString();
		const dbAny = getSupabaseAny();
		const rpc = dbAny.rpc.bind(dbAny) as unknown as (
			fn: string,
			args: Record<string, unknown>,
		) => Promise<{ data: unknown; error: unknown }>;
		const [threadsLatency, igLatency] = await Promise.all([
			rpc("webhook_p95_latency_seconds", {
				tbl: "threads_webhook_events",
				since: cutoff1h,
			}),
			rpc("webhook_p95_latency_seconds", {
				tbl: "ig_webhook_events",
				since: cutoff1h,
			}),
		]);
		const threadsP95 = threadsLatency.data as number | null;
		const igP95 = igLatency.data as number | null;
		if (threadsP95 !== null || igP95 !== null) {
			latencyNote = ` | p95 latency: threads=${threadsP95 ?? "n/a"}s ig=${igP95 ?? "n/a"}s`;
		}
	} catch {
		// Non-blocking — RPC may not exist yet
	}

	const issues: string[] = [];
	if (totalPending > 100) issues.push(`${totalPending} pending events`);
	if (totalSigFailures >= 20)
		issues.push(`${totalSigFailures} sig failures in 3h`);

	return {
		metric: "Webhook processing lag",
		healthy: issues.length === 0,
		value: `${totalPending} pending (threads: ${threadsPending}, ig: ${igPending}) | ${totalDeadLetter} dead-letter | ${totalSigFailures} sig-fail/3h${latencyNote}`,
		threshold: "<=100 pending, <20 sig failures/3h",
	};
}

async function checkGeminiErrorRate(): Promise<CanaryResult> {
	try {
		const redis = getRedis();
		const today = new Date().toISOString().slice(0, 10);
		const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000)
			.toISOString()
			.slice(0, 10);

		const countKeysMatching = async (pattern: string): Promise<number> => {
			let cursor: number | string = 0;
			let total = 0;
			do {
				const result = (await redis.scan(cursor as number, {
					match: pattern,
					count: 100,
				})) as [string | number, string[]];
				const [nextCursor, keys] = result;
				cursor =
					typeof nextCursor === "number"
						? nextCursor
						: parseInt(nextCursor as string, 10);
				total += keys.length;
			} while (cursor !== 0);
			return total;
		};

		const [todayCalls, yesterdayCalls, todayErrors, yesterdayErrors] =
			await Promise.all([
				countKeysMatching(`ai_cost:*:${today}`),
				countKeysMatching(`ai_cost:*:${yesterday}`),
				countKeysMatching(`ai_error:*:${today}`),
				countKeysMatching(`ai_error:*:${yesterday}`),
			]);

		const totalCalls = todayCalls + yesterdayCalls;
		const totalErrors = todayErrors + yesterdayErrors;

		const errorRate = totalCalls > 0 ? (totalErrors / totalCalls) * 100 : 0;

		return {
			metric: "Gemini error rate (24h)",
			healthy: errorRate <= 5,
			value: `${errorRate.toFixed(1)}% (${totalErrors} errors / ${totalCalls} calls)`,
			threshold: "<=5%",
		};
	} catch (err) {
		logger.warn("Failed to check Gemini error rate", { error: String(err) });
		return {
			metric: "Gemini error rate (24h)",
			healthy: true,
			value: `Unable to check: ${err instanceof Error ? err.message : String(err)}`,
			threshold: "<=5%",
		};
	}
}

async function checkWebhookSubscriptions(
	supabase: ReturnType<typeof getSupabase>,
): Promise<CanaryResult> {
	// Regression-based detection: only flag if we previously had events but they stopped.
	// Zero events on a quiet platform is normal — only a *drop* from prior activity signals
	// a broken subscription.
	const cutoff48h = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();
	const cutoff14d = new Date(
		Date.now() - 14 * 24 * 60 * 60 * 1000,
	).toISOString();

	const [
		{ count: activeIgAccounts },
		{ count: recentIgEvents },
		{ count: priorIgEvents },
	] = await Promise.all([
		supabase
			.from("instagram_accounts")
			.select("id", { count: "exact", head: true })
			.not("instagram_access_token_encrypted", "is", null)
			.then((r: { count: number | null }) => ({ count: r.count ?? 0 })),
		supabase
			.from("ig_webhook_events")
			.select("id", { count: "exact", head: true })
			.gte("created_at", cutoff48h)
			.then((r: { count: number | null }) => ({ count: r.count ?? 0 })),
		supabase
			.from("ig_webhook_events")
			.select("id", { count: "exact", head: true })
			.gte("created_at", cutoff14d)
			.lt("created_at", cutoff48h)
			.then((r: { count: number | null }) => ({ count: r.count ?? 0 })),
	]);

	const [
		{ count: activeThreadsAccounts },
		{ count: recentThreadsEvents },
		{ count: priorThreadsEvents },
	] = await Promise.all([
		supabase
			.from("accounts")
			.select("id", { count: "exact", head: true })
			.not("threads_access_token_encrypted", "is", null)
			.then((r: { count: number | null }) => ({ count: r.count ?? 0 })),
		supabase
			.from("threads_webhook_events")
			.select("id", { count: "exact", head: true })
			.gte("created_at", cutoff48h)
			.then((r: { count: number | null }) => ({ count: r.count ?? 0 })),
		supabase
			.from("threads_webhook_events")
			.select("id", { count: "exact", head: true })
			.gte("created_at", cutoff14d)
			.lt("created_at", cutoff48h)
			.then((r: { count: number | null }) => ({ count: r.count ?? 0 })),
	]);

	const issues: string[] = [];

	// Only flag as unhealthy if events STOPPED (had events in prior 14d window, now zero in 48h).
	// Zero events on a platform that never had events is not a regression.
	if (activeIgAccounts > 0 && recentIgEvents === 0 && priorIgEvents > 0) {
		issues.push(
			`IG: ${priorIgEvents} events in prior 14d but 0 in last 48h — possible subscription drop`,
		);
	}
	if (
		activeThreadsAccounts > 0 &&
		recentThreadsEvents === 0 &&
		priorThreadsEvents > 0
	) {
		issues.push(
			`Threads: ${priorThreadsEvents} events in prior 14d but 0 in last 48h — possible subscription drop`,
		);
	}

	// Log informational note when no events have ever been received (not a failure)
	if (
		activeThreadsAccounts > 0 &&
		recentThreadsEvents === 0 &&
		priorThreadsEvents === 0
	) {
		logger.info(
			"[health-monitor] Threads: no webhook events in 14d (normal for quiet accounts or console-configured webhooks)",
		);
	}
	if (activeIgAccounts > 0 && recentIgEvents === 0 && priorIgEvents === 0) {
		logger.info(
			"[health-monitor] IG: no webhook events in 14d (normal for quiet accounts)",
		);
	}

	const healthy = issues.length === 0;

	return {
		metric: "Webhook subscription health",
		healthy,
		value: healthy
			? `Active: ${activeThreadsAccounts} Threads, ${activeIgAccounts} IG | Recent: ${recentThreadsEvents} + ${recentIgEvents} events`
			: issues.join("; "),
		threshold: "No regression from prior 14d activity",
	};
}

async function checkAccountSyncFreshness(
	supabase: ReturnType<typeof getSupabase>,
): Promise<CanaryResult> {
	const { getAccountSyncHealth } = await import("../_lib/syncHealth.js");
	const report = await getAccountSyncHealth(supabase, { limitIssues: 25 });
	const critical = report.issues.filter((issue) => issue.severity === "critical");
	const warning = report.issues.filter((issue) => issue.severity === "warning");
	const actionableIssues = report.issues.filter((issue) =>
		issue.reasons.some((reason) => reason !== "webhook_regression"),
	);
	const webhookOnlyWarnings =
		report.webhookRegressionAccounts > 0 && actionableIssues.length === 0;

	return {
		metric: "Per-account sync and webhook freshness",
		healthy: report.healthy || webhookOnlyWarnings,
		value: report.healthy
			? `${report.totalAccounts} active accounts fresh`
			: webhookOnlyWarnings
				? `${report.webhookRegressionAccounts} quiet webhook account(s), but sync is fresh and credentials are valid`
			: `${report.staleSyncAccounts} stale sync, ${report.webhookRegressionAccounts} webhook regressions, ${report.missingCredentialAccounts} missing credentials (${critical.length} critical, ${warning.length} warning)`,
		threshold:
			"0 active accounts stale beyond cohort window, no actionable webhook/sync regressions, no missing credentials",
	};
}

async function checkCronFreshness(
	supabase: ReturnType<typeof getSupabase>,
): Promise<CanaryResult> {
	// Each job has its own expected freshness window based on schedule frequency.
	// Keep this in sync with vercel.json crons; tests fail if a scheduled cron is
	// missing from this freshness canary.
	const expectedJobs: Array<{ name: string; maxAgeHours: number }> = [
		{ name: "webhook-processor", maxAgeHours: 1 },
		{ name: "publish-worker", maxAgeHours: 1 }, // consolidates scheduled-posts, auto-post-worker, ig-container-publisher
		{ name: "campaign-schedule-recovery", maxAgeHours: 1 },
		{ name: "scheduler", maxAgeHours: 1 },
		{ name: "inbox-suggestions", maxAgeHours: 1 },
		{ name: "auto-reply-worker", maxAgeHours: 1 },
		{ name: "account-state-evaluator", maxAgeHours: 1 },
		{ name: "autoposter-doctor", maxAgeHours: 1 },
		{ name: "sync-orchestrator", maxAgeHours: 2 },
		{ name: "autoposter-watchdog", maxAgeHours: 2 },
		{ name: "reply-farming-worker", maxAgeHours: 2 },
		{ name: "cta-reply-worker", maxAgeHours: 2 },
		{ name: "trend-scanner", maxAgeHours: 4 }, // every 2h
		{ name: "dawn-planner", maxAgeHours: 6 }, // every 4h
		{ name: "health-monitor", maxAgeHours: 8 }, // every 4h — 8h window for buffer
		{ name: "six-hour-pipeline", maxAgeHours: 8 }, // consolidates content-pipeline, periodic-sync
		{ name: "analytics-pipeline", maxAgeHours: 26 },
		{ name: "daily-orchestrator", maxAgeHours: 26 }, // consolidates daily-maintenance, daily-intelligence, inspiration-scan, token-refresh
		{ name: "daily-orchestrator-late", maxAgeHours: 26 },
		{ name: "cost-digest", maxAgeHours: 26 },
		{ name: "auto-learning", maxAgeHours: 26 },
		{ name: "reconcile-daily", maxAgeHours: 26 },
		{ name: "overnight-brief", maxAgeHours: 26 },
		{ name: "originality-capture", maxAgeHours: 26 },
		{ name: "weekly-reports", maxAgeHours: 192 }, // 8 days
		{ name: "monthly-kpi", maxAgeHours: 792 }, // 33 days
	];

	const now = Date.now();
	const recentJobNames = new Set<string>();

	for (const job of expectedJobs) {
		const cutoff = new Date(
			now - job.maxAgeHours * 60 * 60 * 1000,
		).toISOString();
		const { data, error } = await supabase
			.from("cron_runs")
			.select("job_name")
			.eq("job_name", job.name)
			.gte("started_at", cutoff)
			.limit(1);

		if (!error && data && data.length > 0) {
			recentJobNames.add(job.name);
		}
	}
	const staleJobs = expectedJobs.filter((j) => !recentJobNames.has(j.name));

	return {
		metric: "Cron job freshness",
		healthy: staleJobs.length === 0,
		value:
			staleJobs.length === 0
				? `All ${expectedJobs.length} jobs ran within expected windows`
				: `${staleJobs.length} stale: ${staleJobs.map((j) => j.name).join(", ")}`,
		threshold: "All jobs run within their scheduled window",
	};
}

// --- Infrastructure connectivity probes ---

async function checkDbConnectivity(
	supabase: ReturnType<typeof getSupabase>,
): Promise<CanaryResult> {
	try {
		const start = Date.now();
		const { error } = await supabase.from("cron_runs").select("id").limit(1);
		const latency = Date.now() - start;
		if (error) throw error;
		return {
			metric: "Database connectivity",
			healthy: true,
			value: `OK (${latency}ms)`,
			threshold: "Responds within 5s",
		};
	} catch (err) {
		return {
			metric: "Database connectivity",
			healthy: false,
			value: `FAILED: ${err instanceof Error ? err.message : String(err)}`,
			threshold: "Responds within 5s",
		};
	}
}

async function checkRedisConnectivity(): Promise<CanaryResult> {
	try {
		const redis = getRedis();

		// Multi-probe: PING latency + read/write round-trip
		const pingStart = Date.now();
		await redis.ping();
		const pingLatency = Date.now() - pingStart;

		// Write/read probe — verifies full data path (not just control plane)
		const probeKey = "health-probe:canary";
		const probeValue = String(Date.now());
		const rwStart = Date.now();
		await redis.set(probeKey, probeValue, { ex: 60 });
		const readBack = await redis.get(probeKey);
		const rwLatency = Date.now() - rwStart;

		const dataIntegrity = String(readBack) === probeValue;
		const highLatency = pingLatency > 500 || rwLatency > 1000;

		if (!dataIntegrity) {
			return {
				metric: "Redis connectivity",
				healthy: false,
				value: `Data integrity failure: wrote ${probeValue}, read ${String(readBack)}`,
				threshold: "PING < 500ms, R/W < 1000ms, data integrity OK",
			};
		}

		return {
			metric: "Redis connectivity",
			healthy: !highLatency,
			value: `PING ${pingLatency}ms, R/W ${rwLatency}ms`,
			threshold: "PING < 500ms, R/W < 1000ms, data integrity OK",
		};
	} catch (err) {
		return {
			metric: "Redis connectivity",
			healthy: false,
			value: `FAILED: ${err instanceof Error ? err.message : String(err)}`,
			threshold: "PING < 500ms, R/W < 1000ms, data integrity OK",
		};
	}
}

async function checkQStashConnectivity(): Promise<CanaryResult> {
	const token = process.env.QSTASH_TOKEN;
	if (!token) {
		return {
			metric: "QStash connectivity",
			healthy: false,
			value: "QSTASH_TOKEN not set",
			threshold: "API responds",
		};
	}
	try {
		const start = Date.now();
		const res = await fetch("https://qstash.upstash.io/v2/topics", {
			headers: { Authorization: `Bearer ${token}` },
			signal: AbortSignal.timeout(5_000),
		});
		const latency = Date.now() - start;
		return {
			metric: "QStash connectivity",
			healthy: res.ok,
			value: res.ok ? `OK (${latency}ms)` : `HTTP ${res.status}`,
			threshold: "API responds",
		};
	} catch (err) {
		return {
			metric: "QStash connectivity",
			healthy: false,
			value: `FAILED: ${err instanceof Error ? err.message : String(err)}`,
			threshold: "API responds",
		};
	}
}

// --- Sustained failure / backlog probes ---

async function checkSyncOrchestratorHealth(
	supabase: ReturnType<typeof getSupabase>,
): Promise<CanaryResult> {
	const { data: runs } = await supabase
		.from("cron_runs")
		.select("status")
		.eq("job_name", "sync-orchestrator")
		.order("started_at", { ascending: false })
		.limit(6);

	const total = runs?.length ?? 0;
	const successes =
		runs?.filter((r: { status: string }) => r.status === "success").length ?? 0;
	const rate = total > 0 ? (successes / total) * 100 : 100;

	return {
		metric: "Sync orchestrator health (last 6 runs)",
		healthy: rate >= 50,
		value: `${rate.toFixed(0)}% success (${successes}/${total})`,
		threshold: ">=50% success rate",
	};
}

async function checkQueueBacklog(
	supabase: ReturnType<typeof getSupabase>,
): Promise<CanaryResult> {
	const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();

	const { count } = await supabase
		.from("auto_post_queue")
		.select("id", { count: "exact", head: true })
		.in("status", ["pending", "queued"])
		.lt("scheduled_for", twoHoursAgo);

	const staleCount = count ?? 0;

	return {
		metric: "Auto-post queue backlog (items pending >2h)",
		healthy: staleCount <= 50,
		value: `${staleCount} stale items`,
		threshold: "<=50 items pending >2h",
	};
}

async function sumInfraCounters(
	prefix: string,
	hours: number,
): Promise<number> {
	try {
		const redis = getRedis();
		const now = Date.now();
		const hourKeys = Array.from({ length: hours }, (_, idx) =>
			new Date(now - idx * 3600 * 1000).toISOString().slice(0, 13),
		);
		const values = await Promise.all(
			hourKeys.map((hour) => redis.get(`infra:${prefix}:${hour}`)),
		);
		return values.reduce<number>(
			(sum, value) => sum + (value ? parseInt(String(value), 10) : 0),
			0,
		);
	} catch {
		return 0;
	}
}

async function checkQueueDispatchTracking(
	supabase: ReturnType<typeof getSupabase>,
): Promise<CanaryResult> {
	const fifteenMinutesAgo = new Date(Date.now() - 15 * 60 * 1000).toISOString();
	const { count } = await supabase
		.from("auto_post_queue")
		.select("id", { count: "exact", head: true })
		.in("status", ["pending", "queued"])
		.lte("scheduled_for", fifteenMinutesAgo)
		.is("qstash_message_id", null);

	const missingCount = count ?? 0;

	return {
		metric: "Auto-post dispatch tracking",
		healthy: missingCount <= 10,
		value: `${missingCount} due items missing qstash_message_id`,
		threshold: "<=10 due items missing dispatch tracking",
	};
}

async function checkPublishLockFallbacks(): Promise<CanaryResult> {
	const fallbackCount = await sumInfraCounters("publish-lock-db-fallback", 6);
	return {
		metric: "Publish lock fallback usage (6h)",
		healthy: fallbackCount <= 10,
		value: `${fallbackCount} DB fallback lock acquisitions`,
		threshold: "<=10 DB fallback lock acquisitions",
	};
}

async function checkExpiredPublishLocks(
	_supabase: ReturnType<typeof getSupabase>,
): Promise<CanaryResult> {
	const { count } = await getSupabaseAny()
		.from("publish_locks")
		.select("account_id", { count: "exact", head: true })
		.lt("expires_at", new Date().toISOString());

	const expiredCount = count ?? 0;
	return {
		metric: "Expired publish locks",
		healthy: expiredCount === 0,
		value: `${expiredCount} expired DB fallback locks`,
		threshold: "0 expired fallback locks",
	};
}

async function repairExpiredTokenFlags(
	supabase: ReturnType<typeof getSupabase>,
): Promise<PhaseResult> {
	const now = new Date().toISOString();
	const [threadsResult, instagramResult] = await Promise.all([
		supabase
			.from("accounts")
			.update({
				needs_reauth: true,
				status: "needs_reauth",
				is_active: false,
				updated_at: now,
			})
			.lt("token_expires_at", now)
			.eq("needs_reauth", false)
			.select("id"),
		supabase
			.from("instagram_accounts")
			.update({
				needs_reauth: true,
				status: "needs_reauth",
				is_active: false,
				updated_at: now,
			})
			.lt("token_expires_at", now)
			.eq("needs_reauth", false)
			.select("id"),
	]);

	if (threadsResult.error || instagramResult.error) {
		throw new Error(
			[
				threadsResult.error ? `threads=${threadsResult.error.message}` : null,
				instagramResult.error
					? `instagram=${instagramResult.error.message}`
					: null,
			]
				.filter(Boolean)
				.join("; "),
		);
	}

	const threadsFixed = threadsResult.count ?? threadsResult.data?.length ?? 0;
	const instagramFixed =
		instagramResult.count ?? instagramResult.data?.length ?? 0;
	const repaired = threadsFixed + instagramFixed;

	if (repaired > 0) {
		logger.warn("[health-monitor] Repaired expired token reauth flags", {
			threadsFixed,
			instagramFixed,
		});
	}

	return {
		ran: true,
		threadsFixed,
		instagramFixed,
		repaired,
	};
}

async function checkQStashDlqRate(): Promise<CanaryResult> {
	const dlqCount = await sumInfraCounters("qstash-dlq-autopost", 24);
	return {
		metric: "Auto-post QStash DLQ rate (24h)",
		healthy: dlqCount <= 5,
		value: `${dlqCount} autopost messages exhausted retries`,
		threshold: "<=5 exhausted messages / 24h",
	};
}

async function checkThreadsTopicTagPerformance(): Promise<CanaryResult> {
	const fourteenDaysAgo = new Date(
		Date.now() - 14 * 24 * 60 * 60 * 1000,
	).toISOString();
	const { data } = await getSupabaseAny()
		.from("posts")
		.select("topic_tag, views_count")
		.eq("platform", "threads")
		.eq("status", "published")
		.gte("published_at", fourteenDaysAgo)
		.not("views_count", "is", null)
		.limit(500);

	const rows = (data || []) as Array<{
		topic_tag: string | null;
		views_count: number | null;
	}>;
	const tagged = rows.filter(
		(row) => row.topic_tag && (row.views_count ?? 0) >= 0,
	);
	const untagged = rows.filter(
		(row) => !row.topic_tag && (row.views_count ?? 0) >= 0,
	);

	const avg = (items: Array<{ views_count: number | null }>) =>
		items.length > 0
			? Math.round(
					items.reduce((sum, item) => sum + (item.views_count || 0), 0) /
						items.length,
				)
			: 0;

	const taggedAvg = avg(tagged);
	const untaggedAvg = avg(untagged);

	return {
		metric: "Threads topic-tag performance (14d)",
		healthy: true,
		value: `tagged ${taggedAvg} avg views (${tagged.length}) vs untagged ${untaggedAvg} (${untagged.length})`,
		threshold: "informational",
	};
}

async function runCanaryCheck(
	supabase: ReturnType<typeof getSupabase>,
): Promise<PhaseResult> {
	const results = await Promise.allSettled([
		checkStaleAccounts(supabase),
		checkDailyOrchestratorRate(supabase),
		checkWebhookLag(supabase),
		checkWebhookSubscriptions(supabase),
		checkAccountSyncFreshness(supabase),
		checkGeminiErrorRate(),
		checkCronFreshness(supabase),
		checkDbConnectivity(supabase),
		checkRedisConnectivity(),
		checkQStashConnectivity(),
		checkSyncOrchestratorHealth(supabase),
		checkQueueBacklog(supabase),
		checkQueueDispatchTracking(supabase),
		checkPublishLockFallbacks(),
		checkExpiredPublishLocks(supabase),
		checkQStashDlqRate(),
		checkThreadsTopicTagPerformance(),
	]);

	const metrics: CanaryResult[] = results.map((r, i) =>
		r.status === "fulfilled"
			? r.value
			: {
					metric: `Check ${i + 1}`,
					healthy: false,
					value: `Error: ${r.reason}`,
					threshold: "N/A",
				},
	);

	const unhealthy = metrics.filter((m) => !m.healthy);

	if (unhealthy.length > 0) {
		const fields: Record<string, string> = {};
		unhealthy.forEach((m) => {
			fields[`[FAIL] ${m.metric}`] = `${m.value} (threshold: ${m.threshold})`;
		});
		metrics
			.filter((m) => m.healthy)
			.forEach((m) => {
				fields[`[OK] ${m.metric}`] = m.value;
			});

		await alert(
			AlertLevel.WARN,
			`Canary Check: ${unhealthy.length} metric(s) breached`,
			fields,
		);
		logger.warn("Canary check found issues", {
			unhealthy: unhealthy.length,
			metrics,
		});

		// Auto-recovery: dispatch safe idempotent recovery runs for stale crons.
		const cronFreshness = metrics.find(
			(m) => m.metric === "Cron job freshness",
		);
		if (cronFreshness && !cronFreshness.healthy) {
			for (const jobName of ["analytics-pipeline", "monthly-kpi"]) {
				if (cronFreshness.value.includes(jobName)) {
					await dispatchCronRecovery(jobName);
				}
			}
		}
	} else {
		logger.info("Canary check passed — all metrics healthy", {
			metrics: metrics.map((m) => ({ metric: m.metric, value: m.value })),
		});
	}

	return {
		ran: true,
		metricsChecked: metrics.length,
		unhealthyCount: unhealthy.length,
		metrics: metrics.map((m) => ({
			metric: m.metric,
			healthy: m.healthy,
			value: m.value,
		})),
	};
}

async function dispatchCronRecovery(jobName: string): Promise<void> {
	try {
		const redis = getRedis();
		const recoveryKey = `${jobName}:recovery`;
		const alreadyRecovering = await redis.get(recoveryKey);
		if (alreadyRecovering) {
			logger.info(`${jobName} recovery already dispatched — skipping`);
			return;
		}

		const { getQStashClient } = await import("../_lib/qstash.js");
		const { RETRIES: R } = await import("../_lib/qstashDefaults.js");
		const qstash = getQStashClient();
		const baseUrl =
			process.env.APP_URL ||
			(process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "");
		if (!baseUrl || !process.env.CRON_SECRET) {
			logger.warn(`Cannot dispatch ${jobName} recovery — missing route config`);
			return;
		}

		await qstash.publishJSON({
			url: `${baseUrl}/api/cron/${jobName}`,
			headers: { Authorization: `Bearer ${process.env.CRON_SECRET}` },
			retries: R.BEST_EFFORT,
		});
		await redis.set(recoveryKey, "1", { ex: 21600 }); // 6h TTL
		logger.info(`${jobName} stale — dispatched recovery run via QStash`);
	} catch (recoveryErr) {
		logger.warn(`Failed to dispatch ${jobName} recovery`, {
			error: String(recoveryErr),
		});
	}
}

async function runWorkspacePausedCheck(
	supabase: ReturnType<typeof getSupabaseAny>,
): Promise<PhaseResult> {
	const pausedCutoff = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
	const signupCutoff = new Date(
		Date.now() - 7 * 24 * 60 * 60 * 1000,
	).toISOString();

	const { data, error } = await supabase
		.from("auto_post_config")
		.select("workspace_id, updated_at, workspaces!inner(created_at)")
		.eq("is_enabled", false)
		.lt("updated_at", pausedCutoff)
		.lt("workspaces.created_at", signupCutoff);

	if (error) throw error;

	const rows = (data ?? []) as Array<{
		workspace_id: string;
		updated_at: string | null;
		workspaces?: { created_at?: string | null } | null;
	}>;
	const redis = getRedis();
	let alerted = 0;
	let skippedCooldown = 0;

	for (const row of rows) {
		if (!row.updated_at) continue;

		const pausedHours = Math.floor(
			(Date.now() - new Date(row.updated_at).getTime()) / (60 * 60 * 1000),
		);
		const reminderHours = pausedHours < 7 * 24 ? 24 : 7 * 24;
		const cooldownKey = `health-monitor:workspace-paused:${row.workspace_id}`;
		const alreadyAlerted = await redis.get(cooldownKey);
		if (alreadyAlerted) {
			skippedCooldown++;
			continue;
		}

		await alert(AlertLevel.WARN, "Workspace autoposter paused", {
			workspace: row.workspace_id,
			pausedHours,
			lastToggled: row.updated_at,
			action: "Confirm this is intentional or re-enable autoposter",
		});
		await redis.set(cooldownKey, new Date().toISOString(), {
			ex: reminderHours * 60 * 60,
		});
		alerted++;
	}

	return {
		ran: true,
		checked: rows.length,
		alerted,
		skippedCooldown,
	};
}

// ============================================================================
// Main Handler
// ============================================================================

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "GET" && req.method !== "POST") {
		return res.status(405).json({ error: "Method not allowed" });
	}

	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const supabase = getSupabase();
	const startTime = Date.now();

	try {
		const lockResult = await withCronLock(
			supabase,
			JOB_NAME,
			async () => {
				return trackCronRun(supabase, JOB_NAME, async () => {
					const metadata: {
						zombieCleanup: { recovered: number; error?: string | undefined };
						deployImpact: PhaseResult;
						crisisCheck: PhaseResult;
						canaryCheck: PhaseResult;
						workspacePaused: PhaseResult;
					} = {
						zombieCleanup: { recovered: 0 },
						deployImpact: { ran: false, skippedReason: "not started" },
						crisisCheck: { ran: false, skippedReason: "not started" },
						canaryCheck: { ran: false, skippedReason: "not started" },
						workspacePaused: { ran: false, skippedReason: "not started" },
					};

					let totalItemsProcessed = 0;

					// ---- Phase 1: Deploy Impact (~5s) — EVERY invocation ----
					try {
						if (!hasTimeBudget(startTime)) {
							metadata.deployImpact = {
								ran: false,
								skippedReason: "time budget exhausted",
							};
						} else {
							logger.info("[health-monitor] Phase 1: Deploy Impact starting");
							metadata.deployImpact = await runDeployImpact(supabase);
							totalItemsProcessed +=
								(metadata.deployImpact.breachCount as number) || 0;
						}
					} catch (err) {
						logger.error("[health-monitor] Phase 1 failed", {
							error: String(err),
						});
						metadata.deployImpact = { ran: false, error: String(err) };
					}

					// ---- Phase 0: Zombie Cleanup (~1s) — EVERY invocation ----
					try {
						const zombieResult = await runZombieCleanup(supabase);
						metadata.zombieCleanup = zombieResult;
						totalItemsProcessed += zombieResult.recovered;
					} catch (err) {
						logger.error("[health-monitor] Phase 0 (zombie cleanup) failed", {
							error: String(err),
						});
						metadata.zombieCleanup = { recovered: 0, error: String(err) };
					}

					// ---- Phase 2: Crisis Check (~30-120s) — EVERY invocation ----
					try {
						if (!hasTimeBudget(startTime)) {
							metadata.crisisCheck = {
								ran: false,
								skippedReason: "time budget exhausted",
							};
						} else {
							logger.info("[health-monitor] Phase 2: Crisis Check starting");
							metadata.crisisCheck = await runCrisisCheck(supabase, startTime);
							totalItemsProcessed +=
								(metadata.crisisCheck.crisisCount as number) || 0;
						}
					} catch (err) {
						logger.error("[health-monitor] Phase 2 failed", {
							error: String(err),
						});
						metadata.crisisCheck = { ran: false, error: String(err) };
					}

					// ---- Phase 3: Canary Check (~10s) — only every 6h ----
					try {
						const shouldRunCanary = new Date().getUTCHours() % 6 === 0;
						if (!shouldRunCanary) {
							metadata.canaryCheck = {
								ran: false,
								skippedReason: "not a 6h window",
							};
						} else if (!hasTimeBudget(startTime)) {
							metadata.canaryCheck = {
								ran: false,
								skippedReason: "time budget exhausted",
							};
						} else {
							logger.info("[health-monitor] Phase 3: Canary Check starting");
							metadata.canaryCheck = await runCanaryCheck(supabase);
							totalItemsProcessed +=
								(metadata.canaryCheck.metricsChecked as number) || 0;
						}
					} catch (err) {
						logger.error("[health-monitor] Phase 3 failed", {
							error: String(err),
						});
						metadata.canaryCheck = { ran: false, error: String(err) };
					}

					// ---- Phase 4: Workspace Paused Check ----
					try {
						if (!hasTimeBudget(startTime)) {
							metadata.workspacePaused = {
								ran: false,
								skippedReason: "time budget exhausted",
							};
						} else {
							logger.info("[health-monitor] Phase 4: Workspace Paused Check");
							metadata.workspacePaused = await runWorkspacePausedCheck(
								getSupabaseAny(),
							);
							totalItemsProcessed +=
								(metadata.workspacePaused.alerted as number) || 0;
						}
					} catch (err) {
						logger.error("[health-monitor] Phase 4 failed", {
							error: String(err),
						});
						metadata.workspacePaused = { ran: false, error: String(err) };
					}

					// ---- Phase 5: Discord Hourly Ping ----
					try {
						if (hasTimeBudget(startTime)) {
							logger.info("[health-monitor] Phase 5: Discord Hourly Ping");
							const { sendHourlyPing } = await import(
								"../_lib/cron/discord-ops.js"
							);
							await sendHourlyPing();
							(metadata as Record<string, unknown>).discordPing = { ran: true };
						}
					} catch (err) {
						logger.error("[health-monitor] Phase 5 (Discord ping) failed", {
							error: String(err),
						});
						(metadata as Record<string, unknown>).discordPing = {
							ran: false,
							error: String(err),
						};
					}

					// ---- Phase 6: Milestones & Alerts ----
					try {
						if (hasTimeBudget(startTime)) {
							logger.info("[health-monitor] Phase 6: Milestones & Alerts");
							const { checkMilestonesAndAlerts } = await import(
								"../_lib/cron/discord-ops.js"
							);
							await checkMilestonesAndAlerts();
							(metadata as Record<string, unknown>).milestones = { ran: true };
						}
					} catch (err) {
						logger.error("[health-monitor] Phase 6 (milestones) failed", {
							error: String(err),
						});
						(metadata as Record<string, unknown>).milestones = {
							ran: false,
							error: String(err),
						};
					}

					// ---- Phase 7: Account Health Scoring (once per day at 6 AM UTC) ----
					try {
						const shouldScore = new Date().getUTCHours() === 6;
						if (shouldScore && hasTimeBudget(startTime)) {
							logger.info("[health-monitor] Phase 7: Account Health Scoring");
							const { computeAccountHealthScores } = await import(
								"../_lib/cron/account-health-scorer.js"
							);
							const scored = await computeAccountHealthScores();
							totalItemsProcessed += scored;
							(metadata as Record<string, unknown>).healthScoring = {
								ran: true,
								accountsScored: scored,
							};
						} else {
							(metadata as Record<string, unknown>).healthScoring = {
								ran: false,
								skippedReason: shouldScore ? "time budget" : "not 6 AM UTC",
							};
						}
					} catch (err) {
						logger.error("[health-monitor] Phase 7 (health scoring) failed", {
							error: String(err),
						});
						(metadata as Record<string, unknown>).healthScoring = {
							ran: false,
							error: String(err),
						};
					}

					// ---- Phase 6b: Portfolio Account Health (calendar matrix) ----
					try {
						if (hasTimeBudget(startTime)) {
							const { computePortfolioAccountHealth } = await import(
								"../_lib/cron/portfolio-health.js"
							);
							const computed = await computePortfolioAccountHealth();
							totalItemsProcessed += computed;
							(metadata as Record<string, unknown>).portfolioHealth = {
								ran: true,
								accountsComputed: computed,
							};
						}
					} catch (err) {
						logger.error(
							"[health-monitor] Phase 6b (portfolio health) failed",
							{
								error: String(err),
							},
						);
						(metadata as Record<string, unknown>).portfolioHealth = {
							ran: false,
							error: String(err),
						};
					}

					// ---- Phase 6c: Token expiry health signals ----
					try {
						if (hasTimeBudget(startTime)) {
							const { computeTokenExpirySignals } = await import(
								"../_lib/accountHealthSignals.js"
							);
							const computed = await computeTokenExpirySignals();
							totalItemsProcessed += computed;
							(metadata as Record<string, unknown>).tokenExpirySignals = {
								ran: true,
								accountsChecked: computed,
							};
						}
					} catch (err) {
						logger.error(
							"[health-monitor] Phase 6c (token expiry signals) failed",
							{
								error: String(err),
							},
						);
						(metadata as Record<string, unknown>).tokenExpirySignals = {
							ran: false,
							error: String(err),
						};
					}

					// ---- Phase 6d: Token reauth flag repair ----
					try {
						if (hasTimeBudget(startTime)) {
							const repaired = await repairExpiredTokenFlags(supabase);
							totalItemsProcessed += Number(repaired.repaired ?? 0);
							(metadata as Record<string, unknown>).expiredTokenRepair =
								repaired;
						}
					} catch (err) {
						logger.error(
							"[health-monitor] Phase 6d (expired token repair) failed",
							{
								error: String(err),
							},
						);
						(metadata as Record<string, unknown>).expiredTokenRepair = {
							ran: false,
							error: String(err),
						};
					}

					// ---- Phase 8: QStash DLQ Poll + Auto-Purge (every invocation) ----
					try {
						if (hasTimeBudget(startTime)) {
							logger.info("[health-monitor] Phase 8: QStash DLQ Poll");
							const token = process.env.QSTASH_TOKEN;
							if (token) {
								const dlqRes = await fetch("https://qstash.upstash.io/v2/dlq", {
									headers: { Authorization: `Bearer ${token}` },
									signal: AbortSignal.timeout(10_000),
								});
								if (dlqRes.ok) {
									const dlqData = (await dlqRes.json()) as {
										messages?:
											| Array<{
													messageId: string;
													url: string;
													body?: string | undefined;
													createdAt?: number | undefined;
											  }>
											| undefined;
									};
									const dlqMessages = dlqData?.messages ?? [];
									if (dlqMessages.length > 0) {
										// Auto-purge stale DLQ messages older than 1 hour.
										// These are orphaned retries — the posts already resolved
										// (published, failed, or rescheduled) via the normal path.
										const ONE_HOUR_MS = 60 * 60 * 1000;
										const now = Date.now();
										const staleMessages = dlqMessages.filter(
											(m) => m.createdAt && now - m.createdAt > ONE_HOUR_MS,
										);

										if (staleMessages.length > 0) {
											let purged = 0;
											for (const msg of staleMessages) {
												try {
													const delRes = await fetch(
														`https://qstash.upstash.io/v2/dlq/${msg.messageId}`,
														{
															method: "DELETE",
															headers: { Authorization: `Bearer ${token}` },
															signal: AbortSignal.timeout(5_000),
														},
													);
													if (delRes.ok) purged++;
												} catch {
													// Non-fatal — will purge next cycle
												}
											}
											logger.info(
												"[health-monitor] Auto-purged stale QStash DLQ messages",
												{
													total: dlqMessages.length,
													stale: staleMessages.length,
													purged,
												},
											);
										}

										const remaining = dlqMessages.length - staleMessages.length;
										if (remaining > 0) {
											// Alert only for fresh DLQ messages (< 1 hour old)
											logger.warn(
												"[health-monitor] QStash DLQ has fresh messages",
												{
													count: remaining,
													urls: dlqMessages
														.filter(
															(m) =>
																!m.createdAt ||
																now - m.createdAt <= ONE_HOUR_MS,
														)
														.slice(0, 5)
														.map((m) => m.url),
												},
											);
											await alert(
												AlertLevel.WARN,
												`QStash DLQ: ${remaining} message(s) stuck`,
												{
													count: String(remaining),
													sampleUrls: dlqMessages
														.filter(
															(m) =>
																!m.createdAt ||
																now - m.createdAt <= ONE_HOUR_MS,
														)
														.slice(0, 3)
														.map((m) => m.url)
														.join(", "),
												},
											);
										}
									}
									(metadata as Record<string, unknown>).qstashDlq = {
										ran: true,
										messageCount: dlqMessages.length,
									};
								} else {
									logger.warn("[health-monitor] QStash DLQ poll failed", {
										status: dlqRes.status,
									});
									(metadata as Record<string, unknown>).qstashDlq = {
										ran: false,
										error: `HTTP ${dlqRes.status}`,
									};
								}
							} else {
								(metadata as Record<string, unknown>).qstashDlq = {
									ran: false,
									skippedReason: "QSTASH_TOKEN not set",
								};
							}
						}
					} catch (err) {
						logger.error("[health-monitor] Phase 8 (QStash DLQ) failed", {
							error: String(err),
						});
						(metadata as Record<string, unknown>).qstashDlq = {
							ran: false,
							error: String(err),
						};
					}

					return {
						itemsProcessed: totalItemsProcessed,
						metadata,
					};
				});
			},
			305,
		);

		if ("skipped" in lockResult && lockResult.skipped) {
			return res.status(200).json({ skipped: true });
		}

		return res.status(200).json({
			ok: true,
			durationMs: Date.now() - startTime,
			result: (lockResult as Record<string, unknown>).result,
		});
	} catch (error) {
		logger.error("[health-monitor] Top-level failure", {
			error: String(error),
		});
		await alertCronFailure(
			JOB_NAME,
			error instanceof Error ? error.message : String(error),
		);
		return res.status(500).json({ error: "Health monitor failed" });
	}
}
