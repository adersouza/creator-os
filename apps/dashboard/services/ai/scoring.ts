/**
 * Shared scoring functions — extracted to break circular deps between
 * analytics.ts ↔ ideas.ts.
 *
 * calculateViralScore was in analytics.ts (imported by ideas.ts)
 * calculateTrendBonus was in ideas.ts (imported by analytics.ts)
 */

import type { PostIdea } from "./types.js";

/**
 * Calculate trend bonus based on content alignment with trending topics.
 * Returns bonus points (0-15) based on topic match quality.
 */
export const calculateTrendBonus = (
	content: string,
	trendingTopics: Array<{
		topic: string;
		searchVolume: number;
		trending: boolean;
	}> = [],
): number => {
	if (!trendingTopics || trendingTopics.length === 0) return 0;

	const contentLower = content.toLowerCase();
	let maxBonus = 0;

	for (const { topic, searchVolume, trending } of trendingTopics) {
		const topicNormalized = topic.replace("#", "").toLowerCase();

		// Exact topic match (e.g., "#productivity" in content)
		if (
			contentLower.includes(`#${topicNormalized}`) ||
			contentLower.includes(topic.toLowerCase())
		) {
			maxBonus = Math.max(maxBonus, 15);
			continue;
		}

		// Partial match - topic word appears in content
		if (contentLower.includes(topicNormalized)) {
			const volumeBonus = searchVolume >= 80 ? 10 : 7;
			const trendingBonus = trending ? 2 : 0;
			maxBonus = Math.max(maxBonus, volumeBonus + trendingBonus);
			continue;
		}

		// Related topic - check for common synonyms/related words
		const relatedTerms: Record<string, string[]> = {
			ai: ["artificial intelligence", "machine learning", "chatgpt", "llm"],
			productivity: ["efficiency", "workflow", "time management", "gtd"],
			tech: ["technology", "software", "startup", "saas"],
			fitness: ["workout", "exercise", "training", "gym"],
			business: ["entrepreneur", "startup", "company", "revenue"],
		};

		const related = relatedTerms[topicNormalized] || [];
		if (related.some((term) => contentLower.includes(term))) {
			maxBonus = Math.max(maxBonus, 5);
		}
	}

	return maxBonus;
};

/**
 * Score content for viral potential (0-100).
 */
export const calculateViralScore = (
	content: string,
	hasMedia: boolean,
	category: PostIdea["category"],
	isControversial: boolean,
	hasQuestion: boolean,
	hookStrength: number, // 1-10
	trendingTopics?: Array<{
		topic: string;
		searchVolume: number;
		trending: boolean;
	}>,
	_userStats?: { avgLikes: number; avgReplies: number; avgShares: number },
): number => {
	let score = 30; // Base score

	// Content length optimization (sweet spot 100-280 chars)
	const charCount = content.length;
	if (charCount >= 100 && charCount <= 280) score += 15;
	else if (charCount >= 50 && charCount <= 400) score += 8;

	// Media boost
	if (hasMedia) score += 12;

	// Category bonuses
	const categoryScores: Record<PostIdea["category"], number> = {
		hook: 12,
		controversial: 15,
		question: 10,
		story: 8,
		list: 7,
		educational: 6,
		personal: 5,
	};
	score += categoryScores[category] || 5;

	// Question engagement boost
	if (hasQuestion) score += 8;

	// Hook strength (major factor)
	score += hookStrength * 2;

	// Controversial content has higher viral potential
	if (isControversial) score += 10;

	// Check for viral patterns
	const viralPatterns = [
		/^(unpopular opinion|hot take|controversial|i don't care)/i,
		/^(here's why|the truth about|nobody talks about)/i,
		/^(stop|don't|never|always)/i,
		/\?$/,
		/^(i |my |we )/i, // Personal stories
	];

	viralPatterns.forEach((pattern) => {
		if (pattern.test(content)) score += 3;
	});

	// TRENDING TOPICS BONUS
	if (trendingTopics && trendingTopics.length > 0) {
		const trendBonus = calculateTrendBonus(content, trendingTopics);
		score += trendBonus;
	}

	return Math.min(Math.max(score, 0), 100);
};
