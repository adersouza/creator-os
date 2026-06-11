/**
 * MetricDeviationEngine — One primitive powering 10+ features
 *
 * Detects statistical deviations from baseline for any metric.
 * Powers: anomaly alerts, viral content detection, competitor spikes,
 * follower milestones, engagement drops, shadowban detection.
 *
 * Pure functions — no DB calls, no side effects, just math.
 */

// ============================================================================
// Types
// ============================================================================

export interface MetricDataPoint {
	date: string;
	value: number;
}

export interface DeviationResult {
	metric: string;
	currentValue: number;
	baselineAvg: number;
	baselineStdDev: number;
	deviationScore: number; // z-score: how many std devs from mean
	direction: "above" | "below" | "normal";
	severity: "critical" | "warning" | "info" | "none";
	percentChange: number; // % change from baseline
}

export interface DeviationConfig {
	metric: string;
	baselineWindowDays: number; // How many days to compute baseline from (default: 14)
	sensitivity: "low" | "medium" | "high"; // Maps to z-score thresholds
	direction?: "both" | "drop_only" | "spike_only" | undefined; // What to alert on
	minDataPoints?: number | undefined; // Minimum baseline points needed (default: 7)
}

// ============================================================================
// Sensitivity -> z-score threshold mapping
// ============================================================================

const SENSITIVITY_THRESHOLDS: Record<DeviationConfig["sensitivity"], number> = {
	low: 3.0, // only extreme outliers
	medium: 2.0, // notable deviations
	high: 1.5, // early detection
};

// ============================================================================
// Core Statistics Helpers
// ============================================================================

function mean(values: number[]): number {
	if (values.length === 0) return 0;
	return values.reduce((sum, v) => sum + v, 0) / values.length;
}

function stddev(values: number[], avg: number): number {
	if (values.length < 2) return 0;
	const squaredDiffs = values.map((v) => (v - avg) ** 2);
	const variance = squaredDiffs.reduce((sum, v) => sum + v, 0) / values.length;
	return Math.sqrt(variance);
}

// ============================================================================
// Deviation Detection
// ============================================================================

/**
 * Detect whether a current value deviates from a historical baseline.
 *
 * @param dataPoints  Historical data points (sorted by date ascending).
 *                    The most recent `baselineWindowDays` points are used as baseline.
 * @param currentValue The current (latest) value to test against the baseline.
 * @param config       Detection configuration.
 * @returns            A DeviationResult describing the deviation (if any).
 */
export function detectDeviation(
	dataPoints: MetricDataPoint[],
	currentValue: number,
	config: DeviationConfig,
): DeviationResult {
	const {
		metric,
		baselineWindowDays,
		sensitivity,
		direction = "both",
		minDataPoints = 7,
	} = config;

	// Extract numeric values from baseline window
	const baselineValues = dataPoints
		.slice(-baselineWindowDays)
		.map((dp) => dp.value);

	// Filter to non-null / valid values for stats
	const validValues = baselineValues.filter((v) => Number.isFinite(v));

	// ── Edge case: not enough data ──
	if (validValues.length < minDataPoints) {
		return {
			metric,
			currentValue,
			baselineAvg: 0,
			baselineStdDev: 0,
			deviationScore: 0,
			direction: "normal",
			severity: "none",
			percentChange: 0,
		};
	}

	const baselineAvg = mean(validValues);
	const baselineStdDev = stddev(validValues, baselineAvg);

	// ── Edge case: zero or near-zero baseline average ──
	// If the baseline is all zeros, any non-zero value is "infinite" deviation.
	// Use a fallback: treat percentChange as the deviation signal.
	const percentChange =
		baselineAvg !== 0
			? ((currentValue - baselineAvg) / Math.abs(baselineAvg)) * 100
			: currentValue !== 0
				? 100 // went from 0 to something
				: 0;

	// ── Edge case: zero stddev (all baseline values identical) ──
	// If stddev is 0 and current equals baseline, no deviation.
	// If stddev is 0 and current differs, use percent change to assign severity.
	let deviationScore: number;
	if (baselineStdDev === 0) {
		if (currentValue === baselineAvg) {
			deviationScore = 0;
		} else {
			// #607: Synthetic z-score with correct sign based on direction
			// A 50%+ change when all values were constant is notable
			const absPctChange = Math.abs(percentChange);
			let magnitude = 1.0;
			if (absPctChange >= 100) magnitude = 4.0;
			else if (absPctChange >= 50) magnitude = 3.0;
			else if (absPctChange >= 25) magnitude = 2.0;
			else if (absPctChange >= 10) magnitude = 1.5;
			// Apply sign to match direction of change
			deviationScore = percentChange >= 0 ? magnitude : -magnitude;
		}
	} else {
		deviationScore = (currentValue - baselineAvg) / baselineStdDev;
	}

	// Determine direction
	const absScore = Math.abs(deviationScore);
	const threshold = SENSITIVITY_THRESHOLDS[sensitivity];
	let resultDirection: DeviationResult["direction"] = "normal";

	if (deviationScore > 0 && absScore >= threshold * 0.7) {
		resultDirection = "above";
	} else if (deviationScore < 0 && absScore >= threshold * 0.7) {
		resultDirection = "below";
	}

	// Apply direction filter: if config says "drop_only", ignore spikes, etc.
	if (direction === "drop_only" && resultDirection === "above") {
		resultDirection = "normal";
	} else if (direction === "spike_only" && resultDirection === "below") {
		resultDirection = "normal";
	}

	// Determine severity based on absolute z-score
	let severity: DeviationResult["severity"] = "none";

	if (resultDirection !== "normal") {
		if (absScore >= 3.5) {
			severity = "critical";
		} else if (absScore >= threshold) {
			severity = "warning";
		} else if (absScore >= threshold * 0.7) {
			severity = "info";
		}
	}

	return {
		metric,
		currentValue,
		baselineAvg,
		baselineStdDev,
		deviationScore,
		direction: resultDirection,
		severity,
		percentChange,
	};
}

/**
 * Batch: check multiple metrics at once.
 * Each entry is independent — runs detectDeviation for each.
 */
export function detectDeviations(
	metrics: Array<{
		dataPoints: MetricDataPoint[];
		currentValue: number;
		config: DeviationConfig;
	}>,
): DeviationResult[] {
	return metrics.map(({ dataPoints, currentValue, config }) =>
		detectDeviation(dataPoints, currentValue, config),
	);
}

// ============================================================================
// Pre-built config presets for common use cases
// ============================================================================

export const DEVIATION_PRESETS = {
	shadowban: {
		metric: "reach_to_follower_ratio",
		baselineWindowDays: 14,
		sensitivity: "medium" as const,
		direction: "drop_only" as const,
	},
	engagementDrop: {
		metric: "engagement_rate",
		baselineWindowDays: 14,
		sensitivity: "medium" as const,
		direction: "drop_only" as const,
	},
	viralContent: {
		metric: "views",
		baselineWindowDays: 7,
		sensitivity: "high" as const,
		direction: "spike_only" as const,
	},
	followerSpike: {
		metric: "follower_growth",
		baselineWindowDays: 30,
		sensitivity: "medium" as const,
		direction: "spike_only" as const,
	},
	followerDrop: {
		metric: "follower_count",
		baselineWindowDays: 30,
		sensitivity: "low" as const,
		direction: "drop_only" as const,
	},
	competitorSpike: {
		metric: "competitor_engagement",
		baselineWindowDays: 14,
		sensitivity: "medium" as const,
		direction: "spike_only" as const,
	},
	reachAnomaly: {
		metric: "reach",
		baselineWindowDays: 14,
		sensitivity: "medium" as const,
		direction: "both" as const,
	},
} as const satisfies Record<string, DeviationConfig>;
