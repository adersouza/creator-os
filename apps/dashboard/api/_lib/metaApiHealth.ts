/**
 * Meta API Health Check (Circuit Breaker)
 *
 * Lightweight pre-flight check for cron jobs that dispatch Meta API calls.
 * Detects when multiple accounts have stale rate-limit tracking entries.
 * This is local bookkeeping drift, not proof that Meta is down, so the check
 * is diagnostic-only and fails open.
 *
 * Result is cached in Redis for 5 minutes to avoid repeated DB queries.
 */

import { logger } from "./logger.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "./privilegedDb.js";
import { getRedis } from "./redis.js";

/**
 * Returns true if the Meta API appears healthy for the given platform.
 *
 * Checks rate_limit_tracking (Threads) for ACTIVE accounts (posted in last
 * 24h) whose `day_window_start` rollover hasn't happened. This can happen
 * around day boundaries or when local counter rows drift, so it should never
 * freeze analytics dispatch. Per-account publish RPC rate limits remain the
 * hard protection against real overuse.
 *
 * Critical filter: `last_post_at > now() - 24h`. Without it, dormant
 * accounts (haven't posted in weeks) accumulate and trigger false alarms.
 * On 2026-05-06 this fired every 15min for 30+ days because 84 abandoned
 * Threads accounts had April-vintage day_window_start rows — all healthy
 * Meta API, just orphan bookkeeping.
 *
 * Instagram: ig_rate_limit_tracking has a different shape (daily_count +
 * daily_reset_at, no last_post_at). Skip the IG check until the table
 * normalizes — better to never alert than to false-alert.
 *
 * Failure-mode policy: any DB error → healthy=true so a transient hiccup
 * doesn't freeze dispatch. Skip cache on error so next call retries.
 */
export async function isMetaApiHealthy(
	platform: "threads" | "instagram",
): Promise<boolean> {
	// Instagram's ig_rate_limit_tracking schema (daily_count, daily_reset_at)
	// doesn't match the Threads check. Until that's normalized, skip — it has
	// been failing-open silently anyway.
	if (platform === "instagram") return true;

	const cacheKey = `meta-health:${platform}`;

	// Check Redis cache first (5-min TTL)
	try {
		const cached = await getRedis().get(cacheKey);
		if (cached !== null) return cached === "1";
	} catch {
		/* fall through to DB */
	}

	const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
	const oneDayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();

	const supabase = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.metaHealthCheck,
	);
	// biome-ignore lint/suspicious/noExplicitAny: rate_limit_tracking not in generated Supabase types
	const { data, error } = await (supabase as any)
		.from("rate_limit_tracking")
		.select("account_id")
		.gt("posts_today", 0)
		.lt("day_window_start", twoHoursAgo)
		.gt("last_post_at", oneDayAgo) // active accounts only — drop orphans
		.limit(3);

	if (error) {
		// Don't gate dispatch on a broken health check.
		logger.warn(
			`[meta-health] ${platform} health check query errored — failing open`,
			{
				platform,
				error: String(error?.message ?? error),
			},
		);
		return true;
	}

	const staleCount = data?.length ?? 0;
	if (staleCount >= 3) {
		logger.warn(
			`[meta-health] ${platform} rate-limit bookkeeping stale — failing open`,
			{
				platform,
				staleCount,
			},
		);
	}

	try {
		await getRedis().set(cacheKey, "1", { ex: 300 });
	} catch {
		/* best-effort cache write */
	}

	return true;
}
