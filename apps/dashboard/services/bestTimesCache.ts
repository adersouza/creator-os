/**
 * Best Times Cache Service
 *
 * Caches best posting times analysis to prevent expensive recalculations
 * on every modal open. Cache has 30-minute TTL and is cleared on post creation.
 */

import {
	analyzeBestPostingTimes,
	type BestTimesResult,
} from "../utils/bestTimesAnalysis.js";
import logger from "@/utils/logger";

// Lazy import to break circular dep: bestTimesCache ↔ dataService
const getDataService = () => import("./dataService.js").then((m) => m.dataService);

interface BestTimesCacheEntry {
	result: BestTimesResult;
	calculatedAt: number;
	postCount: number;
	accountId?: string | undefined;
}

// Cache TTL: 30 minutes
const CACHE_TTL_MS = 30 * 60 * 1000;

// In-memory cache - one entry per account (or global if no account specified)
const cache = new Map<string, BestTimesCacheEntry>();

/**
 * Get best posting times with caching
 * @param accountId - Optional account ID to filter posts (undefined = all accounts)
 * @returns BestTimesResult with heatmap, insights, and top slots
 */
export async function getBestPostingTimes(
	accountId?: string,
): Promise<BestTimesResult> {
	const cacheKey = accountId || "all-accounts";

	// Check cache validity
	const cached = cache.get(cacheKey);
	if (cached && Date.now() - cached.calculatedAt < CACHE_TTL_MS) {
		logger.info(
			`📊 Best times cache hit for ${cacheKey} (${cached.postCount} posts)`,
		);
		return cached.result;
	}

	logger.info(`📊 Best times cache miss for ${cacheKey}, calculating...`);

	try {
		// Fetch posts from Firestore
		const ds = await getDataService();
		const posts = await ds.getPosts(accountId);

		// Filter to only published posts with performance data
		const publishedPosts = posts.filter(
			(p) => p.status === "published" && p.publishedAt && p.performance,
		);

		// Analyze best times
		const result = await analyzeBestPostingTimes(publishedPosts);

		// Update cache
		cache.set(cacheKey, {
			result,
			calculatedAt: Date.now(),
			postCount: publishedPosts.length,
			accountId,
		});

		logger.info(
			`📊 Best times calculated for ${cacheKey}: ${result.insights.bestDay} at ${result.insights.bestHour}:00 (${publishedPosts.length} posts)`,
		);

		return result;
	} catch (error) {
		logger.error("Failed to calculate best posting times:", error);

		// Return default on error
		return await analyzeBestPostingTimes([]);
	}
}

/**
 * Clear cache for a specific account or all accounts
 * Call this when a new post is published to force recalculation
 */
export function clearBestTimesCache(accountId?: string): void {
	if (accountId) {
		cache.delete(accountId);
		logger.info(`📊 Cleared best times cache for account ${accountId}`);
	} else {
		cache.clear();
		logger.info("📊 Cleared all best times cache");
	}
}
