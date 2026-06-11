// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Forecast a short horizon from a time-indexed numeric series via
 * ordinary-least-squares linear regression, and report 95 % prediction
 * intervals plus a coarse confidence tier derived from R².
 *
 * Intentionally small and dependency-free — dashboard charts should be able
 * to overlay projection bands without pulling a stats library.
 */

export type ForecastConfidence = "low" | "medium" | "high";

export interface ForecastPoint {
	/** Index continuing past the history (history.length, +1, +2, ...). */
	index: number;
	/** Point estimate. */
	value: number;
	/** Upper 95 % prediction interval. */
	upper: number;
	/** Lower 95 % prediction interval. */
	lower: number;
}

export interface ForecastResult {
	points: ForecastPoint[];
	slope: number;
	intercept: number;
	/** Coefficient of determination, 0–1. NaN if variance is zero. */
	r2: number;
	confidence: ForecastConfidence;
}

/** z-score for a 95 % two-sided interval. */
const Z_95 = 1.96;

/**
 * OLS linear fit + 95 % prediction bands.
 *
 * Returns null when the series is too short (n < 3) — callers should hide
 * the overlay rather than render a meaningless projection.
 */
export function computeForecast(
	history: number[],
	horizon: number,
): ForecastResult | null {
	if (horizon <= 0) return null;
	if (history.length < 3) return null;

	const n = history.length;
	const xs = history.map((_, i) => i);
	const meanX = (n - 1) / 2;
	const meanY = history.reduce((sum, v) => sum + v, 0) / n;

	let sxx = 0;
	let sxy = 0;
	for (let i = 0; i < n; i++) {
		const dx = xs[i]! - meanX;
		sxx += dx * dx;
		sxy += dx * (history[i]! - meanY);
	}

	// Degenerate: all x identical. Can't happen with xs = 0..n-1 and n>=3,
	// but guard anyway so the math library is safe to port.
	if (sxx === 0) return null;

	const slope = sxy / sxx;
	const intercept = meanY - slope * meanX;

	// Residual variance (unbiased, n - 2 degrees of freedom).
	let ssRes = 0;
	let ssTot = 0;
	for (let i = 0; i < n; i++) {
		const fit = intercept + slope * i;
		ssRes += (history[i]! - fit) ** 2;
		ssTot += (history[i]! - meanY) ** 2;
	}
	const residualVariance = ssRes / (n - 2);
	const residualStdDev = Math.sqrt(Math.max(residualVariance, 0));

	const r2 = ssTot === 0 ? Number.NaN : 1 - ssRes / ssTot;

	const points: ForecastPoint[] = [];
	for (let k = 1; k <= horizon; k++) {
		const xNew = n - 1 + k;
		const dx = xNew - meanX;
		const stdErr = residualStdDev * Math.sqrt(1 + 1 / n + (dx * dx) / sxx);
		const value = intercept + slope * xNew;
		const margin = Z_95 * stdErr;
		points.push({
			index: xNew,
			value,
			upper: value + margin,
			lower: value - margin,
		});
	}

	return {
		points,
		slope,
		intercept,
		r2,
		confidence: confidenceTier(r2),
	};
}

function confidenceTier(r2: number): ForecastConfidence {
	// NaN (flat series — no variance to explain) is reported as low so the UI
	// can show the projection dimly without implying a strong trend.
	if (!Number.isFinite(r2)) return "low";
	if (r2 >= 0.7) return "high";
	if (r2 >= 0.4) return "medium";
	return "low";
}
