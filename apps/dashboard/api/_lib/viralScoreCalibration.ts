/**
 * Viral Score Calibration — Server-side utility for predicted vs actual comparison.
 */

export interface CalibrationPair {
	predicted: number;
	actual: number;
}

/**
 * Compute the actual performance percentile of a post relative to user's post history.
 * Returns 1-10 scale matching viral score range.
 */
export function computeActualPerformancePercentile(
	post: {
		views_count?: number | null | undefined;
		likes_count?: number | null | undefined;
		replies_count?: number | null | undefined;
		reposts_count?: number | null | undefined;
		shares_count?: number | null | undefined;
	},
	userPostHistory: Array<{
		views_count?: number | null | undefined;
		likes_count?: number | null | undefined;
		replies_count?: number | null | undefined;
		reposts_count?: number | null | undefined;
		shares_count?: number | null | undefined;
	}>,
): number {
	if (userPostHistory.length === 0) return 5;

	const getScore = (p: typeof post): number => {
		const engagement =
			(p.likes_count || 0) +
			(p.replies_count || 0) * 2 +
			(p.reposts_count || 0) * 3 +
			(p.shares_count || 0) * 3;
		const views = p.views_count || 1;
		return engagement + (engagement / views) * 100;
	};

	const postScore = getScore(post);
	const historicalScores = userPostHistory.map(getScore).sort((a, b) => a - b);

	const belowCount = historicalScores.filter((s) => s < postScore).length;
	// #611: Guard against division by zero
	const percentile =
		historicalScores.length > 0 ? belowCount / historicalScores.length : 0.5;

	return Math.min(10, Math.max(1, Math.round(percentile * 9 + 1)));
}
