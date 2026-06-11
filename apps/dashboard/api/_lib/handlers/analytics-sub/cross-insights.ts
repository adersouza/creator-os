// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Cross-Account Insights
 *
 * GET /api/analytics/cross-insights?days=14&platform=threads
 * Workspace-level analytics: aggregated metrics + posting patterns across
 * user accounts (Threads, Instagram, or both).
 *
 * Primary metrics (views, likes, replies) are derived from account_analytics
 * period deltas (latest - earliest in period) which come from the Threads/IG
 * Insights API and are synced daily. This matches dashboard behavior.
 * Post-level data is still used for best hours, best days, rankings, and top post.
 *
 * Called from analytics.ts router (already wrapped with withAuth).
 * Uses getAuthUserOrError directly to avoid double-wrapping.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, getAuthUserOrError } from "../../apiResponse.js";
import { getSupabase } from "../../supabase.js";
import { parseAnalyticsQuery } from "../helpers/parseAnalyticsQuery.js";
import { enforceAnalyticsSubRateLimit } from "./rateLimit.js";

const db = (): ReturnType<typeof getSupabase> => getSupabase();

interface UnifiedAccount {
	id: string;
	username: string;
	platform: "threads" | "instagram";
	followers_count: number;
}

export default async function handleCrossInsights(
	req: VercelRequest,
	res: VercelResponse,
) {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	const userId = user.id;
	const allowed = await enforceAnalyticsSubRateLimit(res, {
		userId,
		action: "cross-insights",
		limit: 20,
	});
	if (!allowed) return;

	const { days, platform: platformFilter } = parseAnalyticsQuery(req.query, {
		defaultDays: 14,
	});
	// Align cutoff to UTC midnight so "7 days" means 7 complete calendar days,
	// not a floating timestamp that shifts with execution time.
	const now = new Date();
	const utcMidnight = Date.UTC(
		now.getUTCFullYear(),
		now.getUTCMonth(),
		now.getUTCDate(),
	);
	const cutoff = new Date(utcMidnight - days * 86_400_000).toISOString();

	// ── Fetch accounts by platform ──
	const includeThreads = !platformFilter || platformFilter === "threads";
	const includeIg = !platformFilter || platformFilter === "instagram";

	// biome-ignore lint/suspicious/noExplicitAny: Vercel TS 5.9 — PostgrestFilterBuilder not assignable to Promise
	const accountQueries: any[] = [];
	if (includeThreads) {
		accountQueries.push(
			db()
				.from("accounts")
				.select("id, username, followers_count")
				.eq("user_id", userId),
		);
	}
	if (includeIg) {
		accountQueries.push(
			db()
				.from("instagram_accounts")
				.select("id, username, follower_count")
				.eq("user_id", userId),
		);
	}

	const accountResults = await Promise.all(accountQueries);

	// Check for errors
	for (const result of accountResults) {
		if (result.error) {
			return apiError(res, 500, "Failed to fetch accounts", {
				details: result.error.message,
			});
		}
	}

	// Unify account lists with platform tag
	const accounts: UnifiedAccount[] = [];
	let resultIdx = 0;

	if (includeThreads) {
		for (const a of accountResults[resultIdx].data ?? []) {
			accounts.push({
				id: a.id,
				username: a.username,
				platform: "threads",
				followers_count: a.followers_count ?? 0,
			});
		}
		resultIdx++;
	}

	if (includeIg) {
		for (const a of accountResults[resultIdx]?.data ?? []) {
			accounts.push({
				id: a.id,
				username: a.username ?? "unknown",
				platform: "instagram",
				followers_count: a.follower_count ?? 0,
			});
		}
	}

	if (accounts.length === 0) {
		return apiSuccess(res, {
			periodDays: days,
			platform: platformFilter ?? "all",
			totalPosts: 0,
			totalAccounts: 0,
			threadsAccounts: 0,
			instagramAccounts: 0,
			aggregated: {
				followers: 0,
				views: 0,
				likes: 0,
				replies: 0,
				shares: 0,
				engagementRate: 0,
			},
			platformBreakdown: { threads: null, instagram: null },
			topPost: null,
			bestHours: [],
			bestDays: [],
			rankings: [],
		});
	}

	const accountIds = accounts.map((a) => a.id);

	// ── Build posts query ──
	// Use published_at for time filtering (matches dashboard behavior).
	// Query by BOTH account_id (Threads) and user_id+platform (IG fallback for NULL account_ids).
	// biome-ignore lint/suspicious/noExplicitAny: Vercel TS 5.9 — PostgrestFilterBuilder not assignable to Promise
	const postsQueries: any[] = [];
	// biome-ignore lint/suspicious/noExplicitAny: Vercel TS 5.9 — PostgrestFilterBuilder not assignable to Promise
	const countQueries: any[] = [];

	if (includeThreads) {
		const threadsAccountIds = accounts
			.filter((a) => a.platform === "threads")
			.map((a) => a.id);

		if (threadsAccountIds.length > 0) {
			postsQueries.push(
				db()
					.from("posts")
					.select(
						"id, content, account_id, views_count, likes_count, replies_count, shares_count, created_at, published_at, platform",
					)
					.in("account_id", threadsAccountIds)
					.eq("user_id", userId)
					.eq("status", "published")
					.not("published_at", "is", null)
					.gte("published_at", cutoff)
					.order("published_at", { ascending: false })
					.limit(2000),
			);
			countQueries.push(
				db()
					.from("posts")
					.select("id", { count: "exact", head: true })
					.in("account_id", threadsAccountIds)
					.eq("user_id", userId)
					.eq("status", "published")
					.not("published_at", "is", null)
					.gte("published_at", cutoff),
			);
		}
	}

	if (includeIg) {
		const igAccountIds = accounts
			.filter((a) => a.platform === "instagram")
			.map((a) => a.id);
		if (igAccountIds.length > 0) {
			// IG posts use instagram_account_id; do not collapse all IG posts into one bucket.
			postsQueries.push(
				db()
					.from("posts")
					.select(
						"id, content, account_id, instagram_account_id, views_count, likes_count, replies_count, shares_count, created_at, published_at, platform",
					)
					.eq("user_id", userId)
					.eq("platform", "instagram")
					.in("instagram_account_id", igAccountIds)
					.eq("status", "published")
					.not("published_at", "is", null)
					.gte("published_at", cutoff)
					.order("published_at", { ascending: false })
					.limit(2000),
			);
			countQueries.push(
				db()
					.from("posts")
					.select("id", { count: "exact", head: true })
					.eq("user_id", userId)
					.eq("platform", "instagram")
					.in("instagram_account_id", igAccountIds)
					.eq("status", "published")
					.not("published_at", "is", null)
					.gte("published_at", cutoff),
			);
		}
	}

	// ── account_analytics period deltas (primary metric source) ──
	// Query all rows in the period to compute (latest - earliest) per account.
	// This matches how get_analytics computes periodDelta and how the dashboard works.
	const cutoffDate = cutoff.split("T")[0]!; // YYYY-MM-DD for date column
	const analyticsQuery = db()
		.from("account_analytics")
		.select(
			"account_id, followers_count, total_views, total_likes, total_replies, total_shares, date",
		)
		.in("account_id", accountIds)
		.gte("date", cutoffDate)
		.order("date", { ascending: true })
		.limit(Math.max(accountIds.length * days, 5000));

	// Run all queries in parallel
	const [analyticsResult, ...postAndCountResults] = await Promise.all([
		analyticsQuery,
		...postsQueries,
		...countQueries,
	]);

	// Split results: first N are post queries, next N are count queries
	const postResults = postAndCountResults.slice(0, postsQueries.length);
	const countResults = postAndCountResults.slice(postsQueries.length);

	// Check for analytics query errors
	if (analyticsResult.error) {
		return apiError(res, 500, "Failed to fetch account analytics", {
			details: analyticsResult.error.message,
		});
	}

	// Check for post query errors
	for (const result of postResults) {
		if (result.error) {
			return apiError(res, 500, "Failed to fetch posts", {
				details: result.error.message,
			});
		}
	}

	// Check for count query errors
	for (const result of countResults) {
		if (result.error) {
			return apiError(res, 500, "Failed to fetch post counts", {
				details: result.error.message,
			});
		}
	}

	// Merge all posts and deduplicate by id
	const seenPostIds = new Set<string>();
	// biome-ignore lint/suspicious/noExplicitAny: Vercel TS 5.9 — Supabase row type needs any for property access
	const allPosts: any[] = [];
	for (const result of postResults) {
		for (const p of result.data ?? []) {
			if (!seenPostIds.has(p.id)) {
				seenPostIds.add(p.id);
				allPosts.push(p);
			}
		}
	}

	// Exact post count
	let exactPostCount = 0;
	for (const result of countResults) {
		exactPostCount += (result.count as number) ?? 0;
	}
	if (exactPostCount === 0) exactPostCount = allPosts.length;

	// ── Period deltas from account_analytics (primary metric source) ──
	// Group rows by account_id, compute (latest - earliest) for each metric.
	const accountAnalyticsRows = new Map<
		string,
		Array<{
			followers_count: number;
			total_views: number;
			total_likes: number;
			total_replies: number;
			total_shares: number;
			date: string;
		}>
	>();
	for (const row of analyticsResult.data ?? []) {
		const aid = row.account_id as string;
		if (!accountAnalyticsRows.has(aid)) accountAnalyticsRows.set(aid, []);
		accountAnalyticsRows.get(aid)?.push({
			followers_count: row.followers_count ?? 0,
			total_views: row.total_views ?? 0,
			total_likes: row.total_likes ?? 0,
			total_replies: row.total_replies ?? 0,
			total_shares: row.total_shares ?? 0,
			date: row.date,
		});
	}

	// Compute per-account period deltas + latest followers
	const accountDeltas = new Map<
		string,
		{
			views: number;
			likes: number;
			replies: number;
			shares: number;
			followers: number;
		}
	>();
	for (const [aid, rows] of accountAnalyticsRows) {
		if (rows.length === 0) continue;
		// Rows are sorted ascending by date from the query
		const earliest = rows[0]!;
		const latest = rows[rows.length - 1]!;
		accountDeltas.set(aid, {
			views: Math.max(0, latest.total_views - earliest.total_views),
			likes: Math.max(0, latest.total_likes - earliest.total_likes),
			replies: Math.max(0, latest.total_replies - earliest.total_replies),
			shares: Math.max(0, latest.total_shares - earliest.total_shares),
			followers: latest.followers_count,
		});
	}

	// Compute followers: prefer analytics snapshot, fallback to live account value
	let aggFollowers = 0;
	const perPlatformFollowers: Record<string, number> = {
		threads: 0,
		instagram: 0,
	};
	for (const acc of accounts) {
		const delta = accountDeltas.get(acc.id);
		const analyticsFollowers = delta?.followers ?? 0;
		const liveFollowers = acc.followers_count;
		const followers = Math.max(analyticsFollowers, liveFollowers);
		aggFollowers += followers;
		perPlatformFollowers[acc.platform] =
			(perPlatformFollowers[acc.platform] ?? 0) + followers;
	}

	// ── Aggregated metrics from account_analytics period deltas ──
	// These are cumulative API values (latest - earliest) = actual gain in period.
	// Falls back to post-level sums for accounts without analytics data.
	let aggViews = 0;
	let aggLikes = 0;
	let aggReplies = 0;
	let aggShares = 0;

	// Per-platform breakdown
	const platformStats: Record<
		"threads" | "instagram",
		{
			posts: number;
			views: number;
			likes: number;
			replies: number;
			shares: number;
			followers: number;
		}
	> = {
		threads: {
			posts: 0,
			views: 0,
			likes: 0,
			replies: 0,
			shares: 0,
			followers: perPlatformFollowers.threads!,
		},
		instagram: {
			posts: 0,
			views: 0,
			likes: 0,
			replies: 0,
			shares: 0,
			followers: perPlatformFollowers.instagram!,
		},
	};

	// Build per-account post-level sums as fallback for accounts without analytics rows
	const postSumsByAccount = new Map<
		string,
		{ views: number; likes: number; replies: number; shares: number }
	>();
	for (const p of allPosts) {
		const aid = p.platform === "instagram" ? p.instagram_account_id : p.account_id;
		if (!aid) continue;
		if (!postSumsByAccount.has(aid))
			postSumsByAccount.set(aid, { views: 0, likes: 0, replies: 0, shares: 0 });
		const sums = postSumsByAccount.get(aid) ?? {
			views: 0,
			likes: 0,
			replies: 0,
			shares: 0,
		};
		sums.views += p.views_count ?? 0;
		sums.likes += p.likes_count ?? 0;
		sums.replies += p.replies_count ?? 0;
		sums.shares += p.shares_count ?? 0;

		const plat = p.platform === "instagram" ? "instagram" : "threads";
		platformStats[plat].posts++;
	}

	// Sum using analytics deltas (accurate), falling back to post sums
	for (const acc of accounts) {
		const delta = accountDeltas.get(acc.id);
		const postSums = postSumsByAccount.get(acc.id);
		const v = delta?.views ?? postSums?.views ?? 0;
		const l = delta?.likes ?? postSums?.likes ?? 0;
		const r = delta?.replies ?? postSums?.replies ?? 0;
		const s = delta?.shares ?? postSums?.shares ?? 0;
		aggViews += v;
		aggLikes += l;
		aggReplies += r;
		aggShares += s;
		platformStats[acc.platform].views += v;
		platformStats[acc.platform].likes += l;
		platformStats[acc.platform].replies += r;
		platformStats[acc.platform].shares += s;
	}

	const totalEngagement = aggLikes + aggReplies + aggShares;
	const engagementRate =
		aggFollowers > 0 && exactPostCount > 0
			? Math.round(
					(totalEngagement / (exactPostCount * aggFollowers)) * 10000,
				) / 100
			: 0;

	// ── Best posting hours (UTC) ──
	const hourBuckets: Record<
		number,
		{ count: number; totalEngagement: number }
	> = {};
	const dayBuckets: Record<number, { count: number; totalEngagement: number }> =
		{};

	for (const p of allPosts) {
		const d = new Date(p.published_at);
		const hour = d.getUTCHours();
		const day = d.getUTCDay();
		const engagement = (p.likes_count ?? 0) + (p.replies_count ?? 0);

		if (!hourBuckets[hour])
			hourBuckets[hour] = { count: 0, totalEngagement: 0 };
		hourBuckets[hour].count++;
		hourBuckets[hour].totalEngagement += engagement;

		if (!dayBuckets[day]) dayBuckets[day] = { count: 0, totalEngagement: 0 };
		dayBuckets[day].count++;
		dayBuckets[day].totalEngagement += engagement;
	}

	const dayNames = [
		"Sunday",
		"Monday",
		"Tuesday",
		"Wednesday",
		"Thursday",
		"Friday",
		"Saturday",
	];

	const bestHours = Object.entries(hourBuckets)
		.map(([hour, data]) => ({
			hour: parseInt(hour, 10),
			posts: data.count,
			avgEngagement: Math.round((data.totalEngagement / data.count) * 10) / 10,
		}))
		.sort((a, b) => b.avgEngagement - a.avgEngagement);

	const bestDays = Object.entries(dayBuckets)
		.map(([day, data]) => ({
			day: dayNames[parseInt(day, 10)] ?? "Unknown",
			dayIndex: parseInt(day, 10),
			posts: data.count,
			avgEngagement: Math.round((data.totalEngagement / data.count) * 10) / 10,
		}))
		.sort((a, b) => b.avgEngagement - a.avgEngagement);

	// ── Per-account performance ──
	const accountMap = new Map(accounts.map((a) => [a.id, a]));
	const accountPerf: Record<
		string,
		{
			posts: Array<(typeof allPosts)[0]>;
			totalEngagement: number;
			totalReach: number;
		}
	> = {};

	for (const p of allPosts) {
		const aid = p.platform === "instagram" ? p.instagram_account_id : p.account_id;
		if (!aid) continue;
		if (!accountPerf[aid]) {
			accountPerf[aid] = {
				posts: [],
				totalEngagement: 0,
				totalReach: 0,
			};
		}
		const perf = accountPerf[aid]!;
		perf.posts.push(p);
		perf.totalEngagement += (p.likes_count ?? 0) + (p.replies_count ?? 0);
		perf.totalReach += p.views_count ?? 0;
	}

	const rankings = Object.entries(accountPerf)
		.map(([accountId, perf]) => {
			const acc = accountMap.get(accountId);
			const delta = accountDeltas.get(accountId);
			const bestPost = perf.posts.reduce((best, p) => {
				const eng = (p.likes_count ?? 0) + (p.replies_count ?? 0);
				const bestEng = (best.likes_count ?? 0) + (best.replies_count ?? 0);
				return eng > bestEng ? p : best;
			}, perf.posts[0]!);

			// Use analytics delta for total reach if available (more accurate)
			const totalReach = delta?.views ?? perf.totalReach;

			return {
				accountId,
				username: acc?.username ?? "unknown",
				platform: acc?.platform ?? (perf.posts[0]?.platform || "unknown"),
				postsCount: perf.posts.length,
				avgEngagement:
					Math.round((perf.totalEngagement / perf.posts.length) * 10) / 10,
				avgReach:
					perf.posts.length > 0
						? Math.round(totalReach / perf.posts.length)
						: 0,
				totalViews: totalReach,
				bestPost: bestPost
					? {
							id: bestPost.id,
							content: bestPost.content?.substring(0, 100) ?? "",
							engagement:
								(bestPost.likes_count ?? 0) + (bestPost.replies_count ?? 0),
							reach: bestPost.views_count ?? 0,
						}
					: null,
			};
		})
		.sort((a, b) => b.avgEngagement - a.avgEngagement);

	// ── Top post across all accounts ──
	type PostRow = (typeof allPosts)[0];
	const topPost =
		allPosts.length > 0
			? allPosts.reduce((best: PostRow, p: PostRow) => {
					const eng =
						(p.likes_count ?? 0) +
						(p.replies_count ?? 0) +
						(p.views_count ?? 0);
					const bestEng =
						(best.likes_count ?? 0) +
						(best.replies_count ?? 0) +
						(best.views_count ?? 0);
					return eng > bestEng ? p : best;
				}, allPosts[0]!)
			: null;

	// ── Platform breakdown (only include platforms that were queried) ──
	const platformBreakdown: Record<
		string,
		{
			posts: number;
			views: number;
			likes: number;
			replies: number;
			shares: number;
			followers: number;
			engagementRate: number;
		} | null
	> = {};
	if (includeThreads && platformStats.threads.posts > 0) {
		const t = platformStats.threads;
		platformBreakdown.threads = {
			posts: t.posts,
			views: t.views,
			likes: t.likes,
			replies: t.replies,
			shares: t.shares,
			followers: t.followers,
			engagementRate:
				t.followers > 0 && t.posts > 0
					? Math.round(
							((t.likes + t.replies + t.shares) / (t.posts * t.followers)) *
								10000,
						) / 100
					: 0,
		};
	} else {
		platformBreakdown.threads = null;
	}

	if (includeIg && platformStats.instagram.posts > 0) {
		const ig = platformStats.instagram;
		platformBreakdown.instagram = {
			posts: ig.posts,
			views: ig.views,
			likes: ig.likes,
			replies: ig.replies,
			shares: ig.shares,
			followers: ig.followers,
			engagementRate:
				ig.followers > 0 && ig.posts > 0
					? Math.round(
							((ig.likes + ig.replies + ig.shares) /
								(ig.posts * ig.followers)) *
								10000,
						) / 100
					: 0,
		};
	} else {
		platformBreakdown.instagram = null;
	}

	return apiSuccess(res, {
		periodDays: days,
		platform: platformFilter ?? "all",
		totalPosts: exactPostCount,
		totalAccounts: accounts.length,
		threadsAccounts: accounts.filter((a) => a.platform === "threads").length,
		instagramAccounts: accounts.filter((a) => a.platform === "instagram")
			.length,

		aggregated: {
			followers: aggFollowers,
			views: aggViews,
			likes: aggLikes,
			replies: aggReplies,
			shares: aggShares,
			engagementRate,
		},

		platformBreakdown,

		topPost: topPost
			? {
					id: topPost.id,
					content: topPost.content?.substring(0, 120) ?? "",
					platform: topPost.platform,
					views: topPost.views_count ?? 0,
					likes: topPost.likes_count ?? 0,
					replies: topPost.replies_count ?? 0,
					publishedAt: topPost.published_at,
				}
			: null,

		bestHours,
		bestDays,
		rankings,
	});
}
