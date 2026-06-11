// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Post Sentiment Tracker — Redis-backed persistence
 *
 * Stores per-post sentiment counters in Redis using HINCRBY.
 * Key format: `sentiment:post:{postId}` → { positive, negative, neutral, question }
 * TTL: 90 days (covers typical analytics window).
 *
 * Called from webhook processors when comments/replies are ingested.
 * Consumed by `getPostSentimentSummary()` for dashboards & crisis detection.
 */

import { logger } from "./logger.js";
import { getRedis } from "./redis.js";
import { analyzeSentiment, type SentimentType } from "./sentiment.js";

const SENTIMENT_KEY_PREFIX = "sentiment:post:";
const SENTIMENT_TTL_SECONDS = 90 * 24 * 60 * 60; // 90 days

function sentimentKey(postId: string): string {
	return `${SENTIMENT_KEY_PREFIX}${postId}`;
}

export interface SentimentBreakdown {
	positive: number;
	negative: number;
	neutral: number;
	question: number;
}

export interface SentimentSummary {
	postId: string;
	total: number;
	breakdown: SentimentBreakdown;
	/** Range: -100 (all negative) to +100 (all positive) */
	score: number;
	verdict: string;
}

/**
 * Record a single comment's sentiment for a post.
 * Runs `analyzeSentiment` on the text and increments the Redis counter.
 * Fire-and-forget safe — errors are logged, never thrown.
 */
export async function trackCommentSentiment(
	postId: string,
	text: string,
): Promise<SentimentType | null> {
	if (!postId || !text) return null;

	try {
		const sentiment = analyzeSentiment(text);
		const redis = getRedis();
		const key = sentimentKey(postId);

		// HINCRBY is atomic — safe for concurrent webhook processing
		await redis.hincrby(key, sentiment, 1);

		// Refresh TTL on every write to keep active posts alive
		await redis.expire(key, SENTIMENT_TTL_SECONDS);

		return sentiment;
	} catch (err) {
		logger.warn("[sentimentTracker] Failed to track sentiment", {
			postId,
			error: err instanceof Error ? err.message : String(err),
		});
		return null;
	}
}

/**
 * Get aggregated sentiment summary for a post.
 * Returns null if no sentiment data exists (post has no tracked comments).
 */
export async function getPostSentimentSummary(
	postId: string,
): Promise<SentimentSummary | null> {
	if (!postId) return null;

	try {
		const redis = getRedis();
		const key = sentimentKey(postId);
		const raw = await redis.hgetall(key);

		if (!raw || Object.keys(raw).length === 0) return null;

		const breakdown: SentimentBreakdown = {
			positive: Number(raw.positive) || 0,
			negative: Number(raw.negative) || 0,
			neutral: Number(raw.neutral) || 0,
			question: Number(raw.question) || 0,
		};

		const total =
			breakdown.positive +
			breakdown.negative +
			breakdown.neutral +
			breakdown.question;

		const score =
			total > 0
				? Math.round(((breakdown.positive - breakdown.negative) / total) * 100)
				: 0;

		let verdict = "Neutral";
		if (score > 30) verdict = "Strongly positive";
		else if (score > 10) verdict = "Mostly positive";
		else if (score < -30) verdict = "Strongly negative";
		else if (score < -10) verdict = "Mostly negative";
		else if (breakdown.question > total * 0.4) verdict = "High question volume";

		return { postId, total, breakdown, score, verdict };
	} catch (err) {
		logger.warn("[sentimentTracker] Failed to get summary", {
			postId,
			error: err instanceof Error ? err.message : String(err),
		});
		return null;
	}
}

/**
 * Get sentiment summaries for multiple posts in a single Redis pipeline.
 * Returns a Map keyed by postId. Missing posts are omitted from the map.
 */
export async function getPostSentimentSummaries(
	postIds: string[],
): Promise<Map<string, SentimentSummary>> {
	const results = new Map<string, SentimentSummary>();
	if (!postIds.length) return results;

	try {
		const redis = getRedis();
		const pipeline = redis.pipeline();

		for (const postId of postIds) {
			pipeline.hgetall(sentimentKey(postId));
		}

		const responses = await pipeline.exec();

		for (let i = 0; i < postIds.length; i++) {
			const raw = responses[i] as Record<string, string> | null;
			if (!raw || Object.keys(raw).length === 0) continue;

			const breakdown: SentimentBreakdown = {
				positive: Number(raw.positive) || 0,
				negative: Number(raw.negative) || 0,
				neutral: Number(raw.neutral) || 0,
				question: Number(raw.question) || 0,
			};

			const total =
				breakdown.positive +
				breakdown.negative +
				breakdown.neutral +
				breakdown.question;

			const score =
				total > 0
					? Math.round(
							((breakdown.positive - breakdown.negative) / total) * 100,
						)
					: 0;

			let verdict = "Neutral";
			if (score > 30) verdict = "Strongly positive";
			else if (score > 10) verdict = "Mostly positive";
			else if (score < -30) verdict = "Strongly negative";
			else if (score < -10) verdict = "Mostly negative";
			else if (breakdown.question > total * 0.4)
				verdict = "High question volume";

			results.set(postIds[i]!, {
				postId: postIds[i]!,
				total,
				breakdown,
				score,
				verdict,
			});
		}
	} catch (err) {
		logger.warn("[sentimentTracker] Failed to get batch summaries", {
			count: postIds.length,
			error: err instanceof Error ? err.message : String(err),
		});
	}

	return results;
}
