/**
 * Rate Limiter with configurable fail mode
 *
 * Uses Upstash Redis for distributed rate limiting.
 * - failMode 'open': allows request if Redis is unavailable (for read-only endpoints)
 * - failMode 'closed': blocks request if Redis is unavailable (for destructive actions)
 *
 * Uses atomic Lua script to prevent INCR/EXPIRE race condition where
 * a key could persist without TTL, causing counters to never reset.
 */

import { logger } from "./logger.js";

interface RateLimitOptions {
	/** Unique key for this rate limit (e.g., `publish:${userId}`) */
	key: string;
	/** Max requests allowed in the window */
	limit: number;
	/** Window duration in seconds */
	windowSeconds: number;
	/** Behavior when Redis is unavailable */
	failMode: "open" | "closed";
}

interface RateLimitResult {
	allowed: boolean;
	remaining: number;
	resetAt?: number | undefined;
	/** Suggested seconds to wait before retrying */
	retryAfterSeconds?: number | undefined;
	/** Why the request was denied */
	reason?: "exceeded" | "redis_unavailable" | undefined;
}

/**
 * Lua script: atomically increment and set TTL.
 * Returns [current_count, ttl_remaining].
 *
 * - If key doesn't exist: INCR creates it (=1), SET EX.
 * - If key exists but has no TTL (orphaned): re-set the TTL.
 * - If key exists with TTL: just INCR.
 */
const RATE_LIMIT_LUA = `
local key = KEYS[1]
local window = tonumber(ARGV[1])
local current = redis.call('INCR', key)
local ttl = redis.call('TTL', key)
if ttl < 0 then
  redis.call('EXPIRE', key, window)
  ttl = window
end
return {current, ttl}
`;

const REDIS_TIMEOUT_MS = 800;

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

/**
 * Check and increment a rate limit counter.
 */
export async function checkRateLimit(
	options: RateLimitOptions,
): Promise<RateLimitResult> {
	const { key, limit, windowSeconds, failMode } = options;
	const redisKey = `rl:${key}`;

	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();

		// Atomic INCR + EXPIRE via Lua script — prevents orphaned keys with no TTL.
		// Some unit-test Redis mocks only implement the legacy incr/expire shape.
		const result =
			typeof redis.eval === "function"
				? ((await withTimeout(
						redis.eval(RATE_LIMIT_LUA, [redisKey], [String(windowSeconds)]),
						"rate limit eval",
					)) as [number, number])
				: ([
						await withTimeout(redis.incr(redisKey), "rate limit incr"),
						windowSeconds,
					] as [number, number]);
		if (typeof redis.eval !== "function" && result[0] === 1) {
			await withTimeout(redis.expire(redisKey, windowSeconds), "rate limit expire");
		}

		const current = result[0];
		const ttl = result[1] > 0 ? result[1] : windowSeconds;

		if (current > limit) {
			const endpoint = key.split(":")[0];
			logger.warn("Rate limit exceeded", {
				endpoint,
				current,
				limit,
				windowSeconds,
			});
			return {
				allowed: false,
				remaining: 0,
				resetAt: Date.now() + ttl * 1000,
				retryAfterSeconds: ttl,
				reason: "exceeded",
			};
		}

		return {
			allowed: true,
			remaining: limit - current,
			resetAt: Date.now() + ttl * 1000,
		};
	} catch (error) {
		logger.error("Rate limiter Redis error", {
			key,
			failMode,
			error: error instanceof Error ? error.message : String(error),
		});

		if (failMode === "closed") {
			return {
				allowed: false,
				remaining: 0,
				retryAfterSeconds: 30,
				reason: "redis_unavailable",
			};
		}

		// Fail open: allow the request — log for observability
		logger.warn("Rate limiter failing open — Redis unavailable", {
			key,
		});
		return { allowed: true, remaining: limit };
	}
}
