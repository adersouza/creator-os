/**
 * Quote-reply ratio — Threads-specific conversation quality signal.
 *
 * GET /api/analytics?action=quote-reply-ratio&periodDays=14
 *
 * Quotes-to-replies ratio surfaces accounts whose posts make people want to
 * share-with-commentary rather than just reply in-thread. High ratio = your
 * content is being spread; low = it's a closed conversation. Fleet avg +
 * per-account so operators can compare.
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
	minPosts: z.coerce.number().int().min(1).max(50).optional().default(3),
});

// biome-ignore lint/suspicious/noExplicitAny: posts columns aren't fully in generated types
const db = (): any => getSupabase();

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds: accountIdsStr, periodDays, minPosts } = parsed;

		let targetAccountIds: string[] = [];
		if (accountIdsStr) {
			targetAccountIds = accountIdsStr.split(",").filter(Boolean);
		} else if (accountId && accountId !== "ALL") {
			targetAccountIds = [accountId];
		}

		if (targetAccountIds.length === 0) {
			const { data: accounts } = await db()
				.from("accounts")
				.select("id, username")
				.eq("user_id", user.id);
			targetAccountIds = (accounts || []).map((a: { id: string }) => a.id);
		} else {
			const { data: owned } = await db()
				.from("accounts")
				.select("id, username")
				.eq("user_id", user.id)
				.in("id", targetAccountIds);
			targetAccountIds = (owned || []).map((a: { id: string }) => a.id);
		}

		if (targetAccountIds.length === 0) {
			return apiSuccess(res, { fleetRatio: 0, accounts: [], periodDays });
		}

		const { data: accountRows } = await db()
			.from("accounts")
			.select("id, username")
			.in("id", targetAccountIds)
			.eq("user_id", user.id);

		const usernameById = new Map<string, string | null>();
		for (const a of (accountRows || []) as Array<{
			id: string;
			username: string | null;
		}>) {
			usernameById.set(a.id, a.username);
		}

		const cutoff = new Date();
		cutoff.setDate(cutoff.getDate() - periodDays);

		const { data: posts } = await db()
			.from("posts")
			.select("account_id, quotes_count, replies_count")
			.in("account_id", targetAccountIds)
			.eq("user_id", user.id)
			.eq("status", "published")
			.gte("published_at", cutoff.toISOString());

		// Per-account rollup — we need ≥ minPosts to emit a ratio.
		const perAccount = new Map<
			string,
			{ quotes: number; replies: number; posts: number }
		>();
		for (const p of (posts || []) as Array<{
			account_id: string;
			quotes_count: number | null;
			replies_count: number | null;
		}>) {
			const existing = perAccount.get(p.account_id) || {
				quotes: 0,
				replies: 0,
				posts: 0,
			};
			existing.quotes += p.quotes_count || 0;
			existing.replies += p.replies_count || 0;
			existing.posts += 1;
			perAccount.set(p.account_id, existing);
		}

		let fleetQuotes = 0;
		let fleetReplies = 0;
		const accountRatios = [];
		for (const [aid, stats] of perAccount) {
			fleetQuotes += stats.quotes;
			fleetReplies += stats.replies;
			if (stats.posts < minPosts) continue;
			if (stats.replies === 0 && stats.quotes === 0) continue;
			const ratio = stats.replies > 0 ? stats.quotes / stats.replies : null;
			accountRatios.push({
				accountId: aid,
				username: usernameById.get(aid) || null,
				ratio,
				quotes: stats.quotes,
				replies: stats.replies,
				posts: stats.posts,
			});
		}

		accountRatios.sort((a, b) => {
			// Nulls last, then ratio DESC.
			if (a.ratio == null && b.ratio == null) return 0;
			if (a.ratio == null) return 1;
			if (b.ratio == null) return -1;
			return b.ratio - a.ratio;
		});

		const fleetRatio =
			fleetReplies > 0 ? fleetQuotes / fleetReplies : null;

		return apiSuccess(res, {
			fleetRatio,
			accounts: accountRatios,
			periodDays,
		});
	},
);
