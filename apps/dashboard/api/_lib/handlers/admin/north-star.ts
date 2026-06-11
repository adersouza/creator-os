/**
 * GET /api/admin/north-star — North Star metrics (admin only)
 *
 * Returns:
 * - northStarPct: % of active users who followed >=1 recommendation AND saw improvement
 * - avgCopilotQueriesPerProUser: avg daily Co-Pilot queries per Pro user
 * - pctUsersPostingViaApp: % of users posting through the app per week
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
			key: `admin-ns:${user.id}`,
			limit: 30,
			windowSeconds: 60,
			failMode: "open",
		});
		if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

		const supabase = getSupabase();

		const now = new Date();
		const oneWeekAgo = new Date(
			now.getTime() - 7 * 24 * 60 * 60 * 1000,
		).toISOString();

		// Active users in last 7 days (have feature_usage entries)
		const { data: activeUsers } = await supabase
			.from("feature_usage")
			.select("user_id")
			.gte("used_at", oneWeekAgo);

		const activeUserIds = [
			...new Set(
				(activeUsers || []).map((r: { user_id: string }) => r.user_id),
			),
		];
		const totalActive = activeUserIds.length;

		// Users who acted on recommendations (QuickWins usage or recommendation_dismissals)
		let followedRec = 0;
		if (totalActive > 0) {
			const { data: recUsers } = await supabase
				.from("feature_usage")
				.select("user_id")
				.in("user_id", activeUserIds)
				.in("feature_name", [
					"QuickWins",
					"quick_win_applied",
					"recommendation_applied",
				])
				.gte("used_at", oneWeekAgo);
			followedRec = new Set(
				(recUsers || []).map((r: { user_id: string }) => r.user_id),
			).size;
		}

		const northStarPct =
			totalActive > 0 ? Math.round((followedRec / totalActive) * 100) : 0;

		// Avg daily Co-Pilot queries per Pro user
		const { count: copilotTotal } = await supabase
			.from("feature_usage")
			.select("id", { count: "exact", head: true })
			.in("feature_name", ["copilot_query", "ai_generate", "co_pilot"])
			.gte("used_at", oneWeekAgo);

		const avgCopilotQueriesPerProUser =
			totalActive > 0
				? Math.round(((copilotTotal || 0) / totalActive / 7) * 10) / 10
				: 0;

		// % users posting via app
		const { data: postersRaw } = await supabase
			.from("feature_usage")
			.select("user_id")
			.in("feature_name", ["post_created", "post_published", "auto_post"])
			.gte("used_at", oneWeekAgo);

		const posterIds = new Set(
			(postersRaw || []).map((r: { user_id: string }) => r.user_id),
		);
		const pctUsersPostingViaApp =
			totalActive > 0 ? Math.round((posterIds.size / totalActive) * 100) : 0;

		return apiSuccess(res, {
			northStarPct,
			avgCopilotQueriesPerProUser,
			pctUsersPostingViaApp,
			totalActiveUsers: totalActive,
			period: "7d",
		});
	},
);
