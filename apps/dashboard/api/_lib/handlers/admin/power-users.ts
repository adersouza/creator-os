/**
 * Power Users Admin API — GET /api/admin/power-users
 *
 * Lists users sorted by power_user_score descending.
 * Requires admin/owner role via withAdminRole middleware.
 *
 * Query params:
 *   - limit (default 50, max 200)
 *   - minScore (default 0)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAdminRole } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

export default withAdminRole(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		// #671: Rate limit admin endpoints
		const { checkRateLimit } = await import("../../rateLimiter.js");
		const rl = await checkRateLimit({
			key: `admin-pu:${user.id}`,
			limit: 30,
			windowSeconds: 60,
			failMode: "open",
		});
		if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

		const supabase = getSupabase();

		const limit = parseInt(String(req.query.limit || "50"), 10);
		if (Number.isNaN(limit) || limit < 1)
			return apiError(res, 400, "Invalid limit");
		const clampedLimit = Math.min(limit, 200);
		const minScore = parseInt(String(req.query.minScore || "0"), 10);
		if (Number.isNaN(minScore) || minScore < 0)
			return apiError(res, 400, "Invalid minScore");

		const { data: powerUsers, error: queryError } = await supabase
			.from("profiles")
			.select("id, display_name, avatar_url, power_user_score, updated_at")
			.gte("power_user_score", minScore)
			.order("power_user_score", { ascending: false })
			.limit(clampedLimit);

		if (queryError) {
			return apiError(res, 500, "Failed to fetch power users");
		}

		return apiSuccess(res, {
			users: powerUsers || [],
			count: powerUsers?.length || 0,
		});
	},
);
