/**
 * Skip-rate alerts — IG Reels above the skip-rate threshold.
 *
 * GET /api/analytics?action=skip-rate-alerts&accountId=X&periodDays=14&threshold=0.5
 *
 * Skip rate is IG's "viewers who scrolled past without engaging" metric for
 * Reels. Above ~50% is a red flag: the opening seconds aren't holding the
 * audience. Returns Reels sorted by skip rate DESC so operators triage the
 * worst first.
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
	groupId: z.string().optional(),
	periodDays: z.coerce.number().int().min(1).max(90).optional().default(14),
	threshold: z.coerce.number().min(0).max(1).optional().default(0.5),
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
			groupId,
			periodDays,
			threshold,
			limit,
		} = parsed;

		const hasSelectedScope =
			!!accountIdsStr || !!groupId || (!!accountId && accountId !== "ALL");
		let targetAccountIds: string[] = [];
		if (accountIdsStr) {
			targetAccountIds = accountIdsStr.split(",").filter(Boolean);
		} else if (accountId && accountId !== "ALL") {
			targetAccountIds = [accountId];
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
			targetAccountIds = ((group?.account_ids ?? []) as string[]).filter(Boolean);
		}

		if (targetAccountIds.length === 0 && hasSelectedScope) {
			return apiSuccess(res, { alerts: [], threshold, periodDays });
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
			return apiSuccess(res, { alerts: [], threshold, periodDays });
		}

		const cutoff = new Date();
		cutoff.setDate(cutoff.getDate() - periodDays);

		const { data: posts } = await db()
			.from("posts")
			.select(
				"id, content, published_at, permalink, ig_skip_rate, ig_views, ig_reach",
			)
			.in("instagram_account_id", targetAccountIds)
			.eq("user_id", user.id)
			.eq("status", "published")
			.not("ig_skip_rate", "is", null)
			.gte("ig_skip_rate", threshold)
			.gte("published_at", cutoff.toISOString())
			.order("ig_skip_rate", { ascending: false })
			.limit(limit);

		const alerts = ((posts || []) as Array<{
			id: string;
			content: string | null;
			published_at: string;
			permalink: string | null;
			ig_skip_rate: number | null;
			ig_views: number | null;
			ig_reach: number | null;
		}>).map((p) => ({
			id: p.id,
			content: p.content,
			publishedAt: p.published_at,
			permalink: p.permalink,
			skipRate: p.ig_skip_rate || 0,
			views: p.ig_views || 0,
			reach: p.ig_reach || 0,
		}));

		return apiSuccess(res, { alerts, threshold, periodDays });
	},
);
