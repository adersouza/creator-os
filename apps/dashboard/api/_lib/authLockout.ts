// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Auth Attempt Lockout
 *
 * Tracks failed authentication attempts in Redis and temporarily locks out
 * identifiers (IP or API key prefix) after too many failures.
 *
 * Thresholds:
 *   - 10 failed attempts in 15 minutes → locked for 15 minutes
 *   - 20 failed attempts in 15 minutes → locked for 60 minutes
 *   - 30+ failed attempts → locked for 4 hours
 *
 * Redis keys (auto-expire):
 *   auth-lockout:fail:<identifier>  — failure counter (15min TTL)
 *   auth-lockout:lock:<identifier>  — lock flag with TTL
 */

import { logger } from "./logger.js";

const FAIL_PREFIX = "auth-lockout:fail:";
const LOCK_PREFIX = "auth-lockout:lock:";
const WINDOW_SEC = 900; // 15 minutes
const MAX_MEMORY_ENTRIES = 10000;

const LOCKOUT_TIERS = [
	{ threshold: 30, durationSec: 14400 }, // 4 hours
	{ threshold: 20, durationSec: 3600 }, // 1 hour
	{ threshold: 10, durationSec: 900 }, // 15 minutes
] as const;
const REDIS_TIMEOUT_MS = 800;

type MemoryFailureState = {
	count: number;
	windowExpiresAt: number;
};

const memoryFailures = new Map<string, MemoryFailureState>();
const memoryLocks = new Map<string, number>();

function withTimeout<T>(
	promise: Promise<T>,
	label: string,
	timeoutMs = REDIS_TIMEOUT_MS,
): Promise<T> {
	return new Promise((resolve, reject) => {
		const timeout = setTimeout(() => {
			reject(new Error(`${label} timed out after ${timeoutMs}ms`));
		}, timeoutMs);
		promise.then(
			(value) => {
				clearTimeout(timeout);
				resolve(value);
			},
			(error) => {
				clearTimeout(timeout);
				reject(error);
			},
		);
	});
}

function pruneExpiredEntries(now = Date.now()) {
	for (const [identifier, expiresAt] of memoryLocks.entries()) {
		if (expiresAt <= now) memoryLocks.delete(identifier);
	}

	for (const [identifier, state] of memoryFailures.entries()) {
		if (state.windowExpiresAt <= now) memoryFailures.delete(identifier);
	}

	for (const [map, label] of [
		[memoryLocks, "locks"],
		[memoryFailures, "failures"],
	] as const) {
		if (map.size > MAX_MEMORY_ENTRIES) {
			let toDrop = map.size - MAX_MEMORY_ENTRIES;
			for (const key of map.keys()) {
				map.delete(key);
				if (--toDrop <= 0) break;
			}
			logger.warn(`[authLockout] Pruned overflow in memory ${label}`, {
				remaining: map.size,
			});
		}
	}
}

function getMemoryLockout(
	identifier: string,
): { locked: true; retryAfterSec: number } | null {
	pruneExpiredEntries();
	const expiresAt = memoryLocks.get(identifier);
	if (!expiresAt) return null;

	const retryAfterSec = Math.ceil((expiresAt - Date.now()) / 1000);
	if (retryAfterSec <= 0) {
		memoryLocks.delete(identifier);
		return null;
	}

	return { locked: true, retryAfterSec };
}

function recordMemoryFailure(identifier: string) {
	pruneExpiredEntries();

	const now = Date.now();
	const existing = memoryFailures.get(identifier);
	const state =
		existing && existing.windowExpiresAt > now
			? { ...existing, count: existing.count + 1 }
			: { count: 1, windowExpiresAt: now + WINDOW_SEC * 1000 };

	memoryFailures.set(identifier, state);

	for (const tier of LOCKOUT_TIERS) {
		if (state.count >= tier.threshold) {
			memoryLocks.set(identifier, now + tier.durationSec * 1000);
			logger.warn("[authLockout] Identifier locked out via memory fallback", {
				identifier: `${identifier.slice(0, 12)}...`,
				attempts: state.count,
				lockDurationSec: tier.durationSec,
			});
			break;
		}
	}
}

function resetMemoryFailures(identifier: string) {
	memoryFailures.delete(identifier);
	memoryLocks.delete(identifier);
}

/**
 * Check if an identifier is currently locked out.
 * Returns null if allowed, or the remaining lockout seconds if locked.
 */
export async function checkAuthLockout(
	identifier: string,
): Promise<{ locked: true; retryAfterSec: number } | null> {
	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();
		const ttl = await withTimeout(
			redis.ttl(`${LOCK_PREFIX}${identifier}`),
			"auth lockout ttl",
		);
		if (ttl > 0) {
			return { locked: true, retryAfterSec: ttl };
		}
		return null;
	} catch (error) {
		logger.error("[authLockout] Redis check failed, using memory fallback", {
			identifier: `${identifier.slice(0, 12)}...`,
			error: String(error),
		});
		return getMemoryLockout(identifier);
	}
}

/**
 * Record a failed auth attempt. If threshold exceeded, engage lockout.
 */
export async function recordAuthFailure(identifier: string): Promise<void> {
	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();
		const key = `${FAIL_PREFIX}${identifier}`;

		// Atomic increment + set TTL
		const count = await withTimeout(redis.incr(key), "auth lockout incr");
		if (count === 1) {
			// First failure — set the window TTL
			await withTimeout(redis.expire(key, WINDOW_SEC), "auth lockout expire");
		}

		// Check if any lockout tier is breached
		for (const tier of LOCKOUT_TIERS) {
			if (count >= tier.threshold) {
				const lockKey = `${LOCK_PREFIX}${identifier}`;
				await withTimeout(
					redis.set(lockKey, "1", { ex: tier.durationSec }),
					"auth lockout set",
				);
				logger.warn("[authLockout] Identifier locked out", {
					identifier: `${identifier.slice(0, 12)}...`,
					attempts: count,
					lockDurationSec: tier.durationSec,
				});
				break;
			}
		}
	} catch (error) {
		logger.error("[authLockout] Redis write failed, using memory fallback", {
			identifier: `${identifier.slice(0, 12)}...`,
			error: String(error),
		});
		recordMemoryFailure(identifier);
	}
}

/**
 * Reset failure counter on successful auth (prevents lockout buildup from
 * occasional typos mixed with valid logins).
 */
export async function resetAuthFailures(identifier: string): Promise<void> {
	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();
		await withTimeout(
			redis.del(`${FAIL_PREFIX}${identifier}`),
			"auth lockout reset",
		);
	} catch (error) {
		logger.warn("[authLockout] Redis reset failed, clearing memory fallback only", {
			identifier: `${identifier.slice(0, 12)}...`,
			error: String(error),
		});
	}
	resetMemoryFailures(identifier);
}

/**
 * Extract a lockout identifier from a request.
 * Uses X-Forwarded-For (Vercel sets this) or falls back to API key prefix.
 */
export function getLockoutIdentifier(req: {
	headers: { "x-forwarded-for"?: string | undefined; authorization?: string | undefined };
}): string {
	// Prefer IP address
	const forwarded = req.headers["x-forwarded-for"];
	if (forwarded) {
		// Take the first IP (client IP before proxies)
		return `ip:${forwarded.split(",")[0]!.trim()}`;
	}

	// Fallback: API key prefix (first 16 chars)
	const auth = req.headers.authorization;
	if (auth?.startsWith("Bearer juno_ak_")) {
		return `key:${auth.slice(7, 23)}`;
	}

	return "ip:unknown";
}
