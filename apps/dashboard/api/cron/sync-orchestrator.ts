/**
 * Sync Orchestrator Cron Job
 *
 * Consolidated worker that processes sync queues sequentially:
 * 0. Analytics dispatch (cohort-based QStash fan-out, every 30 min via cooldown)
 * 1. Engagement sync queue (auto-post metrics, reply metrics, mentions) — lightweight, first
 * 2. Reply sync queue (post replies/conversations) — lightweight
 * 3. Competitor sync queue (competitor profile + posts) — lightweight
 * 4. Stale job cleanup (analytics sync now handled by QStash fan-out from queueSync)
 *
 * Each phase has its own try/catch so one failure doesn't block the rest.
 * Time budget checks prevent exceeding the effective Vercel runtime limit.
 *
 * Schedule: 2,17,32,47 * * * * (every 15 minutes, configured in vercel.json)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { alertCronFailure } from "../_lib/alerting.js";
import { trackCronRun, withCronLock } from "../_lib/cronUtils.js";
import { logger, serializeError } from "../_lib/logger.js";

import { cleanupStaleAnalyticsJobs } from "../_lib/sync/analyticsPhase.js";
import { processCompetitorSyncQueue } from "../_lib/sync/competitorPhase.js";
import { processEngagementSyncQueue } from "../_lib/sync/engagementPhase.js";
import { processReplyChainQueue } from "../_lib/sync/replyChainPhase.js";
import { processReplySyncQueue } from "../_lib/sync/replyPhase.js";
import {
	getOrchestratorStartTime,
	hasTimeBudget,
	setOrchestratorStartTime,
} from "../_lib/sync/shared.js";

// ============================================================================
// Main Handler
// ============================================================================

export const config = { maxDuration: 180 };

export default async function handler(req: VercelRequest, res: VercelResponse) {
	// Strict cron secret check
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	if (
		!process.env.UPSTASH_REDIS_REST_URL ||
		!process.env.UPSTASH_REDIS_REST_TOKEN
	) {
		logger.info("Upstash not configured, skipping sync orchestrator");
		return res.status(200).json({ message: "Queue service not configured" });
	}

	const { getPrivilegedSupabase, PRIVILEGED_DB_REASONS } = await import(
		"../_lib/privilegedDb.js"
	);
	const supabase = getPrivilegedSupabase(
		PRIVILEGED_DB_REASONS.cronOrchestration,
	);

	const lockResult = await withCronLock(
		supabase,
		"sync-orchestrator",
		async () => {
			return trackCronRun(supabase, "sync-orchestrator", async () => {
				setOrchestratorStartTime(Date.now());
				let totalProcessed = 0;
				const metadata: Record<string, unknown> = { phases: {} };
				const phases = metadata.phases as Record<string, unknown>;

				// ---- Phase 0: Analytics dispatch (cohort-based QStash fan-out) ----
				// Runs every ~30 min via Redis cooldown (every other orchestrator invocation)
				try {
					const phase0: Record<string, unknown> = { status: "started" };
					phases.analyticsDispatch = phase0;
					const { getRedis } = await import("../_lib/redis.js");
					const redis = getRedis();
					const dispatchCooldownKey = "analytics-dispatch:last-run";
					const lastDispatch = await redis.get(dispatchCooldownKey);
					const cooldownMs = 25 * 60 * 1000; // 25 min (slightly under 30 to avoid drift)

					if (!lastDispatch || Date.now() - Number(lastDispatch) > cooldownMs) {
						// Pre-flight: Meta API health check (circuit breaker)
						const { isMetaApiHealthy } = await import(
							"../_lib/metaApiHealth.js"
						);
						const [threadsHealthy, igHealthy] = await Promise.all([
							isMetaApiHealthy("threads"),
							isMetaApiHealthy("instagram"),
						]);
						phase0.health = { threads: threadsHealthy, ig: igHealthy };
						if (!threadsHealthy) {
							logger.warn(
								"[orchestrator] Phase 0: Threads API unhealthy — skipping Threads dispatch",
							);
						}
						if (!igHealthy) {
							logger.warn(
								"[orchestrator] Phase 0: Instagram API unhealthy — skipping Instagram dispatch",
							);
						}
						if (!threadsHealthy && !igHealthy) {
							logger.warn(
								"[orchestrator] Phase 0: Both platforms unhealthy — skipping analytics dispatch entirely",
							);
							phase0.status = "skipped";
							phase0.reason = "both-platforms-unhealthy";
						} else {
							logger.info("[orchestrator] Phase 0: Analytics dispatch");
							const { dispatchAnalyticsSync } = await import(
								"../_lib/analyticsDispatch.js"
							);
							const dispatchCount = await dispatchAnalyticsSync();
							await redis.set(dispatchCooldownKey, String(Date.now()), {
								ex: 1800,
							});
							totalProcessed += dispatchCount;
							phase0.status = "complete";
							phase0.dispatched = dispatchCount;
							logger.info("[orchestrator] Phase 0 complete", {
								dispatched: dispatchCount,
							});
						}
					} else {
						logger.debug("[orchestrator] Phase 0: Skipped (cooldown active)");
						phase0.status = "skipped";
						phase0.reason = "cooldown";
						phase0.cooldownMsRemaining =
							cooldownMs - (Date.now() - Number(lastDispatch));
					}
				} catch (error) {
					logger.error("[orchestrator] Phase 0 (analytics dispatch) failed", {
						error: serializeError(error),
					});
					phases.analyticsDispatch = {
						status: "failed",
						error: serializeError(error),
					};
					alertCronFailure("sync-orchestrator-dispatch", serializeError(error));
					try {
						const { captureServerException } = await import(
							"../_lib/sentryServer.js"
						);
						await captureServerException(error, {
							cronJob: "sync-orchestrator",
							phase: "analytics-dispatch",
						});
					} catch (sentryErr) {
						logger.error("[sync-orchestrator] Sentry reporting failed", {
							error: String(sentryErr),
						});
					}
				}

				// ---- Phase 1: Engagement sync queue (lightweight, runs first to prevent starvation) ----
				try {
					if (hasTimeBudget()) {
						logger.info("[orchestrator] Phase 1: Engagement sync");
						const engagementCount = await processEngagementSyncQueue();
						totalProcessed += engagementCount;
						phases.engagement = {
							status: "complete",
							processed: engagementCount,
						};
					} else {
						phases.engagement = { status: "skipped", reason: "no_time_budget" };
					}
				} catch (error) {
					logger.error("[orchestrator] Phase 1 (engagement) failed", {
						error: serializeError(error),
					});
					phases.engagement = {
						status: "failed",
						error: serializeError(error),
					};
					alertCronFailure(
						"sync-orchestrator-engagement",
						serializeError(error),
					);
					try {
						const { captureServerException } = await import(
							"../_lib/sentryServer.js"
						);
						await captureServerException(error, {
							cronJob: "sync-orchestrator",
							phase: "engagement",
						});
					} catch (sentryErr) {
						logger.error("[sync-orchestrator] Sentry reporting failed", {
							error: String(sentryErr),
						});
					}
				}

				// ---- Phase 1.5: Auto-queue engagement for recently published posts ----
				try {
					if (hasTimeBudget()) {
						const { getPrivilegedSupabaseAny } = await import(
							"../_lib/privilegedDb.js"
						);
						const apqDb = getPrivilegedSupabaseAny(
							PRIVILEGED_DB_REASONS.cronOrchestration,
						);
						const oneHourAgo = new Date(
							Date.now() - 60 * 60 * 1000,
						).toISOString();
						const { data: unsynced } = await apqDb
							.from("auto_post_queue")
							.select(
								"id, workspace_id, threads_post_id, account_id, accounts!auto_post_queue_account_id_fkey(user_id)",
							)
							.eq("status", "published")
							.is("engagement_fetched_at", null)
							.not("threads_post_id", "is", null)
							.not("account_id", "is", null)
							.lt("posted_at", oneHourAgo)
							.order("posted_at", { ascending: true })
							.limit(50);

						if (unsynced?.length) {
							const { getRedis } = await import("../_lib/redis.js");
							const { queueEngagementSyncJob } = await import(
								"../_lib/handlers/auto-post/route/routeHelpers.js"
							);
							const redis = getRedis();
							let queued = 0;
							const workspaces = new Map<string, string>();
							for (const item of unsynced as {
								id: string;
								workspace_id: string;
								accounts?: { user_id?: string | null | undefined } | null | undefined;
							}[]) {
								const userId = item.accounts?.user_id;
								if (!userId) continue;
								workspaces.set(item.workspace_id, userId);
							}
							for (const [workspaceId, userId] of workspaces) {
								const dedupeKey = `engagement-sync-dedupe:auto-post:${workspaceId}`;
								const claimed = await redis.set(dedupeKey, Date.now(), {
									ex: 3600,
									nx: true,
								});
								if (!claimed) continue;
								await queueEngagementSyncJob(userId, "auto-post-engagement", {
									workspaceId,
								});
								queued++;
							}
							if (queued > 0) {
								logger.info(
									"[orchestrator] Phase 1.5: Auto-queued engagement sync",
									{ count: queued },
								);
								totalProcessed += queued;
							}
							phases.autoEngagementQueue = {
								status: "complete",
								queued,
							};
						} else {
							phases.autoEngagementQueue = {
								status: "complete",
								queued: 0,
							};
						}
					} else {
						phases.autoEngagementQueue = {
							status: "skipped",
							reason: "no_time_budget",
						};
					}
				} catch (error) {
					logger.warn(
						"[orchestrator] Phase 1.5 (auto-engagement-queue) failed (non-fatal)",
						{
							error: serializeError(error),
						},
					);
					phases.autoEngagementQueue = {
						status: "failed",
						error: serializeError(error),
					};
				}

				// ---- Phase 2: Reply sync queue (lightweight) ----
				try {
					if (hasTimeBudget()) {
						logger.info("[orchestrator] Phase 2: Reply sync");
						const replyCount = await processReplySyncQueue();
						totalProcessed += replyCount;
						phases.replySync = { status: "complete", processed: replyCount };
					} else {
						phases.replySync = { status: "skipped", reason: "no_time_budget" };
					}
				} catch (error) {
					logger.error("[orchestrator] Phase 2 (replies) failed", {
						error: serializeError(error),
					});
					phases.replySync = {
						status: "failed",
						error: serializeError(error),
					};
					alertCronFailure("sync-orchestrator-replies", serializeError(error));
					try {
						const { captureServerException } = await import(
							"../_lib/sentryServer.js"
						);
						await captureServerException(error, {
							cronJob: "sync-orchestrator",
							phase: "replies",
						});
					} catch (sentryErr) {
						logger.error("[sync-orchestrator] Sentry reporting failed", {
							error: String(sentryErr),
						});
					}
				}

				// ---- Phase 3: Competitor sync queue (lightweight) ----
				try {
					if (hasTimeBudget()) {
						logger.info("[orchestrator] Phase 3: Competitor sync");
						const competitorCount = await processCompetitorSyncQueue();
						totalProcessed += competitorCount;
						phases.competitorSync = {
							status: "complete",
							processed: competitorCount,
						};
					} else {
						phases.competitorSync = {
							status: "skipped",
							reason: "no_time_budget",
						};
					}
				} catch (error) {
					logger.error("[orchestrator] Phase 3 (competitors) failed", {
						error: serializeError(error),
					});
					phases.competitorSync = {
						status: "failed",
						error: serializeError(error),
					};
					alertCronFailure(
						"sync-orchestrator-competitors",
						serializeError(error),
					);
					try {
						const { captureServerException } = await import(
							"../_lib/sentryServer.js"
						);
						await captureServerException(error, {
							cronJob: "sync-orchestrator",
							phase: "competitors",
						});
					} catch (sentryErr) {
						logger.error("[sync-orchestrator] Sentry reporting failed", {
							error: String(sentryErr),
						});
					}
				}

				// Stale job cleanup (analytics sync now handled by QStash fan-out)
				try {
					if (hasTimeBudget()) {
						await cleanupStaleAnalyticsJobs();
						phases.staleAnalyticsCleanup = { status: "complete" };
					} else {
						phases.staleAnalyticsCleanup = {
							status: "skipped",
							reason: "no_time_budget",
						};
					}
				} catch (error) {
					logger.warn("[orchestrator] Stale analytics job cleanup failed", {
						error: serializeError(error),
					});
					phases.staleAnalyticsCleanup = {
						status: "failed",
						error: serializeError(error),
					};
				}

				// ---- Phase 5: Reply Chain Pulse (Threads conversation depth) ----
				// Runs last so heavier phases keep priority. ≤24h freshness target.
				try {
					if (hasTimeBudget()) {
						logger.info("[orchestrator] Phase 5: Reply chain pulse");
						const chainStats = await processReplyChainQueue();
						phases.replyChain = chainStats;
						totalProcessed += chainStats.postsProcessed;
					} else {
						phases.replyChain = { skipped: true, reason: "no_time_budget" };
					}
				} catch (error) {
					logger.warn("[orchestrator] Phase 5 (reply chain) failed", {
						error: serializeError(error),
					});
					phases.replyChain = {
						status: "failed",
						error: serializeError(error),
					};
					// Non-critical — don't alert for reply-chain; Discord noise > signal.
				}

				const totalDuration = Date.now() - getOrchestratorStartTime();
				logger.info("[orchestrator] All phases complete", {
					totalProcessed,
					durationMs: totalDuration,
				});

				metadata.totalDurationMs = totalDuration;
				return { itemsProcessed: totalProcessed, metadata };
			});
		},
		185,
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ success: true });
}
