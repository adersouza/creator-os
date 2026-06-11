/**
 * Auto-Learning Cron Job
 *
 * Phase 1: Analyzes post performance from the past week, extracts winning/losing
 * patterns via AI, and updates each group's content strategy tone_notes.
 *
 * Phase 2: Account retirement scan — permanently removes dead accounts (10+ posts,
 * 0 views) from all autoposter groups. Discord report for replacements.
 *
 * Schedule: 0 6 * * * (Every day at 6 AM UTC — changed from weekly to daily)
 * Lock key: "auto-learning"
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { alertCronFailure } from "../_lib/alerting.js";
import { trackCronRun, withCronLock } from "../_lib/cronUtils.js";
import { logger } from "../_lib/logger.js";
import { getSupabase, getSupabaseAny } from "../_lib/supabase.js";

export const config = {
	maxDuration: 300,
};

const MAX_EXECUTION_TIME = 290_000;

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const supabase = getSupabase();
	const looseDb = getSupabaseAny();
	const globalStart = Date.now();

	function hasTimeBudget(): boolean {
		return Date.now() - globalStart < MAX_EXECUTION_TIME;
	}

	const lockResult = await withCronLock(
		supabase,
		"auto-learning",
		async () => {
			return trackCronRun(supabase, "auto-learning", async () => {
				// ── Phase 1: Auto-learning (content strategy updates) ──
				let phase1Result = {
					groupsProcessed: 0,
					toneNotesUpdated: 0,
					feedbackRatings: 0,
					groupResults: [] as unknown[],
				};
				try {
					const { processAutoLearning } = await import(
						"../_lib/cron/auto-learning.js"
					);
					phase1Result = await processAutoLearning();
					logger.info("[auto-learning] Phase 1 completed", {
						groupsProcessed: phase1Result.groupsProcessed,
						toneNotesUpdated: phase1Result.toneNotesUpdated,
						feedbackRatings: phase1Result.feedbackRatings,
					});
				} catch (err) {
					const message = err instanceof Error ? err.message : String(err);
					logger.error("[auto-learning] Phase 1 failed", { error: message });
					try {
						const { captureServerException } = await import(
							"../_lib/sentryServer.js"
						);
						await captureServerException(err, {
							cronJob: "auto-learning",
							phase: 1,
						});
					} catch {
						/* sentry non-critical */
					}
					alertCronFailure("auto-learning", message);
				}

				// ── Phase 2: Account retirement scan (independent of Phase 1) ──
				let retirementResult = {
					retired: [] as unknown[],
					totalScanned: 0,
					groupsUpdated: 0,
				};
				if (!hasTimeBudget()) {
					logger.warn(
						"[auto-learning] Skipping Phase 2 — time budget exhausted",
					);
				} else {
					try {
						const { processAccountRetirement } = await import(
							"../_lib/cron/account-retirement.js"
						);
						retirementResult = await processAccountRetirement();
						logger.info("[auto-learning] Phase 2 (retirement scan) completed", {
							retired: retirementResult.retired.length,
							scanned: retirementResult.totalScanned,
							groupsUpdated: retirementResult.groupsUpdated,
						});
					} catch (retireErr) {
						const retireMsg =
							retireErr instanceof Error
								? retireErr.message
								: String(retireErr);
						logger.error("[auto-learning] Phase 2 (retirement scan) failed", {
							error: retireMsg,
						});
					}
				}

				// ── Phase 3: Per-account content type feedback loop ──
				let contentTypeUpdates = 0;
				if (!hasTimeBudget()) {
					logger.warn(
						"[auto-learning] Skipping Phase 3 — time budget exhausted",
					);
				} else {
					try {
						// Compute top 3 content types by avg views per account (last 30 days)
						const { data: performanceData } = await looseDb
							.from("auto_post_queue")
							.select("account_id, content_type, views_at_24h")
							.eq("status", "published")
							.not("content_type", "is", null)
							.not("views_at_24h", "is", null)
							.gte(
								"posted_at",
								new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString(),
							);

						if (performanceData && performanceData.length > 0) {
							// Group by account + content_type → avg views
							const byAccount = new Map<
								string,
								Map<string, { total: number; count: number }>
							>();
							for (const row of performanceData as Array<{
								account_id: string;
								content_type: string;
								views_at_24h: number;
							}>) {
								if (!row.account_id || !row.content_type) continue;
								const types = byAccount.get(row.account_id) ?? new Map();
								byAccount.set(row.account_id, types);
								const entry = types.get(row.content_type) ?? {
									total: 0,
									count: 0,
								};
								entry.total += row.views_at_24h ?? 0;
								entry.count += 1;
								types.set(row.content_type, entry);
							}

							// For each account, rank content types and write top 3
							for (const [accountId, types] of byAccount) {
								const ranked = [...types.entries()]
									.filter(([, v]) => v.count >= 2) // Need at least 2 posts of that type
									.map(([type, v]) => ({
										type,
										avg: Math.round(v.total / v.count),
										count: v.count,
									}))
									.sort((a, b) => b.avg - a.avg)
									.slice(0, 3);

								if (ranked.length > 0) {
									await looseDb
										.from("account_autoposter_state")
										.update({ best_content_types: ranked })
										.eq("account_id", accountId);
									contentTypeUpdates++;
								}
							}
						}

						logger.info(
							"[auto-learning] Phase 3 (content type feedback) completed",
							{ accountsUpdated: contentTypeUpdates },
						);
					} catch (err) {
						logger.error("[auto-learning] Phase 3 failed", {
							error: err instanceof Error ? err.message : String(err),
						});
					}
				}

				// ── Phase 4: Threads autoposter performance-first attribution ──
				const autoposterAttribution = {
					workspacesProcessed: 0,
					factsLoaded: 0,
					winnerPatternsBuilt: 0,
					strategyRecommendationsBuilt: 0,
				};
				if (!hasTimeBudget()) {
					logger.warn(
						"[auto-learning] Skipping Phase 4 — time budget exhausted",
					);
				} else {
					try {
						const { refreshAutoposterPerformanceAttributionFromFacts } =
							await import(
								"../_lib/handlers/auto-post/performanceAttributionRefresh.js"
							);
						const { data: configs, error: configError } = await looseDb
							.from("auto_post_config")
							.select("workspace_id")
							.eq("is_enabled", true)
							.eq("enable_ai_queue_fill", true);
						if (configError) throw configError;
						const workspaceIds = [
							...new Set(
								((configs || []) as Array<{ workspace_id: string | null }>)
									.map((row) => row.workspace_id)
									.filter((id): id is string => !!id),
							),
						];
						for (const workspaceId of workspaceIds) {
							if (!hasTimeBudget()) break;
							const result =
								await refreshAutoposterPerformanceAttributionFromFacts({
									workspaceId,
									days: 30,
									limit: 25,
									client: looseDb,
								});
							autoposterAttribution.workspacesProcessed++;
							autoposterAttribution.factsLoaded += result.factsLoaded;
							autoposterAttribution.winnerPatternsBuilt +=
								result.winnerPatternsBuilt;
							autoposterAttribution.strategyRecommendationsBuilt +=
								result.strategyRecommendationsBuilt;
						}
						logger.info(
							"[auto-learning] Phase 4 (autoposter attribution) completed",
							autoposterAttribution,
						);
					} catch (err) {
						logger.error("[auto-learning] Phase 4 failed", {
							error: err instanceof Error ? err.message : String(err),
						});
					}
				}

				return {
					itemsProcessed: phase1Result.groupsProcessed,
					metadata: {
						toneNotesUpdated: phase1Result.toneNotesUpdated,
						feedbackRatings: phase1Result.feedbackRatings,
						groupResults: phase1Result.groupResults,
						retirement: {
							retired: retirementResult.retired.length,
							scanned: retirementResult.totalScanned,
							groupsUpdated: retirementResult.groupsUpdated,
						},
						contentTypeUpdates,
						autoposterAttribution,
					},
				};
			});
		},
		305,
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ success: true });
}
