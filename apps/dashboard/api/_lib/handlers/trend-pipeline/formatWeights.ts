// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Format Rotation
 *
 * Weighted random format selection with consecutive-duplicate avoidance
 * for trend-based content generation.
 */

import type { TrendFormat } from "./types.js";

/**
 * Weight distribution for trend output formats.
 * Higher weight = more likely to be selected. Sums to 100.
 */
export const FORMAT_WEIGHTS: Record<TrendFormat, number> = {
	hot_take: 30,
	analysis: 25,
	question: 25,
	thread_style: 20,
};

/**
 * One-sentence prompt directives for each format.
 * Used by the generator to steer Gemini output style.
 */
export const FORMAT_DESCRIPTIONS: Record<TrendFormat, string> = {
	hot_take:
		"Bold, confident opinion on this trend -- slightly provocative, takes a clear stance",
	analysis:
		"Thoughtful breakdown of why this trend matters -- insightful, adds unique perspective",
	question:
		"Engaging question about this trend that invites replies -- conversational, thought-provoking",
	thread_style:
		"Multi-paragraph mini-thread exploring this trend -- structured with line breaks, builds an argument",
};

/**
 * Select a format using weighted random, avoiding consecutive duplicates.
 * If `lastFormat` is provided, it is excluded from the pool.
 */
export function selectFormat(lastFormat?: string): TrendFormat {
	const entries = Object.entries(FORMAT_WEIGHTS).filter(
		([format]) => format !== lastFormat,
	);

	const totalWeight = entries.reduce((sum, [, weight]) => sum + weight, 0);
	let roll = Math.random() * totalWeight;

	for (const [format, weight] of entries) {
		roll -= weight;
		if (roll <= 0) return format as TrendFormat;
	}

	// Fallback (should not reach here)
	return entries[0]![0] as TrendFormat;
}
