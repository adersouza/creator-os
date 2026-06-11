// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Analytics refresh, deltas, demographics API operations
 */

import type { RealtimeChannel } from "@supabase/supabase-js";
import {
	ANALYTICS_SELECT,
	METRIC_REGISTRY,
	type MetricAggregation,
} from "../../src/lib/metricRegistry.js";
import { getAccountIdsForContext } from "../../src/lib/workspaceAccounts.js";
import type { Platform } from "../../src/types/platform.js";
import type {
	AccountAnalyticsRow,
	AnalyticsStats,
	MappedAnalyticsRow,
	SyncJobProgress,
	SyncJobStatus,
	SyncResult,
	SyncResultSingle,
} from "../../types/analytics.js";
import { getAccount, getAccounts } from "./accounts.js";
import {
	getUserIdAsync,
	logger,
	safeJsonParse,
	supabase,
	withRetry,
} from "./shared.js";

type AnalyticsAccountIdentity = { id: string; username: string | null };
type AnalyticsRowWithHandles = AccountAnalyticsRow & {
	accounts?: { username?: string | null | undefined } | null | undefined;
	instagram_accounts?: { username?: string | null | undefined } | null | undefined;
};
type AggregatedAnalyticsRow = {
	date: string;
	followers_count: number | null;
	total_views: number | null;
	total_likes: number | null;
	total_replies: number | null;
	total_reposts: number | null;
	total_quotes: number | null;
	total_shares: number | null;
	total_clicks: number | null;
	engagement_rate: number | null;
};
type AggregatedAnalyticsApiResponse = {
	rows?: AggregatedAnalyticsRow[] | null | undefined;
	error?: string | undefined;
};
type PostFloorAggregateRow = {
	total_views?: number | string | null | undefined;
	total_likes?: number | string | null | undefined;
	total_replies?: number | string | null | undefined;
	total_reposts?: number | string | null | undefined;
	total_quotes?: number | string | null | undefined;
	total_shares?: number | string | null | undefined;
	total_clicks?: number | string | null | undefined;
	total_saves?: number | string | null | undefined;
	post_count?: number | string | null | undefined;
};
type PostFloorAggregateApiResponse = {
	row?: PostFloorAggregateRow | null | undefined;
	error?: string | undefined;
};
type StatsAccountSummary = {
	id: string;
	status?: string | null | undefined;
	followers_count?: number | null | undefined;
	follower_count?: number | null | undefined;
};

/**
 * Resolve "ALL" to a list of account IDs scoped to the given workspace.
 * When workspaceId is null, returns all accounts for userId (backward compatible).
 */
async function resolveAllAccountIds(
	userId: string,
	workspaceId: string | null | undefined,
	platform: string,
): Promise<string[]> {
	return getAccountIdsForContext(
		userId,
		workspaceId ?? null,
		platform === "instagram" || platform === "threads" ? platform : undefined,
	);
}

export async function getAnalytics(
	accountId: string = "ALL",
	daysLimit: number = 30,
	platform: string = "threads",
	workspaceId?: string | null,
): Promise<MappedAnalyticsRow[]> {
	const userId = await getUserIdAsync();

	const cutoffDate = new Date();
	cutoffDate.setDate(cutoffDate.getDate() - daysLimit);
	const cutoffDateStr = cutoffDate.toISOString().split("T")[0]!;

	const isInstagram = platform === "instagram";
	logger.debug(
		`[apiService.getAnalytics] accountId=${accountId}, platform=${platform}, isInstagram=${isInstagram}, daysLimit=${daysLimit}`,
	);

	const mapRow = (
		row: AnalyticsRowWithHandles,
		includeAccountInfo = false,
	): MappedAnalyticsRow => {
		const rawDate = new Date(`${row.date}T00:00:00`);
		return {
			...row,
			id: row.id,
			...(includeAccountInfo
				? {
						accountId: row.account_id,
						accountHandle:
							row.accounts?.username ||
							row.instagram_accounts?.username ||
							undefined,
					}
				: {}),
			date: rawDate.toLocaleDateString("en-US", {
				month: "short",
				day: "numeric",
			}),
			followersCount: row.followers_count || 0,
			followers: row.followers_count || 0,
			followingCount: row.following_count || 0,

			views: row.total_views || 0,
			likes: row.total_likes || 0,
			replies: row.total_replies || 0,
			reposts: row.total_reposts || 0,
			quotes: row.total_quotes || 0,
			shares: row.total_shares || 0,
			clicks: row.total_clicks || 0,
			engagementRate: row.engagement_rate || 0,
			followerGrowth: row.follower_growth || 0,
			rawDate,
			isBackfilled: false,
		};
	};

	if (accountId !== "ALL") {
		if (isInstagram) {
			const { data: igAccount } = await supabase
				.from("instagram_accounts")
				.select("id, username")
				.eq("id", accountId)
				.eq("user_id", userId)
				.maybeSingle();

			if (!igAccount) {
				logger.debug(
					`[apiService.getAnalytics] IG account ${accountId} not found for user`,
				);
				return [];
			}

			const { data, error } = (await withRetry(
				async () =>
					supabase
						.from("account_analytics")
						.select("*")
						.eq("account_id", accountId)
						.gte("date", cutoffDateStr)
						.order("date", { ascending: false })
						.limit(daysLimit),
				{ name: "getAnalytics(instagram)" },
			)) as { data: AccountAnalyticsRow[] | null; error: unknown };

			if (error) {
				logger.error("Failed to fetch IG analytics:", error);
				return [];
			}

			logger.debug(
				`[apiService.getAnalytics] Got ${data?.length || 0} rows for IG account ${accountId} (${igAccount.username})`,
			);
			return (data || []).map((row) => mapRow(row));
		} else {
			const { data: threadsAccount } = await supabase
				.from("accounts")
				.select("id, username")
				.eq("id", accountId)
				.eq("user_id", userId)
				.maybeSingle();

			if (!threadsAccount) {
				logger.debug(
					`[apiService.getAnalytics] Threads account ${accountId} not found for user`,
				);
				return [];
			}

			const { data, error } = (await withRetry(
				async () =>
					supabase
						.from("account_analytics")
						.select("*")
						.eq("account_id", accountId)
						.gte("date", cutoffDateStr)
						.order("date", { ascending: false })
						.limit(daysLimit),
				{ name: "getAnalytics(threads)" },
			)) as { data: AccountAnalyticsRow[] | null; error: unknown };

			if (error) {
				logger.error("Failed to fetch Threads analytics:", error);
				return [];
			}

			logger.debug(
				`[apiService.getAnalytics] Got ${data?.length || 0} rows for Threads account ${accountId} (${threadsAccount.username})`,
			);
			return (data || []).map((row) => mapRow(row));
		}
	}

	// ALL accounts — scale limit with account count to avoid truncation
	// Each account can have up to daysLimit rows

	if (isInstagram) {
		const resolvedIds = await resolveAllAccountIds(
			userId,
			workspaceId,
			"instagram",
		);
		const { data: igAccounts } =
			resolvedIds.length > 0
				? await supabase
						.from("instagram_accounts")
						.select("id, username")
						.in("id", resolvedIds)
				: { data: [] };

		if (!igAccounts || igAccounts.length === 0) {
			logger.debug("[apiService.getAnalytics] No IG accounts found for user");
			return [];
		}

		const igAccountIds = igAccounts.map((a: AnalyticsAccountIdentity) => a.id);
		const usernameMap = new Map<string, string>(
			igAccounts.map(
				(a: AnalyticsAccountIdentity) =>
					[a.id, a.username || ""] as [string, string],
			),
		);
		const maxRows = igAccounts.length * daysLimit;

		const { data, error } = (await withRetry(
			async () =>
				supabase
					.from("account_analytics")
					.select("*")
					.in("account_id", igAccountIds)
					.gte("date", cutoffDateStr)
					.order("date", { ascending: false })
					.limit(maxRows),
			{ name: "getAnalytics(ALL,instagram)" },
		)) as { data: AccountAnalyticsRow[] | null; error: unknown };

		if (error) {
			logger.error("Failed to fetch all IG analytics:", error);
			return [];
		}

		logger.debug(
			`[apiService.getAnalytics] Got ${data?.length || 0} rows for ALL IG accounts`,
		);
		return (data || []).map((row) => ({
			...mapRow(row, true),
			accountHandle: usernameMap.get(row.account_id) || "unknown",
		}));
	} else {
		const resolvedIds = await resolveAllAccountIds(
			userId,
			workspaceId,
			"threads",
		);
		const { data: threadsAccounts } =
			resolvedIds.length > 0
				? await supabase
						.from("accounts")
						.select("id, username")
						.in("id", resolvedIds)
				: { data: [] };

		if (!threadsAccounts || threadsAccounts.length === 0) {
			logger.debug(
				"[apiService.getAnalytics] No Threads accounts found for user",
			);
			return [];
		}

		const accountIds = threadsAccounts.map((a) => a.id);
		const usernameMap = new Map<string, string>(
			threadsAccounts.map((a) => [a.id, a.username] as [string, string]),
		);
		const maxRows = threadsAccounts.length * daysLimit;

		const { data, error } = (await withRetry(
			async () =>
				supabase
					.from("account_analytics")
					.select("*")
					.in("account_id", accountIds)
					.gte("date", cutoffDateStr)
					.order("date", { ascending: false })
					.limit(maxRows),
			{ name: "getAnalytics(ALL,threads)" },
		)) as { data: AccountAnalyticsRow[] | null; error: unknown };

		if (error) {
			logger.error("Failed to fetch all Threads analytics:", error);
			return [];
		}

		logger.debug(
			`[apiService.getAnalytics] Got ${data?.length || 0} rows for ALL Threads accounts`,
		);
		return (data || []).map((row) => ({
			...mapRow(row, true),
			accountHandle: usernameMap.get(row.account_id) || "unknown",
		}));
	}
}

/**
 * Server-side aggregated analytics for "ALL" accounts view.
 * Returns ~days rows (one per day) instead of N_accounts * days rows.
 * Uses Supabase RPC function for efficient GROUP BY on the database.
 */
export async function getAggregatedAnalytics(
	daysLimit: number = 90,
	platform: string = "threads",
	accountIds?: string[],
	workspaceId?: string | null,
): Promise<MappedAnalyticsRow[]> {
	const userId = await getUserIdAsync();

	// If no explicit accountIds, resolve from workspace context
	const resolvedIds =
		accountIds ?? (await resolveAllAccountIds(userId, workspaceId, platform));

	const {
		data: { session },
	} = await supabase.auth.getSession();
	const response = await fetch("/api/analytics?action=aggregated", {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
		},
		body: JSON.stringify({
			days: daysLimit,
			platform,
			accountIds: resolvedIds.length > 0 ? resolvedIds : null,
		}),
	});

	if (!response.ok) {
		const error = await response.json().catch(() => ({}));
		logger.error("Failed to fetch aggregated analytics:", error);
		// Fallback to per-row fetch
		return getAnalytics("ALL", daysLimit, platform, workspaceId);
	}

	const payload = (await response.json()) as AggregatedAnalyticsApiResponse;
	const rows = payload.rows || [];
	if (rows.length === 0) return [];

	return rows.map((row) => {
		const rawDate = new Date(`${row.date}T00:00:00`);
		return {
			id: `agg-${row.date}`,
			account_id: "ALL",
			user_id: userId,
			date: rawDate.toLocaleDateString("en-US", {
				month: "short",
				day: "numeric",
			}),
			followersCount: Number(row.followers_count) || 0,
			followers: Number(row.followers_count) || 0,
			followingCount: 0,
			views: Number(row.total_views) || 0,
			likes: Number(row.total_likes) || 0,
			replies: Number(row.total_replies) || 0,
			reposts: Number(row.total_reposts) || 0,
			quotes: Number(row.total_quotes) || 0,
			shares: Number(row.total_shares) || 0,
			clicks: Number(row.total_clicks) || 0,
			engagementRate: Number(row.engagement_rate) || 0,
			followerGrowth: 0,
			rawDate,
			isBackfilled: false,
		} as MappedAnalyticsRow;
	});
}

export async function getAnalyticsStats(
	accountId: string = "ALL",
	platform: Platform = "threads",
	workspaceId?: string | null,
	periodDays?: number,
	scopeAccountIds?: string[],
): Promise<AnalyticsStats> {
	const userId = await getUserIdAsync();

	let accounts: StatsAccountSummary[];
	if (scopeAccountIds && scopeAccountIds.length > 0) {
		// Scoped mode: use the provided account IDs directly (e.g., group-filtered)
		// Use .or() instead of .neq() to include NULL-status accounts (active accounts
		// may have status = NULL; .neq("status","suspended") excludes NULLs in Postgres).
		if (platform === "instagram") {
			const { data } = await supabase
				.from("instagram_accounts")
				.select("*")
				.in("id", scopeAccountIds)
				.or("status.is.null,status.neq.suspended");
			accounts = data || [];
		} else {
			const { data } = await supabase
				.from("accounts")
				.select("*")
				.in("id", scopeAccountIds)
				.or("status.is.null,status.neq.suspended");
			accounts = data || [];
		}
	} else if (accountId !== "ALL") {
		// Single-account: query raw rows to get snake_case follower columns.
		// getAccount() returns camelCase ServiceAccount objects; the live follower
		// computation below reads followers_count / follower_count (snake_case).
		if (platform === "instagram") {
			const { data } = await supabase
				.from("instagram_accounts")
				.select("*")
				.eq("id", accountId)
				.maybeSingle();
			accounts = data ? [data] : [];
		} else {
			const { data } = await supabase
				.from("accounts")
				.select("*")
				.eq("id", accountId)
				.maybeSingle();
			accounts = data ? [data] : [];
		}
	} else {
		const resolvedIds = await resolveAllAccountIds(
			userId,
			workspaceId,
			platform,
		);
		if (resolvedIds.length === 0) {
			accounts = [];
		} else if (platform === "instagram") {
			const { data } = await supabase
				.from("instagram_accounts")
				.select("*")
				.in("id", resolvedIds)
				.or("status.is.null,status.neq.suspended");
			accounts = data || [];
		} else {
			const { data } = await supabase
				.from("accounts")
				.select("*")
				.in("id", resolvedIds)
				.or("status.is.null,status.neq.suspended");
			accounts = data || [];
		}
	}

	if (!accounts || accounts.length === 0) {
		return {
			totalFollowers: 0,
			totalLikes: 0,
			totalReplies: 0,
			totalViews: 0,
			totalReposts: 0,
			totalQuotes: 0,
			totalShares: 0,
			totalClicks: 0,
			scheduledCount: 0,
			igNewFollows: 0,
			igUnfollows: 0,
			igAccountsEngaged: 0,
			igProfileViews: 0,
			igWebsiteClicks: 0,
			igTotalInteractions: 0,
			igNonFollowerReachPct: 0,
		};
	}

	const accountIds = accounts.map((a) => a.id);

	// Compute date cutoff for period-scoped queries
	let cutoffDateStr: string | null = null;
	if (periodDays && periodDays > 0) {
		const cutoff = new Date();
		cutoff.setDate(cutoff.getDate() - periodDays);
		cutoffDateStr = cutoff.toISOString().split("T")[0]!;
	}

	// Fetch rows from account_analytics within the period.
	// For "latest"/"snapshot" metrics we only need the most recent row per account,
	// but we fetch up to 2 rows per account to cover edge cases.
	// IMPORTANT: Supabase PostgREST defaults to 1000 rows if no limit is set,
	// which silently truncates results for large account sets.
	const rowLimit = Math.max(accountIds.length * 2, 500);
	let analyticsQuery = supabase
		.from("account_analytics")
		.select(ANALYTICS_SELECT)
		.in("account_id", accountIds)
		.order("date", { ascending: false })
		.limit(rowLimit);

	if (cutoffDateStr) {
		analyticsQuery = analyticsQuery.gte("date", cutoffDateStr);
	}

	const { data: rows } = (await analyticsQuery) as {
		data: Partial<AccountAnalyticsRow>[] | null;
		error: unknown;
	};

	// Registry-driven aggregation:
	// "sum" metrics: SUM all rows across all accounts in the period
	// "latest"/"snapshot" metrics: take the latest row per account (already sorted desc by date)
	const totals: Record<string, number> = {};
	const latestSeen = new Set<string>(); // tracks per-account latest for "latest"/"snapshot"

	if (rows && rows.length > 0) {
		for (const row of rows) {
			const aid = row.account_id || "";
			const isFirstRowForAccount = !latestSeen.has(aid);
			if (isFirstRowForAccount) latestSeen.add(aid);

			for (const metric of METRIC_REGISTRY) {
				if (!metric.dbColumn) continue;
				if (!metric.platforms.includes(platform)) continue;

				const agg: MetricAggregation = metric.aggregation ?? "sum";
				const dbVal = (row as Record<string, unknown>)[
					metric.dbColumn
				] as number;
				const val = dbVal || 0;

				if (agg === "sum") {
					// SUM all rows in the period
					totals[metric.key] = (totals[metric.key] || 0) + val;
				} else {
					// "latest" or "snapshot": take the most recent row per account
					if (isFirstRowForAccount) {
						totals[metric.key] = (totals[metric.key] || 0) + val;
					}
				}
			}
		}
	}

	// Followers: live account values are more reliable than analytics snapshots.
	// Always compute both and take the higher value.
	const analyticsFollowers = totals.totalFollowers || 0;
	let liveFollowers = 0;
	for (const account of accounts) {
		if (account.status === "suspended") continue;
		liveFollowers += account.followers_count || account.follower_count || 0;
	}
	const totalFollowers = Math.max(analyticsFollowers, liveFollowers);

	// Scheduled count
	let scheduledQuery = supabase
		.from("posts")
		.select("id", { count: "exact" })
		.eq("user_id", userId)
		.eq("status", "scheduled");

	if (accountId !== "ALL") {
		scheduledQuery =
			platform === "instagram"
				? scheduledQuery.eq("instagram_account_id", accountId)
				: scheduledQuery.eq("account_id", accountId);
	} else if (platform === "instagram") {
		scheduledQuery = scheduledQuery.eq("platform", "instagram");
	} else if (platform === "threads") {
		scheduledQuery = scheduledQuery.eq("platform", "threads");
	}

	const { count } = await scheduledQuery;

	const totalLikes = totals.totalLikes || 0;
	const totalReplies = totals.totalReplies || 0;
	const totalViews = totals.totalViews || 0;
	const totalReposts = totals.totalReposts || 0;
	const totalQuotes = totals.totalQuotes || 0;
	const totalClicks = totals.totalClicks || 0;
	const totalIgReach = totals.totalIgReach || 0;
	const totalIgSaved = totals.totalIgSaved || 0;
	const totalIgShares = totals.totalIgShares || 0;
	const totalIgImpressions = totals.totalIgImpressions || 0;

	// Engagement rate (mirrors api/_lib/metricCalculators.ts)
	let engagementRate: number;
	if (platform === "instagram") {
		const interactions =
			totalLikes + totalReplies * 2 + totalIgSaved * 3 + totalIgShares;
		// Prefer reach as denominator (Meta standard). Fall back to followers when
		// reach is unavailable (accounts without insights permission). If neither
		// is available, return 0 rather than dividing by 1 and inflating the rate
		// to thousands of percent.
		const denominator = totalIgReach > 0 ? totalIgReach : totalFollowers > 0 ? totalFollowers : 0;
		engagementRate = denominator > 0 ? (interactions / denominator) * 100 : 0;
	} else {
		const interactions =
			totalLikes + totalReplies * 2 + totalReposts * 1.5 + totalQuotes;
		engagementRate = (interactions / Math.max(totalViews, 1)) * 100;
	}

	// Reels watch-to-view: requires post-level aggregation (reels only).
	// One extra query; skipped for threads platform.
	let igReelsWatchPerView: number | undefined;
	if (platform === "instagram" && accountIds.length > 0) {
		let reelsQuery = supabase
			.from("posts")
			.select("ig_views, ig_reels_video_view_total_time")
			.in("instagram_account_id", accountIds)
			.eq("ig_media_type", "REELS")
			.eq("status", "published");
		if (cutoffDateStr) {
			reelsQuery = reelsQuery.gte("published_at", cutoffDateStr);
		}
		const { data: reelsRows } = await reelsQuery;
		if (reelsRows && reelsRows.length > 0) {
			let totalWatchSeconds = 0;
			let totalViews = 0;
			for (const r of reelsRows as Array<{
				ig_views: number | null;
				ig_reels_video_view_total_time: number | null;
			}>) {
				totalWatchSeconds += r.ig_reels_video_view_total_time || 0;
				totalViews += r.ig_views || 0;
			}
			if (totalViews > 0) {
				igReelsWatchPerView = totalWatchSeconds / totalViews;
			}
		}
	}

	// Save-to-reach: strongest IG ranking proxy Meta exposes.
	const igSaveRate =
		totalIgReach > 0 ? totalIgSaved / totalIgReach : undefined;

	// Quote-to-reply: >1 hot-take, <1 conversation.
	const threadsQuoteReplyRatio =
		totalReplies > 0 ? totalQuotes / totalReplies : undefined;

	return {
		totalFollowers,
		totalLikes,
		totalReplies,
		totalViews,
		totalReposts,
		totalQuotes,
		totalShares: totals.totalShares || 0,
		totalClicks,
		scheduledCount: count || 0,
		engagementRate,
		totalIgReach,
		totalIgSaved,
		totalIgShares,
		totalIgImpressions,
		igNewFollows: totals.igNewFollows || 0,
		igUnfollows: totals.igUnfollows || 0,
		igAccountsEngaged: totals.igAccountsEngaged || 0,
		igProfileViews: totals.igProfileViews || 0,
		igWebsiteClicks: totals.igWebsiteClicks || 0,
		igTotalInteractions: totals.igTotalInteractions || 0,
		igNonFollowerReachPct: totals.igNonFollowerReachPct || 0,
		igSaveRate,
		igReelsWatchPerView,
		threadsQuoteReplyRatio,
	};
}

export async function getAnalyticsWithDeltas(
	accountId: string = "ALL",
	periodDays: number = 7,
	platform: Platform = "threads",
	workspaceId?: string | null,
	scopeAccountIds?: string[],
): Promise<{
	current: Record<string, number>;
	previous: Record<string, number>;
	deltas: {
		followers: string;
		likes: string;
		replies: string;
		reposts: string;
		views: string;
		clicks: string;
		reach: string;
		saves: string;
		shares: string;
		engagement: string;
	};
}> {
	// Period-scoped: "sum" metrics return the period total, "latest"/"snapshot" return latest value
	const currentStats = await getAnalyticsStats(
		accountId,
		platform,
		workspaceId,
		periodDays > 0 ? periodDays : undefined,
		scopeAccountIds,
	);
	const userId = await getUserIdAsync();

	let accounts: StatsAccountSummary[];
	if (scopeAccountIds && scopeAccountIds.length > 0) {
		// Scoped mode: use the provided account IDs directly
		if (platform === "instagram") {
			const { data } = await supabase
				.from("instagram_accounts")
				.select("id, follower_count, status")
				.in("id", scopeAccountIds)
				.or("status.is.null,status.neq.suspended");
			accounts = data || [];
		} else {
			const { data } = await supabase
				.from("accounts")
				.select("id, followers_count, status")
				.in("id", scopeAccountIds)
				.or("status.is.null,status.neq.suspended");
			accounts = data || [];
		}
	} else if (accountId !== "ALL") {
		accounts = [await getAccount(accountId)];
	} else {
		const resolvedIds = await resolveAllAccountIds(
			userId,
			workspaceId,
			platform,
		);
		if (resolvedIds.length === 0) {
			accounts = [];
		} else if (platform === "instagram") {
			const { data } = await supabase
				.from("instagram_accounts")
				.select("id, follower_count, status")
				.in("id", resolvedIds)
				.or("status.is.null,status.neq.suspended");
			accounts = data || [];
		} else {
			const { data } = await supabase
				.from("accounts")
				.select("id, followers_count, status")
				.in("id", resolvedIds)
				.or("status.is.null,status.neq.suspended");
			accounts = data || [];
		}
	}

	if (!accounts || accounts.length === 0) {
		return {
			current: {
				totalFollowers: 0,
				totalLikes: 0,
				totalReplies: 0,
				totalReposts: 0,
				totalQuotes: 0,
				totalShares: 0,
				totalClicks: 0,
				totalViews: 0,
				scheduledCount: 0,
				totalIgImpressions: 0,
				totalIgReach: 0,
				totalIgSaved: 0,
				totalIgShares: 0,
				igNewFollows: 0,
				igUnfollows: 0,
				igAccountsEngaged: 0,
				igProfileViews: 0,
				igWebsiteClicks: 0,
				igTotalInteractions: 0,
				igNonFollowerReachPct: 0,
			},
			previous: {
				totalFollowers: 0,
				totalLikes: 0,
				totalReplies: 0,
				totalReposts: 0,
				totalViews: 0,
				totalIgReach: 0,
				totalIgSaved: 0,
				totalIgShares: 0,
			},
			deltas: {
				followers: "—",
				likes: "—",
				replies: "—",
				reposts: "—",
				views: "—",
				clicks: "—",
				reach: "—",
				saves: "—",
				shares: "—",
				engagement: "—",
			},
		};
	}

	const accountIds = accounts.map((a) => a.id);

	let previousAnalytics: Partial<AccountAnalyticsRow>[] | null = null;

	// Post-level period sums — authoritative floor for period metrics.
	// Queries ALL published posts in the period (no client-side ~500 limit).
	// Used as Math.max(snapshotGain, postLevelSums) to guarantee accuracy
	// even when account_analytics history is incomplete for new accounts.
	const postFloor = {
		views: 0,
		likes: 0,
		replies: 0,
		reposts: 0,
		quotes: 0,
		shares: 0,
		clicks: 0,
		saves: 0,
		count: 0,
	};

	if (periodDays > 0) {
		const previousDate = new Date();
		previousDate.setDate(previousDate.getDate() - periodDays);
		const dateStr = previousDate.toISOString().split("T")[0]!;
		const cutoffIso = new Date(
			Date.now() - periodDays * 86_400_000,
		).toISOString();

		// Post-level floor: use server-side RPC to aggregate sums.
		// This avoids PostgREST's 1000-row default limit which was causing
		// undercounted views (1000 of 1309 posts → 24k instead of 32k).
		const {
			data: { session },
		} = await supabase.auth.getSession();
		const postFloorRequest = fetch(
			"/api/analytics?action=post-floor-aggregates",
			{
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session?.access_token}`,
				},
				body: JSON.stringify({
					accountIds,
					since: cutoffIso,
					platform: platform === "instagram" ? "instagram" : null,
				}),
			},
		);

		// Run previous analytics + post-level sums in parallel
		const [prevResult, postFloorResult] = await Promise.all([
			supabase
				.from("account_analytics")
				.select(
					"account_id, total_likes, total_replies, total_views, total_reposts, total_quotes, total_shares, total_reach, total_saves, total_clicks, followers_count, date",
				)
				.in("account_id", accountIds)
				.lte("date", dateStr)
				.order("date", { ascending: false })
				.limit(accountIds.length * 2),
			postFloorRequest,
		]);

		previousAnalytics = prevResult.data as
			| Partial<AccountAnalyticsRow>[]
			| null;

		// Parse post floor aggregate result
		if (postFloorResult.ok) {
			const payload =
				(await postFloorResult.json()) as PostFloorAggregateApiResponse;
			const row = payload.row;
			if (row) {
				postFloor.views = Number(row.total_views) || 0;
				postFloor.likes = Number(row.total_likes) || 0;
				postFloor.replies = Number(row.total_replies) || 0;
				postFloor.reposts = Number(row.total_reposts) || 0;
				postFloor.quotes = Number(row.total_quotes) || 0;
				postFloor.shares = Number(row.total_shares) || 0;
				postFloor.clicks = Number(row.total_clicks) || 0;
				postFloor.saves = Number(row.total_saves) || 0;
				postFloor.count = Number(row.post_count) || 0;
			}
		}
	}

	let prevFollowers = 0;
	let prevLikes = 0;
	let prevReplies = 0;
	let prevViews = 0;
	let prevReposts = 0;
	let prevQuotes = 0;
	let prevShares = 0;
	let prevClicks = 0;
	let prevReach = 0;
	let prevSaves = 0;
	let hasPreviousData = false;

	// Track which accounts have a previous baseline — accounts without one
	// should NOT contribute their full cumulative total to the period delta.
	const accountsWithBaseline = new Set<string>();

	if (previousAnalytics && previousAnalytics.length > 0) {
		const seen = new Set<string>();
		for (const row of previousAnalytics) {
			const aid = row.account_id || "";
			if (!seen.has(aid)) {
				seen.add(aid);
				accountsWithBaseline.add(aid);

				prevFollowers += row.followers_count || 0;
				prevLikes += row.total_likes || 0;
				prevReplies += row.total_replies || 0;
				prevViews += row.total_views || 0;
				prevReposts += row.total_reposts || 0;
				prevQuotes += row.total_quotes || 0;
				prevShares += row.total_shares || 0;
				prevClicks += row.total_clicks || 0;
				prevReach += row.total_reach || 0;
				prevSaves += row.total_saves || 0;
				hasPreviousData = true;
			}
		}
	}

	// Fetch pre-previous period (2× periodDays ago) for period-over-period deltas
	let prePrevFollowers = 0;
	let prePrevLikes = 0;
	let prePrevReplies = 0;
	let prePrevViews = 0;
	let prePrevReposts = 0;
	let prePrevShares = 0;
	let prePrevClicks = 0;
	let _prePrevReach = 0;
	let prePrevSaves = 0;
	let hasPrePreviousData = false;

	if (periodDays > 0 && hasPreviousData) {
		const prePrevDate = new Date();
		prePrevDate.setDate(prePrevDate.getDate() - periodDays * 2);
		const prePrevDateStr = prePrevDate.toISOString().split("T")[0]!;

		const { data: prePrevRows } = (await supabase
			.from("account_analytics")
			.select(
				"account_id, followers_count, total_likes, total_replies, total_views, total_reposts, total_shares, total_clicks, total_reach, total_saves",
			)
			.in("account_id", accountIds)
			.lte("date", prePrevDateStr)
			.order("date", { ascending: false })
			.limit(accountIds.length * 2)) as {
			data: Partial<AccountAnalyticsRow>[] | null;
		};

		if (prePrevRows && prePrevRows.length > 0) {
			const seen = new Set<string>();
			for (const row of prePrevRows) {
				const aid = row.account_id || "";
				if (!seen.has(aid) && accountsWithBaseline.has(aid)) {
					seen.add(aid);
					prePrevFollowers += row.followers_count || 0;
					prePrevLikes += row.total_likes || 0;
					prePrevReplies += row.total_replies || 0;
					prePrevViews += row.total_views || 0;
					prePrevReposts += row.total_reposts || 0;
					prePrevShares += row.total_shares || 0;
					prePrevClicks += row.total_clicks || 0;
					_prePrevReach += row.total_reach || 0;
					prePrevSaves += row.total_saves || 0;
					hasPrePreviousData = true;
				}
			}
		}
	}

	const computeDelta = (current: number, previous: number): string => {
		if (previous <= 0 && current === 0) return "0%";
		if (previous <= 0) return current > 0 ? "New" : "0%";
		const pct = ((current - previous) / previous) * 100;
		if (Math.abs(pct) < 0.1) return "0%";
		const sign = pct >= 0 ? "+" : "";
		return `${sign}${pct.toFixed(1)}%`;
	};

	const isAllTime = periodDays === 0;

	// Period metric computation strategy:
	//   1. PRIMARY: per-account snapshot subtraction (only for accounts with a baseline)
	//   2. FLOOR: post-level sums from ALL published posts in period (no client limit)
	//   3. Result: Math.max(snapshotGain, postFloor) — guarantees accuracy
	//   4. All-time: use cumulative totals directly
	//   5. No previous data + not all-time: fall back to postFloor (not 0)
	//
	// CRITICAL: Only include accounts that have both a current AND previous snapshot
	// in the delta. Accounts without a previous row would inflate the delta with
	// their full all-time cumulative total (prev=0 → delta=entire history).
	const canComputePeriod = hasPreviousData && !isAllTime;

	// Compute baseline-matched current: only sum current values for accounts
	// that have a previous row (so the subtraction is apples-to-apples).
	let matchedCurViews = 0,
		matchedCurLikes = 0,
		matchedCurReplies = 0;
	let matchedCurReposts = 0,
		matchedCurQuotes = 0,
		matchedCurShares = 0;
	let matchedCurClicks = 0,
		matchedCurSaves = 0;

	if (canComputePeriod) {
		// Re-read current analytics rows (already fetched by getAnalyticsStats, but
		// we need per-account breakdown). Query latest row per account.
		const { data: curRows } = (await supabase
			.from("account_analytics")
			.select(
				"account_id, total_views, total_likes, total_replies, total_reposts, total_quotes, total_shares, total_clicks, total_saves",
			)
			.in("account_id", accountIds)
			.order("date", { ascending: false })
			.limit(accountIds.length * 2)) as {
			data: Partial<AccountAnalyticsRow>[] | null;
		};

		if (curRows) {
			const seen = new Set<string>();
			for (const row of curRows) {
				const aid = row.account_id || "";
				if (!seen.has(aid) && accountsWithBaseline.has(aid)) {
					seen.add(aid);
					matchedCurViews += row.total_views || 0;
					matchedCurLikes += row.total_likes || 0;
					matchedCurReplies += row.total_replies || 0;
					matchedCurReposts += row.total_reposts || 0;
					matchedCurQuotes += row.total_quotes || 0;
					matchedCurShares += row.total_shares || 0;
					matchedCurClicks += row.total_clicks || 0;
					matchedCurSaves += row.total_saves || 0;
				}
			}
		}
	}

	const periodLikes = canComputePeriod
		? Math.max(Math.max(0, matchedCurLikes - prevLikes), postFloor.likes)
		: isAllTime
			? currentStats.totalLikes || 0
			: postFloor.likes;
	const periodReplies = canComputePeriod
		? Math.max(Math.max(0, matchedCurReplies - prevReplies), postFloor.replies)
		: isAllTime
			? currentStats.totalReplies || 0
			: postFloor.replies;
	const snapshotDeltaViews = Math.max(0, matchedCurViews - prevViews);
	const periodViews = canComputePeriod
		? Math.max(snapshotDeltaViews, postFloor.views)
		: isAllTime
			? currentStats.totalViews || 0
			: postFloor.views;

	const periodReposts = canComputePeriod
		? Math.max(Math.max(0, matchedCurReposts - prevReposts), postFloor.reposts)
		: isAllTime
			? currentStats.totalReposts || 0
			: postFloor.reposts;
	const periodQuotes = canComputePeriod
		? Math.max(Math.max(0, matchedCurQuotes - prevQuotes), postFloor.quotes)
		: isAllTime
			? currentStats.totalQuotes || 0
			: postFloor.quotes;
	const periodShares = canComputePeriod
		? Math.max(Math.max(0, matchedCurShares - prevShares), postFloor.shares)
		: isAllTime
			? currentStats.totalShares || 0
			: postFloor.shares;
	const periodClicks = canComputePeriod
		? Math.max(Math.max(0, matchedCurClicks - prevClicks), postFloor.clicks)
		: isAllTime
			? currentStats.totalClicks || 0
			: postFloor.clicks;
	const periodSaves = canComputePeriod
		? Math.max(Math.max(0, matchedCurSaves - prevSaves), postFloor.saves)
		: isAllTime
			? currentStats.totalIgSaved || 0
			: postFloor.saves;
	const periodIgShares = canComputePeriod
		? Math.max(Math.max(0, matchedCurShares - prevShares), postFloor.shares)
		: isAllTime
			? currentStats.totalIgShares || 0
			: postFloor.shares;

	const current = {
		totalFollowers: currentStats.totalFollowers || 0,
		totalLikes: periodLikes,
		totalReplies: periodReplies,
		totalReposts: periodReposts,
		totalQuotes: periodQuotes,
		totalShares: periodShares,
		totalClicks: periodClicks,
		totalViews: periodViews,
		scheduledCount: currentStats.scheduledCount || 0,
		totalIgImpressions: currentStats.totalIgImpressions || 0,
		totalIgReach: currentStats.totalIgReach || 0,
		totalIgSaved: periodSaves,
		totalIgShares: periodIgShares,
		igNewFollows: currentStats.igNewFollows || 0,
		igUnfollows: currentStats.igUnfollows || 0,
		periodPostCount: postFloor.count,
	};

	const previous = {
		totalFollowers: prevFollowers,
		totalLikes: prevLikes,
		totalReplies: prevReplies,
		totalReposts: prevReposts,
		totalViews: prevViews,
		totalIgReach: prevReach,
		totalIgSaved: prevSaves,
		totalIgShares: prevShares,
	};

	// Period-over-period delta computation
	// Compare this period's gain vs previous period's gain.
	const currentPeriodLikes = periodLikes;
	const currentPeriodReplies = periodReplies;
	const currentPeriodReposts = periodReposts;
	const currentPeriodViews = periodViews;
	const currentPeriodClicks = periodClicks;
	const currentPeriodSaves = periodSaves;
	const currentPeriodShares = periodIgShares;
	const currentPeriodReach = currentStats.totalIgReach || 0;
	const currentPeriodFollowerGrowth =
		(currentStats.totalFollowers || 0) - prevFollowers;

	// Previous period: gain = prev_latest - pre_prev_latest
	const prevPeriodLikes = hasPrePreviousData
		? Math.max(0, prevLikes - prePrevLikes)
		: prevLikes;
	const prevPeriodReplies = hasPrePreviousData
		? Math.max(0, prevReplies - prePrevReplies)
		: prevReplies;
	const prevPeriodReposts = hasPrePreviousData
		? Math.max(0, prevReposts - prePrevReposts)
		: prevReposts;
	const prevPeriodViews = hasPrePreviousData
		? Math.max(0, prevViews - prePrevViews)
		: prevViews;
	const prevPeriodClicks = hasPrePreviousData
		? Math.max(0, prevClicks - prePrevClicks)
		: prevClicks;
	const prevPeriodSaves = hasPrePreviousData
		? Math.max(0, prevSaves - prePrevSaves)
		: prevSaves;
	const prevPeriodShares = hasPrePreviousData
		? Math.max(0, prevShares - prePrevShares)
		: prevShares;
	const prevPeriodReach = prevReach;
	const prevPeriodFollowerGrowth = prevFollowers - prePrevFollowers;

	const currentEngagement =
		currentPeriodViews > 0
			? ((currentPeriodLikes +
					currentPeriodReplies +
					currentPeriodReposts +
					currentPeriodShares) /
					currentPeriodViews) *
				100
			: 0;
	const previousEngagement =
		prevPeriodViews > 0
			? ((prevPeriodLikes +
					prevPeriodReplies +
					prevPeriodReposts +
					prevPeriodShares) /
					prevPeriodViews) *
				100
			: 0;

	const deltas = isAllTime
		? {
				followers: "—",
				likes: "—",
				replies: "—",
				reposts: "—",
				views: "—",
				clicks: "—",
				reach: "—",
				saves: "—",
				shares: "—",
				engagement: "—",
			}
		: !hasPreviousData
			? {
					followers: "—",
					likes: "—",
					replies: "—",
					reposts: "—",
					views: "—",
					clicks: "—",
					reach: "—",
					saves: "—",
					shares: "—",
					engagement: "—",
				}
			: !hasPrePreviousData
				? {
						// Only one period of data — show growth from zero
						followers: computeDelta(currentPeriodFollowerGrowth, 0),
						likes: currentPeriodLikes > 0 ? "New" : "0%",
						replies: currentPeriodReplies > 0 ? "New" : "0%",
						reposts: currentPeriodReposts > 0 ? "New" : "0%",
						views: currentPeriodViews > 0 ? "New" : "0%",
						clicks: currentPeriodClicks > 0 ? "New" : "0%",
						reach: currentPeriodReach > 0 ? "New" : "0%",
						saves: currentPeriodSaves > 0 ? "New" : "0%",
						shares: currentPeriodShares > 0 ? "New" : "0%",
						engagement: currentEngagement > 0 ? "New" : "0%",
					}
				: {
						// Period-over-period: compare this period vs last period
						followers: computeDelta(
							currentPeriodFollowerGrowth,
							prevPeriodFollowerGrowth,
						),
						likes: computeDelta(currentPeriodLikes, prevPeriodLikes),
						replies: computeDelta(currentPeriodReplies, prevPeriodReplies),
						reposts: computeDelta(currentPeriodReposts, prevPeriodReposts),
						views: computeDelta(currentPeriodViews, prevPeriodViews),
						clicks: computeDelta(currentPeriodClicks, prevPeriodClicks),
						reach: computeDelta(currentPeriodReach, prevPeriodReach),
						saves: computeDelta(currentPeriodSaves, prevPeriodSaves),
						shares: computeDelta(currentPeriodShares, prevPeriodShares),
						engagement: computeDelta(currentEngagement, previousEngagement),
					};

	return { current, previous, deltas };
}

export async function syncAnalytics(
	accountId: string,
): Promise<SyncResultSingle> {
	const {
		data: { session },
	} = await supabase.auth.getSession();

	return withRetry(
		async () => {
			const controller = new AbortController();
			const timeoutId = setTimeout(() => controller.abort(), 60000);

			try {
				const response = await fetch("/api/analytics?action=refresh", {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						Authorization: `Bearer ${session?.access_token}`,
					},
					body: JSON.stringify({ accountId }),
					signal: controller.signal,
				});

				clearTimeout(timeoutId);

				const contentType = response.headers.get("content-type");
				const isJson = contentType?.includes("application/json");

				if (!response.ok) {
					if (response.status === 429) {
						throw new Error(
							"Threads rate limit reached. Please wait a moment and try again.",
						);
					}
					if (response.status === 404) {
						throw new Error(
							"Analytics API not available (API routes require deployment)",
						);
					}
					if (response.status === 502 || response.status === 503) {
						throw new Error(`Server error (${response.status})`);
					}
					if (isJson) {
						const error = await response.json();
						throw new Error(
							error.error || error.hint || "Failed to sync analytics",
						);
					}
					throw new Error(`Failed to sync analytics (${response.status})`);
				}

				if (!isJson) {
					throw new Error("Invalid response from analytics API");
				}

				return response.json();
			} catch (error: unknown) {
				clearTimeout(timeoutId);
				if (error instanceof Error && error.name === "AbortError") {
					throw new Error("Sync timed out - please try again");
				}
				throw error;
			}
		},
		{
			retries: 3,
			baseDelay: 2000,
			name: `syncAnalytics(${accountId.slice(0, 8)})`,
		},
	);
}

export async function syncInstagramAnalytics(
	igAccountId: string,
): Promise<SyncResultSingle> {
	const {
		data: { session },
	} = await supabase.auth.getSession();

	return withRetry(
		async () => {
			const controller = new AbortController();
			const timeoutId = setTimeout(() => controller.abort(), 60000);

			try {
				const response = await fetch("/api/analytics?action=ig-refresh", {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						Authorization: `Bearer ${session?.access_token}`,
					},
					body: JSON.stringify({ igAccountId }),
					signal: controller.signal,
				});

				clearTimeout(timeoutId);

				const contentType = response.headers.get("content-type");
				const isJson = contentType?.includes("application/json");

				if (!response.ok) {
					if (response.status === 429) {
						throw new Error(
							"Threads rate limit reached. Please wait a moment and try again.",
						);
					}
					if (response.status === 404) {
						throw new Error(
							"Analytics API not available (API routes require deployment)",
						);
					}
					if (response.status === 502 || response.status === 503) {
						throw new Error(`Server error (${response.status})`);
					}
					if (isJson) {
						const error = await response.json();
						throw new Error(
							error.error || error.hint || "Failed to sync IG analytics",
						);
					}
					throw new Error(`Failed to sync IG analytics (${response.status})`);
				}

				if (!isJson) {
					throw new Error("Invalid response from analytics API");
				}

				return response.json();
			} catch (error: unknown) {
				clearTimeout(timeoutId);
				if (error instanceof Error && error.name === "AbortError") {
					throw new Error("Sync timed out - please try again");
				}
				throw error;
			}
		},
		{
			retries: 3,
			baseDelay: 2000,
			name: `syncInstagramAnalytics(${igAccountId.slice(0, 8)})`,
		},
	);
}

// Watch job progress via Supabase Realtime (with polling fallback)
async function watchJobProgress(
	jobId: string,
	accessToken: string | undefined,
	onProgress?: (progress: SyncJobProgress) => void,
): Promise<SyncResult> {
	const TIMEOUT = 600000;
	const POLL_INTERVAL = 5000;

	return new Promise((resolve) => {
		let channel: RealtimeChannel | null = null;
		let resolved = false;
		let pollInterval: ReturnType<typeof setInterval> | null = null;
		let timeoutId: ReturnType<typeof setTimeout> | null = null;

		const cleanup = () => {
			if (channel) {
				supabase.removeChannel(channel);
				channel = null;
			}
			if (pollInterval) {
				clearInterval(pollInterval);
				pollInterval = null;
			}
			if (timeoutId) {
				clearTimeout(timeoutId);
				timeoutId = null;
			}
		};

		const handleJobUpdate = (job: SyncJobStatus) => {
			if (resolved) return;

			const statusText =
				job.status === "processing"
					? `Syncing account ${job.current_progress}/${job.account_count}...`
					: job.status === "queued"
						? "Waiting for worker..."
						: "Completing...";

			onProgress?.({
				current: job.current_progress || 0,
				total: job.account_count || 0,
				status: statusText,
			});

			if (job.status === "completed" || job.status === "failed") {
				resolved = true;
				cleanup();

				logger.log(
					`[Analytics Sync] Job ${job.status}: ${job.success_count || 0}/${job.account_count || 0} succeeded`,
				);

				resolve({
					results: [],
					suspendedAccounts: job.suspended_accounts || [],
					reactivatedAccounts: job.reactivated_accounts || [],
					summary: {
						total: job.account_count || 0,
						success: job.success_count || 0,
						failed: job.failed_count || 0,
						suspended: (job.suspended_accounts || []).length,
					},
				});
			}
		};

		try {
			channel = supabase
				.channel(`sync_job_${jobId}`)
				.on(
					"postgres_changes",
					{
						event: "UPDATE",
						schema: "public",
						table: "sync_jobs",
						filter: `id=eq.${jobId}`,
					},
					(payload) => {
						logger.log("[Analytics Sync] Realtime update received");
						handleJobUpdate(payload.new as SyncJobStatus);
					},
				)
				.subscribe((status) => {
					if (status === "SUBSCRIBED") {
						logger.log("[Analytics Sync] Realtime subscription active");
					} else if (status === "CHANNEL_ERROR") {
						logger.warn("[Analytics Sync] Realtime failed, using polling");
					}
				});
		} catch (_error) {
			logger.warn("[Analytics Sync] Realtime setup failed, using polling only");
		}

		const pollForStatus = async () => {
			if (resolved) return;

			try {
				const statusResponse = await fetch("/api/analytics?action=job-status", {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						Authorization: `Bearer ${accessToken}`,
					},
					body: JSON.stringify({ jobId }),
				});

				if (statusResponse.ok) {
					const { job } = await statusResponse.json();
					if (job) {
						handleJobUpdate({
							id: job.id,
							status: job.status,
							current_progress: job.progress?.current || 0,
							account_count: job.progress?.total || 0,
							success_count: job.results?.success || 0,
							failed_count: job.results?.failed || 0,
							suspended_accounts: job.results?.suspended || [],
							reactivated_accounts: job.results?.reactivated || [],
							created_at: job.created_at,
						});
					}
				}
			} catch (error) {
				logger.warn("[Analytics Sync] Poll failed:", error);
			}
		};

		pollInterval = setInterval(pollForStatus, POLL_INTERVAL);
		pollForStatus();

		timeoutId = setTimeout(() => {
			if (!resolved) {
				resolved = true;
				cleanup();
				logger.warn("[Analytics Sync] Timed out");
				resolve({
					results: [],
					suspendedAccounts: [],
					reactivatedAccounts: [],
					error: "Sync timed out - check back later",
				});
			}
		}, TIMEOUT);
	});
}

export async function syncAllAnalytics(
	onProgress?: (progress: SyncJobProgress) => void,
): Promise<SyncResult> {
	const {
		data: { session },
	} = await supabase.auth.getSession();

	logger.log("[Analytics Sync] Queuing sync job...");
	onProgress?.({ current: 0, total: 0, status: "Queuing sync job..." });

	const queueResponse = await fetch("/api/analytics?action=queue-sync", {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
		},
		body: JSON.stringify({}),
	});

	if (!queueResponse.ok) {
		const error = await queueResponse.json().catch(() => ({}));
		throw new Error(error.error || "Failed to queue sync");
	}

	const queueResult = await queueResponse.json();

	if (!queueResult.queued) {
		if (queueResult.existingJob) {
			logger.log("[Analytics Sync] Existing job in progress, polling...");
			return watchJobProgress(
				queueResult.job.id,
				session?.access_token,
				onProgress,
			);
		}
		return { results: [], suspendedAccounts: [], reactivatedAccounts: [] };
	}

	logger.log(
		`[Analytics Sync] Job queued: ${queueResult.job.id} (${queueResult.job.accountCount} accounts)`,
	);
	onProgress?.({
		current: 0,
		total: queueResult.job.accountCount,
		status: "Sync queued, waiting for worker...",
	});

	return watchJobProgress(
		queueResult.job.id,
		session?.access_token,
		onProgress,
	);
}

/**
 * Fire-and-forget: POST to queue-sync and return immediately.
 * The sync-orchestrator cron (runs every ~15min) picks up the job.
 * Dashboard data refreshes on next load or tab-visible event.
 */
export async function queueSync(): Promise<{
	queued: boolean;
	existingJob?: boolean | undefined;
	accountCount?: number | undefined;
	message?: string | undefined;
}> {
	const {
		data: { session },
	} = await supabase.auth.getSession();

	logger.log("[queueSync] Posting to queue-sync...");

	const response = await fetch("/api/analytics?action=queue-sync", {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
		},
		body: JSON.stringify({}),
	});

	const data = await response.json().catch(() => ({}));
	logger.log("[queueSync] Response:", { status: response.status, data });

	if (!response.ok) {
		throw new Error(data.error || `Queue sync failed (${response.status})`);
	}

	return {
		queued: !!data.queued,
		existingJob: !!data.existingJob,
		accountCount: data.job?.accountCount ?? 0,
		message: data.message,
	};
}

export async function backfillHistoricalAnalytics(
	accountId: string,
): Promise<{ success: boolean; skipped?: boolean | undefined; error?: string | undefined }> {
	const {
		data: { session },
	} = await supabase.auth.getSession();

	const response = await fetch("/api/analytics?action=backfill", {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
		},
		body: JSON.stringify({ accountId }),
	});

	const data = await safeJsonParse<{
		success: boolean;
		skipped?: boolean | undefined;
		error?: string | undefined;
	}>(response, "Backfill analytics");
	if (!response.ok) {
		throw new Error(data.error || "Failed to backfill analytics");
	}

	return data;
}

export async function rebackfillAnalytics(
	accountId: string,
): Promise<{ success: boolean; skipped?: boolean | undefined; error?: string | undefined }> {
	const {
		data: { session },
	} = await supabase.auth.getSession();

	const response = await fetch("/api/analytics?action=rebackfill", {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
		},
		body: JSON.stringify({ accountId }),
	});

	const data = await safeJsonParse<{
		success: boolean;
		skipped?: boolean | undefined;
		error?: string | undefined;
	}>(response, "Rebackfill analytics");
	if (!response.ok) {
		throw new Error(data.error || "Failed to rebackfill analytics");
	}

	return data;
}

export async function fixAccountBaselines(): Promise<{
	success: boolean;
	skipped?: boolean | undefined;
	error?: string | undefined;
}> {
	const {
		data: { session },
	} = await supabase.auth.getSession();

	const response = await fetch("/api/analytics?action=fix-baselines", {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
		},
		body: JSON.stringify({}),
	});

	const data = await safeJsonParse<{
		success: boolean;
		skipped?: boolean | undefined;
		error?: string | undefined;
	}>(response, "Fix account baselines");
	if (!response.ok) {
		throw new Error(data.error || "Failed to fix account baselines");
	}

	return data;
}

export async function fetchFollowerDemographics(accountId: string): Promise<{
	success: boolean;
	skipped?: boolean | undefined;
	error?: string | undefined;
	demographics?: Record<string, unknown> | undefined;
}> {
	const {
		data: { session },
	} = await supabase.auth.getSession();

	const response = await fetch("/api/analytics?action=demographics", {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session?.access_token}`,
		},
		body: JSON.stringify({ accountId }),
	});

	const data = await safeJsonParse<{
		success: boolean;
		skipped?: boolean | undefined;
		error?: string | undefined;
		demographics?: Record<string, unknown> | undefined;
	}>(response, "Fetch demographics");
	if (!response.ok) {
		throw new Error(data.error || "Failed to fetch demographics");
	}

	return data;
}

export interface DailyActivityBucket {
	date: string;
	views: number;
	likes: number;
	replies: number;
	posts: number;
}

export async function getDailyActivity(
	accountId: string = "ALL",
	periodDays: number = 30,
	accountIds?: string[],
): Promise<DailyActivityBucket[]> {
	const params = new URLSearchParams({
		action: "daily-activity",
		periodDays: String(periodDays),
	});
	if (accountId && accountId !== "ALL") {
		params.set("accountId", accountId);
	}
	if (accountIds?.length) {
		params.set("accountIds", accountIds.join(","));
	}

	const response = await fetch(`/api/analytics?${params}`, {
		headers: {
			Authorization: `Bearer ${(await supabase.auth.getSession()).data.session?.access_token}`,
		},
	});
	const data = await safeJsonParse<{
		days?: DailyActivityBucket[] | undefined;
		error?: string | undefined;
	}>(response, "Fetch daily activity");
	if (!response.ok) {
		throw new Error(data.error || "Failed to fetch daily activity");
	}
	return data.days || [];
}

// ============================================================================
// Measurement-only endpoints (no predictions)
// ============================================================================

export interface FollowerAttributionDay {
	date: string;
	followerGrowth: number;
	posts: Array<{
		id: string;
		content: string | null;
		likes: number;
		replies: number;
		views: number;
		permalink: string | null;
	}>;
}

export async function getFollowerAttribution(
	accountId: string = "ALL",
	periodDays: number = 30,
	platform: Platform = "threads",
): Promise<FollowerAttributionDay[]> {
	const params = new URLSearchParams({
		action: "follower-attribution",
		periodDays: String(periodDays),
		platform,
	});
	if (accountId !== "ALL") params.set("accountId", accountId);
	const response = await fetch(`/api/analytics?${params}`, {
		headers: {
			Authorization: `Bearer ${(await supabase.auth.getSession()).data.session?.access_token}`,
		},
	});
	const data = await safeJsonParse<{
		days?: FollowerAttributionDay[] | undefined;
		error?: string | undefined;
	}>(response, "Fetch follower attribution");
	if (!response.ok)
		throw new Error(data.error || "Failed to fetch follower attribution");
	return data.days || [];
}

export interface ContentTypeTrend {
	current: Record<string, Record<string, number>>;
	previous: Record<string, Record<string, number>>;
	deltas: Record<
		string,
		Record<
			string,
			{
				current: number;
				previous: number;
				delta: number;
				pctChange: number | null;
			}
		>
	>;
}

export async function getContentTypeTrend(
	accountId: string = "ALL",
): Promise<ContentTypeTrend> {
	const params = new URLSearchParams({ action: "content-type-trend" });
	if (accountId !== "ALL") params.set("accountId", accountId);
	const response = await fetch(`/api/analytics?${params}`, {
		headers: {
			Authorization: `Bearer ${(await supabase.auth.getSession()).data.session?.access_token}`,
		},
	});
	const data = await safeJsonParse<ContentTypeTrend & { error?: string | undefined }>(
		response,
		"Fetch content type trend",
	);
	if (!response.ok)
		throw new Error(data.error || "Failed to fetch content type trend");
	return { current: data.current, previous: data.previous, deltas: data.deltas };
}

export interface CompetitorBenchmark {
	userFollowers: number;
	userRate: number;
	peerCount: number;
	peerBand?: { low: number; high: number } | undefined;
	percentile: number | null;
	peerP50: number;
	peerP75: number;
	peerP90: number;
}

export async function getCompetitorBenchmark(
	accountId: string,
	platform: Platform = "threads",
	bandWidth = 0.5,
): Promise<CompetitorBenchmark> {
	const params = new URLSearchParams({
		action: "competitor-benchmark",
		accountId,
		platform,
		bandWidth: String(bandWidth),
	});
	const response = await fetch(`/api/analytics?${params}`, {
		headers: {
			Authorization: `Bearer ${(await supabase.auth.getSession()).data.session?.access_token}`,
		},
	});
	const data = await safeJsonParse<CompetitorBenchmark & { error?: string | undefined }>(
		response,
		"Fetch competitor benchmark",
	);
	if (!response.ok)
		throw new Error(data.error || "Failed to fetch competitor benchmark");
	return data;
}

// ---------------------------------------------------------------------------
// Overnight brief (cron-generated morning narrative)
// ---------------------------------------------------------------------------

export interface OvernightBriefMove {
	label: string;
	reason: string;
	route: string;
	severity: "good" | "warn" | "critical";
}

export interface OvernightBriefAnomaly {
	account: string;
	metric: string;
	direction: "up" | "down";
	severity: "low" | "medium" | "high" | "critical";
}

export interface OvernightBrief {
	id: string;
	narrative: string;
	moves: OvernightBriefMove[];
	anomalies: OvernightBriefAnomaly[];
	generatedAt: string;
	windowStart: string;
	windowEnd: string;
	aiModel: string | null;
}

export interface OvernightBriefResponse {
	brief: OvernightBrief | null;
	fallback: "live" | null;
}

export async function getOvernightBrief(): Promise<OvernightBriefResponse> {
	const response = await fetch("/api/analytics?action=overnight-brief", {
		headers: {
			Authorization: `Bearer ${(await supabase.auth.getSession()).data.session?.access_token}`,
		},
	});
	const data = await safeJsonParse<OvernightBriefResponse & { error?: string | undefined }>(
		response,
		"Fetch overnight brief",
	);
	if (!response.ok)
		throw new Error(data.error || "Failed to fetch overnight brief");
	return { brief: data.brief, fallback: data.fallback };
}

export interface HashtagPerformance {
	hashtag: string;
	postCount: number;
	platforms: string[];
	totalViews: number;
	totalReach: number;
	totalLikes: number;
	totalReplies: number;
	totalSaves: number;
	totalShares: number;
	avgEngagementRate: number;
}

export async function getHashtagPerformance(
	accountId: string = "ALL",
	periodDays: number = 30,
	platform: "threads" | "instagram" | "all" = "all",
	limit = 50,
): Promise<HashtagPerformance[]> {
	const params = new URLSearchParams({
		action: "hashtag-performance",
		periodDays: String(periodDays),
		platform,
		limit: String(limit),
	});
	if (accountId !== "ALL") params.set("accountId", accountId);
	const response = await fetch(`/api/analytics?${params}`, {
		headers: {
			Authorization: `Bearer ${(await supabase.auth.getSession()).data.session?.access_token}`,
		},
	});
	const data = await safeJsonParse<{
		hashtags?: HashtagPerformance[] | undefined;
		error?: string | undefined;
	}>(response, "Fetch hashtag performance");
	if (!response.ok)
		throw new Error(data.error || "Failed to fetch hashtag performance");
	return data.hashtags || [];
}

export async function backfillAllHistoricalAnalytics(): Promise<
	{
		accountId: string;
		success: boolean;
		data?: Record<string, unknown> | undefined;
		error?: string | undefined;
	}[]
> {
	const accounts = await getAccounts();
	const results = [];

	for (const account of accounts) {
		try {
			const result = await rebackfillAnalytics(account.id);
			results.push({
				accountId: account.id,
				success: true,
				data: result,
			});
		} catch (error: unknown) {
			results.push({
				accountId: account.id,
				success: false,
				error: error instanceof Error ? error.message : String(error),
			});
		}
	}

	return results;
}
