// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Audience online now — hourly online-followers histogram for IG.
 *
 * GET /api/analytics?action=audience-online-now&accountId=X
 *
 * Reads the latest row of account_analytics.ig_online_followers, a
 * Record<hour (0–23), count> blob Meta returns in UTC. Aggregates across
 * the user's IG accounts. The frontend shifts hours into the user's
 * local timezone for display — we return UTC here so it's unambiguous.
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
});

// biome-ignore lint/suspicious/noExplicitAny: JSONB column
const db = (): any => getSupabase();

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds: accountIdsStr } = parsed;

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
			return apiSuccess(res, { hourlyUtc: [], accountCount: 0 });
		}

		// Pull the most recent row per account. We sort by date desc and take
		// the first non-null per account in memory — Postgres DISTINCT ON would
		// be cleaner but needs a custom RPC and this scales fine at fleet size.
		const { data: rows } = await db()
			.from("account_analytics")
			.select("account_id, ig_online_followers, date")
			.in("account_id", targetAccountIds)
			.not("ig_online_followers", "is", null)
			.order("date", { ascending: false })
			.limit(targetAccountIds.length * 5);

		const latestByAccount = new Map<string, Record<string, number>>();
		for (const r of (rows || []) as Array<{
			account_id: string;
			ig_online_followers: Record<string, number> | null;
			date: string;
		}>) {
			if (latestByAccount.has(r.account_id)) continue;
			if (!r.ig_online_followers) continue;
			latestByAccount.set(r.account_id, r.ig_online_followers);
		}

		// Sum by hour across accounts. Hours are UTC "0"-"23" strings.
		const hourly = new Array<number>(24).fill(0);
		for (const followersByHour of latestByAccount.values()) {
			for (const [hourStr, count] of Object.entries(followersByHour)) {
				const h = Number.parseInt(hourStr, 10);
				if (Number.isFinite(h) && h >= 0 && h < 24 && typeof count === "number") {
					hourly[h]! += count;
				}
			}
		}

		return apiSuccess(res, {
			hourlyUtc: hourly,
			accountCount: latestByAccount.size,
		});
	},
);
