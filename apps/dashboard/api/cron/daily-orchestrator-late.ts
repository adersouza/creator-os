/**
 * Daily Orchestrator (Late) — second wave of daily tasks
 *
 * Split from daily-orchestrator to stay within Vercel's 300s maxDuration.
 * The main daily-orchestrator runs at 1:00 AM and handles core maintenance
 * + intelligence + token refresh + inspiration + shadowban scan + inbox repair.
 *
 * This handles the newer analytical/optimization phases:
 *   Phase 1: Discord Daily Report
 *   Phase 2: Collab Invite Refresh
 *   Phase 3: Comment Repair
 *   Phase 4: Content A/B Testing + Velocity Scoring
 *   Phase 5: Smart Timing (Wednesdays only)
 *   Phase 6: Content Recycling (Saturdays only)
 *   Phase 7: Shadowban Recovery Protocol
 *   Phase 8: Funnel Tracking + CTA A/B Testing
 *   Phase 9: Media Vision Tagging
 *
 * Schedule: daily at 1:30 AM UTC (configured in vercel.json)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

export const config = {
	maxDuration: 300,
};

const JOB_NAME = "daily-orchestrator-late";
const MAX_EXECUTION_TIME = 240_000; // 60s buffer for Vercel (matches main orchestrator)

function hasTimeBudget(startTime: number): boolean {
	return Date.now() - startTime < MAX_EXECUTION_TIME;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const { withCronLock, trackCronRun } = await import("../_lib/cronUtils.js");
	const { getPrivilegedSupabase, PRIVILEGED_DB_REASONS } = await import(
		"../_lib/privilegedDb.js"
	);
	const { logger } = await import("../_lib/logger.js");
	const { alertCronFailure } = await import("../_lib/alerting.js");

	const supabase = getPrivilegedSupabase(
		PRIVILEGED_DB_REASONS.cronOrchestration,
	);
	const globalStart = Date.now();

	const lockResult = await withCronLock(
		supabase,
		JOB_NAME,
		async () => {
			return trackCronRun(supabase, JOB_NAME, async () => {
				const phases: Record<string, unknown> = {};
				const metadata: Record<string, unknown> = { phases };
				let totalItems = 0;

				// ── Phase 1: Discord Daily Report ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 1: Discord Daily Report`);
						const { sendDailyReport } = await import(
							"../_lib/cron/discord-ops.js"
						);
						await sendDailyReport();
						phases.discordDailyReport = { status: "completed" };
					} catch (err) {
						const errMsg = String(err);
						phases.discordDailyReport = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 1 failed`, { error: errMsg });
						try {
							const { captureServerException } = await import(
								"../_lib/sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: JOB_NAME,
								phase: "discord-daily-report",
							});
						} catch {
							/* best-effort */
						}
					}
				}

				// ── Phase 2: Collab Invite Refresh ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 2: Collab Invite Refresh`);
						const p = Date.now();
						const { phaseCollabInviteRefresh } = await import(
							"../_lib/cron/daily-maintenance.js"
						);
						const result = await phaseCollabInviteRefresh(
							supabase,
							logger,
							globalStart,
						);
						phases.collabInviteRefresh = {
							status: "completed",
							accounts_refreshed: result.refreshed,
							invites_found: result.invites,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += result.refreshed;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.collabInviteRefresh = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 2 failed`, { error: errMsg });
						try {
							const { captureServerException } = await import(
								"../_lib/sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: JOB_NAME,
								phase: "collab-invite-refresh",
							});
						} catch {
							/* best-effort */
						}
					}
				}

				// ── Phase 3: Comment Repair ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 3: Comment Repair`);
						const p = Date.now();
						const { phaseCommentRepair } = await import(
							"../_lib/cron/daily-maintenance.js"
						);
						const result = await phaseCommentRepair(
							supabase,
							logger,
							globalStart,
						);
						phases.commentRepair = {
							status: "completed",
							accounts_processed: result.accounts,
							comments_synced: result.comments,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += result.comments;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.commentRepair = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 3 failed`, { error: errMsg });
						alertCronFailure(JOB_NAME, `comment-repair: ${errMsg}`);
						try {
							const { captureServerException } = await import(
								"../_lib/sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: JOB_NAME,
								phase: "comment-repair",
							});
						} catch {
							/* best-effort */
						}
						throw err;
					}
				}

				// ── Phase 4: Content A/B Testing + Velocity Scoring ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 4: Content A/B Testing`);
						const p = Date.now();
						const { processContentABTesting } = await import(
							"../_lib/cron/content-ab-testing.js"
						);
						const abResult = await processContentABTesting();
						phases.contentABTesting = {
							status: "completed",
							velocity_scores: abResult.velocityScores,
							ab_winner: abResult.abTest.winner,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += abResult.velocityScores;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.contentABTesting = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 4 failed`, { error: errMsg });
						try {
							const { captureServerException } = await import(
								"../_lib/sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: JOB_NAME,
								phase: "content-ab-testing",
							});
						} catch {
							/* best-effort */
						}
					}
				}

				// ── Phase 5: Smart Timing (weekly — only on Wednesdays) ──
				if (hasTimeBudget(globalStart) && new Date().getUTCDay() === 3) {
					try {
						logger.info(`[${JOB_NAME}] Phase 5: Smart Timing`);
						const p = Date.now();
						const { computeSmartTiming } = await import(
							"../_lib/cron/smart-timing.js"
						);
						const timingResult = await computeSmartTiming();
						phases.smartTiming = {
							status: "completed",
							accounts_analyzed: timingResult.accountsAnalyzed,
							overrides_written: timingResult.overridesWritten,
							anti_patterns: timingResult.antiPatternsDetected,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += timingResult.accountsAnalyzed;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.smartTiming = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 5 failed`, { error: errMsg });
						try {
							const { captureServerException } = await import(
								"../_lib/sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: JOB_NAME,
								phase: "smart-timing",
							});
						} catch {
							/* best-effort */
						}
					}
				}

				// ── Phase 6: Content Recycling (weekly — only on Saturdays) ──
				if (hasTimeBudget(globalStart) && new Date().getUTCDay() === 6) {
					try {
						logger.info(`[${JOB_NAME}] Phase 6: Content Recycling`);
						const p = Date.now();
						const { processContentRecycling } = await import(
							"../_lib/cron/content-recycler.js"
						);
						const recycleResult = await processContentRecycling();
						phases.contentRecycling = {
							status: "completed",
							candidates: recycleResult.candidatesFound,
							recycled: recycleResult.recycled,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += recycleResult.recycled;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.contentRecycling = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 6 failed`, { error: errMsg });
						try {
							const { captureServerException } = await import(
								"../_lib/sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: JOB_NAME,
								phase: "content-recycling",
							});
						} catch {
							/* best-effort */
						}
					}
				}

				// ── Phase 7: Shadowban Recovery Protocol ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 7: Shadowban Recovery`);
						const p = Date.now();
						const { processShadowbanRecovery } = await import(
							"../_lib/cron/shadowban-recovery.js"
						);
						const recoveryResult = await processShadowbanRecovery();
						phases.shadowbanRecovery = {
							status: "completed",
							in_recovery: recoveryResult.accountsInRecovery,
							recovered: recoveryResult.recovered,
							permanently_dead: recoveryResult.permanentlyDead,
							safe_posts_queued: recoveryResult.safePostsQueued,
							trigger_patterns: recoveryResult.triggerPatternsFound,
							phase_duration_ms: Date.now() - p,
						};
						totalItems +=
							recoveryResult.recovered + recoveryResult.safePostsQueued;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.shadowbanRecovery = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 7 failed`, { error: errMsg });
						alertCronFailure(JOB_NAME, `shadowban-recovery: ${errMsg}`);
						try {
							const { captureServerException } = await import(
								"../_lib/sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: JOB_NAME,
								phase: "shadowban-recovery",
							});
						} catch {
							/* best-effort */
						}
						throw err;
					}
				}

				// ── Phase 8: Funnel Tracking + CTA A/B Testing ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 8: Funnel Tracking`);
						const p = Date.now();
						const { processFunnelTracking } = await import(
							"../_lib/cron/funnel-tracker.js"
						);
						const funnelResult = await processFunnelTracking();
						phases.funnelTracking = {
							status: "completed",
							accounts_tracked: funnelResult.accountsTracked,
							posts_with_delta: funnelResult.postsWithDelta,
							top_converters: funnelResult.topConverters.length,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += funnelResult.postsWithDelta;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.funnelTracking = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 8 failed`, { error: errMsg });
						try {
							const { captureServerException } = await import(
								"../_lib/sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: JOB_NAME,
								phase: "funnel-tracking",
							});
						} catch {
							/* best-effort */
						}
					}
				}

				// ── Phase 9: Media Vision Tagging ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 9: Media Vision Tagging`);
						const p = Date.now();
						const { backfillMediaDescriptions } = await import(
							"../_lib/mediaVision.js"
						);
						const visionResult = await backfillMediaDescriptions(30);
						phases.mediaVisionTagging = {
							status: "completed",
							analyzed: visionResult.analyzed,
							skipped: visionResult.skipped,
							errors: visionResult.errors,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += visionResult.analyzed;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.mediaVisionTagging = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 9 failed`, { error: errMsg });
						try {
							const { captureServerException } = await import(
								"../_lib/sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: JOB_NAME,
								phase: "media-vision-tagging",
							});
						} catch {
							/* best-effort */
						}
					}
				}

				metadata.totalDurationMs = Date.now() - globalStart;
				metadata.phasesCompleted = Object.values(
					phases as Record<string, { status: string }>,
				).filter(
					(p) => p.status === "completed" || p.status === "success",
				).length;
				metadata.phasesErrored = Object.values(
					phases as Record<string, { status: string }>,
				).filter((p) => p.status === "error").length;

				return { itemsProcessed: totalItems, metadata };
			});
		},
		305,
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ ok: true });
}
