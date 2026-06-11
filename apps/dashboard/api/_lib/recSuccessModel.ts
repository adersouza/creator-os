/**
 * Per-user Recommendation Success Model (Bayesian-ish, no ML)
 *
 * Tracks how often a user acts on recommendations per category
 * and whether the metric actually improved. Uses this to weight
 * future recommendations toward categories that work for this user.
 */

import { logger } from "./logger.js";
import type {
	Recommendation,
	RecommendationCategory,
} from "./lowHangingFruit.js";
import { getRedis } from "./redis.js";

interface CategoryStats {
	acted: number;
	improved: number;
}

type SuccessData = Record<string, CategoryStats>;

type SuccessRates = Record<string, number>;

const REDIS_PREFIX = "rec:success:";
const DEFAULT_RATE = 0.5;
const TTL_SECONDS = 90 * 24 * 3600; // 90 days

/**
 * Update success tracking when a recommendation is acted on.
 * Always increments `acted`; increments `improved` only if true.
 */
export async function updateRecSuccess(
	userId: string,
	category: RecommendationCategory,
	improved: boolean,
): Promise<void> {
	try {
		const redis = getRedis();
		const key = `${REDIS_PREFIX}${userId}`;

		// #612: Use atomic HINCRBY to prevent read-modify-write race conditions
		const pipeline = redis.pipeline();
		pipeline.hincrby(key, `${category}:acted`, 1);
		if (improved) {
			pipeline.hincrby(key, `${category}:improved`, 1);
		}
		pipeline.expire(key, TTL_SECONDS);
		await pipeline.exec();
	} catch (err) {
		logger.error("[recSuccessModel] updateRecSuccess failed", {
			userId,
			category,
			error: String(err),
		});
	}
}

/**
 * Get per-category success rates for a user.
 * Returns improved/acted ratio, defaulting to 0.5 for unseen categories.
 */
export async function getRecSuccessRates(
	userId: string,
): Promise<SuccessRates> {
	try {
		const redis = getRedis();
		const key = `${REDIS_PREFIX}${userId}`;

		// #612: Read from hash structure (compatible with HINCRBY writes)
		const raw = await redis.hgetall(key);
		if (!raw || Object.keys(raw).length === 0) return {};

		// Reconstruct category stats from hash fields like "category:acted", "category:improved"
		const data: SuccessData = {};
		for (const [field, value] of Object.entries(raw)) {
			const lastColon = field.lastIndexOf(":");
			if (lastColon === -1) continue;
			const cat = field.substring(0, lastColon);
			const metric = field.substring(lastColon + 1);
			if (!data[cat]) data[cat] = { acted: 0, improved: 0 };
			if (metric === "acted") data[cat].acted = Number(value) || 0;
			if (metric === "improved") data[cat].improved = Number(value) || 0;
		}

		const rates: SuccessRates = {};
		for (const [cat, stats] of Object.entries(data)) {
			rates[cat] =
				stats.acted > 0 ? stats.improved / stats.acted : DEFAULT_RATE;
		}
		return rates;
	} catch (err) {
		logger.error("[recSuccessModel] getRecSuccessRates failed", {
			userId,
			error: String(err),
		});
		return {};
	}
}

/**
 * Weight recommendations by per-user success rates.
 * Multiplies each rec's ROI by its category success rate, then re-sorts.
 */
export function applySuccessWeighting(
	recommendations: Recommendation[],
	successRates: SuccessRates,
): Recommendation[] {
	return recommendations
		.map((rec) => {
			const rate = successRates[rec.category] ?? DEFAULT_RATE;
			return { ...rec, roi: rec.roi * rate };
		})
		.sort((a, b) => b.roi - a.roi);
}
