/**
 * Daily Orchestrator — core daily maintenance & intelligence
 *
 * Phases 0-15 (core maintenance + intelligence):
 *   Phase 0:     Clean orphaned cron_runs
 *   Phases 1-6:  daily-maintenance  (expire trials, tokens, retention, audit, media, account limits)
 *   Phases 7-10: daily-intelligence (power-user scoring, quickwin, discover, competitors)
 *   Phase 11:    token-refresh      (7-day safety-net refresh, deduped with Phase 2)
 *   Phase 12:    inspiration-scan   (AI idea generation, skipped if no configs)
 *   Phase 13:    shadowban-scanner  (flag 0-view accounts, Discord report)
 *   Phase 14:    auto-unpost        (opt-in duplicate fanout cleanup)
 *   Phase 15:    inbox-dm-repair    (lightweight DM sync for stale accounts)
 *
 * Phases 16-23 (analytics/optimization) moved to daily-orchestrator-late (1:30 AM)
 * to stay within Vercel's 300s maxDuration budget.
 *
 * Schedule: daily at 1 AM UTC (configured in vercel.json)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

export const config = {
	maxDuration: 300,
};

const JOB_NAME = "daily-orchestrator";
const MAX_EXECUTION_TIME = 240_000;

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

				// ── Phase 0: Clean up orphaned cron_runs ──
				// Cron jobs stuck in "running" longer than maxDuration + 60s are marked failed
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 0: Clean up orphaned cron_runs`);
						const p = Date.now();
						const orphanThreshold = new Date(
							Date.now() - 360_000,
						).toISOString(); // 6 min
						const { data: orphaned } = await supabase
							.from("cron_runs")
							.update({
								status: "failed",
								error: "Orphaned: exceeded maxDuration",
							})
							.eq("status", "running")
							.lt("started_at", orphanThreshold)
							.select("id");
						const count = orphaned?.length ?? 0;
						phases.orphanedCronCleanup = {
							status: "completed",
							items_processed: count,
							phase_duration_ms: Date.now() - p,
						};
						if (count > 0) {
							logger.warn(
								`[${JOB_NAME}] Cleaned up ${count} orphaned cron_runs`,
							);
						}
						totalItems += count;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.orphanedCronCleanup = {
							status: "error",
							error: errMsg,
						};
						logger.error(`[${JOB_NAME}] Phase 0 failed`, {
							error: errMsg,
						});
					}
				}

				// ── Phase 1: Expire Trials ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 1/14: Expire Trials`);
						const p = Date.now();
						const { phaseExpireTrials } = await import(
							"../_lib/cron/daily-maintenance.js"
						);
						const result = await phaseExpireTrials(supabase, logger);
						phases.expireTrials = {
							status: "completed",
							items_processed: result.count,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += result.count;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.expireTrials = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 1 failed`, { error: errMsg });
						try {
							const { captureServerException } = await import(
								"../_lib/sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: JOB_NAME,
								phase: "expire-trials",
							});
						} catch {
							/* best-effort */
						}
						alertCronFailure(JOB_NAME, `expire-trials: ${errMsg}`);
						throw err;
					}
				}

				// ── Phase 2: Refresh Tokens (72h window from daily-maintenance) ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 2/14: Refresh Tokens (72h)`);
						const p = Date.now();
						const { phaseRefreshTokens } = await import(
							"../_lib/cron/daily-maintenance.js"
						);
						const result = await phaseRefreshTokens(
							supabase,
							logger,
							globalStart,
						);
						phases.refreshTokens = {
							status: "completed",
							items_processed: result.refreshed,
							items_failed: result.failed,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += result.refreshed;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.refreshTokens = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 2 failed`, { error: errMsg });
						try {
							const { captureServerException } = await import(
								"../_lib/sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: JOB_NAME,
								phase: "refresh-tokens",
							});
						} catch {
							/* best-effort */
						}
						alertCronFailure(JOB_NAME, `refresh-tokens: ${errMsg}`);
						throw err;
					}
				}

				// ── Phase 3: Data Retention ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 3/14: Data Retention`);
						const p = Date.now();
						const { phaseDataRetention } = await import(
							"../_lib/cron/daily-maintenance.js"
						);
						const result = await phaseDataRetention(supabase, logger);
						phases.dataRetention = {
							status: "completed",
							items_processed: result.deleted,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += result.deleted;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.dataRetention = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 3 failed`, { error: errMsg });
						try {
							const { captureServerException } = await import(
								"../_lib/sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: JOB_NAME,
								phase: "data-retention",
							});
						} catch {
							/* best-effort */
						}
						alertCronFailure(JOB_NAME, `data-retention: ${errMsg}`);
						throw err;
					}
				}

				// ── Phase 4: Cleanup Audit Logs ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 4/14: Cleanup Audit Logs`);
						const p = Date.now();
						const { phaseCleanupAuditLogs } = await import(
							"../_lib/cron/daily-maintenance.js"
						);
						const result = await phaseCleanupAuditLogs(supabase, logger);
						phases.cleanupAuditLogs = {
							status: "completed",
							items_processed: result.deleted || 0,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += result.deleted || 0;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.cleanupAuditLogs = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 4 failed`, { error: errMsg });
					}
				}

				// ── Phase 5: Media Migration ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 5/14: Media Migration`);
						const p = Date.now();
						const { phaseMediaMigration } = await import(
							"../_lib/cron/daily-maintenance.js"
						);
						const result = await phaseMediaMigration(
							supabase,
							logger,
							globalStart,
						);
						phases.mediaMigration = {
							status: "completed",
							items_processed: result.migrated,
							items_failed: result.failed,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += result.migrated;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.mediaMigration = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 5 failed`, { error: errMsg });
						alertCronFailure(JOB_NAME, `media-migration: ${errMsg}`);
						throw err;
					}
				}

				// ── Phase 6: Enforce Account Limits ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 6/14: Enforce Account Limits`);
						const p = Date.now();
						const { phaseEnforceAccountLimits } = await import(
							"../_lib/cron/daily-maintenance.js"
						);
						const result = await phaseEnforceAccountLimits(supabase, logger);
						phases.enforceAccountLimits = {
							status: "completed",
							items_processed: result.enforced,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += result.enforced;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.enforceAccountLimits = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 6 failed`, { error: errMsg });
						alertCronFailure(JOB_NAME, `enforce-account-limits: ${errMsg}`);
						throw err;
					}
				}

				// ── Phase 7: Power-User Scoring ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 7/14: Power-User Scoring`);
						const p = Date.now();
						const { phasePowerUserScoring } = await import(
							"../_lib/cron/daily-intelligence.js"
						);
						const result = await phasePowerUserScoring();
						phases.powerUserScoring = {
							status: result.status,
							items_processed: (result.detail?.usersScored as number) || 0,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += (result.detail?.usersScored as number) || 0;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.powerUserScoring = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 7 failed`, { error: errMsg });
					}
				}

				// ── Phase 8: Quick Win Monitor ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 8/14: Quick Win Monitor`);
						const p = Date.now();
						const { phaseQuickwinMonitor } = await import(
							"../_lib/cron/daily-intelligence.js"
						);
						const result = await phaseQuickwinMonitor();
						const items =
							((result.detail?.regressionsDetected as number) || 0) +
							((result.detail?.remindersSent as number) || 0);
						phases.quickwinMonitor = {
							status: result.status,
							items_processed: items,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += items;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.quickwinMonitor = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 8 failed`, { error: errMsg });
					}
				}

				// ── Phase 9: Discover Refresh ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 9/14: Discover Refresh`);
						const p = Date.now();
						const { phaseDiscoverRefresh } = await import(
							"../_lib/cron/daily-intelligence.js"
						);
						const result = await phaseDiscoverRefresh();
						phases.discoverRefresh = {
							status: result.status,
							items_processed:
								(result.detail?.searchesProcessed as number) || 0,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += (result.detail?.searchesProcessed as number) || 0;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.discoverRefresh = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 9 failed`, { error: errMsg });
						try {
							const { captureServerException } = await import(
								"../_lib/sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: JOB_NAME,
								phase: "discover-refresh",
							});
						} catch {
							/* best-effort */
						}
					}
				}

				// ── Phase 10: Competitor Snapshots ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 10/14: Competitor Snapshots`);
						const p = Date.now();
						const { phaseCompetitorSnapshots } = await import(
							"../_lib/cron/daily-intelligence.js"
						);
						const result = await phaseCompetitorSnapshots(globalStart);
						phases.competitorSnapshots = {
							status: result.status,
							items_processed: (result.detail?.snapshotsCreated as number) || 0,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += (result.detail?.snapshotsCreated as number) || 0;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.competitorSnapshots = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 10 failed`, { error: errMsg });
						try {
							const { captureServerException } = await import(
								"../_lib/sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: JOB_NAME,
								phase: "competitor-snapshots",
							});
						} catch {
							/* best-effort */
						}
						alertCronFailure(JOB_NAME, `competitor-snapshots: ${errMsg}`);
					}
				}

				// ── Phase 11: Safety-Net Token Refresh (7-day window) ──
				// Deduped with Phase 2 via Redis keys — tokens already refreshed in Phase 2 are skipped
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(
							`[${JOB_NAME}] Phase 11/14: Token Refresh (7d safety-net)`,
						);
						const p = Date.now();
						const { refreshAllTokens } = await import(
							"../_lib/cron/token-refresh.js"
						);
						const result = await refreshAllTokens();
						phases.tokenRefreshSafetyNet = {
							status: "completed",
							items_processed: result.total,
							threads_refreshed: result.threadsRefreshed,
							threads_skipped: result.threadsSkipped,
							ig_refreshed: result.igRefreshed,
							ig_skipped: result.igSkipped,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += result.total;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.tokenRefreshSafetyNet = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 11 failed`, { error: errMsg });
						alertCronFailure(JOB_NAME, `token-refresh-safety: ${errMsg}`);
						throw err;
					}
				}

				// ── Phase 12: Inspiration Scan ──
				// Skipped if no enabled configs (avoids wasted AI calls)
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 12/14: Inspiration Scan`);
						const p = Date.now();
						const { processInspirationScan } = await import(
							"../_lib/cron/inspiration-scan.js"
						);
						const count = await processInspirationScan();
						phases.inspirationScan = {
							status: "completed",
							items_processed: count,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += count;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.inspirationScan = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 12 failed`, { error: errMsg });
					}
				}

				// ── Phase 13: Shadowban Scanner ──
				// Flag accounts with 0 views after 3+ days of posting, send Discord report
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 13/14: Shadowban Scanner`);
						const p = Date.now();
						const { processShadowbanScan } = await import(
							"../_lib/cron/shadowban-scanner.js"
						);
						const scanResult = await processShadowbanScan();
						phases.shadowbanScan = {
							status: "completed",
							items_processed: scanResult.totalScanned,
							flagged: scanResult.flagged.length,
							unflagged: scanResult.unflagged.length,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += scanResult.totalScanned;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.shadowbanScan = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 13 failed`, { error: errMsg });
					}
				}

				// ── Phase 14: Auto-Unpost duplicate fanout cleanup ──
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 14/15: Auto-Unpost`);
						const p = Date.now();
						const { processAutoUnpost } = await import(
							"../_lib/cron/auto-unpost.js"
						);
						const result = await processAutoUnpost(supabase, logger);
						phases.autoUnpost = {
							status: "completed",
							items_processed: result.deleted,
							items_failed: result.failed,
							scanned_groups: result.scannedGroups,
							skipped_groups: result.skippedGroups,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += result.deleted;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.autoUnpost = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 15 failed`, { error: errMsg });
					}
				}

				// ── Phase 15: Inbox DM Repair ──
				// Lightweight daily sync for accounts that may have missed DM webhooks
				if (hasTimeBudget(globalStart)) {
					try {
						logger.info(`[${JOB_NAME}] Phase 15/15: Inbox DM Repair`);
						const p = Date.now();
						const { phaseInboxRepair } = await import(
							"../_lib/cron/daily-maintenance.js"
						);
						const result = await phaseInboxRepair(
							supabase,
							logger,
							globalStart,
						);
						phases.inboxDmRepair = {
							status: "completed",
							accounts_synced: result.synced,
							messages_synced: result.messages,
							phase_duration_ms: Date.now() - p,
						};
						totalItems += result.synced;
					} catch (err) {
						const errMsg = err instanceof Error ? err.message : String(err);
						phases.inboxDmRepair = { status: "error", error: errMsg };
						logger.error(`[${JOB_NAME}] Phase 14 failed`, { error: errMsg });
						alertCronFailure(JOB_NAME, `inbox-dm-repair: ${errMsg}`);
						throw err;
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
