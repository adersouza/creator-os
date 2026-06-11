/**
 * Redis Cache Utilities
 *
 * Server-side caching for expensive Supabase queries.
 * Uses Upstash Redis with configurable TTL.
 *
 * Usage:
 *   const data = await cached("analytics:user123:30d", 300, async () => {
 *     // expensive query
 *     return result;
 *   });
 */

import { logger } from "./logger.js";
import { getRedis } from "./redis.js";

const CACHE_PREFIX = "cache:";

/**
 * Get a cached value or compute and store it.
 *
 * @param key    Cache key (will be prefixed with "cache:")
 * @param ttlSec TTL in seconds (e.g., 300 = 5 minutes)
 * @param fn     Async function to compute the value if not cached
 * @returns      The cached or computed value
 */
export async function cached<T>(
	key: string,
	ttlSec: number,
	fn: () => Promise<T>,
): Promise<T> {
	try {
		const redis = getRedis();
		const cacheKey = `${CACHE_PREFIX}${key}`;

		// Try to get from cache
		const cachedValue = await redis.get(cacheKey);
		if (cachedValue !== null && cachedValue !== undefined) {
			// Upstash returns parsed JSON automatically
			return cachedValue as T;
		}

		// Cache miss — compute the value
		const result = await fn();

		// Store in Redis with TTL (fire-and-forget, don't block on cache write)
		redis.set(cacheKey, JSON.stringify(result), { ex: ttlSec }).catch((err) => {
			logger.error("Cache set failed", {
				cacheKey,
				error: String(err instanceof Error ? err.message : err),
			});
		});

		return result;
	} catch (err: unknown) {
		// If Redis is down, fall through to direct computation
		logger.error("Redis error, falling through to direct computation", {
			key,
			error: String(err instanceof Error ? err.message : err),
		});
		return fn();
	}
}

/**
 * Invalidate a specific cache key.
 */
export async function invalidateCache(key: string): Promise<void> {
	try {
		const redis = getRedis();
		await redis.del(`${CACHE_PREFIX}${key}`);
	} catch (err: unknown) {
		logger.error("Cache invalidation failed", {
			key,
			error: String(err instanceof Error ? err.message : err),
		});
	}
}

/**
 * Invalidate all cache keys matching a pattern.
 * Uses Redis SCAN to find and delete matching keys.
 *
 * @param pattern  Glob pattern (e.g., "analytics:user123:*")
 */
export async function invalidateCachePattern(pattern: string): Promise<void> {
	try {
		const redis = getRedis();
		const fullPattern = `${CACHE_PREFIX}${pattern}`;

		// Upstash Redis scan
		let cursor: number | string = 0;
		do {
			const result: [string | number, string[]] = await redis.scan(
				cursor as number,
				{ match: fullPattern, count: 100 },
			);
			cursor = result[0];
			const keys = result[1];
			if (keys.length > 0) {
				await Promise.all(
					keys.map((k: string | number) => redis.del(k as string)),
				);
			}
		} while (cursor !== 0);
	} catch (err: unknown) {
		logger.error("Cache pattern invalidation failed", {
			pattern,
			error: String(err instanceof Error ? err.message : err),
		});
	}
}

// ============================================================================
// Stale-While-Error Cache
// ============================================================================

/**
 * Cache with stale fallback — returns stale data if the upstream function fails.
 *
 * Stores two copies:
 *   1. Primary cache key with short TTL (ttlSec)
 *   2. Stale cache key with long TTL (staleTtlSec)
 *
 * On cache miss:
 *   - Calls fn() to compute fresh data
 *   - On success: stores both primary and stale, returns { data, stale: false }
 *   - On failure: tries to return stale data with { data, stale: true }
 *   - If no stale data: re-throws the original error
 *
 * @param key         Cache key
 * @param ttlSec      Primary TTL in seconds
 * @param staleTtlSec Stale TTL in seconds (typically 24h+)
 * @param fn          Async function to compute the value
 */
export async function cachedWithStale<T>(
	key: string,
	ttlSec: number,
	staleTtlSec: number,
	fn: () => Promise<T>,
): Promise<{ data: T; stale: boolean }> {
	try {
		const redis = getRedis();
		const cacheKey = `${CACHE_PREFIX}${key}`;
		const staleKey = `${CACHE_PREFIX}stale:${key}`;

		// Try primary cache
		const cachedValue = await redis.get(cacheKey);
		if (cachedValue !== null && cachedValue !== undefined) {
			return { data: cachedValue as T, stale: false };
		}

		// Cache miss — try to compute fresh data
		try {
			const result = await fn();

			// Store primary + stale (fire-and-forget)
			const serialized = JSON.stringify(result);
			redis.set(cacheKey, serialized, { ex: ttlSec }).catch(() => {});
			redis.set(staleKey, serialized, { ex: staleTtlSec }).catch(() => {});

			return { data: result, stale: false };
		} catch (upstreamError) {
			// Upstream failed — try stale cache
			const staleValue = await redis.get(staleKey);
			if (staleValue !== null && staleValue !== undefined) {
				logger.warn("Serving stale data due to upstream failure", { key });
				return { data: staleValue as T, stale: true };
			}
			// No stale data available — re-throw
			throw upstreamError;
		}
	} catch (err: unknown) {
		// Redis completely down — try direct computation
		logger.error("Redis error in cachedWithStale", {
			key,
			error: String(err instanceof Error ? err.message : err),
		});
		const result = await fn();
		return { data: result, stale: false };
	}
}

// ============================================================================
// Pre-built Cache Keys
// ============================================================================

/** Cache key for account analytics aggregate */
export function analyticsKey(accountId: string, period: string): string {
	return `analytics:${accountId}:${period}`;
}

/** Cache key for post metrics */
export function postMetricsKey(postId: string): string {
	return `post-metrics:${postId}`;
}

/** Cache key for health dashboard data */
export function healthKey(): string {
	return "admin:health";
}

/** Cache key for DLQ summary */
export function dlqKey(): string {
	return "admin:dlq";
}

/** Cache key for best posting times */
export function bestTimesKey(accountId: string): string {
	return `best-times:${accountId}`;
}

/** Cache key for anomaly alerts */
export function alertsKey(accountId: string): string {
	return `alerts:${accountId}`;
}

/** Cache key for group-level analytics aggregate */
export function groupAnalyticsKey(
	userId: string,
	groupId: string,
	days: number,
): string {
	return `group-analytics:${userId}:${groupId}:${days}d`;
}
