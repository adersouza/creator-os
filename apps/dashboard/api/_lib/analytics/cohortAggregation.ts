// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Phase 2.5 — anonymized cohort aggregation.
 *
 * Reads today's account_analytics rows for opted-in users, buckets them by
 * (platform × follower_tier × niche), and writes percentile aggregates to
 * cohort_benchmarks. Gated by COHORT_AGGREGATION_ENABLED so the kill switch
 * stays flippable until the opt-in base produces non-trivial sample sizes.
 *
 * Privacy model (both dimensions required, enforced at write time; the read
 * handler re-checks the same thresholds as defense in depth):
 *   - median (p50)                    → account_count ≥ 30 AND user_count ≥ 10
 *   - full distribution (p25–p90)     → account_count ≥ 50 AND user_count ≥ 15
 *
 * Niche resolution priority:
 *   1. accounts.user_niche            (self-declared at opt-in — authoritative)
 *   2. accounts.inferred_niche        (AI fallback — mode of posts.content_category)
 *   3. account_groups.category        (normalized against canonical set)
 *   4. 'uncategorized'
 *
 * Only bucket aggregates are persisted. Account IDs and user IDs never leave
 * this module.
 */

import {
	CANONICAL_NICHES,
	type CanonicalNiche,
	isCanonicalNiche,
	normalizeNiche,
} from "../cohorts/niches.js";
import { logger } from "../logger.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../privilegedDb.js";
import { isTimeBudgetExceeded } from "./constants.js";

type Platform = "threads" | "instagram";
type FollowerTier = "0-1K" | "1K-5K" | "5K-10K" | "10K-50K" | "50K+";

// Write-time k-anonymity floor — matches the read handler's fallback-to-
// suppressed contract. Anything below this never reaches cohort_benchmarks.
const MIN_ACCOUNT_COUNT = 30;
const MIN_USER_COUNT = 10;
// Full-distribution threshold. Below this but above the median floor we
// still write the row — the read handler decides whether to return p25/p75
// or median-only based on the same numbers.
const MIN_ACCOUNT_COUNT_FULL = 50;
const MIN_USER_COUNT_FULL = 15;

const RETENTION_DAYS = 90;
const INFERRED_NICHE_DOMINANCE = 0.4; // 40% mode-share required
const INFERRED_NICHE_LOOKBACK_DAYS = 30;

type AnalyticsRow = {
	account_id: string;
	engagement_rate: number | null;
	follower_growth: number | null;
	followers_count: number | null;
	posts_count: number | null;
	total_views: number | null;
	total_replies: number | null;
	total_saves: number | null;
	total_reach: number | null;
};

type AccountMeta = {
	user_id: string;
	platform: Platform;
	niche: CanonicalNiche;
};

interface MetricDef {
	name: string;
	compute: (row: AnalyticsRow) => number | null;
	igOnly?: boolean | undefined;
}

// v1 metric set — stays narrow on purpose. Each compute() returns null when
// the underlying field is missing so a zero-row doesn't poison the bucket.
const METRICS: MetricDef[] = [
	{
		name: "engagement_rate",
		compute: (r) => (r.engagement_rate == null ? null : Number(r.engagement_rate)),
	},
	{
		name: "views_per_post",
		compute: (r) => {
			const views = r.total_views ?? 0;
			const posts = r.posts_count ?? 0;
			return posts > 0 ? views / posts : null;
		},
	},
	{
		name: "follower_growth_7d",
		compute: (r) => (r.follower_growth == null ? null : Number(r.follower_growth)),
	},
	{
		name: "reply_rate",
		compute: (r) => {
			const replies = r.total_replies ?? 0;
			const views = r.total_views ?? 0;
			return views > 0 ? (replies / views) * 100 : null;
		},
	},
	{
		name: "save_rate",
		igOnly: true,
		compute: (r) => {
			const saves = r.total_saves ?? 0;
			const reach = r.total_reach ?? 0;
			return reach > 0 ? (saves / reach) * 100 : null;
		},
	},
];

export function tierFromFollowers(count: number): FollowerTier {
	if (count < 1_000) return "0-1K";
	if (count < 5_000) return "1K-5K";
	if (count < 10_000) return "5K-10K";
	if (count < 50_000) return "10K-50K";
	return "50K+";
}

/** Linear-interpolated quantile on a pre-sorted ascending array. */
export function percentile(sorted: number[], q: number): number {
	if (sorted.length === 0) return 0;
	if (sorted.length === 1) return sorted[0]!;
	const pos = (sorted.length - 1) * q;
	const lo = Math.floor(pos);
	const hi = Math.ceil(pos);
	if (lo === hi) return sorted[lo]!;
	const frac = pos - lo;
	return sorted[lo]! * (1 - frac) + sorted[hi]! * frac;
}

function mean(values: number[]): number {
	if (values.length === 0) return 0;
	let sum = 0;
	for (const v of values) sum += v;
	return sum / values.length;
}

function stddev(values: number[], m: number): number {
	if (values.length < 2) return 0;
	let sqsum = 0;
	for (const v of values) sqsum += (v - m) ** 2;
	return Math.sqrt(sqsum / (values.length - 1));
}

function round4(n: number): number {
	return Math.round(n * 10_000) / 10_000;
}

export async function runPhase2_5_CohortAggregation(
	startTime: number,
): Promise<number> {
	if (process.env.COHORT_AGGREGATION_ENABLED !== "1") {
		logger.info("[cohort-agg] disabled — COHORT_AGGREGATION_ENABLED != '1'");
		return 0;
	}
	if (isTimeBudgetExceeded(startTime)) {
		logger.warn("[cohort-agg] time budget exceeded before start — skipping");
		return 0;
	}

	const supabase = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.cohortAggregation,
	);
	const today = new Date().toISOString().split("T")[0]!;

	// 1. Opted-in user pool
	const { data: optedInRows, error: optedInError } = await supabase
		.from("user_preferences")
		.select("user_id")
		.eq("data_contribution_opted_in", true);
	if (optedInError) {
		logger.error("[cohort-agg] opt-in query failed", {
			error: optedInError.message,
		});
		return 0;
	}
	const userIds = Array.from(
		new Set((optedInRows ?? []).map((r: { user_id: string }) => r.user_id)),
	);
	if (userIds.length === 0) {
		logger.info("[cohort-agg] no opted-in users — skipping");
		return 0;
	}

	// 2. Refresh inferred_niche for accounts without user_niche.
	//    Best-effort — failures don't block the aggregation.
	if (!isTimeBudgetExceeded(startTime)) {
		try {
			await refreshInferredNiche(supabase, userIds);
		} catch (err: unknown) {
			logger.warn("[cohort-agg] inferred_niche refresh failed", {
				error: err instanceof Error ? err.message : String(err),
			});
		}
	}

	// 3. Load accounts (threads + IG) with their resolved niche.
	const accountMeta = await loadAccountsWithNiche(supabase, userIds);
	if (accountMeta.size === 0) {
		logger.info("[cohort-agg] opted-in users have no accounts — skipping");
		return 0;
	}

	if (isTimeBudgetExceeded(startTime)) {
		logger.warn("[cohort-agg] time budget exceeded after account load");
		return 0;
	}

	// 4. Today's analytics for those accounts.
	const accountIds = Array.from(accountMeta.keys());
	const analyticsRows: AnalyticsRow[] = [];
	const CHUNK = 500;
	for (let i = 0; i < accountIds.length; i += CHUNK) {
		if (isTimeBudgetExceeded(startTime)) break;
		const chunk = accountIds.slice(i, i + CHUNK);
		const { data, error } = await supabase
			.from("account_analytics")
			.select(
				"account_id, engagement_rate, follower_growth, followers_count, posts_count, total_views, total_replies, total_saves, total_reach",
			)
			.in("account_id", chunk)
			.eq("date", today);
		if (error) {
			logger.warn("[cohort-agg] analytics chunk fetch failed", {
				error: error.message,
				chunkIndex: i,
			});
			continue;
		}
		analyticsRows.push(...((data ?? []) as AnalyticsRow[]));
	}

	if (analyticsRows.length === 0) {
		logger.info("[cohort-agg] no analytics rows for today — skipping", {
			today,
		});
		return 0;
	}

	// 5. Bucket: key = platform:tier:niche, value = per-metric sample set.
	type MetricAcc = {
		values: number[];
		users: Set<string>;
		accounts: Set<string>;
	};
	type Bucket = {
		platform: Platform;
		tier: FollowerTier;
		niche: CanonicalNiche;
		metrics: Map<string, MetricAcc>;
	};
	const buckets = new Map<string, Bucket>();

	for (const row of analyticsRows) {
		const meta = accountMeta.get(row.account_id);
		if (!meta) continue;
		const tier = tierFromFollowers(row.followers_count ?? 0);
		const key = `${meta.platform}:${tier}:${meta.niche}`;
		let bucket = buckets.get(key);
		if (!bucket) {
			bucket = {
				platform: meta.platform,
				tier,
				niche: meta.niche,
				metrics: new Map(),
			};
			buckets.set(key, bucket);
		}
		for (const metric of METRICS) {
			if (metric.igOnly && meta.platform !== "instagram") continue;
			const val = metric.compute(row);
			if (val == null || !Number.isFinite(val)) continue;
			let acc = bucket.metrics.get(metric.name);
			if (!acc) {
				acc = { values: [], users: new Set(), accounts: new Set() };
				bucket.metrics.set(metric.name, acc);
			}
			acc.values.push(val);
			acc.users.add(meta.user_id);
			acc.accounts.add(row.account_id);
		}
	}

	// 6. Apply k-anonymity and build upsert payload.
	//    Rows that clear the median floor but not the full-distribution floor
	//    are still written with p25/p75/p90 = null so the read handler can
	//    decide median-only vs full based on the same numbers.
	const inserts: Array<{
		snapshot_date: string;
		platform: Platform;
		follower_tier: FollowerTier;
		niche: CanonicalNiche;
		metric_name: string;
		account_count: number;
		user_count: number;
		p25: number | null;
		p50: number | null;
		p75: number | null;
		p90: number | null;
		mean: number;
		stddev: number;
	}> = [];

	let suppressedBucketCells = 0;
	for (const bucket of buckets.values()) {
		for (const [metricName, acc] of bucket.metrics) {
			const account_count = acc.accounts.size;
			const user_count = acc.users.size;
			if (account_count < MIN_ACCOUNT_COUNT || user_count < MIN_USER_COUNT) {
				suppressedBucketCells += 1;
				continue;
			}
			const sorted = [...acc.values].sort((a, b) => a - b);
			const m = mean(sorted);
			const sd = stddev(sorted, m);
			const fullDist =
				account_count >= MIN_ACCOUNT_COUNT_FULL &&
				user_count >= MIN_USER_COUNT_FULL;
			inserts.push({
				snapshot_date: today!,
				platform: bucket.platform,
				follower_tier: bucket.tier,
				niche: bucket.niche,
				metric_name: metricName,
				account_count,
				user_count,
				p25: fullDist ? round4(percentile(sorted, 0.25)) : null,
				p50: round4(percentile(sorted, 0.5)),
				p75: fullDist ? round4(percentile(sorted, 0.75)) : null,
				p90: fullDist ? round4(percentile(sorted, 0.9)) : null,
				mean: round4(m),
				stddev: round4(sd),
			});
		}
	}

	if (inserts.length > 0) {
		const { error } = await supabase
			.from("cohort_benchmarks")
			.upsert(inserts, {
				onConflict: "snapshot_date,platform,follower_tier,niche,metric_name",
			});
		if (error) {
			logger.error("[cohort-agg] upsert failed", { error: error.message });
			return 0;
		}
	}

	// 7. Prune old snapshots. Don't block on failure.
	try {
		const cutoff = new Date(Date.now() - RETENTION_DAYS * 86_400_000)
			.toISOString()
			.split("T")[0]!;
		await supabase
			.from("cohort_benchmarks")
			.delete()
			.lt("snapshot_date", cutoff);
	} catch (err: unknown) {
		logger.warn("[cohort-agg] prune failed", {
			error: err instanceof Error ? err.message : String(err),
		});
	}

	logger.info("[cohort-agg] completed", {
		optedInUsers: userIds.length,
		accountsSeen: accountMeta.size,
		analyticsRows: analyticsRows.length,
		bucketsSeen: buckets.size,
		rowsWritten: inserts.length,
		bucketCellsSuppressed: suppressedBucketCells,
	});

	return inserts.length;
}

/**
 * Refresh accounts.inferred_niche for opted-in accounts that lack user_niche.
 * Mode calc over the last 30 days of posts.content_category, requires ≥40%
 * share to commit — lower dominance leaves inferred_niche NULL so the
 * resolver falls through to account_groups.category.
 */
async function refreshInferredNiche(
	supabase: ReturnType<typeof getPrivilegedSupabaseAny>,
	userIds: string[],
): Promise<void> {
	const sinceIso = new Date(
		Date.now() - INFERRED_NICHE_LOOKBACK_DAYS * 86_400_000,
	).toISOString();

	// Only look at accounts that (a) belong to an opted-in user and (b) have
	// no self-declared niche. A filled user_niche is authoritative and skips
	// the inference write entirely.
	const [threadsRes, igRes] = await Promise.all([
		supabase
			.from("accounts")
			.select("id")
			.in("user_id", userIds)
			.is("user_niche", null),
		supabase
			.from("instagram_accounts")
			.select("id")
			.in("user_id", userIds)
			.is("user_niche", null),
	]);

	const threadsIds = ((threadsRes.data as Array<{ id: string }> | null) ?? []).map(
		(r) => r.id,
	);
	const igIds = ((igRes.data as Array<{ id: string }> | null) ?? []).map(
		(r) => r.id,
	);
	const candidateIds = [...threadsIds, ...igIds];
	if (candidateIds.length === 0) return;

	const { data: postRows, error } = await supabase
		.from("posts")
		.select("account_id, content_category")
		.in("account_id", candidateIds)
		.not("content_category", "is", null)
		.gte("published_at", sinceIso);
	if (error || !postRows) return;

	const modePerAccount = new Map<string, CanonicalNiche | null>();
	const counts = new Map<string, Map<CanonicalNiche, number>>();
	for (const row of postRows as Array<{
		account_id: string;
		content_category: string | null;
	}>) {
		const niche = normalizeNiche(row.content_category);
		let bucket = counts.get(row.account_id);
		if (!bucket) {
			bucket = new Map();
			counts.set(row.account_id, bucket);
		}
		bucket.set(niche, (bucket.get(niche) ?? 0) + 1);
	}
	for (const [accountId, bucket] of counts) {
		let total = 0;
		let topNiche: CanonicalNiche | null = null;
		let topCount = 0;
		for (const [niche, count] of bucket) {
			total += count;
			if (count > topCount) {
				topCount = count;
				topNiche = niche;
			}
		}
		const dominant =
			topNiche && topCount / total >= INFERRED_NICHE_DOMINANCE ? topNiche : null;
		modePerAccount.set(accountId, dominant);
	}

	const threadsIdSet = new Set(threadsIds);
	for (const [accountId, niche] of modePerAccount) {
		if (niche === null) continue;
		const table = threadsIdSet.has(accountId) ? "accounts" : "instagram_accounts";
		await supabase
			.from(table)
			.update({ inferred_niche: niche })
			.eq("id", accountId);
	}
}

/**
 * Resolve niche for every opted-in account on both platforms.
 * Returns a map keyed on account_id with { user_id, platform, niche }.
 */
async function loadAccountsWithNiche(
	supabase: ReturnType<typeof getPrivilegedSupabaseAny>,
	userIds: string[],
): Promise<Map<string, AccountMeta>> {
	const [threadsRes, igRes, groupsRes] = await Promise.all([
		supabase
			.from("accounts")
			.select("id, user_id, user_niche, inferred_niche, group_id")
			.in("user_id", userIds),
		supabase
			.from("instagram_accounts")
			.select("id, user_id, user_niche, inferred_niche, group_id")
			.in("user_id", userIds),
		supabase
			.from("account_groups")
			.select("id, category")
			.in("user_id", userIds),
	]);

	const groupCategory = new Map<string, string | null>();
	for (const g of (groupsRes.data as Array<{
		id: string;
		category: string | null;
	}> | null) ?? []) {
		groupCategory.set(g.id, g.category);
	}

	const map = new Map<string, AccountMeta>();
	const resolve = (
		user_niche: string | null,
		inferred_niche: string | null,
		group_id: string | null,
	): CanonicalNiche => {
		if (isCanonicalNiche(user_niche)) return user_niche;
		if (isCanonicalNiche(inferred_niche)) return inferred_niche;
		const groupCat = group_id ? groupCategory.get(group_id) ?? null : null;
		if (groupCat) {
			const normalized = normalizeNiche(groupCat);
			if (normalized !== "uncategorized") return normalized;
		}
		return "uncategorized";
	};

	type AccountRow = {
		id: string;
		user_id: string;
		user_niche: string | null;
		inferred_niche: string | null;
		group_id: string | null;
	};
	for (const a of (threadsRes.data as AccountRow[] | null) ?? []) {
		map.set(a.id, {
			user_id: a.user_id,
			platform: "threads",
			niche: resolve(a.user_niche, a.inferred_niche, a.group_id),
		});
	}
	for (const a of (igRes.data as AccountRow[] | null) ?? []) {
		map.set(a.id, {
			user_id: a.user_id,
			platform: "instagram",
			niche: resolve(a.user_niche, a.inferred_niche, a.group_id),
		});
	}
	return map;
}

// Re-export for test visibility.
export const __test__ = {
	METRICS,
	CANONICAL_NICHES,
	MIN_ACCOUNT_COUNT,
	MIN_USER_COUNT,
	MIN_ACCOUNT_COUNT_FULL,
	MIN_USER_COUNT_FULL,
};
