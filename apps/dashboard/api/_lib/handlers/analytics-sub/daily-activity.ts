// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Daily Activity
 *
 * GET /api/analytics?action=daily-activity&accountId=X&periodDays=30
 * Returns daily aggregated views, likes, replies, and posts published
 * computed from post_metric_history snapshots (server-side, no client cap).
 *
 * Falls back to post-level publish-date grouping when history data is sparse.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";

const QuerySchema = z.object({
	accountId: z.string().optional(),
	accountIds: z.string().optional(), // comma-separated
	periodDays: z.coerce.number().int().min(1).max(365).optional().default(30),
});

// biome-ignore lint/suspicious/noExplicitAny: table not yet in generated types
const db = (): any => getSupabase();

interface DailyBucket {
	date: string;
	views: number;
	likes: number;
	replies: number;
	posts: number;
}

interface AccountDailySnapshot {
	date: string;
	followers_count: number;
	engagement_rate: number;
	total_views: number;
	total_likes: number;
	total_replies: number;
	total_reach: number;
	total_saves: number;
	total_shares: number;
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { accountId, accountIds: accountIdsStr, periodDays } = parsed;

		// Resolve target account IDs
		let targetAccountIds: string[] = [];

		if (accountIdsStr) {
			targetAccountIds = accountIdsStr.split(",").filter(Boolean);
		} else if (accountId && accountId !== "ALL") {
			targetAccountIds = [accountId];
		}

		// If ALL or no account specified, get all user accounts
		if (targetAccountIds.length === 0) {
			const { data: accounts } = await db()
				.from("accounts")
				.select("id")
				.eq("user_id", user.id);
			targetAccountIds = (accounts || []).map((a: { id: string }) => a.id);
		} else {
			// Verify ownership
			const { data: ownedAccounts } = await db()
				.from("accounts")
				.select("id")
				.eq("user_id", user.id)
				.in("id", targetAccountIds);
			targetAccountIds = (ownedAccounts || []).map((a: { id: string }) => a.id);
		}

		if (targetAccountIds.length === 0) {
			return apiSuccess(res, { days: [], count: 0 });
		}

		const cutoff = new Date();
		cutoff.setDate(cutoff.getDate() - periodDays);
		const cutoffStr = cutoff.toISOString();

		// Strategy: get daily snapshots from post_metric_history
		// For each post, take latest snapshot per day, then compute deltas
		const { data: rawSnapshots, error } = await db()
			.from("post_metric_history")
			.select("post_id, views_count, likes_count, replies_count, snapshot_at")
			.in("account_id", targetAccountIds)
			.gte("snapshot_at", cutoffStr)
			.order("snapshot_at", { ascending: true });

		if (error) {
			return apiError(res, 500, "Failed to fetch history", {
				details: error.message,
			});
		}

		const rows = (rawSnapshots || []) as {
			post_id: string;
			views_count: number | null;
			likes_count: number | null;
			replies_count: number | null;
			snapshot_at: string;
		}[];

		// Group by post+day, keep latest snapshot per day
		const latestByPostDay = new Map<
			string,
			{ views: number; likes: number; replies: number }
		>();
		for (const row of rows) {
			const day = row.snapshot_at.split("T")[0]!;
			const key = `${row.post_id}:${day}`;
			// Ascending order: later rows overwrite earlier
			latestByPostDay.set(key, {
				views: row.views_count ?? 0,
				likes: row.likes_count ?? 0,
				replies: row.replies_count ?? 0,
			});
		}

		// For each post, compute daily deltas (today's snapshot - yesterday's)
		// Group snapshots by post first
		const snapshotsByPost = new Map<
			string,
			{ day: string; views: number; likes: number; replies: number }[]
		>();
		for (const [key, val] of latestByPostDay) {
			const [postId, day] = key.split(":");
			if (!snapshotsByPost.has(postId!)) {
				snapshotsByPost.set(postId!, []);
			}
			snapshotsByPost.get(postId!)?.push({ day: day!, ...val });
		}

		// Compute daily gains across all posts
		const dailyGains = new Map<
			string,
			{ views: number; likes: number; replies: number }
		>();
		for (const [_postId, daySnapshots] of snapshotsByPost) {
			daySnapshots.sort((a, b) => a.day.localeCompare(b.day));
			for (let i = 0; i < daySnapshots.length; i++) {
				const curr = daySnapshots[i];
				const prev = i > 0 ? daySnapshots[i - 1] : null;
				const gain = prev
					? {
							views: Math.max(0, curr!.views - prev.views),
							likes: Math.max(0, curr!.likes - prev.likes),
							replies: Math.max(0, curr!.replies - prev.replies),
						}
					: // First snapshot for this post — count as initial value
						{ views: 0, likes: 0, replies: 0 };

				const existing = dailyGains.get(curr!.day) || {
					views: 0,
					likes: 0,
					replies: 0,
				};
				dailyGains.set(curr!.day, {
					views: existing.views + gain.views,
					likes: existing.likes + gain.likes,
					replies: existing.replies + gain.replies,
				});
			}
		}

		// Count posts published per day
		const { data: publishedPosts } = await db()
			.from("posts")
			.select("published_at")
			.in("account_id", targetAccountIds)
			.eq("user_id", user.id)
			.eq("status", "published")
			.not("published_at", "is", null)
			.gte("published_at", cutoffStr);

		const postsPerDay = new Map<string, number>();
		for (const p of publishedPosts || []) {
			const day = new Date(p.published_at).toISOString().split("T")[0]!;
			postsPerDay.set(day!, (postsPerDay.get(day!) || 0) + 1);
		}

		// Merge into final daily buckets
		const allDays = new Set([...dailyGains.keys(), ...postsPerDay.keys()]);
		const days: DailyBucket[] = [...allDays].sort().map((date) => {
			const gains = dailyGains.get(date) || {
				views: 0,
				likes: 0,
				replies: 0,
			};
			return {
				date,
				views: gains.views,
				likes: gains.likes,
				replies: gains.replies,
				posts: postsPerDay.get(date) || 0,
			};
		});

		// Also fetch account-level daily snapshots for sparkline data
		const cutoffDate = cutoff.toISOString().split("T")[0]!;
		const { data: analyticsRows } = await db()
			.from("account_analytics")
			.select(
				"date, followers_count, engagement_rate, total_views, total_likes, total_replies, total_reach, total_saves, total_shares",
			)
			.in("account_id", targetAccountIds)
			.gte("date", cutoffDate)
			.order("date", { ascending: true });

		// If multiple accounts, sum by date
		const snapshotMap = new Map<string, AccountDailySnapshot>();
		for (const row of (analyticsRows || []) as AccountDailySnapshot[]) {
			const existing = snapshotMap.get(row.date);
			if (existing) {
				existing.followers_count += row.followers_count ?? 0;
				existing.total_views += row.total_views ?? 0;
				existing.total_likes += row.total_likes ?? 0;
				existing.total_replies += row.total_replies ?? 0;
				existing.total_reach += row.total_reach ?? 0;
				existing.total_saves += row.total_saves ?? 0;
				existing.total_shares += row.total_shares ?? 0;
				// Average engagement rate across accounts
				existing.engagement_rate =
					(existing.engagement_rate + (row.engagement_rate ?? 0)) / 2;
			} else {
				snapshotMap.set(row.date, {
					date: row.date,
					followers_count: row.followers_count ?? 0,
					engagement_rate: row.engagement_rate ?? 0,
					total_views: row.total_views ?? 0,
					total_likes: row.total_likes ?? 0,
					total_replies: row.total_replies ?? 0,
					total_reach: row.total_reach ?? 0,
					total_saves: row.total_saves ?? 0,
					total_shares: row.total_shares ?? 0,
				});
			}
		}
		const snapshots = [...snapshotMap.values()].sort((a, b) =>
			a.date.localeCompare(b.date),
		);

		return apiSuccess(res, {
			days,
			snapshots,
			count: days.length,
			periodDays,
		});
	},
);
