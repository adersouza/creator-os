// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Dashboard Load Cache
 *
 * Caches assembled dashboard data per account per day in Redis.
 * - Fresh (<15 min): return cached
 * - Stale (15-30 min): return cached + trigger background refresh
 * - Expired (>30 min): cache miss
 */

import { logger } from "./logger.js";
import { getRedis } from "./redis.js";

const DASH_TTL = 1800; // 30 minutes
const STALE_THRESHOLD = 15 * 60 * 1000; // 15 minutes in ms

interface CachedDashboard<T = unknown> {
	data: T;
	cachedAt: number; // epoch ms
}

function dashKey(accountId: string): string {
	const dateString = new Date().toISOString().split("T")[0]!;
	return `dash:${accountId}:${dateString}`;
}

/**
 * Get cached dashboard data for an account.
 * Returns { data, stale } if cached, or null if no cache.
 */
export async function getCachedDashboard<T = unknown>(
	accountId: string,
): Promise<{ data: T; stale: boolean } | null> {
	try {
		const redis = getRedis();
		const raw = await redis.get(dashKey(accountId));
		if (!raw) return null;

		let cached: CachedDashboard<T>;
		try {
			cached = (
				typeof raw === "string" ? JSON.parse(raw) : raw
			) as CachedDashboard<T>;
		} catch {
			return null;
		}
		const age = Date.now() - cached.cachedAt;
		const stale = age > STALE_THRESHOLD;

		return { data: cached.data, stale };
	} catch (err: unknown) {
		logger.error("dashboardCache get failed", {
			accountId,
			error: err instanceof Error ? err.message : String(err),
		});
		return null;
	}
}

/**
 * Store dashboard data in cache with 30 min TTL.
 */
export async function setCachedDashboard<T = unknown>(
	accountId: string,
	data: T,
): Promise<void> {
	try {
		const redis = getRedis();
		const entry: CachedDashboard<T> = { data, cachedAt: Date.now() };
		await redis.set(dashKey(accountId), JSON.stringify(entry), {
			ex: DASH_TTL,
		});
	} catch (err: unknown) {
		logger.error("dashboardCache set failed", {
			accountId,
			error: err instanceof Error ? err.message : String(err),
		});
	}
}

/**
 * Invalidate dashboard cache for an account (call after analytics refresh).
 */
export async function invalidateDashboard(accountId: string): Promise<void> {
	try {
		const redis = getRedis();
		await redis.del(dashKey(accountId));
	} catch (err: unknown) {
		logger.error("dashboardCache invalidate failed", {
			accountId,
			error: err instanceof Error ? err.message : String(err),
		});
	}
}
