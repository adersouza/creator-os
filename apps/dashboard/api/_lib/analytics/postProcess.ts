// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { logger } from "../logger.js";
import { analyzeBestPostTimes } from "../metricCalculators.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../privilegedDb.js";
import { getRedis } from "../redis.js";
import { isTimeBudgetExceeded } from "./constants.js";

interface UserGroupRow {
	user_id: string;
}

interface AccountRow {
	id: string;
	user_id: string;
}

interface AnalyticsRow {
	account_id: string;
	total_views: number;
	total_likes: number;
	total_replies: number;
	total_reposts: number;
	engagement_rate: number;
	followers_count: number;
	follower_growth: number;
}

interface YdAnalyticsRow {
	account_id: string;
	total_views: number;
	engagement_rate: number;
	followers_count: number;
}

interface PostRow {
	id: string;
	account_id: string;
	views_count: number | null;
	published_at?: string | undefined;
	engagement_rate?: number | null | undefined;
}

const db = () =>
	getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.analyticsPostprocess);

export async function runPhase2_AnalyticsPostprocess(
	startTime: number,
): Promise<number> {
	logger.info("Phase 2: Starting analytics postprocessing");
	let processed = 0;

	// 1. Refresh group-level analytics
	try {
		if (isTimeBudgetExceeded(startTime)) return processed;
		const { data: usersWithGroups } = await db()
			.from("account_groups")
			.select("user_id")
			.not("account_ids", "is", null);
		if (usersWithGroups && usersWithGroups.length > 0) {
			const uniqueUserIds = Array.from(
				new Set(usersWithGroups.map((r: UserGroupRow) => r.user_id)),
			);
			for (const userId of uniqueUserIds) {
				try {
					const { data: count } = await db().rpc("refresh_group_analytics", {
						p_user_id: userId,
					});
					processed += count || 0;
				} catch (_e) {
					logger.warn("[postProcess] group analytics refresh failed", {
						error: String(_e),
					});
				}
			}
		}
	} catch (_e) {
		logger.warn("[postProcess] group analytics phase failed", {
			error: String(_e),
		});
	}

	// 2. Account daily summaries
	try {
		if (isTimeBudgetExceeded(startTime)) return processed;
		const today = new Date().toISOString().split("T")[0]!;
		const yesterday = new Date(Date.now() - 86400000)
			.toISOString()
			.split("T")[0]!;

		const { data: threadsAccounts } = await db()
			.from("accounts")
			.select("id, user_id")
			.not("threads_access_token_encrypted", "is", null);
		if (threadsAccounts && threadsAccounts.length > 0) {
			const accountIds = threadsAccounts.map((a: AccountRow) => a.id);
			const userMap = new Map(
				threadsAccounts.map((a: AccountRow) => [a.id, a.user_id]),
			);

			const { data: todayAnalytics } = await db()
				.from("account_analytics")
				.select(
					"account_id, total_views, total_likes, total_replies, total_reposts, total_shares, engagement_rate, followers_count, follower_growth",
				)
				.in("account_id", accountIds)
				.eq("date", today);
			const analyticsMap = new Map(
				(todayAnalytics || []).map((r: AnalyticsRow) => [r.account_id, r]),
			);

			const { data: ydAnalytics } = await db()
				.from("account_analytics")
				.select("account_id, total_views, engagement_rate, followers_count")
				.in("account_id", accountIds)
				.eq("date", yesterday);
			const ydMap = new Map(
				(ydAnalytics || []).map((r: YdAnalyticsRow) => [r.account_id, r]),
			);

			const { data: todayPosts } = await db()
				.from("posts")
				.select("id, account_id, views_count")
				.in("account_id", accountIds)
				.eq("status", "published")
				.gte("published_at", `${today}T00:00:00Z`)
				.order("views_count", { ascending: false });

			const bestPostMap = new Map<string, PostRow>();
			const postCountMap = new Map<string, number>();
			const todayViewsSumMap = new Map<string, number>();
			(todayPosts || []).forEach((post: PostRow) => {
				postCountMap.set(
					post.account_id,
					(postCountMap.get(post.account_id) || 0) + 1,
				);
				todayViewsSumMap.set(
					post.account_id,
					(todayViewsSumMap.get(post.account_id) || 0) +
						(post.views_count || 0),
				);
				if (!bestPostMap.has(post.account_id))
					bestPostMap.set(post.account_id, post);
			});

			const summaryRows = accountIds
				.map((accountId) => {
					const analytics = analyticsMap.get(accountId);
					if (!analytics) return null;
					const yd = ydMap.get(accountId) as YdAnalyticsRow | undefined;
					// NOTE: vt/et/ft are cumulative-ratio percentages (today vs yesterday),
					// not true period-over-period deltas. They overstate change when the
					// denominator is small. These fields are only used in the summary table
					// and are NOT consumed by the frontend dashboard widgets.
					const vt =
						yd && yd.total_views > 0
							? ((analytics.total_views - yd.total_views) / yd.total_views) *
								100
							: 0;
					const et =
						yd && yd.engagement_rate > 0
							? ((analytics.engagement_rate - yd.engagement_rate) /
									yd.engagement_rate) *
								100
							: 0;
					const ft =
						yd && yd.followers_count > 0
							? ((analytics.followers_count - yd.followers_count) /
									yd.followers_count) *
								100
							: 0;
					const bestPost = bestPostMap.get(accountId);
					const pc = postCountMap.get(accountId) || 0;
					return {
						account_id: accountId,
						user_id: userMap.get(accountId),
						platform: "threads",
						date: today,
						followers_count: analytics.followers_count || 0,
						follower_growth: analytics.follower_growth || 0,
						total_views: analytics.total_views || 0,
						total_likes: analytics.total_likes || 0,
						total_replies: analytics.total_replies || 0,
						total_reposts: analytics.total_reposts || 0,
						engagement_rate: analytics.engagement_rate || 0,
						posts_published: pc,
						best_post_id: bestPost?.id || null,
						best_post_views: bestPost?.views_count || 0,
						avg_views_per_post:
							pc > 0
								? Math.round((todayViewsSumMap.get(accountId) || 0) / pc)
								: 0,
						views_trend_pct: Math.round(vt * 100) / 100,
						engagement_trend_pct: Math.round(et * 100) / 100,
						follower_trend_pct: Math.round(ft * 100) / 100,
						updated_at: new Date().toISOString(),
					};
				})
				.filter((row): row is NonNullable<typeof row> => row !== null);

			if (summaryRows.length > 0) {
				await db().from("account_daily_summary").upsert(summaryRows, {
					onConflict: "account_id,platform,date",
				});
				processed += summaryRows.length;
			}
		}
	} catch (_e) {
		logger.warn("[postProcess] daily summaries phase failed", {
			error: String(_e),
		});
	}

	// 3. Best posting times
	try {
		if (isTimeBudgetExceeded(startTime)) return processed;
		const redis = getRedis();
		const { data: tAccts } = await db()
			.from("accounts")
			.select("id")
			.not("threads_access_token_encrypted", "is", null);
		const { data: iAccts } = await db()
			.from("instagram_accounts")
			.select("id")
			.not("instagram_access_token_encrypted", "is", null);
		const allAccts = [...(tAccts || []), ...(iAccts || [])];
		const thirtyDaysAgo = new Date(Date.now() - 30 * 86400000).toISOString();
		const accountIds = allAccts.map((a) => a.id);

		// Per-account query with tight limit. Each account only needs ~100
		// recent posts for best-times analysis. Avoids both N+1 (sequential
		// but bounded) and unbounded bulk fetches that starve quiet accounts.
		for (const acctId of accountIds) {
			if (isTimeBudgetExceeded(startTime)) break;
			try {
				const { data: posts } = await db()
					.from("posts")
					.select("published_at, engagement_rate")
					.eq("account_id", acctId)
					.eq("status", "published")
					.gte("published_at", thirtyDaysAgo)
					.not("published_at", "is", null)
					.order("published_at", { ascending: false })
					.limit(100);

				if (posts && posts.length >= 5) {
					const bestTimes = analyzeBestPostTimes(
						posts as Array<{
							published_at: string;
							engagement_rate: number;
						}>,
					);
					await redis.set(
						`best-times:${acctId}`,
						JSON.stringify(bestTimes),
						{ ex: 86400 },
					);
					processed++;
				}
			} catch (_e) {
				logger.warn(
					"[postProcess] best times calculation failed for account",
					{ error: String(_e), accountId: acctId },
				);
			}
		}
	} catch (_e) {
		logger.warn("[postProcess] best posting times phase failed", {
			error: String(_e),
		});
	}

	// 4. Daily insights
	try {
		if (isTimeBudgetExceeded(startTime)) return processed;
		const { generateDailyInsight: genInsight } = await import(
			"../../_lib/dailyInsight.js"
		);
		const { getAllActiveAccounts } = await import(
			"../../_lib/unifiedAccount.js"
		);
		const accounts = await getAllActiveAccounts({ requireToken: true });

		for (const acct of accounts) {
			if (isTimeBudgetExceeded(startTime)) break;
			try {
				await genInsight(acct.id, acct.platform, acct.userId);
				processed++;
			} catch (_e) {
				logger.warn(
					"[postProcess] daily insight generation failed for account",
					{ error: String(_e) },
				);
			}
		}
	} catch (_e) {
		logger.warn("[postProcess] daily insights phase failed", {
			error: String(_e),
		});
	}

	return processed;
}
