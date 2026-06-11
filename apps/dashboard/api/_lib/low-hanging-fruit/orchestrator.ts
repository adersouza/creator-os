/**
 * Main orchestrator for the Low-Hanging Fruit recommendations engine.
 * Coordinates all checks, applies filtering/weighting, and returns top 3 recs.
 */

import { logger } from "../logger.js";
import {
	applySuccessWeighting,
	getRecSuccessRates,
	updateRecSuccess,
} from "../recSuccessModel.js";
import {
	checkAccountHealth,
	checkGroupPerformanceGap,
	checkPostDecayPatterns,
} from "./advancedChecks.js";
import { filterDeprioritizedAndDismissed } from "./filtering.js";
import { getHistoryBasedRecommendations } from "./historyRecommendations.js";
import {
	checkAltText,
	checkBestTimes,
	checkContentTypeMix,
	checkPostingConsistency,
	checkPostingGaps,
	checkQuestionOpener,
	checkRepetitiveHashtags,
	checkReplyTime,
	checkReplyWindow,
	checkStories,
} from "./postChecks.js";
import type {
	LhfPost,
	LowHangingFruitResult,
	Recommendation,
	RecommendationCategory,
} from "./shared.js";
import { db, dbAny } from "./shared.js";
import {
	detectSolvedRecs,
	getRegressedRecs,
	storeBaselines,
} from "./solvedAndRegressed.js";

export async function getLowHangingFruit(
	userId: string,
	accountId: string,
	platform: string,
): Promise<LowHangingFruitResult> {
	const recommendations: Recommendation[] = [];

	try {
		// Fetch recent posts (last 30 days)
		const thirtyDaysAgo = new Date(
			Date.now() - 30 * 24 * 60 * 60 * 1000,
		).toISOString();
		const sevenDaysAgo = new Date(
			Date.now() - 7 * 24 * 60 * 60 * 1000,
		).toISOString();

		const postsTable = platform === "instagram" ? "instagram_posts" : "posts";
		const accountCol =
			platform === "instagram" ? "instagram_account_id" : "account_id";

		// Verify account ownership before querying posts
		const ownershipTable =
			platform === "instagram" ? "instagram_accounts" : "accounts";
		const { data: ownedAccount } = await db()
			.from(ownershipTable)
			.select("id")
			.eq("id", accountId)
			.eq("user_id", userId)
			.maybeSingle();
		if (!ownedAccount) {
			return { recommendations: [], solved: [], regressed: [] };
		}

		const { data: recentPosts } = await dbAny()
			.from(postsTable)
			.select(
				"id, published_at, likes_count, replies_count, reposts_count, shares_count, views_count, media_type, alt_text, content",
			)
			.eq(accountCol, accountId)
			.gte("published_at", thirtyDaysAgo)
			.not("published_at", "is", null)
			.order("published_at", { ascending: false })
			.limit(200);

		if (!recentPosts || recentPosts.length < 5) {
			return { recommendations: [], solved: [], regressed: [] }; // Not enough data
		}

		const sampleSize = recentPosts.length;

		// 1. Not posting at best times (impact: 8, effort: 1)
		await checkBestTimes(
			recentPosts,
			accountId,
			platform,
			recommendations,
			sampleSize,
		);

		// 2. Missing alt text (impact: 3, effort: 1) — IG only
		if (platform === "instagram") {
			checkAltText(recentPosts, recommendations, sampleSize);
		}

		// 3. Repetitive hashtags (impact: 7, effort: 2)
		const lastWeekPosts = recentPosts.filter(
			(p: LhfPost) =>
				p.published_at && new Date(p.published_at) >= new Date(sevenDaysAgo),
		);
		checkRepetitiveHashtags(lastWeekPosts, recommendations, sampleSize);

		// 4. Underusing best content type (impact: 8, effort: 2)
		checkContentTypeMix(recentPosts, platform, recommendations, sampleSize);

		// 5. Slow reply time (impact: 6, effort: 2)
		await checkReplyTime(accountId, platform, recommendations, sampleSize);

		// 6. Inconsistent posting (impact: 7, effort: 3)
		checkPostingConsistency(recentPosts, recommendations, sampleSize);

		// 7. No stories in 7 days (impact: 5, effort: 3) — IG only
		if (platform === "instagram") {
			await checkStories(accountId, sevenDaysAgo, recommendations, sampleSize);
		}

		// 8. Reply window — author replies within 30 min (impact: 9, effort: 2)
		await checkReplyWindow(
			accountId,
			platform,
			recentPosts,
			recommendations,
			sampleSize,
		);

		// 9. Question openers drive more engagement (impact: 8, effort: 1)
		checkQuestionOpener(recentPosts, recommendations, sampleSize);

		// 10. Posting gaps kill momentum (impact: 8, effort: 3)
		checkPostingGaps(recentPosts, recommendations, sampleSize);
	} catch (err) {
		logger.error("getLowHangingFruit error", {
			error: String(err),
			accountId,
			platform,
		});
	}

	// History-based recommendations (account_analytics + post_metric_history)
	try {
		const historyRecs = await getHistoryBasedRecommendations(
			accountId,
			userId,
			platform,
		);
		recommendations.push(...historyRecs);
	} catch (err) {
		logger.warn("[lowHangingFruit] History-based recommendations failed", {
			error: String(err),
			accountId,
		});
	}

	// 11. Group performance gap (cross-group comparison)
	try {
		const groupGapRecs = await checkGroupPerformanceGap(userId);
		recommendations.push(...groupGapRecs);
	} catch (err) {
		logger.warn("[lowHangingFruit] Group performance gap check failed", {
			error: String(err),
			userId,
		});
	}

	// 12. Post decay detection — still-growing vs peaked posts
	try {
		const decayRecs = await checkPostDecayPatterns(accountId, platform);
		recommendations.push(...decayRecs);
	} catch (err) {
		logger.warn("[lowHangingFruit] Post decay pattern check failed", {
			error: String(err),
			accountId,
		});
	}

	// 13. Account health — stagnation and shadowban alerts
	try {
		const healthRecs = await checkAccountHealth(accountId, platform);
		recommendations.push(...healthRecs);
	} catch (err) {
		logger.warn("[lowHangingFruit] Account health check failed", {
			error: String(err),
			accountId,
		});
	}

	// Sort by ROI descending
	recommendations.sort((a, b) => b.roi - a.roi);

	// Category deduplication: max 1 rec per category
	const seenCategories = new Set<RecommendationCategory>();
	const deduplicated: Recommendation[] = [];
	for (const rec of recommendations) {
		if (!seenCategories.has(rec.category)) {
			seenCategories.add(rec.category);
			deduplicated.push(rec);
		}
	}

	// Filter out deprioritized categories (Redis) and resurfacing dismissals
	const filtered = await filterDeprioritizedAndDismissed(
		userId,
		accountId,
		deduplicated,
	);

	// Apply per-user success weighting before selecting top recs
	const successRates = await getRecSuccessRates(userId);
	const weighted = applySuccessWeighting(filtered, successRates);

	const topRecs = weighted.slice(0, 3);

	// Detect solved recs against the full eligible set, not just the top three.
	// A recommendation falling to rank 4, being deduped, or being success-weighted
	// down is not proof that the underlying issue improved.
	const solved = await detectSolvedRecs(accountId, platform, weighted);
	await storeBaselines(accountId, platform, topRecs);

	// Update success model for solved recs
	for (const s of solved) {
		await updateRecSuccess(userId, s.category, true);
	}

	// Fetch regressed recs
	const regressed = await getRegressedRecs(accountId, platform);

	return { recommendations: topRecs, solved, regressed };
}
