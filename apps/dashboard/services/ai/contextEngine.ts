/**
 * AIContextEngine -- Unified context builder for all AI features
 *
 * Every AI feature is just a different prompt template + this context.
 * Instead of each feature independently fetching user data, analytics,
 * and history, this engine builds a rich context object once.
 *
 * Usage:
 *   const ctx = await buildAIContext(userId, accountId, "threads", CONTEXT_PRESETS.contentGeneration);
 *   const systemSection = contextToSystemPrompt(ctx);
 *   // Prepend systemSection to any AI prompt
 */

import type { Platform } from "../../src/types/platform.js";
import type { PostStatus, ThreadPost } from "../../types.js";
import { analyzeBestPostingTimes } from "../../utils/bestTimesAnalysis.js";
import { logger } from "@/utils/logger";
import { type CompetitorPost, competitorService } from "../competitorService.js";
import { dataService } from "../dataService.js";
import type { VoiceProfile } from "./types.js";
import { loadVoiceProfile } from "./voiceHelpers.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AIContext {
	// User & Account
	userId: string;
	accountId: string;
	platform: Platform;
	username: string;
	followerCount: number;

	// Recent Performance (last 7 days)
	recentMetrics: {
		avgEngagementRate: number;
		totalViews: number;
		totalPosts: number;
		followerGrowth: number;
		bestPostEngagement: number;
	};

	// Top Performing Content (last N days)
	topPosts: Array<{
		content: string;
		engagementRate: number;
		views: number;
		publishedAt: string;
		mediaType?: string | undefined;
	}>;

	// Voice Profile (if exists)
	voiceProfile?: {
        		tone: string;
        		topics: string[];
        		avoidTopics: string[];
        		samplePosts: string[];
        	} | undefined;

	// Competitor Context (if available)
	competitorInsights?: {
        		topCompetitorPosts: Array<{
        			username: string;
        			content: string;
        			engagement: number;
        		}>;
        		industryAvgEngagement: number;
        	} | undefined;

	// Best Posting Times
	bestTimes?: Array<{
        		dayOfWeek: number;
        		hour: number;
        		avgEngagement: number;
        	}> | undefined;

	// Audience Demographics (if available)
	audienceSummary?: string | undefined;
}

export interface ContextOptions {
	includeTopPosts?: boolean | undefined; // default: true
	includeVoice?: boolean | undefined; // default: true
	includeCompetitors?: boolean | undefined; // default: false (heavier query)
	includeBestTimes?: boolean | undefined; // default: false
	includeAudience?: boolean | undefined; // default: false
	topPostsLimit?: number | undefined; // default: 5
	timeRangeDays?: number | undefined; // default: 30
}

// ---------------------------------------------------------------------------
// Pre-built option presets for each AI feature
// ---------------------------------------------------------------------------

export const CONTEXT_PRESETS = {
	contentGeneration: {
		includeTopPosts: true,
		includeVoice: true,
		includeCompetitors: true,
		topPostsLimit: 10,
	},
	replySuggestion: {
		includeTopPosts: false,
		includeVoice: true,
		topPostsLimit: 3,
	},
	analyticsInsight: {
		includeTopPosts: true,
		includeBestTimes: true,
		includeAudience: true,
	},
	growthAdvice: {
		includeTopPosts: true,
		includeCompetitors: true,
		includeBestTimes: true,
		includeAudience: true,
	},
	captionWriter: {
		includeTopPosts: true,
		includeVoice: true,
		topPostsLimit: 5,
	},
	copilot: {
		includeTopPosts: true,
		includeVoice: true,
		includeCompetitors: false,
		topPostsLimit: 3,
	},
} as const;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Simple client-side engagement rate calculation. */
function calcEngagementRate(post: ThreadPost, followerCount: number): number {
	const likes = post.performance?.likes ?? post.likes ?? 0;
	const replies = post.performance?.replies ?? post.replies ?? 0;
	const reposts = post.performance?.reposts ?? 0;
	const quotes = post.performance?.quotes ?? 0;
	const shares = post.performance?.shares ?? 0;

	const totalInteractions = likes + replies + reposts + quotes + shares;

	// Prefer views-based ER when available, fall back to follower-based
	const views = post.performance?.views ?? post.views ?? 0;
	if (views > 0) {
		return totalInteractions / views;
	}
	if (followerCount > 0) {
		return totalInteractions / followerCount;
	}
	return 0;
}

/** Date N days ago as ISO string. */
function daysAgo(n: number): string {
	const d = new Date();
	d.setDate(d.getDate() - n);
	return d.toISOString();
}

/** Safe date string from various timestamp formats. */
function toISOString(value: unknown): string {
	if (!value) return "";
	if (value instanceof Date) return value.toISOString();
	if (
		typeof value === "object" &&
		value !== null &&
		"toDate" in value &&
		typeof (value as { toDate: () => Date }).toDate === "function"
	) {
		return (value as { toDate: () => Date }).toDate().toISOString();
	}
	if (typeof value === "string") return value;
	return "";
}

/** Format follower count with K/M suffix. */
function formatFollowers(count: number): string {
	if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
	if (count >= 1_000) return `${(count / 1_000).toFixed(1)}K`;
	return String(count);
}

/** Format a percentage for display. */
function pct(value: number): string {
	return `${(value * 100).toFixed(1)}%`;
}

const DAY_NAMES = [
	"Sunday",
	"Monday",
	"Tuesday",
	"Wednesday",
	"Thursday",
	"Friday",
	"Saturday",
];

// ---------------------------------------------------------------------------
// Context Builder
// ---------------------------------------------------------------------------

/**
 * Build a rich AI context from Supabase / cached data.
 *
 * Fetches account info, recent posts, voice profile, competitor insights,
 * and best posting times in parallel where possible.
 */
export async function buildAIContext(
	userId: string,
	accountId: string,
	platform: Platform,
	options?: ContextOptions,
): Promise<AIContext> {
	const opts: Required<ContextOptions> = {
		includeTopPosts: options?.includeTopPosts ?? true,
		includeVoice: options?.includeVoice ?? true,
		includeCompetitors: options?.includeCompetitors ?? false,
		includeBestTimes: options?.includeBestTimes ?? false,
		includeAudience: options?.includeAudience ?? false,
		topPostsLimit: options?.topPostsLimit ?? 5,
		timeRangeDays: options?.timeRangeDays ?? 30,
	};

	// ------------------------------------------------------------------
	// 1. Kick off parallel data fetches
	// ------------------------------------------------------------------

	const accountPromise = dataService.getAccount(accountId);

	// Fetch posts for the configured time range
		const sinceDate = daysAgo(opts.timeRangeDays ?? 30);
	const postsPromise = dataService.getPosts(
		accountId,
		false,
		undefined,
		sinceDate,
	);

	const voicePromise = opts.includeVoice
		? loadVoiceProfile().catch((err) => {
				logger.warn("[AIContextEngine] Voice profile load failed:", err);
				return null;
			})
		: Promise.resolve(null);

	const competitorsPromise = opts.includeCompetitors
		? fetchCompetitorInsights().catch((err) => {
				logger.warn("[AIContextEngine] Competitor fetch failed:", err);
				return undefined;
			})
		: Promise.resolve(undefined);

	// Wait for account + posts first (needed by downstream computations)
	const [account, posts, voiceProfile, competitorInsights] = await Promise.all([
		accountPromise,
		postsPromise,
		voicePromise,
		competitorsPromise,
	]);

	// ------------------------------------------------------------------
	// 2. Derive account basics
	// ------------------------------------------------------------------

	const username = account?.handle ?? account?.username ?? "unknown";
	const followerCount = account?.followers ?? account?.followersCount ?? 0;

	// ------------------------------------------------------------------
	// 3. Compute recent metrics (last 7 days)
	// ------------------------------------------------------------------

	const sevenDaysAgo = daysAgo(7);
	const recentPosts = posts.filter((p) => {
		const pubDate = toISOString(p.publishedAt);
		return (
			pubDate >= sevenDaysAgo &&
			(p.status === ("published" as PostStatus) ||
				(p.status as string) === "PUBLISHED")
		);
	});

	const recentEngagementRates = recentPosts.map((p) =>
		calcEngagementRate(p, followerCount),
	);
	const avgEngagementRate =
		recentEngagementRates.length > 0
			? recentEngagementRates.reduce((a, b) => a + b, 0) /
				recentEngagementRates.length
			: 0;

	const totalViews = recentPosts.reduce(
		(sum, p) => sum + (p.performance?.views ?? p.views ?? 0),
		0,
	);

	const bestPostEngagement =
		recentEngagementRates.length > 0 ? Math.max(...recentEngagementRates) : 0;

	let followerGrowth = 0;
	try {
		const history = await dataService.getFollowerHistory(accountId, 8);
		const usable = history
			.map((point) => point.v)
			.filter((value) => Number.isFinite(value) && value > 0);
		const prior = usable[0] ?? 0;
		const current = usable[usable.length - 1] ?? followerCount;
		if (prior > 0 && current > 0) {
			followerGrowth = (current - prior) / prior;
		}
	} catch {
		// Non-critical
	}

	const recentMetrics = {
		avgEngagementRate,
		totalViews,
		totalPosts: recentPosts.length,
		followerGrowth,
		bestPostEngagement,
	};

	// ------------------------------------------------------------------
	// 4. Top performing posts
	// ------------------------------------------------------------------

	let topPosts: AIContext["topPosts"] = [];

	if (opts.includeTopPosts) {
		const publishedPosts = posts.filter(
			(p) =>
				(p.status === ("published" as PostStatus) ||
					(p.status as string) === "PUBLISHED") &&
				p.content &&
				p.content.length > 10,
		);

		const scored = publishedPosts.map((p) => ({
			post: p,
			er: calcEngagementRate(p, followerCount),
		}));

		scored.sort((a, b) => b.er - a.er);

		topPosts = scored.slice(0, opts.topPostsLimit).map((s) => ({
			content: s.post.content,
			engagementRate: s.er,
			views: s.post.performance?.views ?? s.post.views ?? 0,
			publishedAt: toISOString(s.post.publishedAt),
			mediaType:
				s.post.igMediaType ?? (s.post.mediaUrls?.length ? "image" : "text"),
		}));
	}

	// ------------------------------------------------------------------
	// 5. Voice profile
	// ------------------------------------------------------------------

	let voiceCtx: AIContext["voiceProfile"];
	if (voiceProfile) {
		const vp = voiceProfile as VoiceProfile;
		voiceCtx = {
			tone: vp.voice_profile ?? vp.extracted_style?.tone?.vibe ?? "casual",
			topics: vp.focus_topics ?? [],
			avoidTopics: vp.avoid_topics ?? [],
			samplePosts: topPosts.slice(0, 3).map((p) => p.content),
		};
	}

	// ------------------------------------------------------------------
	// 6. Best times (computed from posts)
	// ------------------------------------------------------------------

	let bestTimes: AIContext["bestTimes"];
	if (opts.includeBestTimes) {
		try {
			const btResult = await analyzeBestPostingTimes(posts);
			if (btResult.topSlots.length > 0) {
				bestTimes = btResult.topSlots.slice(0, 5).map((slot) => ({
					dayOfWeek: slot.day,
					hour: slot.hour,
					avgEngagement: slot.avgEngagementRate,
				}));
			}
		} catch (err) {
			logger.warn("[AIContextEngine] Best times analysis failed:", err);
		}
	}

	// ------------------------------------------------------------------
	// 7. Audience summary (derive from available data)
	// ------------------------------------------------------------------

	let audienceSummary: string | undefined;
	if (opts.includeAudience) {
		// No dedicated audience API on the client -- build a simple summary
		// from available account + post data.
		const summaryParts: string[] = [];
		summaryParts.push(`${formatFollowers(followerCount)} followers`);
		if (recentPosts.length > 0) {
			summaryParts.push(`${recentPosts.length} posts in the last 7 days`);
			summaryParts.push(`${pct(avgEngagementRate)} avg engagement rate`);
		}
		if (topPosts.length > 0) {
			const topViews = Math.max(...topPosts.map((p) => p.views));
			summaryParts.push(`top post reached ${topViews.toLocaleString()} views`);
		}
		audienceSummary = summaryParts.join(" | ");
	}

	// ------------------------------------------------------------------
	// 8. Assemble context
	// ------------------------------------------------------------------

	return {
		userId,
		accountId,
		platform,
		username,
		followerCount,
		recentMetrics,
		topPosts,
		voiceProfile: voiceCtx,
		competitorInsights,
		bestTimes,
		audienceSummary,
	};
}

// ---------------------------------------------------------------------------
// Competitor Insights Helper
// ---------------------------------------------------------------------------

async function fetchCompetitorInsights(): Promise<
	AIContext["competitorInsights"] | undefined
> {
	try {
		const competitors = await competitorService.getCompetitors();
		if (!competitors || competitors.length === 0) return undefined;

		// Gather top posts from each competitor (limit to first 5 competitors)
		const postBatches = await Promise.all(
			competitors.slice(0, 5).map(async (c) => {
				try {
					const posts = await competitorService.getCompetitorPosts(c.id, 5);
					return posts.map((p: CompetitorPost) => ({
						username: c.username,
						content: p.content,
						engagement: p.likeCount + p.replyCount + p.repostCount,
					}));
				} catch {
					return [];
				}
			}),
		);

		const allCompetitorPosts = postBatches.flat();

		// Sort by engagement and take top 10
		allCompetitorPosts.sort((a, b) => b.engagement - a.engagement);
		const topCompetitorPosts = allCompetitorPosts.slice(0, 10);

		// Compute industry average engagement
		const totalEng = allCompetitorPosts.reduce(
			(sum, p) => sum + p.engagement,
			0,
		);
		const industryAvgEngagement =
			allCompetitorPosts.length > 0 ? totalEng / allCompetitorPosts.length : 0;

		return { topCompetitorPosts, industryAvgEngagement };
	} catch (err) {
		logger.warn("[AIContextEngine] Competitor insights failed:", err);
		return undefined;
	}
}

// ---------------------------------------------------------------------------
// System Prompt Formatter
// ---------------------------------------------------------------------------

/**
 * Format the context object into a clean text block that can be prepended
 * to any AI prompt as a system-level context section.
 */
export function contextToSystemPrompt(context: AIContext): string {
	const sections: string[] = [];

	// ---- User Context ----
	const growthStr =
		context.recentMetrics.followerGrowth !== 0
			? ` | ${context.recentMetrics.followerGrowth > 0 ? "+" : ""}${pct(context.recentMetrics.followerGrowth)} growth this week`
			: "";

	sections.push(
		`## User Context
Account: @${context.username} (${context.platform}) | ${formatFollowers(context.followerCount)} followers${growthStr}
Recent Performance: ${pct(context.recentMetrics.avgEngagementRate)} avg engagement | ${context.recentMetrics.totalViews.toLocaleString()} total views | ${context.recentMetrics.totalPosts} posts (last 7 days)`,
	);

	// ---- Top Posts ----
	if (context.topPosts.length > 0) {
		const postLines = context.topPosts.map((p, i) => {
			const snippet =
				p.content.length > 120 ? `${p.content.slice(0, 117)}...` : p.content;
			return `${i + 1}. "${snippet}" -- ${pct(p.engagementRate)} engagement, ${p.views.toLocaleString()} views`;
		});

		sections.push(
			`## Top Performing Content (Last ${guessTimeRange(context)} Days)\n${postLines.join("\n")}`,
		);
	}

	// ---- Voice Profile ----
	if (context.voiceProfile) {
		const vp = context.voiceProfile;
		const parts: string[] = [];
		if (vp.tone) parts.push(`Tone: ${vp.tone}`);
		if (vp.topics.length > 0) parts.push(`Topics: ${vp.topics.join(", ")}`);
		if (vp.avoidTopics.length > 0)
			parts.push(`Avoid: ${vp.avoidTopics.join(", ")}`);
		if (vp.samplePosts.length > 0) {
			parts.push(
				`Sample voice:\n${vp.samplePosts.map((s) => `  - "${s.length > 80 ? `${s.slice(0, 77)}...` : s}"`).join("\n")}`,
			);
		}

		sections.push(`## Voice Profile\n${parts.join("\n")}`);
	}

	// ---- Competitor Insights ----
	if (
		context.competitorInsights &&
		context.competitorInsights.topCompetitorPosts.length > 0
	) {
		const ci = context.competitorInsights;
		const postLines = ci.topCompetitorPosts.slice(0, 5).map((p) => {
			const snippet =
				p.content.length > 100 ? `${p.content.slice(0, 97)}...` : p.content;
			return `- @${p.username}: "${snippet}" (${p.engagement.toLocaleString()} engagements)`;
		});

		sections.push(
			`## Competitor Insights\nIndustry avg engagement: ${ci.industryAvgEngagement.toFixed(0)} interactions/post\nTop competitor posts:\n${postLines.join("\n")}`,
		);
	}

	// ---- Best Times ----
	if (context.bestTimes && context.bestTimes.length > 0) {
		const timeLines = context.bestTimes.map((t) => {
			const day = DAY_NAMES[t.dayOfWeek] ?? `Day ${t.dayOfWeek}`;
			const hour12 =
				t.hour === 0
					? "12 AM"
					: t.hour < 12
						? `${t.hour} AM`
						: t.hour === 12
							? "12 PM"
							: `${t.hour - 12} PM`;
			return `- ${day} at ${hour12} (${pct(t.avgEngagement)} avg ER)`;
		});

		sections.push(`## Best Posting Times\n${timeLines.join("\n")}`);
	}

	// ---- Audience ----
	if (context.audienceSummary) {
		sections.push(`## Audience Summary\n${context.audienceSummary}`);
	}

	return sections.join("\n\n");
}

/** Estimate the time range from context data (for display purposes). */
function guessTimeRange(ctx: AIContext): number {
	if (ctx.topPosts.length === 0) return 30;
	const oldest = ctx.topPosts.reduce((min, p) => {
		return p.publishedAt && p.publishedAt < min ? p.publishedAt : min;
	}, new Date().toISOString());
	const diffMs = Date.now() - new Date(oldest).getTime();
	const diffDays = Math.ceil(diffMs / 86_400_000);
	return Math.max(diffDays, 7);
}
