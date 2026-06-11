/**
 * Watch-time leaders — IG Reels ranked by average watch time.
 *
 * GET /api/analytics?action=watch-time-leaders&accountId=X&periodDays=14
 *
 * Average watch time is IG's retention-quality signal. Longer avg-watch on
 * comparable views = the Reel is holding attention. Returns top N Reels
 * sorted by ig_reels_avg_watch_time DESC, filtered to those with enough
 * views to be meaningful (default 500).
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
	periodDays: z.coerce.number().int().min(1).max(90).optional().default(14),
	minViews: z.coerce.number().int().min(0).max(100000).optional().default(500),
	limit: z.coerce.number().int().min(1).max(20).optional().default(5),
});

// biome-ignore lint/suspicious/noExplicitAny: posts columns aren't fully in generated types
const db = (): any => getSupabase();

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const {
			accountId,
			accountIds: accountIdsStr,
			periodDays,
			minViews,
			limit,
		} = parsed;

		let targetAccountIds: string[] = [];
		if (accountIdsStr) {
			targetAccountIds = accountIdsStr.split(",").filter(Boolean);
		} else if (accountId && accountId !== "ALL") {
			targetAccountIds = [accountId];
		}

		if (targetAccountIds.length === 0) {
			const { data: igAccounts } = await db()
				.from("instagram_accounts")
				.select("id")
				.eq("user_id", user.id);
			targetAccountIds = (igAccounts || []).map((a: { id: string }) => a.id);
		} else {
			const { data: owned } = await db()
				.from("instagram_accounts")
				.select("id")
				.eq("user_id", user.id)
				.in("id", targetAccountIds);
			targetAccountIds = (owned || []).map((a: { id: string }) => a.id);
		}

		if (targetAccountIds.length === 0) {
			return apiSuccess(res, { leaders: [], periodDays });
		}

		const cutoff = new Date();
		cutoff.setDate(cutoff.getDate() - periodDays);

		const { data: posts } = await db()
			.from("posts")
			.select(
				"id, content, published_at, permalink, ig_reels_avg_watch_time, ig_views, ig_reach",
			)
			.in("instagram_account_id", targetAccountIds)
			.eq("user_id", user.id)
			.eq("status", "published")
			.not("ig_reels_avg_watch_time", "is", null)
			.gte("ig_views", minViews)
			.gte("published_at", cutoff.toISOString())
			.order("ig_reels_avg_watch_time", { ascending: false })
			.limit(limit);

		const leaders = ((posts || []) as Array<{
			id: string;
			content: string | null;
			published_at: string;
			permalink: string | null;
			ig_reels_avg_watch_time: number | null;
			ig_views: number | null;
			ig_reach: number | null;
		}>).map((p) => ({
			id: p.id,
			content: p.content,
			publishedAt: p.published_at,
			permalink: p.permalink,
			avgWatchMs: p.ig_reels_avg_watch_time || 0,
			views: p.ig_views || 0,
			reach: p.ig_reach || 0,
		}));

		return apiSuccess(res, { leaders, periodDays });
	},
);
