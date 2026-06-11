// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Competitor Performance Trends Over Time
 *
 * GET /api/analytics?action=competitor-trends&competitorId=X&days=30
 *
 * Queries competitor_metrics_history for a given competitor over the period.
 * Returns daily metrics array + trend summary (engagement rate change, follower growth).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess, getAuthUserOrError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { verifyCompetitorOwnership } from "../helpers/verifyOwnership.js";

// biome-ignore lint/suspicious/noExplicitAny: table not yet in generated types
const db = (): any => getSupabase();

const CompetitorTrendsQuerySchema = z.object({
	competitorId: z.string().min(1, "competitorId is required"),
	days: z.coerce.number().int().min(1).max(90).optional().default(30),
});

interface HistoryRow {
	date: string;
	followers_count: number;
	avg_engagement_rate: number;
	total_posts: number;
	avg_views: number;
	avg_likes: number;
	top_post_engagement: number;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	const parsed = parseQueryOrError(res, CompetitorTrendsQuerySchema, req.query);
	if (!parsed) return;

	const { competitorId, days } = parsed;
	const userId = user.id;

	try {
		// Verify competitor belongs to user via competitors table
		const competitor = await verifyCompetitorOwnership(
			res,
			competitorId,
			userId,
		);
		if (!competitor) return;

		// Query competitor_metrics_history for the period
		const cutoffDate = new Date(Date.now() - days * 86_400_000)
			.toISOString()
			.split("T")[0]!;

		const { data: historyData, error: historyError } = await db()
			.from("competitor_metrics_history")
			.select(
				"date, followers_count, avg_engagement_rate, total_posts, avg_views, avg_likes, top_post_engagement",
			)
			.eq("competitor_id", competitorId)
			.gte("date", cutoffDate)
			.order("date", { ascending: true });

		if (historyError) {
			logger.error("[competitor-trends] Failed to fetch history", {
				error: historyError.message,
			});
			return apiError(res, 500, "Failed to fetch competitor history");
		}

		const rows: HistoryRow[] = historyData ?? [];

		// Build history array
		const history = rows.map((row) => ({
			date: row.date,
			followersCount: row.followers_count ?? 0,
			avgEngagementRate: Number(row.avg_engagement_rate ?? 0),
			totalPosts: row.total_posts ?? 0,
			avgViews: row.avg_views ?? 0,
			avgLikes: row.avg_likes ?? 0,
			topPostEngagement: row.top_post_engagement ?? 0,
		}));

		// Calculate trends
		const trends = computeTrends(rows);

		return apiSuccess(res, {
			competitorId,
			username: competitor.username,
			platform: competitor.platform,
			periodDays: days,
			history,
			trends,
		});
	} catch (error) {
		logger.error("[competitor-trends] Unexpected error", {
			error: error instanceof Error ? error.message : String(error),
		});
		return apiError(res, 500, "Internal server error");
	}
}

function computeTrends(rows: HistoryRow[]): {
	followerGrowth: number;
	engagementRateChange: number;
	postingFrequencyChange: number;
	direction: "improving" | "declining" | "stable";
} {
	if (rows.length < 2) {
		return {
			followerGrowth: 0,
			engagementRateChange: 0,
			postingFrequencyChange: 0,
			direction: "stable",
		};
	}

	const first = rows[0];
	const last = rows[rows.length - 1];

	// Follower growth percentage
	const followerGrowth =
		first!.followers_count > 0
			? Math.round(
					((last!.followers_count - first!.followers_count) /
						first!.followers_count) *
						10000,
				) / 100
			: 0;

	// Engagement rate change percentage
	const firstEngagement = Number(first!.avg_engagement_rate ?? 0);
	const lastEngagement = Number(last!.avg_engagement_rate ?? 0);
	const engagementRateChange =
		firstEngagement > 0
			? Math.round(
					((lastEngagement - firstEngagement) / firstEngagement) * 10000,
				) / 100
			: 0;

	// Posting frequency change: compare first half vs second half average posts
	const midIdx = Math.floor(rows.length / 2);
	const firstHalf = rows.slice(0, midIdx);
	const secondHalf = rows.slice(midIdx);

	const avgPostsFirst =
		firstHalf.length > 0
			? firstHalf.reduce((s, r) => s + (r.total_posts ?? 0), 0) /
				firstHalf.length
			: 0;
	const avgPostsSecond =
		secondHalf.length > 0
			? secondHalf.reduce((s, r) => s + (r.total_posts ?? 0), 0) /
				secondHalf.length
			: 0;

	const postingFrequencyChange =
		avgPostsFirst > 0
			? Math.round(((avgPostsSecond - avgPostsFirst) / avgPostsFirst) * 10000) /
				100
			: 0;

	// Overall direction based on engagement + followers
	let score = 0;
	if (followerGrowth > 1) score++;
	if (followerGrowth < -1) score--;
	if (engagementRateChange > 5) score++;
	if (engagementRateChange < -5) score--;

	const direction: "improving" | "declining" | "stable" =
		score > 0 ? "improving" : score < 0 ? "declining" : "stable";

	return {
		followerGrowth,
		engagementRateChange,
		postingFrequencyChange,
		direction,
	};
}
