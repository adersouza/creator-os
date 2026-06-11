// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Public API v1 — GET /api/v1/analytics
 * Account-level analytics for the authenticated API key user.
 *
 * Query params: account_id (required), period (7d|30d|90d)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { getFollowerCount } from "../../followerCount.js";
import { logger } from "../../logger.js";
import { getSupabase, getSupabaseAny } from "../../supabase.js";
import { withApiKey } from "../../withApiKey.js";

interface IgAccRow {
	id: string;
	username: string | null;
	follower_count: number | null;
}

interface PostMetricsRow {
	id: string;
	views_count: number | null;
	likes_count: number | null;
	replies_count: number | null;
	ig_saved: number | null;
	shares_count: number | null;
	published_at: string | null;
}

interface AccountAnalyticsRow {
	date: string;
	followers_count: number | null;
	total_views: number | null;
	total_likes: number | null;
	total_replies: number | null;
	total_shares?: number | null | undefined;
	engagement_rate?: number | null | undefined;
}

export default withApiKey(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const db = getSupabase();
		const dbAny = getSupabaseAny();
		const accountId = req.query.account_id as string;
		if (!accountId) return apiError(res, 400, "account_id required");
		// #594: Validate account_id format
		if (typeof accountId !== "string" || accountId.length > 100) {
			return apiError(res, 400, "Invalid account_id format");
		}

		const period = (req.query.period as string) || "30d";
		const days =
			period === "7d" ? 7 : period === "14d" ? 14 : period === "90d" ? 90 : 30;
		const since = new Date(
			Date.now() - days * 24 * 60 * 60 * 1000,
		).toISOString();
		const includeHistory = req.query.include_history === "true";

		// Verify account ownership — try accounts first, fall back to instagram_accounts
		const { data: acc, error: accError } = await db
			.from("accounts")
			.select("id, username, followers_count")
			.eq("id", accountId)
			.eq("user_id", user.id)
			.maybeSingle();

		if (accError && accError.code !== "PGRST116") {
			logger.error("Failed to fetch account", {
				error: accError.message ?? JSON.stringify(accError),
			});
			return apiError(res, 500, "Internal server error");
		}

		let igAcc: IgAccRow | null = null;
		if (!acc) {
			// Only query instagram_accounts if not found in accounts
			// instagram_accounts uses follower_count (singular); accounts uses followers_count (plural)
			const { data, error: igAccError } = await db
				.from("instagram_accounts")
				.select("id, username, follower_count")
				.eq("id", accountId)
				.eq("user_id", user.id)
				.maybeSingle();

			if (igAccError && igAccError.code !== "PGRST116") {
				logger.error("Failed to fetch instagram account", {
					error: igAccError.message ?? JSON.stringify(igAccError),
				});
				return apiError(res, 500, "Internal server error");
			}
			igAcc = data;
		}

		const account = acc || igAcc;
		// #598: Generic error to prevent account enumeration via API
		if (!account) return apiError(res, 403, "Forbidden");

		// Get posts + latest analytics snapshot in parallel
		// Query both account_id and instagram_account_id to include IG posts
		const [postsResult, analyticsSnap] = await Promise.all([
			db
				.from("posts")
				.select(
					"id, views_count, likes_count, replies_count, ig_saved, shares_count, published_at",
				)
				.or(`account_id.eq.${accountId},instagram_account_id.eq.${accountId}`)
				.eq("user_id", user.id)
				.eq("status", "published")
				.gte("published_at", since)
				.order("published_at", { ascending: false }),
			// Latest synced analytics row (more accurate than live account snapshot)
			// Defense-in-depth: filter by user_id alongside account_id
			dbAny
				.from("account_analytics")
				.select(
					"followers_count, total_views, total_likes, total_replies, total_shares, engagement_rate",
				)
				.eq("account_id", accountId)
				.eq("user_id", user.id)
				.order("date", { ascending: false })
				.limit(1)
				.maybeSingle(),
		]);

		if (postsResult.error) {
			logger.error("Failed to fetch posts", {
				error: postsResult.error.message ?? JSON.stringify(postsResult.error),
			});
			return apiError(res, 500, "Internal server error");
		}

		const allPosts = (postsResult.data || []) as PostMetricsRow[];
		const totalViews = allPosts.reduce(
			(s: number, p: PostMetricsRow) => s + (p.views_count || 0),
			0,
		);
		const totalLikes = allPosts.reduce(
			(s: number, p: PostMetricsRow) => s + (p.likes_count || 0),
			0,
		);
		const totalReplies = allPosts.reduce(
			(s: number, p: PostMetricsRow) => s + (p.replies_count || 0),
			0,
		);
		const totalSaves = allPosts.reduce(
			(s: number, p: PostMetricsRow) => s + (p.ig_saved || 0),
			0,
		);
		const totalEngagement = totalLikes + totalReplies + totalSaves;

		// Prefer synced analytics followers over stale account snapshot
		const snap = analyticsSnap.data;
		const followerCount =
			(snap?.followers_count ?? 0) || getFollowerCount(acc ?? igAcc ?? {});
		const engagementRate =
			followerCount > 0
				? (totalEngagement / (allPosts.length * followerCount)) * 100
				: 0;

		// Top posts by engagement
		const topPosts = [...allPosts]
			.sort((a: PostMetricsRow, b: PostMetricsRow) => {
				const engA =
					(a.likes_count || 0) + (a.replies_count || 0) + (a.ig_saved || 0);
				const engB =
					(b.likes_count || 0) + (b.replies_count || 0) + (b.ig_saved || 0);
				return engB - engA;
			})
			.slice(0, 5)
			.map((p: PostMetricsRow) => ({
				id: p.id,
				views: p.views_count,
				likes: p.likes_count,
				replies: p.replies_count,
				saves: p.ig_saved,
				published_at: p.published_at,
			}));

		// Period deltas: compare current period vs previous period using account_analytics
		let periodDelta: {
			followers_gained: number;
			views_gained: number;
			likes_gained: number;
			replies_gained: number;
		} | null = null;

		try {
			const prevSince = new Date(
				Date.now() - days * 2 * 24 * 60 * 60 * 1000,
			).toISOString();
			const { data: histRows } = await dbAny
				.from("account_analytics")
				.select(
					"date, followers_count, total_views, total_likes, total_replies",
				)
				.eq("account_id", accountId)
				.eq("user_id", user.id)
				.gte("date", prevSince.split("T")[0]!)
				.order("date", { ascending: true });

			const analyticsRows = (histRows || []) as AccountAnalyticsRow[];
			if (analyticsRows.length >= 2) {
				const midpoint = new Date(Date.now() - days * 24 * 60 * 60 * 1000)
					.toISOString()
					.split("T")[0]!;

				const prev = analyticsRows.filter((r) => r.date < midpoint!);
				const curr = analyticsRows.filter((r) => r.date >= midpoint!);

				const firstPrev = prev[0];
				const lastPrev = prev[prev.length - 1];
				const firstCurr = curr[0];
				const lastCurr = curr[curr.length - 1];

				if (firstPrev && lastPrev && firstCurr && lastCurr) {
					periodDelta = {
						followers_gained:
							(lastCurr.followers_count ?? 0) -
							(firstCurr.followers_count ?? 0),
						views_gained:
							(lastCurr.total_views ?? 0) - (firstCurr.total_views ?? 0),
						likes_gained:
							(lastCurr.total_likes ?? 0) - (firstCurr.total_likes ?? 0),
						replies_gained:
							(lastCurr.total_replies ?? 0) - (firstCurr.total_replies ?? 0),
					};
				}
			}
		} catch {
			// Non-fatal — deltas are optional
		}

		// Optional: daily breakdown from account_analytics
		let dailyHistory:
			| {
					date: string;
					followers: number;
					views: number;
					likes: number;
					replies: number;
			  }[]
			| undefined;
		if (includeHistory) {
			try {
				const { data: dayRows } = await dbAny
					.from("account_analytics")
					.select(
						"date, followers_count, total_views, total_likes, total_replies",
					)
					.eq("account_id", accountId)
					.eq("user_id", user.id)
					.gte("date", since.split("T")[0]!)
					.order("date", { ascending: true });

				const analyticsDayRows = (dayRows || []) as AccountAnalyticsRow[];
				if (analyticsDayRows.length > 0) {
					dailyHistory = analyticsDayRows.map((r) => ({
						date: r.date,
						followers: r.followers_count ?? 0,
						views: r.total_views ?? 0,
						likes: r.total_likes ?? 0,
						replies: r.total_replies ?? 0,
					}));
				}
			} catch {
				// Non-fatal
			}
		}

		return apiSuccess(res, {
			account_id: accountId,
			period,
			followers: { current: followerCount },
			engagement: {
				rate: Math.round(engagementRate * 100) / 100,
				total: totalEngagement,
				views: totalViews,
				likes: totalLikes,
				replies: totalReplies,
				saves: totalSaves,
			},
			postCount: allPosts.length,
			postingFrequency:
				days > 0 ? Math.round((allPosts.length / days) * 100) / 100 : 0,
			topPosts,
			periodDelta,
			...(dailyHistory ? { dailyHistory } : {}),
		});
	},
	"read",
);
