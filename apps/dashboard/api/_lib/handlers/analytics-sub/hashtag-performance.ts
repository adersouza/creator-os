/**
 * Hashtag Performance
 *
 * GET /api/analytics?action=hashtag-performance&accountId=X&periodDays=30&platform=threads|instagram|all
 *
 * Aggregates engagement per hashtag across the user's published posts.
 * Pure SQL roll-up on existing data — no new API calls. Handles both
 * platforms; per-platform metrics (views/reach/saves) fall through
 * naturally depending on which platform(s) the hashtag appears on.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";

// biome-ignore lint/suspicious/noExplicitAny: posts columns not fully typed
const db = (): any => getSupabase();

const QuerySchema = z.object({
	accountId: z.string().optional(),
	accountIds: z.string().optional(),
	groupId: z.string().optional(),
	periodDays: z.coerce.number().int().min(1).max(365).optional().default(30),
	platform: z.enum(["threads", "instagram", "all"]).optional().default("all"),
	limit: z.coerce.number().int().min(1).max(200).optional().default(50),
});

interface HashtagStats {
	hashtag: string;
	postCount: number;
	platforms: string[];
	totalViews: number;
	totalReach: number;
	totalLikes: number;
	totalReplies: number;
	totalSaves: number;
	totalShares: number;
	sumEngagementRate: number;
}

interface PostRow {
	platform: string | null;
	hashtags: string[] | null;
	content: string | null;
	account_id: string | null;
	instagram_account_id: string | null;
	likes_count: number | null;
	replies_count: number | null;
	views_count: number | null;
	ig_views: number | null;
	ig_reach: number | null;
	ig_comment_count: number | null;
	ig_saved: number | null;
	ig_shares: number | null;
	engagement_rate: number | null;
}

function extractTags(post: PostRow): string[] {
	const seen = new Set<string>();
	if (Array.isArray(post.hashtags)) {
		for (const h of post.hashtags) {
			if (typeof h === "string" && h.length > 0) {
				seen.add(h.toLowerCase().replace(/^#/, ""));
			}
		}
	}
	if (seen.size === 0 && post.content) {
		const matches = post.content.match(/#\w+/g);
		if (matches) {
			for (const m of matches) seen.add(m.toLowerCase().replace(/^#/, ""));
		}
	}
	return [...seen];
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds: accountIdsStr, groupId, periodDays, platform, limit } = parsed;

		const cutoff = new Date();
		cutoff.setDate(cutoff.getDate() - periodDays);
		const cutoffIso = cutoff.toISOString();

		// Scope: start from posts filtered by user_id (works for both platforms).
		// Then narrow by account / platform if requested.
		let query = db()
			.from("posts")
			.select(
				"platform, hashtags, content, account_id, instagram_account_id, likes_count, replies_count, views_count, ig_views, ig_reach, ig_comment_count, ig_saved, ig_shares, engagement_rate",
			)
			.eq("user_id", user.id)
			.eq("status", "published")
			.not("published_at", "is", null)
			.gte("published_at", cutoffIso);

		if (platform !== "all") {
			query = query.eq("platform", platform);
		}

		let ids: string[] = [];
		if (accountIdsStr) {
			ids = accountIdsStr.split(",").filter(Boolean);
		} else if (groupId) {
			const { data: group, error: groupError } = await db()
				.from("account_groups")
				.select("account_ids")
				.eq("id", groupId)
				.eq("user_id", user.id)
				.maybeSingle();
			if (groupError) {
				return apiError(res, 500, "Failed to resolve account group", {
					details: groupError.message,
				});
			}
			ids = ((group?.account_ids ?? []) as string[]).filter(Boolean);
		}

		if (ids.length > 0) {
			query = query.or(
				`account_id.in.(${ids.join(",")}),instagram_account_id.in.(${ids.join(",")})`,
			);
		} else if (accountIdsStr || groupId) {
			return apiSuccess(res, { hashtags: [], totalPosts: 0 });
		} else if (accountId && accountId !== "ALL") {
			query = query.or(
				`account_id.eq.${accountId},instagram_account_id.eq.${accountId}`,
			);
		}

		const { data: posts, error } = await query;
		if (error) {
			return apiError(res, 500, "Failed to fetch posts", {
				details: error.message,
			});
		}
		if (!posts || posts.length === 0) {
			return apiSuccess(res, { hashtags: [], totalPosts: 0 });
		}

		const hashtagMap = new Map<string, HashtagStats>();

		for (const p of posts as PostRow[]) {
			const tags = extractTags(p);
			if (tags.length === 0) continue;

			// Unify metrics across platforms. Threads uses views_count / replies_count;
			// IG uses ig_views / ig_comment_count / ig_reach / ig_saved / ig_shares.
			const isIg = p.platform === "instagram";
			const views = isIg ? p.ig_views ?? 0 : p.views_count ?? 0;
			const replies = isIg ? p.ig_comment_count ?? 0 : p.replies_count ?? 0;
			const reach = p.ig_reach ?? 0; // IG-only; threads has no reach field
			const saves = p.ig_saved ?? 0; // IG-only
			const shares = p.ig_shares ?? 0; // IG-only (threads doesn't expose per-post)
			const likes = p.likes_count ?? 0;
			const er = p.engagement_rate ?? 0;

			for (const tag of tags) {
				const cur = hashtagMap.get(tag) || {
					hashtag: tag,
					postCount: 0,
					platforms: [],
					totalViews: 0,
					totalReach: 0,
					totalLikes: 0,
					totalReplies: 0,
					totalSaves: 0,
					totalShares: 0,
					sumEngagementRate: 0,
				};
				cur.postCount++;
				cur.totalViews += views;
				cur.totalReach += reach;
				cur.totalLikes += likes;
				cur.totalReplies += replies;
				cur.totalSaves += saves;
				cur.totalShares += shares;
				cur.sumEngagementRate += er;
				if (p.platform && !cur.platforms.includes(p.platform)) {
					cur.platforms.push(p.platform);
				}
				hashtagMap.set(tag, cur);
			}
		}

		// Materialize avg engagement rate; sort by total engagement (likes + replies + saves).
		const hashtags = [...hashtagMap.values()]
			.map((h) => ({
				hashtag: h.hashtag,
				postCount: h.postCount,
				platforms: h.platforms,
				totalViews: h.totalViews,
				totalReach: h.totalReach,
				totalLikes: h.totalLikes,
				totalReplies: h.totalReplies,
				totalSaves: h.totalSaves,
				totalShares: h.totalShares,
				avgEngagementRate:
					h.postCount > 0
						? Number.parseFloat((h.sumEngagementRate / h.postCount).toFixed(2))
						: 0,
			}))
			.sort(
				(a, b) =>
					b.totalLikes +
					b.totalReplies +
					b.totalSaves -
					(a.totalLikes + a.totalReplies + a.totalSaves),
			)
			.slice(0, limit);

		return apiSuccess(res, { hashtags, totalPosts: posts.length });
	},
);
