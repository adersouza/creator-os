/**
 * Meta API Configuration — Single Source of Truth
 *
 * All Meta Graph API knowledge lives here: endpoints, metrics, metric types,
 * batch support, API versions, base URLs per login type, and rate-limit handling.
 *
 * When Meta changes their API (deprecations, new required params, etc.),
 * update THIS file — not scattered hardcoded strings across the codebase.
 */

import { logger } from "./logger.js";

// ============================================================================
// API Version & Base URLs
// ============================================================================

export const META_API_VERSION = "v25.0";

/** Base URL per login type */
export const GRAPH_BASE_URL = {
	instagram: "https://graph.instagram.com",
	facebook: "https://graph.facebook.com",
} as const;

export function getGraphBaseUrl(loginType?: string): string {
	return loginType === "facebook"
		? GRAPH_BASE_URL.facebook
		: GRAPH_BASE_URL.instagram;
}

// ============================================================================
// Account Insights — metric_type split
// ============================================================================

/**
 * Account-level insights require metric_type parameter (since ~v18+).
 * Meta silently drops metrics if metric_type is wrong or missing.
 *
 * time_series: returns { values: [{ value: N }] }
 * total_value: returns { total_value: { value: N } }
 */
export const ACCOUNT_INSIGHTS = {
	timeSeries: {
		metricType: "time_series" as const,
		/** follower_count is day-only and not returned for accounts with <100 followers */
		metrics: ["reach", "follower_count"],
		/** Subset for non-day periods (follower_count is day-only) */
		metricsNonDay: ["reach"],
	},
	totalValue: {
		metricType: "total_value" as const,
		/** Instagram Business Login metrics */
		instagram: [
			"accounts_engaged",
			"total_interactions",
			"profile_links_taps",
			"reposts",
			"views",
		],
		/** Facebook Login metrics (profile_links_taps not available) */
		facebook: ["accounts_engaged", "total_interactions", "reposts", "views"],
	},
} as const;

/** Get time_series metrics string for a given period */
export function getTimeSeriesMetrics(period: string): string {
	return (
		period === "day"
			? ACCOUNT_INSIGHTS.timeSeries.metrics
			: ACCOUNT_INSIGHTS.timeSeries.metricsNonDay
	).join(",");
}

/** Get total_value metrics string for a given login type */
export function getTotalValueMetrics(loginType?: string): string {
	return (
		loginType === "facebook"
			? ACCOUNT_INSIGHTS.totalValue.facebook
			: ACCOUNT_INSIGHTS.totalValue.instagram
	).join(",");
}

// ============================================================================
// Post / Media Insights
// ============================================================================

/** Post-level insight metrics (used in both batch and individual calls) */
export const POST_INSIGHT_METRICS =
	"views,reach,likes,comments,shares,saved";

/** Story-level insight metrics */
export const STORY_INSIGHT_METRICS =
	"views,reach,replies,navigation,follows,shares,total_interactions";

/** Reel-specific insight metrics (superset of POST_INSIGHT_METRICS) */
export const REEL_INSIGHT_METRICS =
	"views,reach,likes,comments,shares,saved,ig_reels_avg_watch_time,reels_skip_rate,ig_reels_video_view_total_time";

/** Optional Reel metrics that can throw when the Reel is not crossposted to Facebook. */
export const REEL_CROSSPOST_INSIGHT_METRICS =
	"crossposted_views,facebook_views";

// ============================================================================
// Batch API
// ============================================================================

/**
 * The Meta Batch API only works on graph.facebook.com.
 * graph.instagram.com returns empty 200 responses for batch requests.
 * Instagram Business Login tokens are NOT compatible with batch endpoint.
 */
export const BATCH_API = {
	baseUrl: "https://graph.facebook.com",
	supportedLoginTypes: ["facebook"] as string[],
	/** Max items per batch request */
	maxBatchSize: 50,
} as const;

/** Check if batch API is available for a given login type */
export function isBatchSupported(loginType?: string): boolean {
	return BATCH_API.supportedLoginTypes.includes(loginType || "");
}

// ============================================================================
// Demographics
// ============================================================================

export const DEMOGRAPHIC_BREAKDOWNS = [
	"age",
	"gender",
	"country",
	"city",
] as const;

// ============================================================================
// Rate Limit — x-app-usage header backoff
// ============================================================================

/**
 * Thrown when x-app-usage indicates Meta API usage ≥ 95%.
 * Batch loops should catch this and abort early — remaining accounts are
 * picked up next run (sorted by last_synced_at ASC ensures fair rotation).
 */
export class MetaRateLimitError extends Error {
	constructor(
		message: string,
		public maxPct: number,
	) {
		super(message);
		this.name = "MetaRateLimitError";
	}
}

/**
 * Read Meta's x-app-usage response header and apply backpressure.
 * Call after every Graph API response — igFetch() does this automatically.
 *
 * Thresholds (per Meta documentation, percentages of the hourly token budget):
 *   ≥ 40%: log — informational, no delay
 *   ≥ 70%: exponential delay (1–30 s) before returning — active backpressure
 *   ≥ 95%: throw MetaRateLimitError — abort batch, retry next cycle
 *
 * Header JSON shape: { call_count: N, total_cputime: N, total_time: N }
 */
export async function checkMetaAppUsage(
	response: Response,
	context: string,
): Promise<void> {
	const raw = response.headers.get("x-app-usage");
	if (!raw) return;

	let usage: {
		call_count?: number | undefined;
		total_cputime?: number | undefined;
		total_time?: number | undefined;
	};
	try {
		usage = JSON.parse(raw) as typeof usage;
	} catch {
		return; // malformed header — ignore
	}

	const maxPct = Math.max(
		usage.call_count ?? 0,
		usage.total_cputime ?? 0,
		usage.total_time ?? 0,
	);

	// Cache latest reading in Redis so batch orchestrators can pre-check rate limit
	// state before starting a new batch (proactive, not just reactive).
	// Non-blocking: monitoring must never stall the API response path.
	if (maxPct > 0) {
		const { getRedis } = await import("./redis.js");
		getRedis()
			.set(
				"meta:app-usage:latest",
				JSON.stringify({ maxPct, ts: Date.now() }),
				{ ex: 300 },
			)
			.catch(() => {});
	}

	if (maxPct >= 95) {
		logger.error("Meta API at rate limit ceiling — aborting", {
			context,
			maxPct,
		});
		throw new MetaRateLimitError(
			`Meta API usage at ${maxPct}% — aborting to prevent IP ban`,
			maxPct,
		);
	}

	if (maxPct >= 70) {
		// 70% → 1s, 80% → 2s, 90% → 8s, 94% → 16s (capped at 30s)
		const cooldownMs = Math.min(
			1000 * 2 ** (Math.floor(maxPct / 10) - 7),
			30_000,
		);
		logger.warn("Meta API rate limit approaching — applying backpressure", {
			context,
			maxPct,
			cooldownMs,
		});
		await new Promise((r) => setTimeout(r, cooldownMs));
		return;
	}

	if (maxPct >= 40) {
		logger.info("Meta API rate limit usage elevated", { context, maxPct });
	}
}
