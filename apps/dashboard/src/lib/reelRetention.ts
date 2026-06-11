/**
 * Reel Retention — pure helpers.
 *
 * Meta exposes `ig_reels_avg_watch_time` (ms) and `ig_skip_rate` (0–1) per
 * Reel via the insights endpoint. Both are already synced into `posts` by
 * Juno33's analytics sync. We combine them into an operator-
 * friendly retention score and classify each Reel into a retention bucket.
 *
 * Why a combined score: raw watch time ignores skip rate (a Reel that
 * 95% of viewers swipe past after 1s can still have 4s avg watch time
 * from the 5% who stayed). Raw skip rate ignores the staying viewers'
 * engagement depth. We want a single number an operator can rank on.
 */

export interface ReelMetricsInput {
	/** Milliseconds. From posts.ig_reels_avg_watch_time */
	avgWatchMs: number | null | undefined;
	/** Fraction 0–1. From posts.ig_skip_rate */
	skipRate: number | null | undefined;
}

/**
 * Returns a 0–100 score: higher = stickier Reel.
 *
 * Score = normalize(avgWatchMs) × (1 - skipRate)
 *   - avgWatchMs normalized against a 30s target (most Reels are 15–60s).
 *     We don't have per-Reel video_duration synced yet, so 30s is a
 *     reasonable fleet-wide benchmark.
 *   - (1 - skipRate) penalizes Reels that get swiped past in <3s.
 *
 * Returns 0 when we have no usable data.
 */
export function computeReelRetentionScore(input: ReelMetricsInput): number {
	const avgWatchMs = input.avgWatchMs ?? 0;
	const skipRate = clamp01(input.skipRate ?? 0);

	if (avgWatchMs <= 0 && skipRate <= 0) return 0;

	const WATCH_TARGET_MS = 30_000; // 30s reference duration
	const watchComponent = Math.min(1, avgWatchMs / WATCH_TARGET_MS);
	const stickComponent = 1 - skipRate;

	const score = watchComponent * stickComponent;

	return Math.round(clamp01(score) * 100);
}

export type RetentionBucket =
	| "excellent" // score ≥ 75
	| "strong" // score ≥ 55
	| "weak" // score ≥ 30
	| "sub3"; // score < 30 — viewers bailing before the hook lands

export function bucketReelRetention(score: number): RetentionBucket {
	if (score >= 75) return "excellent";
	if (score >= 55) return "strong";
	if (score >= 30) return "weak";
	return "sub3";
}

export interface FleetRetentionSummary {
	/** Number of Reels we actually had data for. Widget hides itself below MIN_DATA. */
	sampledReels: number;
	/** Fleet average score, 0–100. */
	avgScore: number;
	/** Reels whose score fell in each bucket. */
	byBucket: Record<RetentionBucket, number>;
	/** Fraction (0–1) of Reels bucketed `sub3` — viewers bailing in the first 3s. */
	sub3Rate: number;
}

export function summarizeFleetRetention(
	rows: Array<ReelMetricsInput & { views?: number | null | undefined }>,
): FleetRetentionSummary {
	const empty: FleetRetentionSummary = {
		sampledReels: 0,
		avgScore: 0,
		byBucket: { excellent: 0, strong: 0, weak: 0, sub3: 0 },
		sub3Rate: 0,
	};

	const scored: number[] = [];
	const byBucket: Record<RetentionBucket, number> = {
		excellent: 0,
		strong: 0,
		weak: 0,
		sub3: 0,
	};

	for (const r of rows) {
		// Require at least ONE of the two signals to be non-null/zero; a row
		// of all-zeros is the empty-metrics case Meta returns before sync.
		if ((r.avgWatchMs ?? 0) <= 0 && (r.skipRate ?? 0) <= 0) continue;
		const score = computeReelRetentionScore(r);
		scored.push(score);
		byBucket[bucketReelRetention(score)]++;
	}

	if (scored.length === 0) return empty;

	const avgScore = Math.round(
		scored.reduce((a, b) => a + b, 0) / scored.length,
	);

	return {
		sampledReels: scored.length,
		avgScore,
		byBucket,
		sub3Rate: byBucket.sub3 / scored.length,
	};
}

function clamp01(n: number): number {
	if (!Number.isFinite(n)) return 0;
	if (n < 0) return 0;
	if (n > 1) return 1;
	return n;
}
