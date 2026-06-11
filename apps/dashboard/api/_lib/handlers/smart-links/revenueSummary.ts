/**
 * Revenue summary — dashboard card data aggregated via RPC.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db } from "./shared.js";

export async function handleRevenueSummary(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const days = parseInt(req.query.days as string, 10) || 30;

	const { data, error } = await db().rpc("get_smart_link_revenue_summary", {
		p_user_id: userId,
		p_days: days,
	});

	if (error) {
		logger.error("[smart-links] Revenue summary error", {
			error: String(error),
		});
		return apiError(res, 500, "Failed to fetch revenue summary");
	}

	// RPC returns an array with one row
	const row = Array.isArray(data) ? data[0] : data;
	return apiSuccess(res, {
		total_clicks: parseInt(String(row?.total_clicks ?? 0), 10) || 0,
		total_conversions: parseInt(String(row?.total_conversions ?? 0), 10) || 0,
		total_actual_revenue:
			parseFloat(String(row?.total_actual_revenue ?? 0)) || 0,
		total_estimated_revenue:
			parseFloat(String(row?.total_estimated_revenue ?? 0)) || 0,
		conversion_rate: parseFloat(String(row?.conversion_rate ?? 0)) || 0,
	});
}
