// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Analytics Handler: group-analytics
 *
 * Retrieve pre-computed group-level analytics from group_analytics table.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { cached, groupAnalyticsKey } from "../../redisCache.js";
import { getSupabase } from "../../supabase.js";
import { parseBodyOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";

const db = () => getSupabase();

// ============================================================================
// Zod Schema
// ============================================================================

const GroupAnalyticsSchema = z.object({
	groupId: z.string().min(1, "groupId is required"),
	days: z.number().int().min(1).max(365).optional().default(30),
});

// ============================================================================
// Handler
// ============================================================================

/**
 * POST /api/analytics?action=group-analytics
 * Get pre-computed group analytics with time-series and summary.
 */
export async function handleGroupAnalytics(
	req: VercelRequest,
	res: VercelResponse,
) {
	const authHeader = req.headers.authorization;
	if (!authHeader?.startsWith("Bearer ")) {
		return apiError(res, 401, "Unauthorized");
	}

	const authToken = authHeader.replace("Bearer ", "");
	const {
		data: { user },
		error: authError,
	} = await db().auth.getUser(authToken);
	if (authError || !user) {
		return apiError(res, 401, "Invalid or expired token");
	}

	const parsed = parseBodyOrError(res, GroupAnalyticsSchema, req.body);
	if (!parsed) return;
	const { groupId, days } = parsed;

	const sinceDate = new Date(Date.now() - days * 24 * 60 * 60 * 1000)
		.toISOString()
		.split("T")[0]!;

	const cacheKey = groupAnalyticsKey(user.id, groupId, days);
	const result = await cached(cacheKey, 300, async () => {
		const { data: analytics, error } = await db()
			.from("group_analytics")
			.select("*")
			.eq("group_id", groupId)
			.eq("user_id", user.id)
			.gte("date", sinceDate)
			.order("date", { ascending: true });

		if (error) {
			throw new Error(error.message);
		}

		// Latest snapshot
		const latest =
			analytics && analytics.length > 0
				? analytics[analytics.length - 1]
				: null;

		// Calculate trends from the time series
		const first = analytics && analytics.length > 1 ? analytics[0] : null;
		const followerGrowthTotal =
			latest && first
				? (latest.total_followers || 0) - (first.total_followers || 0)
				: 0;

		return {
			groupId,
			latest: latest || null,
			timeSeries: analytics || [],
			summary: {
				totalFollowers: latest?.total_followers || 0,
				totalViews: latest?.total_views || 0,
				totalLikes: latest?.total_likes || 0,
				totalReplies: latest?.total_replies || 0,
				avgEngagementRate: latest?.avg_engagement_rate || 0,
				followerGrowthPeriod: followerGrowthTotal,
				topPerformingAccountId: latest?.top_performing_account_id || null,
				accountsCount: latest?.accounts_count || 0,
				postsCount: latest?.posts_count || 0,
			},
		};
	});

	return apiSuccess(res, result);
}
