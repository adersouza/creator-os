/**
 * Viral Potential Score Calculator
 * Scores a post 1-10 based on reply potential, completion signal, timing,
 * media type, caption length, hashtags.
 * Weights aligned with 2026 Threads algorithm research.
 */

import {
	optimalBodyChars,
	optimalHashtagCount,
	type Platform,
} from "@/lib/socialPlatform";
import type { BestTimeSlot } from "./bestTimes";

export interface ViralScoreParams {
	postTime: Date;
	mediaType: string;
	captionLength: number;
	hashtags: string[];
	platform: string;
	bestTimes: BestTimeSlot[];
	typePerformance: Record<string, number>;
	hashtagPerformance: Record<string, number>;
	totalPosts?: number | undefined;
	/** Calibration adjustment factor from feedback loop (default 1.0) */
	calibrationAdjustment?: number | undefined;
	/** Caption text for reply potential + completion signal analysis */
	captionText?: string | undefined;
	/** Avg replies in first hour for this account's posts */
	replyVelocityAvg?: number | undefined;
	/** Baseline avg replies in first hour */
	accountAvgReplies1h?: number | undefined;
	/** Saves/reach ratio for similar posts */
	savesRate?: number | undefined;
}

export type ConfidenceLevel = "high" | "medium" | "low";

export interface ViralScoreResult {
	score: number;
	breakdown: {
		replyPotential: number;
		completionSignal: number;
		timing: number;
		type: number;
		caption: number;
		hashtags: number;
	};
	confidence: ConfidenceLevel;
	confidenceLabel: string;
}

const DAYS = [
	"Sunday",
	"Monday",
	"Tuesday",
	"Wednesday",
	"Thursday",
	"Friday",
	"Saturday",
];

function formatHour(h: number): string {
	if (h === 0) return "12:00 AM";
	if (h === 12) return "12:00 PM";
	return h < 12 ? `${h}:00 AM` : `${h - 12}:00 PM`;
}

/**
 * Reply Potential Score — How likely is this post to drive fast replies?
 * Questions and engagement prompts dramatically boost reply velocity.
 */
function calculateReplyPotentialScore(
	captionText: string,
	replyVelocityAvg?: number,
	accountAvgReplies1h?: number,
): number {
	let score = 5; // neutral default

	// Question detection: +3 if first sentence ends with "?"
	const firstSentence = captionText.split(/[.!?\n]/)[0] || "";
	const startsWithQuestion =
		captionText.trim().endsWith("?") || firstSentence.trim().endsWith("?");
	const hasQuestionWord =
		/^(what|why|how|who|when|where|which|do you|have you|would you|should|is it|are you|can you)/i.test(
			captionText.trim(),
		);

	if (startsWithQuestion || hasQuestionWord) score += 3;

	// Open-ended prompts: "thoughts?" "agree?" "what do you think?"
	const engagementPrompts =
		/\b(thoughts|agree|disagree|what do you think|tell me|share your|drop your|let me know|hot take|unpopular opinion)\b/i;
	if (engagementPrompts.test(captionText)) score += 2;

	// Historical reply velocity (if available)
	if (replyVelocityAvg && accountAvgReplies1h) {
		const velocityRatio = replyVelocityAvg / Math.max(accountAvgReplies1h, 1);
		score += Math.min(2, velocityRatio); // up to +2 for above-average velocity
	}

	return Math.min(10, Math.max(1, score));
}

/**
 * Completion Signal Score — Will people read the full post?
 * Saves rate is the strongest proxy for content completion.
 */
function calculateCompletionScore(
	captionText: string,
	savesRate?: number,
): number {
	let score = 5;

	// Saves rate (strongest proxy for completion)
	if (savesRate !== undefined) {
		if (savesRate > 0.05)
			score += 3; // >5% saves/reach = excellent
		else if (savesRate > 0.02)
			score += 2; // >2% = good
		else if (savesRate > 0.01) score += 1; // >1% = decent
	}

	// Open loop detection: line breaks + hook structure
	const lines = captionText.split("\n").filter((l) => l.trim());
	if (lines.length >= 3) score += 1; // structured content = higher completion

	// Hook detection: starts with a bold claim, number, or story opener
	const hookPatterns =
		/^(I |Here's|The truth|Most people|Nobody|Everyone|Stop|Don't|[0-9]+ )/i;
	if (hookPatterns.test(captionText.trim())) score += 1;

	return Math.min(10, Math.max(1, score));
}

export function calculateViralScore(
	params: ViralScoreParams,
): ViralScoreResult {
	const {
		postTime,
		mediaType,
		captionLength,
		hashtags,
		platform,
		bestTimes,
		typePerformance,
		hashtagPerformance,
		totalPosts,
		calibrationAdjustment = 1.0,
		captionText = "",
		replyVelocityAvg,
		accountAvgReplies1h,
		savesRate,
	} = params;

	// 1. Reply Potential Score (30% weight)
	const replyPotentialScore = calculateReplyPotentialScore(
		captionText,
		replyVelocityAvg,
		accountAvgReplies1h,
	);

	// 2. Completion Signal Score (20% weight)
	const completionScore = calculateCompletionScore(captionText, savesRate);

	// 3. Timing score (20% weight) — proximity to best posting times
	let timingScore = 5; // default neutral
	if (bestTimes.length > 0) {
		const postDay = DAYS[postTime.getDay()];
		const postHour = postTime.getHours();
		const postHourStr = formatHour(postHour);

		// Find closest best time slot
		let bestMatch = 0;
		for (const slot of bestTimes) {
			const dayMatch = slot.day === postDay ? 1 : 0;
			// Check if hour is close
			const slotHourMatch = slot.hour === postHourStr ? 1 : 0;
			const slotScore =
				slot.score * (dayMatch * 0.5 + slotHourMatch * 0.5 + 0.2);
			bestMatch = Math.max(bestMatch, slotScore);
		}
		timingScore = Math.min(10, Math.max(1, Math.round(bestMatch * 10)));
	}

	// 4. Media type score (15% weight)
	let typeScore = 5;
	if (Object.keys(typePerformance).length > 0) {
		const values = Object.values(typePerformance);
		const maxPerf = Math.max(...values, 1);
		const currentPerf =
			typePerformance[mediaType.toLowerCase()] ||
			typePerformance[mediaType] ||
			0;
		typeScore = Math.min(
			10,
			Math.max(1, Math.round((currentPerf / maxPerf) * 10)),
		);
	}

	// 5. Caption length score (10% weight)
	// Optimal ranges differ by platform
	let captionScore = 5;
	const platformSafe: Platform = platform === "instagram" ? "instagram" : "threads";
	const { min: optimalMin, max: optimalMax } = optimalBodyChars(platformSafe);
	if (captionLength >= optimalMin && captionLength <= optimalMax) {
		captionScore = 9;
	} else if (captionLength > 0 && captionLength < optimalMin) {
		captionScore = Math.max(3, Math.round((captionLength / optimalMin) * 7));
	} else if (captionLength > optimalMax) {
		const overBy = captionLength - optimalMax;
		captionScore = Math.max(4, 9 - Math.floor(overBy / 100));
	} else {
		captionScore = 2; // empty
	}

	// 6. Hashtag score (5% weight — Threads barely uses them)
	let hashtagScore = 5;
	if (hashtags.length === 0) {
		hashtagScore = platformSafe === "threads" ? 6 : 3; // threads doesn't rely on hashtags
	} else {
		const optimalCount = optimalHashtagCount(platformSafe);
		const countScore = Math.max(
			0,
			1 - Math.abs(hashtags.length - optimalCount) / optimalCount,
		);

		// Quality from historical performance
		let qualityScore = 0.5;
		if (Object.keys(hashtagPerformance).length > 0) {
			const maxHashPerf = Math.max(...Object.values(hashtagPerformance), 1);
			const avgPerf =
				hashtags.reduce((sum, h) => {
					const tag = h.replace(/^#/, "").toLowerCase();
					return (
						sum +
						(hashtagPerformance[tag] || hashtagPerformance[`#${tag}`] || 0)
					);
				}, 0) / hashtags.length;
			qualityScore = avgPerf / maxHashPerf;
		}

		hashtagScore = Math.min(
			10,
			Math.max(1, Math.round((countScore * 0.4 + qualityScore * 0.6) * 10)),
		);
	}

	// Weighted average — 2026 Threads algo weights
	const weightedScore =
		replyPotentialScore * 0.3 +
		completionScore * 0.2 +
		timingScore * 0.2 +
		typeScore * 0.15 +
		captionScore * 0.1 +
		hashtagScore * 0.05;

	let finalScore = Math.min(
		10,
		Math.max(1, Math.round(weightedScore * 10) / 10),
	);

	// Apply calibration adjustment from feedback loop
	finalScore = Math.min(
		10,
		Math.max(1, Math.round(finalScore * calibrationAdjustment * 10) / 10),
	);

	// Determine confidence based on totalPosts and apply caps
	let confidence: ConfidenceLevel = "high";
	let confidenceLabel = "Strong data";

	if (totalPosts !== undefined) {
		if (totalPosts < 15) {
			confidence = "low";
			confidenceLabel = "⚠️ Early data";
			finalScore = Math.min(finalScore, 7);
		} else if (totalPosts <= 30) {
			confidence = "medium";
			confidenceLabel = "Based on limited data";
			finalScore = Math.min(finalScore, 9);
		}
	}

	return {
		score: finalScore,
		breakdown: {
			replyPotential: replyPotentialScore,
			completionSignal: completionScore,
			timing: timingScore,
			type: typeScore,
			caption: captionScore,
			hashtags: hashtagScore,
		},
		confidence,
		confidenceLabel,
	};
}
