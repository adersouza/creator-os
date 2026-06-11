/**
 * Metric Calculators — Centralized metric computation
 *
 * Consolidates 8 separate engagement rate implementations into
 * one source of truth with platform-aware formulas.
 */

import type { Platform } from "./platform.js";

export interface PostMetrics {
	views?: number | undefined;
	likes?: number | undefined;
	replies?: number | undefined;
	reposts?: number | undefined;
	quotes?: number | undefined;
	shares?: number | undefined;
	saves?: number | undefined;
	reach?: number | undefined;
	impressions?: number | undefined;
	comments?: number | undefined;
}

/**
 * Platform-aware engagement rate: one function, consistent formula.
 *
 * Threads:   (likes + replies*2 + reposts*1.5 + quotes + shares) / max(views, 1) * 100
 * Instagram: (likes + comments*2 + saves*3 + shares) / max(reach, 1) * 100
 *            Falls back to impressions when reach is 0.
 * Generic:   (likes + replies + reposts) / max(views, 1) * 100
 */
const MAX_ENGAGEMENT_RATE = 100;

export function calculateEngagementRate(
	metrics: PostMetrics,
	platform: Platform,
): number {
	const likes = metrics.likes ?? 0;

	if (platform === "threads") {
		const replies = metrics.replies ?? 0;
		const reposts = metrics.reposts ?? 0;
		const quotes = metrics.quotes ?? 0;
		const shares = metrics.shares ?? 0;
		const views = Math.max(metrics.views ?? 0, 1);
		return Math.min(
			((likes + replies * 2 + reposts * 1.5 + quotes + shares) / views) * 100,
			MAX_ENGAGEMENT_RATE,
		);
	}

	if (platform === "instagram") {
		const comments = metrics.comments ?? 0;
		const saves = metrics.saves ?? 0;
		const shares = metrics.shares ?? 0;
		const reach = metrics.reach ?? 0;
		const impressions = metrics.impressions ?? 0;
		const denominator = reach > 0 ? reach : Math.max(impressions, 1);
		return Math.min(
			((likes + comments * 2 + saves * 3 + shares) / denominator) * 100,
			MAX_ENGAGEMENT_RATE,
		);
	}

	// Generic fallback
	const replies = metrics.replies ?? 0;
	const reposts = metrics.reposts ?? 0;
	const views = Math.max(metrics.views ?? 0, 1);
	return Math.min(
		((likes + replies + reposts) / views) * 100,
		MAX_ENGAGEMENT_RATE,
	);
}

/**
 * Competitor engagement rate (normalized by followers + post count).
 *
 * Formula: ((totalLikes + totalComments) / postCount / followerCount) * 100
 * Returns 0 when followerCount or postCount is 0.
 */
export function calculateCompetitorEngagementRate(
	totalLikes: number,
	totalComments: number,
	postCount: number,
	followerCount: number,
): number {
	if (followerCount <= 0 || postCount <= 0) return 0;
	return Math.min(
		Math.round(
			((totalLikes + totalComments) / postCount / followerCount) * 10000,
		) / 100,
		MAX_ENGAGEMENT_RATE,
	);
}

/**
 * Aggregate engagement rate from an array of posts.
 *
 * Computes the engagement rate for each post and returns the average.
 * Returns 0 for an empty array.
 */
export function calculateAggregateEngagementRate(
	posts: PostMetrics[],
	platform: Platform,
): number {
	if (posts.length === 0) return 0;
	const total = posts.reduce(
		(sum, p) => sum + calculateEngagementRate(p, platform),
		0,
	);
	return total / posts.length;
}

/**
 * Best time to post analysis from historical post data.
 *
 * Groups posts by (dayOfWeek, hour) and computes average engagement
 * for each bucket. Returns results sorted by avgEngagement descending.
 *
 * @param posts - Array of posts with published_at timestamp and engagement_rate
 * @param timezone - IANA timezone string (defaults to "UTC")
 * @returns Sorted array of time buckets with average engagement and post count
 */
export function analyzeBestPostTimes(
	posts: Array<{ published_at: string; engagement_rate: number }>,
	timezone?: string,
): Array<{
	dayOfWeek: number;
	hour: number;
	avgEngagement: number;
	postCount: number;
}> {
	const tz = timezone ?? "UTC";
	const buckets: Record<
		string,
		{ dayOfWeek: number; hour: number; totalEngagement: number; count: number }
	> = {};

	for (const post of posts) {
		if (!post.published_at) continue;

		let dayOfWeek: number;
		let hour: number;

		try {
			// Use Intl to resolve timezone-aware day/hour
			const date = new Date(post.published_at);
			if (Number.isNaN(date.getTime())) continue;

			const parts = new Intl.DateTimeFormat("en-US", {
				timeZone: tz,
				weekday: "short",
				hour: "numeric",
				hour12: false,
			}).formatToParts(date);

			const weekdayStr =
				parts.find((p) => p.type === "weekday")?.value ?? "Sun";
			const hourStr = parts.find((p) => p.type === "hour")?.value ?? "0";

			const dayMap: Record<string, number> = {
				Sun: 0,
				Mon: 1,
				Tue: 2,
				Wed: 3,
				Thu: 4,
				Fri: 5,
				Sat: 6,
			};
			dayOfWeek = dayMap[weekdayStr] ?? 0;
			hour = parseInt(hourStr, 10);
			if (hour === 24) hour = 0; // midnight edge case
		} catch {
			// If timezone is invalid, fall back to UTC
			const date = new Date(post.published_at);
			if (Number.isNaN(date.getTime())) continue;
			dayOfWeek = date.getUTCDay();
			hour = date.getUTCHours();
		}

		const key = `${dayOfWeek}-${hour}`;
		if (!buckets[key]) {
			buckets[key] = { dayOfWeek, hour, totalEngagement: 0, count: 0 };
		}
		buckets[key].totalEngagement += post.engagement_rate;
		buckets[key].count++;
	}

	return Object.values(buckets)
		.map((b) => ({
			dayOfWeek: b.dayOfWeek,
			hour: b.hour,
			avgEngagement: b.count > 0 ? b.totalEngagement / b.count : 0,
			postCount: b.count,
		}))
		.sort((a, b) => b.avgEngagement - a.avgEngagement);
}
