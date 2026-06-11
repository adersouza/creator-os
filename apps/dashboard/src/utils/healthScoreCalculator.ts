// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Health Score Calculator
 * Phase 3.2 - Calculates overall account health score (0-100)
 *
 * Breakdown:
 * - Growth Momentum: 20 points (follower growth rate)
 * - Engagement Quality: 25 points (engagement rate vs benchmarks)
 * - Consistency Score: 20 points (posting frequency and regularity)
 * - Viral Potential: 15 points (top posts performance)
 * - Competitive Position: 20 points (vs competitors if available)
 */

export interface HealthScoreBreakdown {
	growthMomentum: number; // 0-20
	engagementQuality: number; // 0-25
	consistencyScore: number; // 0-20
	viralPotential: number; // 0-15
	competitivePosition: number; // 0-20
}

export interface HealthScoreResult {
	score: number; // 0-100
	grade: string; // A+, A, B+, B, C+, C, D, F
	color: string; // Color for display
	breakdown: HealthScoreBreakdown;
	lowestCategory: {
		name: string;
		score: number;
		maxScore: number;
	};
	trend: number; // Change from previous calculation
	audienceQualityScore: number; // 0-100
}

export interface HealthScoreInput {
	// Growth metrics
	followerGrowthRate: number; // Percentage growth
	currentFollowers: number;

	// Engagement metrics
	engagementRate: number; // Decimal (e.g., 0.05 = 5%)
	totalPosts: number;
	avgPostsPerDay: number;

	// Viral metrics
	topPostEngagement: number; // Max engagement on any post
	avgEngagement: number; // Average engagement per post

	// Competitor data (optional)
	competitorBenchmarks?: {
        		avgFollowerCount: number;
        		avgEngagementRate: number;
        		avgPostFrequency: number;
        	} | null | undefined;

	// Historical data for trend
	previousScore?: number | undefined;
}

/**
 * Calculate growth momentum score (0-20 points)
 * Based on follower growth rate
 */
function calculateGrowthMomentum(
	followerGrowthRate: number,
	currentFollowers: number,
): number {
	// Exceptional growth: > 20% = 20 points
	if (followerGrowthRate >= 20) return 20;

	// Strong growth: 10-20% = 15-19 points
	if (followerGrowthRate >= 10) {
		return 15 + ((followerGrowthRate - 10) / 10) * 5;
	}

	// Good growth: 5-10% = 10-14 points
	if (followerGrowthRate >= 5) {
		return 10 + ((followerGrowthRate - 5) / 5) * 5;
	}

	// Modest growth: 0-5% = 5-9 points
	if (followerGrowthRate >= 0) {
		return 5 + (followerGrowthRate / 5) * 5;
	}

	// Declining: negative growth
	// Cap at 0, but allow small buffer for new accounts
	if (currentFollowers < 100) {
		return 5; // New accounts get benefit of doubt
	}

	return Math.max(0, 5 + followerGrowthRate); // Negative growth reduces score
}

/**
 * Calculate engagement quality score (0-25 points)
 * Based on engagement rate and benchmarks
 */
function calculateEngagementQuality(
	engagementRate: number,
	_competitorAvgEngagement?: number,
): number {
	const engagementPct = engagementRate * 100;

	// Exceptional: > 10% = 25 points
	if (engagementPct >= 10) return 25;

	// Excellent: 7-10% = 20-24 points
	if (engagementPct >= 7) {
		return 20 + ((engagementPct - 7) / 3) * 5;
	}

	// Very Good: 5-7% = 15-19 points
	if (engagementPct >= 5) {
		return 15 + ((engagementPct - 5) / 2) * 5;
	}

	// Good: 3-5% = 10-14 points
	if (engagementPct >= 3) {
		return 10 + ((engagementPct - 3) / 2) * 5;
	}

	// Average: 1-3% = 5-9 points
	if (engagementPct >= 1) {
		return 5 + ((engagementPct - 1) / 2) * 5;
	}

	// Below average: < 1% = 0-4 points
	return Math.max(0, engagementPct * 5);
}

/**
 * Calculate consistency score (0-20 points)
 * Based on posting frequency and regularity
 */
function calculateConsistencyScore(
	avgPostsPerDay: number,
	totalPosts: number,
): number {
	// Need at least 5 posts to evaluate consistency
	if (totalPosts < 5) return 5;

	// Optimal: 1-3 posts per day = 20 points
	if (avgPostsPerDay >= 1 && avgPostsPerDay <= 3) return 20;

	// Good: 0.5-1 posts per day = 15-19 points
	if (avgPostsPerDay >= 0.5 && avgPostsPerDay < 1) {
		return 15 + ((avgPostsPerDay - 0.5) / 0.5) * 5;
	}

	// Decent: 0.3-0.5 posts per day = 10-14 points
	if (avgPostsPerDay >= 0.3 && avgPostsPerDay < 0.5) {
		return 10 + ((avgPostsPerDay - 0.3) / 0.2) * 5;
	}

	// Low: 0.1-0.3 posts per day = 5-9 points
	if (avgPostsPerDay >= 0.1 && avgPostsPerDay < 0.3) {
		return 5 + ((avgPostsPerDay - 0.1) / 0.2) * 5;
	}

	// Over-posting: > 3 posts per day penalized
	if (avgPostsPerDay > 3) {
		// Diminishing returns for posting too much
		return Math.max(10, 20 - (avgPostsPerDay - 3) * 2);
	}

	// Very low activity
	return Math.max(0, avgPostsPerDay * 50);
}

/**
 * Calculate viral potential score (0-15 points)
 * Based on top post performance vs average
 */
function calculateViralPotential(
	topPostEngagement: number,
	avgEngagement: number,
): number {
	if (avgEngagement === 0 || topPostEngagement === 0) return 5;

	const viralRatio = topPostEngagement / avgEngagement;

	// Exceptional viral content: 10x+ avg = 15 points
	if (viralRatio >= 10) return 15;

	// Strong viral potential: 5-10x = 12-14 points
	if (viralRatio >= 5) {
		return 12 + ((viralRatio - 5) / 5) * 3;
	}

	// Good viral potential: 3-5x = 9-11 points
	if (viralRatio >= 3) {
		return 9 + ((viralRatio - 3) / 2) * 3;
	}

	// Moderate potential: 2-3x = 6-8 points
	if (viralRatio >= 2) {
		return 6 + ((viralRatio - 2) / 1) * 3;
	}

	// Low potential: 1-2x = 3-5 points
	return Math.max(3, 3 + (viralRatio - 1) * 3);
}

/**
 * Calculate competitive position score (0-20 points)
 * Based on comparison to competitors
 */
function calculateCompetitivePosition(
	currentFollowers: number,
	engagementRate: number,
	avgPostsPerDay: number,
	competitorBenchmarks?: {
		avgFollowerCount: number;
		avgEngagementRate: number;
		avgPostFrequency: number;
	} | null,
): number {
	if (!competitorBenchmarks) {
		// No competitor data - give neutral score
		return 10;
	}

	let score = 0;

	// Follower count comparison (0-7 points)
	const followerRatio =
		currentFollowers / competitorBenchmarks.avgFollowerCount;
	if (followerRatio >= 2)
		score += 7; // 2x competitors
	else if (followerRatio >= 1.5) score += 6;
	else if (followerRatio >= 1.2) score += 5;
	else if (followerRatio >= 1) score += 4;
	else if (followerRatio >= 0.8) score += 3;
	else if (followerRatio >= 0.6) score += 2;
	else if (followerRatio >= 0.4) score += 1;

	// Engagement rate comparison (0-8 points)
	const engagementPct = engagementRate * 100;
	const engagementDiff = engagementPct - competitorBenchmarks.avgEngagementRate;
	if (engagementDiff >= 3)
		score += 8; // 3%+ better
	else if (engagementDiff >= 2) score += 6;
	else if (engagementDiff >= 1) score += 5;
	else if (engagementDiff >= 0) score += 4;
	else if (engagementDiff >= -1) score += 3;
	else if (engagementDiff >= -2) score += 2;
	else if (engagementDiff >= -3) score += 1;

	// Posting frequency comparison (0-5 points)
	const postingDiff = avgPostsPerDay - competitorBenchmarks.avgPostFrequency;
	if (Math.abs(postingDiff) <= 0.5)
		score += 5; // Similar frequency
	else if (Math.abs(postingDiff) <= 1) score += 4;
	else if (postingDiff > 1)
		score += 3; // Posting more
	else if (postingDiff < -1) score += 2; // Posting less

	return Math.min(20, score);
}

/**
 * Get grade based on score
 */
function getGrade(score: number): string {
	if (score >= 95) return "A+";
	if (score >= 90) return "A";
	if (score >= 85) return "B+";
	if (score >= 80) return "B";
	if (score >= 75) return "C+";
	if (score >= 70) return "C";
	if (score >= 60) return "D";
	return "F";
}

/**
 * Get color based on score
 */
function getColor(score: number): string {
	if (score >= 81) return "#10b981"; // Green - Excellent
	if (score >= 61) return "#3b82f6"; // Blue - Good
	if (score >= 41) return "#f59e0b"; // Yellow - Average
	return "#ef4444"; // Red - Needs Attention
}

/**
 * Calculate audience quality score (0-100)
 * Based on engagement-to-follower ratio and growth/engagement consistency
 */
function calculateAudienceQuality(
	engagementRate: number,
	followerGrowthRate: number,
	currentFollowers: number,
): number {
	const engagementPct = engagementRate * 100;

	// Base score from engagement-to-follower ratio
	let score: number;
	if (engagementPct >= 5) score = 100;
	else if (engagementPct >= 3) score = 80;
	else if (engagementPct >= 1) score = 60;
	else if (engagementPct >= 0.5) score = 40;
	else score = 20;

	// Suspicious growth: high follower growth but low engagement suggests bought followers
	if (followerGrowthRate > 20 && engagementPct < 2) {
		score -= 20;
	}

	// Proportionality adjustment: large accounts naturally have lower engagement rates
	if (currentFollowers > 10000 && engagementPct >= 2) {
		score += 10; // Good engagement at scale
	} else if (currentFollowers < 1000 && engagementPct < 1) {
		score -= 10; // Low engagement even at small scale
	}

	return Math.max(0, Math.min(100, score));
}

/**
 * Calculate overall health score
 */
export function calculateHealthScore(
	input: HealthScoreInput,
): HealthScoreResult {
	// Calculate raw breakdown scores and round them
	const breakdown: HealthScoreBreakdown = {
		growthMomentum: Math.round(
			calculateGrowthMomentum(input.followerGrowthRate, input.currentFollowers),
		),
		engagementQuality: Math.round(
			calculateEngagementQuality(
				input.engagementRate,
				input.competitorBenchmarks?.avgEngagementRate,
			),
		),
		consistencyScore: Math.round(
			calculateConsistencyScore(input.avgPostsPerDay, input.totalPosts),
		),
		viralPotential: Math.round(
			calculateViralPotential(input.topPostEngagement, input.avgEngagement),
		),
		competitivePosition: Math.round(
			calculateCompetitivePosition(
				input.currentFollowers,
				input.engagementRate,
				input.avgPostsPerDay,
				input.competitorBenchmarks,
			),
		),
	};

	const score = Object.values(breakdown).reduce((sum, val) => sum + val, 0);

	// Find lowest category
	const categories = [
		{ name: "Growth Momentum", score: breakdown.growthMomentum, maxScore: 20 },
		{
			name: "Engagement Quality",
			score: breakdown.engagementQuality,
			maxScore: 25,
		},
		{
			name: "Consistency Score",
			score: breakdown.consistencyScore,
			maxScore: 20,
		},
		{ name: "Viral Potential", score: breakdown.viralPotential, maxScore: 15 },
		{
			name: "Competitive Position",
			score: breakdown.competitivePosition,
			maxScore: 20,
		},
	];

	const lowestCategory = categories.reduce((lowest, current) => {
		const lowestPct = (lowest.score / lowest.maxScore) * 100;
		const currentPct = (current.score / current.maxScore) * 100;
		return currentPct < lowestPct ? current : lowest;
	});

	const trend = input.previousScore ? score - input.previousScore : 0;

	const audienceQualityScore = calculateAudienceQuality(
		input.engagementRate,
		input.followerGrowthRate,
		input.currentFollowers,
	);

	return {
		score: Math.round(score),
		grade: getGrade(score),
		color: getColor(score),
		breakdown,
		lowestCategory,
		trend: Math.round(trend),
		audienceQualityScore,
	};
}

// ---------------------------------------------------------------------------
// Anomaly Detection
// ---------------------------------------------------------------------------

export interface AnomalyAlert {
	type: "engagement_drop" | "follower_stall" | "sudden_spike" | "posting_gap";
	severity: "warning" | "critical" | "positive";
	title: string;
	description: string;
	suggestedAction: string;
}

export function detectAnomalies(
	recentEngagementRates: number[], // Last 14 days of engagement rates
	historicalAvg: number, // 30-day average engagement rate
	followerHistory: number[], // Last 14 days of follower counts
	postDates?: string[], // Dates of recent posts
): AnomalyAlert[] {
	const alerts: AnomalyAlert[] = [];

	if (historicalAvg > 0 && recentEngagementRates.length >= 7) {
		// Calculate recent 7-day average
		const recent7 = recentEngagementRates.slice(-7);
		const recent7Avg = recent7.reduce((s, v) => s + v, 0) / recent7.length;
		const ratio = recent7Avg / historicalAvg;

		if (ratio < 0.5) {
			alerts.push({
				type: "engagement_drop",
				severity: "critical",
				title: "Engagement has dropped significantly",
				description: `Your 7-day engagement is ${Math.round((1 - ratio) * 100)}% below your 30-day average.`,
				suggestedAction:
					"Experiment with different content formats, post at peak hours, and engage with your audience through replies.",
			});
		} else if (ratio < 0.7) {
			alerts.push({
				type: "engagement_drop",
				severity: "warning",
				title: "Engagement is declining",
				description: `Your 7-day engagement is ${Math.round((1 - ratio) * 100)}% below your 30-day average.`,
				suggestedAction:
					"Try asking questions in your posts and replying to comments to boost interaction.",
			});
		}

		// Sudden spike: recent 3-day avg > 3x historical
		if (recentEngagementRates.length >= 3) {
			const recent3 = recentEngagementRates.slice(-3);
			const recent3Avg = recent3.reduce((s, v) => s + v, 0) / recent3.length;
			if (recent3Avg > historicalAvg * 3) {
				alerts.push({
					type: "sudden_spike",
					severity: "positive",
					title: "Engagement is surging!",
					description: `Your last 3 days of engagement are ${Math.round(recent3Avg / historicalAvg)}x your average. Something is resonating.`,
					suggestedAction:
						"Double down on the content style that triggered this spike. Post more frequently to ride the momentum.",
				});
			}
		}
	}

	// Follower stall: 14-day history shows 0 or negative growth
	if (followerHistory.length >= 2) {
		const first = followerHistory[0];
		const last = followerHistory[followerHistory.length - 1];
		if (first! > 0 && last! <= first!) {
			alerts.push({
				type: "follower_stall",
				severity: "warning",
				title: "Follower growth has stalled",
				description: `Your follower count hasn't grown over the past ${followerHistory.length} days.`,
				suggestedAction:
					"Focus on shareable content, collaborate with other creators, and engage in trending conversations.",
			});
		}
	}

	// Posting gap: >5 days since last post
	if (postDates && postDates.length > 0) {
		const sorted = [...postDates].sort(
			(a, b) => new Date(b).getTime() - new Date(a).getTime(),
		);
		const lastPostDate = new Date(sorted[0]!);
		const daysSinceLastPost =
			(Date.now() - lastPostDate.getTime()) / (1000 * 60 * 60 * 24);
		if (daysSinceLastPost > 5) {
			alerts.push({
				type: "posting_gap",
				severity: "warning",
				title: "You haven't posted recently",
				description: `It has been ${Math.round(daysSinceLastPost)} days since your last post. Algorithms penalize inactivity.`,
				suggestedAction:
					"Schedule at least one post today to re-engage your audience and maintain algorithmic reach.",
			});
		}
	}

	return alerts;
}
