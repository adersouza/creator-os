// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Link-click leaders — top outbound URLs from Threads posts.
 *
 * GET /api/analytics?action=link-click-leaders&periodDays=14
 *
 * Reads threads_link_click_breakdown (per-account per-day per-URL). Revenue
 * proxy: the URLs driving the most click-throughs are the offers, affiliate
 * links, or landing pages doing the work. Sums clicks across the window
 * per (account_id, link_url).
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
	limit: z.coerce.number().int().min(1).max(30).optional().default(8),
});

// biome-ignore lint/suspicious/noExplicitAny: types aren't exhaustive
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
			const { data: accounts } = await db()
				.from("accounts")
				.select("id")
				.eq("user_id", user.id);
			targetAccountIds = (accounts || []).map((a: { id: string }) => a.id);
		} else {
			const { data: owned } = await db()
				.from("accounts")
				.select("id")
				.eq("user_id", user.id)
				.in("id", targetAccountIds);
			targetAccountIds = (owned || []).map((a: { id: string }) => a.id);
		}

		if (targetAccountIds.length === 0) {
			return apiSuccess(res, { leaders: [], totalClicks: 0, periodDays });
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
		const cutoffDate = cutoff.toISOString().split("T")[0]!;

		const { data: rows } = await db()
			.from("threads_link_click_breakdown")
			.select("account_id, link_url, clicks")
			.in("account_id", targetAccountIds)
			.gte("fetched_date", cutoffDate);

		// Aggregate across days by (account_id, link_url).
		const agg = new Map<string, { accountId: string; url: string; clicks: number }>();
		let totalClicks = 0;
		for (const r of (rows || []) as Array<{
			account_id: string;
			link_url: string;
			clicks: number | null;
		}>) {
			const key = `${r.account_id}::${r.link_url}`;
			const existing = agg.get(key) || {
				accountId: r.account_id,
				url: r.link_url,
				clicks: 0,
			};
			existing.clicks += r.clicks || 0;
			totalClicks += r.clicks || 0;
			agg.set(key, existing);
		}

		const leaders = Array.from(agg.values())
			.filter((x) => x.clicks > 0)
			.sort((a, b) => b.clicks - a.clicks)
			.slice(0, limit)
			.map((x) => ({
				accountId: x.accountId,
				username: usernameById.get(x.accountId) || null,
				url: x.url,
				clicks: x.clicks,
			}));

		return apiSuccess(res, { leaders, totalClicks, periodDays });
	},
);
