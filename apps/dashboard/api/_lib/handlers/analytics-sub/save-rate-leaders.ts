/**
 * Save-rate leaders — IG posts ranked by saves/reach.
 *
 * GET /api/analytics?action=save-rate-leaders&accountId=X&periodDays=14
 *
 * Saves are the strongest "I'll come back to this" signal. High save rate
 * surfaces content worth reinforcing (lists, guides, how-tos). Applies to
 * all IG media types, not just Reels. Keep thin samples visible rather than
 * hiding the tile; the dashboard labels sparse leaderboards explicitly.
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
	limit: z.coerce.number().int().min(1).max(200).optional().default(5),
});

const MIN_REACH = 1;

// biome-ignore lint/suspicious/noExplicitAny: posts columns aren't fully in generated types
const db = (): any => getSupabase();

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds: accountIdsStr, periodDays, limit } = parsed;

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
				"id, content, published_at, permalink, ig_saved, ig_reach, ig_views, media_urls",
			)
			.in("instagram_account_id", targetAccountIds)
			.eq("user_id", user.id)
			.eq("status", "published")
			.not("ig_saved", "is", null)
			.gte("ig_reach", MIN_REACH)
			.gte("published_at", cutoff.toISOString());

		const leaders = ((posts || []) as Array<{
			id: string;
			content: string | null;
			published_at: string;
			permalink: string | null;
			ig_saved: number | null;
			ig_reach: number | null;
			ig_views: number | null;
			media_urls: string[] | null;
		}>)
			.map((p) => {
				const reach = p.ig_reach || 0;
				const saved = p.ig_saved || 0;
				return {
					id: p.id,
					content: p.content,
					publishedAt: p.published_at,
					permalink: p.permalink,
					saved,
					reach,
					views: p.ig_views || 0,
					saveRate: reach > 0 ? saved / reach : 0,
					mediaUrl:
						Array.isArray(p.media_urls) && p.media_urls.length > 0
							? p.media_urls[0]
							: null,
				};
			})
			.filter((p) => p.saveRate > 0)
			.sort((a, b) => b.saveRate - a.saveRate)
			.slice(0, limit);

		return apiSuccess(res, { leaders, periodDays });
	},
);
