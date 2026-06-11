/**
 * GET /api/admin/feature-usage — Feature usage analytics (admin only)
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAdminRole } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

export default withAdminRole(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const { checkRateLimit } = await import("../../rateLimiter.js");
		const rl = await checkRateLimit({
			key: `admin-fu:${user.id}`,
			limit: 30,
			windowSeconds: 60,
			failMode: "open",
		});
		if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

		const period = parseInt(String(req.query.period || "30"), 10);
		const days = Math.min(Math.max(period, 1), 365);
		const since = new Date(Date.now() - days * 86400000).toISOString();

		const supabase = getSupabase();
		const { data: rows, error } = await supabase
			.from("feature_usage")
			.select("feature_name, user_id")
			.gte("used_at", since);

		if (error) return apiError(res, 500, "Failed to query feature usage");

		// Aggregate by feature name
		const features: Record<string, { count: number; users: Set<string> }> = {};
		for (const row of rows || []) {
			const name = row.feature_name;
			if (!features[name]) features[name] = { count: 0, users: new Set() };
			features[name].count++;
			features[name].users.add(row.user_id);
		}

		const result = Object.entries(features)
			.map(([name, { count, users }]) => ({
				name,
				count,
				uniqueUsers: users.size,
			}))
			.sort((a, b) => b.count - a.count);

		return apiSuccess(res, { features: result, period: days });
	},
);
