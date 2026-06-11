// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Reach Anomaly Detection
 *
 * GET /api/analytics/reach-anomaly?accountId=...
 * Compares recent (last 3 days) vs baseline (4-14 days) post performance.
 * Enhanced with follower trend from account_metrics_history and
 * first-24h velocity from post_metric_history.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { verifyAccountOwnership } from "../helpers/verifyOwnership.js";

// biome-ignore lint/suspicious/noExplicitAny: table not yet in generated types
const db = (): any => getSupabase();

/** Compute average of a numeric field across an array */
const avg = (
	arr: Array<{
		views_count: number;
		likes_count: number;
		replies_count: number;
	}>,
	field: "views_count" | "likes_count" | "replies_count",
) => {
	const sum = arr.reduce((s, p) => s + (p[field] ?? 0), 0);
	return arr.length > 0 ? sum / arr.length : 0;
};

/** Determine follower trend classification from history rows */
function analyzeFollowerTrend(
	rows: Array<{ date: string; followers_count: number }>,
): {
	followerTrend: "flat" | "growing" | "declining";
	followerChange: number;
} {
	if (rows.length < 2) {
		return { followerTrend: "flat", followerChange: 0 };
	}

	// Rows are ordered by date ascending
	const earliest = rows[0]!.followers_count ?? 0;
	const latest = rows[rows.length - 1]!.followers_count ?? 0;

	if (earliest === 0) {
		return { followerTrend: "flat", followerChange: 0 };
	}

	const changePercent = ((latest - earliest) / earliest) * 100;

	let followerTrend: "flat" | "growing" | "declining";
	if (changePercent > 5) {
		followerTrend = "growing";
	} else if (changePercent < -5) {
		followerTrend = "declining";
	} else {
		followerTrend = "flat";
	}

	return {
		followerTrend,
		followerChange: Math.round(changePercent * 10) / 10,
	};
}

/** Compute average first-24h views from post_metric_history snapshots */
function computeVelocityAvg(
	snapshots: Array<{
		post_id: string;
		hours_since_publish: number;
		views_count: number;
	}>,
): number {
	if (snapshots.length === 0) return 0;

	// Group by post_id: take the snapshot closest to 24h per post
	const byPost = new Map<
		string,
		{ hours_since_publish: number; views_count: number }
	>();
	for (const snap of snapshots) {
		const existing = byPost.get(snap.post_id);
		if (
			!existing ||
			Math.abs(snap.hours_since_publish - 24) <
				Math.abs(existing.hours_since_publish - 24)
		) {
			byPost.set(snap.post_id, snap);
		}
	}

	const values = Array.from(byPost.values());
	const total = values.reduce((s, v) => s + (v.views_count ?? 0), 0);
	return values.length > 0 ? total / values.length : 0;
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		const userId = user.id;
		const accountId = req.query.accountId as string;

		if (!accountId) return apiError(res, 400, "accountId is required");

		// Verify account belongs to user
		const account = await verifyAccountOwnership(res, accountId, userId);
		if (!account) return;

		const now = Date.now();
		const threeDaysAgo = new Date(now - 3 * 86_400_000).toISOString();
		const fourteenDaysAgo = new Date(now - 14 * 86_400_000).toISOString();
		const fourteenDaysAgoDate = new Date(now - 14 * 86_400_000)
			.toISOString()
			.split("T")[0]!;

		// Run all three queries in parallel
		const [postsResult, followerResult, _velocityResult] = await Promise.all([
			// 1) Published posts from last 14 days (existing)
			db()
				.from("posts")
				.select("id, views_count, likes_count, replies_count, created_at")
				.eq("account_id", accountId)
				.eq("user_id", userId)
				.eq("status", "published")
				.gte("created_at", fourteenDaysAgo)
				.order("created_at", { ascending: false }),

			// 2) Follower trend from account_metrics_history (new)
			db()
				.from("account_metrics_history")
				.select("date, followers_count")
				.eq("account_id", accountId)
				.gte("date", fourteenDaysAgoDate)
				.order("date", { ascending: true }),

			// 3) post_metric_history — we query after we know post IDs
			//    (placeholder; actual query below once we have post IDs)
			Promise.resolve(null),
		]);

		if (postsResult.error)
			return apiError(res, 500, "Failed to fetch posts", {
				details: postsResult.error.message,
			});

		const allPosts = postsResult.data ?? [];

		if (allPosts.length < 2) {
			return apiSuccess(res, {
				status: "insufficient_data",
				message: "Need at least 2 published posts in the last 14 days",
				totalPosts: allPosts.length,
			});
		}

		// Split into recent vs baseline
		const recent = allPosts.filter(
			(p: { created_at: string }) => p.created_at >= threeDaysAgo,
		);
		const baseline = allPosts.filter(
			(p: { created_at: string }) => p.created_at < threeDaysAgo,
		);

		if (recent.length === 0 || baseline.length === 0) {
			return apiSuccess(res, {
				status: "insufficient_data",
				message:
					"Need posts in both recent (0-3 days) and baseline (4-14 days) periods",
				recentCount: recent.length,
				baselineCount: baseline.length,
			});
		}

		// --- Follower trend analysis ---
		const followerRows = followerResult.error
			? []
			: (followerResult.data ?? []);
		const { followerTrend, followerChange } =
			analyzeFollowerTrend(followerRows);

		// --- First-24h velocity from post_metric_history ---
		const recentPostIds = recent.map((p: { id: string }) => p.id);
		const baselinePostIds = baseline.map((p: { id: string }) => p.id);
		const allPostIds = [...recentPostIds, ...baselinePostIds];

		let recentVelocityAvg = 0;
		let baselineVelocityAvg = 0;
		let hasVelocityData = false;

		if (allPostIds.length > 0) {
			// Query post_metric_history for 20-28h window (close to 24h mark)
			const { data: velocitySnaps, error: velError } = await db()
				.from("post_metric_history")
				.select("post_id, hours_since_publish, views_count")
				.in("post_id", allPostIds)
				.gte("hours_since_publish", 20)
				.lte("hours_since_publish", 28);

			if (!velError && velocitySnaps && velocitySnaps.length > 0) {
				hasVelocityData = true;

				const recentSnaps = velocitySnaps.filter((s: { post_id: string }) =>
					recentPostIds.includes(s.post_id),
				);
				const baselineSnaps = velocitySnaps.filter((s: { post_id: string }) =>
					baselinePostIds.includes(s.post_id),
				);

				recentVelocityAvg = computeVelocityAvg(recentSnaps);
				baselineVelocityAvg = computeVelocityAvg(baselineSnaps);
			}
		}

		// --- Compute reach & engagement from posts ---
		// If we have velocity data, prefer it over current snapshots for reach comparison
		const recentAvgReach = hasVelocityData
			? recentVelocityAvg
			: avg(recent, "views_count");
		const baselineAvgReach = hasVelocityData
			? baselineVelocityAvg
			: avg(baseline, "views_count");

		const recentAvgEngagement =
			avg(recent, "likes_count") + avg(recent, "replies_count");
		const baselineAvgEngagement =
			avg(baseline, "likes_count") + avg(baseline, "replies_count");

		const reachChange =
			baselineAvgReach > 0
				? ((recentAvgReach - baselineAvgReach) / baselineAvgReach) * 100
				: 0;
		const engagementChange =
			baselineAvgEngagement > 0
				? ((recentAvgEngagement - baselineAvgEngagement) /
						baselineAvgEngagement) *
					100
				: 0;

		// --- Shadowban detection ---
		// Views dropped >40% but followers stayed flat → likely shadowban
		const isLikelyShadowban = reachChange < -40 && followerTrend === "flat";

		let status: string;
		let verdict: string;

		if (reachChange < -40) {
			status = "anomaly";
			if (isLikelyShadowban) {
				verdict = `Reach dropped ${Math.abs(Math.round(reachChange))}% while followers stayed flat — likely shadowban or algorithmic suppression`;
			} else {
				verdict = `Reach dropped ${Math.abs(Math.round(reachChange))}% compared to baseline — significant anomaly detected`;
			}
		} else if (reachChange < -25) {
			status = "concerning";
			verdict = `Reach dropped ${Math.abs(Math.round(reachChange))}% compared to baseline — worth monitoring`;
		} else if (reachChange > 25) {
			status = "above_average";
			verdict = `Reach increased ${Math.round(reachChange)}% compared to baseline — above average performance`;
		} else {
			status = "normal";
			verdict = "Reach is within normal range compared to baseline";
		}

		return apiSuccess(res, {
			status,
			reach: {
				recentAvg: Math.round(recentAvgReach),
				baselineAvg: Math.round(baselineAvgReach),
				changePercent: Math.round(reachChange * 10) / 10,
				recentPostCount: recent.length,
				baselinePostCount: baseline.length,
				dataSource: hasVelocityData
					? "post_metric_history_24h"
					: "posts_latest_snapshot",
			},
			engagement: {
				recentAvg: Math.round(recentAvgEngagement * 10) / 10,
				baselineAvg: Math.round(baselineAvgEngagement * 10) / 10,
				changePercent: Math.round(engagementChange * 10) / 10,
			},
			followerTrend,
			followerChange,
			isLikelyShadowban,
			velocityComparison: {
				recent24hAvg: Math.round(recentVelocityAvg),
				baseline24hAvg: Math.round(baselineVelocityAvg),
				hasData: hasVelocityData,
			},
			verdict,
		});
	},
);
