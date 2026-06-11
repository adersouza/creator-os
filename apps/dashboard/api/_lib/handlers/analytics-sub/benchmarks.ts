// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Benchmarks Handler — Cross-User Tier Benchmarks
 * GET /api/benchmarks?accountId=...
 * Merged from api/benchmarks.ts
 */

import { z } from "../../zodCompat.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { cached } from "../../redisCache.js";
import { getSupabase } from "../../supabase.js";
import { verifyAnyAccountOwnership } from "../helpers/verifyOwnership.js";

interface UserPreferenceRow {
	user_id: string;
}

interface AccountIdRow {
	id: string;
}

interface AnalyticsRow {
	account_id: string;
	followers_count?: number | null | undefined;
	engagement_rate?: number | null | undefined;
	posts_count?: number | null | undefined;
	follower_growth?: number | null | undefined;
	total_views?: number | null | undefined;
	date?: string | null | undefined;
}

const db = () => getSupabase();

const querySchema = z.object({
	accountId: z.string().optional(),
});

const TIERS = [
	{ name: "0-1K", min: 0, max: 1000 },
	{ name: "1K-5K", min: 1000, max: 5000 },
	{ name: "5K-10K", min: 5000, max: 10000 },
	{ name: "10K-50K", min: 10000, max: 50000 },
	{ name: "50K+", min: 50000, max: Infinity },
] as const;

const MIN_ACCOUNTS_PER_TIER = 30;
const CACHE_TTL = 86400;

interface TierBenchmark {
	tier: string;
	accountCount: number;
	avgEngagementRate: number;
	avgPostsPerWeek: number;
	avgFollowerGrowthRate: number;
	avgViewsPerPost: number;
}

async function computeBenchmarks(): Promise<TierBenchmark[]> {
	const sevenDaysAgo = new Date();
	sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);

	const [optedInResult, _] = await Promise.all([
		db()
			.from("user_preferences")
			.select("user_id")
			.eq("data_contribution_opted_in", true),
		Promise.resolve(),
	]);

	const optedInUserIds = (
		(optedInResult.data as UserPreferenceRow[]) || []
	).map((u: UserPreferenceRow) => u.user_id);
	if (optedInUserIds.length === 0) return [];

	const [accountsResult, analyticsResult] = await Promise.all([
		db().from("accounts").select("id").in("user_id", optedInUserIds),
		db()
			.from("account_analytics")
			.select(
				"account_id, followers_count, engagement_rate, posts_count, follower_growth, total_views, date",
			)
			.gte("date", sevenDaysAgo.toISOString().split("T")[0]!)
			.order("date", { ascending: false }),
	]);

	const optedInAccountIds = new Set(
		((accountsResult.data as AccountIdRow[]) || []).map(
			(a: AccountIdRow) => a.id,
		),
	);
	if (optedInAccountIds.size === 0) return [];

	const analytics = analyticsResult.data;
	const error = analyticsResult.error;

	if (error || !analytics) {
		logger.error("Failed to fetch analytics for benchmarks", {
			error: error?.message,
		});
		return [];
	}

	const latestByAccount = new Map<string, AnalyticsRow>();
	for (const row of analytics as AnalyticsRow[]) {
		if (
			optedInAccountIds.has(row.account_id) &&
			!latestByAccount.has(row.account_id)
		) {
			latestByAccount.set(row.account_id, row);
		}
	}

	const results: TierBenchmark[] = [];

	for (const tier of TIERS) {
		const tierAccounts = Array.from(latestByAccount.values()).filter(
			(a: AnalyticsRow) => {
				const followers = a.followers_count ?? 0;
				return followers >= tier.min && followers < tier.max;
			},
		);

		if (tierAccounts.length < MIN_ACCOUNTS_PER_TIER) {
			results.push({
				tier: tier.name,
				accountCount: 0,
				avgEngagementRate: 0,
				avgPostsPerWeek: 0,
				avgFollowerGrowthRate: 0,
				avgViewsPerPost: 0,
			});
			continue;
		}

		const count = tierAccounts.length;
		const sumEngagement = tierAccounts.reduce(
			(s: number, a: AnalyticsRow) => s + (a.engagement_rate ?? 0),
			0,
		);
		const sumPostsPerWeek = tierAccounts.reduce(
			(s: number, a: AnalyticsRow) => s + (a.posts_count ?? 0),
			0,
		);
		const sumGrowthRate = tierAccounts.reduce((s: number, a: AnalyticsRow) => {
			const followers = a.followers_count ?? 1;
			const growth = a.follower_growth ?? 0;
			return s + (growth / followers) * 100;
		}, 0);
		const sumViewsPerPost = tierAccounts.reduce(
			(s: number, a: AnalyticsRow) => {
				const views = a.total_views ?? 0;
				const posts = a.posts_count ?? 1;
				return s + (posts > 0 ? views / posts : 0);
			},
			0,
		);

		results.push({
			tier: tier.name,
			accountCount: count,
			avgEngagementRate: Math.round((sumEngagement / count) * 100) / 100,
			avgPostsPerWeek: Math.round((sumPostsPerWeek / count) * 7 * 100) / 100,
			avgFollowerGrowthRate: Math.round((sumGrowthRate / count) * 100) / 100,
			avgViewsPerPost: Math.round(sumViewsPerPost / count),
		});
	}

	return results;
}

export default withAuth(async (req, res, user) => {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	try {
		const { accountId } = querySchema.parse(req.query);
		if (accountId) {
			const owned = await verifyAnyAccountOwnership(res, accountId, user.id);
			if (!owned) return;
		}

		const { data: pref, error: prefError } = await db()
			.from("user_preferences")
			.select("data_contribution_opted_in")
			.eq("user_id", user.id)
			.maybeSingle();
		if (prefError) {
			logger.warn("Benchmark preference lookup failed", {
				userId: user.id,
				error: prefError.message,
			});
		}
		const optedIn =
			(pref as { data_contribution_opted_in?: boolean | null } | null)
				?.data_contribution_opted_in === true;

		const { data: accounts } = await db()
			.from("account_analytics")
			.select("followers_count")
			.eq("account_id", accountId || "")
			.order("date", { ascending: false })
			.limit(1);

		const userFollowers =
			(accounts as AnalyticsRow[] | null)?.[0]?.followers_count ?? 0;
		const userTier =
			TIERS.find((t) => userFollowers >= t.min && userFollowers < t.max)
				?.name ?? "0-1K";

		if (!optedIn) {
			return apiSuccess(res, {
				status: "locked",
				benchmarks: [],
				userTier,
				userFollowers,
			});
		}

		const benchmarks = await cached<TierBenchmark[]>(
			"benchmarks:all",
			CACHE_TTL,
			computeBenchmarks,
		);

		return apiSuccess(res, {
			benchmarks,
			userTier,
			userFollowers,
		});
	} catch (error: unknown) {
		logger.error("Benchmarks API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
