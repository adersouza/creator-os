// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Fleet Reach Anomaly Rollup
 *
 * GET /api/analytics?action=reach-anomalies&limit=50
 *
 * Batches the same recent-vs-baseline signal used by reach-anomaly across
 * the user's active Threads accounts. Recent = last 3 days; baseline =
 * days 4-14. Uses first-24h post_metric_history snapshots when available.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { enforceAnalyticsSubRateLimit } from "./rateLimit.js";

const QuerySchema = z.object({
	limit: z.coerce.number().int().min(1).max(100).optional().default(50),
});

// biome-ignore lint/suspicious/noExplicitAny: generated DB types do not cover every analytics table here
const db = (): any => getSupabase();

type Status =
	| "insufficient_data"
	| "anomaly"
	| "concerning"
	| "above_average"
	| "normal";

type AccountRow = {
	id: string;
	username: string | null;
};

type PostRow = {
	id: string;
	account_id: string;
	views_count: number | null;
	likes_count: number | null;
	replies_count: number | null;
	created_at: string;
};

type FollowerRow = {
	account_id: string;
	date: string;
	followers_count: number | null;
};

type VelocityRow = {
	post_id: string;
	hours_since_publish: number;
	views_count: number | null;
};

function avg(
	rows: PostRow[],
	field: "views_count" | "likes_count" | "replies_count",
): number {
	if (rows.length === 0) return 0;
	return rows.reduce((sum, row) => sum + (row[field] ?? 0), 0) / rows.length;
}

function analyzeFollowerTrend(rows: FollowerRow[]): {
	followerTrend: "flat" | "growing" | "declining";
	followerChange: number;
} {
	if (rows.length < 2) return { followerTrend: "flat", followerChange: 0 };
	const sorted = [...rows].sort((a, b) => a.date.localeCompare(b.date));
	const earliest = sorted[0]!.followers_count ?? 0;
	const latest = sorted[sorted.length - 1]!.followers_count ?? 0;
	if (earliest <= 0) return { followerTrend: "flat", followerChange: 0 };

	const changePercent = ((latest - earliest) / earliest) * 100;
	if (changePercent > 5) {
		return {
			followerTrend: "growing",
			followerChange: Math.round(changePercent * 10) / 10,
		};
	}
	if (changePercent < -5) {
		return {
			followerTrend: "declining",
			followerChange: Math.round(changePercent * 10) / 10,
		};
	}
	return {
		followerTrend: "flat",
		followerChange: Math.round(changePercent * 10) / 10,
	};
}

function closest24hByPost(rows: VelocityRow[]): Map<string, number> {
	const byPost = new Map<string, { hours: number; views: number }>();
	for (const row of rows) {
		const existing = byPost.get(row.post_id);
		const hours = row.hours_since_publish;
		if (!existing || Math.abs(hours - 24) < Math.abs(existing.hours - 24)) {
			byPost.set(row.post_id, { hours, views: row.views_count ?? 0 });
		}
	}
	return new Map(
		[...byPost.entries()].map(([postId, row]) => [postId, row.views]),
	);
}

function avgVelocity(
	posts: PostRow[],
	viewsByPost: Map<string, number>,
): number {
	const values = posts
		.map((post) => viewsByPost.get(post.id))
		.filter((value): value is number => value != null);
	if (values.length === 0) return 0;
	return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function statusFor(changePercent: number): Status {
	if (changePercent < -40) return "anomaly";
	if (changePercent < -25) return "concerning";
	if (changePercent > 25) return "above_average";
	return "normal";
}

function verdictFor(status: Status, changePercent: number): string {
	switch (status) {
		case "anomaly":
			return `Reach dropped ${Math.abs(Math.round(changePercent))}% vs the 4-14 day baseline.`;
		case "concerning":
			return `Reach dropped ${Math.abs(Math.round(changePercent))}% vs the 4-14 day baseline.`;
		case "above_average":
			return `Reach increased ${Math.round(changePercent)}% vs the 4-14 day baseline.`;
		default:
			return "Reach is within normal range vs the 4-14 day baseline.";
	}
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const allowed = await enforceAnalyticsSubRateLimit(res, {
			userId: user.id,
			action: "reach-anomalies",
			limit: 30,
		});
		if (!allowed) return;

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { limit } = parsed;

		const now = Date.now();
		const threeDaysAgo = new Date(now - 3 * 86_400_000).toISOString();
		const fourteenDaysAgo = new Date(now - 14 * 86_400_000).toISOString();
		const fourteenDaysAgoDate = fourteenDaysAgo.split("T")[0]!;

		const { data: accounts, error: accountsError } = await db()
			.from("accounts")
			.select("id, username")
			.eq("user_id", user.id)
			.eq("is_active", true)
			.eq("is_retired", false);

		if (accountsError) {
			return apiError(res, 500, "Failed to fetch accounts", {
				details: accountsError.message,
			});
		}

		const accountRows = (accounts ?? []) as AccountRow[];
		const accountIds = accountRows.map((account) => account.id);
		if (accountIds.length === 0) {
			return apiSuccess(res, {
				accounts: [],
				total: 0,
				concerning: 0,
				anomalous: 0,
				sourceAccounts: 0,
			});
		}

		const [postsRes, followerRes] = await Promise.all([
			db()
				.from("posts")
				.select(
					"id, account_id, views_count, likes_count, replies_count, created_at",
				)
				.eq("user_id", user.id)
				.eq("status", "published")
				.in("account_id", accountIds)
				.gte("created_at", fourteenDaysAgo),
			db()
				.from("account_metrics_history")
				.select("account_id, date, followers_count")
				.in("account_id", accountIds)
				.gte("date", fourteenDaysAgoDate),
		]);

		if (postsRes.error) {
			return apiError(res, 500, "Failed to fetch posts", {
				details: postsRes.error.message,
			});
		}

		const posts = (postsRes.data ?? []) as PostRow[];
		const postIds = posts.map((post) => post.id);
		let velocityByPost = new Map<string, number>();

		if (postIds.length > 0) {
			const { data: velocityRows, error: velocityError } = await db()
				.from("post_metric_history")
				.select("post_id, hours_since_publish, views_count")
				.in("post_id", postIds)
				.gte("hours_since_publish", 20)
				.lte("hours_since_publish", 28);

			if (!velocityError && velocityRows) {
				velocityByPost = closest24hByPost(velocityRows as VelocityRow[]);
			}
		}

		const postsByAccount = new Map<string, PostRow[]>();
		for (const post of posts) {
			if (!post.account_id) continue;
			const list = postsByAccount.get(post.account_id) ?? [];
			list.push(post);
			postsByAccount.set(post.account_id, list);
		}

		const followersByAccount = new Map<string, FollowerRow[]>();
		if (!followerRes.error) {
			for (const row of (followerRes.data ?? []) as FollowerRow[]) {
				const list = followersByAccount.get(row.account_id) ?? [];
				list.push(row);
				followersByAccount.set(row.account_id, list);
			}
		}

		const results = accountRows.map((account) => {
			const accountPosts = postsByAccount.get(account.id) ?? [];
			const recent = accountPosts.filter(
				(post) => post.created_at >= threeDaysAgo,
			);
			const baseline = accountPosts.filter(
				(post) => post.created_at < threeDaysAgo,
			);

			if (
				accountPosts.length < 2 ||
				recent.length === 0 ||
				baseline.length === 0
			) {
				return {
					accountId: account.id,
					username: account.username ?? "unknown",
					status: "insufficient_data" as Status,
					message: "Need posts in both recent and 4-14 day baseline periods.",
					reachChangePercent: null,
					recentAvg: null,
					baselineAvg: null,
					recentPostCount: recent.length,
					baselinePostCount: baseline.length,
					dataSource: null,
					followerTrend: null,
					followerChange: null,
					isLikelyShadowban: false,
					verdict: null,
				};
			}

			const recentVelocityAvg = avgVelocity(recent, velocityByPost);
			const baselineVelocityAvg = avgVelocity(baseline, velocityByPost);
			const hasVelocityData = recentVelocityAvg > 0 && baselineVelocityAvg > 0;
			const recentAvg = hasVelocityData
				? recentVelocityAvg
				: avg(recent, "views_count");
			const baselineAvg = hasVelocityData
				? baselineVelocityAvg
				: avg(baseline, "views_count");
			const reachChangePercent =
				baselineAvg > 0 ? ((recentAvg - baselineAvg) / baselineAvg) * 100 : 0;
			const status = statusFor(reachChangePercent);
			const followerTrend = analyzeFollowerTrend(
				followersByAccount.get(account.id) ?? [],
			);

			return {
				accountId: account.id,
				username: account.username ?? "unknown",
				status,
				message: null,
				reachChangePercent: Math.round(reachChangePercent * 10) / 10,
				recentAvg: Math.round(recentAvg),
				baselineAvg: Math.round(baselineAvg),
				recentPostCount: recent.length,
				baselinePostCount: baseline.length,
				dataSource: hasVelocityData
					? "post_metric_history_24h"
					: "posts_latest_snapshot",
				...followerTrend,
				isLikelyShadowban: false,
				verdict: verdictFor(status, reachChangePercent),
			};
		});

		const sorted = results.sort((a, b) => {
			const aScore = a.reachChangePercent ?? 999;
			const bScore = b.reachChangePercent ?? 999;
			return aScore - bScore;
		});

		return apiSuccess(res, {
			accounts: sorted.slice(0, limit),
			total: sorted.length,
			concerning: sorted.filter(
				(row) => row.status === "concerning" || row.status === "anomaly",
			).length,
			anomalous: sorted.filter((row) => row.status === "anomaly").length,
			sourceAccounts: accountRows.length,
		});
	},
);
