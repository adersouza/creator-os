// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Account Health Scoring with Stagnation Detection
 *
 * GET /api/analytics?action=account-health
 *
 * For each account (Threads + IG), queries account_metrics_history (last 14 days)
 * to detect stagnation, possible shadowbans, and breakout growth.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, getAuthUserOrError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabase } from "../../supabase.js";
import { enforceAnalyticsSubRateLimit } from "./rateLimit.js";

// biome-ignore lint/suspicious/noExplicitAny: table not yet in generated types
const db = (): any => getSupabase();

type HealthStatus = "healthy" | "stagnant" | "possible_shadowban" | "breakout";

interface AccountHealthEntry {
	accountId: string;
	username: string;
	platform: "threads" | "instagram";
	groupId: string | null;
	groupName: string | null;
	status: HealthStatus;
	details: string;
	followerCount: number;
	followerChange7d: number;
	avgViews7d: number;
	avgViewsPrev7d: number;
}

interface MetricsRow {
	account_id: string;
	date: string;
	followers_count: number;
	total_views: number;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	try {
		const userId = user.id;
		const allowed = await enforceAnalyticsSubRateLimit(res, {
			userId,
			action: "account-health",
			limit: 30,
		});
		if (!allowed) return;

		const now = Date.now();
		const fourteenDaysAgo = new Date(now - 14 * 86_400_000)
			.toISOString()
			.split("T")[0]!;
		const sevenDaysAgo = new Date(now - 7 * 86_400_000)
			.toISOString()
			.split("T")[0]!;

		// Parallel: fetch Threads accounts, IG accounts, account groups
		const [threadsResult, igResult, groupsResult] = await Promise.all([
			db()
				.from("accounts")
				.select("id, username, followers_count, group_id, is_active")
				.eq("user_id", userId),
			db()
				.from("instagram_accounts")
				.select("id, username, follower_count, group_id, is_active")
				.eq("user_id", userId),
			db().from("account_groups").select("id, name").eq("user_id", userId),
		]);

		if (threadsResult.error) {
			logger.error("[account-health] Failed to fetch Threads accounts", {
				error: threadsResult.error.message,
			});
			return apiError(res, 500, "Failed to fetch accounts");
		}
		if (igResult.error) {
			logger.error("[account-health] Failed to fetch IG accounts", {
				error: igResult.error.message,
			});
			return apiError(res, 500, "Failed to fetch accounts");
		}

		const threadsAccounts: Array<{
			id: string;
			username: string;
			followers_count: number;
			group_id: string | null;
			is_active: boolean;
		}> = threadsResult.data || [];

		const igAccounts: Array<{
			id: string;
			username: string;
			follower_count: number;
			group_id: string | null;
			is_active: boolean;
		}> = igResult.data || [];

		const groups: Array<{ id: string; name: string }> = groupsResult.data || [];
		const groupMap = new Map(groups.map((g) => [g.id, g.name]));

		// Collect all account IDs for batch metrics query
		const threadsAccountIds = threadsAccounts.map((a) => a.id);
		const igAccountIds = igAccounts.map((a) => a.id);
		const allAccountIds = [...threadsAccountIds, ...igAccountIds];

		if (allAccountIds.length === 0) {
			return apiSuccess(res, {
				accounts: [],
				summary: {
					healthy: 0,
					stagnant: 0,
					possibleShadowban: 0,
					breakout: 0,
					total: 0,
				},
			});
		}

		// Batch fetch metrics history for all accounts (last 14 days)
		const { data: metricsData, error: metricsError } = await db()
			.from("account_metrics_history")
			.select("account_id, date, followers_count, total_views")
			.in("account_id", allAccountIds)
			.gte("date", fourteenDaysAgo)
			.order("date", { ascending: true });

		if (metricsError) {
			logger.error("[account-health] Failed to fetch metrics history", {
				error: metricsError.message,
			});
			return apiError(res, 500, "Failed to fetch metrics history");
		}

		const allMetrics: MetricsRow[] = metricsData || [];

		// Group metrics by account_id
		const metricsByAccount = new Map<string, MetricsRow[]>();
		for (const row of allMetrics) {
			const existing = metricsByAccount.get(row.account_id);
			if (existing) {
				existing.push(row);
			} else {
				metricsByAccount.set(row.account_id, [row]);
			}
		}

		// Batch fetch post counts for the last 7 days (to detect stagnation with activity)
		const recentPostsQueries: Promise<{
			data: Array<{
				account_id?: string | null | undefined;
				instagram_account_id?: string | null | undefined;
			}> | null;
			error?: { message?: string | undefined } | undefined;
		}>[] = [];
		if (threadsAccountIds.length > 0) {
			recentPostsQueries.push(
				db()
					.from("posts")
					.select("account_id")
					.eq("user_id", userId)
					.eq("status", "published")
					.gte("created_at", new Date(now - 7 * 86_400_000).toISOString())
					.in("account_id", threadsAccountIds),
			);
		}
		if (igAccountIds.length > 0) {
			recentPostsQueries.push(
				db()
					.from("posts")
					.select("instagram_account_id")
					.eq("user_id", userId)
					.eq("status", "published")
					.eq("platform", "instagram")
					.gte("created_at", new Date(now - 7 * 86_400_000).toISOString())
					.in("instagram_account_id", igAccountIds),
			);
		}

		const recentPostResults = await Promise.all(recentPostsQueries);
		const postsError = recentPostResults.find((result) => result.error)?.error;

		if (postsError) {
			logger.error("[account-health] Failed to fetch recent posts", {
				error: postsError.message,
			});
			// Non-fatal: continue without post data
		}

		// Count posts per account
		const postsPerAccount = new Map<string, number>();
		for (const p of recentPostResults.flatMap((result) => result.data || [])) {
			const accountId = p.instagram_account_id || p.account_id;
			if (!accountId) continue;
			postsPerAccount.set(accountId, (postsPerAccount.get(accountId) || 0) + 1);
		}

		// Calculate per-group average growth rate (for breakout detection)
		const groupGrowthRates = new Map<string, number[]>();

		// First pass: compute growth rates for all accounts
		const accountGrowthRates = new Map<string, number>();

		for (const accountId of allAccountIds) {
			const metrics = metricsByAccount.get(accountId) || [];
			const recent = metrics.filter((m) => m.date >= sevenDaysAgo!);
			const older = metrics.filter((m) => m.date < sevenDaysAgo!);

			if (recent.length === 0 || older.length === 0) continue;

			const latestFollowers = recent[recent.length - 1]!.followers_count ?? 0;
			const oldestFollowers = older[0]!.followers_count ?? 0;

			if (oldestFollowers > 0) {
				const growthRate =
					((latestFollowers - oldestFollowers) / oldestFollowers) * 100;
				accountGrowthRates.set(accountId, growthRate);
			}
		}

		// Map account IDs to their group IDs
		const accountGroupMap = new Map<string, string | null>();
		for (const a of threadsAccounts) {
			accountGroupMap.set(a.id, a.group_id);
		}
		for (const a of igAccounts) {
			accountGroupMap.set(a.id, a.group_id);
		}

		// Build group growth rates for breakout detection
		for (const [accountId, rate] of accountGrowthRates) {
			const gid = accountGroupMap.get(accountId);
			if (!gid) continue;
			const existing = groupGrowthRates.get(gid);
			if (existing) {
				existing.push(rate);
			} else {
				groupGrowthRates.set(gid, [rate]);
			}
		}

		// Compute average growth per group
		const groupAvgGrowth = new Map<string, number>();
		for (const [gid, rates] of groupGrowthRates) {
			if (rates.length > 0) {
				const avg = rates.reduce((s, r) => s + r, 0) / rates.length;
				groupAvgGrowth.set(gid, avg);
			}
		}

		// Score each account
		function scoreAccount(
			accountId: string,
			username: string,
			platform: "threads" | "instagram",
			currentFollowers: number,
			groupId: string | null,
		): AccountHealthEntry {
			const metrics = metricsByAccount.get(accountId) || [];
			const recentMetrics = metrics.filter((m) => m.date >= sevenDaysAgo!);
			const olderMetrics = metrics.filter((m) => m.date < sevenDaysAgo!);

			// Follower change over last 7 days
			let followerChange7d = 0;
			if (recentMetrics.length >= 2) {
				const first = recentMetrics[0]!.followers_count ?? 0;
				const last =
					recentMetrics[recentMetrics.length - 1]!.followers_count ?? 0;
				followerChange7d = last - first;
			} else if (recentMetrics.length === 1 && olderMetrics.length > 0) {
				const oldLast =
					olderMetrics[olderMetrics.length - 1]!.followers_count ?? 0;
				const newLast = recentMetrics[0]!.followers_count ?? 0;
				followerChange7d = newLast - oldLast;
			}

			// Average views for recent 7d vs prior 7d
			const avgViews7d = computeAvgViews(recentMetrics);
			const avgViewsPrev7d = computeAvgViews(olderMetrics);

			// Has published posts in last 7 days?
			const hasRecentPosts = (postsPerAccount.get(accountId) || 0) > 0;

			// Determine status
			let status: HealthStatus = "healthy";
			let details = "Account is performing normally";

			// Check stagnant: follower count unchanged for 7+ days AND has posted
			const isStagnant =
				followerChange7d === 0 && hasRecentPosts && recentMetrics.length >= 3;

			// Check possible shadowban: avg views dropped >50%
			const isPossibleShadowban =
				avgViewsPrev7d > 0 &&
				avgViews7d > 0 &&
				avgViews7d < avgViewsPrev7d * 0.5;

			// Check breakout: growth rate is >2x group average
			const growthRate = accountGrowthRates.get(accountId);
			const groupAvg =
				groupId != null ? groupAvgGrowth.get(groupId) : undefined;
			const isBreakout =
				growthRate !== undefined &&
				groupAvg !== undefined &&
				groupAvg > 0 &&
				growthRate > groupAvg * 2;

			// Priority: shadowban > stagnant > breakout > healthy
			if (isPossibleShadowban) {
				const dropPct =
					avgViewsPrev7d > 0
						? Math.round(((avgViewsPrev7d - avgViews7d) / avgViewsPrev7d) * 100)
						: 0;
				status = "possible_shadowban";
				details = `Average views dropped ${dropPct}% (${Math.round(avgViewsPrev7d)} -> ${Math.round(avgViews7d)}) compared to prior 7 days`;
			} else if (isStagnant) {
				status = "stagnant";
				details = `Follower count unchanged at ${currentFollowers} for 7+ days despite publishing ${postsPerAccount.get(accountId) || 0} posts`;
			} else if (isBreakout) {
				status = "breakout";
				details = `Follower growth rate (${growthRate?.toFixed(1)}%) is more than 2x the group average (${groupAvg?.toFixed(1)}%)`;
			}

			return {
				accountId,
				username,
				platform,
				groupId,
				groupName: groupId ? (groupMap.get(groupId) ?? null) : null,
				status,
				details,
				followerCount: currentFollowers,
				followerChange7d,
				avgViews7d: Math.round(avgViews7d),
				avgViewsPrev7d: Math.round(avgViewsPrev7d),
			};
		}

		const accounts: AccountHealthEntry[] = [];

		// Score Threads accounts
		for (const a of threadsAccounts) {
			if (!a.is_active) continue;
			accounts.push(
				scoreAccount(
					a.id,
					a.username,
					"threads",
					a.followers_count ?? 0,
					a.group_id,
				),
			);
		}

		// Score IG accounts (note: follower_count is singular)
		for (const a of igAccounts) {
			if (!a.is_active) continue;
			accounts.push(
				scoreAccount(
					a.id,
					a.username,
					"instagram",
					a.follower_count ?? 0,
					a.group_id,
				),
			);
		}

		// Build summary
		const summary = {
			healthy: 0,
			stagnant: 0,
			possibleShadowban: 0,
			breakout: 0,
			total: accounts.length,
		};

		for (const a of accounts) {
			switch (a.status) {
				case "healthy":
					summary.healthy++;
					break;
				case "stagnant":
					summary.stagnant++;
					break;
				case "possible_shadowban":
					summary.possibleShadowban++;
					break;
				case "breakout":
					summary.breakout++;
					break;
			}
		}

		return apiSuccess(res, { accounts, summary });
	} catch (error) {
		logger.error("[account-health] Unexpected error", {
			error: error instanceof Error ? error.message : String(error),
		});
		return apiError(res, 500, "Internal server error");
	}
}

/** Compute average total_views from a set of metrics rows */
function computeAvgViews(metrics: MetricsRow[]): number {
	if (metrics.length === 0) return 0;
	const total = metrics.reduce((s, m) => s + (m.total_views ?? 0), 0);
	return total / metrics.length;
}
