/**
 * AI Response Cache
 *
 * Caches AI-generated responses in Upstash Redis to reduce API costs
 * and improve response times for repeated/similar queries.
 */

import * as crypto from "node:crypto";

const { createHash } = crypto;

import { logger } from "./logger.js";
import { getRedis } from "./redis.js";

const AI_CACHE_PREFIX = "ai-cache:";
const AI_CACHE_STATS_KEY = "ai-cache:stats";

/** Default TTLs */
export const AI_CACHE_TTL = {
	CONTENT_GENERATION: 3600, // 1 hour
	ANALYTICS_INSIGHTS: 14400, // 4 hours
} as const;

/**
 * Generate a deterministic cache key from prompt + model + temperature.
 * #617: userId included to prevent cross-user cache poisoning.
 */
export function buildAICacheKey(
	prompt: string,
	model: string,
	temperature: number,
	userId?: string,
): string {
	const hash = createHash("sha256")
		.update(`${userId || "anon"}|${prompt}|${model}|${temperature}`)
		.digest("hex");
	return `${AI_CACHE_PREFIX}${hash}`;
}

/**
 * Retrieve a cached AI response.
 */
export async function getCachedAIResponse(
	cacheKey: string,
): Promise<string | null> {
	try {
		const redis = getRedis();
		const value = await redis.get(cacheKey);
		if (value !== null && value !== undefined) {
			// Track hit (expire stats hash after 8 days so it resets weekly)
			// Use pipeline for atomic hincrby+expire (prevents orphaned keys if crash between calls)
			redis
				.pipeline()
				.hincrby(AI_CACHE_STATS_KEY, "hits", 1)
				.expire(AI_CACHE_STATS_KEY, 691200)
				.exec()
				.catch(() => {});
			return value as string;
		}
		// Track miss
		redis
			.pipeline()
			.hincrby(AI_CACHE_STATS_KEY, "misses", 1)
			.expire(AI_CACHE_STATS_KEY, 691200)
			.exec()
			.catch(() => {});
		return null;
	} catch (err: unknown) {
		logger.error("AI cache get failed", {
			cacheKey,
			error: err instanceof Error ? err.message : String(err),
		});
		return null;
	}
}

/**
 * Store an AI response in cache.
 */
export async function setCachedAIResponse(
	cacheKey: string,
	response: string,
	ttlSeconds: number = AI_CACHE_TTL.CONTENT_GENERATION,
): Promise<void> {
	try {
		const redis = getRedis();
		await redis.set(cacheKey, response, { ex: ttlSeconds });
	} catch (err: unknown) {
		logger.error("AI cache set failed", {
			cacheKey,
			error: err instanceof Error ? err.message : String(err),
		});
	}
}

/**
 * Get cache hit/miss stats.
 */
export async function getAICacheStats(): Promise<{
	hits: number;
	misses: number;
}> {
	try {
		const redis = getRedis();
		const stats = await redis.hgetall(AI_CACHE_STATS_KEY);
		return {
			hits: Number(stats?.hits || 0),
			misses: Number(stats?.misses || 0),
		};
	} catch (err) {
		logger.debug("Failed to fetch AI cache stats from Redis", {
			error: String(err),
		});
		return { hits: 0, misses: 0 };
	}
}
