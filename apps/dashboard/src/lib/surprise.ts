/**
 * Surprise scoring — ranks metrics by how anomalous their latest value is
 * relative to their trailing window, so the Auto-Insights Feed can lift the
 * most "unexpected this week" rows to the top.
 *
 * This is a z-score / Mahalanobis-style ranker. Naming it "surprise" keeps
 * the product vocabulary while the math stays cheap enough to run over dozens
 * of metrics client-side.
 */

export type SurpriseDirection = "up" | "down" | "flat";
export type SurpriseTier = "mild" | "notable" | "striking";

export interface SurpriseScore {
	/** Signed z-score: (current - mean) / std. */
	zScore: number;
	/** Absolute magnitude — used for ranking. */
	magnitude: number;
	direction: SurpriseDirection;
	tier: SurpriseTier;
	/** Trailing-window mean the current value was compared against. */
	baseline: number;
	/** Trailing-window standard deviation used in the z-score. */
	stdDev: number;
}

export interface MetricSample {
	/** Stable key — label collisions dedupe in the feed. */
	key: string;
	label: string;
	/** Prior values, ordered oldest → newest. Current value should NOT be in here. */
	history: number[];
	current: number;
	/**
	 * Optional direction hint — e.g. "down" is bad for reach, "up" is bad for
	 * unfollows. The feed can use it to color the magnitude pill.
	 */
	higherIsBetter?: boolean | undefined;
}

export interface RankedInsight extends MetricSample {
	score: SurpriseScore;
}

const MIN_HISTORY = 5;
const STRIKING_THRESHOLD = 3; // z > 3σ → very rare under a normal prior.
const NOTABLE_THRESHOLD = 2;
const MILD_THRESHOLD = 1;
const FLAT_Z_THRESHOLD = 0.15;

/**
 * Score a single metric's current value against its history.
 *
 * Returns null when:
 *   • history has fewer than 5 points (can't form a reliable baseline)
 *   • the trailing window has zero variance AND the current value matches
 *     the baseline exactly (nothing surprising to report)
 *
 * When history has zero variance but current differs, we treat stdDev as a
 * tiny ε of the baseline so the metric still surfaces with a large magnitude.
 */
export function scoreSurprise(
	history: number[],
	current: number,
): SurpriseScore | null {
	if (history.length < MIN_HISTORY) return null;
	if (!Number.isFinite(current)) return null;

	const n = history.length;
	const mean = history.reduce((sum, v) => sum + v, 0) / n;
	let ssq = 0;
	for (const v of history) ssq += (v - mean) ** 2;
	const variance = ssq / n;
	let stdDev = Math.sqrt(variance);

	if (stdDev === 0) {
		if (current === mean) return null;
		// ε floor so the z-score is computable but still reflects the jump.
		stdDev = Math.max(Math.abs(mean) * 0.01, 0.5);
	}

	const zScore = (current - mean) / stdDev;
	const magnitude = Math.abs(zScore);
	const direction: SurpriseDirection =
		magnitude < FLAT_Z_THRESHOLD ? "flat" : zScore > 0 ? "up" : "down";

	return {
		zScore,
		magnitude,
		direction,
		tier: tierFor(magnitude),
		baseline: mean,
		stdDev,
	};
}

/**
 * Rank a set of metric samples by absolute surprise magnitude.
 * Metrics that can't be scored are dropped (they'll reappear when enough
 * history accumulates).
 */
export function rankBySurprise(
	metrics: MetricSample[],
	limit = 5,
): RankedInsight[] {
	const scored: RankedInsight[] = [];
	for (const m of metrics) {
		const score = scoreSurprise(m.history, m.current);
		if (!score) continue;
		// Nothing below 1σ is "unexpected" — keeps the feed from filling up
		// with week-over-week wiggle that the reader already expects.
		if (score.magnitude < MILD_THRESHOLD) continue;
		scored.push({ ...m, score });
	}
	scored.sort((a, b) => b.score.magnitude - a.score.magnitude);
	return scored.slice(0, limit);
}

function tierFor(magnitude: number): SurpriseTier {
	if (magnitude >= STRIKING_THRESHOLD) return "striking";
	if (magnitude >= NOTABLE_THRESHOLD) return "notable";
	if (magnitude >= MILD_THRESHOLD) return "mild";
	return "mild";
}
