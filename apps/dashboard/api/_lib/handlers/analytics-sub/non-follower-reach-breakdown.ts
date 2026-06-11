// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Non-follower reach breakdown — IG fleet + per-account.
 *
 * GET /api/analytics?action=non-follower-reach-breakdown&accountId=X
 *
 * Non-follower reach % measures how far your content travels beyond your
 * existing audience — the single best "discovery" signal on IG. Pulls
 * account_analytics.ig_non_follower_reach_pct averaged over the last 7
 * rows per account; fleet-weighted by total rows.
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
	periodDays: z.coerce.number().int().min(1).max(90).optional().default(7),
});

// biome-ignore lint/suspicious/noExplicitAny: JSON/typed columns
const db = (): any => getSupabase();

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds: accountIdsStr, periodDays } = parsed;

		let targetAccountIds: string[] = [];
		if (accountIdsStr) {
			targetAccountIds = accountIdsStr.split(",").filter(Boolean);
		} else if (accountId && accountId !== "ALL") {
			targetAccountIds = [accountId];
		}

		if (targetAccountIds.length === 0) {
			const { data: igAccounts } = await db()
				.from("instagram_accounts")
				.select("id, username")
				.eq("user_id", user.id);
			targetAccountIds = (igAccounts || []).map((a: { id: string }) => a.id);
		} else {
			const { data: owned } = await db()
				.from("instagram_accounts")
				.select("id, username")
				.eq("user_id", user.id)
				.in("id", targetAccountIds);
			targetAccountIds = (owned || []).map((a: { id: string }) => a.id);
		}

		if (targetAccountIds.length === 0) {
			return apiSuccess(res, { fleetAvg: null, accounts: [], periodDays });
		}

		const { data: accountRows } = await db()
			.from("instagram_accounts")
			.select("id, username")
			.in("id", targetAccountIds);

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
			.from("account_analytics")
			.select("account_id, ig_non_follower_reach_pct, date")
			.in("account_id", targetAccountIds)
			.gte("date", cutoffDate)
			.not("ig_non_follower_reach_pct", "is", null);

		const perAccount = new Map<string, { sum: number; count: number }>();
		for (const r of (rows || []) as Array<{
			account_id: string;
			ig_non_follower_reach_pct: number | null;
			date: string;
		}>) {
			if (r.ig_non_follower_reach_pct == null) continue;
			const existing = perAccount.get(r.account_id) || { sum: 0, count: 0 };
			existing.sum += r.ig_non_follower_reach_pct;
			existing.count += 1;
			perAccount.set(r.account_id, existing);
		}

		let fleetSum = 0;
		let fleetCount = 0;
		const accounts = [];
		for (const [aid, { sum, count }] of perAccount) {
			if (count === 0) continue;
			fleetSum += sum;
			fleetCount += count;
			accounts.push({
				accountId: aid,
				username: usernameById.get(aid) || null,
				avgPct: sum / count,
				sampleDays: count,
			});
		}

		accounts.sort((a, b) => b.avgPct - a.avgPct);

		const fleetAvg = fleetCount > 0 ? fleetSum / fleetCount : null;

		return apiSuccess(res, { fleetAvg, accounts, periodDays });
	},
);
