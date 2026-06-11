/**
 * Sends-per-reach leaders — IG posts ranked by shares/reach.
 *
 * GET /api/analytics?action=sends-per-reach-leaders&accountId=X&periodDays=14
 *
 * Meta's ranking signal applies across IG content. High sends-per-reach =
 * content worth reinforcing. Keep thin samples visible rather than hiding the
 * tile; the dashboard labels them as thin when there are fewer than 3 rows.
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
				"id, content, published_at, permalink, ig_reach, ig_shares, ig_views, instagram_account_id",
			)
			.in("instagram_account_id", targetAccountIds)
			.eq("user_id", user.id)
			.eq("status", "published")
			.gte("ig_reach", MIN_REACH)
			.gte("published_at", cutoff.toISOString());

		const leaders = ((posts || []) as Array<{
			id: string;
			content: string | null;
			published_at: string;
			permalink: string | null;
			ig_reach: number | null;
			ig_shares: number | null;
			ig_views: number | null;
			instagram_account_id: string | null;
		}>)
			.map((p) => {
				const reach = p.ig_reach || 0;
				const shares = p.ig_shares || 0;
				return {
					id: p.id,
					content: p.content,
					publishedAt: p.published_at,
					permalink: p.permalink,
					reach,
					shares,
					views: p.ig_views || 0,
					sendsPerReach: reach > 0 ? shares / reach : 0,
					instagramAccountId: p.instagram_account_id,
				};
			})
			.filter((p) => p.sendsPerReach > 0)
			.sort((a, b) => b.sendsPerReach - a.sendsPerReach)
			.slice(0, limit);

		return apiSuccess(res, { leaders, periodDays });
	},
);
