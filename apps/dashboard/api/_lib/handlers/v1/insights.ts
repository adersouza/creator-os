/**
 * Public API v1 — GET /api/v1/insights
 * CES score, quick wins, and recommendations.
 *
 * Query params: account_id (required)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabase } from "../../supabase.js";
import { withApiKey } from "../../withApiKey.js";
import { verifyAnyAccountOwnership } from "../helpers/verifyOwnership.js";

export default withApiKey(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const db = getSupabase();
		const accountId = req.query.account_id as string;
		if (!accountId) return apiError(res, 400, "account_id required");

		// Verify ownership
		const owned = await verifyAnyAccountOwnership(res, accountId, user.id);
		if (!owned) return;

		// Latest analytics snapshot from account_analytics
		// Defense-in-depth: filter by user_id alongside account_id (RLS should already handle this)
		// biome-ignore lint/suspicious/noExplicitAny: Supabase deep type recursion (TS2589)
		const { data: analytics, error: analyticsError } = await (db as any)
			.from("account_analytics")
			.select(
				"engagement_rate, total_views, total_likes, total_replies, follower_growth",
			)
			.eq("account_id", accountId)
			.eq("user_id", user.id)
			.order("date", { ascending: false })
			.limit(1)
			.maybeSingle();

		if (analyticsError) {
			logger.error("Failed to fetch analytics", {
				error: analyticsError.message ?? JSON.stringify(analyticsError),
			});
			return apiError(res, 500, "Internal server error");
		}

		// Quick wins
		// Defense-in-depth: filter by user_id alongside account_id
		const { data: quickWins, error: quickWinsError } = await db
			.from("quick_wins")
			.select("id, title, description, priority, status, created_at")
			.eq("account_id", accountId)
			.eq("user_id", user.id)
			.eq("status", "pending")
			.order("priority", { ascending: false })
			.limit(10);

		if (quickWinsError) {
			logger.error("Failed to fetch quick wins", {
				error: quickWinsError.message ?? JSON.stringify(quickWinsError),
			});
			return apiError(res, 500, "Internal server error");
		}

		return apiSuccess(res, {
			account_id: accountId,
			engagement: {
				rate: analytics?.engagement_rate || null,
				total_views: analytics?.total_views || null,
				total_likes: analytics?.total_likes || null,
				total_replies: analytics?.total_replies || null,
				follower_growth: analytics?.follower_growth || null,
			},
			quickWins: quickWins || [],
		});
	},
	"read",
);
