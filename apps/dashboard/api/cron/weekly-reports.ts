// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Consolidated Weekly Reports Cron Job
 *
 * Merges three formerly separate crons into a single sequential pipeline:
 *   Phase 1 — report-delivery  (weekly/monthly email reports, heaviest)
 *   Phase 2 — weekly-recap     (personalized weekly recap emails)
 *   Phase 3 — ai-cost-report   (Discord AI cost alert, fast)
 *
 * Schedule: 0 8 * * 1 (Every Monday at 8 AM UTC)
 * Lock key: "weekly-reports"
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { alertCronFailure } from "../_lib/alerting.js";
import { trackCronRun, withCronLock } from "../_lib/cronUtils.js";
import { sendReportEmail } from "../_lib/emailService.js";
import { logger } from "../_lib/logger.js";
import type { AIReportInsights, ReportData } from "../_lib/reportTemplate.js";
import { getSupabase, getSupabaseAny } from "../_lib/supabase.js";

export const config = {
	maxDuration: 300,
};

/** Hard ceiling: 290s to stay under the 300s Vercel limit */
const MAX_EXECUTION_TIME = 290_000;

// ─── Phase result types ─────────────────────────────────────────────────────

interface PhaseResult {
	status: "success" | "error" | "skipped_time_budget";
	durationMs: number;
	error?: string | undefined;
	[key: string]: unknown;
}

interface ScheduledReportRow {
	id: string;
	user_id: string;
	name: string;
	cadence: string;
	network?: string | null | undefined;
	recipients?: unknown | undefined;
	next_run_at?: string | null | undefined;
}

type BuildWeeklyReportHtml = (data: ReportData) => string;

async function loadEmailDigestPrefs(
	userIds: string[],
): Promise<Map<string, boolean>> {
	if (userIds.length === 0) return new Map();
	const { data, error } = await getSupabaseAny()
		.from("user_settings")
		.select("user_id, setting_value")
		.eq("setting_key", "notification_email_digest")
		.in("user_id", userIds);
	if (error) {
		logger.warn("[weekly-reports] Failed to load email digest prefs", {
			error: error instanceof Error ? error.message : String(error),
		});
		return new Map();
	}
	const prefs = new Map<string, boolean>();
	for (const row of (data as Array<{ user_id: string; setting_value?: unknown }> | null) ?? []) {
		prefs.set(row.user_id, row.setting_value !== false);
	}
	return prefs;
}

// ─── Helper: check remaining time budget ────────────────────────────────────

function hasTimeBudget(startTime: number, minimumMs = 10_000): boolean {
	const elapsed = Date.now() - startTime;
	return elapsed + minimumMs < MAX_EXECUTION_TIME;
}

function startOfUtcDay(date: Date): Date {
	return new Date(
		Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()),
	);
}

function reportPeriodStart(now: Date, frequency: "weekly" | "monthly"): Date {
	if (frequency === "monthly") {
		return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
	}

	const start = startOfUtcDay(now);
	const day = start.getUTCDay();
	const daysSinceMonday = (day + 6) % 7;
	start.setUTCDate(start.getUTCDate() - daysSinceMonday);
	return start;
}

function reportPeriodKey(now: Date, frequency: "weekly" | "monthly"): string {
	const start = reportPeriodStart(now, frequency);
	return frequency === "monthly"
		? `monthly:${start.toISOString().slice(0, 7)}`
		: `weekly:${start.toISOString().slice(0, 10)}`;
}

function wasSentInReportPeriod(
	lastSentAt: unknown,
	now: Date,
	frequency: "weekly" | "monthly",
): boolean {
	if (typeof lastSentAt !== "string" || !lastSentAt) return false;
	const sentAt = new Date(lastSentAt);
	if (Number.isNaN(sentAt.getTime())) return false;
	return sentAt >= reportPeriodStart(now, frequency);
}

// ═══════════════════════════════════════════════════════════════════════════
// Handler
// ═══════════════════════════════════════════════════════════════════════════

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const supabase = getSupabase();
	const globalStart = Date.now();

	const lockResult = await withCronLock(
		supabase,
		"weekly-reports",
		async () => {
			return trackCronRun(supabase, "weekly-reports", async () => {
				const metadata: Record<string, unknown> = {};
				let totalItemsProcessed = 0;

				// ── Phase 1: report-delivery ────────────────────────────────────
				const phase1 = await runPhaseReportDelivery(globalStart);
				metadata.reportDelivery = phase1;
				if (phase1.status === "success") {
					totalItemsProcessed += (phase1.emailsSent as number) || 0;
				}

				// ── Phase 2: weekly-recap ───────────────────────────────────────
				const phase2 = await runPhaseWeeklyRecap(globalStart);
				metadata.weeklyRecap = phase2;
				if (phase2.status === "success") {
					totalItemsProcessed += (phase2.emailsSent as number) || 0;
				}

				// ── Phase 3: ai-cost-report ────────────────────────────────────
				const phase3 = await runPhaseAiCostReport(globalStart);
				metadata.aiCostReport = phase3;
				if (phase3.status === "success") {
					totalItemsProcessed += 1;
				}

				// ── Phase 4: Discord Weekly Strategy ───────────────────────────
				try {
					const { sendWeeklyStrategy } = await import(
						"../_lib/cron/discord-ops.js"
					);
					await sendWeeklyStrategy();
					metadata.discordWeeklyStrategy = { status: "success" };
				} catch (err) {
					metadata.discordWeeklyStrategy = {
						status: "error",
						error: String(err),
					};
				}

				metadata.totalDurationMs = Date.now() - globalStart;
				return { itemsProcessed: totalItemsProcessed, metadata };
			});
		},
		305,
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ success: true });
}

// ═══════════════════════════════════════════════════════════════════════════
// Phase 1 — Report Delivery (weekly/monthly email reports)
// ═══════════════════════════════════════════════════════════════════════════

async function runPhaseReportDelivery(
	globalStart: number,
): Promise<PhaseResult> {
	if (!hasTimeBudget(globalStart, 60_000)) {
		return { status: "skipped_time_budget", durationMs: 0 };
	}

	const phaseStart = Date.now();
	try {
		const count = await processReportDelivery();
		return {
			status: "success",
			durationMs: Date.now() - phaseStart,
			emailsSent: count,
		};
	} catch (err) {
		const message = err instanceof Error ? err.message : String(err);
		logger.error("[weekly-reports] Phase report-delivery failed", {
			error: message,
		});
		try {
			const { captureServerException } = await import(
				"../_lib/sentryServer.js"
			);
			await captureServerException(err, {
				cronJob: "weekly-reports",
				phase: "report-delivery",
			});
		} catch {
			/* sentry non-critical */
		}
		alertCronFailure("weekly-reports/report-delivery", message);
		return {
			status: "error",
			durationMs: Date.now() - phaseStart,
			error: message,
		};
	}
}

async function processReportDelivery(): Promise<number> {
	const supabase = getSupabase();
	const now = new Date();
	const dayOfWeek = now.getUTCDay(); // 0=Sun, 1=Mon
	const dayOfMonth = now.getUTCDate();
	const isMonday = dayOfWeek === 1;
	const isFirstOfMonth = dayOfMonth === 1;

	// Fetch all users with report_preferences enabled
	const { data: settings, error: settingsError } = await supabase
		.from("user_settings")
		.select("user_id, setting_value")
		.eq("setting_key", "report_preferences");

	if (settingsError) {
		logger.error("[weekly-reports] Failed to fetch settings", {
			error:
				settingsError instanceof Error
					? settingsError.message
					: String(settingsError),
		});
		return 0;
	}

	// Lazy import email service and template
	const { sendReportEmail } = await import("../_lib/emailService.js");
	const { buildWeeklyReportHtml } = await import("../_lib/reportTemplate.js");
	const digestPrefs = await loadEmailDigestPrefs(
		(settings ?? []).map((setting) => setting.user_id),
	);

	let sent = 0;
	let _errors = 0;

	for (const setting of settings || []) {
		const prefs = setting.setting_value as Record<string, unknown>;
		// User must be enabled AND have at least one delivery channel
		const emailDigestEnabled = digestPrefs.get(setting.user_id) !== false;
		const hasEmail =
			emailDigestEnabled && typeof prefs?.email === "string" && prefs.email;
		const hasSlack =
			typeof prefs?.slack_webhook_url === "string" &&
			(prefs.slack_webhook_url as string).startsWith(
				"https://hooks.slack.com/",
			);
		if (!prefs?.enabled || (!hasEmail && !hasSlack)) continue;

		// Check frequency
		const frequency = prefs.frequency === "monthly" ? "monthly" : "weekly";
		if (frequency === "weekly" && !isMonday) continue;
		if (frequency === "monthly" && !isFirstOfMonth) continue;

		const periodKey = reportPeriodKey(now, frequency);
		if (prefs.last_sent_period_key === periodKey) {
			logger.info("[weekly-reports] Skipping already delivered user report", {
				userId: setting.user_id,
				periodKey,
			});
			continue;
		}

		try {
			// Get user's accounts
			const { data: accounts } = await supabase
				.from("accounts")
				.select("id, username, followers_count")
				.eq("user_id", setting.user_id)
				.limit(5);

			if (!accounts || accounts.length === 0) continue;

			// Get user profile name
			const { data: profile } = await supabase
				.from("profiles")
				.select("display_name, email")
				.eq("id", setting.user_id)
				.maybeSingle();

			const userName = profile?.display_name || "there";

			// Compute period
			const periodDays = frequency === "monthly" ? 30 : 7;
			const periodStart = new Date(now);
			periodStart.setDate(periodStart.getDate() - periodDays);

			const periodLabel =
				frequency === "monthly"
					? `Monthly Report - ${now.toLocaleDateString("en-US", { month: "long", year: "numeric" })}`
					: `Weekly Report - ${periodStart.toLocaleDateString("en-US", { month: "short", day: "numeric" })} to ${now.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;

			// Get published posts in period
			const accountIds = accounts.map((a: { id: string }) => a.id);
			const { data: posts } = await supabase
				.from("posts")
				.select("content, likes_count, replies_count, views_count")
				.in("account_id", accountIds)
				.eq("status", "published")
				.gte("published_at", periodStart.toISOString())
				.order("likes_count", { ascending: false })
				.limit(20);

			const publishedPosts = posts || [];
			const totalViews = publishedPosts.reduce(
				(s: number, p: { views_count?: number | null | undefined }) =>
					s + (p.views_count || 0),
				0,
			);
			const totalLikes = publishedPosts.reduce(
				(s: number, p: { likes_count?: number | null | undefined }) =>
					s + (p.likes_count || 0),
				0,
			);
			const totalFollowers = accounts.reduce(
				(s: number, a: { followers_count?: number | null | undefined }) =>
					s + (a.followers_count || 0),
				0,
			);

			// Approximate engagement rate
			const avgEngagement =
				totalFollowers > 0 && publishedPosts.length > 0
					? (totalLikes / publishedPosts.length / totalFollowers) * 100
					: 0;

			// Follower gain from account_analytics snapshots
			let followerGain = 0;
			try {
				const periodDateKey = periodStart.toISOString().split("T")[0]!;
				const { data: oldSnapshots } = await supabase
					.from("account_analytics")
					.select("account_id, followers_count, date")
					.in("account_id", accountIds)
					.lte("date", periodDateKey)
					.order("date", { ascending: false });
				if (oldSnapshots && oldSnapshots.length > 0) {
					const latestByAccount = new Map<string, number>();
					for (const snap of oldSnapshots) {
						if (!latestByAccount.has(snap.account_id)) {
							latestByAccount.set(snap.account_id, snap.followers_count || 0);
						}
					}
					const oldTotal = Array.from(latestByAccount.values()).reduce(
						(s, v) => s + v,
						0,
					);
					followerGain = totalFollowers - oldTotal;
				}
			} catch (err) {
				logger.debug("non-critical", { error: String(err) });
			}

			// Fetch revenue data from smart links (non-critical)
			let revenueData = null;
			try {
				const { data: revRow } = await supabase.rpc(
					"get_smart_link_revenue_summary",
					{
						p_user_id: setting.user_id,
						p_days: periodDays,
					},
				);
				const row = Array.isArray(revRow) ? revRow[0] : revRow;
				if (row && (parseInt(String(row.total_clicks), 10) || 0) > 0) {
					let topLinkName: string | undefined;
					try {
						const { data: topLink } = await supabase
							.from("smart_links")
							.select("title, code")
							.eq("user_id", setting.user_id)
							.order("click_count", { ascending: false })
							.limit(1)
							.maybeSingle();
						if (topLink)
							topLinkName =
								((topLink as Record<string, unknown>).title as
									| string
									| undefined) ||
								((topLink as Record<string, unknown>).code as
									| string
									| undefined);
					} catch {
						/* optional */
					}

					revenueData = {
						totalClicks: parseInt(String(row.total_clicks), 10) || 0,
						totalConversions: parseInt(String(row.total_conversions), 10) || 0,
						totalRevenue: parseFloat(String(row.total_actual_revenue)) || 0,
						topLink: topLinkName,
					};
				}
			} catch (revErr) {
				logger.debug("Revenue data fetch failed (non-critical)", {
					error: String(revErr),
				});
			}

			// Generate AI insights for the report
			let aiInsights = null;
			try {
				aiInsights = await generateReportInsights({
					followerGain,
					totalFollowers,
					totalViews,
					avgEngagement,
					postsPublished: publishedPosts.length,
					periodDays,
				});
			} catch (aiErr) {
				logger.error("AI insights generation failed (non-critical)", {
					error: aiErr instanceof Error ? aiErr.message : String(aiErr),
				});
			}

			try {
				const reportHtml = buildWeeklyReportHtml({
					userName,
					periodLabel,
					followerGain,
					totalFollowers,
					totalViews,
					avgEngagement,
					postsPublished: publishedPosts.length,
					topPosts: publishedPosts
						.slice(0, 3)
						.map(
							(p: {
								content?: string | null | undefined;
								likes_count?: number | null | undefined;
								replies_count?: number | null | undefined;
							}) => ({
								content: p.content || "",
								likes: p.likes_count || 0,
								replies: p.replies_count || 0,
							}),
						),
					aiInsights,
					revenueData,
				});

				// Build PDF attachment (non-fatal — email sends without it on failure)
				let attachments:
					| Array<{ filename: string; content: string }>
					| undefined;
				try {
					const { buildPdfReport } = await import("../_lib/reportBuilder.js");
					const reportType: "weekly" | "monthly" =
						frequency === "monthly" ? "monthly" : "weekly";
					const pdfParams =
						accountIds.length > 1
							? {
									reportType: "consolidated" as const,
									dateRange: {
										start: periodStart.toISOString().slice(0, 10),
										end: now.toISOString().slice(0, 10),
									},
									platform: "threads" as const,
									accountIds,
								}
							: {
									reportType,
									dateRange: {
										start: periodStart.toISOString().slice(0, 10),
										end: now.toISOString().slice(0, 10),
									},
									platform: "threads" as const,
									accountId: accountIds[0],
								};
					const pdfResult = await buildPdfReport(setting.user_id, pdfParams);
					if (pdfResult.success === true) {
						attachments = [
							{
								filename: pdfResult.filename,
								content: pdfResult.pdfBuffer.toString("base64"),
							},
						];
					} else {
						logger.warn("[weekly-reports] PDF build skipped", {
							userId: setting.user_id,
							error: pdfResult.error,
						});
					}
				} catch (pdfErr) {
					logger.warn("[weekly-reports] PDF build failed (non-fatal)", {
						userId: setting.user_id,
						error: pdfErr instanceof Error ? pdfErr.message : String(pdfErr),
					});
				}

				// Email delivery (skipped when only Slack is configured)
				let emailOk = false;
				if (hasEmail) {
					const result = await sendReportEmail(
						prefs.email as string,
						`Your ${frequency === "monthly" ? "Monthly" : "Weekly"} Threads Report`,
						reportHtml,
						attachments,
					);
					if (result.success) {
						emailOk = true;
					} else {
						logger.error("Failed to send report email", {
							email: prefs.email,
							error: String(result.error),
						});
					}
				}

				// Slack delivery (non-fatal)
				let slackOk = false;
				if (hasSlack) {
					try {
						const { sendSlackReportMessage } = await import(
							"../_lib/slackNotifier.js"
						);
						const slackResult = await sendSlackReportMessage(
							prefs.slack_webhook_url as string,
							{
								periodLabel,
								totalFollowers,
								followerGain,
								totalViews,
								postsPublished: publishedPosts.length,
								avgEngagement: avgEngagement.toFixed(2),
								topPost: publishedPosts[0]
									? {
											content: String(publishedPosts[0].content || ""),
											likes: Number(publishedPosts[0].likes_count || 0),
											replies: Number(publishedPosts[0].replies_count || 0),
										}
									: undefined,
								emailRecipient: hasEmail ? (prefs.email as string) : undefined,
							},
						);
						if (slackResult.success) {
							slackOk = true;
						} else {
							logger.warn("Failed to deliver Slack report", {
								userId: setting.user_id,
								error: slackResult.error,
							});
						}
					} catch (slackErr) {
						logger.warn("Slack delivery threw (non-fatal)", {
							userId: setting.user_id,
							error:
								slackErr instanceof Error ? slackErr.message : String(slackErr),
						});
					}
				}

				if (emailOk || slackOk) {
					sent++;
					await supabase
						.from("user_settings")
						.update({
							setting_value: {
								...prefs,
								last_sent_at: now.toISOString(),
								last_sent_period_key: periodKey,
							},
						})
						.eq("user_id", setting.user_id)
						.eq("setting_key", "report_preferences");
				} else {
					_errors++;
				}
			} catch (buildSendErr) {
				const errMsg =
					buildSendErr instanceof Error
						? buildSendErr.message
						: String(buildSendErr);
				logger.error("[weekly-reports] Failed to build/send report", {
					userId: setting.user_id,
					error: errMsg,
				});
				_errors++;
			}
		} catch (err) {
			logger.error("Error processing report for user", {
				userId: setting.user_id,
				error: err instanceof Error ? err.message : String(err),
			});
			_errors++;
		}
	}

	sent += await processSavedViewReportSchedules({
		supabase,
		now,
		buildWeeklyReportHtml,
	});

	// ── Also process report_schedules table (new scheduled reports feature) ──
	try {
		// biome-ignore lint/suspicious/noExplicitAny: report_schedules not yet in generated Supabase types
		const { data: schedules } = await (supabase as any)
			.from("report_schedules")
			.select("*")
			.eq("is_active", true);

		if (schedules && schedules.length > 0) {
			for (const schedule of schedules) {
				try {
					// Check if schedule matches today
					const schedType = schedule.schedule_type;
					if (schedType === "weekly" && schedule.day_of_week !== dayOfWeek)
						continue;
					if (schedType === "monthly" && schedule.day_of_month !== dayOfMonth)
						continue;
					if (schedType !== "weekly" && schedType !== "monthly") continue;
					if (wasSentInReportPeriod(schedule.last_sent_at, now, schedType)) {
						logger.info(
							"[weekly-reports] Skipping already delivered schedule",
							{
								scheduleId: schedule.id,
								periodKey: reportPeriodKey(now, schedType),
							},
						);
						continue;
					}

					const recipients = (schedule.recipient_emails || []) as string[];
					if (recipients.length === 0) continue;

					// Get user's accounts
					const { data: schedAccounts } = await supabase
						.from("accounts")
						.select("id, username, followers_count")
						.eq("user_id", schedule.user_id)
						.limit(10);
					if (!schedAccounts || schedAccounts.length === 0) continue;

					const schedPeriodDays = schedType === "monthly" ? 30 : 7;
					const schedPeriodStart = new Date(now);
					schedPeriodStart.setDate(
						schedPeriodStart.getDate() - schedPeriodDays,
					);

					const schedAccountIds = schedAccounts.map(
						(a: { id: string }) => a.id,
					);
					const { data: schedPosts } = await supabase
						.from("posts")
						.select("content, likes_count, replies_count, views_count")
						.in("account_id", schedAccountIds)
						.eq("status", "published")
						.gte("published_at", schedPeriodStart.toISOString())
						.order("likes_count", { ascending: false })
						.limit(20);

					const sPosts = schedPosts || [];
					const sViews = sPosts.reduce(
						(s: number, p: { views_count?: number | null | undefined }) =>
							s + (p.views_count || 0),
						0,
					);
					const sFollowers = schedAccounts.reduce(
						(s: number, a: { followers_count?: number | null | undefined }) =>
							s + (a.followers_count || 0),
						0,
					);
					const sLikes = sPosts.reduce(
						(s: number, p: { likes_count?: number | null | undefined }) =>
							s + (p.likes_count || 0),
						0,
					);
					const sAvgEng =
						sFollowers > 0 && sPosts.length > 0
							? (sLikes / sPosts.length / sFollowers) * 100
							: 0;

					const sPeriodLabel =
						schedType === "monthly"
							? `Monthly Report - ${now.toLocaleDateString("en-US", { month: "long", year: "numeric" })}`
							: `Weekly Report - ${schedPeriodStart.toLocaleDateString("en-US", { month: "short", day: "numeric" })} to ${now.toLocaleDateString("en-US", { month: "short", day: "numeric" })}`;

					const reportHtml = buildWeeklyReportHtml({
						userName: schedule.client_name || "there",
						periodLabel: sPeriodLabel,
						followerGain: 0,
						totalFollowers: sFollowers,
						totalViews: sViews,
						avgEngagement: sAvgEng,
						postsPublished: sPosts.length,
						topPosts: sPosts
							.slice(0, 3)
							.map(
								(p: {
									content?: string | null | undefined;
									likes_count?: number | null | undefined;
									replies_count?: number | null | undefined;
								}) => ({
									content: p.content || "",
									likes: p.likes_count || 0,
									replies: p.replies_count || 0,
								}),
							),
						aiInsights: null,
						revenueData: null,
					});

					for (const email of recipients) {
						const result = await sendReportEmail(
							email,
							`Your ${schedType === "monthly" ? "Monthly" : "Weekly"} Report`,
							reportHtml,
						);
						if (result.success) sent++;
						else _errors++;
					}

					// Update last_sent_at
					// biome-ignore lint/suspicious/noExplicitAny: report_schedules not yet in generated types
					await (supabase as any)
						.from("report_schedules")
						.update({ last_sent_at: now.toISOString() })
						.eq("id", schedule.id);
				} catch (schedErr) {
					logger.error("[weekly-reports] Schedule processing error", {
						scheduleId: schedule.id,
						error:
							schedErr instanceof Error ? schedErr.message : String(schedErr),
					});
					_errors++;
				}
			}
		}
	} catch (schedQueryErr) {
		logger.error("[weekly-reports] Failed to query report_schedules", {
			error:
				schedQueryErr instanceof Error
					? schedQueryErr.message
					: String(schedQueryErr),
		});
	}

	return sent;
}

async function processSavedViewReportSchedules({
	supabase,
	now,
	buildWeeklyReportHtml,
}: {
	supabase: ReturnType<typeof getSupabase>;
	now: Date;
	buildWeeklyReportHtml: BuildWeeklyReportHtml;
}): Promise<number> {
	void supabase;
	void buildWeeklyReportHtml;
	let sent = 0;
	let errors = 0;

	try {
		const { data: reports, error } = await getSupabaseAny()
			.from("reports")
			.select("id, user_id, name, cadence, network, recipients, next_run_at")
			.eq("type", "scheduled")
			.eq("status", "active")
			.not("next_run_at", "is", null)
			.lte("next_run_at", now.toISOString())
			.order("next_run_at", { ascending: true })
			.limit(50);

		if (error) {
			logger.error("[weekly-reports] Failed to query saved-view reports", {
				error: error.message,
			});
			return 0;
		}

		const { sendReportById } = await import("../_lib/handlers/reports/send.js");
		for (const report of (reports || []) as ScheduledReportRow[]) {
			const result = await sendReportById({
				reportId: report.id,
				userId: report.user_id,
				markNextRun: true,
				now,
			});
			if (result.ok) {
				sent += result.delivered ?? 0;
			} else {
				errors++;
				logger.error("[weekly-reports] Saved-view report send failed", {
					reportId: report.id,
					error: result.error,
				});
			}
		}
		if (errors > 0) {
			logger.warn(
				"[weekly-reports] Saved-view report delivery finished with errors",
				{
					errors,
				},
			);
		}
		return sent;
	} catch (err) {
		logger.error("[weekly-reports] Saved-view report query failed", {
			error: err instanceof Error ? err.message : String(err),
		});
		return sent;
	}
}

/**
 * Generate AI-powered insights for the weekly report using Gemini.
 * Uses the platform API key (GEMINI_API_KEY env var) — not per-user keys.
 */
async function generateReportInsights(metrics: {
	followerGain: number;
	totalFollowers: number;
	totalViews: number;
	avgEngagement: number;
	postsPublished: number;
	periodDays: number;
}): Promise<AIReportInsights | null> {
	const apiKey = process.env.GEMINI_API_KEY;
	if (!apiKey) return null;

	// Bail before the API call if the platform daily spend cap is hit.
	const { checkDailySpendLimit, trackAICost } = await import(
		"../_lib/aiCostTracker.js"
	);
	const { allowed } = await checkDailySpendLimit();
	if (!allowed) {
		logger.warn(
			"[weekly-reports] AI insights skipped — daily spend limit reached",
		);
		return null;
	}

	const { GoogleGenAI } = await import("@google/genai");
	const { describeValue, describeEngagementRate } = await import(
		"../_lib/sanitizeForAI.js"
	);
	const client = new GoogleGenAI({ apiKey });

	const prompt = `You are a social media analytics advisor generating a concise weekly report summary.

Metrics this period (${metrics.periodDays} days):
- Follower growth: ${metrics.followerGain >= 0 ? "positive" : "negative"} (${describeValue(Math.abs(metrics.followerGain))})
- Total followers: ${describeValue(metrics.totalFollowers)}
- Total views: ${describeValue(metrics.totalViews)}
- Average engagement rate: ${describeEngagementRate(metrics.avgEngagement / 100)}
- Posts published: ${metrics.postsPublished}

Generate exactly 4 bullet points in this JSON format:
{
  "topInsight": "One key observation about the data",
  "biggestWin": "The most positive metric or achievement",
  "areaToImprove": "One specific area needing attention",
  "recommendedAction": "One concrete action for next week"
}

Keep each bullet to 1-2 sentences max. Return ONLY valid JSON.`;

	const modelId = "gemini-2.0-flash";
	const response = await client.models.generateContent({
		model: modelId,
		contents: prompt,
		config: { maxOutputTokens: 512, temperature: 0.3 },
	});

	// Attribute platform-key spend so the daily cap can enforce it next call.
	const usage = (
		response as {
			usageMetadata?: {
                				promptTokenCount?: number | undefined;
                				candidatesTokenCount?: number | undefined;
                			} | undefined;
		}
	).usageMetadata;
	if (usage) {
		trackAICost(
			"platform",
			usage.promptTokenCount ?? 0,
			usage.candidatesTokenCount ?? 0,
			modelId,
			"weekly_report_insights",
			"env_fallback",
		).catch(() => {});
	}

	const text = response.text || "";
	try {
		const cleaned = text
			.replace(/```json\n?/g, "")
			.replace(/```\n?/g, "")
			.trim();
		return JSON.parse(cleaned) as AIReportInsights;
	} catch (err) {
		logger.error("[weekly-reports] Failed to parse AI insights JSON", {
			text,
			error: String(err),
		});
		return null;
	}
}

// ═══════════════════════════════════════════════════════════════════════════
// Phase 2 — Weekly Recap (personalized recap emails)
// ═══════════════════════════════════════════════════════════════════════════

interface WeeklyStats {
	postsPublished: number;
	totalViews: number;
	totalLikes: number;
	totalEngagement: number;
	topPost: {
		id: string;
		text: string;
		views: number;
		likes: number;
		engagement_rate: number;
	} | null;
	followerChange: number;
	prevWeekViews: number;
	prevWeekLikes: number;
	prevWeekEngagement: number;
}

// ─── History-based trend data (from account_metrics_history + post_metric_history) ──

interface TrendData {
	/** e.g. "+42 followers this week (18% vs last week)" */
	followerDelta: string | null;
	/** "up" | "down" | "flat" */
	viewsTrend: "up" | "down" | "flat" | null;
	/** Top velocity post: content snippet + views in first 24h */
	topVelocityPost: { snippet: string; viewsIn24h: number } | null;
	/** Engagement rate direction over 4 weeks: "up" | "down" | "flat" */
	erTrend: "up" | "down" | "flat" | null;
	/** Account health alerts: stagnant, possible shadowban */
	healthAlerts: string[];
}

/**
 * Query account_metrics_history and post_metric_history for richer trend
 * data to include in the weekly recap email. Wrapped in try-catch so failures
 * never break existing report delivery.
 */
async function getHistoryTrendData(accountId: string): Promise<TrendData> {
	// biome-ignore lint/suspicious/noExplicitAny: table not yet in generated types
	const db = (): any => getSupabase();

	const now = new Date();
	const todayStr = now.toISOString().split("T")[0]!;
	const sevenDaysAgo = new Date(now.getTime() - 7 * 86_400_000);
	const fourteenDaysAgo = new Date(now.getTime() - 14 * 86_400_000);
	const twentyEightDaysAgo = new Date(now.getTime() - 28 * 86_400_000);
	const sevenDaysAgoStr = sevenDaysAgo.toISOString().split("T")[0]!;
	const fourteenDaysAgoStr = fourteenDaysAgo.toISOString().split("T")[0]!;
	const twentyEightDaysAgoStr = twentyEightDaysAgo.toISOString().split("T")[0]!;

	let followerDelta: string | null = null;
	let viewsTrend: "up" | "down" | "flat" | null = null;
	let topVelocityPost: TrendData["topVelocityPost"] = null;
	let erTrend: "up" | "down" | "flat" | null = null;

	try {
		// ── 1. Follower + views + ER from account_metrics_history ──────────
		// Fetch last 28 days so we can compute week-over-week AND 4-week ER trend
		const { data: historyRows } = await db()
			.from("account_metrics_history")
			.select("date, followers_count, total_views, engagement_rate")
			.eq("account_id", accountId)
			.gte("date", twentyEightDaysAgoStr)
			.lte("date", todayStr)
			.order("date", { ascending: true });

		if (historyRows && historyRows.length > 0) {
			type HistRow = {
				date: string;
				followers_count: number;
				total_views: number;
				engagement_rate: number;
			};
			const rows = historyRows as HistRow[];

			// Split into this week vs last week
			const thisWeekRows = rows.filter(
				(r) => r.date >= sevenDaysAgoStr! && r.date <= todayStr!,
			);
			const lastWeekRows = rows.filter(
				(r) => r.date >= fourteenDaysAgoStr! && r.date < sevenDaysAgoStr!,
			);

			// ── Follower delta ──
			if (thisWeekRows.length >= 2) {
				const earliest = thisWeekRows[0]!.followers_count ?? 0;
				const latest =
					thisWeekRows[thisWeekRows.length - 1]!.followers_count ?? 0;
				const weekGain = latest - earliest;

				let prevWeekGain = 0;
				if (lastWeekRows.length >= 2) {
					const prevEarliest = lastWeekRows[0]!.followers_count ?? 0;
					const prevLatest =
						lastWeekRows[lastWeekRows.length - 1]!.followers_count ?? 0;
					prevWeekGain = prevLatest - prevEarliest;
				}

				const sign = weekGain >= 0 ? "+" : "";
				if (prevWeekGain !== 0) {
					const pctVsPrev = Math.round(
						((weekGain - prevWeekGain) / Math.abs(prevWeekGain)) * 100,
					);
					const pctSign = pctVsPrev >= 0 ? "+" : "";
					followerDelta = `${sign}${weekGain} followers this week (${pctSign}${pctVsPrev}% vs last week)`;
				} else {
					followerDelta = `${sign}${weekGain} followers this week`;
				}
			}

			// ── Views trend (this week total_views delta vs last week) ──
			if (thisWeekRows.length >= 2 && lastWeekRows.length >= 2) {
				const thisWeekViewsDelta =
					(thisWeekRows[thisWeekRows.length - 1]!.total_views ?? 0) -
					(thisWeekRows[0]!.total_views ?? 0);
				const lastWeekViewsDelta =
					(lastWeekRows[lastWeekRows.length - 1]!.total_views ?? 0) -
					(lastWeekRows[0]!.total_views ?? 0);

				if (lastWeekViewsDelta === 0) {
					viewsTrend = thisWeekViewsDelta > 0 ? "up" : "flat";
				} else {
					const viewsPctChange =
						((thisWeekViewsDelta - lastWeekViewsDelta) /
							Math.abs(lastWeekViewsDelta)) *
						100;
					if (viewsPctChange > 10) viewsTrend = "up";
					else if (viewsPctChange < -10) viewsTrend = "down";
					else viewsTrend = "flat";
				}
			}

			// ── ER trend over 4 weeks ──
			// Compute average engagement_rate per week bucket
			const weekBuckets: number[][] = [[], [], [], []];
			for (const r of rows) {
				const daysDiff = Math.floor(
					(now.getTime() - new Date(r.date).getTime()) / 86_400_000,
				);
				const bucket = Math.min(Math.floor(daysDiff / 7), 3);
				weekBuckets[bucket]!.push(r.engagement_rate ?? 0);
			}

			const weekAvgs = weekBuckets.map((bucket) =>
				bucket.length > 0
					? bucket.reduce((s, v) => s + v, 0) / bucket.length
					: null,
			);

			// Compare most recent week (bucket 0) vs oldest available
			const recentER = weekAvgs[0];
			const oldestER = weekAvgs[3] ?? weekAvgs[2] ?? weekAvgs[1] ?? null;
			if (recentER !== null && oldestER !== null && oldestER > 0) {
				const erPctChange = ((recentER! - oldestER) / oldestER) * 100;
				if (erPctChange > 10) erTrend = "up";
				else if (erPctChange < -10) erTrend = "down";
				else erTrend = "flat";
			}
		}
	} catch (err) {
		logger.debug(
			"[weekly-reports] account_metrics_history query failed (non-critical)",
			{
				accountId,
				error: err instanceof Error ? err.message : String(err),
			},
		);
	}

	// ── 2. Top velocity post from post_metric_history ──────────────────
	try {
		// Get posts published this week
		const weekAgoIso = sevenDaysAgo.toISOString();
		const { data: recentPosts } = await getSupabase()
			.from("posts")
			.select("id, content")
			.eq("account_id", accountId)
			.eq("status", "published")
			.gte("published_at", weekAgoIso)
			.limit(50);

		if (recentPosts && recentPosts.length > 0) {
			const postIds = recentPosts.map((p: { id: string }) => p.id);
			const contentMap = new Map<string, string>();
			for (const p of recentPosts as {
				id: string;
				content?: string | null | undefined;
			}[]) {
				contentMap.set(p.id, (p.content || "").slice(0, 60));
			}

			// Query post_metric_history for first-24h window (20-28h)
			const { data: velocitySnaps } = await db()
				.from("post_metric_history")
				.select("post_id, hours_since_publish, views_count")
				.in("post_id", postIds)
				.gte("hours_since_publish", 20)
				.lte("hours_since_publish", 28);

			if (velocitySnaps && velocitySnaps.length > 0) {
				type VelSnap = {
					post_id: string;
					hours_since_publish: number;
					views_count: number;
				};
				const snaps = velocitySnaps as VelSnap[];

				// Pick snapshot closest to 24h per post
				const bestByPost = new Map<string, VelSnap>();
				for (const snap of snaps) {
					const existing = bestByPost.get(snap.post_id);
					if (
						!existing ||
						Math.abs(snap.hours_since_publish - 24) <
							Math.abs(existing.hours_since_publish - 24)
					) {
						bestByPost.set(snap.post_id, snap);
					}
				}

				// Find the post with highest 24h views
				let topSnap: VelSnap | null = null;
				for (const snap of bestByPost.values()) {
					if (!topSnap || snap.views_count > topSnap.views_count) {
						topSnap = snap;
					}
				}

				if (topSnap && topSnap.views_count > 0) {
					const snippet = contentMap.get(topSnap.post_id) || "(no content)";
					topVelocityPost = {
						snippet: snippet + (snippet.length >= 60 ? "\u2026" : ""),
						viewsIn24h: topSnap.views_count,
					};
				}
			}
		}
	} catch (err) {
		logger.debug(
			"[weekly-reports] post_metric_history velocity query failed (non-critical)",
			{
				accountId,
				error: err instanceof Error ? err.message : String(err),
			},
		);
	}

	// ── 4. Account health alerts ─────────────────────────────────────────
	const healthAlerts: string[] = [];
	try {
		// Stagnation: no follower growth in 7+ days with posting activity
		if (followerDelta?.includes("+0")) {
			const { count: postCount } = await getSupabase()
				.from("posts")
				.select("*", { count: "exact", head: true })
				.eq("account_id", accountId)
				.eq("status", "published")
				.gte("published_at", sevenDaysAgo.toISOString());

			if ((postCount || 0) >= 3) {
				healthAlerts.push(
					"Stagnant: Zero follower growth despite active posting. Consider a content refresh.",
				);
			}
		}

		// Shadowban risk: views down >50% with stable followers
		if (viewsTrend === "down") {
			// Re-query for exact numbers to check severity
			const thisWeekRows =
				(
					await db()
						.from("account_metrics_history")
						.select("total_views")
						.eq("account_id", accountId)
						.gte("date", sevenDaysAgoStr)
						.lte("date", todayStr)
				).data || [];
			const lastWeekRows =
				(
					await db()
						.from("account_metrics_history")
						.select("total_views")
						.eq("account_id", accountId)
						.gte("date", fourteenDaysAgoStr)
						.lt("date", sevenDaysAgoStr)
				).data || [];

			if (thisWeekRows.length > 0 && lastWeekRows.length > 0) {
				const avgThis =
					thisWeekRows.reduce(
						(s: number, r: Record<string, unknown>) =>
							s + ((r.total_views as number) || 0),
						0,
					) / thisWeekRows.length;
				const avgLast =
					lastWeekRows.reduce(
						(s: number, r: Record<string, unknown>) =>
							s + ((r.total_views as number) || 0),
						0,
					) / lastWeekRows.length;
				if (avgLast > 0 && avgThis < avgLast * 0.5) {
					const dropPct = Math.round((1 - avgThis / avgLast) * 100);
					healthAlerts.push(
						`Possible shadowban: Views dropped ${dropPct}% week-over-week. Consider pausing posting 7-14 days.`,
					);
				}
			}
		}
	} catch {
		// Non-critical — health alerts are supplementary
	}

	return { followerDelta, viewsTrend, topVelocityPost, erTrend, healthAlerts };
}

async function runPhaseWeeklyRecap(globalStart: number): Promise<PhaseResult> {
	if (!hasTimeBudget(globalStart, 30_000)) {
		return { status: "skipped_time_budget", durationMs: 0 };
	}

	const phaseStart = Date.now();
	try {
		const count = await processWeeklyRecaps(globalStart);
		return {
			status: "success",
			durationMs: Date.now() - phaseStart,
			emailsSent: count,
		};
	} catch (err) {
		const message = err instanceof Error ? err.message : String(err);
		logger.error("[weekly-reports] Phase weekly-recap failed", {
			error: message,
		});
		try {
			const { captureServerException } = await import(
				"../_lib/sentryServer.js"
			);
			await captureServerException(err, {
				cronJob: "weekly-reports",
				phase: "weekly-recap",
			});
		} catch {
			/* sentry non-critical */
		}
		alertCronFailure("weekly-reports/weekly-recap", message);
		return {
			status: "error",
			durationMs: Date.now() - phaseStart,
			error: message,
		};
	}
}

interface PostStatsRow {
	id: string;
	content?: string | null | undefined;
	views_count?: number | null | undefined;
	likes_count?: number | null | undefined;
	replies_count?: number | null | undefined;
	reposts_count?: number | null | undefined;
	shares_count?: number | null | undefined;
	engagement_rate?: number | null | undefined;
}

async function getWeeklyStats(
	accountId: string,
	_userId: string,
): Promise<WeeklyStats | null> {
	const supabase = getSupabase();
	const now = new Date();
	const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
	const twoWeeksAgo = new Date(now.getTime() - 14 * 24 * 60 * 60 * 1000);
	const weekAgoStr = weekAgo.toISOString();
	const twoWeeksAgoStr = twoWeeksAgo.toISOString();

	// Posts published this week
	const { data: posts } = await supabase
		.from("posts")
		.select(
			"id, content, views_count, likes_count, replies_count, reposts_count, shares_count, engagement_rate",
		)
		.eq("account_id", accountId)
		.eq("status", "published")
		.gte("published_at", weekAgoStr)
		.order("views_count", { ascending: false });

	if (!posts || posts.length === 0) return null;

	const typedPosts = posts as PostStatsRow[];
	const totalViews = typedPosts.reduce((s, p) => s + (p.views_count || 0), 0);
	const totalLikes = typedPosts.reduce((s, p) => s + (p.likes_count || 0), 0);
	const totalEngagement = typedPosts.reduce(
		(s, p) =>
			s +
			(p.likes_count || 0) +
			(p.replies_count || 0) +
			(p.reposts_count || 0) +
			(p.shares_count || 0),
		0,
	);

	const topPost = typedPosts[0]
		? {
				id: typedPosts[0].id,
				text: (typedPosts[0].content || "").slice(0, 80),
				views: typedPosts[0].views_count || 0,
				likes: typedPosts[0].likes_count || 0,
				engagement_rate: typedPosts[0].engagement_rate || 0,
			}
		: null;

	// Follower change from account_analytics
	const todayKey = now.toISOString().split("T")[0]!;
	const weekAgoKey = weekAgo.toISOString().split("T")[0]!;
	const { data: currentAnalytics } = await supabase
		.from("account_analytics")
		.select("followers_count")
		.eq("account_id", accountId)
		.eq("date", todayKey!)
		.maybeSingle();
	const { data: prevAnalytics } = await supabase
		.from("account_analytics")
		.select("followers_count")
		.eq("account_id", accountId)
		.eq("date", weekAgoKey!)
		.maybeSingle();

	const followerChange =
		(currentAnalytics?.followers_count || 0) -
		(prevAnalytics?.followers_count || 0);

	// Previous week stats for comparison
	const { data: prevPosts } = await supabase
		.from("posts")
		.select(
			"views_count, likes_count, replies_count, reposts_count, shares_count",
		)
		.eq("account_id", accountId)
		.eq("status", "published")
		.gte("published_at", twoWeeksAgoStr)
		.lt("published_at", weekAgoStr);

	const typedPrevPosts = (prevPosts || []) as PostStatsRow[];
	const prevWeekViews = typedPrevPosts.reduce(
		(s, p) => s + (p.views_count || 0),
		0,
	);
	const prevWeekLikes = typedPrevPosts.reduce(
		(s, p) => s + (p.likes_count || 0),
		0,
	);
	const prevWeekEngagement = typedPrevPosts.reduce(
		(s, p) =>
			s +
			(p.likes_count || 0) +
			(p.replies_count || 0) +
			(p.reposts_count || 0) +
			(p.shares_count || 0),
		0,
	);

	return {
		postsPublished: posts.length,
		totalViews,
		totalLikes,
		totalEngagement,
		topPost,
		followerChange,
		prevWeekViews,
		prevWeekLikes,
		prevWeekEngagement,
	};
}

function pctChange(current: number, previous: number): string {
	if (previous === 0) return current > 0 ? "+\u221E%" : "0%";
	const pct = Math.round(((current - previous) / previous) * 100);
	return pct >= 0 ? `+${pct}%` : `${pct}%`;
}

function escapeHtml(str: string): string {
	return str
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

/** Build the "Trends" HTML section from history table data. Returns "" if no data. */
function buildTrendsHtml(trendData?: TrendData | null): string {
	if (!trendData) return "";

	const items: string[] = [];

	if (trendData.followerDelta) {
		items.push(
			`<li style="margin:4px 0;"><strong>Followers:</strong> ${escapeHtml(trendData.followerDelta)}</li>`,
		);
	}

	if (trendData.viewsTrend) {
		const label =
			trendData.viewsTrend === "up"
				? "Views trending up vs last week"
				: trendData.viewsTrend === "down"
					? "Views trending down vs last week"
					: "Views steady vs last week";
		const color =
			trendData.viewsTrend === "up"
				? "#22c55e"
				: trendData.viewsTrend === "down"
					? "#ef4444"
					: "#666";
		items.push(
			`<li style="margin:4px 0;"><strong>Views:</strong> <span style="color:${color}">${label}</span></li>`,
		);
	}

	if (trendData.topVelocityPost) {
		items.push(
			`<li style="margin:4px 0;"><strong>Fastest post:</strong> &ldquo;${escapeHtml(trendData.topVelocityPost.snippet)}&rdquo; &mdash; ${trendData.topVelocityPost.viewsIn24h.toLocaleString()} views in first 24h</li>`,
		);
	}

	if (trendData.erTrend) {
		const erLabel =
			trendData.erTrend === "up"
				? "Engagement rate trending up over 4 weeks"
				: trendData.erTrend === "down"
					? "Engagement rate trending down over 4 weeks"
					: "Engagement rate steady over 4 weeks";
		const erColor =
			trendData.erTrend === "up"
				? "#22c55e"
				: trendData.erTrend === "down"
					? "#ef4444"
					: "#666";
		items.push(
			`<li style="margin:4px 0;"><strong>Engagement:</strong> <span style="color:${erColor}">${erLabel}</span></li>`,
		);
	}

	// Health alerts
	if (trendData.healthAlerts && trendData.healthAlerts.length > 0) {
		for (const alert of trendData.healthAlerts) {
			items.push(
				`<li style="margin:4px 0;color:#ef4444;"><strong>&#9888; Alert:</strong> ${escapeHtml(alert)}</li>`,
			);
		}
	}

	if (items.length === 0) return "";

	return `
  <div style="background:#f5f3ff;padding:16px;border-radius:12px;margin:16px 0;">
    <div style="font-size:12px;color:#666;margin-bottom:4px;">Trends</div>
    <ul style="margin:8px 0;padding-left:20px;font-size:14px;">
      ${items.join("\n      ")}
    </ul>
  </div>`;
}

function buildRecapHtml(
	username: string,
	stats: WeeklyStats,
	quickWin: string | null,
	unsubscribeUrl: string,
	trendData?: TrendData | null,
): string {
	const viewsChange = pctChange(stats.totalViews, stats.prevWeekViews);
	const likesChange = pctChange(stats.totalLikes, stats.prevWeekLikes);
	const engagementChange = pctChange(
		stats.totalEngagement,
		stats.prevWeekEngagement,
	);
	const followerSign = stats.followerChange >= 0 ? "+" : "";

	return `
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#1a1a1a;">
  <h1 style="font-size:24px;margin-bottom:4px;">Your Weekly Recap</h1>
  <p style="color:#666;margin-top:0;">Hey @${escapeHtml(username)}, here's how your week went on Juno33:</p>

  <table style="width:100%;border-collapse:collapse;margin:16px 0;">
    <tr>
      <td style="padding:12px;background:#f8f9fa;border-radius:8px;text-align:center;">
        <div style="font-size:28px;font-weight:700;">${stats.postsPublished}</div>
        <div style="font-size:12px;color:#666;">Posts Published</div>
      </td>
      <td style="padding:12px;background:#f8f9fa;border-radius:8px;text-align:center;">
        <div style="font-size:28px;font-weight:700;">${stats.totalViews.toLocaleString()}</div>
        <div style="font-size:12px;color:#666;">Views <span style="color:${stats.totalViews >= stats.prevWeekViews ? "#22c55e" : "#ef4444"}">${viewsChange}</span></div>
      </td>
      <td style="padding:12px;background:#f8f9fa;border-radius:8px;text-align:center;">
        <div style="font-size:28px;font-weight:700;">${stats.totalLikes.toLocaleString()}</div>
        <div style="font-size:12px;color:#666;">Likes <span style="color:${stats.totalLikes >= stats.prevWeekLikes ? "#22c55e" : "#ef4444"}">${likesChange}</span></div>
      </td>
    </tr>
  </table>

  <p><strong>Total Engagement:</strong> ${stats.totalEngagement.toLocaleString()} interactions <span style="color:${stats.totalEngagement >= stats.prevWeekEngagement ? "#22c55e" : "#ef4444"}">${engagementChange} vs last week</span></p>

  <p><strong>Followers:</strong> ${followerSign}${stats.followerChange}</p>

  ${
		stats.topPost
			? `
  <div style="background:#f0f7ff;padding:16px;border-radius:12px;margin:16px 0;">
    <div style="font-size:12px;color:#666;margin-bottom:4px;">Top Performing Post</div>
    <p style="margin:4px 0;font-style:italic;">"${escapeHtml(stats.topPost.text)}${stats.topPost.text.length >= 80 ? "\u2026" : ""}"</p>
    <p style="margin:4px 0;font-size:14px;color:#666;">${stats.topPost.views.toLocaleString()} views / ${stats.topPost.likes} likes / ${stats.topPost.engagement_rate.toFixed(1)}% engagement</p>
  </div>
  `
			: ""
	}

  ${
		quickWin
			? `
  <div style="background:#f0fdf4;padding:16px;border-radius:12px;margin:16px 0;">
    <div style="font-size:12px;color:#666;margin-bottom:4px;">Quick Win</div>
    <p style="margin:4px 0;">${escapeHtml(quickWin)}</p>
  </div>
  `
			: ""
	}

  ${buildTrendsHtml(trendData)}

  <p style="text-align:center;margin-top:24px;">
    <a href="https://juno33.com" style="background:#7c3aed;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600;">Open Juno33 Dashboard</a>
  </p>

  <p style="font-size:11px;color:#999;text-align:center;margin-top:32px;">
    <a href="${unsubscribeUrl}" style="color:#999;">Unsubscribe from weekly recaps</a>
  </p>
</body>
</html>`;
}

async function processWeeklyRecaps(globalStart: number): Promise<number> {
	const supabase = getSupabase();
	logger.info("[weekly-reports] Starting weekly recap email generation");

	const weekAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();

	// Get all users with published posts in the last 7 days
	const { data: activeAccounts, error: accountsError } = await supabase
		.from("posts")
		.select("account_id, accounts!inner(id, user_id, username)")
		.eq("status", "published")
		.gte("published_at", weekAgo)
		.not("account_id", "is", null);

	if (accountsError || !activeAccounts) {
		logger.error("Failed to fetch active accounts for recap", {
			error: String(accountsError),
		});
		throw new Error("Failed to fetch active accounts");
	}

	// Deduplicate by account_id
	interface RecapAccount {
		id: string;
		user_id: string;
		username: string | null;
	}
	const uniqueAccounts = new Map<string, RecapAccount>();
	for (const row of activeAccounts) {
		const acc = (row as Record<string, unknown>)
			.accounts as RecapAccount | null;
		if (acc && !uniqueAccounts.has(acc.id)) {
			uniqueAccounts.set(acc.id, acc);
		}
	}

	let emailsSent = 0;

	// Batch-fetch prefs + profiles for all unique users (was N+1: 2 queries per account)
	const allUserIds = [
		...new Set(Array.from(uniqueAccounts.values()).map((a) => a.user_id)),
	];
	const { data: allPrefs } = await getSupabaseAny()
		.from("user_preferences")
		.select("user_id, weekly_recap_unsubscribed")
		.in("user_id", allUserIds);
	const { data: allProfiles } = await supabase
		.from("profiles")
		.select("id, email")
		.in("id", allUserIds);
	const digestPrefs = await loadEmailDigestPrefs(allUserIds);

	const prefsMap = new Map<string, boolean>();
	for (const p of (allPrefs as {
		user_id: string;
		weekly_recap_unsubscribed?: boolean | undefined;
	}[]) || []) {
		if (p.weekly_recap_unsubscribed) prefsMap.set(p.user_id, true);
	}
	const profilesMap = new Map<string, string>();
	for (const p of (allProfiles as { id: string; email?: string | undefined }[]) || []) {
		if (p.email) profilesMap.set(p.id, p.email);
	}

	for (const account of Array.from(uniqueAccounts.values())) {
		// Per-account time budget: stop gracefully before Vercel timeout
		if (!hasTimeBudget(globalStart, 15_000)) {
			logger.warn("[weekly-reports] Time budget exhausted during recap loop", {
				emailsSent,
				accountsRemaining: uniqueAccounts.size - emailsSent,
			});
			break;
		}

		try {
			// Check user preferences for unsubscribe (from batch)
			if (prefsMap.get(account.user_id)) {
				logger.info("User unsubscribed from weekly recap", {
					username: account.username,
				});
				continue;
			}

			// Get user email (from batch)
			if (digestPrefs.get(account.user_id) === false) continue;
			const userEmail = profilesMap.get(account.user_id);
			if (!userEmail) continue;

			const stats = await getWeeklyStats(account.id, account.user_id);
			if (!stats) continue;

			// Get one quick win recommendation
			let quickWin: string | null = null;
			try {
				const { getLowHangingFruit } = await import(
					"../_lib/lowHangingFruit.js"
				);
				const result = await getLowHangingFruit(
					account.user_id,
					account.id,
					"threads",
				);
				if (result.recommendations.length > 0) {
					quickWin = `${result.recommendations[0]!.icon} ${result.recommendations[0]!.title}: ${result.recommendations[0]!.description}`;
				}
			} catch (err) {
				logger.warn("Failed to fetch quick win for weekly recap", {
					accountId: account.id,
					error: String(err),
				});
			}

			// Fetch trend data from history tables (non-critical — won't break email if it fails)
			let trendData: TrendData | null = null;
			try {
				trendData = await getHistoryTrendData(account.id);
			} catch (err) {
				logger.debug("Failed to fetch trend data for weekly recap", {
					accountId: account.id,
					error: err instanceof Error ? err.message : String(err),
				});
			}

			const unsubscribeUrl = `https://juno33.com/settings?unsubscribe=weekly-recap&uid=${account.user_id}`;
			const html = buildRecapHtml(
				account.username ?? "",
				stats,
				quickWin,
				unsubscribeUrl,
				trendData,
			);

			const subject = `Your weekly recap: ${stats.totalViews.toLocaleString()} views, ${stats.postsPublished} posts`;
			const result = await sendReportEmail(userEmail, subject, html);

			if (result.success) {
				emailsSent++;

				// Update last_recap_sent
				await supabase.from("user_preferences").upsert(
					{
						user_id: account.user_id,
						last_recap_sent: new Date().toISOString(),
					} as never,
					{ onConflict: "user_id" },
				);
			}
		} catch (err: unknown) {
			logger.warn("Failed to send recap for account", {
				username: account.username,
				error: err instanceof Error ? err.message : String(err),
			});
		}
	}

	logger.info("[weekly-reports] Weekly recap complete", {
		emailsSent,
		totalAccounts: uniqueAccounts.size,
	});
	return emailsSent;
}

// ═══════════════════════════════════════════════════════════════════════════
// Phase 3 — AI Cost Report (Discord webhook)
// ═══════════════════════════════════════════════════════════════════════════

interface EndpointCost {
	endpoint: string;
	costUsd: number;
	calls: number;
}

interface CostReport {
	totalCostUsd: number;
	endpointCosts: EndpointCost[];
	flashPct: number;
	proPct: number;
	topUsers: { userId: string; calls: number }[];
	cacheHitRate: number | null;
	period: string;
}

async function runPhaseAiCostReport(globalStart: number): Promise<PhaseResult> {
	if (!hasTimeBudget(globalStart, 15_000)) {
		return { status: "skipped_time_budget", durationMs: 0 };
	}

	const phaseStart = Date.now();
	try {
		const report = await generateCostReport();
		await sendDiscordReport(report);
		logger.info("[weekly-reports] AI cost report sent", {
			totalCost: report.totalCostUsd.toFixed(4),
		});
		return {
			status: "success",
			durationMs: Date.now() - phaseStart,
			totalCostUsd: report.totalCostUsd,
		};
	} catch (err) {
		const message = err instanceof Error ? err.message : String(err);
		logger.error("[weekly-reports] Phase ai-cost-report failed", {
			error: message,
		});
		try {
			const { captureServerException } = await import(
				"../_lib/sentryServer.js"
			);
			await captureServerException(err, {
				cronJob: "weekly-reports",
				phase: "ai-cost-report",
			});
		} catch {
			/* sentry non-critical */
		}
		alertCronFailure("weekly-reports/ai-cost-report", message);
		return {
			status: "error",
			durationMs: Date.now() - phaseStart,
			error: message,
		};
	}
}

async function generateCostReport(): Promise<CostReport> {
	const { getRedis } = await import("../_lib/redis.js");
	const redis = getRedis();

	// Scan for ai_cost keys from last 7 days
	const dates: string[] = [];
	for (let i = 0; i < 7; i++) {
		const d = new Date(Date.now() - i * 24 * 60 * 60 * 1000);
		dates.push(d.toISOString().slice(0, 10));
	}

	const period = `${dates[dates.length - 1]} to ${dates[0]}`;

	// Collect per-user daily costs
	const userCosts: Record<string, number> = {};
	let totalMicroCost = 0;

	for (const date of dates) {
		const pattern = `ai_cost:*:${date}`;
		let cursor = 0;
		do {
			const [nextCursor, keys] = await redis.scan(cursor, {
				match: pattern,
				count: 100,
			});
			cursor =
				typeof nextCursor === "number"
					? nextCursor
					: parseInt(nextCursor as string, 10);

			if (keys.length > 0) {
				const values = await redis.mget<(number | null)[]>(...keys);
				keys.forEach((key: string, i: number) => {
					const val = values[i] ?? 0;
					totalMicroCost += val;

					const parts = key.split(":");
					const userId = parts[1] || "unknown";
					userCosts[userId] = (userCosts[userId] || 0) + val;
				});
			}
		} while (cursor !== 0);
	}

	// Scan for endpoint-specific costs
	const endpointCosts: Record<string, { cost: number; calls: number }> = {};
	for (const date of dates) {
		const pattern = `ai_cost_endpoint:*:${date}`;
		let cursor = 0;
		do {
			const [nextCursor, keys] = await redis.scan(cursor, {
				match: pattern,
				count: 100,
			});
			cursor =
				typeof nextCursor === "number"
					? nextCursor
					: parseInt(nextCursor as string, 10);

			if (keys.length > 0) {
				const values = await redis.mget<(string | null)[]>(...keys);
				keys.forEach((key: string, i: number) => {
					const parts = key.split(":");
					const endpoint = parts[1] || "unknown";
					if (!endpointCosts[endpoint])
						endpointCosts[endpoint] = { cost: 0, calls: 0 };
					const val = parseInt(values[i] || "0", 10);
					endpointCosts[endpoint].cost += val;
					endpointCosts[endpoint].calls++;
				});
			}
		} while (cursor !== 0);
	}

	const endpointList: EndpointCost[] = Object.entries(endpointCosts)
		.map(([endpoint, { cost, calls }]) => ({
			endpoint,
			costUsd: cost / 1_000_000,
			calls,
		}))
		.sort((a, b) => b.costUsd - a.costUsd);

	// Flash vs Pro split
	let flashCalls = 0;
	let proCalls = 0;
	for (const date of dates) {
		const flashVal = await redis.get(`ai_model_calls:flash:${date}`);
		const proVal = await redis.get(`ai_model_calls:pro:${date}`);
		flashCalls += (flashVal as number) || 0;
		proCalls += (proVal as number) || 0;
	}
	const totalModelCalls = flashCalls + proCalls;
	const flashPct =
		totalModelCalls > 0 ? (flashCalls / totalModelCalls) * 100 : 0;
	const proPct = totalModelCalls > 0 ? (proCalls / totalModelCalls) * 100 : 0;

	// Top 5 users by cost
	const topUsers = Object.entries(userCosts)
		.map(([userId, cost]) => ({ userId: userId.slice(0, 8), calls: cost }))
		.sort((a, b) => b.calls - a.calls)
		.slice(0, 5);

	// Cache hit rate — reads from the ai-cache:stats hash written by aiCache.ts
	let cacheHitRate: number | null = null;
	try {
		const stats = (await redis.hgetall("ai-cache:stats")) as Record<
			string,
			string
		> | null;
		if (stats?.hits && stats?.misses) {
			const hits = Number(stats.hits);
			const misses = Number(stats.misses);
			const total = hits + misses;
			cacheHitRate = total > 0 ? (hits / total) * 100 : null;
		}
	} catch (err) {
		logger.warn("Failed to fetch AI cache hit rate", { error: String(err) });
	}

	return {
		totalCostUsd: totalMicroCost / 1_000_000,
		endpointCosts: endpointList,
		flashPct,
		proPct,
		topUsers,
		cacheHitRate,
		period,
	};
}

async function sendDiscordReport(report: CostReport): Promise<void> {
	const webhookUrl = process.env.DISCORD_ALERT_WEBHOOK_URL;
	if (!webhookUrl) {
		logger.warn("[weekly-reports] DISCORD_ALERT_WEBHOOK_URL not set, skipping");
		return;
	}

	const fields: { name: string; value: string; inline: boolean }[] = [];

	fields.push({
		name: "Total Spend",
		value: `$${report.totalCostUsd.toFixed(4)}`,
		inline: true,
	});

	fields.push({
		name: "Period",
		value: report.period,
		inline: true,
	});

	if (report.flashPct > 0 || report.proPct > 0) {
		fields.push({
			name: "Model Split",
			value: `Flash: ${report.flashPct.toFixed(1)}% | Pro: ${report.proPct.toFixed(1)}%`,
			inline: true,
		});
	}

	if (report.endpointCosts.length > 0) {
		const endpointLines = report.endpointCosts
			.slice(0, 8)
			.map(
				(e) => `\`${e.endpoint}\`: $${e.costUsd.toFixed(4)} (${e.calls} calls)`,
			)
			.join("\n");
		fields.push({
			name: "Cost by Endpoint",
			value: endpointLines || "No endpoint data",
			inline: false,
		});
	}

	if (report.topUsers.length > 0) {
		const userLines = report.topUsers
			.map(
				(u, i) =>
					`${i + 1}. \`${u.userId}...\` — $${(u.calls / 1_000_000).toFixed(4)}`,
			)
			.join("\n");
		fields.push({
			name: "Top 5 Users by Cost",
			value: userLines,
			inline: false,
		});
	}

	if (report.cacheHitRate !== null) {
		fields.push({
			name: "Cache Hit Rate",
			value: `${report.cacheHitRate.toFixed(1)}%`,
			inline: true,
		});
	}

	const payload = {
		embeds: [
			{
				title: "Weekly AI Cost Report — Juno33",
				color: 0x3498db,
				fields,
				footer: { text: "Juno33 AI Cost Tracker" },
				timestamp: new Date().toISOString(),
			},
		],
	};

	const resp = await fetch(webhookUrl, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(payload),
		signal: AbortSignal.timeout(15000),
	});

	if (!resp.ok) {
		throw new Error(
			`Discord webhook failed: ${resp.status} ${await resp.text()}`,
		);
	}
}
