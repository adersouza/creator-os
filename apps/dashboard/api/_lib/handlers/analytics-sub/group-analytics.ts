// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Group Analytics
 *
 * GET /api/analytics/group-analytics?groupId=...&days=30
 * Aggregates metrics across all accounts in an account group.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";

const QuerySchema = z.object({
	groupId: z.string().min(1, "groupId is required"),
	days: z.coerce.number().int().min(1).max(90).optional().default(30),
});

// biome-ignore lint/suspicious/noExplicitAny: table not yet in generated types
const db = (): any => getSupabase();

interface UnifiedAccountRow {
	id: string;
	username: string | null;
	followers_count: number | null;
	platform: "threads" | "instagram";
}

interface GroupPostRow {
	id: string;
	content: string | null;
	account_id: string | null;
	instagram_account_id: string | null;
	views_count: number | null;
	likes_count: number | null;
	replies_count: number | null;
	shares_count: number | null;
	published_at: string | null;
}

const POSTS_PAGE_SIZE = 1000;
const POSTS_MAX_ROWS = 20_000;

async function fetchGroupPosts(params: {
	accountColumn: "account_id" | "instagram_account_id";
	accountIds: string[];
	userId: string;
	cutoff: string;
	platform?: "instagram";
}): Promise<{ rows: GroupPostRow[]; limited: boolean }> {
	const rows: GroupPostRow[] = [];
	for (let from = 0; from < POSTS_MAX_ROWS; from += POSTS_PAGE_SIZE) {
		let query = db()
			.from("posts")
			.select(
				"id, content, account_id, instagram_account_id, views_count, likes_count, replies_count, shares_count, published_at",
			)
			.in(params.accountColumn, params.accountIds)
			.eq("user_id", params.userId)
			.eq("status", "published")
			.gte("created_at", params.cutoff)
			.order("created_at", { ascending: false })
			.range(from, from + POSTS_PAGE_SIZE - 1);
		if (params.platform) {
			query = query.eq("platform", params.platform);
		}
		const { data, error } = await query;
		if (error) throw error;
		const page = (data ?? []) as GroupPostRow[];
		rows.push(...page);
		if (page.length < POSTS_PAGE_SIZE) {
			return { rows, limited: false };
		}
	}
	return { rows, limited: true };
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET" && req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		const userId = user.id;
		const rawInput =
			req.method === "POST" ? { ...req.query, ...req.body } : req.query;
		const parsed = parseQueryOrError(res, QuerySchema, rawInput);
		if (!parsed) return;
		const { groupId, days } = parsed;

		// Look up group
		const { data: group, error: groupError } = await db()
			.from("account_groups")
			.select("id, name, account_ids")
			.eq("id", groupId)
			.eq("user_id", userId)
			.maybeSingle();

		if (groupError)
			return apiError(res, 500, "Failed to fetch group", {
				details: groupError.message,
			});
		if (!group) return apiError(res, 404, "Group not found");

		const accountIds: string[] = group.account_ids ?? [];
		if (accountIds.length === 0) {
			return apiSuccess(res, {
				groupId,
				groupName: group.name,
				periodDays: days,
				accounts: [],
				aggregated: {
					followers: 0,
					views: 0,
					likes: 0,
					replies: 0,
					posts: 0,
					engagementRate: 0,
				},
				topPosts: [],
			});
		}

		const cutoff = new Date(Date.now() - days * 86_400_000).toISOString();

		const [threadsAccountsResult, igAccountsResult, analyticsResult] =
			await Promise.all([
				db()
					.from("accounts")
					.select("id, username, followers_count")
					.in("id", accountIds)
					.eq("user_id", userId),
				db()
					.from("instagram_accounts")
					.select("id, username, follower_count")
					.in("id", accountIds)
					.eq("user_id", userId),
				db()
					.from("account_analytics")
					.select(
						"account_id, followers_count, total_views, total_likes, total_replies, date",
					)
					.in("account_id", accountIds)
					.order("date", { ascending: false }),
			]);

		const threadsAccountIds = (threadsAccountsResult.data ?? []).map(
			(a: { id: string }) => a.id,
		);
		const igAccountIds = (igAccountsResult.data ?? []).map(
			(a: { id: string }) => a.id,
		);

		const postQueries: Promise<{ rows: GroupPostRow[]; limited: boolean }>[] = [];
		if (threadsAccountIds.length > 0) {
			postQueries.push(
				fetchGroupPosts({
					accountColumn: "account_id",
					accountIds: threadsAccountIds,
					userId,
					cutoff,
				}),
			);
		}
		if (igAccountIds.length > 0) {
			postQueries.push(
				fetchGroupPosts({
					accountColumn: "instagram_account_id",
					accountIds: igAccountIds,
					userId,
					cutoff,
					platform: "instagram",
				}),
			);
		}

		const postResults = await Promise.all(postQueries);
		const postRowsLimited = postResults.some((result) => result.limited);

		const unifiedAccounts: UnifiedAccountRow[] = [
			...(threadsAccountsResult.data ?? []).map(
				(a: {
					id: string;
					username: string | null;
					followers_count: number | null;
				}) => ({
					id: a.id,
					username: a.username,
					followers_count: a.followers_count,
					platform: "threads" as const,
				}),
			),
			...(igAccountsResult.data ?? []).map(
				(a: {
					id: string;
					username: string | null;
					follower_count: number | null;
				}) => ({
					id: a.id,
					username: a.username,
					followers_count: a.follower_count,
					platform: "instagram" as const,
				}),
			),
		];

		const allPosts = postResults.flatMap((result) => result.rows);
		// biome-ignore lint/suspicious/noExplicitAny: Vercel TS 5.9 — Supabase row type needs any for property access
		const accountMap = new Map<string, any>(
			unifiedAccounts.map((a) => [a.id, a]),
		);

		// Latest analytics per account
		const latestAnalytics = new Map<
			string,
			{ followers_count?: number | null | undefined; account_id: string }
		>();
		for (const row of analyticsResult.data ?? []) {
			if (!latestAnalytics.has(row.account_id)) {
				latestAnalytics.set(row.account_id, row);
			}
		}

		// Aggregated metrics
		let aggFollowers = 0;
		let aggViews = 0;
		let aggLikes = 0;
		let aggReplies = 0;

		// Per-account breakdown
		const perAccount: Record<
			string,
			{
				posts: number;
				views: number;
				likes: number;
				replies: number;
			}
		> = {};

		for (const id of accountIds) {
			perAccount[id] = { posts: 0, views: 0, likes: 0, replies: 0 };
			const analytics = latestAnalytics.get(id);
			aggFollowers += analytics?.followers_count ?? 0;
		}

		for (const p of allPosts) {
			const v = p.views_count ?? 0;
			const l = p.likes_count ?? 0;
			const r = p.replies_count ?? 0;
			aggViews += v;
			aggLikes += l;
			aggReplies += r;

			const postAccountId = p.instagram_account_id || p.account_id;
			if (postAccountId && perAccount[postAccountId]) {
				perAccount[postAccountId].posts++;
				perAccount[postAccountId].views += v;
				perAccount[postAccountId].likes += l;
				perAccount[postAccountId].replies += r;
			}
		}

		// Fallback follower count from accounts table
		if (aggFollowers === 0) {
			for (const id of accountIds) {
				const acc = accountMap.get(id);
				aggFollowers += acc?.followers_count ?? 0;
			}
		}

		const totalEngagement = aggLikes + aggReplies;
		const engagementRate =
			aggFollowers > 0 && allPosts.length > 0
				? Math.round(
						(totalEngagement / (allPosts.length * aggFollowers)) * 10000,
					) / 100
				: 0;

		// Per-account result
		const accounts = accountIds.map((id) => {
			const acc = accountMap.get(id);
			const perf = perAccount[id] ?? {
				posts: 0,
				views: 0,
				likes: 0,
				replies: 0,
			};
			const analytics = latestAnalytics.get(id);
			return {
				accountId: id,
				username: acc?.username ?? "unknown",
				followers: analytics?.followers_count ?? acc?.followers_count ?? 0,
				posts: perf.posts,
				views: perf.views,
				likes: perf.likes,
				replies: perf.replies,
				engagementRate:
					perf.views > 0
						? Math.round(((perf.likes + perf.replies) / perf.views) * 10000) /
							100
						: 0,
			};
		});

		// Top 5 posts across group
		const topPosts = [...allPosts]
			.sort((a, b) => {
				const engA =
					(a.likes_count ?? 0) + (a.replies_count ?? 0) + (a.views_count ?? 0);
				const engB =
					(b.likes_count ?? 0) + (b.replies_count ?? 0) + (b.views_count ?? 0);
				return engB - engA;
			})
			.slice(0, 5)
			.map((p) => {
				const postAccountId =
					p.instagram_account_id || p.account_id || "unknown";
				return {
					id: p.id,
					content: p.content?.substring(0, 100) ?? "",
					accountId: postAccountId,
					username: accountMap.get(postAccountId)?.username ?? "unknown",
					views: p.views_count ?? 0,
					likes: p.likes_count ?? 0,
					replies: p.replies_count ?? 0,
					publishedAt: p.published_at,
				};
			});

		// Time-series from account_metrics_history for follower trend chart
		let timeSeries: {
			date: string;
			total_followers: number;
			total_views: number;
			avg_engagement_rate: number;
		}[] = [];
		let followerGrowthPeriod = 0;
		try {
			const histCutoff = new Date(Date.now() - days * 86_400_000)
				.toISOString()
				.split("T")[0]!;
			const { data: historyRows } = await db()
				.from("account_metrics_history")
				.select("date, followers_count, total_views, engagement_rate")
				.in("account_id", accountIds)
				.gte("date", histCutoff)
				.order("date", { ascending: true });

			if (historyRows && historyRows.length > 0) {
				// Group by date, sum followers and views
				const byDate = new Map<
					string,
					{ followers: number; views: number; erSum: number; erCount: number }
				>();
				for (const row of historyRows) {
					const d = row.date;
					const entry = byDate.get(d) || {
						followers: 0,
						views: 0,
						erSum: 0,
						erCount: 0,
					};
					entry.followers += row.followers_count ?? 0;
					entry.views += row.total_views ?? 0;
					if (row.engagement_rate != null) {
						entry.erSum += Number(row.engagement_rate);
						entry.erCount++;
					}
					byDate.set(d, entry);
				}

				timeSeries = [...byDate.entries()]
					.sort(([a], [b]) => a.localeCompare(b))
					.map(([date, vals]) => ({
						date,
						total_followers: vals.followers,
						total_views: vals.views,
						avg_engagement_rate:
							vals.erCount > 0
								? Math.round((vals.erSum / vals.erCount) * 100) / 100
								: 0,
					}));

				// Follower growth: first entry vs last entry
				if (timeSeries.length >= 2) {
					const first = timeSeries[0]!.total_followers;
					const last = timeSeries[timeSeries.length - 1]!.total_followers;
					followerGrowthPeriod =
						first > 0 ? Math.round(((last - first) / first) * 1000) / 10 : 0;
				}
			}
		} catch {
			// Non-fatal — timeSeries will be empty
		}

		// Best performing account
		const bestAccount = accounts.reduce<{ id: string | null; views: number }>(
			(best, acc) =>
				acc.views > best.views ? { id: acc.accountId, views: acc.views } : best,
			{ id: null, views: 0 },
		);

		return apiSuccess(res, {
			groupId,
			groupName: group.name,
			periodDays: days,
			totalAccounts: accountIds.length,
			aggregated: {
				followers: aggFollowers,
				views: aggViews,
				likes: aggLikes,
				replies: aggReplies,
				posts: allPosts.length,
				engagementRate,
			},
			accounts,
			topPosts,
			// Fields expected by GroupInsightsPanel
			timeSeries,
			latest: timeSeries.length > 0 ? timeSeries[timeSeries.length - 1] : null,
			summary: {
				totalFollowers: aggFollowers,
				totalViews: aggViews,
				avgEngagementRate: engagementRate,
				followerGrowthPeriod,
				topPerformingAccountId: bestAccount.id,
				accountsCount: accountIds.length,
				postsCount: allPosts.length,
			},
			meta: {
				postRowsLimited,
				postRowsReturned: allPosts.length,
				postRowsMax: POSTS_MAX_ROWS,
			},
		});
	},
);
