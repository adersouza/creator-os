import type { VercelRequest, VercelResponse } from "@vercel/node";
import { alertCronFailure } from "../_lib/alerting.js";
import { apiSuccess, verifyCronAuth } from "../_lib/apiResponse.js";
import { trackCronRun, withCronLock } from "../_lib/cronUtils.js";
import { logger } from "../_lib/logger.js";
import { getSupabase } from "../_lib/supabase.js";

export const config = { maxDuration: 300 };

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (!verifyCronAuth(req, res)) return;
	const db = getSupabase();
	const lockResult = await withCronLock(
		db,
		"trend-scanner",
		async () => {
			return trackCronRun(db, "trend-scanner", async () => {
				try {
					const { processTrendPipeline } = await import(
						"../_lib/handlers/trend-pipeline/index.js"
					);
					// processTrendPipeline has its own internal time budget (270s)
					const count = await processTrendPipeline();
					return { itemsProcessed: count };
				} catch (err: unknown) {
					const errMsg = err instanceof Error ? err.message : String(err);
					logger.error("[trend-scanner] Pipeline failed", { error: errMsg });
					try {
						const { captureServerException } = await import(
							"../_lib/sentryServer.js"
						);
						await captureServerException(err, { cronJob: "trend-scanner" });
					} catch {
						/* sentry best-effort */
					}
					alertCronFailure("trend-scanner", errMsg);
					throw err;
				}
			});
		},
		305,
	);
	if (lockResult.skipped)
		return res.status(200).json({ skipped: true, reason: "lock_held" });
	return apiSuccess(res, lockResult);
}
