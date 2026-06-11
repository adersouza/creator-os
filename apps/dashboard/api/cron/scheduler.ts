/**
 * Unified Scheduler Cron — every 5 minutes, 180s max
 *
 * Autoposter v2 migration. Replaces 4 independent crons:
 *   - dawn-planner (batch content planning)
 *   - publish-worker Phases 3-4 (queue reconciliation + fill safety net)
 *   - account-state-evaluator (state evaluation)
 *   - autoposter-watchdog (health checks)
 *
 * Runs only for workspaces with `auto_post_config.scheduler_version >= 2`:
 *   - v2: Unified scheduler (Phase 1)
 *   - v3: Content pool — accounts assigned at publish, not fill time (Phase 2)
 *   - v4: Flat config — single account_schedule table (Phase 3)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

export const config = {
	maxDuration: 180,
};

const JOB_NAME = "scheduler";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const { withCronLock, trackCronRun } = await import("../_lib/cronUtils.js");
	const { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } = await import(
		"../_lib/privilegedDb.js"
	);
	const { logger } = await import("../_lib/logger.js");

	const supabase = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.schedulerWorker,
	);

	const lockResult = await withCronLock(
		supabase,
		JOB_NAME,
		async () => {
			return trackCronRun(supabase, JOB_NAME, async () => {
				const { runSchedulerLoop } = await import(
					"../_lib/cron/scheduler/accountLoop.js"
				);

				const summary = await runSchedulerLoop();

				logger.info(`[${JOB_NAME}] Complete`, {
					runId: summary.runId,
					groups: summary.groupsProcessed,
					accounts: summary.accountsEvaluated,
					dispatched: summary.dispatched,
					fills: summary.fillsTriggered,
					states: summary.statesUpserted,
					decisions: summary.decisionsLogged,
					errors: summary.errors.length,
					durationMs: summary.durationMs,
				});

				// Alert on errors
				if (summary.errors.length > 0) {
					try {
						const { alertCronFailure } = await import("../_lib/alerting.js");
						alertCronFailure(
							JOB_NAME,
							`${summary.errors.length} error(s): ${summary.errors.slice(0, 3).join("; ")}`,
							summary.durationMs,
						);
					} catch {
						/* best-effort alerting */
					}
				}

				return {
					itemsProcessed: summary.dispatched + summary.fillsTriggered,
					metadata: {
						runId: summary.runId,
						groupsProcessed: summary.groupsProcessed,
						accountsEvaluated: summary.accountsEvaluated,
						dispatched: summary.dispatched,
						fillsTriggered: summary.fillsTriggered,
						statesUpserted: summary.statesUpserted,
						decisionsLogged: summary.decisionsLogged,
						errors: summary.errors,
						durationMs: summary.durationMs,
					},
				};
			});
		},
		185,
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ ok: true });
}
