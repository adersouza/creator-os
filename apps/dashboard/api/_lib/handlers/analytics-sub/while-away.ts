// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * GET /api/analytics/while-away
 * Returns delta metrics since the user's last visit.
 * Query params: accountId, platform, since (ISO date)
 */
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

async function handler(
	req: VercelRequest,
	res: VercelResponse,
	user: { id: string; email?: string | undefined },
) {
	const userId = user.id;
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const accountId = req.query.accountId as string;
	let since = req.query.since as string;

	if (!accountId) {
		return apiError(res, 400, "accountId is required");
	}

	const supabase = getSupabase();

	// #575: If no `since` provided, use the most recent feature_usage entry
	// as a proxy for the user's last visit timestamp
	if (!since) {
		try {
			const { data: lastUsage } = await supabase
				.from("feature_usage")
				.select("used_at")
				.eq("user_id", userId)
				.order("used_at", { ascending: false })
				.limit(1);
			if (lastUsage && lastUsage.length > 0 && lastUsage[0]!.used_at) {
				since = lastUsage[0]!.used_at;
			}
		} catch {
			// Non-critical — fall through to default
		}
		// If still no `since`, default to 7 days ago
		if (!since) {
			since = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
		}
	}

	const sinceDate = new Date(since);

	try {
		// Get follower change (with ownership check)
		const { data: account } = await supabase
			.from("accounts")
			.select("followers_count")
			.eq("id", accountId)
			.eq("user_id", userId)
			.maybeSingle();

		if (!account) {
			return apiError(res, 403, "Account not found");
		}

		// Get oldest analytics snapshot since last visit for follower delta
		const { data: history } = await supabase
			.from("account_analytics")
			.select("followers_count")
			.eq("account_id", accountId)
			.gte("date", sinceDate.toISOString().split("T")[0]!)
			.order("date", { ascending: true })
			.limit(1);

		const oldFollowers =
			(history as { followers_count?: number | undefined }[] | null)?.[0]
				?.followers_count ??
			account?.followers_count ??
			0;
		const currentFollowers = account?.followers_count ?? 0;
		const newFollowers = Math.max(currentFollowers - oldFollowers, 0);

		// Get top performing post since last visit
		const { data: topPost } = await supabase
			.from("posts")
			.select("views_count")
			.eq("account_id", accountId)
			.eq("user_id", userId)
			.gte("published_at", sinceDate.toISOString())
			.order("views_count", { ascending: false })
			.limit(1);

		const topPostViewsTotal = topPost?.[0]?.views_count ?? 0;

		// #569: CES normalized per-post since last visit
		const { data: postsSinceVisit } = await supabase
			.from("posts")
			.select("likes_count, replies_count, views_count")
			.eq("account_id", accountId)
			.eq("user_id", userId)
			.gte("published_at", sinceDate.toISOString())
			.order("published_at", { ascending: false })
			.limit(50);

		let cesValue = 0;
		if (postsSinceVisit && postsSinceVisit.length > 0) {
			// Per-post engagement rate, then average across posts
			const perPostRates = postsSinceVisit.map((p) => {
				const eng = (p.likes_count || 0) + (p.replies_count || 0);
				const views = p.views_count || 0;
				return views > 0 ? eng / views : 0;
			});
			const avgRate =
				perPostRates.reduce((s, r) => s + r, 0) / perPostRates.length;
			cesValue = Math.round(avgRate * 10000) / 100; // percentage with 2 decimals
		}

		// #570: Compute cesChange by comparing CES before vs after `since` date
		let cesChange: "up" | "down" | "steady" = "steady";
		const { data: postsBefore } = await supabase
			.from("posts")
			.select("likes_count, replies_count, views_count")
			.eq("account_id", accountId)
			.eq("user_id", userId)
			.lt("published_at", sinceDate.toISOString())
			.order("published_at", { ascending: false })
			.limit(50);

		if (postsBefore && postsBefore.length >= 3) {
			const beforeRates = postsBefore.map((p) => {
				const eng = (p.likes_count || 0) + (p.replies_count || 0);
				const views = p.views_count || 0;
				return views > 0 ? eng / views : 0;
			});
			const avgBefore =
				beforeRates.reduce((s, r) => s + r, 0) / beforeRates.length;
			const avgAfterRaw = cesValue / 100; // convert back from percentage
			if (avgBefore > 0) {
				const changePct = ((avgAfterRaw - avgBefore) / avgBefore) * 100;
				if (changePct > 5) cesChange = "up";
				else if (changePct < -5) cesChange = "down";
			}
		}

		return apiSuccess(res, {
			topPostViewsGained: topPostViewsTotal,
			topPostViewsTotal,
			newFollowers,
			cesChange,
			cesValue,
		});
	} catch (err) {
		logger.debug("Failed to compute while-away metrics", {
			error: String(err),
		});
		return apiError(res, 500, "Failed to compute while-away metrics");
	}
}

export default withAuth(handler);
