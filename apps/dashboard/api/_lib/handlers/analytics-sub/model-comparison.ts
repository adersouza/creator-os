/**
 * Model Comparison
 *
 * GET /api/analytics/model-comparison?days=14
 * Compares performance across all account groups for the user.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getSupabaseAny } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";

const QuerySchema = z.object({
	days: z.coerce.number().int().min(1).max(90).optional().default(14),
});

const db = () => getSupabaseAny();

interface GroupRow {
	id: string;
	name: string;
	account_ids: string[] | null;
}

interface PostRow {
	id: string;
	content: string | null;
	account_id: string | null;
	instagram_account_id: string | null;
	views_count: number | null;
	likes_count: number | null;
	replies_count: number | null;
	published_at: string | null;
}

interface WinnerResult {
	groupId: string;
	groupName: string;
	metric: string;
	value: number;
}

const POSTS_PAGE_SIZE = 1000;
const POSTS_MAX_ROWS = 20_000;

async function fetchComparisonPosts(params: {
	accountColumn: "account_id" | "instagram_account_id";
	accountIds: string[];
	userId: string;
	cutoff: string;
	platform?: "instagram";
}): Promise<{ rows: PostRow[]; limited: boolean }> {
	const rows: PostRow[] = [];
	for (let from = 0; from < POSTS_MAX_ROWS; from += POSTS_PAGE_SIZE) {
		let query = db()
			.from("posts")
			.select(
				"id, content, account_id, instagram_account_id, views_count, likes_count, replies_count, published_at",
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
		const page = (data ?? []) as PostRow[];
		rows.push(...page);
		if (page.length < POSTS_PAGE_SIZE) {
			return { rows, limited: false };
		}
	}
	return { rows, limited: true };
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") {
			return apiError(res, 405, "Method not allowed");
		}

		const userId = user.id;
		const parsed = parseQueryOrError(res, QuerySchema, req.query);
		if (!parsed) return;
		const { days } = parsed;

		// Get all groups for user
		const { data: groups, error: groupsError } = await db()
			.from("account_groups")
			.select("id, name, account_ids")
			.eq("user_id", userId)
			.order("name", { ascending: true });

		if (groupsError)
			return apiError(res, 500, "Failed to fetch groups", {
				details: groupsError.message,
			});

		if (!groups || groups.length === 0) {
			return apiSuccess(res, { groups: [], periodDays: days, winner: null });
		}

		const cutoff = new Date(Date.now() - days * 86_400_000).toISOString();

		// Collect all account IDs across groups
		const allAccountIds = new Set<string>();
		for (const g of groups) {
			for (const id of g.account_ids ?? []) {
				allAccountIds.add(id);
			}
		}
		const accountIdsList = [...allAccountIds];

		if (accountIdsList.length === 0) {
			return apiSuccess(res, {
				groups: (groups as GroupRow[]).map((g) => ({
					groupId: g.id,
					groupName: g.name,
					totalFollowers: 0,
					totalViews: 0,
					totalLikes: 0,
					totalReplies: 0,
					postsCount: 0,
					avgViewsPerPost: 0,
					engagementRate: 0,
					topPost: null,
				})),
				periodDays: days,
				winner: null,
			});
		}

		const [threadsAccountsResult, igAccountsResult, analyticsResult] =
			await Promise.all([
				db()
					.from("accounts")
					.select("id, followers_count")
					.in("id", accountIdsList)
					.eq("user_id", userId),
				db()
					.from("instagram_accounts")
					.select("id, follower_count")
					.in("id", accountIdsList)
					.eq("user_id", userId),
				db()
					.from("account_analytics")
					.select("account_id, followers_count, date")
					.in("account_id", accountIdsList)
					.order("date", { ascending: false }),
			]);

		const threadsAccountIds = (threadsAccountsResult.data ?? []).map(
			(a: { id: string }) => a.id,
		);
		const igAccountIds = (igAccountsResult.data ?? []).map(
			(a: { id: string }) => a.id,
		);

		const postQueries: Promise<{ rows: PostRow[]; limited: boolean }>[] = [];
		if (threadsAccountIds.length > 0) {
			postQueries.push(
				fetchComparisonPosts({
					accountColumn: "account_id",
					accountIds: threadsAccountIds,
					userId,
					cutoff,
				}),
			);
		}
		if (igAccountIds.length > 0) {
			postQueries.push(
				fetchComparisonPosts({
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

		// Index posts by account
		const postsByAccount = new Map<string, PostRow[]>();
		const allPosts = postResults.flatMap((result) => result.rows);
		for (const p of allPosts) {
			const postAccountId = p.instagram_account_id || p.account_id;
			if (!postAccountId) continue;
			if (!postsByAccount.has(postAccountId))
				postsByAccount.set(postAccountId, []);
			postsByAccount.get(postAccountId)?.push(p);
		}

		// Latest followers per account
		const followerMap = new Map<string, number>();
		for (const row of analyticsResult.data ?? []) {
			if (!followerMap.has(row.account_id) && row.followers_count) {
				followerMap.set(row.account_id, row.followers_count);
			}
		}
		// Fallback from accounts table
		for (const acc of threadsAccountsResult.data ?? []) {
			if (!followerMap.has(acc.id) && acc.followers_count) {
				followerMap.set(acc.id, acc.followers_count);
			}
		}
		for (const acc of igAccountsResult.data ?? []) {
			if (!followerMap.has(acc.id) && acc.follower_count) {
				followerMap.set(acc.id, acc.follower_count);
			}
		}

		// Build per-group summaries
		const groupSummaries = (groups as GroupRow[]).map((g) => {
			const gAccountIds: string[] = g.account_ids ?? [];
			let totalFollowers = 0;
			let totalViews = 0;
			let totalLikes = 0;
			let totalReplies = 0;
			let postsCount = 0;
			let bestPost: PostRow | null = null;
			let bestScore = 0;

			for (const accId of gAccountIds) {
				totalFollowers += followerMap.get(accId) ?? 0;
				const posts = postsByAccount.get(accId) ?? [];
				for (const p of posts) {
					postsCount++;
					totalViews += p.views_count ?? 0;
					totalLikes += p.likes_count ?? 0;
					totalReplies += p.replies_count ?? 0;
					const score =
						(p.views_count ?? 0) +
						(p.likes_count ?? 0) * 10 +
						(p.replies_count ?? 0) * 20;
					if (score > bestScore) {
						bestScore = score;
						bestPost = p;
					}
				}
			}

			const totalEngagement = totalLikes + totalReplies;
			const engagementRate =
				totalFollowers > 0 && postsCount > 0
					? Math.round(
							(totalEngagement / (postsCount * totalFollowers)) * 10000,
						) / 100
					: 0;

			return {
				groupId: g.id,
				groupName: g.name,
				totalFollowers,
				totalViews,
				totalLikes,
				totalReplies,
				postsCount,
				avgViewsPerPost:
					postsCount > 0 ? Math.round(totalViews / postsCount) : 0,
				engagementRate,
				topPost: bestPost
					? {
							id: bestPost.id,
							content: bestPost.content?.substring(0, 100) ?? "",
							views: bestPost.views_count ?? 0,
						}
					: null,
			};
		});

		// Determine winner by engagement rate
		const winner = groupSummaries.reduce<WinnerResult | null>((best, g) => {
			if (g.engagementRate > (best?.value ?? 0)) {
				return {
					groupId: g.groupId,
					groupName: g.groupName,
					metric: "engagement",
					value: g.engagementRate,
				};
			}
			return best;
		}, null);

		return apiSuccess(res, {
			groups: groupSummaries,
			periodDays: days,
			winner,
			meta: {
				postRowsLimited,
				postRowsReturned: allPosts.length,
				postRowsMax: POSTS_MAX_ROWS,
			},
		});
	},
);
