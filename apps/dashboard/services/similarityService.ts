// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Similarity Service
 * Phase 3.4 - Find similar posts based on content features
 *
 * Uses multi-factor similarity scoring:
 * - Media type match
 * - Content length similarity
 * - Hashtag overlap
 * - Posting time similarity
 * - Emoji usage pattern
 */

import logger from "@/utils/logger";

export interface PostFeatures {
	mediaType: "text" | "image" | "video" | "carousel" | "reels";
	contentLength: number;
	hashtags: string[];
	postingHour: number; // 0-23
	postingDay: number; // 0-6 (Sunday-Saturday)
	emojiCount: number;
	hasQuestion: boolean;
	hasLink: boolean;
	// Calculated
	avgWordLength: number;
	lineCount: number;
}

export interface SimilarPost {
	id: string;
	content: string;
	views: number;
	likes: number;
	replies: number;
	reposts: number;
	shares: number;
	engagementRate: number;
	publishedAt: Date;
	mediaType: "text" | "image" | "video" | "carousel" | "reels";
	permalink?: string | null | undefined;
	similarityScore: number; // 0-100
	matchReasons: string[]; // Why it's similar
}

interface Post {
	id: string;
	content: string;
	views: number;
	likes: number;
	replies: number;
	reposts: number;
	shares: number;
	engagementRate: number;
	publishedAt: Date;
	mediaType: "text" | "image" | "video" | "carousel" | "reels";
	permalink?: string | null | undefined;
}

/**
 * Extract features from post content
 */
export function extractFeatures(post: Post): PostFeatures {
	const content = post.content || "";

	// Extract hashtags
	const hashtagMatches = content.match(/#\w+/g) || [];
	const hashtags = hashtagMatches.map((h) => h.toLowerCase());

	// Count emojis (Unicode emoji range)
	const emojiMatches = content.match(/[\u{1F300}-\u{1F9FF}]/gu) || [];
	const emojiCount = emojiMatches.length;

	// Check for question
	const hasQuestion = /\?/.test(content);

	// Check for link
	const hasLink = /https?:\/\//.test(content);

	// Calculate avg word length
	const words = content.split(/\s+/).filter((w) => w.length > 0);
	const avgWordLength =
		words.length > 0
			? words.reduce((sum, w) => sum + w.length, 0) / words.length
			: 0;

	// Count lines
	const lineCount = content
		.split("\n")
		.filter((line) => line.trim().length > 0).length;

	// Extract posting time
	const postingHour = post.publishedAt.getHours();
	const postingDay = post.publishedAt.getDay();

	return {
		mediaType: post.mediaType,
		contentLength: content.length,
		hashtags,
		postingHour,
		postingDay,
		emojiCount,
		hasQuestion,
		hasLink,
		avgWordLength,
		lineCount,
	};
}

/**
 * Calculate similarity between two feature sets
 * Returns score 0-100
 */
export function calculateSimilarity(
	targetFeatures: PostFeatures,
	candidateFeatures: PostFeatures,
): { score: number; reasons: string[] } {
	let totalScore = 0;
	const reasons: string[] = [];

	// Media type match (20 points)
	if (targetFeatures.mediaType === candidateFeatures.mediaType) {
		totalScore += 20;
		reasons.push("Same media type");
	}

	// Content length similarity (15 points)
	// Similar if within 30% of each other
	const maxLen = Math.max(
		targetFeatures.contentLength,
		candidateFeatures.contentLength,
	);
	const lengthRatio =
		maxLen > 0
			? Math.min(
					targetFeatures.contentLength,
					candidateFeatures.contentLength,
				) / maxLen
			: 0;
	if (lengthRatio >= 0.7) {
		const lengthScore = 15 * lengthRatio;
		totalScore += lengthScore;
		reasons.push("Similar content length");
	}

	// Hashtag overlap (20 points)
	if (
		targetFeatures.hashtags.length > 0 ||
		candidateFeatures.hashtags.length > 0
	) {
		const commonHashtags = targetFeatures.hashtags.filter((h) =>
			candidateFeatures.hashtags.includes(h),
		);
		const totalHashtags = new Set([
			...targetFeatures.hashtags,
			...candidateFeatures.hashtags,
		]).size;
		const hashtagScore =
			totalHashtags > 0 ? (commonHashtags.length / totalHashtags) * 20 : 0;
		totalScore += hashtagScore;
		if (commonHashtags.length > 0) {
			reasons.push(
				`${commonHashtags.length} shared hashtag${commonHashtags.length > 1 ? "s" : ""}`,
			);
		}
	}

	// Posting time similarity (10 points)
	// Same hour or +/- 1 hour
	const hourDiff = Math.abs(
		targetFeatures.postingHour - candidateFeatures.postingHour,
	);
	if (hourDiff === 0) {
		totalScore += 10;
		reasons.push("Posted at same hour");
	} else if (hourDiff <= 1) {
		totalScore += 5;
		reasons.push("Posted at similar time");
	}

	// Same day of week (5 points)
	if (targetFeatures.postingDay === candidateFeatures.postingDay) {
		totalScore += 5;
		reasons.push("Same day of week");
	}

	// Emoji usage pattern (10 points)
	const emojiDiff = Math.abs(
		targetFeatures.emojiCount - candidateFeatures.emojiCount,
	);
	if (emojiDiff === 0 && targetFeatures.emojiCount > 0) {
		totalScore += 10;
		reasons.push("Same emoji count");
	} else if (emojiDiff <= 2) {
		totalScore += 5;
		reasons.push("Similar emoji usage");
	}

	// Question pattern (5 points)
	if (targetFeatures.hasQuestion === candidateFeatures.hasQuestion) {
		totalScore += 5;
		if (targetFeatures.hasQuestion) {
			reasons.push("Both contain questions");
		}
	}

	// Link pattern (5 points)
	if (targetFeatures.hasLink === candidateFeatures.hasLink) {
		totalScore += 5;
		if (targetFeatures.hasLink) {
			reasons.push("Both contain links");
		}
	}

	// Line structure similarity (5 points)
	const lineDiff = Math.abs(
		targetFeatures.lineCount - candidateFeatures.lineCount,
	);
	if (lineDiff === 0) {
		totalScore += 5;
		reasons.push("Same line structure");
	} else if (lineDiff <= 1) {
		totalScore += 2.5;
	}

	// Word length pattern (5 points)
	const maxWordLen = Math.max(
		targetFeatures.avgWordLength,
		candidateFeatures.avgWordLength,
	);
	const wordLengthRatio =
		maxWordLen > 0
			? Math.min(
					targetFeatures.avgWordLength,
					candidateFeatures.avgWordLength,
				) / maxWordLen
			: 0;
	if (wordLengthRatio >= 0.8) {
		totalScore += 5 * wordLengthRatio;
		reasons.push("Similar word length");
	}

	return {
		score: Math.round(totalScore),
		reasons: reasons.slice(0, 3), // Top 3 reasons
	};
}

/**
 * Find posts similar to a target post
 * Returns top 5 most similar posts with similarity score >= 60
 */
export function findSimilarPosts(
	targetPost: Post,
	allPosts: Post[],
	minSimilarityScore: number = 60,
): SimilarPost[] {
	logger.info(`[Similarity] Finding similar posts to ${targetPost.id}`);

	// Extract features from target post
	const targetFeatures = extractFeatures(targetPost);

	// Score all posts
	const scoredPosts: SimilarPost[] = allPosts
		.filter((p) => p.id !== targetPost.id) // Exclude the target post itself
		.map((post) => {
			const candidateFeatures = extractFeatures(post);
			const { score, reasons } = calculateSimilarity(
				targetFeatures,
				candidateFeatures,
			);

			return {
				...post,
				similarityScore: score,
				matchReasons: reasons,
			};
		})
		.filter((p) => p.similarityScore >= minSimilarityScore)
		.sort((a, b) => b.similarityScore - a.similarityScore)
		.slice(0, 5); // Top 5

	logger.info(
		`[Similarity] Found ${scoredPosts.length} similar posts (score >= ${minSimilarityScore})`,
	);

	return scoredPosts;
}

/**
 * Pattern detection across similar posts
 * Used for AI analysis
 */
export interface PatternAnalysis {
	commonMediaType: string;
	avgContentLength: number;
	commonHashtags: string[];
	preferredPostingHour: number;
	preferredPostingDay: string;
	avgEmojiCount: number;
	questionUsageRate: number; // 0-100%
	linkUsageRate: number; // 0-100%
	avgEngagementRate: number;
}

/**
 * Analyze patterns across a set of posts
 */
export function analyzePatterns(posts: Post[]): PatternAnalysis {
	if (posts.length === 0) {
		return {
			commonMediaType: "text",
			avgContentLength: 0,
			commonHashtags: [],
			preferredPostingHour: 12,
			preferredPostingDay: "Monday",
			avgEmojiCount: 0,
			questionUsageRate: 0,
			linkUsageRate: 0,
			avgEngagementRate: 0,
		};
	}

	const features = posts.map((p) => extractFeatures(p));

	// Common media type (most frequent)
	const mediaTypeCounts: Record<string, number> = {};
	features.forEach((f) => {
		mediaTypeCounts[f.mediaType] = (mediaTypeCounts[f.mediaType] || 0) + 1;
	});
	const commonMediaType = Object.entries(mediaTypeCounts).sort(
		(a, b) => b[1] - a[1],
	)[0]![0];

	// Average content length
	const avgContentLength = Math.round(
		features.reduce((sum, f) => sum + f.contentLength, 0) / features.length,
	);

	// Common hashtags (appearing in 40%+ of posts)
	const hashtagCounts: Record<string, number> = {};
	features.forEach((f) => {
		f.hashtags.forEach((tag) => {
			hashtagCounts[tag] = (hashtagCounts[tag] || 0) + 1;
		});
	});
	const commonHashtags = Object.entries(hashtagCounts)
		.filter(([_, count]) => count / posts.length >= 0.4)
		.sort((a, b) => b[1] - a[1])
		.slice(0, 5)
		.map(([tag]) => tag);

	// Preferred posting hour (most frequent)
	const hourCounts: Record<number, number> = {};
	features.forEach((f) => {
		hourCounts[f.postingHour] = (hourCounts[f.postingHour] || 0) + 1;
	});
	const preferredPostingHour = parseInt(
		Object.entries(hourCounts).sort((a, b) => b[1] - a[1])[0]![0],
		10,
	);

	// Preferred posting day (most frequent)
	const dayCounts: Record<number, number> = {};
	features.forEach((f) => {
		dayCounts[f.postingDay] = (dayCounts[f.postingDay] || 0) + 1;
	});
	const preferredPostingDayNum = parseInt(
		Object.entries(dayCounts).sort((a, b) => b[1] - a[1])[0]![0],
		10,
	);
	const dayNames = [
		"Sunday",
		"Monday",
		"Tuesday",
		"Wednesday",
		"Thursday",
		"Friday",
		"Saturday",
	];
	const preferredPostingDay = dayNames[preferredPostingDayNum];

	// Average emoji count
	const avgEmojiCount = Math.round(
		features.reduce((sum, f) => sum + f.emojiCount, 0) / features.length,
	);

	// Question usage rate
	const questionCount = features.filter((f) => f.hasQuestion).length;
	const questionUsageRate = Math.round((questionCount / features.length) * 100);

	// Link usage rate
	const linkCount = features.filter((f) => f.hasLink).length;
	const linkUsageRate = Math.round((linkCount / features.length) * 100);

	// Average engagement rate
	const avgEngagementRate =
		posts.reduce((sum, p) => sum + p.engagementRate, 0) / posts.length;

	return {
		commonMediaType,
		avgContentLength,
		commonHashtags,
		preferredPostingHour,
		preferredPostingDay: preferredPostingDay!,
		avgEmojiCount,
		questionUsageRate,
		linkUsageRate,
		avgEngagementRate,
	};
}

export const similarityService = {
	extractFeatures,
	calculateSimilarity,
	findSimilarPosts,
	analyzePatterns,
};
