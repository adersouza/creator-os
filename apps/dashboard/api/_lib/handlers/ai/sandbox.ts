/**
 * POST /api/ai/sandbox — AI sandbox for testing recommendation logic with fake data
 * Admin-only — uses withAdminRole middleware
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAdminRole } from "../../middleware.js";

interface SandboxInput {
	followers: number;
	totalPosts: number;
	avgEngagementRate: number;
	postingTimesDistribution: Record<string, number>;
	contentTypeMix: Record<string, number>;
	hashtags: string[];
	avgReplyTimeMins: number;
	recentEngagementTrend: "up" | "down" | "flat";
}

/**
 * Simulate low-hanging fruit recommendations based on fake data.
 * Mirrors logic in api/_lib/lowHangingFruit.ts but without DB queries.
 */
function simulateRecommendations(input: SandboxInput) {
	const recs: Array<{
		id: string;
		title: string;
		description: string;
		impactScore: number;
		effortScore: number;
		roi: number;
		fires: boolean;
		reason: string;
	}> = [];

	// 1. Posting time optimization
	const totalPostsByHour = Object.values(input.postingTimesDistribution);
	const totalPosts = totalPostsByHour.reduce((a, b) => a + b, 0);
	const peakHours = ["9", "12", "18", "20", "21"]; // typical best hours
	const peakPosts = peakHours.reduce(
		(sum, h) => sum + (input.postingTimesDistribution[h] || 0),
		0,
	);
	const peakRatio = totalPosts > 0 ? peakPosts / totalPosts : 0;
	const timingFires = peakRatio < 0.4;
	recs.push({
		id: "best-times",
		title: "Post at your best times",
		description: timingFires
			? `Only ${Math.round(peakRatio * 100)}% of posts are during peak hours`
			: `${Math.round(peakRatio * 100)}% of posts already in peak hours`,
		impactScore: 8,
		effortScore: 1,
		roi: 8,
		fires: timingFires,
		reason: `peakRatio=${peakRatio.toFixed(2)}`,
	});

	// 2. Content type diversification
	const types = Object.entries(input.contentTypeMix);
	const topType = types.sort((a, b) => b[1] - a[1])[0];
	const topTypeRatio = totalPosts > 0 && topType ? topType[1] / totalPosts : 0;
	const typeFires = topTypeRatio > 0.7 && types.length > 1;
	recs.push({
		id: "content-mix",
		title: "Diversify content types",
		description: typeFires
			? `${Math.round(topTypeRatio * 100)}% of posts are ${topType?.[0]} — try mixing in other types`
			: "Good content type mix",
		impactScore: 8,
		effortScore: 2,
		roi: 4,
		fires: typeFires,
		reason: `topTypeRatio=${topTypeRatio.toFixed(2)}, topType=${topType?.[0]}`,
	});

	// 3. Hashtag repetition
	const uniqueHashtags = new Set(input.hashtags.map((h) => h.toLowerCase()));
	const hashtagRepeatRatio =
		input.hashtags.length > 0
			? 1 - uniqueHashtags.size / input.hashtags.length
			: 0;
	const hashtagFires = hashtagRepeatRatio > 0.5;
	recs.push({
		id: "hashtag-rotation",
		title: "Rotate your hashtags",
		description: hashtagFires
			? `${Math.round(hashtagRepeatRatio * 100)}% hashtag repetition detected`
			: "Hashtag variety looks good",
		impactScore: 7,
		effortScore: 2,
		roi: 3.5,
		fires: hashtagFires,
		reason: `repeatRatio=${hashtagRepeatRatio.toFixed(2)}, unique=${uniqueHashtags.size}/${input.hashtags.length}`,
	});

	// 4. Reply time
	const replyFires = input.avgReplyTimeMins > 60;
	recs.push({
		id: "reply-time",
		title: "Reply faster to comments",
		description: replyFires
			? `Average reply time is ${Math.round(input.avgReplyTimeMins)}min — under 60min boosts engagement`
			: `Reply time of ${Math.round(input.avgReplyTimeMins)}min is good`,
		impactScore: 6,
		effortScore: 3,
		roi: 2,
		fires: replyFires,
		reason: `avgReplyTimeMins=${input.avgReplyTimeMins}`,
	});

	return recs;
}

/**
 * Quick viral score estimate from account-level data.
 */
function estimateViralScore(input: SandboxInput): {
	score: number;
	factors: Record<string, number>;
} {
	const engagementFactor = Math.min(10, input.avgEngagementRate * 100); // 10% → 10
	const followerFactor = Math.min(
		10,
		Math.log10(Math.max(1, input.followers)) * 2,
	);
	const consistencyFactor =
		input.totalPosts >= 50 ? 8 : input.totalPosts >= 20 ? 6 : 3;
	const trendFactor =
		input.recentEngagementTrend === "up"
			? 8
			: input.recentEngagementTrend === "flat"
				? 5
				: 2;

	const score =
		Math.round(
			(engagementFactor * 0.35 +
				followerFactor * 0.2 +
				consistencyFactor * 0.2 +
				trendFactor * 0.25) *
				10,
		) / 10;

	return {
		score: Math.min(10, Math.max(1, score)),
		factors: {
			engagement: engagementFactor,
			followers: followerFactor,
			consistency: consistencyFactor,
			trend: trendFactor,
		},
	};
}

export default withAdminRole(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		const input = req.body as SandboxInput;
		if (!input || typeof input.followers !== "number") {
			return apiError(
				res,
				400,
				"Invalid sandbox input — followers (number) is required",
			);
		}

		logger.info("[ai/sandbox] Running sandbox simulation", { userId: user.id });

		const recommendations = simulateRecommendations(input);
		const viralEstimate = estimateViralScore(input);

		return apiSuccess(res, {
			recommendations: {
				all: recommendations,
				firing: recommendations.filter((r) => r.fires),
			},
			viralEstimate,
			input,
		});
	},
);
