/**
 * Consolidated Daily Maintenance Cron Job
 *
 * Merges formerly separate daily cron jobs into a single sequential handler:
 *   1. expire-trials     (~5s)   — Downgrade expired trial profiles
 *   2. refresh-tokens    (~30-55s) — Refresh expiring Threads + Instagram tokens
 *   3. data-retention    (~10s)  — Purge stale rows from 10 tables
 *   4. cleanup-audit-logs (~5s)  — Call cleanup_old_audit_logs() RPC
 *   5. media-migration   (~60-180s) — Migrate expired CDN URLs to Supabase Storage (least critical)
 *   6. enforce-accounts  (~5s)   — Catchall for webhook enforcement failures
 *   7. vacuum-analyze    (~2s)   — ANALYZE small high-churn tables
 *   8. storage-cleanup   (~5s)   — Remove orphaned storage files
 *   9. stripe-sub-poll   (~10-30s) — Verify DB subscription status matches Stripe
 *
 * Total budget: 290s (MAX_EXECUTION_TIME) out of 300s maxDuration.
 * Each phase runs in its own try/catch so a failure in one does not abort the rest.
 *
 * Schedule: Daily (configured in vercel.json)
 *
 * Phase implementations live in ./daily-maintenance/ sub-modules.
 * This file is the orchestrator that calls each phase.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

export { phaseCleanupAuditLogs } from "./daily-maintenance/cleanup-audit.js";
export { phaseCollabInviteRefresh } from "./daily-maintenance/collab-refresh.js";
export { phaseCommentRepair } from "./daily-maintenance/comment-repair.js";
export { phaseDataRetention } from "./daily-maintenance/data-retention.js";
export { phaseDlqSweep } from "./daily-maintenance/dlq-sweep.js";
export { phaseEnforceAccountLimits } from "./daily-maintenance/enforce-accounts.js";
// Re-export all phases for consumers (daily-orchestrator, daily-orchestrator-late)
export { phaseExpireTrials } from "./daily-maintenance/expire-trials.js";
export { phaseInboxRepair } from "./daily-maintenance/inbox-repair.js";
export { phaseMediaMigration } from "./daily-maintenance/media-migration.js";
export { phaseRefreshTokens } from "./daily-maintenance/refresh-tokens.js";
export { phaseStorageCleanup } from "./daily-maintenance/storage-cleanup.js";
export { phaseStripeSubscriptionPoll } from "./daily-maintenance/stripe-poll.js";
export { phaseVacuumAnalyze } from "./daily-maintenance/vacuum-analyze.js";

// Import types and helpers from shared
import type { PhaseMetadata } from "./daily-maintenance/shared.js";
import { hasTimeBudget } from "./daily-maintenance/shared.js";

// ============================================================================
// Main Handler
// ============================================================================

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const startTime = Date.now();

	// Strict cron secret check
	const { verifyCronAuth } = await import("../apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	// Lazy imports for heavy modules
	const { withCronLock, trackCronRun } = await import("../cronUtils.js");
	const { getSupabase } = await import("../supabase.js");
	const { logger } = await import("../logger.js");
	const { alertCronFailure } = await import("../alerting.js");

	// Lazy import phase functions
	const { phaseExpireTrials } = await import(
		"./daily-maintenance/expire-trials.js"
	);
	const { phaseRefreshTokens } = await import(
		"./daily-maintenance/refresh-tokens.js"
	);
	const { phaseDataRetention } = await import(
		"./daily-maintenance/data-retention.js"
	);
	const { phaseCleanupAuditLogs } = await import(
		"./daily-maintenance/cleanup-audit.js"
	);
	const { phaseMediaMigration } = await import(
		"./daily-maintenance/media-migration.js"
	);
	const { phaseEnforceAccountLimits } = await import(
		"./daily-maintenance/enforce-accounts.js"
	);
	const { phaseVacuumAnalyze } = await import(
		"./daily-maintenance/vacuum-analyze.js"
	);
	const { phaseStorageCleanup } = await import(
		"./daily-maintenance/storage-cleanup.js"
	);
	const { phaseStripeSubscriptionPoll } = await import(
		"./daily-maintenance/stripe-poll.js"
	);
	const { phaseDlqSweep } = await import("./daily-maintenance/dlq-sweep.js");

	const supabase = getSupabase();

	const metadata: PhaseMetadata = {
		expireTrials: { count: 0 },
		refreshTokens: { refreshed: 0, failed: 0 },
		dataRetention: { deleted: 0 },
		cleanupAudit: { ok: false },
		mediaMigration: { migrated: 0, failed: 0 },
		enforceAccounts: { enforced: 0 },
		vacuumAnalyze: { ok: false },
		storageCleanup: { deleted: 0 },
		stripeSubscriptionPoll: { checked: 0, corrected: 0 },
		dlqSweep: { threadsRevived: 0, igRevived: 0 },
	};

	const lockResult = await withCronLock(
		supabase,
		"daily-maintenance",
		async () => {
			return trackCronRun(supabase, "daily-maintenance", async () => {
				let totalProcessed = 0;

				// Phase 1: Expire Trials (~5s)
				if (hasTimeBudget(startTime)) {
					logger.info("[daily-maintenance] Phase 1/10: Expire Trials");
					try {
						metadata.expireTrials = await phaseExpireTrials(supabase, logger);
						totalProcessed += metadata.expireTrials.count;
					} catch (err) {
						metadata.expireTrials.error =
							err instanceof Error ? err.message : String(err);
						logger.error("[daily-maintenance] Phase 1 failed", {
							error: metadata.expireTrials.error,
						});
						try {
							const { captureServerException } = await import(
								"../sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: "daily-maintenance",
								phase: "expire-trials",
							});
						} catch (sentryErr) {
							logger.debug("Sentry reporting failed", {
								error: String(sentryErr),
							});
						}
					}
				}

				// Phase 2: Refresh Tokens (~30-55s)
				if (hasTimeBudget(startTime)) {
					logger.info("[daily-maintenance] Phase 2/10: Refresh Tokens");
					try {
						metadata.refreshTokens = await phaseRefreshTokens(
							supabase,
							logger,
							startTime,
						);
						totalProcessed += metadata.refreshTokens.refreshed;
					} catch (err) {
						metadata.refreshTokens.error =
							err instanceof Error ? err.message : String(err);
						logger.error("[daily-maintenance] Phase 2 failed", {
							error: metadata.refreshTokens.error,
						});
						try {
							const { captureServerException } = await import(
								"../sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: "daily-maintenance",
								phase: "refresh-tokens",
							});
						} catch (sentryErr) {
							logger.debug("Sentry reporting failed", {
								error: String(sentryErr),
							});
						}
						alertCronFailure(
							"daily-maintenance/refresh-tokens",
							metadata.refreshTokens.error ?? "Unknown error",
						);
					}
				}

				// Phase 3: Data Retention (~10s)
				if (hasTimeBudget(startTime)) {
					logger.info("[daily-maintenance] Phase 3/10: Data Retention");
					try {
						metadata.dataRetention = await phaseDataRetention(supabase, logger);
						totalProcessed += metadata.dataRetention.deleted;
					} catch (err) {
						metadata.dataRetention.error =
							err instanceof Error ? err.message : String(err);
						logger.error("[daily-maintenance] Phase 3 failed", {
							error: metadata.dataRetention.error,
						});
						try {
							const { captureServerException } = await import(
								"../sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: "daily-maintenance",
								phase: "data-retention",
							});
						} catch (sentryErr) {
							logger.debug("Sentry reporting failed", {
								error: String(sentryErr),
							});
						}
						alertCronFailure(
							"daily-maintenance/data-retention",
							metadata.dataRetention.error ?? "Unknown error",
						);
					}
				}

				// Phase 4: Cleanup Audit Logs (~5s)
				if (hasTimeBudget(startTime)) {
					logger.info("[daily-maintenance] Phase 4/10: Cleanup Audit Logs");
					try {
						metadata.cleanupAudit = await phaseCleanupAuditLogs(
							supabase,
							logger,
						);
						totalProcessed += metadata.cleanupAudit.deleted ?? 0;
					} catch (err) {
						metadata.cleanupAudit = {
							ok: false,
							error: err instanceof Error ? err.message : String(err),
						};
						logger.error("[daily-maintenance] Phase 4 failed", {
							error: metadata.cleanupAudit.error,
						});
						try {
							const { captureServerException } = await import(
								"../sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: "daily-maintenance",
								phase: "cleanup-audit-logs",
							});
						} catch (sentryErr) {
							logger.debug("Sentry reporting failed", {
								error: String(sentryErr),
							});
						}
						alertCronFailure(
							"daily-maintenance/cleanup-audit-logs",
							metadata.cleanupAudit.error ?? "Unknown error",
						);
					}
				}

				// Phase 5: Media Migration (~60-180s, least critical — placed last)
				if (hasTimeBudget(startTime)) {
					logger.info("[daily-maintenance] Phase 5/10: Media Migration");
					try {
						metadata.mediaMigration = await phaseMediaMigration(
							supabase,
							logger,
							startTime,
						);
						totalProcessed += metadata.mediaMigration.migrated;
					} catch (err) {
						metadata.mediaMigration.error =
							err instanceof Error ? err.message : String(err);
						logger.error("[daily-maintenance] Phase 5 failed", {
							error: metadata.mediaMigration.error,
						});
						try {
							const { captureServerException } = await import(
								"../sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: "daily-maintenance",
								phase: "media-migration",
							});
						} catch (sentryErr) {
							logger.debug("Sentry reporting failed", {
								error: String(sentryErr),
							});
						}
						alertCronFailure(
							"daily-maintenance/media-migration",
							metadata.mediaMigration.error ?? "Unknown error",
						);
					}
				}

				// Phase 6: Enforce Account Limits (catchall for failed webhook enforcement)
				if (hasTimeBudget(startTime)) {
					logger.info("[daily-maintenance] Phase 6: Enforce Account Limits");
					try {
						metadata.enforceAccounts = await phaseEnforceAccountLimits(
							supabase,
							logger,
						);
						totalProcessed += metadata.enforceAccounts.enforced;
					} catch (err) {
						metadata.enforceAccounts.error =
							err instanceof Error ? err.message : String(err);
						logger.error("[daily-maintenance] Phase 6 failed", {
							error: metadata.enforceAccounts.error,
						});
						try {
							const { captureServerException } = await import(
								"../sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: "daily-maintenance",
								phase: "enforce-accounts",
							});
						} catch (sentryErr) {
							logger.debug("Sentry reporting failed", {
								error: String(sentryErr),
							});
						}
						alertCronFailure(
							"daily-maintenance/enforce-accounts",
							metadata.enforceAccounts.error ?? "Unknown error",
						);
					}
				}

				// Phase 7: ANALYZE Small High-Churn Tables (~2s)
				if (hasTimeBudget(startTime)) {
					logger.info("[daily-maintenance] Phase 7: ANALYZE Small Tables");
					try {
						metadata.vacuumAnalyze = await phaseVacuumAnalyze(supabase, logger);
					} catch (err) {
						metadata.vacuumAnalyze = {
							ok: false,
							error: err instanceof Error ? err.message : String(err),
						};
						logger.error("[daily-maintenance] Phase 7 failed", {
							error: metadata.vacuumAnalyze.error,
						});
						// Non-critical — don't alert, just log
					}
				}

				// Phase 8: Orphaned Storage Cleanup (~5s)
				if (hasTimeBudget(startTime)) {
					logger.info("[daily-maintenance] Phase 8: Storage Cleanup");
					try {
						metadata.storageCleanup = await phaseStorageCleanup(
							supabase,
							logger,
						);
						totalProcessed += metadata.storageCleanup.deleted;
					} catch (err) {
						metadata.storageCleanup = {
							deleted: 0,
							error: err instanceof Error ? err.message : String(err),
						};
						logger.error("[daily-maintenance] Phase 8 failed", {
							error: metadata.storageCleanup.error,
						});
						// Non-critical — don't alert, just log
					}
				}

				// Phase 9: Stripe Subscription Status Poll (~10-30s)
				// Safety net for missed webhooks — verifies DB matches Stripe's truth.
				if (hasTimeBudget(startTime)) {
					logger.info("[daily-maintenance] Phase 9: Stripe Subscription Poll");
					try {
						metadata.stripeSubscriptionPoll = await phaseStripeSubscriptionPoll(
							supabase,
							logger,
						);
						totalProcessed += metadata.stripeSubscriptionPoll.corrected;
					} catch (err) {
						metadata.stripeSubscriptionPoll = {
							checked: 0,
							corrected: 0,
							error: err instanceof Error ? err.message : String(err),
						};
						logger.error("[daily-maintenance] Phase 9 failed", {
							error: metadata.stripeSubscriptionPoll.error,
						});
						try {
							const { captureServerException } = await import(
								"../sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: "daily-maintenance",
								phase: "stripe-subscription-poll",
							});
						} catch (sentryErr) {
							logger.debug("Sentry reporting failed", {
								error: String(sentryErr),
							});
						}
						alertCronFailure(
							"daily-maintenance/stripe-subscription-poll",
							metadata.stripeSubscriptionPoll.error ?? "Unknown error",
						);
					}
				}

				// Phase 10: DLQ Sweep (~2s) — auto-revive eligible dead-lettered webhook events
				if (hasTimeBudget(startTime)) {
					logger.info("[daily-maintenance] Phase 10: DLQ Sweep");
					try {
						metadata.dlqSweep = await phaseDlqSweep(supabase, logger);
						totalProcessed +=
							metadata.dlqSweep.threadsRevived + metadata.dlqSweep.igRevived;
					} catch (err) {
						metadata.dlqSweep = {
							threadsRevived: 0,
							igRevived: 0,
							error: err instanceof Error ? err.message : String(err),
						};
						logger.error("[daily-maintenance] Phase 10 failed", {
							error: metadata.dlqSweep.error,
						});
						// Non-critical — DLQ events will wait for next daily run or manual retry
					}
				}

				const durationMs = Date.now() - startTime;
				logger.info("[daily-maintenance] All phases complete", {
					durationMs,
					metadata,
					totalProcessed,
				});

				return { itemsProcessed: totalProcessed };
			});
		},
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res
		.status(200)
		.json({ success: true, metadata, durationMs: Date.now() - startTime });
}
