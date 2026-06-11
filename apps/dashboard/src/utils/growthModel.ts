// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * growthModel.ts — Advanced stochastic growth modeling
 *
 * Features:
 * 1. Saturation Coefficient: Logarithmic decay for high-frequency posting.
 * 2. Monte Carlo Simulation: 1,000 runs to generate probability bands.
 * 3. Strategy Presets: Maps business objectives to mathematical parameters.
 */

export type GrowthStrategy = "steady" | "aggressive" | "balanced";

export interface StrategyParams {
	volatility: number; // Higher = wider cone (viral potential)
	baseRetention: number; // Higher = better floor, slower growth
	growthMultiplier: number; // Sensitivity to tactics
}

export const STRATEGY_CONFIG: Record<GrowthStrategy, StrategyParams> = {
	steady: {
		volatility: 0.05,
		baseRetention: 0.995, // 0.5% churn
		growthMultiplier: 0.8,
	},
	balanced: {
		volatility: 0.12,
		baseRetention: 0.99, // 1% churn
		growthMultiplier: 1.0,
	},
	aggressive: {
		volatility: 0.25, // High risk/reward
		baseRetention: 0.98, // 2% churn
		growthMultiplier: 1.4,
	},
};

/**
 * Calculates the Saturation Multiplier.
 * As frequency increases, the value per post decreases logarithmically.
 * Formula: y = (1 + ln(x)) / x  (normalized to 1 at x=1)
 */
export function calculateSaturation(postsPerDay: number): number {
	if (postsPerDay <= 1) return 1.0;
	// We use 1 + ln(x) to ensure it doesn't drop too fast, but still caps growth.
	// A user posting 10x a day shouldn't get 10x the growth of 1x a day.
	return (1 + Math.log(postsPerDay)) / postsPerDay;
}

export interface SimulationRun {
	day: number;
	followers: number;
}

export interface MonteCarloResult {
	p10: number[]; // 10th percentile (Pessimistic)
	p50: number[]; // 50th percentile (Median)
	p90: number[]; // 90th percentile (Optimistic/Viral)
	days: string[];
}

/**
 * Runs a Monte Carlo simulation for growth.
 */
export function runMonteCarlo(
	currentFollowers: number,
	baseDailyRate: number,
	postsPerDay: number,
	strategy: GrowthStrategy,
	days: number = 90,
): MonteCarloResult {
	const ITERATIONS = 1000;
	const config = STRATEGY_CONFIG[strategy];
	const saturation = calculateSaturation(postsPerDay);

	// All runs: [iteration][day]
	const allRuns: number[][] = Array.from({ length: ITERATIONS }, () => []);
	const dateLabels: string[] = [];

	const startDay = new Date();

	for (let i = 0; i < ITERATIONS; i++) {
		let followers = currentFollowers;

		for (let d = 0; d < days; d++) {
			// 1. Calculate growth for this day
			// baseDailyRate * strategyMultiplier * saturation
			const dailyGrowth = baseDailyRate * config.growthMultiplier * saturation;

			// 2. Add Stochastic Noise (The Algorithm Jitter)
			// Normal distribution approximation using Box-Muller transform
			const u1 = Math.random();
			const u2 = Math.random();
			const z0 = Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);

			// Daily change factor: growth + noise
			const dailyChange =
				1 + dailyGrowth + z0 * config.volatility * dailyGrowth;

			// 3. Apply Retention/Churn
			followers = followers * dailyChange * config.baseRetention;

			// Floor at 0
			followers = Math.max(0, followers);
			allRuns[i]!.push(followers);

			// Only build date labels on the first iteration
			if (i === 0) {
				const date = new Date(startDay);
				date.setDate(date.getDate() + d);
				dateLabels.push(
					date.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
				);
			}
		}
	}

	// Calculate percentiles per day
	const p10: number[] = [];
	const p50: number[] = [];
	const p90: number[] = [];

	for (let d = 0; d < days; d++) {
		const dayValues = allRuns.map((run) => run[d]).sort((a, b) => a! - b!);
		p10.push(Math.round(dayValues[Math.floor(ITERATIONS * 0.1)]!));
		p50.push(Math.round(dayValues[Math.floor(ITERATIONS * 0.5)]!));
		p90.push(Math.round(dayValues[Math.floor(ITERATIONS * 0.9)]!));
	}

	return { p10, p50, p90, days: dateLabels };
}
