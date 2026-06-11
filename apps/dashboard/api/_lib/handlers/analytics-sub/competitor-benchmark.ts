// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Competitor benchmark — normalized by follower count
 *
 * GET /api/analytics?action=competitor-benchmark&accountId=X&platform=threads
 *
 * Pulls competitors in a ±50% follower-size band on the same platform,
 * computes each one's 7d engagement rate per 1k followers, and reports
 * where the user's account lands within that peer group (percentile).
 *
 * Not a prediction — a snapshot percentile against the peer pool we
 * already collect in the `competitors` table.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";

const QuerySchema = z.object({
	accountId: z.string(),
	platform: z.string().optional().default("threads"),
	/** Size-band half-width as a fraction of user followers (0.5 = ±50%). */
	bandWidth: z.coerce.number().min(0.1).max(2).optional().default(0.5),
});

// biome-ignore lint/suspicious/noExplicitAny: mix of tables not fully typed
const db = (): any => getSupabase();

/** Engagement score per 1k followers, 7-day. */
function normalizedRate(
	likes: number,
	replies: number,
	reposts: number,
	quotes: number,
	followers: number,
): number {
	if (followers <= 0) return 0;
	const interactions = likes + replies * 2 + reposts + quotes;
	return (interactions / followers) * 1000;
}

function percentile(values: number[], target: number): number {
	if (values.length === 0) return 0;
	const below = values.filter((v) => v < target).length;
	return (below / values.length) * 100;
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, platform, bandWidth } = parsed;

		const isInstagram = platform === "instagram";
		const accountsTable = isInstagram ? "instagram_accounts" : "accounts";

		// Get user's account (followers + 7d engagement)
		const { data: account } = await db()
			.from(accountsTable)
			.select(isInstagram ? "id, follower_count" : "id, followers_count")
			.eq("id", accountId)
			.eq("user_id", user.id)
			.maybeSingle();

		if (!account) return apiError(res, 404, "Account not found");

		const userFollowers = isInstagram
			? account.follower_count || 0
			: account.followers_count || 0;

		if (userFollowers <= 0) {
			return apiSuccess(res, {
				userFollowers: 0,
				userRate: 0,
				peerCount: 0,
				percentile: null,
				peerP50: 0,
				peerP75: 0,
				peerP90: 0,
			});
		}

		// User's 7d rollup from account_analytics (latest row)
		const sevenDaysAgo = new Date();
		sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);
		const cutoff = sevenDaysAgo.toISOString().split("T")[0]!;

		const { data: userRows } = await db()
			.from("account_analytics")
			.select("total_likes, total_replies, total_reposts, total_quotes, date")
			.eq("account_id", accountId)
			.gte("date", cutoff)
			.order("date", { ascending: false })
			.limit(1);

		const userStats = userRows?.[0] || {};
		const userRate = normalizedRate(
			userStats.total_likes || 0,
			userStats.total_replies || 0,
			userStats.total_reposts || 0,
			userStats.total_quotes || 0,
			userFollowers,
		);

		// Peer band: ±bandWidth * followers
		const low = Math.floor(userFollowers * (1 - bandWidth));
		const high = Math.ceil(userFollowers * (1 + bandWidth));

		const { data: peers } = await db()
			.from("competitors")
			.select(
				"follower_count, likes_count_7d, replies_count_7d, reposts_count_7d, quotes_count_7d",
			)
			.eq("user_id", user.id)
			.eq("platform", platform)
			.gte("follower_count", low)
			.lte("follower_count", high)
			.not("follower_count", "is", null);

		const peerRates: number[] = [];
		for (const p of (peers || []) as Array<{
			follower_count: number | null;
			likes_count_7d: number | null;
			replies_count_7d: number | null;
			reposts_count_7d: number | null;
			quotes_count_7d: number | null;
		}>) {
			const rate = normalizedRate(
				p.likes_count_7d || 0,
				p.replies_count_7d || 0,
				p.reposts_count_7d || 0,
				p.quotes_count_7d || 0,
				p.follower_count || 0,
			);
			if (rate > 0) peerRates.push(rate);
		}

		peerRates.sort((a, b) => a - b);
		const pct = (q: number) =>
			peerRates.length === 0
				? 0
				: peerRates[
						Math.min(peerRates.length - 1, Math.floor(q * peerRates.length))
					];

		return apiSuccess(res, {
			userFollowers,
			userRate,
			peerCount: peerRates.length,
			peerBand: { low, high },
			percentile: peerRates.length > 0 ? percentile(peerRates, userRate) : null,
			peerP50: pct(0.5),
			peerP75: pct(0.75),
			peerP90: pct(0.9),
		});
	},
);
