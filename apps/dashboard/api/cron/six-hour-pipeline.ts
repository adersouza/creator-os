/**
 * Six-Hour Pipeline — consolidated 6-hourly cron
 *
 * Replaces 2 separate crons:
 *   Phases 1-2: periodic-sync     (social listening + competitor post refresh)
 *   Phases 3-5: content-pipeline  (evergreen recycling + trend forecasts + health snapshots)
 *
 * Each phase has independent try/catch. Total estimated: ~12s avg, ~51s worst case.
 * Budget: 280s within 300s maxDuration.
 *
 * Schedule: every 6 hours (configured in vercel.json)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

export const config = {
	maxDuration: 300,
};

const JOB_NAME = "six-hour-pipeline";
const MAX_EXECUTION_TIME = 280_000;
const TOTAL_PHASES = 5;

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

				// ── Phase 1: Social Listening (pure DB, fastest) ──
				try {
					logger.info(
						`[${JOB_NAME}] Phase 1/${TOTAL_PHASES}: Social Listening — starting`,
					);
					const p1Start = Date.now();

					const { runSocialListening } = await import(
						"../_lib/cron/periodic-sync.js"
					);
					const result = await runSocialListening(supabase);

					phases.socialListening = {
						status: "completed",
						items_processed: result.alertsProcessed,
						phase_duration_ms: Date.now() - p1Start,
					};
					totalItems += result.alertsProcessed;
					logger.info(
						`[${JOB_NAME}] Phase 1/${TOTAL_PHASES}: Social Listening — complete`,
						{
							alertsProcessed: result.alertsProcessed,
							durationMs: Date.now() - p1Start,
						},
					);
				} catch (err) {
					const errMsg = err instanceof Error ? err.message : String(err);
					phases.socialListening = { status: "error", error: errMsg };
					logger.error(
						`[${JOB_NAME}] Phase 1/${TOTAL_PHASES}: Social Listening — failed`,
						{
							error: errMsg,
						},
					);
				}

				// ── Phase 2: Refresh Competitor Posts (external API, heavier) ──
				if (hasTimeBudget(globalStart)) {
					const remainingBudget =
						MAX_EXECUTION_TIME - (Date.now() - globalStart);
					if (remainingBudget < 30_000) {
						phases.refreshCompetitorPosts = {
							status: "skipped",
							reason: "insufficient_time_budget",
							remainingMs: remainingBudget,
						};
						logger.warn(
							`[${JOB_NAME}] Phase 2/${TOTAL_PHASES}: Skipped — insufficient time budget`,
						);
					} else {
						try {
							logger.info(
								`[${JOB_NAME}] Phase 2/${TOTAL_PHASES}: Competitor Post Refresh — starting`,
							);
							const p2Start = Date.now();

							const { runRefreshCompetitorPosts } = await import(
								"../_lib/cron/periodic-sync.js"
							);
							const result = await runRefreshCompetitorPosts(globalStart);

							phases.refreshCompetitorPosts = {
								status: "completed",
								items_processed: result.competitorsProcessed,
								total_posts_fetched: result.totalPostsFetched,
								errors: result.errors,
								phase_duration_ms: Date.now() - p2Start,
							};
							totalItems += result.competitorsProcessed;
							logger.info(
								`[${JOB_NAME}] Phase 2/${TOTAL_PHASES}: Competitor Post Refresh — complete`,
								{
									competitorsProcessed: result.competitorsProcessed,
									durationMs: Date.now() - p2Start,
								},
							);
						} catch (err) {
							const errMsg = err instanceof Error ? err.message : String(err);
							phases.refreshCompetitorPosts = {
								status: "error",
								error: errMsg,
							};
							logger.error(
								`[${JOB_NAME}] Phase 2/${TOTAL_PHASES}: Competitor Post Refresh — failed`,
								{ error: errMsg },
							);
							try {
								const { captureServerException } = await import(
									"../_lib/sentryServer.js"
								);
								await captureServerException(err, {
									cronJob: JOB_NAME,
									phase: "competitor-refresh",
								});
							} catch {
								/* best-effort */
							}
							alertCronFailure(JOB_NAME, `competitor-refresh: ${errMsg}`);
						}
					}
				}

				// ── Phase 3: Evergreen Recycling ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(
							`[${JOB_NAME}] Phase 3/${TOTAL_PHASES}: Evergreen Recycling — starting`,
						);
						const p4Start = Date.now();

						const { runEvergreenRecycling } = await import(
							"../_lib/cron/content-pipeline.js"
						);
						const result = await runEvergreenRecycling(globalStart);

						phases.evergreenRecycling = {
							status: "completed",
							items_processed: result.postsRecycled,
							errors: result.errors,
							phase_duration_ms: Date.now() - p4Start,
						};
						totalItems += result.postsRecycled;
						logger.info(
							`[${JOB_NAME}] Phase 3/${TOTAL_PHASES}: Evergreen Recycling — complete`,
							result,
						);
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.evergreenRecycling = { status: "error", error: errMsg };
						logger.error(
							`[${JOB_NAME}] Phase 3/${TOTAL_PHASES}: Evergreen Recycling — failed`,
							{ error: errMsg },
						);
						alertCronFailure(JOB_NAME, `evergreen: ${errMsg}`);
					}
				} else {
					phases.evergreenRecycling = {
						status: "skipped",
						reason: "time_budget",
					};
				}

				// ── Phase 4: Trend Forecasts ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(
							`[${JOB_NAME}] Phase 4/${TOTAL_PHASES}: Trend Forecasts — starting`,
						);
						const p5Start = Date.now();

						const { runTrendForecasts } = await import(
							"../_lib/cron/content-pipeline.js"
						);
						const result = await runTrendForecasts(globalStart);

						phases.trendForecasts = {
							status: "completed",
							items_processed: result.forecastsGenerated,
							errors: result.errors,
							phase_duration_ms: Date.now() - p5Start,
						};
						totalItems += result.forecastsGenerated;
						logger.info(
							`[${JOB_NAME}] Phase 4/${TOTAL_PHASES}: Trend Forecasts — complete`,
							result,
						);
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.trendForecasts = { status: "error", error: errMsg };
						logger.error(
							`[${JOB_NAME}] Phase 4/${TOTAL_PHASES}: Trend Forecasts — failed`,
							{
								error: errMsg,
							},
						);
						alertCronFailure(JOB_NAME, `trend-forecasts: ${errMsg}`);
					}
				} else {
					phases.trendForecasts = { status: "skipped", reason: "time_budget" };
				}

				// ── Phase 5: Account Health Snapshots ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(
							`[${JOB_NAME}] Phase 5/${TOTAL_PHASES}: Health Snapshots — starting`,
						);
						const p6Start = Date.now();

						const { computeHealthSnapshots } = await import(
							"../_lib/cron/health-snapshots.js"
						);
						const result = await computeHealthSnapshots(supabase, logger);

						phases.healthSnapshots = {
							status: "completed",
							accounts_processed: result.accountsProcessed,
							anomalies_found: result.anomaliesFound,
							phase_duration_ms: Date.now() - p6Start,
						};
						totalItems += result.accountsProcessed;
						logger.info(
							`[${JOB_NAME}] Phase 5/${TOTAL_PHASES}: Health Snapshots — complete`,
							{
								accountsProcessed: result.accountsProcessed,
								anomaliesFound: result.anomaliesFound,
								durationMs: Date.now() - p6Start,
							},
						);
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.healthSnapshots = { status: "error", error: errMsg };
						logger.error(
							`[${JOB_NAME}] Phase 5/${TOTAL_PHASES}: Health Snapshots — failed`,
							{ error: errMsg },
						);
						alertCronFailure(JOB_NAME, `health-snapshots: ${errMsg}`);
					}
				} else {
					phases.healthSnapshots = { status: "skipped", reason: "time_budget" };
				}

				metadata.totalDurationMs = Date.now() - globalStart;
				metadata.phasesCompleted = Object.values(
					phases as Record<string, { status: string }>,
				).filter((p) => p.status === "completed").length;
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
