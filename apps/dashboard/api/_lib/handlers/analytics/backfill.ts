/**
 * Analytics Handlers: backfill + rebackfill
 *
 * Historical synthetic analytics backfill has been retired. These handlers
 * remain only to return a clear 410 for old clients.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "../../apiResponse.js";

/**
 * POST /api/analytics?action=backfill
 */
export async function handleBackfill(_req: VercelRequest, res: VercelResponse) {
	return apiError(
		res,
		410,
		"Analytics synthetic backfill has been removed. Use platform sync or analytics refresh to populate real account_analytics rows.",
	);
}

/**
 * POST /api/analytics?action=rebackfill
 */
export async function handleRebackfill(
	_req: VercelRequest,
	res: VercelResponse,
) {
	return apiError(
		res,
		410,
		"Analytics synthetic rebackfill has been removed. Use platform sync or analytics refresh to populate real account_analytics rows.",
	);
}
