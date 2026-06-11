// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Follower-change attribution
 *
 * GET /api/analytics?action=follower-attribution&accountId=X&periodDays=30
 *
 * For each day in the period, return the net follower change plus the posts
 * that were published that day. No prediction — just surfacing "which post
 * days moved the needle" by joining account_analytics.follower_growth against
 * posts.published_at.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";

const QuerySchema = z.object({
	accountId: z.string().optional(),
	accountIds: z.string().optional(),
	periodDays: z.coerce.number().int().min(1).max(365).optional().default(30),
	platform: z.string().optional(),
});

// biome-ignore lint/suspicious/noExplicitAny: posts columns aren't fully in generated types
const db = (): any => getSupabase();

interface DayBucket {
	date: string;
	followerGrowth: number;
	posts: Array<{
		id: string;
		content: string | null;
		likes: number;
		replies: number;
		views: number;
		permalink: string | null;
	}>;
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds: accountIdsStr, periodDays, platform } = parsed;

		let targetAccountIds: string[] = [];
		if (accountIdsStr) {
			targetAccountIds = accountIdsStr.split(",").filter(Boolean);
		} else if (accountId && accountId !== "ALL") {
			targetAccountIds = [accountId];
		}

		const includeThreads = !platform || platform === "threads";
		const includeInstagram = !platform || platform === "instagram";

		if (targetAccountIds.length === 0) {
			const [threadsRes, igRes] = await Promise.all([
				includeThreads
					? db()
						.from("accounts")
						.select("id")
						.eq("user_id", user.id)
						.eq("is_retired", false)
					: Promise.resolve({ data: [] }),
				includeInstagram
					? db()
						.from("instagram_accounts")
						.select("id")
						.eq("user_id", user.id)
						.eq("is_active", true)
					: Promise.resolve({ data: [] }),
			]);
			targetAccountIds = [
				...((threadsRes.data || []) as Array<{ id: string }>).map((a) => a.id),
				...((igRes.data || []) as Array<{ id: string }>).map((a) => a.id),
			];
		} else {
			const [threadsRes, igRes] = await Promise.all([
				includeThreads
					? db()
						.from("accounts")
						.select("id")
						.eq("user_id", user.id)
						.in("id", targetAccountIds)
					: Promise.resolve({ data: [] }),
				includeInstagram
					? db()
						.from("instagram_accounts")
						.select("id")
						.eq("user_id", user.id)
						.in("id", targetAccountIds)
					: Promise.resolve({ data: [] }),
			]);
			targetAccountIds = [
				...((threadsRes.data || []) as Array<{ id: string }>).map((a) => a.id),
				...((igRes.data || []) as Array<{ id: string }>).map((a) => a.id),
			];
		}

		if (targetAccountIds.length === 0) {
			return apiSuccess(res, { days: [], periodDays });
		}

		const cutoff = new Date();
		cutoff.setDate(cutoff.getDate() - periodDays);
		const cutoffDate = cutoff.toISOString().split("T")[0]!;
		const cutoffIso = cutoff.toISOString();

		const { data: analyticsRows } = await db()
			.from("account_analytics")
			.select("date, follower_growth")
			.in("account_id", targetAccountIds)
			.gte("date", cutoffDate)
			.order("date", { ascending: true });

		const growthByDate = new Map<string, number>();
		for (const row of (analyticsRows || []) as Array<{
			date: string;
			follower_growth: number | null;
		}>) {
			growthByDate.set(
				row.date,
				(growthByDate.get(row.date) || 0) + (row.follower_growth || 0),
			);
		}

		const [threadPostsRes, igPostsRes] = await Promise.all([
			includeThreads
				? db()
					.from("posts")
					.select(
						"id, content, published_at, likes_count, replies_count, views_count, ig_views, permalink",
					)
					.in("account_id", targetAccountIds)
					.eq("user_id", user.id)
					.eq("status", "published")
					.not("published_at", "is", null)
					.gte("published_at", cutoffIso)
				: Promise.resolve({ data: [] }),
			includeInstagram
				? db()
					.from("posts")
					.select(
						"id, content, published_at, likes_count, replies_count, views_count, ig_views, permalink",
					)
					.in("instagram_account_id", targetAccountIds)
					.eq("user_id", user.id)
					.eq("status", "published")
					.not("published_at", "is", null)
					.gte("published_at", cutoffIso)
				: Promise.resolve({ data: [] }),
		]);
		const posts = [
			...((threadPostsRes.data || []) as Array<{
				id: string;
				content: string | null;
				published_at: string;
				likes_count: number | null;
				replies_count: number | null;
				views_count: number | null;
				ig_views: number | null;
				permalink: string | null;
			}>),
			...((igPostsRes.data || []) as Array<{
				id: string;
				content: string | null;
				published_at: string;
				likes_count: number | null;
				replies_count: number | null;
				views_count: number | null;
				ig_views: number | null;
				permalink: string | null;
			}>),
		];

		const postsByDate = new Map<string, DayBucket["posts"]>();
		for (const p of posts as Array<{
			id: string;
			content: string | null;
			published_at: string;
			likes_count: number | null;
			replies_count: number | null;
			views_count: number | null;
			ig_views: number | null;
			permalink: string | null;
		}>) {
			const day = p.published_at.split("T")[0]!;
			const arr = postsByDate.get(day!) || [];
			arr.push({
				id: p.id,
				content: p.content,
				likes: p.likes_count || 0,
				replies: p.replies_count || 0,
				views: (p.views_count || p.ig_views) || 0,
				permalink: p.permalink,
			});
			postsByDate.set(day!, arr);
		}

		const allDates = new Set<string>([
			...growthByDate.keys(),
			...postsByDate.keys(),
		]);
		// Posts within each day are sorted by views descending so consumers can
		// safely treat posts[0] as "today's lead post by views". The endpoint
		// does NOT attempt follow attribution — daily-diff follower_growth has
		// no causal link to specific posts. Consumers must label accordingly.
		const days: DayBucket[] = [...allDates]
			.sort()
			.map((date) => ({
				date,
				followerGrowth: growthByDate.get(date) || 0,
				posts: (postsByDate.get(date) || [])
					.slice()
					.sort((a, b) => b.views - a.views),
			}));

		return apiSuccess(res, { days, periodDays });
	},
);
