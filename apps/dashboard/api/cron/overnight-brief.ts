/**
 * Overnight brief cron — runs at 1:55 AM UTC (vercel.json).
 *
 * Thin wrapper: auth + lock + tracking + orchestrator call. Actual logic lives
 * in api/_lib/cron/overnight-brief.ts so it's unit-testable without a VercelRequest.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

export const config = {
	maxDuration: 300,
};

const JOB_NAME = "overnight-brief";

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const { withCronLock, trackCronRun } = await import("../_lib/cronUtils.js");
	const { getSupabase } = await import("../_lib/supabase.js");
	const { logger } = await import("../_lib/logger.js");
	const { alertCronFailure } = await import("../_lib/alerting.js");
	const { processOvernightBriefs } = await import(
		"../_lib/cron/overnight-brief.js"
	);

	const supabase = getSupabase();
	const startTime = Date.now();

	const lockResult = await withCronLock(
		supabase,
		JOB_NAME,
		async () => {
			return trackCronRun(supabase, JOB_NAME, async () => {
				try {
					const stats = await processOvernightBriefs(startTime);
					return {
						itemsProcessed: stats.briefsGenerated,
						metadata: {
							usersConsidered: stats.usersConsidered,
							briefsGenerated: stats.briefsGenerated,
							skippedNoChange: stats.skippedNoChange,
							skippedBudget: stats.skippedBudget,
							failed: stats.failed,
							totalDurationMs: Date.now() - startTime,
						},
					};
				} catch (err) {
					const msg = err instanceof Error ? err.message : String(err);
					logger.error(`[${JOB_NAME}] failed`, { error: msg });
					alertCronFailure(JOB_NAME, msg);
					try {
						const { captureServerException } = await import(
							"../_lib/sentryServer.js"
						);
						await captureServerException(err, { cronJob: JOB_NAME });
					} catch {
						/* best-effort */
					}
					throw err;
				}
			});
		},
		305,
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}
	return res.status(200).json({ ok: true });
}
