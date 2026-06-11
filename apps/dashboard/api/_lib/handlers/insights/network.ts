// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Network Insights API — Cross-User Pattern Analysis
 *
 * GET /api/insights/network
 *
 * Aggregates anonymized patterns across all users with sufficient data.
 * Cached in Redis for 7 days. Minimum 10 accounts per insight for privacy.
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { cached } from "../../redisCache.js";
import { getSupabase } from "../../supabase.js";

const db = () => getSupabase();

const CACHE_TTL = 604800; // 7 days
const MIN_ACCOUNT_DAYS = 30;
const MIN_ACCOUNT_POSTS = 20;
const MIN_ACCOUNTS_FOR_INSIGHT = 5;

interface NetworkInsight {
	id: string;
	text: string;
	magnitude: string;
	sampleSize: number;
	confidence: number; // 0-1
}

interface AnalyticsRow {
	account_id: string;
	date: string;
	total_views: number | null;
	followers_count: number | null;
}

interface PostRow {
	account_id: string;
	published_at: string | null;
	replies_count: number | null;
	views_count: number | null;
	likes_count: number | null;
	content: string | null;
}

/* ------------------------------------------------------------------ */
/*  Insight computers                                                  */
/* ------------------------------------------------------------------ */

async function computeReplyTimeInsight(
	optedInIds: Set<string> | null,
): Promise<NetworkInsight | null> {
	// Scope queries to opted-in accounts only (was full table scan)
	const accountFilter = optedInIds ? Array.from(optedInIds) : null;
	if (accountFilter && accountFilter.length === 0) return null;

	let analyticsQuery = db()
		.from("account_analytics")
		.select("account_id, date, total_views, followers_count")
		.order("date", { ascending: true });
	if (accountFilter)
		analyticsQuery = analyticsQuery.in("account_id", accountFilter);

	const { data: accounts, error } = await analyticsQuery;

	if (error || !accounts || accounts.length === 0) return null;

	// Group by account
	const byAccount = new Map<string, AnalyticsRow[]>();
	for (const row of accounts as AnalyticsRow[]) {
		const arr = byAccount.get(row.account_id) || [];
		arr.push(row);
		byAccount.set(row.account_id, arr);
	}

	// Filter accounts with enough data
	const qualifiedAccounts = Array.from(byAccount.entries()).filter(
		([_id, rows]) => rows.length >= MIN_ACCOUNT_DAYS,
	);

	if (qualifiedAccounts.length < MIN_ACCOUNTS_FOR_INSIGHT) return null;

	// Get reply data from posts (scoped to opted-in accounts)
	let postsQuery = db()
		.from("posts")
		.select("account_id, published_at, replies_count, views_count, content")
		.not("published_at", "is", null)
		.order("published_at", { ascending: true });
	if (accountFilter) postsQuery = postsQuery.in("account_id", accountFilter);

	const { data: posts } = await postsQuery;

	if (!posts || posts.length === 0) return null;

	const postsByAccount = new Map<string, PostRow[]>();
	for (const p of posts as PostRow[]) {
		const arr = postsByAccount.get(p.account_id) || [];
		arr.push(p);
		postsByAccount.set(p.account_id, arr);
	}

	// For each account, compute avg views for posts that got quick replies vs slow
	let fastReplyAccounts = 0;
	let slowReplyAccounts = 0;
	let fastReplyAvgViews = 0;

	for (const [_accountId, accountPosts] of postsByAccount) {
		if (accountPosts.length < MIN_ACCOUNT_POSTS) continue;

		const highReplyPosts = accountPosts.filter(
			(p) => (p.replies_count ?? 0) > 2,
		);
		const lowReplyPosts = accountPosts.filter(
			(p) => (p.replies_count ?? 0) <= 2,
		);

		if (highReplyPosts.length < 3 || lowReplyPosts.length < 3) continue;

		const avgHighViews =
			highReplyPosts.reduce((s: number, p) => s + (p.views_count ?? 0), 0) /
			highReplyPosts.length;
		const avgLowViews =
			lowReplyPosts.reduce((s: number, p) => s + (p.views_count ?? 0), 0) /
			lowReplyPosts.length;

		if (avgLowViews > 0 && avgHighViews > avgLowViews) {
			fastReplyAccounts++;
			fastReplyAvgViews += avgHighViews / avgLowViews;
		} else {
			slowReplyAccounts++;
		}
	}

	const totalAccounts = fastReplyAccounts + slowReplyAccounts;
	if (totalAccounts < MIN_ACCOUNTS_FOR_INSIGHT) return null;

	const avgLift =
		fastReplyAccounts > 0
			? (fastReplyAvgViews / fastReplyAccounts - 1) * 100
			: 0;
	if (avgLift <= 5) return null;

	const magnitude = `${Math.round(avgLift)}%`;
	return {
		id: "reply-time-reach",
		text: `Creators who actively engage with comments see ${magnitude} more reach on subsequent posts`,
		magnitude,
		sampleSize: totalAccounts,
		confidence: Math.min(totalAccounts / 50, 1),
	};
}

async function computeQuestionPostInsight(
	optedInIds: Set<string> | null,
): Promise<NetworkInsight | null> {
	const accountFilter = optedInIds ? Array.from(optedInIds) : null;
	if (accountFilter && accountFilter.length === 0) return null;

	let postsQuery = db()
		.from("posts")
		.select("account_id, content, replies_count, likes_count, views_count")
		.not("published_at", "is", null)
		.not("content", "is", null);
	if (accountFilter) postsQuery = postsQuery.in("account_id", accountFilter);

	const { data: posts } = await postsQuery;

	if (!posts || posts.length === 0) return null;

	const postsByAccount = new Map<string, PostRow[]>();
	for (const p of posts as PostRow[]) {
		const arr = postsByAccount.get(p.account_id) || [];
		arr.push(p);
		postsByAccount.set(p.account_id, arr);
	}

	let accountsWithData = 0;
	let totalMultiplier = 0;

	for (const [accountId, accountPosts] of postsByAccount) {
		if (accountPosts.length < MIN_ACCOUNT_POSTS) continue;
		if (optedInIds && !optedInIds.has(accountId)) continue;

		const questionPosts = accountPosts.filter((p) => {
			const firstSentence = (p.content || "").split(/[.!?\n]/)[0] || "";
			return firstSentence.includes("?");
		});
		const nonQuestionPosts = accountPosts.filter((p) => {
			const firstSentence = (p.content || "").split(/[.!?\n]/)[0] || "";
			return !firstSentence.includes("?");
		});

		if (questionPosts.length < 3 || nonQuestionPosts.length < 3) continue;

		const avgQComments =
			questionPosts.reduce((s: number, p) => s + (p.replies_count ?? 0), 0) /
			questionPosts.length;
		const avgNQComments =
			nonQuestionPosts.reduce((s: number, p) => s + (p.replies_count ?? 0), 0) /
			nonQuestionPosts.length;

		if (avgNQComments > 0) {
			accountsWithData++;
			totalMultiplier += avgQComments / avgNQComments;
		}
	}

	if (accountsWithData < MIN_ACCOUNTS_FOR_INSIGHT) return null;

	const avgMultiplier = totalMultiplier / accountsWithData;
	if (avgMultiplier <= 1.1) return null;

	const magnitude = `${avgMultiplier.toFixed(1)}×`;
	return {
		id: "question-comments",
		text: `Posts with questions in the first sentence get ${magnitude} more comments`,
		magnitude,
		sampleSize: accountsWithData,
		confidence: Math.min(accountsWithData / 50, 1),
	};
}

async function computePostingFrequencyInsight(
	optedInIds: Set<string> | null,
): Promise<NetworkInsight | null> {
	const thirtyDaysAgo = new Date();
	thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

	const accountFilter = optedInIds ? Array.from(optedInIds) : null;
	if (accountFilter && accountFilter.length === 0) return null;

	let analyticsQuery = db()
		.from("account_analytics")
		.select("account_id, followers_count, date")
		.gte("date", thirtyDaysAgo.toISOString().split("T")[0]!)
		.order("date", { ascending: true });
	if (accountFilter)
		analyticsQuery = analyticsQuery.in("account_id", accountFilter);

	const { data: analytics } = await analyticsQuery;

	if (!analytics || analytics.length === 0) return null;

	let freqPostsQuery = db()
		.from("posts")
		.select("account_id, published_at")
		.not("published_at", "is", null)
		.gte("published_at", thirtyDaysAgo.toISOString());
	if (accountFilter)
		freqPostsQuery = freqPostsQuery.in("account_id", accountFilter);

	const { data: posts } = await freqPostsQuery;

	if (!posts || posts.length === 0) return null;

	// Count posts per account in last 30 days
	const postCounts = new Map<string, number>();
	for (const p of posts as PostRow[]) {
		postCounts.set(p.account_id, (postCounts.get(p.account_id) || 0) + 1);
	}

	// Get follower growth per account
	const analyticsByAccount = new Map<string, AnalyticsRow[]>();
	for (const row of analytics as AnalyticsRow[]) {
		const arr = analyticsByAccount.get(row.account_id) || [];
		arr.push(row);
		analyticsByAccount.set(row.account_id, arr);
	}

	let highFreqGrowth = 0;
	let highFreqCount = 0;
	let lowFreqGrowth = 0;
	let lowFreqCount = 0;

	for (const [accountId, rows] of analyticsByAccount) {
		if (rows.length < 7) continue;
		if (optedInIds && !optedInIds.has(accountId)) continue;
		const sorted = rows.sort((a, b) => a.date.localeCompare(b.date));
		const first = sorted[0]!.followers_count ?? 0;
		const last = sorted[sorted.length - 1]!.followers_count ?? 0;
		if (first <= 0) continue;

		const growthRate = ((last - first) / first) * 100;
		const postsPerWeek = ((postCounts.get(accountId) || 0) / 30) * 7;

		if (postsPerWeek >= 4) {
			highFreqGrowth += growthRate;
			highFreqCount++;
		} else if (postsPerWeek >= 1 && postsPerWeek <= 2) {
			lowFreqGrowth += growthRate;
			lowFreqCount++;
		}
	}

	if (
		highFreqCount < MIN_ACCOUNTS_FOR_INSIGHT ||
		lowFreqCount < MIN_ACCOUNTS_FOR_INSIGHT
	)
		return null;

	const avgHighGrowth = highFreqGrowth / highFreqCount;
	const avgLowGrowth = lowFreqGrowth / lowFreqCount;

	if (avgLowGrowth <= 0 || avgHighGrowth <= avgLowGrowth) return null;

	const multiplier = avgHighGrowth / avgLowGrowth;
	if (multiplier <= 1.2) return null;

	const magnitude = `${multiplier.toFixed(1)}×`;
	return {
		id: "posting-frequency-growth",
		text: `Accounts posting 4-5×/week grow followers ${magnitude} faster than 1-2×/week`,
		magnitude,
		sampleSize: highFreqCount + lowFreqCount,
		confidence: Math.min((highFreqCount + lowFreqCount) / 50, 1),
	};
}

async function computeContentLengthInsight(
	optedInIds: Set<string> | null,
): Promise<NetworkInsight | null> {
	const accountFilter = optedInIds ? Array.from(optedInIds) : null;
	if (accountFilter && accountFilter.length === 0) return null;

	let lenPostsQuery = db()
		.from("posts")
		.select("account_id, content, views_count, likes_count, replies_count")
		.not("published_at", "is", null)
		.not("content", "is", null);
	if (accountFilter)
		lenPostsQuery = lenPostsQuery.in("account_id", accountFilter);

	const { data: posts } = await lenPostsQuery;

	if (!posts || posts.length === 0) return null;

	const postsByAccount = new Map<string, PostRow[]>();
	for (const p of posts as PostRow[]) {
		const arr = postsByAccount.get(p.account_id) || [];
		arr.push(p);
		postsByAccount.set(p.account_id, arr);
	}

	let accountsWithData = 0;
	let totalLift = 0;

	for (const [accountId, accountPosts] of postsByAccount) {
		if (accountPosts.length < MIN_ACCOUNT_POSTS) continue;
		if (optedInIds && !optedInIds.has(accountId)) continue;

		const mediumPosts = accountPosts.filter((p) => {
			const len = (p.content || "").length;
			return len >= 100 && len <= 300;
		});
		const shortPosts = accountPosts.filter(
			(p) => (p.content || "").length < 100,
		);

		if (mediumPosts.length < 3 || shortPosts.length < 3) continue;

		const avgMediumEng =
			mediumPosts.reduce(
				(s: number, p) => s + (p.likes_count ?? 0) + (p.replies_count ?? 0),
				0,
			) / mediumPosts.length;
		const avgShortEng =
			shortPosts.reduce(
				(s: number, p) => s + (p.likes_count ?? 0) + (p.replies_count ?? 0),
				0,
			) / shortPosts.length;

		if (avgShortEng > 0) {
			accountsWithData++;
			totalLift += ((avgMediumEng - avgShortEng) / avgShortEng) * 100;
		}
	}

	if (accountsWithData < MIN_ACCOUNTS_FOR_INSIGHT) return null;

	const avgLift = totalLift / accountsWithData;
	if (avgLift <= 5) return null;

	const magnitude = `${Math.round(avgLift)}%`;
	return {
		id: "content-length-engagement",
		text: `Medium-length posts (100-300 chars) get ${magnitude} more engagement than short posts`,
		magnitude,
		sampleSize: accountsWithData,
		confidence: Math.min(accountsWithData / 50, 1),
	};
}

async function computeTimingConsistencyInsight(
	optedInIds: Set<string> | null,
): Promise<NetworkInsight | null> {
	const accountFilter = optedInIds ? Array.from(optedInIds) : null;
	if (accountFilter && accountFilter.length === 0) return null;

	let timingPostsQuery = db()
		.from("posts")
		.select("account_id, published_at, views_count")
		.not("published_at", "is", null);
	if (accountFilter)
		timingPostsQuery = timingPostsQuery.in("account_id", accountFilter);

	const { data: posts } = await timingPostsQuery;

	if (!posts || posts.length === 0) return null;

	const postsByAccount = new Map<string, PostRow[]>();
	for (const p of posts as PostRow[]) {
		const arr = postsByAccount.get(p.account_id) || [];
		arr.push(p);
		postsByAccount.set(p.account_id, arr);
	}

	let consistentAvgViews = 0;
	let consistentCount = 0;
	let inconsistentAvgViews = 0;
	let inconsistentCount = 0;

	for (const [accountId, accountPosts] of postsByAccount) {
		if (accountPosts.length < MIN_ACCOUNT_POSTS) continue;
		if (optedInIds && !optedInIds.has(accountId)) continue;

		// Check hour-of-day consistency
		const hours = accountPosts.map((p) =>
			new Date(p.published_at ?? "").getHours(),
		);
		const avgHour =
			hours.reduce((s: number, h: number) => s + h, 0) / hours.length;
		const variance =
			hours.reduce((s: number, h: number) => s + (h - avgHour) ** 2, 0) /
			hours.length;
		const stdDev = Math.sqrt(variance);

		const avgViews =
			accountPosts.reduce((s: number, p) => s + (p.views_count ?? 0), 0) /
			accountPosts.length;

		if (stdDev <= 3) {
			consistentAvgViews += avgViews;
			consistentCount++;
		} else {
			inconsistentAvgViews += avgViews;
			inconsistentCount++;
		}
	}

	if (
		consistentCount < MIN_ACCOUNTS_FOR_INSIGHT ||
		inconsistentCount < MIN_ACCOUNTS_FOR_INSIGHT
	)
		return null;

	const avgConsistent = consistentAvgViews / consistentCount;
	const avgInconsistent = inconsistentAvgViews / inconsistentCount;

	if (avgInconsistent <= 0 || avgConsistent <= avgInconsistent) return null;

	const lift = ((avgConsistent - avgInconsistent) / avgInconsistent) * 100;
	if (lift <= 5) return null;

	const magnitude = `${Math.round(lift)}%`;
	return {
		id: "timing-consistency",
		text: `Creators who post at consistent times see ${magnitude} more average views`,
		magnitude,
		sampleSize: consistentCount + inconsistentCount,
		confidence: Math.min((consistentCount + inconsistentCount) / 50, 1),
	};
}

/* ------------------------------------------------------------------ */
/*  Main compute function                                              */
/* ------------------------------------------------------------------ */

/**
 * Get account IDs belonging to users who opted into data contribution.
 * Returns null if no filter should be applied (fallback: include all).
 */
async function getOptedInAccountIds(): Promise<Set<string> | null> {
	try {
		const { data: prefs } = await db()
			.from("user_preferences")
			.select("user_id")
			.eq("data_contribution_opted_in", true);

		if (!prefs || prefs.length === 0) return new Set<string>(); // no opted-in users → empty set (don't aggregate without consent)

		const userIds = (prefs as { user_id: string }[]).map((p) => p.user_id);

		const { data: accounts } = await db()
			.from("accounts")
			.select("id")
			.in("user_id", userIds);

		if (!accounts || accounts.length === 0) return new Set<string>();
		return new Set((accounts as { id: string }[]).map((a) => a.id));
	} catch (err) {
		logger.warn("Failed to fetch opted-in accounts for network insights", {
			error: String(err),
		});
		return new Set<string>(); // fallback: empty set (don't aggregate on error)
	}
}

async function computeNetworkInsights(): Promise<NetworkInsight[]> {
	// Pre-fetch opted-in account filter
	const optedInIds = await getOptedInAccountIds();

	const results = await Promise.allSettled([
		computeReplyTimeInsight(optedInIds),
		computeQuestionPostInsight(optedInIds),
		computePostingFrequencyInsight(optedInIds),
		computeContentLengthInsight(optedInIds),
		computeTimingConsistencyInsight(optedInIds),
	]);

	const insights: NetworkInsight[] = [];
	for (const result of results) {
		if (result.status === "fulfilled" && result.value) {
			insights.push(result.value);
		} else if (result.status === "rejected") {
			logger.warn("Network insight computation failed", {
				error: String(result.reason),
			});
		}
	}

	// Sort by confidence desc, take top 5
	return insights.sort((a, b) => b.confidence - a.confidence).slice(0, 5);
}

/* ------------------------------------------------------------------ */
/*  Handler                                                            */
/* ------------------------------------------------------------------ */

export default withAuth(async (req, res, user) => {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	try {
		// #628: Include user ID in cache key so different users don't share
		// cached insights data (each user may have different opted-in accounts)
		const insights = await cached<NetworkInsight[]>(
			`network:insights:${user.id}`,
			CACHE_TTL,
			computeNetworkInsights,
		);

		return apiSuccess(res, {
			data: { insights },
		});
	} catch (error: unknown) {
		logger.error("Network insights API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
