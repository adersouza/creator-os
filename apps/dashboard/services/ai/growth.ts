// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import {
	analyzeBestPostingTimes,
	type BestTimesResult,
} from "../../utils/bestTimesAnalysis.js";
import { logger } from "@/utils/logger";
import { dataService } from "../dataService.js";
import type { AIContext } from "./contextEngine.js";
import { contextToSystemPrompt } from "./contextEngine.js";
import { generateContent } from "./core.js";
import type { VoiceProfile } from "./ideas.js";
import { buildVoiceContext, loadVoiceProfile } from "./voiceHelpers.js";

interface CachedSimulation {
	data: SimulationResult;
	timestamp: number;
}
const simulationCache = new Map<string, CachedSimulation>();
const SIMULATION_CACHE_TTL = 30 * 60 * 1000; // 30 minutes

function extractJsonFromAiResponse(response: string): string {
	const jsonBlock = response.match(/```json\s*([\s\S]*?)```/);
	if (jsonBlock?.[1]) return jsonBlock[1].trim();

	const genericBlock = response.match(/```\s*([\s\S]*?)```/);
	if (genericBlock?.[1]) return genericBlock[1].trim();

	return response.trim();
}

/**
 * Generate cache key for simulation results
 * Rounds followers to nearest 1k to improve cache hit rate
 */
function getSimulationCacheKey(input: SimulationInput): string {
	const roundedFollowers = Math.round(input.currentFollowers / 1000) * 1000;
	const settingsHash = JSON.stringify({
		freq: input.settings.postFrequency,
		carousel: input.settings.useCarousels,
		hooks: input.settings.useBoldHooks,
		hashtags: input.settings.useHashtags,
		reply: input.settings.replyToComments,
		timing: input.settings.postAtOptimalTimes,
		mix: input.settings.contentMix,
	});

	return `${roundedFollowers}-${settingsHash}`;
}

/**
 * Get cached simulation result if still valid
 */
function getCachedSimulation(input: SimulationInput): SimulationResult | null {
	const key = getSimulationCacheKey(input);
	const cached = simulationCache.get(key);

	if (cached && Date.now() - cached.timestamp < SIMULATION_CACHE_TTL) {
		logger.info("Using cached simulation result");
		return cached.data;
	}

	// Remove expired cache entry
	if (cached) {
		simulationCache.delete(key);
	}

	return null;
}

/**
 * Cache simulation result
 */
function cacheSimulation(
	input: SimulationInput,
	result: SimulationResult,
): void {
	const key = getSimulationCacheKey(input);
	simulationCache.set(key, {
		data: result,
		timestamp: Date.now(),
	});

	const now = Date.now();
	for (const [k, v] of simulationCache) {
		if (now - v.timestamp > SIMULATION_CACHE_TTL) {
			simulationCache.delete(k);
		}
	}

	if (simulationCache.size > 50) {
		const entries = Array.from(simulationCache.entries());
		entries.sort((a, b) => a[1].timestamp - b[1].timestamp);
		const toDelete = entries.slice(0, entries.length - 50);
		for (const [keyToDelete] of toDelete) {
			simulationCache.delete(keyToDelete);
		}
	}
}

// Load AI config from Supabase (always fresh)

export interface GrowthPlanData {
	totalFollowers: number;
	followerGrowth: number;
	totalViews: number;
	totalLikes: number;
	totalReplies: number;
	engagementRate: number;
	bestPostingTime: string;
	topTopic: string;
	postsByDay: Record<
		string,
		{ views: number; likes: number; replies: number; count: number }
	>;
	hashtags: Record<string, number>;
	postTimes: Record<number, { count: number; engagement: number }>;
	timePeriod: number;
}

export interface AIInsightsPrefs {
	goalPriority: "followers" | "engagement" | "posting_times" | "content_ideas";
	engagementBenchmark: number;
	viewToFollowBenchmark: number;
	tipFrequency: "daily" | "weekly" | "on_demand";
	excludeTopics: string[];
}

export interface GrowthPlanResult {
	insights: string;
	strengths: string;
	opportunities: string;
	recommendations: { priority: number; text: string }[];
	// Enhanced fields for detailed growth plan
	weeklySchedule?: {
        		day: string;
        		postCount: number;
        		bestTimes: string[];
        		contentFocus: string;
        	}[] | undefined;
	contentStrategy?: {
        		topPerformingType: string;
        		suggestedMix: { type: string; percentage: number }[];
        		hookStyles: string[];
        		avoidPatterns: string[];
        	} | undefined;
	engagementTactics?: {
        		replyStrategy: string;
        		hashtagStrategy: string;
        		ctaRecommendation: string;
        		communityTip: string;
        	} | undefined;
	milestones?: {
        		target: string;
        		metric: string;
        		timeframe: string;
        		actions: string[];
        	}[] | undefined;
	quickWins?: string[] | undefined;
}

/**
 * Generate content variations from a competitor's post
 * Used in the "Adapt & Post" feature for competitor analysis
 */

export const generateGrowthPlan = async (
	data: GrowthPlanData,
	userPrefs?: AIInsightsPrefs,
	aiContext?: AIContext,
): Promise<GrowthPlanResult | null> => {
	const prefs: AIInsightsPrefs = userPrefs || {
		goalPriority: "engagement",
		engagementBenchmark: 5,
		viewToFollowBenchmark: 2,
		tipFrequency: "daily",
		excludeTopics: [],
	};

	const dayNames = [
		"Sunday",
		"Monday",
		"Tuesday",
		"Wednesday",
		"Thursday",
		"Friday",
		"Saturday",
	];

	// Build day-of-week performance summary
	const dayPerformance: Record<string, { engagement: number; count: number }> =
		{};
	Object.entries(data.postsByDay).forEach(([dateStr, dayData]) => {
		const date = new Date(dateStr);
		const dayName = dayNames[date.getDay()] ?? "Unknown";
		if (!dayPerformance[dayName]) {
			dayPerformance[dayName] = { engagement: 0, count: 0 };
		}
		dayPerformance[dayName].engagement += dayData.likes + dayData.replies;
		dayPerformance[dayName].count += dayData.count;
	});

	// Find best and worst days
	let bestAvg = 0;
	let worstAvg = Infinity;
	const lowActivityDays: string[] = [];

	dayNames.forEach((day) => {
		const perf = dayPerformance[day];
		if (perf && perf.count > 0) {
			const avg = perf.engagement / perf.count;
			if (avg > bestAvg) {
				bestAvg = avg;
			}
			if (avg < worstAvg) {
				worstAvg = avg;
			}
		} else {
			lowActivityDays.push(day);
		}
	});

	// Find best hours
	const sortedHours = Object.entries(data.postTimes)
		.filter(([_, d]) => d.count > 0)
		.map(([hour, d]) => ({
			hour: parseInt(hour, 10),
			avgEng: d.engagement / d.count,
		}))
		.sort((a, b) => b.avgEng - a.avgEng);

	// Top hashtags
	const sortedHashtags = Object.entries(data.hashtags)
		.sort((a, b) => b[1] - a[1])
		.slice(0, 5)
		.map(([tag]) => `#${tag}`);

	// Map goal priority to focus area description
	const goalFocusMap: Record<string, string> = {
		followers: `PRIORITY: GROW FOLLOWERS. Focus tips on CTAs, viral hooks, and strategies to convert viewers to followers.`,
		engagement: `PRIORITY: BOOST ENGAGEMENT. Target engagement rate is ${prefs.engagementBenchmark}% (current: ${data.engagementRate.toFixed(2)}%). Focus on conversation starters and reply-bait.`,
		posting_times: `PRIORITY: OPTIMIZE TIMING. Focus tips heavily on WHEN to post based on the data.`,
		content_ideas: `PRIORITY: CONTENT IDEAS. Focus on creative content formats and trending topics.`,
	};

	// Calculate view-to-follower conversion rate
	const viewToFollowerRate =
		data.totalViews > 0
			? (
					(((data.followerGrowth / 100) * data.totalFollowers) /
						data.totalViews) *
					100
				).toFixed(3)
			: "0";

	// Build day performance context
	const dayPerformanceContext = dayNames
		.filter((day) => (dayPerformance[day]?.count ?? 0) > 0)
		.map((day) => {
			const perf = dayPerformance[day]!;
			const avg = (perf.engagement / perf.count).toFixed(1);
			return `${day}: ${perf.count} posts, ${avg} avg engagement`;
		})
		.join("\n");

	// Build hour performance context
	const hourPerformanceContext = sortedHours
		.slice(0, 8)
		.map((h) => {
			const ampm = h.hour >= 12 ? "PM" : "AM";
			const displayHour =
				h.hour > 12 ? h.hour - 12 : h.hour === 0 ? 12 : h.hour;
			return `${displayHour}${ampm}: ${h.avgEng.toFixed(1)} avg engagement`;
		})
		.join(", ");

	const aiContextSection = aiContext
		? `${contextToSystemPrompt(aiContext)}\n\n`
		: "";

	const prompt = `${aiContextSection}You are an elite social media strategist creating a DETAILED, SPECIFIC growth plan. Not generic advice - give EXACT numbers, days, times, and actionable tactics based on this account's real data.

${goalFocusMap[prefs.goalPriority]}

📊 ACCOUNT METRICS (Last ${data.timePeriod} days):
- Followers: ${data.totalFollowers.toLocaleString()}
- Growth Rate: ${data.followerGrowth > 0 ? "+" : ""}${data.followerGrowth.toFixed(2)}%
- Total Views: ${data.totalViews.toLocaleString()}
- Engagement Rate: ${data.engagementRate.toFixed(2)}%
- View-to-Follow Rate: ${viewToFollowerRate}%
- Posts Analyzed: ${Object.values(data.postsByDay).reduce((sum, d) => sum + d.count, 0)}

📅 DAY-BY-DAY PERFORMANCE:
${dayPerformanceContext || "No daily data available"}

⏰ HOUR-BY-HOUR PERFORMANCE (Best to Worst):
${hourPerformanceContext || "No hourly data available"}

🏷️ TOP HASHTAGS: ${sortedHashtags.length > 0 ? sortedHashtags.join(", ") : "None tracked"}

Based on this SPECIFIC data, create a comprehensive growth plan. Be SPECIFIC with numbers, percentages, and exact recommendations. NO generic advice.

Respond in this exact JSON format:
{
  "insights": "2-3 sentences analyzing the most important pattern in their data. Include specific numbers.",
  "strengths": "What's working well based on their actual metrics. Be specific about which days/times/content.",
  "opportunities": "The biggest gap or missed opportunity with specific improvement potential.",
  "recommendations": [
    {"priority": 1, "text": "Most impactful action with specific details (e.g., 'Post at 7PM on Tuesdays - your engagement is 3x higher')"},
    {"priority": 2, "text": "Second most important action with numbers"},
    {"priority": 3, "text": "Third action - specific and measurable"},
    {"priority": 4, "text": "Fourth action with clear next step"},
    {"priority": 5, "text": "Fifth action - quick win they can do today"}
  ],
  "weeklySchedule": [
    {"day": "Monday", "postCount": 1, "bestTimes": ["7PM", "12PM"], "contentFocus": "Motivational or week-starter content"},
    {"day": "Tuesday", "postCount": 2, "bestTimes": ["9AM", "6PM"], "contentFocus": "Educational or tips"},
    {"day": "Wednesday", "postCount": 1, "bestTimes": ["12PM"], "contentFocus": "Engagement-bait or questions"},
    {"day": "Thursday", "postCount": 2, "bestTimes": ["8AM", "7PM"], "contentFocus": "Personal stories or behind-the-scenes"},
    {"day": "Friday", "postCount": 1, "bestTimes": ["5PM"], "contentFocus": "Fun or weekend preview"},
    {"day": "Saturday", "postCount": 1, "bestTimes": ["10AM"], "contentFocus": "Lifestyle or casual"},
    {"day": "Sunday", "postCount": 1, "bestTimes": ["8PM"], "contentFocus": "Reflective or week preview"}
  ],
  "contentStrategy": {
    "topPerformingType": "Based on their data, what content type works best",
    "suggestedMix": [
      {"type": "Questions/Polls", "percentage": 30},
      {"type": "Personal stories", "percentage": 25},
      {"type": "Tips/Value", "percentage": 25},
      {"type": "Trending topics", "percentage": 20}
    ],
    "hookStyles": ["3 specific hook styles that would work for this account"],
    "avoidPatterns": ["2-3 content patterns to avoid based on low performance"]
  },
  "engagementTactics": {
    "replyStrategy": "Specific advice on how/when to reply to comments",
    "hashtagStrategy": "Specific hashtag advice based on their data",
    "ctaRecommendation": "Best CTA style for their audience",
    "communityTip": "How to build community around their content"
  },
  "milestones": [
    {"target": "Short-term goal", "metric": "e.g., 500 new followers", "timeframe": "2 weeks", "actions": ["Action 1", "Action 2"]},
    {"target": "Medium-term goal", "metric": "e.g., 5% engagement rate", "timeframe": "1 month", "actions": ["Action 1", "Action 2"]}
  ],
  "quickWins": [
    "Something they can do in the next 5 minutes",
    "A simple tweak to their next post",
    "An engagement tactic to try today"
  ]
}`;

	try {
		const response = await generateContent(prompt);

		// Parse JSON from response
		const jsonStr = extractJsonFromAiResponse(response);

		return JSON.parse(jsonStr) as GrowthPlanResult;
	} catch (error) {
		logger.error("Growth plan generation error:", error);
		return null;
	}
};

// ===== NEW AI TOOLS FOR INSPIRATION LIBRARY =====

/**
 * Generate multiple rephrase variations with different tones
 * Used in the AI Tools Panel for Inspiration Library
 */

export interface SimulationSettings {
	postFrequency: number;
	useCarousels: boolean;
	useBoldHooks: boolean;
	useHashtags: boolean;
	replyToComments: boolean;
	postAtOptimalTimes: boolean;
	contentMix: "text" | "mixed" | "media-heavy";
	mediaPercentage?: number | undefined; // 0-50% media usage

	// New Strategy Preset for Monte Carlo
	strategy?: "steady" | "aggressive" | "balanced" | undefined;

	// New Phase 3 settings
	collaborationsPerWeek?: number | undefined; // 0-5, +8% each
	jumpOnTrends?: boolean | undefined; // +25% boost
	threadLength?: "short" | "medium" | "long" | undefined; // long = +18%
	engageWithBigAccounts?: boolean | undefined; // +15% boost

	// Sensitivity analysis
	optimismFactor?: number | undefined; // 0.5 - 1.5 (pessimistic - realistic - optimistic)
	showConfidenceBands?: boolean | undefined; // Show ±15% variance
}

export interface SimulationInput {
	currentFollowers: number;
	currentAvgViews: number;
	currentEngagementRate: number;
	avgDailyPosts: number;
	topPerformingFormats: string[];
	historicalGrowthRate: number;
	settings: SimulationSettings;
}

export interface SimulationProjection {
	day: number;
	date: string;
	currentFollowers: number;
	projectedFollowers: number;
	currentViews: number;
	projectedViews: number;
	currentEngagement: number;
	projectedEngagement: number;

	// Confidence bands (±15% variance)
	upperBound?: number | undefined;
	lowerBound?: number | undefined;
}

export interface SimulationResult {
	projections: SimulationProjection[];
	summary: {
		followerUplift: number;
		viewsUplift: number;
		engagementUplift: number;
		projectedFollowers30d: number;
		projectedFollowers90d: number;
		projectedFollowers180d?: number | undefined; // New 180-day projection
		projectedViews30d: number;
		keyInsights: string[];
	};
	bestTimeHeatmap: {
		day: number;
		hour: number;
		score: number;
	}[];
}

/**
 * Generate AI-powered key insights for growth simulation
 * Uses Gemini AI to provide personalized, data-driven recommendations
 * Falls back to template insights if AI fails
 */
async function generateKeyInsights(
	input: SimulationInput,
	bestTimesResult: BestTimesResult,
	totalMultiplier: number,
	frequencyMultiplier: number,
): Promise<string[]> {
	// Generate fallback insights first (used if AI fails)
	const fallbackInsights = generateFallbackInsights(
		input,
		bestTimesResult,
		totalMultiplier,
		frequencyMultiplier,
	);

	// If user doesn't have enough post data, skip AI and return fallback
	if (!bestTimesResult.insights.hasEnoughData) {
		return fallbackInsights;
	}

	// Build AI prompt with real user data
	const prompt = `You are an expert Threads growth analyst. Analyze this user's posting data and provide 3 SPECIFIC, actionable insights:

CURRENT METRICS:
- Followers: ${input.currentFollowers.toLocaleString()}
- Posting frequency: ${input.avgDailyPosts.toFixed(1)} posts/day
- Engagement rate: ${input.currentEngagementRate.toFixed(2)}%
- Historical growth: ${input.historicalGrowthRate.toFixed(1)}% monthly
- Published posts analyzed: ${bestTimesResult.insights.postCount}

REAL POSTING PATTERNS (from user's ${bestTimesResult.insights.postCount} published posts):
- Best performing day: ${bestTimesResult.insights.bestDay}
- Best performing hour: ${bestTimesResult.insights.bestHour}:00
- Top performing formats: ${input.topPerformingFormats.join(", ") || "text posts"}

SIMULATION STRATEGY:
- Target frequency: ${input.settings.postFrequency} posts/day
- Using carousels: ${input.settings.useCarousels ? "Yes" : "No"}
- Using bold hooks: ${input.settings.useBoldHooks ? "Yes" : "No"}
- Replying to comments: ${input.settings.replyToComments ? "Yes" : "No"}
- Posting at optimal times: ${input.settings.postAtOptimalTimes ? "Yes" : "No"}
- Content mix: ${input.settings.contentMix}

PROJECTED IMPACT:
- Expected reach boost: ${Math.round((totalMultiplier - 1) * 100)}%
- Frequency increase boost: ${Math.round((frequencyMultiplier - 1) * 100)}%

Provide 3 insights that are:
1. Data-specific (reference actual numbers from user's patterns)
2. Immediately actionable
3. Focus on the biggest ROI opportunities

Return ONLY a JSON array of 3 strings, each under 120 characters. Example:
["Your ${bestTimesResult.insights.bestDay} posts get 2x engagement - schedule 50% of posts on that day", "Second insight", "Third insight"]`;

	try {
		const response = await generateContent(prompt);

		// Extract JSON from response
		const jsonStr = extractJsonFromAiResponse(response);

		// Parse JSON
		const insights = JSON.parse(jsonStr);

		// Validate response
		if (
			Array.isArray(insights) &&
			insights.length >= 3 &&
			insights.every((i) => typeof i === "string")
		) {
			return insights.slice(0, 3);
		} else {
			logger.warn("AI returned invalid insights format, using fallback");
			return fallbackInsights;
		}
	} catch (error) {
		logger.error("AI insights generation failed:", error);
		return fallbackInsights;
	}
}

/**
 * Generate fallback template-based insights
 * Used when AI fails or user has insufficient data
 */
function generateFallbackInsights(
	input: SimulationInput,
	bestTimesResult: BestTimesResult,
	_totalMultiplier: number,
	frequencyMultiplier: number,
): string[] {
	const insights: string[] = [];

	// Frequency insight
	const frequencyIncrease = input.settings.postFrequency - input.avgDailyPosts;
	if (frequencyIncrease > 1) {
		insights.push(
			`Increasing from ${input.avgDailyPosts.toFixed(1)} to ${input.settings.postFrequency} posts/day could boost reach by ${Math.round((frequencyMultiplier - 1) * 100)}%`,
		);
	}

	// Best time insight (use real data if available)
	if (
		bestTimesResult.insights.hasEnoughData &&
		input.settings.postAtOptimalTimes
	) {
		insights.push(
			`Your best posting time is ${bestTimesResult.insights.bestDay} at ${bestTimesResult.insights.bestHour}:00 based on ${bestTimesResult.insights.postCount} posts`,
		);
	} else if (input.settings.postAtOptimalTimes) {
		insights.push(
			"Benchmark estimate: peak-time posting can lift initial engagement, but this account needs more history before Juno can personalize the window.",
		);
	}

	// Carousel insight
	if (
		input.settings.useCarousels &&
		!input.topPerformingFormats.includes("carousel")
	) {
		insights.push(
			"Industry benchmark: carousel posts often outperform single images; treat this as a test until your own format history confirms it.",
		);
	}

	// Reply insight
	if (input.settings.replyToComments) {
		insights.push(
			"Replying to comments within 1 hour boosts algorithmic visibility",
		);
	}

	// Hook insight
	if (input.settings.useBoldHooks) {
		insights.push(
			"Strong hooks in the first line can increase read-through by 40%",
		);
	}

	// Default insight if nothing else applies
	if (insights.length === 0) {
		insights.push(
			"Current strategy is solid - consider experimenting with one variable at a time",
		);
	}

	// Return first 3 insights
	return insights.slice(0, 3);
}

/**
 * Generate growth simulation projections based on user settings
 * Uses a hybrid approach: deterministic calculations + AI insights
 */
export const generateGrowthSimulation = async (
	input: SimulationInput,
): Promise<SimulationResult | null> => {
	// Check cache first
	const cached = getCachedSimulation(input);
	if (cached) {
		return cached;
	}

	// Calculate multipliers based on settings
	const getFrequencyMultiplier = (freq: number, avgPosts: number): number => {
		const ratio = freq / Math.max(avgPosts, 1);
		// Diminishing returns above 3x increase
		if (ratio <= 1) return 1;
		if (ratio <= 2) return 1 + (ratio - 1) * 0.3;
		if (ratio <= 3) return 1.3 + (ratio - 2) * 0.2;
		return 1.5 + (ratio - 3) * 0.1;
	};

	// Strategy boost percentages are estimates derived from industry benchmarks:
	//   - Carousels +25%: Meta's 2024 data shows carousels get 1.4x reach vs single images;
	//     25% is conservative since engagement lift varies by niche (source: Socialinsider 2024)
	//   - Bold hooks +15%: A/B testing across creator accounts shows strong first-line hooks
	//     increase read-through rate by 30-40%; the 15% engagement lift is the downstream effect
	//   - Hashtags +10%: Threads/Instagram hashtag reach boost is modest (3-15% range);
	//     10% reflects the average for accounts with <100k followers
	//   - Reply to comments +20%: Algorithmic reward for creator replies is well-documented;
	//     accounts that reply within 1hr see ~20% more impressions on subsequent posts
	//   - Optimal timing +18%: Posting during audience peak hours vs random times;
	//     based on analysis of 50k+ posts across time zones (Sprout Social 2024)
	//   - Media-heavy +30%: Visual-first content gets significantly more reach on both platforms;
	//     mixed content (+15%) still outperforms text-only but less dramatically
	//   - Collaborations +8% each: Cross-pollination effect per collab partner
	//   - Trend jumping +25%: Early trend adoption gives algorithmic priority
	//   - Long threads +18%: Multi-part threads get boosted by Threads algorithm for depth
	//   - Big account engagement +15%: Replies to large accounts expose you to their audience
	const carouselBoost = input.settings.useCarousels ? 1.25 : 1;
	const hookBoost = input.settings.useBoldHooks ? 1.15 : 1;
	const hashtagBoost = input.settings.useHashtags ? 1.1 : 1;
	const replyBoost = input.settings.replyToComments ? 1.2 : 1;
	const timingBoost = input.settings.postAtOptimalTimes ? 1.18 : 1;
	const contentMixMultiplier =
		input.settings.contentMix === "media-heavy"
			? 1.3
			: input.settings.contentMix === "mixed"
				? 1.15
				: 1;

	// Phase 3 multipliers (same benchmark methodology as above)
	const collaborationsBoost =
		1 + (input.settings.collaborationsPerWeek || 0) * 0.08;
	const trendsBoost = input.settings.jumpOnTrends ? 1.25 : 1;
	const threadLengthBoost =
		input.settings.threadLength === "long"
			? 1.18
			: input.settings.threadLength === "medium"
				? 1.08
				: 1;
	const bigAccountsBoost = input.settings.engageWithBigAccounts ? 1.15 : 1;

	// Optimism factor (default 1.0 = realistic)
	const optimismFactor = input.settings.optimismFactor || 1.0;

	const frequencyMultiplier = getFrequencyMultiplier(
		input.settings.postFrequency,
		input.avgDailyPosts,
	);

	// Compound multiplier (capped at 3.0x to accommodate new strategies)
	const baseMultiplier =
		frequencyMultiplier *
		carouselBoost *
		hookBoost *
		hashtagBoost *
		replyBoost *
		timingBoost *
		contentMixMultiplier *
		collaborationsBoost *
		trendsBoost *
		threadLengthBoost *
		bigAccountsBoost;

	const totalMultiplier = Math.min(baseMultiplier * optimismFactor, 3.0);

	// Base daily growth rates
	const baseFollowerGrowthRate = Math.max(
		input.historicalGrowthRate / 30,
		0.001,
	); // daily
	const projectedDailyGrowth = baseFollowerGrowthRate * totalMultiplier;

	// Generate 180-day projections (extended from 90 days)
	const projections: SimulationProjection[] = [];
	const currentDate = new Date();
	const showConfidenceBands = input.settings.showConfidenceBands || false;

	// Monte Carlo-style variance estimation for confidence bands.
	// We run N simplified simulation paths with randomized daily growth jitter
	// to compute the standard deviation at each day, then use 1.96 * sigma
	// for 95% confidence intervals (instead of the previous hardcoded +/-15%).
	const NUM_MONTE_CARLO_RUNS = 50;
	const monteCarloResults: number[][] = []; // [day][run] = follower count

	if (showConfidenceBands) {
		// Seed a simple deterministic PRNG for reproducibility (based on input hash)
		const seedVal =
			input.currentFollowers + input.settings.postFrequency * 1000;
		let prngState = seedVal;
		const nextRandom = () => {
			// Simple LCG for deterministic pseudo-random numbers
			prngState = (prngState * 1664525 + 1013904223) & 0x7fffffff;
			return prngState / 0x7fffffff;
		};

		for (let run = 0; run < NUM_MONTE_CARLO_RUNS; run++) {
			const runResults: number[] = [];
			let followers = input.currentFollowers;
			for (let day = 1; day <= 180; day++) {
				// Add daily jitter: normal-ish distribution via Box-Muller approximation
				const u1 = Math.max(0.0001, nextRandom());
				const u2 = nextRandom();
				const normalRandom =
					Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
				// Daily growth with variance proportional to the growth rate itself
				const jitteredGrowth = projectedDailyGrowth * (1 + normalRandom * 0.3);
				followers = Math.max(0, followers * (1 + jitteredGrowth));
				runResults.push(Math.round(followers));
			}
			monteCarloResults.push(runResults);
		}
	}

	for (let day = 1; day <= 180; day++) {
		const date = new Date(currentDate);
		date.setDate(date.getDate() + day);

		// Compound growth with some variance
		const compoundFactor = (1 + projectedDailyGrowth) ** day;
		const baseFactor = (1 + baseFollowerGrowthRate) ** day;

		const projectedFollowers = Math.round(
			input.currentFollowers * compoundFactor,
		);
		const currentFollowers = Math.round(input.currentFollowers * baseFactor);

		// 95% confidence bands using Monte Carlo standard deviation (1.96 * sigma)
		let upperBound: number | undefined;
		let lowerBound: number | undefined;
		if (showConfidenceBands && monteCarloResults.length > 0) {
			const dayValues = monteCarloResults
				.map((run) => run[day - 1])
				.filter((value): value is number => value !== undefined);
			if (dayValues.length === 0) continue;
			const mean = dayValues.reduce((s, v) => s + v, 0) / dayValues.length;
			const variance =
				dayValues.reduce((s, v) => s + (v - mean) ** 2, 0) / dayValues.length;
			const sigma = Math.sqrt(variance);
			upperBound = Math.round(projectedFollowers + 1.96 * sigma);
			lowerBound = Math.max(0, Math.round(projectedFollowers - 1.96 * sigma));
		}

		// Views scale with follower growth and tactics, not exponentially with time
		// Guard against division by zero when currentFollowers is 0
		const safeCurrentFollowers = Math.max(input.currentFollowers, 1);
		const followerGrowthFactor = projectedFollowers / safeCurrentFollowers;
		const viewsMultiplier = totalMultiplier * followerGrowthFactor;
		const projectedViews = Math.round(input.currentAvgViews * viewsMultiplier);
		const currentViews = Math.round(
			input.currentAvgViews * (currentFollowers / safeCurrentFollowers),
		);

		// Engagement rate tends to decrease as accounts grow (diminishing returns)
		const engagementBoost =
			replyBoost - 1 + (hookBoost - 1) + (carouselBoost - 1) * 0.5;
		const followerScaleFactor = Math.max(
			0.7,
			1 - (projectedFollowers / safeCurrentFollowers - 1) * 0.1,
		); // ER drops 10% per 100% follower growth
		const boostedEngagement =
			input.currentEngagementRate * (1 + engagementBoost) * followerScaleFactor;
		const projectedEngagement = Math.min(boostedEngagement, 20); // More realistic cap

		projections.push({
			day,
			date: date.toISOString().split("T")[0]! ?? date.toISOString(),
			currentFollowers,
			projectedFollowers,
			currentViews,
			projectedViews,
			currentEngagement: input.currentEngagementRate,
			projectedEngagement,
			upperBound,
			lowerBound,
		});
	}

	// Generate best time heatmap based on user's actual post performance
	// Note: Gets ALL posts to analyze overall posting patterns across all accounts
	let bestTimesResult: BestTimesResult;
	try {
		const publishedPosts = await dataService.getPublishedPostsForAI({
			limit: 500,
		});
		bestTimesResult = await analyzeBestPostingTimes(publishedPosts);
	} catch (error) {
		logger.error("Failed to analyze best posting times:", error);
		// Fallback to analyzing empty array (will return default heatmap)
		bestTimesResult = await analyzeBestPostingTimes([]);
	}

	const bestTimeHeatmap = bestTimesResult.heatmap;

	// Calculate summary stats - use safe array access with fallbacks
	const day30 =
		projections.find((p) => p.day === 30) ||
		projections[Math.min(29, projections.length - 1)]!;
	const day90 =
		projections.find((p) => p.day === 90) ||
		projections[Math.min(89, projections.length - 1)]!;
	const day180 = projections.find((p) => p.day === 180);

	const followerUplift =
		((day30.projectedFollowers - day30.currentFollowers) /
			day30.currentFollowers) *
		100;
	const viewsUplift = (totalMultiplier - 1) * 100;
	const engagementUplift =
		((day30.projectedEngagement - input.currentEngagementRate) /
			input.currentEngagementRate) *
		100;

	// Generate AI-powered insights based on real data
	const keyInsights = await generateKeyInsights(
		input,
		bestTimesResult,
		totalMultiplier,
		frequencyMultiplier,
	);

	const result: SimulationResult = {
		projections,
		summary: {
			followerUplift: Math.round(followerUplift * 10) / 10,
			viewsUplift: Math.round(viewsUplift * 10) / 10,
			engagementUplift: Math.round(engagementUplift * 10) / 10,
			projectedFollowers30d: day30.projectedFollowers,
			projectedFollowers90d: day90.projectedFollowers,
			projectedFollowers180d: day180?.projectedFollowers,
			projectedViews30d: Math.round(day30.projectedViews),
			keyInsights,
		},
		bestTimeHeatmap,
	};

	// Cache the result for 1 hour
	cacheSimulation(input, result);

	return result;
};

/**
 * Get AI-powered insights for the simulation
 * This adds qualitative analysis on top of the quantitative projections
 */
export const getSimulationInsights = async (
	input: SimulationInput,
	result: SimulationResult,
): Promise<string[]> => {
	const frequencyIncrease = input.settings.postFrequency - input.avgDailyPosts;
	const isIncreasingFrequency = frequencyIncrease > 0;
	const activeStrategies = [
		input.settings.useCarousels && "carousels",
		input.settings.useBoldHooks && "bold hooks",
		input.settings.postAtOptimalTimes && "optimal timing",
		input.settings.replyToComments && "comment replies",
		input.settings.contentMix !== "text" &&
			`${input.settings.contentMix} content`,
	].filter(Boolean);

	const prompt = `You are an elite Threads growth strategist with years of experience scaling accounts to 100k+ followers. Analyze this growth simulation and provide 4 HIGHLY SPECIFIC, data-driven insights:

ACCOUNT METRICS:
- Current Followers: ${input.currentFollowers.toLocaleString()}
- Daily Views: ${input.currentAvgViews.toLocaleString()}
- Engagement Rate: ${input.currentEngagementRate.toFixed(2)}%
- Current Posting: ${input.avgDailyPosts.toFixed(1)} posts/day
- Historical Growth: ${input.historicalGrowthRate.toFixed(1)}% monthly

SIMULATION STRATEGY:
- Target Frequency: ${input.settings.postFrequency} posts/day ${isIncreasingFrequency ? `(+${frequencyIncrease.toFixed(1)} from current)` : "(same as current)"}
- Active Tactics: ${activeStrategies.length > 0 ? activeStrategies.join(", ") : "baseline approach"}
- Content Mix: ${input.settings.contentMix}

30-DAY PROJECTIONS:
- Follower Growth: +${result.summary.followerUplift.toFixed(1)}% (${(input.currentFollowers * (result.summary.followerUplift / 100)).toFixed(0)} new followers)
- Views Increase: +${result.summary.viewsUplift.toFixed(1)}%
- Engagement Lift: +${result.summary.engagementUplift.toFixed(1)}%

TASK: Provide 4 insights that are:
1. SPECIFIC to these exact numbers (not generic advice)
2. ACTIONABLE with clear next steps
3. STRATEGIC - focus on what will move the needle most
4. Include ONE realistic caution about this approach

Format each insight as a single punchy sentence (max 100 chars). Be direct and tactical.

Examples of GOOD insights:
- "With 3 posts/day, you'll hit 10k followers in 45 days if engagement holds at 4.2%"
- "Your 2.1% ER is below the 3.5% benchmark—add CTAs to boost it or follower growth will plateau"
- "Carousels + optimal timing could 2x your reach, but posting at 9 PM might not fit your audience"

Examples of BAD (too generic) insights:
- "Post consistently to grow your account"
- "Engagement is important for success"
- "Try using carousels"

Return ONLY a JSON array of exactly 4 strings:
["Tactical insight with specific numbers", "Strategic recommendation", "Risk/caution about this approach", "Next immediate action to take"]`;

	try {
		const response = await generateContent(prompt);

		const jsonStr = extractJsonFromAiResponse(response);

		const insights = JSON.parse(jsonStr);
		return Array.isArray(insights) ? insights : result.summary.keyInsights;
	} catch (error) {
		logger.error("Failed to get AI simulation insights:", error);
		return result.summary.keyInsights;
	}
};

// ===== NEXT POST IDEAS GENERATOR =====

export interface GrowthDiagnosisInput {
	// Account metrics
	currentFollowers: number;
	followerGrowthRate: number; // percentage over period
	totalViews: number;
	totalLikes: number;
	totalReplies: number;
	totalReposts: number;
	totalShares: number;
	engagementRate: number;

	// Post data
	totalPosts: number;
	avgPostsPerDay: number;

	// Top performing posts
	topPosts: {
		content: string;
		views: number;
		likes: number;
		replies: number;
		shares: number;
		publishedAt: string;
		mediaType?: "text" | "image" | "video" | "carousel" | "reels" | undefined;
	}[];

	// Timing data
	postsByDayOfWeek: Record<string, { count: number; engagement: number }>;
	postsByHour: Record<number, { count: number; engagement: number }>;

	// Content patterns
	hashtags: Record<string, number>;
	avgPostLength: number;
	mediaUsageRate: number; // percentage of posts with media

	// Period info
	periodDays: number;
	accountHandle: string;

	// Phase 3.1 - Competitor benchmarking
	competitorBenchmarks?: {
        		avgFollowerCount: number;
        		avgEngagementRate: number;
        		avgPostFrequency: number;
        		competitorCount: number;
        	} | null | undefined;
}

export interface DiagnosisCategory {
	title: string;
	emoji: string;
	items: {
		insight: string;
		metric?: string | undefined;
		confidence: "high" | "medium" | "low";
		actionable: boolean;
		action?: string | undefined;
		draftPrompt?: string | undefined; // Prompt to generate a post based on this insight
	}[];
}

export interface GrowthDiagnosisResult {
	strengths: DiagnosisCategory;
	weaknesses: DiagnosisCategory;
	opportunities: DiagnosisCategory;
	predictions: {
		followers30d: number;
		followers90d: number;
		engagementTrend: "up" | "down" | "stable";
		viralPotential: number; // 0-100
		insights: string[];
	};
	quickWins: {
		action: string;
		impact: "high" | "medium" | "low";
		effort: "low" | "medium" | "high";
		draftPrompt?: string | undefined;
	}[];
	generatedAt: string;
	dataQuality: "excellent" | "good" | "limited";
}

/**
 * Generate comprehensive AI-powered growth diagnosis
 * Analyzes user's own data to provide SWOT-style insights
 */
export const generateGrowthDiagnosis = async (
	input: GrowthDiagnosisInput,
): Promise<GrowthDiagnosisResult | null> => {
	// Calculate data quality score
	const dataQuality =
		input.totalPosts >= 30
			? "excellent"
			: input.totalPosts >= 10
				? "good"
				: "limited";

	// Find best day and hour
	const bestDay = Object.entries(input.postsByDayOfWeek)
		.filter(([_, d]) => d.count > 0)
		.sort(
			(a, b) => b[1].engagement / b[1].count - a[1].engagement / a[1].count,
		)[0];

	const bestHour = Object.entries(input.postsByHour)
		.filter(([_, d]) => d.count > 0)
		.map(([hour, d]) => ({
			hour: parseInt(hour, 10),
			avgEng: d.engagement / d.count,
		}))
		.sort((a, b) => b.avgEng - a.avgEng)[0];

	// Find top hashtags
	const topHashtags = Object.entries(input.hashtags)
		.sort((a, b) => b[1] - a[1])
		.slice(0, 5)
		.map(([tag]) => `#${tag}`);

	// Analyze top posts for patterns
	const topPostPatterns = input.topPosts.slice(0, 5).map((p) => ({
		length: p.content.length,
		hasQuestion: p.content.includes("?"),
		hasEmoji: /[\u{1F300}-\u{1F9FF}]/u.test(p.content),
		hasMedia: p.mediaType && p.mediaType !== "text",
		engagement: p.likes + p.replies + p.shares,
	}));

	const avgTopPostLength =
		topPostPatterns.length > 0
			? topPostPatterns.reduce((s, p) => s + p.length, 0) /
				topPostPatterns.length
			: 0;
	const questionRate =
		topPostPatterns.filter((p) => p.hasQuestion).length /
		Math.max(topPostPatterns.length, 1);
	const emojiRate =
		topPostPatterns.filter((p) => p.hasEmoji).length /
		Math.max(topPostPatterns.length, 1);

	// Build context for AI
	const topPostsContext = input.topPosts
		.slice(0, 5)
		.map(
			(p, i) =>
				`${i + 1}. "${p.content.slice(0, 150)}..." (${p.views} views, ${p.likes} likes, ${p.replies} replies)`,
		)
		.join("\n");

	const prompt = `You are an elite Threads growth strategist analyzing @${input.accountHandle}'s account. Generate a comprehensive SWOT-style growth diagnosis.

ACCOUNT METRICS (Last ${input.periodDays} days):
- Current Followers: ${input.currentFollowers.toLocaleString()}
- Follower Growth: ${input.followerGrowthRate >= 0 ? "+" : ""}${input.followerGrowthRate.toFixed(1)}%
- Total Views: ${input.totalViews.toLocaleString()}
- Engagement Rate: ${(input.engagementRate * 100).toFixed(2)}%
- Total Posts: ${input.totalPosts} (${input.avgPostsPerDay.toFixed(1)}/day avg)
- Media Usage: ${(input.mediaUsageRate * 100).toFixed(0)}% of posts

ENGAGEMENT BREAKDOWN:
- Likes: ${input.totalLikes.toLocaleString()}
- Replies: ${input.totalReplies.toLocaleString()}
- Reposts: ${input.totalReposts.toLocaleString()}
- Shares: ${input.totalShares.toLocaleString()}

${
	input.competitorBenchmarks
		? `COMPETITOR BENCHMARKS (${input.competitorBenchmarks.competitorCount} competitors tracked):
- Avg Competitor Followers: ${input.competitorBenchmarks.avgFollowerCount.toLocaleString()}
- Your Followers vs Avg: ${input.currentFollowers > input.competitorBenchmarks.avgFollowerCount ? `+${((input.currentFollowers / input.competitorBenchmarks.avgFollowerCount - 1) * 100).toFixed(1)}%` : `-${((1 - input.currentFollowers / input.competitorBenchmarks.avgFollowerCount) * 100).toFixed(1)}%`} ${input.currentFollowers > input.competitorBenchmarks.avgFollowerCount ? "(AHEAD)" : "(BEHIND)"}
- Avg Competitor Engagement: ${input.competitorBenchmarks.avgEngagementRate.toFixed(2)}%
- Your Engagement vs Avg: ${input.engagementRate * 100 > input.competitorBenchmarks.avgEngagementRate ? `+${(input.engagementRate * 100 - input.competitorBenchmarks.avgEngagementRate).toFixed(2)}%` : `-${(input.competitorBenchmarks.avgEngagementRate - input.engagementRate * 100).toFixed(2)}%`} ${input.engagementRate * 100 > input.competitorBenchmarks.avgEngagementRate ? "(OUTPERFORMING)" : "(UNDERPERFORMING)"}
- Avg Competitor Posting Freq: ~${input.competitorBenchmarks.avgPostFrequency} posts/day

**Use these benchmarks to provide competitive insights in your analysis.**
`
		: ""
}
TOP PERFORMING POSTS:
${topPostsContext || "No data available"}

PATTERNS DETECTED:
- Best Day: ${bestDay ? `${bestDay[0]} (${(bestDay[1].engagement / bestDay[1].count).toFixed(0)} avg engagement)` : "Not enough data"}
- Best Hour: ${bestHour ? `${bestHour.hour}:00 (${bestHour.avgEng.toFixed(0)} avg engagement)` : "Not enough data"}
- Top Hashtags: ${topHashtags.length > 0 ? topHashtags.join(", ") : "None detected"}
- Avg Post Length: ${Math.round(input.avgPostLength)} chars
- Top Posts Avg Length: ${Math.round(avgTopPostLength)} chars
- Question Rate in Top Posts: ${(questionRate * 100).toFixed(0)}%
- Emoji Rate in Top Posts: ${(emojiRate * 100).toFixed(0)}%

DATA QUALITY: ${dataQuality.toUpperCase()}

TASK: Generate a detailed growth diagnosis in this EXACT JSON format. Be SPECIFIC with numbers and actionable advice:

{
  "strengths": {
    "title": "Strengths",
    "emoji": "💪",
    "items": [
      {
        "insight": "Specific strength with data (e.g., 'Your question-based posts get 2.3x more replies')",
        "metric": "Optional metric to display (e.g., '2.3x replies')",
        "confidence": "high|medium|low",
        "actionable": true,
        "action": "How to leverage this (e.g., 'Add a question to every post')",
        "draftPrompt": "Optional: prompt to generate a post leveraging this strength"
      }
    ]
  },
  "weaknesses": {
    "title": "Weaknesses",
    "emoji": "🎯",
    "items": [
      {
        "insight": "Specific weakness with data",
        "metric": "Optional metric",
        "confidence": "high|medium|low",
        "actionable": true,
        "action": "How to improve",
        "draftPrompt": "Optional: prompt to generate a post addressing this"
      }
    ]
  },
  "opportunities": {
    "title": "Opportunities",
    "emoji": "🚀",
    "items": [
      {
        "insight": "Untapped opportunity based on data",
        "metric": "Potential impact",
        "confidence": "high|medium|low",
        "actionable": true,
        "action": "Specific next step",
        "draftPrompt": "Optional: prompt for opportunity-focused post"
      }
    ]
  },
  "predictions": {
    "followers30d": 1234,
    "followers90d": 5678,
    "engagementTrend": "up|down|stable",
    "viralPotential": 65,
    "insights": ["Prediction insight 1", "Prediction insight 2"]
  },
  "quickWins": [
    {
      "action": "Immediate action to take",
      "impact": "high|medium|low",
      "effort": "low|medium|high",
      "draftPrompt": "Optional: prompt for quick-win post"
    }
  ]
}

REQUIREMENTS:
1. Each category should have 2-4 items
2. Be SPECIFIC - use actual numbers from the data
3. Include draftPrompt for actionable items that could lead to posts
4. Predictions should be realistic based on current trajectory
5. Quick wins should be low-effort, high-impact actions
6. Confidence levels: high (based on strong data), medium (some data), low (limited data)

Return ONLY valid JSON, no markdown or explanation.`;

	try {
		const response = await generateContent(prompt, undefined, {
			responseMimeType: "application/json",
			maxTokens: 4096,
		});

		// Parse JSON from response with robust repair
		const jsonStr = extractJsonFromAiResponse(response);

		let diagnosis: GrowthDiagnosisResult | null = null;

		// Attempt 1: direct parse
		try {
			diagnosis = JSON.parse(jsonStr);
		} catch {
			// Attempt 2: extract first { to last }
			const firstBrace = jsonStr.indexOf("{");
			const lastBrace = jsonStr.lastIndexOf("}");
			if (firstBrace !== -1 && lastBrace > firstBrace) {
				try {
					diagnosis = JSON.parse(jsonStr.slice(firstBrace, lastBrace + 1));
				} catch {
					// Attempt 3: truncate to last complete } and retry
					const truncated = jsonStr.slice(firstBrace);
					for (let i = truncated.length - 1; i >= 0; i--) {
						if (truncated[i] === "}") {
							try {
								diagnosis = JSON.parse(truncated.slice(0, i + 1));
								break;
							} catch {}
						}
					}
				}
			}
		}

		if (!diagnosis) {
			logger.error("Growth diagnosis JSON repair failed, returning fallback");
			return {
				generation_error: true,
				strengths: { title: "Strengths", emoji: "💪", items: [] },
				weaknesses: { title: "Weaknesses", emoji: "⚠️", items: [] },
				opportunities: { title: "Opportunities", emoji: "🎯", items: [] },
				predictions: {
					followers30d: 0,
					followers90d: 0,
					engagementTrend: "stable" as const,
					viralPotential: 0,
					insights: [
						"Analysis could not be fully generated. Please try again.",
					],
				},
				quickWins: [],
				generatedAt: new Date().toISOString(),
				dataQuality,
			} as GrowthDiagnosisResult & { generation_error: boolean };
		}

		// Add metadata
		return {
			...diagnosis,
			generatedAt: new Date().toISOString(),
			dataQuality,
		};
	} catch (error) {
		logger.error("Growth diagnosis parsing error:", error);
		return {
			generation_error: true,
			strengths: { title: "Strengths", emoji: "💪", items: [] },
			weaknesses: { title: "Weaknesses", emoji: "⚠️", items: [] },
			opportunities: { title: "Opportunities", emoji: "🎯", items: [] },
			predictions: {
				followers30d: 0,
				followers90d: 0,
				engagementTrend: "stable" as const,
				viralPotential: 0,
				insights: ["Analysis encountered an error. Please try again."],
			},
			quickWins: [],
			generatedAt: new Date().toISOString(),
			dataQuality: "limited",
		} as GrowthDiagnosisResult & { generation_error: boolean };
	}
};

/**
 * Generate a post draft based on a diagnosis insight
 */
export const generateDiagnosisDraft = async (
	draftPrompt: string,
	userStyle?: "casual" | "professional" | "witty" | "inspirational" | "edgy",
	voiceProfile?: VoiceProfile,
	aiContext?: AIContext,
): Promise<string | null> => {
	let voiceContext = "";
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		const vp = voiceProfile ?? (await loadVoiceProfile());
		voiceContext = vp ? buildVoiceContext(vp) : "";
	}
	const styleGuide = userStyle
		? {
				casual: "Use conversational, friendly language. Keep it relatable.",
				professional: "Polished but approachable. Clear value proposition.",
				witty: "Clever wordplay, unexpected twists, or subtle humor.",
				inspirational: "Uplifting and motivating. Paint a vision.",
				edgy: "Bold and provocative. Challenge conventional thinking.",
			}[userStyle]
		: "Use a natural, engaging tone.";

	const prompt = `You are a viral content creator for Threads. Generate a post based on this strategy:
${voiceContext}
STRATEGY: ${draftPrompt}

STYLE: ${styleGuide}

REQUIREMENTS:
1. Under 500 characters
2. Start with a scroll-stopping hook
3. Include 1-2 relevant emojis naturally
4. End with engagement driver (question, CTA, or provocative statement)
5. Sound authentic and human, not AI-generated

Return ONLY the post text, nothing else.`;

	try {
		const response = await generateContent(prompt);

		return response.trim();
	} catch (error) {
		logger.error("Draft generation error:", error);
		return null;
	}
};

// ===== POST ANALYSIS AI FUNCTIONS =====

export interface GoalProgress {
	goalType:
		| "followers"
		| "engagement"
		| "views"
		| "posts"
		| "engagement_rate"
		| "weekly_posts"
		| "weekly_views"
		| "daily_replies"
		| "monthly_posts"
		| "viral_post"
		| "collaboration"
		| "custom";
	goalName: string;
	current: number;
	target: number;
	progress: number; // 0-100
	trend: "up" | "down" | "flat";
	daysRemaining?: number | undefined;
	id?: string | undefined; // For custom goals
}

export interface CoachingInsight {
	message: string;
	priority: "urgent" | "important" | "suggestion";
	actionType: "post_more" | "engage_more" | "timing" | "content" | "celebrate";
	suggestedAction?: string | undefined;
}

/**
 * Generate personalized AI coaching insights based on goal progress
 */
export const generateGoalCoaching = async (
	goals: GoalProgress[],
	postingStreak: number,
	recentPostCount: number,
	avgEngagementRate: number,
): Promise<CoachingInsight[]> => {
	// First, generate deterministic insights based on data
	const insights: CoachingInsight[] = [];

	// Check each goal and generate insights
	for (const goal of goals) {
		if (goal.progress >= 100) {
			// Goal achieved!
			insights.push({
				message: `You hit your ${goal.goalName} goal! Time to set a new target.`,
				priority: "suggestion",
				actionType: "celebrate",
				suggestedAction: "Update your goal to keep growing",
			});
		} else if (
			goal.progress < 25 &&
			goal.daysRemaining &&
			goal.daysRemaining < 7
		) {
			// Urgent - far behind with little time
			const deficit = goal.target - goal.current;
			insights.push({
				message: `You're ${100 - goal.progress}% behind on ${goal.goalName}. Need ${deficit.toLocaleString()} more to hit your goal.`,
				priority: "urgent",
				actionType:
					goal.goalType === "posts"
						? "post_more"
						: goal.goalType === "engagement"
							? "engage_more"
							: "content",
				suggestedAction:
					goal.goalType === "posts"
						? `Try to post ${Math.ceil(deficit / Math.max(goal.daysRemaining, 1))} times per day`
						: goal.goalType === "engagement"
							? "Reply to more comments and ask questions in your posts"
							: "Focus on content that resonates with your audience",
			});
		} else if (goal.progress < 50 && goal.trend === "down") {
			// Behind and trending down
			insights.push({
				message: `Your ${goal.goalName} is trending down. You're at ${goal.progress}% of your goal.`,
				priority: "important",
				actionType: "content",
				suggestedAction: "Try mixing up your content format or posting times",
			});
		} else if (goal.progress >= 80 && goal.progress < 100) {
			// Almost there!
			const remaining = goal.target - goal.current;
			insights.push({
				message: `Almost there! Just ${remaining.toLocaleString()} more ${goal.goalType === "posts" ? "posts" : goal.goalType === "followers" ? "followers" : goal.goalType === "views" ? "views" : "%"} to hit your ${goal.goalName} goal.`,
				priority: "suggestion",
				actionType: "post_more",
				suggestedAction: "Keep up the momentum with consistent posting",
			});
		}
	}

	// Streak-based insights
	if (postingStreak === 0) {
		insights.push({
			message: "You haven't posted today. Start a streak to build momentum!",
			priority: "important",
			actionType: "post_more",
			suggestedAction: "Post at least once to start your streak",
		});
	} else if (postingStreak >= 7) {
		insights.push({
			message: `🔥 ${postingStreak}-day streak! You're on fire. Keep it going!`,
			priority: "suggestion",
			actionType: "celebrate",
		});
	} else if (postingStreak >= 3) {
		insights.push({
			message: `Nice! ${postingStreak}-day posting streak. ${7 - postingStreak} more days to hit a week!`,
			priority: "suggestion",
			actionType: "post_more",
		});
	}

	// Engagement insights
	if (avgEngagementRate < 2) {
		insights.push({
			message:
				"Your engagement rate is below average. Try asking questions or sharing personal stories.",
			priority: "important",
			actionType: "engage_more",
			suggestedAction: "Add a question at the end of your next post",
		});
	} else if (avgEngagementRate >= 5) {
		insights.push({
			message: `Great engagement! ${avgEngagementRate.toFixed(1)}% is above average. Your content is resonating.`,
			priority: "suggestion",
			actionType: "celebrate",
		});
	}

	// Try to get AI-enhanced insight if available
	try {
		const goalsContext = goals
			.map(
				(g) =>
					`${g.goalName}: ${g.current}/${g.target} (${g.progress}%, trend: ${g.trend})`,
			)
			.join("\n");

		const prompt = `You are a brief, punchy social media coach. Based on this data, give ONE short actionable tip (max 15 words):

Goals:
${goalsContext}

Posting streak: ${postingStreak} days
Recent posts (7d): ${recentPostCount}
Engagement rate: ${avgEngagementRate.toFixed(1)}%

Return ONLY the tip, no explanation. Be specific and actionable. Use casual language.`;

		const response = await generateContent(prompt);
		if (response && response.length < 100) {
			insights.unshift({
				message: response.trim(),
				priority: "suggestion",
				actionType: "content",
			});
		}
	} catch {
		// AI insight failed, use deterministic insights only
	}

	// Return top 3 most relevant insights
	return insights
		.sort((a, b) => {
			const priorityOrder = { urgent: 0, important: 1, suggestion: 2 };
			return priorityOrder[a.priority] - priorityOrder[b.priority];
		})
		.slice(0, 3);
};

/**
 * Calculate projected goal completion date based on current progress
 */
export const projectGoalCompletion = (
	current: number,
	target: number,
	dailyGrowthRate: number,
): { daysToComplete: number; projectedDate: Date } | null => {
	if (current >= target) {
		return { daysToComplete: 0, projectedDate: new Date() };
	}

	if (dailyGrowthRate <= 0) {
		return null; // Can't project with no growth
	}

	const remaining = target - current;
	const daysToComplete = Math.ceil(remaining / dailyGrowthRate);

	const projectedDate = new Date();
	projectedDate.setDate(projectedDate.getDate() + daysToComplete);

	return { daysToComplete, projectedDate };
};

// ============================================================================
// REPLY ASSISTANT - AI-powered reply suggestions and sentiment analysis
// ============================================================================
