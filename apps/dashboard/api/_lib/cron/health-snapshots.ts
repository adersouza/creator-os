// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Health Snapshots — pre-computes per-account health metrics.
 *
 * Called as a phase from six-hour-pipeline.
 * For each user's accounts: computes growth %, reach anomalies,
 * days since last post, and engagement rate.
 * Results upserted into account_health_snapshots table.
 */

import type { SupabaseClient } from "@supabase/supabase-js";

type Logger = {
	info: (msg: string, ctx?: Record<string, unknown>) => void;
	warn: (msg: string, ctx?: Record<string, unknown>) => void;
	error: (msg: string, ctx?: Record<string, unknown>) => void;
};

const PERIOD_DAYS = 7;
const REACH_DROP_THRESHOLD = -40; // flag if reach dropped >40%
const STALE_DAYS_THRESHOLD = 3;

interface SnapshotRow {
	account_table: "accounts" | "instagram_accounts";
	user_id: string;
	workspace_id: string;
	account_id: string;
	account_name: string;
	platform: string;
	followers_current: number;
	followers_previous: number;
	growth_pct: number;
	reach_3day: number;
	reach_14day: number;
	reach_drop_pct: number;
	engagement_rate: number;
	group_avg_er: number;
	days_since_last_post: number;
	posts_this_period: number;
	has_anomaly: boolean;
	anomaly_severity: string | null;
	anomaly_detail: string | null;
	period_days: number;
	computed_at: string;
}

interface SnapshotAccount {
	id: string;
	userId: string;
	name: string;
	workspaceId: string;
	followers: number;
	platform: "threads" | "instagram";
	accountTable: "accounts" | "instagram_accounts";
}

interface AnalyticsRowBase {
	account_id: string;
	account_table: SnapshotAccount["accountTable"];
}

interface CurrentAnalyticsRow extends AnalyticsRowBase {
	followers_count: number | null;
	views_count: number | null;
	likes_count: number | null;
	replies_count: number | null;
	reposts_count: number | null;
	ig_reach: number | null;
}

interface PreviousAnalyticsRow extends AnalyticsRowBase {
	followers_count: number | null;
}

interface ReachAnalyticsRow extends AnalyticsRowBase {
	views_count: number | null;
	ig_reach: number | null;
}

function getSnapshotAccountKey(
	accountTable: SnapshotAccount["accountTable"],
	accountId: string,
): string {
	return `${accountTable}:${accountId}`;
}

export async function computeHealthSnapshots(
	supabase: SupabaseClient,
	logger: Logger,
): Promise<{ accountsProcessed: number; anomaliesFound: number }> {
	const now = new Date();
	const computedAt = now.toISOString();
	const threeDaysAgo = new Date(now.getTime() - 3 * 86400000)
		.toISOString()
		.split("T")[0]!;
	const sevenDaysAgo = new Date(now.getTime() - 7 * 86400000)
		.toISOString()
		.split("T")[0]!;
	const fourteenDaysAgo = new Date(now.getTime() - 14 * 86400000)
		.toISOString()
		.split("T")[0]!;
	const today = now.toISOString().split("T")[0]!;

	// 1. Get all active accounts (Threads + Instagram) grouped by user
	const { data: threadsAccounts, error: tErr } = await supabase
		.from("accounts")
		.select("id, user_id, username, followers_count, is_active")
		.eq("is_active", true);

	if (tErr) {
		logger.error("[health-snapshots] Failed to fetch Threads accounts", {
			error: tErr.message,
		});
		return { accountsProcessed: 0, anomaliesFound: 0 };
	}

	const { data: igAccounts, error: iErr } = await supabase
		.from("instagram_accounts")
		.select("id, user_id, username, follower_count, is_active")
		.eq("is_active", true);

	if (iErr) {
		logger.error("[health-snapshots] Failed to fetch IG accounts", {
			error: iErr.message,
		});
		return { accountsProcessed: 0, anomaliesFound: 0 };
	}

	// Resolve workspace_id from user_id via workspaces.owner_id
	// (accounts/instagram_accounts don't have workspace_id — it lives on workspaces)
	const allUserIds = [
		...new Set([
			...(threadsAccounts || []).map((a) => a.user_id),
			...(igAccounts || []).map((a) => a.user_id),
		]),
	];
	const userToWorkspace = new Map<string, string>();
	if (allUserIds.length > 0) {
		const { data: workspaces } = await supabase
			.from("workspaces")
			.select("id, owner_id")
			.in("owner_id", allUserIds);
		for (const ws of workspaces || []) {
			userToWorkspace.set(ws.owner_id, ws.id);
		}
	}

	const allAccounts = [
		...(threadsAccounts || []).map((a) => ({
			id: a.id,
			userId: a.user_id,
			name: `@${a.username || a.id}`,
			workspaceId: userToWorkspace.get(a.user_id) || "",
			followers: a.followers_count || 0,
			platform: "threads" as const,
			accountTable: "accounts" as const,
		})),
		...(igAccounts || []).map((a) => ({
			id: a.id,
			userId: a.user_id,
			name: `@${a.username || a.id}`,
			workspaceId: userToWorkspace.get(a.user_id) || "",
			followers: a.follower_count || 0,
			platform: "instagram" as const,
			accountTable: "instagram_accounts" as const,
		})),
	] satisfies SnapshotAccount[];

	if (allAccounts.length === 0) {
		logger.info("[health-snapshots] No active accounts to process");
		return { accountsProcessed: 0, anomaliesFound: 0 };
	}

	// 2. Batch-fetch analytics data for all accounts
	const threadAccounts = allAccounts.filter(
		(account) => account.accountTable === "accounts",
	);
	const instagramAccounts = allAccounts.filter(
		(account) => account.accountTable === "instagram_accounts",
	);
	const threadAccountIds = threadAccounts.map((account) => account.id);
	const instagramAccountIds = instagramAccounts.map((account) => account.id);

	const fetchAnalyticsRows = async (
		accountTable: SnapshotAccount["accountTable"],
		select: string,
		fromDate?: string,
		toDate?: string,
	): Promise<CurrentAnalyticsRow[] | ReachAnalyticsRow[]> => {
		const ids =
			accountTable === "accounts" ? threadAccountIds : instagramAccountIds;
		if (ids.length === 0) return [];

		let query = supabase
			.from("account_analytics")
			.select(select)
			.in("account_id", ids);
		if (fromDate) query = query.gte("date", fromDate);
		if (toDate) query = query.lte("date", toDate);
		const { data } = await query.order("date", { ascending: false });
		return (data || []).map((row) => ({
			...(row as unknown as Record<string, unknown>),
			account_table: accountTable,
		})) as CurrentAnalyticsRow[] | ReachAnalyticsRow[];
	};

	const [threadCurrentAnalytics, instagramCurrentAnalytics] = await Promise.all(
		[
			fetchAnalyticsRows(
				"accounts",
				"account_id, date, followers_count, views_count, likes_count, replies_count, reposts_count, ig_reach",
				sevenDaysAgo,
				today,
			),
			fetchAnalyticsRows(
				"instagram_accounts",
				"account_id, date, followers_count, views_count, likes_count, replies_count, reposts_count, ig_reach",
				sevenDaysAgo,
				today,
			),
		],
	);
	const currentAnalytics: CurrentAnalyticsRow[] = [
		...threadCurrentAnalytics,
		...instagramCurrentAnalytics,
	] as CurrentAnalyticsRow[];

	const [threadPreviousAnalytics, instagramPreviousAnalytics] =
		await Promise.all([
			supabase
				.from("account_analytics")
				.select("account_id, date, followers_count")
				.in(
					"account_id",
					threadAccountIds.length > 0 ? threadAccountIds : ["__none__"],
				)
				.gte("date", fourteenDaysAgo)
				.lt("date", sevenDaysAgo)
				.order("date", { ascending: false }),
			supabase
				.from("account_analytics")
				.select("account_id, date, followers_count")
				.in(
					"account_id",
					instagramAccountIds.length > 0 ? instagramAccountIds : ["__none__"],
				)
				.gte("date", fourteenDaysAgo)
				.lt("date", sevenDaysAgo)
				.order("date", { ascending: false }),
		]);
	const previousAnalytics: PreviousAnalyticsRow[] = [
		...(threadPreviousAnalytics.data || []).map((row) => ({
			...row,
			account_table: "accounts" as const,
		})),
		...(instagramPreviousAnalytics.data || []).map((row) => ({
			...row,
			account_table: "instagram_accounts" as const,
		})),
	];

	const [threadReach3d, instagramReach3d, threadReach14d, instagramReach14d] =
		await Promise.all([
			fetchAnalyticsRows(
				"accounts",
				"account_id, views_count, ig_reach",
				threeDaysAgo,
				today,
			),
			fetchAnalyticsRows(
				"instagram_accounts",
				"account_id, views_count, ig_reach",
				threeDaysAgo,
				today,
			),
			fetchAnalyticsRows(
				"accounts",
				"account_id, views_count, ig_reach",
				fourteenDaysAgo,
				today,
			),
			fetchAnalyticsRows(
				"instagram_accounts",
				"account_id, views_count, ig_reach",
				fourteenDaysAgo,
				today,
			),
		]);

	const reachData3d: ReachAnalyticsRow[] = [
		...threadReach3d,
		...instagramReach3d,
	] as ReachAnalyticsRow[];
	const reachData14d: ReachAnalyticsRow[] = [
		...threadReach14d,
		...instagramReach14d,
	] as ReachAnalyticsRow[];

	// Current period analytics (last 7 days) was fetched via the scoped helper above.
	// Previous-period and reach queries are also scoped per account table so threads and
	// instagram rows never collide in-memory even if raw IDs overlap.

	// Last post dates
	const [threadLastPosts, instagramLastPosts] = await Promise.all([
		threadAccountIds.length > 0
			? supabase
					.from("posts")
					.select("account_id, published_at")
					.in("account_id", threadAccountIds)
					.eq("status", "published")
					.order("published_at", { ascending: false })
			: Promise.resolve({
					data: [] as Array<{
						account_id: string;
						published_at: string | null;
					}>,
				}),
		instagramAccountIds.length > 0
			? supabase
					.from("posts")
					.select("instagram_account_id, published_at")
					.in("instagram_account_id", instagramAccountIds)
					.eq("platform", "instagram")
					.eq("status", "published")
					.order("published_at", { ascending: false })
			: Promise.resolve({
					data: [] as Array<{
						instagram_account_id: string | null;
						published_at: string | null;
					}>,
				}),
	]);

	// 3. Build lookup maps
	const currentByAccount = new Map<
		string,
		{
			followers: number;
			views: number;
			likes: number;
			replies: number;
			reposts: number;
			reach: number;
		}
	>();
	for (const row of currentAnalytics || []) {
		const accountKey = getSnapshotAccountKey(row.account_table, row.account_id);
		const existing = currentByAccount.get(accountKey);
		if (!existing) {
			currentByAccount.set(accountKey, {
				followers: row.followers_count || 0,
				views: row.views_count || 0,
				likes: row.likes_count || 0,
				replies: row.replies_count || 0,
				reposts: row.reposts_count || 0,
				reach: row.ig_reach || 0,
			});
		}
	}

	const previousFollowersByAccount = new Map<string, number>();
	for (const row of previousAnalytics || []) {
		const accountKey = getSnapshotAccountKey(row.account_table, row.account_id);
		if (!previousFollowersByAccount.has(accountKey)) {
			previousFollowersByAccount.set(accountKey, row.followers_count || 0);
		}
	}

	// Aggregate 3-day and 14-day reach per account
	const reach3dByAccount = new Map<string, number>();
	for (const row of reachData3d || []) {
		const accountKey = getSnapshotAccountKey(row.account_table, row.account_id);
		const current = reach3dByAccount.get(accountKey) || 0;
		reach3dByAccount.set(
			accountKey,
			current + (row.views_count || 0) + (row.ig_reach || 0),
		);
	}

	const reach14dByAccount = new Map<string, number>();
	for (const row of reachData14d || []) {
		const accountKey = getSnapshotAccountKey(row.account_table, row.account_id);
		const current = reach14dByAccount.get(accountKey) || 0;
		reach14dByAccount.set(
			accountKey,
			current + (row.views_count || 0) + (row.ig_reach || 0),
		);
	}

	// Last post date per account (most recent only)
	const lastPostByAccount = new Map<string, Date>();
	for (const row of threadLastPosts.data || []) {
		if (!lastPostByAccount.has(row.account_id) && row.published_at) {
			lastPostByAccount.set(
				getSnapshotAccountKey("accounts", row.account_id),
				new Date(row.published_at),
			);
		}
	}
	for (const row of instagramLastPosts.data || []) {
		if (!row.instagram_account_id) continue;
		const accountKey = getSnapshotAccountKey(
			"instagram_accounts",
			row.instagram_account_id,
		);
		if (!lastPostByAccount.has(accountKey) && row.published_at) {
			lastPostByAccount.set(accountKey, new Date(row.published_at));
		}
	}

	// Posts count in period per account
	const postsInPeriod = new Map<string, number>();
	for (const row of threadLastPosts.data || []) {
		if (
			row.published_at &&
			new Date(row.published_at) >= new Date(sevenDaysAgo!)
		) {
			postsInPeriod.set(
				getSnapshotAccountKey("accounts", row.account_id),
				(postsInPeriod.get(getSnapshotAccountKey("accounts", row.account_id)) ||
					0) + 1,
			);
		}
	}
	for (const row of instagramLastPosts.data || []) {
		if (
			row.instagram_account_id &&
			row.published_at &&
			new Date(row.published_at) >= new Date(sevenDaysAgo!)
		) {
			const accountKey = getSnapshotAccountKey(
				"instagram_accounts",
				row.instagram_account_id,
			);
			postsInPeriod.set(accountKey, (postsInPeriod.get(accountKey) || 0) + 1);
		}
	}

	// 4. Compute per-user average ER for anomaly comparison
	const userERs = new Map<string, number[]>();
	for (const account of allAccounts) {
		const stats = currentByAccount.get(
			getSnapshotAccountKey(account.accountTable, account.id),
		);
		if (!stats) continue;
		const base = account.platform === "threads" ? stats.views : stats.reach;
		const engagements =
			account.platform === "threads"
				? stats.likes + stats.replies + stats.reposts
				: stats.likes + stats.replies;
		const er = base > 0 ? (engagements / base) * 100 : 0;
		const list = userERs.get(account.userId) || [];
		list.push(er);
		userERs.set(account.userId, list);
	}

	const userAvgER = new Map<string, number>();
	for (const [userId, ers] of userERs) {
		const avg = ers.reduce((s, v) => s + v, 0) / ers.length;
		userAvgER.set(userId, avg);
	}

	// 5. Build snapshot rows
	const rows: SnapshotRow[] = [];
	let anomaliesFound = 0;

	for (const account of allAccounts) {
		const accountKey = getSnapshotAccountKey(account.accountTable, account.id);
		const stats = currentByAccount.get(accountKey);
		const prevFollowers =
			previousFollowersByAccount.get(accountKey) || account.followers;
		const currentFollowers = stats?.followers || account.followers;

		// Growth %
		const growthPct =
			prevFollowers > 0
				? ((currentFollowers - prevFollowers) / prevFollowers) * 100
				: 0;

		// Reach anomaly
		const r3d = reach3dByAccount.get(accountKey) || 0;
		const r14d = reach14dByAccount.get(accountKey) || 0;
		// Normalize to daily average for fair comparison
		const avgReach3d = r3d / 3;
		const avgReach14d = r14d / 14;
		const reachDropPct =
			avgReach14d > 0 ? ((avgReach3d - avgReach14d) / avgReach14d) * 100 : 0;

		// Engagement rate
		const base =
			account.platform === "threads" ? stats?.views || 0 : stats?.reach || 0;
		const engagements =
			account.platform === "threads"
				? (stats?.likes || 0) + (stats?.replies || 0) + (stats?.reposts || 0)
				: (stats?.likes || 0) + (stats?.replies || 0);
		const er = base > 0 ? (engagements / base) * 100 : 0;
		const groupAvgER = userAvgER.get(account.userId) || 0;

		// Days since last post
		const lastPost = lastPostByAccount.get(accountKey);
		const daysSinceLastPost = lastPost
			? Math.floor((now.getTime() - lastPost.getTime()) / 86400000)
			: 999;

		const postsCount = postsInPeriod.get(accountKey) || 0;

		// Determine anomaly
		let hasAnomaly = false;
		let severity: string | null = null;
		let detail: string | null = null;

		if (reachDropPct <= REACH_DROP_THRESHOLD && avgReach14d > 0) {
			hasAnomaly = true;
			severity = "high";
			detail = `Reach dropped ${Math.abs(Math.round(reachDropPct))}% in 3 days vs 14-day baseline`;
		} else if (er > 0 && groupAvgER > 0 && er < groupAvgER * 0.5) {
			hasAnomaly = true;
			severity = "medium";
			detail = `Engagement rate (${er.toFixed(1)}%) is below workspace average (${groupAvgER.toFixed(1)}%)`;
		} else if (
			daysSinceLastPost >= STALE_DAYS_THRESHOLD &&
			daysSinceLastPost < 999
		) {
			// Only flag as stale if the account HAS posted before (not never-posted accounts)
			hasAnomaly = true;
			severity = "low";
			detail = `No posts in ${daysSinceLastPost} days`;
		}

		if (hasAnomaly) anomaliesFound++;

		rows.push({
			account_table: account.accountTable,
			user_id: account.userId,
			workspace_id: account.workspaceId,
			account_id: account.id,
			account_name: account.name,
			platform: account.platform,
			followers_current: currentFollowers,
			followers_previous: prevFollowers,
			growth_pct: Number.parseFloat(growthPct.toFixed(2)),
			reach_3day: r3d,
			reach_14day: r14d,
			reach_drop_pct: Number.parseFloat(reachDropPct.toFixed(2)),
			engagement_rate: Number.parseFloat(er.toFixed(2)),
			group_avg_er: Number.parseFloat(groupAvgER.toFixed(2)),
			days_since_last_post: daysSinceLastPost === 999 ? -1 : daysSinceLastPost,
			posts_this_period: postsCount,
			has_anomaly: hasAnomaly,
			anomaly_severity: severity,
			anomaly_detail: detail,
			period_days: PERIOD_DAYS,
			computed_at: computedAt,
		});
	}

	// 6. Upsert in batches (Supabase has a 1000-row limit per upsert)
	const BATCH_SIZE = 500;
	let upserted = 0;

	for (let i = 0; i < rows.length; i += BATCH_SIZE) {
		const batch = rows.slice(i, i + BATCH_SIZE);
		const { error: upsertErr } = await supabase
			.from("account_health_snapshots")
			.upsert(batch as unknown as Record<string, unknown>[], {
				onConflict: "user_id,account_table,account_id,period_days",
			});

		if (upsertErr) {
			logger.error("[health-snapshots] Upsert batch failed", {
				error: upsertErr.message,
				batchStart: i,
				batchSize: batch.length,
			});
		} else {
			upserted += batch.length;
		}
	}

	logger.info("[health-snapshots] Complete", {
		accountsProcessed: upserted,
		anomaliesFound,
		totalAccounts: allAccounts.length,
	});

	return { accountsProcessed: upserted, anomaliesFound };
}
