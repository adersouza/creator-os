// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Tier-aware AI rate limiter
 *
 * Limits: Free 20/h, Pro 100/h, Empire 500/h
 * Uses Upstash Redis sliding window.
 */

import { logger } from "./logger.js";
import { getUserTier } from "./tierGate.js";

const TIER_LIMITS: Record<string, number> = {
	free: 20,
	pro: 100,
	agency: 300,
	empire: 500,
};

const WINDOW_SEC = 3600; // 1 hour

export async function checkAIRateLimit(
	userId: string,
	endpoint: string,
): Promise<{ allowed: boolean; remaining: number; limit: number }> {
	let tier: string;
	try {
		tier = await getUserTier(userId);
	} catch (err) {
		logger.warn("[aiRateLimit] Tier lookup failed, defaulting to free", {
			userId,
			error: err instanceof Error ? err.message : String(err),
		});
		tier = "free";
	}
	const limit = TIER_LIMITS[tier] || TIER_LIMITS.free;

	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();
		const key = `rl:ai:${endpoint}:${userId}`;
		const now = Date.now();
		const windowStart = now - WINDOW_SEC * 1000;

		const pipe = redis.pipeline();
		pipe.zremrangebyscore(key, 0, windowStart);
		pipe.zadd(key, { score: now, member: `${now}:${Math.random()}` });
		pipe.zcard(key);
		pipe.expire(key, WINDOW_SEC + 1);
		const results = await pipe.exec();

		const count = (results[2] as number) || 0;
		return {
				allowed: count <= limit!,
				remaining: Math.max(0, limit! - count),
				limit: limit!,
		};
	} catch (err) {
		logger.error("[aiRateLimit] Redis error — failing closed", {
			endpoint,
			error: String(err),
		});
		// Fail closed: deny requests when rate limiter is unavailable
		return { allowed: false, remaining: 0, limit: limit! };
	}
}
