// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Cohort Benchmarks Handler — anonymized peer percentile distributions.
 *
 * GET /api/analytics?action=cohort-benchmarks
 *   &platform=threads|instagram
 *   &follower_tier=0-1K|1K-5K|5K-10K|10K-50K|50K+
 *   &niche=<canonical>
 *   &metrics=engagement_rate,views_per_post,...    (or repeated ?metric=...)
 *
 * Returns one of four per-metric shapes (chosen from the aggregate's sample
 * sizes, which are guaranteed non-locked by the write-time k-anonymity filter):
 *
 *   { status: 'locked' }                               — caller isn't opted in
 *   { status: 'suppressed', reason, account_count, user_count }
 *   { status: 'median_only', p50, mean, account_count, user_count }
 *   { status: 'ok', p25, p50, p75, p90, mean, stddev, account_count, user_count }
 *
 * The locked decision is per-request (we check user_preferences on every call)
 * and never cached. The raw aggregate row is cached for 12h under a key that
 * does NOT include user_id, so the same row backs every opted-in reader.
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import {
	CANONICAL_NICHES,
	type CanonicalNiche,
	isCanonicalNiche,
	normalizeNiche,
} from "../../cohorts/niches.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { cached } from "../../redisCache.js";
import { getSupabaseAny } from "../../supabase.js";
import { z, zEnum } from "../../zodCompat.js";
import { enforceAnalyticsSubRateLimit } from "./rateLimit.js";

const READ_MIN_ACCOUNT_COUNT = 30;
const READ_MIN_USER_COUNT = 10;
const READ_MIN_ACCOUNT_COUNT_FULL = 50;
const READ_MIN_USER_COUNT_FULL = 15;
const CACHE_TTL_SEC = 12 * 60 * 60; // 12h — matches daily refresh cadence

const METRIC_NAMES = [
	"engagement_rate",
	"views_per_post",
	"follower_growth_7d",
	"reply_rate",
	"save_rate",
] as const;
type MetricName = (typeof METRIC_NAMES)[number];
const METRIC_NAME_SET: Set<string> = new Set(METRIC_NAMES);
type CohortPlatform = "threads" | "instagram";
type FollowerTier = "0-1K" | "1K-5K" | "5K-10K" | "10K-50K" | "50K+";
interface WorkspaceMetricSums {
	likes: number;
	replies: number;
	reposts: number;
	quotes: number;
	saves: number;
	reach: number;
	views: number;
	posts: number;
	followerGrowth: number;
}

const querySchema = z.object({
	action: z.string().optional(),
	platform: zEnum(["threads", "instagram"]),
	follower_tier: zEnum([
		"0-1K",
		"1K-5K",
		"5K-10K",
		"10K-50K",
		"50K+",
	]).optional(),
	niche: zEnum(CANONICAL_NICHES as unknown as [string, ...string[]]).optional(),
	metric: z.string().optional(),
	metrics: z.string().optional(),
});

interface CohortRow {
	metric_name: string;
	account_count: number;
	user_count: number;
	p25: number | null;
	p50: number | null;
	p75: number | null;
	p90: number | null;
	mean: number | null;
	stddev: number | null;
	snapshot_date: string;
}

type MetricResponse =
	| {
			status: "suppressed";
			reason: string;
			account_count: number;
			user_count: number;
	  }
	| {
			status: "workspace_baseline";
			p25: number | null;
			p50: number | null;
			p75: number | null;
			p90: number | null;
			mean: number | null;
			account_count: number;
			user_count: number;
			snapshot_date: string;
	  }
	| {
			status: "median_only";
			p50: number | null;
			mean: number | null;
			account_count: number;
			user_count: number;
			snapshot_date: string;
	  }
	| {
			status: "ok";
			p25: number | null;
			p50: number | null;
			p75: number | null;
			p90: number | null;
			mean: number | null;
			stddev: number | null;
			account_count: number;
			user_count: number;
			snapshot_date: string;
	  };

function parseMetricList(
	metric: string | undefined,
	metrics: string | undefined,
): MetricName[] {
	const raw = (metrics ?? metric ?? "")
		.split(",")
		.map((s) => s.trim())
		.filter(Boolean);
	if (raw.length === 0) return [...METRIC_NAMES];
	const filtered = raw.filter((m): m is MetricName => METRIC_NAME_SET.has(m));
	return filtered.length > 0 ? filtered : [...METRIC_NAMES];
}

function tierFromFollowers(count: number): FollowerTier {
	if (count < 1_000) return "0-1K";
	if (count < 5_000) return "1K-5K";
	if (count < 10_000) return "5K-10K";
	if (count < 50_000) return "10K-50K";
	return "50K+";
}

function median(values: number[]): number {
	if (values.length === 0) return 0;
	const sorted = [...values].sort((a, b) => a - b);
	const mid = Math.floor(sorted.length / 2);
	return sorted.length % 2 === 0
		? (sorted[mid - 1]! + sorted[mid]!) / 2
		: sorted[mid]!;
}

function percentileValue(values: number[], q: number): number | null {
	if (values.length === 0) return null;
	const sorted = [...values].sort((a, b) => a - b);
	const index = Math.min(
		sorted.length - 1,
		Math.max(0, Math.floor(q * sorted.length)),
	);
	return sorted[index]!;
}

function mean(values: number[]): number | null {
	if (values.length === 0) return null;
	return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function modeNiche(values: Array<string | null | undefined>): CanonicalNiche {
	const counts = new Map<CanonicalNiche, number>();
	for (const value of values) {
		const niche = isCanonicalNiche(value) ? value : normalizeNiche(value);
		counts.set(niche, (counts.get(niche) ?? 0) + 1);
	}
	let best: CanonicalNiche = "uncategorized";
	let bestCount = 0;
	for (const [niche, count] of counts) {
		if (niche !== "uncategorized" && count > bestCount) {
			best = niche;
			bestCount = count;
		}
	}
	return best;
}

async function resolveUserCohortAxes(
	db: ReturnType<typeof getSupabaseAny>,
	userId: string,
	platform: CohortPlatform,
	explicitTier: FollowerTier | undefined,
	explicitNiche: CanonicalNiche | undefined,
): Promise<{
	follower_tier: FollowerTier;
	niche: CanonicalNiche;
	resolved_from: string;
}> {
	if (explicitTier && explicitNiche) {
		return {
			follower_tier: explicitTier,
			niche: explicitNiche,
			resolved_from: "query",
		};
	}

	const table = platform === "threads" ? "accounts" : "instagram_accounts";
	const followerColumn =
		platform === "threads" ? "followers_count" : "follower_count";
	const { data: accountRows, error: accountError } = await db
		.from(table)
		.select(`id, ${followerColumn}, user_niche, inferred_niche, group_id`)
		.eq("user_id", userId);

	if (accountError) {
		logger.warn("[cohort-benchmarks] axis account lookup failed", {
			error: accountError.message,
			userId,
			platform,
		});
	}

	const rows = (accountRows ?? []) as Array<{
		id: string;
		followers_count?: number | null | undefined;
		follower_count?: number | null | undefined;
		user_niche: string | null;
		inferred_niche: string | null;
		group_id: string | null;
	}>;
	const followerCounts = rows.map((row) =>
		platform === "threads"
			? (row.followers_count ?? 0)
			: (row.follower_count ?? 0),
	);

	let resolvedNiche = explicitNiche;
	if (!resolvedNiche) {
		const direct = modeNiche(
			rows.map((row) => row.user_niche ?? row.inferred_niche),
		);
		resolvedNiche = direct;
	}

	if (!explicitNiche && resolvedNiche === "uncategorized") {
		const groupIds = Array.from(
			new Set(rows.map((row) => row.group_id).filter(Boolean)),
		) as string[];
		if (groupIds.length > 0) {
			const { data: groups, error: groupError } = await db
				.from("account_groups")
				.select("id, category")
				.in("id", groupIds)
				.eq("user_id", userId);
			if (groupError) {
				logger.warn("[cohort-benchmarks] axis group lookup failed", {
					error: groupError.message,
					userId,
				});
			}
			resolvedNiche = modeNiche(
				((groups ?? []) as Array<{ category: string | null }>).map(
					(row) => row.category,
				),
			);
		}
	}

	return {
		follower_tier: explicitTier ?? tierFromFollowers(median(followerCounts)),
		niche: resolvedNiche ?? "uncategorized",
		resolved_from: explicitTier || explicitNiche ? "query+user" : "user",
	};
}

async function fetchLatestSnapshot(
	platform: string,
	tier: string,
	niche: string,
): Promise<CohortRow[]> {
	const db = getSupabaseAny();
	// Pull the most recent snapshot_date that has ANY row for this (platform,
	// tier, niche); return every metric row from that date. Fronts the cohort
	// chart with a stable day, not a mix of yesterday's medians for one metric
	// and today's for another.
	const { data: latestDateRow, error: dateErr } = await db
		.from("cohort_benchmarks")
		.select("snapshot_date")
		.eq("platform", platform)
		.eq("follower_tier", tier)
		.eq("niche", niche)
		.order("snapshot_date", { ascending: false })
		.limit(1)
		.maybeSingle();
	if (dateErr) {
		logger.warn("[cohort-benchmarks] date lookup failed", {
			error: dateErr.message,
		});
		return [];
	}
	const latestDate = (latestDateRow as { snapshot_date: string } | null)
		?.snapshot_date;
	if (!latestDate) return [];

	const { data: rows, error: rowsErr } = await db
		.from("cohort_benchmarks")
		.select(
			"metric_name, account_count, user_count, p25, p50, p75, p90, mean, stddev, snapshot_date",
		)
		.eq("platform", platform)
		.eq("follower_tier", tier)
		.eq("niche", niche)
		.eq("snapshot_date", latestDate);
	if (rowsErr) {
		logger.warn("[cohort-benchmarks] rows fetch failed", {
			error: rowsErr.message,
		});
		return [];
	}
	return (rows as CohortRow[] | null) ?? [];
}

async function buildWorkspaceBaseline(
	db: ReturnType<typeof getSupabaseAny>,
	userId: string,
	platform: CohortPlatform,
	metricList: MetricName[],
): Promise<Record<string, MetricResponse>> {
	const table = platform === "threads" ? "accounts" : "instagram_accounts";
	const followerColumn =
		platform === "threads" ? "followers_count" : "follower_count";
	const { data: accounts } = await db
		.from(table)
		.select(`id, ${followerColumn}`)
		.eq("user_id", userId)
		.eq("is_active", true);
	const accountRows = (accounts ?? []) as Array<{
		id: string;
		followers_count?: number | null | undefined;
		follower_count?: number | null | undefined;
	}>;
	const accountIds = accountRows.map((row) => row.id);
	if (accountIds.length === 0) {
		return Object.fromEntries(
			metricList.map((metricName) => [
				metricName,
				{
					status: "suppressed" as const,
					reason: "no_workspace_accounts",
					account_count: 0,
					user_count: 1,
				},
			]),
		);
	}

	const cutoff = new Date(Date.now() - 7 * 86_400_000)
		.toISOString()
		.slice(0, 10);
	const { data: analytics } = await db
		.from("account_analytics")
		.select(
			"account_id, date, engagement_rate, follower_growth, posts_count, total_views, total_reach, total_likes, total_replies, total_reposts, total_quotes, total_saves",
		)
		.in("account_id", accountIds)
		.gte("date", cutoff);

	const byAccount = new Map<string, Array<Record<string, unknown>>>();
	for (const row of (analytics ?? []) as Array<Record<string, unknown>>) {
		const accountId = String(row.account_id ?? "");
		if (!accountId) continue;
		const rows = byAccount.get(accountId) ?? [];
		rows.push(row);
		byAccount.set(accountId, rows);
	}

	const valuesByMetric = new Map<MetricName, number[]>(
		metricList.map((metricName) => [metricName, []]),
	);
	for (const account of accountRows) {
		const rows = byAccount.get(account.id) ?? [];
		if (rows.length === 0) continue;
		const sums = rows.reduce<WorkspaceMetricSums>(
			(acc: WorkspaceMetricSums, row: Record<string, unknown>) => {
				acc.likes += Number(row.total_likes ?? 0);
				acc.replies += Number(row.total_replies ?? 0);
				acc.reposts += Number(row.total_reposts ?? 0);
				acc.quotes += Number(row.total_quotes ?? 0);
				acc.saves += Number(row.total_saves ?? 0);
				acc.reach += Number(row.total_reach ?? row.total_views ?? 0);
				acc.views += Number(row.total_views ?? row.total_reach ?? 0);
				acc.posts += Number(row.posts_count ?? 0);
				acc.followerGrowth += Number(row.follower_growth ?? 0);
				return acc;
			},
			{
				likes: 0,
				replies: 0,
				reposts: 0,
				quotes: 0,
				saves: 0,
				reach: 0,
				views: 0,
				posts: 0,
				followerGrowth: 0,
			} satisfies WorkspaceMetricSums,
		);
		const interactions =
			sums.likes + sums.replies + sums.reposts + sums.quotes + sums.saves;
		const add = (metricName: MetricName, value: number | null) => {
			if (value != null && Number.isFinite(value))
				valuesByMetric.get(metricName)?.push(value);
		};
		add(
			"engagement_rate",
			sums.reach > 0 ? (interactions / sums.reach) * 100 : null,
		);
		add("views_per_post", sums.posts > 0 ? sums.views / sums.posts : null);
		add("follower_growth_7d", sums.followerGrowth);
		add(
			"reply_rate",
			sums.reach > 0 ? (sums.replies / sums.reach) * 100 : null,
		);
		add("save_rate", sums.reach > 0 ? (sums.saves / sums.reach) * 100 : null);
	}

	const snapshotDate = new Date().toISOString().slice(0, 10);
	return Object.fromEntries(
		metricList.map((metricName) => {
			const values = valuesByMetric.get(metricName) ?? [];
			if (values.length === 0) {
				return [
					metricName,
					{
						status: "suppressed" as const,
						reason: "no_workspace_metric_rows",
						account_count: 0,
						user_count: 1,
					},
				];
			}
			return [
				metricName,
				{
					status: "workspace_baseline" as const,
					p25: percentileValue(values, 0.25),
					p50: percentileValue(values, 0.5),
					p75: percentileValue(values, 0.75),
					p90: percentileValue(values, 0.9),
					mean: mean(values),
					account_count: values.length,
					user_count: 1,
					snapshot_date: snapshotDate,
				},
			];
		}),
	);
}

function shapeMetric(row: CohortRow | undefined): MetricResponse {
	if (!row) {
		return {
			status: "suppressed",
			reason: "no_aggregate_row",
			account_count: 0,
			user_count: 0,
		};
	}
	const { account_count, user_count } = row;
	if (
		account_count < READ_MIN_ACCOUNT_COUNT ||
		user_count < READ_MIN_USER_COUNT
	) {
		logger.warn("[cohort-benchmarks] read-time suppression", {
			metric: row.metric_name,
			account_count,
			user_count,
			snapshot_date: row.snapshot_date,
		});
		return {
			status: "suppressed",
			reason: "insufficient_sample",
			account_count,
			user_count,
		};
	}
	if (
		account_count < READ_MIN_ACCOUNT_COUNT_FULL ||
		user_count < READ_MIN_USER_COUNT_FULL
	) {
		return {
			status: "median_only",
			p50: row.p50,
			mean: row.mean,
			account_count,
			user_count,
			snapshot_date: row.snapshot_date,
		};
	}
	return {
		status: "ok",
		p25: row.p25,
		p50: row.p50,
		p75: row.p75,
		p90: row.p90,
		mean: row.mean,
		stddev: row.stddev,
		account_count,
		user_count,
		snapshot_date: row.snapshot_date,
	};
}

export default withAuth(async (req, res, user) => {
	if (req.method !== "GET" && req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const allowed = await enforceAnalyticsSubRateLimit(res, {
		userId: user.id,
		action: "cohort-benchmarks",
		limit: 20,
	});
	if (!allowed) return;

	const parsed = querySchema.safeParse(req.query);
	if (!parsed.success) {
		return apiError(res, 400, "Invalid cohort parameters", {
			details: parsed.error.issues.map((i) => i.message).join("; "),
		});
	}
	const { platform, follower_tier, niche, metric, metrics } = parsed.data;
	const metricList = parseMetricList(metric, metrics);

	// Per-request opt-in check — never cached.
	const db = getSupabaseAny();
	const { data: pref, error: prefError } = await db
		.from("user_preferences")
		.select("data_contribution_opted_in")
		.eq("user_id", user.id)
		.maybeSingle();
	if (prefError) {
		logger.warn("[cohort-benchmarks] prefs lookup failed", {
			error: prefError.message,
			userId: user.id,
		});
	}
	const optedIn =
		(pref as { data_contribution_opted_in: boolean | null } | null)
			?.data_contribution_opted_in === true;
	if (!optedIn) {
		const axes = await resolveUserCohortAxes(
			db,
			user.id,
			platform,
			follower_tier,
			niche,
		);
		return apiSuccess(res, {
			platform,
			follower_tier: axes.follower_tier,
			niche: axes.niche,
			resolved_from: "workspace_baseline",
			metrics: await buildWorkspaceBaseline(db, user.id, platform, metricList),
		});
	}

	const axes = await resolveUserCohortAxes(
		db,
		user.id,
		platform,
		follower_tier,
		niche,
	);

	// Cache key: raw aggregate keyed on (platform, tier, niche). TTL covers the
	// 24h refresh cadence; no user-scoped component so hits are shared across
	// every opted-in reader for the same bucket.
	const cacheKey = `cohort:${platform}:${axes.follower_tier}:${axes.niche}`;
	let rows: CohortRow[];
	try {
		rows = await cached<CohortRow[]>(cacheKey, CACHE_TTL_SEC, () =>
			fetchLatestSnapshot(platform, axes.follower_tier, axes.niche),
		);
	} catch (err: unknown) {
		logger.error("[cohort-benchmarks] fetch failed", {
			error: err instanceof Error ? err.message : String(err),
		});
		return apiError(res, 500, "Internal server error");
	}

	const byMetric = new Map(rows.map((r) => [r.metric_name, r]));
	const out: Record<string, MetricResponse> = {};
	for (const m of metricList) {
		out[m] = shapeMetric(byMetric.get(m));
	}
	const hasPeerMetric = Object.values(out).some(
		(row) => row.status === "ok" || row.status === "median_only",
	);
	if (!hasPeerMetric) {
		const fallback = await buildWorkspaceBaseline(
			db,
			user.id,
			platform,
			metricList,
		);
		for (const m of metricList) {
			out[m] = fallback[m] ?? out[m]!;
		}
	}

	return apiSuccess(res, {
		platform,
		follower_tier: axes.follower_tier,
		niche: axes.niche,
		resolved_from: axes.resolved_from,
		metrics: out,
	});
});
