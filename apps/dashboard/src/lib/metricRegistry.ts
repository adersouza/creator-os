/**
 * Metric Registry — single source of truth for all analytics metrics.
 *
 * Adding a new metric: add one entry here.
 * Both getAnalyticsStats() and reconcileStats() loop this registry automatically —
 * no other file needs changing.
 */
import type { Platform } from "@/src/types/platform.js";

/**
 * How a metric's DB rows should be aggregated across a date range:
 *   "sum"      — cumulative counter: SUM all rows in the period (likes, views, etc.)
 *   "latest"   — point-in-time gauge: take the most recent row's value (followers)
 *   "snapshot" — Meta rolling-window metric: latest row IS the period value,
 *                do NOT subtract previous period for deltas (reach, impressions)
 */
export type MetricAggregation = "sum" | "latest" | "snapshot";

export interface MetricDef {
	/** DashboardStats / AnalyticsStats field key */
	readonly key: string;
	/** Column name in account_analytics */
	readonly dbColumn: string;
	/**
	 * Dot-notation path to the value on a raw post object.
	 * e.g. "performance.views" resolves post.performance.views
	 *      "igReach" resolves post.igReach
	 */
	readonly postPath: string;
	/** Which platforms produce this metric */
	readonly platforms: readonly Platform[];
	/** How to aggregate across date-range rows (default: "sum") */
	readonly aggregation?: MetricAggregation | undefined;
}

export const METRIC_REGISTRY: readonly MetricDef[] = [
	{
		key: "totalLikes",
		dbColumn: "total_likes",
		postPath: "performance.likes",
		platforms: ["threads", "instagram"],
		aggregation: "latest",
	},
	{
		key: "totalReplies",
		dbColumn: "total_replies",
		postPath: "performance.replies",
		platforms: ["threads", "instagram"],
		aggregation: "latest",
	},
	{
		key: "totalViews",
		dbColumn: "total_views",
		postPath: "performance.views",
		platforms: ["threads"],
		aggregation: "latest",
	},
	{
		key: "totalReposts",
		dbColumn: "total_reposts",
		postPath: "performance.reposts",
		platforms: ["threads"],
		aggregation: "latest",
	},
	{
		key: "totalQuotes",
		dbColumn: "total_quotes",
		postPath: "performance.quotes",
		platforms: ["threads"],
		aggregation: "latest",
	},
	{
		key: "totalIgReach",
		dbColumn: "total_reach",
		postPath: "igReach",
		platforms: ["instagram"],
		aggregation: "snapshot",
	},
	{
		key: "totalIgSaved",
		dbColumn: "total_saves",
		postPath: "igSaved",
		platforms: ["instagram"],
		aggregation: "latest",
	},
	{
		key: "totalIgShares",
		dbColumn: "total_shares",
		postPath: "igShares",
		platforms: ["instagram"],
		aggregation: "latest",
	},
	{
		key: "totalIgImpressions",
		dbColumn: "ig_impressions",
		postPath: "igImpressions",
		platforms: ["instagram"],
		aggregation: "snapshot",
	},
	{
		key: "totalFollowers",
		dbColumn: "followers_count",
		postPath: "",
		platforms: ["threads", "instagram"],
		aggregation: "latest",
	},
	{
		key: "totalClicks",
		dbColumn: "total_clicks",
		postPath: "",
		platforms: ["threads"],
		aggregation: "latest",
	},
	{
		key: "totalShares",
		dbColumn: "total_shares",
		postPath: "performance.shares",
		platforms: ["threads"],
		aggregation: "latest",
	},
	{
		key: "scheduledCount",
		dbColumn: "",
		postPath: "",
		platforms: ["threads", "instagram"],
	},
	{
		key: "igNewFollows",
		dbColumn: "ig_new_follows",
		postPath: "",
		platforms: ["instagram"],
		aggregation: "latest",
	},
	{
		key: "igUnfollows",
		dbColumn: "ig_unfollows",
		postPath: "",
		platforms: ["instagram"],
		aggregation: "latest",
	},
	{
		key: "igAccountsEngaged",
		dbColumn: "ig_accounts_engaged",
		postPath: "",
		platforms: ["instagram"],
		aggregation: "snapshot",
	},
	{
		key: "igProfileViews",
		dbColumn: "ig_profile_views",
		postPath: "",
		platforms: ["instagram"],
		aggregation: "snapshot",
	},
	{
		key: "igWebsiteClicks",
		dbColumn: "ig_website_clicks",
		postPath: "",
		platforms: ["instagram"],
		aggregation: "snapshot",
	},
	{
		key: "igTotalInteractions",
		dbColumn: "ig_total_interactions",
		postPath: "",
		platforms: ["instagram"],
		aggregation: "snapshot",
	},
	{
		key: "igNonFollowerReachPct",
		dbColumn: "ig_non_follower_reach_pct",
		postPath: "",
		platforms: ["instagram"],
		aggregation: "snapshot",
	},
];

/** Read a value from a post object by dot-notation path */
export function getPostValue(
	post: Record<string, unknown>,
	path: string,
): number {
	const parts = path.split(".");
	let val: unknown = post;
	for (const part of parts) {
		if (val == null || typeof val !== "object") return 0;
		val = (val as Record<string, unknown>)[part];
	}
	return Number(val) || 0;
}

/** All unique dbColumn values from the registry (excluding empty strings) */
export const ALL_DB_COLUMNS = [
	...new Set(METRIC_REGISTRY.map((m) => m.dbColumn).filter(Boolean)),
];

/** Build the account_analytics SELECT string for all extended metrics */
export const EXTENDED_DB_COLUMNS = ALL_DB_COLUMNS.filter(
	// exclude the 4 core columns already in account_daily_summary
	(col) =>
		!["total_likes", "total_replies", "total_views", "total_reposts"].includes(
			col,
		),
).join(", ");

/** Full SELECT clause for account_analytics queries (account_id + all metric cols + date) */
export const ANALYTICS_SELECT = ["account_id", ...ALL_DB_COLUMNS, "date"].join(
	", ",
);
