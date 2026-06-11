// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * growthForecast.ts — Linear regression forecasting + milestone detection
 *
 * Used by the Forecast tab in GrowthSimulator to project follower growth
 * based on historical account_analytics snapshots.
 */

export interface DataPoint {
	x: number;
	y: number;
}

export interface RegressionResult {
	slope: number;
	intercept: number;
	r2: number;
}

export interface ForecastPoint {
	date: string;
	predicted: number;
	upper: number;
	lower: number;
}

export interface Milestone {
	label: string;
	target: number;
	daysAway: number;
	date: string;
}

const MILESTONE_TARGETS = [
	500, 1_000, 2_500, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000,
	1_000_000,
];

/**
 * Standard least-squares linear regression.
 * Returns slope, intercept, and R-squared goodness-of-fit.
 */
export function linearRegression(points: DataPoint[]): RegressionResult {
	const n = points.length;
	if (n < 2) return { slope: 0, intercept: points[0]?.y ?? 0, r2: 0 };

	let sumX = 0;
	let sumY = 0;
	let sumXY = 0;
	let sumXX = 0;
	let _sumYY = 0;

	for (const { x, y } of points) {
		sumX += x;
		sumY += y;
		sumXY += x * y;
		sumXX += x * x;
		_sumYY += y * y;
	}

	const denom = n * sumXX - sumX * sumX;
	if (denom === 0) return { slope: 0, intercept: sumY / n, r2: 0 };

	const slope = (n * sumXY - sumX * sumY) / denom;
	const intercept = (sumY - slope * sumX) / n;

	// R-squared
	const meanY = sumY / n;
	let ssTot = 0;
	let ssRes = 0;
	for (const { x, y } of points) {
		const predicted = slope * x + intercept;
		ssTot += (y - meanY) ** 2;
		ssRes += (y - predicted) ** 2;
	}
	const r2 = ssTot === 0 ? 1 : 1 - ssRes / ssTot;

	return { slope, intercept, r2 };
}

/**
 * Project follower growth forward from historical snapshots.
 *
 * Converts snapshots to DataPoints (x = day index from first snapshot, y = followers),
 * runs linear regression, and projects `daysAhead` into the future.
 * Upper/lower bounds use +/-1 standard deviation of regression residuals.
 */
export function forecastGrowth(
	snapshots: { date: string; followers: number }[],
	daysAhead: number,
): ForecastPoint[] {
	if (snapshots.length < 2) return [];

	// Convert to DataPoints with x = days since first snapshot
	const firstDate = new Date(snapshots[0]!.date).getTime();
	const MS_PER_DAY = 86_400_000;

	const points: DataPoint[] = snapshots.map((s) => ({
		x: Math.round((new Date(s.date).getTime() - firstDate) / MS_PER_DAY),
		y: s.followers,
	}));

	const reg = linearRegression(points);

	// Compute standard deviation of residuals for confidence band
	const residuals = points.map((p) => p.y - (reg.slope * p.x + reg.intercept));
	const meanResidual = residuals.reduce((a, b) => a + b, 0) / residuals.length;
	const stddev = Math.sqrt(
		residuals.reduce((sum, r) => sum + (r - meanResidual) ** 2, 0) /
			residuals.length,
	);

	// Last data point's x value = starting point for forecast
	const lastX = points[points.length - 1]!.x;
	const lastDate = new Date(snapshots[snapshots.length - 1]!.date);

	const forecast: ForecastPoint[] = [];
	for (let d = 1; d <= daysAhead; d++) {
		const x = lastX + d;
		const predicted = Math.max(0, Math.round(reg.slope * x + reg.intercept));
		const upper = Math.max(0, Math.round(predicted + stddev));
		const lower = Math.max(0, Math.round(predicted - stddev));

		const forecastDate = new Date(lastDate);
		forecastDate.setDate(forecastDate.getDate() + d);

		forecast.push({
			date: forecastDate.toISOString().slice(0, 10),
			predicted,
			upper,
			lower,
		});
	}

	return forecast;
}

/**
 * Find which follower milestones are reachable within the forecast period.
 *
 * Scans the forecasted follower counts to find when each milestone target
 * is first crossed. Returns milestones above the current count with
 * estimated days until reached.
 */
export function findMilestones(
	currentFollowers: number,
	forecastedCounts: number[],
	startDate: Date,
): Milestone[] {
	const milestones: Milestone[] = [];

	for (const target of MILESTONE_TARGETS) {
		// Only consider milestones above current followers
		if (target <= currentFollowers) continue;

		// Find first day in forecast that crosses this target
		const dayIndex = forecastedCounts.findIndex((count) => count >= target);
		if (dayIndex === -1) continue;

		const daysAway = dayIndex + 1; // 1-based (day 1 = tomorrow)
		const milestoneDate = new Date(startDate);
		milestoneDate.setDate(milestoneDate.getDate() + daysAway);

		milestones.push({
			label: formatMilestoneLabel(target),
			target,
			daysAway,
			date: milestoneDate.toISOString().slice(0, 10),
		});
	}

	return milestones;
}

function formatMilestoneLabel(target: number): string {
	if (target >= 1_000_000) return `${(target / 1_000_000).toFixed(1)}M`;
	if (target >= 1_000) return `${(target / 1_000).toFixed(1)}K`;
	return String(target);
}
