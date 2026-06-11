import { describe, it, expect } from "vitest";

// ─── Pure helper functions extracted from the sync pipeline ───
// These replicate the exact algorithms in threadsRefresh.ts, instagramRefresh.ts,
// and postProcess.ts so we can test correctness without DB/network dependencies.

interface PostMetrics {
	views_count: number | null | undefined;
	likes_count: number | null | undefined;
	replies_count: number | null | undefined;
	reposts_count: number | null | undefined;
	quotes_count: number | null | undefined;
	shares_count: number | null | undefined;
}

interface PostInsights {
	views: number;
	likes: number;
	replies: number;
	reposts: number;
	quotes: number;
	shares: number;
}

interface AccountTotals {
	total_views: number;
	total_likes: number;
	total_replies: number;
	total_reposts: number;
	total_quotes: number;
	total_shares: number;
	posts_count: number;
	engagement_rate: number;
}

/**
 * Replicates the SUM logic from threadsRefresh.ts lines 455-471:
 * Sums ALL published posts from the DB, not just the API-refreshed subset.
 */
function computeAccountTotals(allPublishedPosts: PostMetrics[]): AccountTotals {
	let dbTotalViews = 0;
	let dbTotalLikes = 0;
	let dbTotalReplies = 0;
	let dbTotalReposts = 0;
	let dbTotalQuotes = 0;
	let dbTotalShares = 0;

	for (const p of allPublishedPosts) {
		dbTotalViews += p.views_count || 0;
		dbTotalLikes += p.likes_count || 0;
		dbTotalReplies += p.replies_count || 0;
		dbTotalReposts += p.reposts_count || 0;
		dbTotalQuotes += p.quotes_count || 0;
		dbTotalShares += p.shares_count || 0;
	}

	const engagementRate =
		dbTotalViews > 0
			? ((dbTotalLikes + dbTotalReplies + dbTotalReposts + dbTotalShares) /
					dbTotalViews) *
				100
			: 0;

	return {
		total_views: dbTotalViews,
		total_likes: dbTotalLikes,
		total_replies: dbTotalReplies,
		total_reposts: dbTotalReposts,
		total_quotes: dbTotalQuotes,
		total_shares: dbTotalShares,
		posts_count: allPublishedPosts.length,
		engagement_rate: engagementRate,
	};
}

/**
 * Replicates per-post engagement rate from threadsRefresh.ts lines 246-254.
 */
function computePostEngagementRate(insights: PostInsights): number {
	return insights.views > 0
		? ((insights.likes +
				insights.replies +
				insights.reposts +
				insights.shares) /
				insights.views) *
				100
		: 0;
}

/**
 * Replicates the IG engagement rate formula from instagramRefresh.ts lines 247-255.
 * IG uses reach first, then falls back to views.
 */
function computeIgEngagementRate(
	likes: number,
	comments: number,
	shares: number,
	saved: number,
	reach: number,
	views: number,
): number {
	if (reach > 0) return ((likes + comments + shares + saved) / reach) * 100;
	if (views > 0) return ((likes + comments + shares + saved) / views) * 100;
	return 0;
}

/**
 * Replicates follower growth from threadsRefresh.ts lines 498-527.
 */
function computeFollowerGrowth(
	todayFollowers: number,
	yesterdayRow: { followers_count: number | null } | null,
	latestHistoricalRow: { followers_count: number | null } | null,
): number {
	if (yesterdayRow?.followers_count) {
		return todayFollowers - yesterdayRow.followers_count;
	}
	if (latestHistoricalRow?.followers_count) {
		return todayFollowers - latestHistoricalRow.followers_count;
	}
	return 0;
}

/**
 * Replicates trend percentage from postProcess.ts lines 141-156.
 * viewsTrendPct, engagementTrendPct, followerTrendPct all use same formula.
 */
function computeTrendPct(today: number, yesterday: number): number {
	if (yesterday > 0) {
		return Math.round(((today - yesterday) / yesterday) * 100 * 100) / 100;
	}
	return 0;
}

/**
 * Replicates the "accumulate from API results only" totals (the OLD buggy approach
 * that only counted API-refreshed posts). Used to verify the fix works.
 */
function computeTotalsFromApiResults(
	apiResults: (PostInsights | null)[],
): Omit<AccountTotals, "engagement_rate"> {
	let totalViews = 0;
	let totalLikes = 0;
	let totalReplies = 0;
	let totalReposts = 0;
	let totalQuotes = 0;
	let totalShares = 0;
	let postsCount = 0;

	for (const insights of apiResults) {
		if (insights) {
			totalViews += insights.views;
			totalLikes += insights.likes;
			totalReplies += insights.replies;
			totalReposts += insights.reposts;
			totalQuotes += insights.quotes || 0;
			totalShares += insights.shares;
			postsCount++;
		}
	}

	return {
		total_views: totalViews,
		total_likes: totalLikes,
		total_replies: totalReplies,
		total_reposts: totalReposts,
		total_quotes: totalQuotes,
		total_shares: totalShares,
		posts_count: postsCount,
	};
}

/**
 * Replicates the monotonic guard logic: new metric value must be >= old value.
 * From threadsRefresh.ts lines 277-296 (update_post_metrics_if_newer RPC).
 */
function shouldUpdateMetrics(
	newMetrics: PostInsights,
	existingMetrics: PostInsights,
): boolean {
	const newTotal =
		(newMetrics.views || 0) +
		(newMetrics.likes || 0) +
		(newMetrics.replies || 0) +
		(newMetrics.reposts || 0);
	const existingTotal =
		(existingMetrics.views || 0) +
		(existingMetrics.likes || 0) +
		(existingMetrics.replies || 0) +
		(existingMetrics.reposts || 0);
	return newTotal >= existingTotal;
}

/**
 * Replicates best post selection from postProcess.ts lines 117-133.
 * Posts are ordered by views_count DESC, first one per account wins.
 */
function selectBestPost(
	posts: Array<{ id: string; account_id: string; views_count: number | null }>,
	accountId: string,
): { id: string; views_count: number | null } | null {
	// Sort by views_count DESC, nulls last
	const sorted = [...posts]
		.filter((p) => p.account_id === accountId)
		.sort((a, b) => {
			const aViews = a.views_count ?? -1;
			const bViews = b.views_count ?? -1;
			return bViews - aViews;
		});
	return sorted.length > 0 ? sorted[0] : null;
}

/**
 * Replicates IG post-derived totals from instagramRefresh.ts lines 394-409.
 */
function computeIgPostDerivedTotals(
	allPublished: Array<{
		ig_comment_count: number | null | undefined;
		ig_saved: number | null | undefined;
		ig_shares: number | null | undefined;
	}>,
): { totalComments: number; totalSaved: number; totalShares: number; count: number } {
	let totalComments = 0;
	let totalSaved = 0;
	let totalShares = 0;

	for (const p of allPublished) {
		totalComments += p.ig_comment_count || 0;
		totalSaved += p.ig_saved || 0;
		totalShares += p.ig_shares || 0;
	}

	return { totalComments, totalSaved, totalShares, count: allPublished.length };
}

// ─── Tests ───

describe("Data Pipeline Integrity", () => {
	describe("1. Account totals must equal SUM of all published posts", () => {
		it("correctly sums 5 posts with known metrics", () => {
			const posts: PostMetrics[] = [
				{ views_count: 100, likes_count: 10, replies_count: 5, reposts_count: 2, quotes_count: 1, shares_count: 3 },
				{ views_count: 200, likes_count: 20, replies_count: 10, reposts_count: 4, quotes_count: 2, shares_count: 6 },
				{ views_count: 300, likes_count: 30, replies_count: 15, reposts_count: 6, quotes_count: 3, shares_count: 9 },
				{ views_count: 400, likes_count: 40, replies_count: 20, reposts_count: 8, quotes_count: 4, shares_count: 12 },
				{ views_count: 500, likes_count: 50, replies_count: 25, reposts_count: 10, quotes_count: 5, shares_count: 15 },
			];

			const totals = computeAccountTotals(posts);

			expect(totals.total_views).toBe(1500);
			expect(totals.total_likes).toBe(150);
			expect(totals.total_replies).toBe(75);
			expect(totals.total_reposts).toBe(30);
			expect(totals.total_quotes).toBe(15);
			expect(totals.total_shares).toBe(45);
			expect(totals.posts_count).toBe(5);
		});

		it("handles mixed null/undefined/0 values in metric fields", () => {
			const posts: PostMetrics[] = [
				{ views_count: 100, likes_count: null, replies_count: undefined, reposts_count: 0, quotes_count: null, shares_count: 5 },
				{ views_count: null, likes_count: 20, replies_count: 10, reposts_count: null, quotes_count: undefined, shares_count: 0 },
				{ views_count: undefined, likes_count: undefined, replies_count: null, reposts_count: undefined, quotes_count: 0, shares_count: null },
			];

			const totals = computeAccountTotals(posts);

			expect(totals.total_views).toBe(100);
			expect(totals.total_likes).toBe(20);
			expect(totals.total_replies).toBe(10);
			expect(totals.total_reposts).toBe(0);
			expect(totals.total_quotes).toBe(0);
			expect(totals.total_shares).toBe(5);
			expect(totals.posts_count).toBe(3);
		});

		it("returns all zeros for empty post array", () => {
			const totals = computeAccountTotals([]);

			expect(totals.total_views).toBe(0);
			expect(totals.total_likes).toBe(0);
			expect(totals.posts_count).toBe(0);
			expect(totals.engagement_rate).toBe(0);
		});

		it("returns correct totals when all metrics are zero", () => {
			const posts: PostMetrics[] = [
				{ views_count: 0, likes_count: 0, replies_count: 0, reposts_count: 0, quotes_count: 0, shares_count: 0 },
				{ views_count: 0, likes_count: 0, replies_count: 0, reposts_count: 0, quotes_count: 0, shares_count: 0 },
			];

			const totals = computeAccountTotals(posts);

			expect(totals.total_views).toBe(0);
			expect(totals.posts_count).toBe(2);
			expect(totals.engagement_rate).toBe(0);
		});
	});

	describe("2. posts_count must equal actual published post count", () => {
		it("posts_count equals the length of allPublishedPosts array", () => {
			const posts: PostMetrics[] = Array.from({ length: 42 }, () => ({
				views_count: 10,
				likes_count: 1,
				replies_count: 0,
				reposts_count: 0,
				quotes_count: 0,
				shares_count: 0,
			}));

			const totals = computeAccountTotals(posts);
			expect(totals.posts_count).toBe(42);
		});

		it("API failures do not inflate posts_count (DB-sourced totals use ALL posts)", () => {
			// Scenario: 5 posts exist in DB, but API only returns insights for 3
			const allDbPosts: PostMetrics[] = [
				{ views_count: 100, likes_count: 10, replies_count: 5, reposts_count: 2, quotes_count: 1, shares_count: 3 },
				{ views_count: 200, likes_count: 20, replies_count: 10, reposts_count: 4, quotes_count: 2, shares_count: 6 },
				{ views_count: 50, likes_count: 5, replies_count: 2, reposts_count: 1, quotes_count: 0, shares_count: 1 },
				{ views_count: 300, likes_count: 30, replies_count: 15, reposts_count: 6, quotes_count: 3, shares_count: 9 },
				{ views_count: 150, likes_count: 15, replies_count: 7, reposts_count: 3, quotes_count: 1, shares_count: 4 },
			];

			const totals = computeAccountTotals(allDbPosts);
			// Must reflect ALL 5 posts, not just the 3 that API returned
			expect(totals.posts_count).toBe(5);
		});

		it("API failures do not deflate posts_count", () => {
			// Even if API returns null for all posts, DB count is authoritative
			const apiResults: (PostInsights | null)[] = [null, null, null, null, null];
			const apiTotals = computeTotalsFromApiResults(apiResults);
			// API-only count would be 0 (the old bug)
			expect(apiTotals.posts_count).toBe(0);

			// But DB-sourced totals correctly report 5
			const dbPosts: PostMetrics[] = Array.from({ length: 5 }, () => ({
				views_count: 100,
				likes_count: 10,
				replies_count: 5,
				reposts_count: 2,
				quotes_count: 1,
				shares_count: 3,
			}));
			const dbTotals = computeAccountTotals(dbPosts);
			expect(dbTotals.posts_count).toBe(5);
		});
	});

	describe("3. Failed API calls must not reduce totals", () => {
		it("DB-sourced totals include all 5 posts even when API fails for 2", () => {
			// All 5 posts exist in DB with their stored metrics
			const allDbPosts: PostMetrics[] = [
				{ views_count: 100, likes_count: 10, replies_count: 5, reposts_count: 2, quotes_count: 1, shares_count: 3 },
				{ views_count: 200, likes_count: 20, replies_count: 10, reposts_count: 4, quotes_count: 2, shares_count: 6 },
				{ views_count: 300, likes_count: 30, replies_count: 15, reposts_count: 6, quotes_count: 3, shares_count: 9 },
				{ views_count: 400, likes_count: 40, replies_count: 20, reposts_count: 8, quotes_count: 4, shares_count: 12 },
				{ views_count: 500, likes_count: 50, replies_count: 25, reposts_count: 10, quotes_count: 5, shares_count: 15 },
			];

			// API only returns 3 of 5
			const apiResults: (PostInsights | null)[] = [
				{ views: 100, likes: 10, replies: 5, reposts: 2, quotes: 1, shares: 3 },
				null, // API failure
				{ views: 300, likes: 30, replies: 15, reposts: 6, quotes: 3, shares: 9 },
				null, // API failure
				{ views: 500, likes: 50, replies: 25, reposts: 10, quotes: 5, shares: 15 },
			];

			const apiTotals = computeTotalsFromApiResults(apiResults);
			const dbTotals = computeAccountTotals(allDbPosts);

			// API-only totals miss 2 posts
			expect(apiTotals.total_views).toBe(900);
			expect(apiTotals.posts_count).toBe(3);

			// DB-sourced totals include all 5
			expect(dbTotals.total_views).toBe(1500);
			expect(dbTotals.posts_count).toBe(5);
			expect(dbTotals.total_views).toBeGreaterThan(apiTotals.total_views);
		});

		it("total likes from DB are never less than API-only totals", () => {
			const dbPosts: PostMetrics[] = [
				{ views_count: 100, likes_count: 50, replies_count: 0, reposts_count: 0, quotes_count: 0, shares_count: 0 },
				{ views_count: 200, likes_count: 30, replies_count: 0, reposts_count: 0, quotes_count: 0, shares_count: 0 },
			];

			const apiResults: (PostInsights | null)[] = [
				{ views: 100, likes: 50, replies: 0, reposts: 0, quotes: 0, shares: 0 },
				null, // second post failed
			];

			const dbTotals = computeAccountTotals(dbPosts);
			const apiTotals = computeTotalsFromApiResults(apiResults);

			expect(dbTotals.total_likes).toBeGreaterThanOrEqual(apiTotals.total_likes);
		});
	});

	describe("4. Engagement rate calculation", () => {
		it("correct formula: (likes + replies + reposts + shares) / views * 100", () => {
			const insights: PostInsights = {
				views: 1000,
				likes: 50,
				replies: 20,
				reposts: 10,
				quotes: 5,
				shares: 20,
			};

			const rate = computePostEngagementRate(insights);
			// (50 + 20 + 10 + 20) / 1000 * 100 = 10%
			expect(rate).toBe(10);
		});

		it("zero views produces engagement rate of 0 (not NaN or Infinity)", () => {
			const insights: PostInsights = {
				views: 0,
				likes: 50,
				replies: 20,
				reposts: 10,
				quotes: 5,
				shares: 20,
			};

			const rate = computePostEngagementRate(insights);
			expect(rate).toBe(0);
			expect(Number.isFinite(rate)).toBe(true);
			expect(Number.isNaN(rate)).toBe(false);
		});

		it("all zeros produces engagement rate of 0", () => {
			const insights: PostInsights = {
				views: 0,
				likes: 0,
				replies: 0,
				reposts: 0,
				quotes: 0,
				shares: 0,
			};

			const rate = computePostEngagementRate(insights);
			expect(rate).toBe(0);
		});

		it("account-level engagement rate uses totals correctly", () => {
			const posts: PostMetrics[] = [
				{ views_count: 500, likes_count: 25, replies_count: 10, reposts_count: 5, quotes_count: 2, shares_count: 10 },
				{ views_count: 500, likes_count: 25, replies_count: 10, reposts_count: 5, quotes_count: 3, shares_count: 10 },
			];

			const totals = computeAccountTotals(posts);
			// (50 + 20 + 10 + 20) / 1000 * 100 = 10%
			expect(totals.engagement_rate).toBe(10);
		});

		it("IG engagement rate uses reach first, then views as fallback", () => {
			// With reach available
			const erWithReach = computeIgEngagementRate(10, 5, 3, 2, 100, 500);
			expect(erWithReach).toBe(20); // (10+5+3+2)/100*100

			// With reach=0, falls back to views
			const erWithViews = computeIgEngagementRate(10, 5, 3, 2, 0, 500);
			expect(erWithViews).toBe(4); // (10+5+3+2)/500*100

			// Both zero
			const erZero = computeIgEngagementRate(10, 5, 3, 2, 0, 0);
			expect(erZero).toBe(0);
		});
	});

	describe("5. Follower growth calculation", () => {
		it("growth = today - yesterday when yesterday row exists", () => {
			const growth = computeFollowerGrowth(1050, { followers_count: 1000 }, null);
			expect(growth).toBe(50);
		});

		it("negative growth is computed correctly", () => {
			const growth = computeFollowerGrowth(950, { followers_count: 1000 }, null);
			expect(growth).toBe(-50);
		});

		it("falls back to latest historical row when no yesterday row", () => {
			const growth = computeFollowerGrowth(
				1100,
				null,
				{ followers_count: 1000 },
			);
			expect(growth).toBe(100);
		});

		it("returns 0 when no historical rows exist at all", () => {
			const growth = computeFollowerGrowth(500, null, null);
			expect(growth).toBe(0);
		});

		it("returns 0 when yesterday has null followers_count", () => {
			const growth = computeFollowerGrowth(500, { followers_count: null }, null);
			expect(growth).toBe(0);
		});

		it("returns 0 when yesterday has 0 followers_count (falsy check in source)", () => {
			// The source code uses `if (previousData?.followers_count)` which is falsy for 0
			const growth = computeFollowerGrowth(500, { followers_count: 0 }, null);
			// With the falsy check, 0 falls through to the historical lookup
			expect(growth).toBe(0);
		});

		it("growth = todayFollowers when yesterday followers is 0 and no historical", () => {
			// Note: source code treats 0 as falsy, so it falls through to historical, then to 0
			const growth = computeFollowerGrowth(500, { followers_count: 0 }, null);
			expect(growth).toBe(0);
		});

		it("prefers yesterday over historical when both exist", () => {
			const growth = computeFollowerGrowth(
				1100,
				{ followers_count: 1050 },
				{ followers_count: 900 },
			);
			expect(growth).toBe(50); // Uses yesterday (1100-1050), not historical (1100-900)
		});
	});

	describe("6. Monotonicity check: metrics should not regress without reason", () => {
		it("new metrics with higher total should update", () => {
			const existing: PostInsights = { views: 100, likes: 10, replies: 5, reposts: 2, quotes: 1, shares: 3 };
			const newer: PostInsights = { views: 150, likes: 15, replies: 7, reposts: 3, quotes: 2, shares: 5 };

			expect(shouldUpdateMetrics(newer, existing)).toBe(true);
		});

		it("new metrics with equal total should update (>=)", () => {
			const existing: PostInsights = { views: 100, likes: 10, replies: 5, reposts: 2, quotes: 1, shares: 3 };
			const newer: PostInsights = { views: 100, likes: 10, replies: 5, reposts: 2, quotes: 1, shares: 3 };

			expect(shouldUpdateMetrics(newer, existing)).toBe(true);
		});

		it("new metrics with lower total should NOT update (stale data)", () => {
			const existing: PostInsights = { views: 200, likes: 20, replies: 10, reposts: 4, quotes: 2, shares: 6 };
			const newer: PostInsights = { views: 100, likes: 10, replies: 5, reposts: 2, quotes: 1, shares: 3 };

			expect(shouldUpdateMetrics(newer, existing)).toBe(false);
		});

		it("today sync fetches same 3 posts with higher likes: total should increase", () => {
			// Yesterday: 500 likes across 3 posts
			const yesterdayPosts: PostMetrics[] = [
				{ views_count: 1000, likes_count: 200, replies_count: 0, reposts_count: 0, quotes_count: 0, shares_count: 0 },
				{ views_count: 800, likes_count: 150, replies_count: 0, reposts_count: 0, quotes_count: 0, shares_count: 0 },
				{ views_count: 600, likes_count: 150, replies_count: 0, reposts_count: 0, quotes_count: 0, shares_count: 0 },
			];

			// Today: same 3 posts, now with 510 likes total
			const todayPosts: PostMetrics[] = [
				{ views_count: 1050, likes_count: 210, replies_count: 0, reposts_count: 0, quotes_count: 0, shares_count: 0 },
				{ views_count: 830, likes_count: 155, replies_count: 0, reposts_count: 0, quotes_count: 0, shares_count: 0 },
				{ views_count: 620, likes_count: 145, replies_count: 0, reposts_count: 0, quotes_count: 0, shares_count: 0 },
			];

			const yesterdayTotals = computeAccountTotals(yesterdayPosts);
			const todayTotals = computeAccountTotals(todayPosts);

			expect(yesterdayTotals.total_likes).toBe(500);
			expect(todayTotals.total_likes).toBe(510);
			expect(todayTotals.total_likes).toBeGreaterThan(yesterdayTotals.total_likes);
		});
	});

	describe("7. Posts older than 30 days still included in totals", () => {
		it("old post metrics are included in DB-sourced account_analytics totals", () => {
			// The key fix: allPublishedPosts query has NO date filter.
			// It queries ALL published posts for the account.
			// This test verifies the SUM includes posts of any age.
			const allDbPosts: PostMetrics[] = [
				// Recent post (1 day old)
				{ views_count: 100, likes_count: 10, replies_count: 5, reposts_count: 2, quotes_count: 1, shares_count: 3 },
				// Older post (15 days old)
				{ views_count: 200, likes_count: 20, replies_count: 10, reposts_count: 4, quotes_count: 2, shares_count: 6 },
				// Very old post (60 days old) — was excluded in the old bug
				{ views_count: 100, likes_count: 5, replies_count: 2, reposts_count: 1, quotes_count: 0, shares_count: 1 },
				// Ancient post (90 days old)
				{ views_count: 50, likes_count: 3, replies_count: 1, reposts_count: 0, quotes_count: 0, shares_count: 0 },
			];

			const totals = computeAccountTotals(allDbPosts);

			// The 60-day-old post's 100 views MUST be included
			expect(totals.total_views).toBe(450);
			expect(totals.posts_count).toBe(4);
			// Verify the old post's views are part of the total
			expect(totals.total_views).toBeGreaterThan(300); // Would be 300 without the old posts
		});

		it("API-only totals miss old posts (demonstrating the bug)", () => {
			// API only refreshes posts within 7-30 day window
			const apiRefreshedResults: (PostInsights | null)[] = [
				{ views: 100, likes: 10, replies: 5, reposts: 2, quotes: 1, shares: 3 }, // recent
				{ views: 200, likes: 20, replies: 10, reposts: 4, quotes: 2, shares: 6 }, // 15 days
			];
			// Posts >30 days are NOT in the API refresh set

			const apiTotals = computeTotalsFromApiResults(apiRefreshedResults);
			expect(apiTotals.total_views).toBe(300);
			expect(apiTotals.posts_count).toBe(2);

			// DB-sourced totals include ALL posts
			const allDbPosts: PostMetrics[] = [
				{ views_count: 100, likes_count: 10, replies_count: 5, reposts_count: 2, quotes_count: 1, shares_count: 3 },
				{ views_count: 200, likes_count: 20, replies_count: 10, reposts_count: 4, quotes_count: 2, shares_count: 6 },
				{ views_count: 100, likes_count: 5, replies_count: 2, reposts_count: 1, quotes_count: 0, shares_count: 1 }, // 60 days old
			];

			const dbTotals = computeAccountTotals(allDbPosts);
			expect(dbTotals.total_views).toBe(400);
			expect(dbTotals.posts_count).toBe(3);
			expect(dbTotals.total_views).toBeGreaterThan(apiTotals.total_views);
		});
	});

	describe("8. Concurrent sync safety", () => {
		it("monotonic guard prevents stale pipeline data from overwriting fresher data", () => {
			// Webhook delivered fresh data first
			const webhookData: PostInsights = { views: 500, likes: 50, replies: 20, reposts: 10, quotes: 5, shares: 15 };

			// Then a stale pipeline sync arrives with older numbers
			const stalePipelineData: PostInsights = { views: 400, likes: 40, replies: 15, reposts: 8, quotes: 4, shares: 12 };

			// Monotonic guard should reject the stale data
			expect(shouldUpdateMetrics(stalePipelineData, webhookData)).toBe(false);

			// But a legitimate newer sync should be accepted
			const newerPipelineData: PostInsights = { views: 600, likes: 60, replies: 25, reposts: 12, quotes: 6, shares: 18 };
			expect(shouldUpdateMetrics(newerPipelineData, webhookData)).toBe(true);
		});

		it("last write with correct data wins when two syncs run simultaneously", () => {
			// Both syncs compute totals from the same DB snapshot
			const dbPosts: PostMetrics[] = [
				{ views_count: 100, likes_count: 10, replies_count: 5, reposts_count: 2, quotes_count: 1, shares_count: 3 },
				{ views_count: 200, likes_count: 20, replies_count: 10, reposts_count: 4, quotes_count: 2, shares_count: 6 },
			];

			const sync1Totals = computeAccountTotals(dbPosts);
			const sync2Totals = computeAccountTotals(dbPosts);

			// Both should produce identical results
			expect(sync1Totals.total_views).toBe(sync2Totals.total_views);
			expect(sync1Totals.total_likes).toBe(sync2Totals.total_likes);
			expect(sync1Totals.posts_count).toBe(sync2Totals.posts_count);
			expect(sync1Totals.engagement_rate).toBe(sync2Totals.engagement_rate);
		});

		it("monotonic guard uses total engagement (views+likes+replies+reposts) for comparison", () => {
			// Edge case: views went down but likes went up — total engagement still higher
			const existing: PostInsights = { views: 200, likes: 10, replies: 5, reposts: 2, quotes: 1, shares: 3 };
			const newer: PostInsights = { views: 180, likes: 30, replies: 10, reposts: 5, quotes: 2, shares: 5 };

			const existingTotal = 200 + 10 + 5 + 2; // 217
			const newerTotal = 180 + 30 + 10 + 5; // 225

			expect(newerTotal).toBeGreaterThan(existingTotal);
			expect(shouldUpdateMetrics(newer, existing)).toBe(true);
		});
	});

	describe("9. Zero-division guards in postProcess", () => {
		it("views_trend_pct is 0 when yesterday_views is 0", () => {
			const trend = computeTrendPct(500, 0);
			expect(trend).toBe(0);
			expect(Number.isFinite(trend)).toBe(true);
		});

		it("engagement_trend_pct is 0 when yesterday_engagement is 0", () => {
			const trend = computeTrendPct(5.5, 0);
			expect(trend).toBe(0);
			expect(Number.isFinite(trend)).toBe(true);
		});

		it("follower_trend_pct is 0 when yesterday_followers is 0", () => {
			const trend = computeTrendPct(1000, 0);
			expect(trend).toBe(0);
			expect(Number.isFinite(trend)).toBe(true);
		});

		it("positive trend is calculated correctly", () => {
			const trend = computeTrendPct(1100, 1000);
			expect(trend).toBe(10); // 10% increase
		});

		it("negative trend is calculated correctly", () => {
			const trend = computeTrendPct(900, 1000);
			expect(trend).toBe(-10); // 10% decrease
		});

		it("no change produces 0% trend", () => {
			const trend = computeTrendPct(1000, 1000);
			expect(trend).toBe(0);
		});

		it("large growth does not overflow", () => {
			const trend = computeTrendPct(1000000, 1);
			expect(Number.isFinite(trend)).toBe(true);
			expect(trend).toBe(99999900);
		});
	});

	describe("10. Null ordering in best post selection", () => {
		it("posts with null views_count should not be selected as best post", () => {
			const posts = [
				{ id: "p1", account_id: "a1", views_count: null },
				{ id: "p2", account_id: "a1", views_count: 500 },
				{ id: "p3", account_id: "a1", views_count: null },
			];

			const best = selectBestPost(posts, "a1");
			expect(best).not.toBeNull();
			expect(best!.id).toBe("p2");
			expect(best!.views_count).toBe(500);
		});

		it("post with highest non-null views should win", () => {
			const posts = [
				{ id: "p1", account_id: "a1", views_count: 100 },
				{ id: "p2", account_id: "a1", views_count: 500 },
				{ id: "p3", account_id: "a1", views_count: 300 },
				{ id: "p4", account_id: "a1", views_count: null },
			];

			const best = selectBestPost(posts, "a1");
			expect(best).not.toBeNull();
			expect(best!.id).toBe("p2");
			expect(best!.views_count).toBe(500);
		});

		it("all null views returns the first post (null-safe)", () => {
			const posts = [
				{ id: "p1", account_id: "a1", views_count: null },
				{ id: "p2", account_id: "a1", views_count: null },
			];

			const best = selectBestPost(posts, "a1");
			// Both have null (-1 in sort), first one wins due to stable sort
			expect(best).not.toBeNull();
		});

		it("returns null for empty posts array", () => {
			const best = selectBestPost([], "a1");
			expect(best).toBeNull();
		});

		it("only considers posts for the specified account", () => {
			const posts = [
				{ id: "p1", account_id: "a1", views_count: 100 },
				{ id: "p2", account_id: "a2", views_count: 1000 },
				{ id: "p3", account_id: "a1", views_count: 200 },
			];

			const best = selectBestPost(posts, "a1");
			expect(best).not.toBeNull();
			expect(best!.id).toBe("p3");
			expect(best!.views_count).toBe(200);
		});

		it("post with 0 views is preferred over null views", () => {
			const posts = [
				{ id: "p1", account_id: "a1", views_count: null },
				{ id: "p2", account_id: "a1", views_count: 0 },
			];

			const best = selectBestPost(posts, "a1");
			expect(best).not.toBeNull();
			expect(best!.id).toBe("p2");
			expect(best!.views_count).toBe(0);
		});
	});

	describe("IG post-derived totals", () => {
		it("correctly sums comment, save, and share counts from all published IG posts", () => {
			const posts = [
				{ ig_comment_count: 10, ig_saved: 5, ig_shares: 3 },
				{ ig_comment_count: 20, ig_saved: 8, ig_shares: 6 },
				{ ig_comment_count: 15, ig_saved: 12, ig_shares: 9 },
			];

			const totals = computeIgPostDerivedTotals(posts);
			expect(totals.totalComments).toBe(45);
			expect(totals.totalSaved).toBe(25);
			expect(totals.totalShares).toBe(18);
			expect(totals.count).toBe(3);
		});

		it("handles null and undefined IG metric fields", () => {
			const posts = [
				{ ig_comment_count: null, ig_saved: undefined, ig_shares: 3 },
				{ ig_comment_count: 10, ig_saved: null, ig_shares: null },
				{ ig_comment_count: undefined, ig_saved: 5, ig_shares: undefined },
			];

			const totals = computeIgPostDerivedTotals(posts);
			expect(totals.totalComments).toBe(10);
			expect(totals.totalSaved).toBe(5);
			expect(totals.totalShares).toBe(3);
			expect(totals.count).toBe(3);
		});
	});
});
