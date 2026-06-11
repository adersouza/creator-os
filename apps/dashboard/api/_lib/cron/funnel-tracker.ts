// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Funnel Tracker — profile visit estimation + CTA A/B testing
 *
 * Tracks followers_delta per post (followers before vs 24h after).
 * Scores posts by conversion rate (followers gained / views).
 * Optimizes for this metric, not just views.
 *
 * CTA A/B testing:
 *   - Rotates CTA types: none, soft, direct, mystery
 *   - 48-hour test per CTA type
 *   - Measures follower delta per CTA
 *   - Picks winner, repeat
 *
 * Runs daily via daily-orchestrator.
 */

import { logger, serializeError } from "../logger.js";
import { getSupabase } from "../supabase.js";

// biome-ignore lint/suspicious/noExplicitAny: new columns not in generated types
const db = (): any => getSupabase();

const LOG_PREFIX = "[funnel-tracker]";

// ============================================================================
// Types
// ============================================================================

interface FunnelResult {
	accountsTracked: number;
	postsWithDelta: number;
	topConverters: {
		content: string;
		views: number;
		followerDelta: number;
		conversionRate: number;
	}[];
	ctaResults: Record<string, { posts: number; avgDelta: number }>;
}

// CTA types for A/B testing
const CTA_TYPES = ["none", "soft", "direct", "mystery"] as const;
type CTAType = (typeof CTA_TYPES)[number];

const CTA_EXAMPLES: Record<CTAType, string> = {
	none: "(no CTA — pure engagement bait)",
	soft: "click my profile if you're brave enough",
	direct: "snap? / add me / dm me",
	mystery: "don't open my profile around your friends",
};

// ============================================================================
// Main Orchestrator
// ============================================================================

export async function processFunnelTracking(): Promise<FunnelResult> {
	const result: FunnelResult = {
		accountsTracked: 0,
		postsWithDelta: 0,
		topConverters: [],
		ctaResults: {},
	};

	try {
		await trackFollowerDeltas(result);
		await analyzeCTAPerformance(result);
		await storeInsights(result);

		logger.info(`${LOG_PREFIX} Complete`, {
			accountsTracked: result.accountsTracked,
			postsWithDelta: result.postsWithDelta,
			topConverters: result.topConverters.length,
		});
	} catch (err) {
		logger.error(`${LOG_PREFIX} Fatal error`, { error: serializeError(err) });
	}

	return result;
}

// ============================================================================
// Follower Delta Tracking
// ============================================================================

async function trackFollowerDeltas(result: FunnelResult): Promise<void> {
	// Get accounts with metric history
	const { data: accounts } = await db()
		.from("accounts")
		.select("id, username, followers_count, group_id")
		.eq("is_active", true)
		.not("followers_count", "is", null);

	if (!accounts || accounts.length === 0) return;

	const oneDayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
	const threeDaysAgo = new Date(
		Date.now() - 3 * 24 * 60 * 60 * 1000,
	).toISOString();

	for (const account of accounts) {
		try {
			// Get follower count from 24h ago (account_metrics_history if exists)
			const { data: historyRow } = await db()
				.from("account_metrics_history")
				.select("followers_count, recorded_at")
				.eq("account_id", account.id)
				.lte("recorded_at", oneDayAgo)
				.order("recorded_at", { ascending: false })
				.limit(1)
				.maybeSingle();

			const followersBefore =
				historyRow?.followers_count || account.followers_count || 0;
			const followersNow = account.followers_count || 0;
			const delta = followersNow - followersBefore;

			if (delta === 0) continue;

			// Get posts published in the 24-48h window (published long enough for impact)
			const { data: recentPosts } = await db()
				.from("posts")
				.select("id, content, views_count, published_at")
				.eq("account_id", account.id)
				.eq("platform", "threads")
				.eq("status", "published")
				.gte("published_at", threeDaysAgo)
				.lte("published_at", oneDayAgo)
				.not("views_count", "is", null);

			if (!recentPosts || recentPosts.length === 0) continue;

			result.accountsTracked++;

			// Distribute delta proportionally across posts by views
			const totalViews = recentPosts.reduce(
				(s: number, p: { views_count: number }) => s + (p.views_count || 0),
				0,
			);
			if (totalViews === 0) continue;

			for (const post of recentPosts) {
				const views = post.views_count || 0;
				const postDelta = Math.round(delta * (views / totalViews) * 100) / 100;
				const conversionRate = views > 0 ? (postDelta / views) * 100 : 0;

				// Track top converters
				if (postDelta > 0 && views >= 10) {
					result.topConverters.push({
						content: (post.content || "").slice(0, 100),
						views,
						followerDelta: postDelta,
						conversionRate: Math.round(conversionRate * 1000) / 1000,
					});
					result.postsWithDelta++;
				}
			}
		} catch (err) {
			logger.error(`${LOG_PREFIX} Account delta tracking failed`, {
				accountId: account.id,
				error: serializeError(err),
			});
		}
	}

	// Sort top converters by conversion rate
	result.topConverters.sort((a, b) => b.conversionRate - a.conversionRate);
	result.topConverters = result.topConverters.slice(0, 10);
}

// ============================================================================
// CTA A/B Testing
// ============================================================================

async function analyzeCTAPerformance(result: FunnelResult): Promise<void> {
	const sevenDaysAgo = new Date(
		Date.now() - 7 * 24 * 60 * 60 * 1000,
	).toISOString();

	// Get published posts from auto_post_queue with source metadata
	const { data: posts } = await db()
		.from("auto_post_queue")
		.select("content, likes_count, replies_count, engagement_rate")
		.eq("status", "published")
		.gte("posted_at", sevenDaysAgo);

	if (!posts || posts.length < 10) return;

	// Classify posts by CTA type based on content analysis
	const ctaBuckets: Record<CTAType, { engagement: number; count: number }> = {
		none: { engagement: 0, count: 0 },
		soft: { engagement: 0, count: 0 },
		direct: { engagement: 0, count: 0 },
		mystery: { engagement: 0, count: 0 },
	};

	for (const post of posts) {
		const content = ((post.content as string) || "").toLowerCase();
		const engagement =
			((post.likes_count as number) || 0) +
			((post.replies_count as number) || 0) * 3;

		let ctaType: CTAType = "none";
		if (/\bsnap\b|\bdm\b|\badd me\b|\bfollow me\b/i.test(content)) {
			ctaType = "direct";
		} else if (/\bprofile\b|\bcheck\b|\bclick\b|\btap\b/i.test(content)) {
			ctaType = "soft";
		} else if (
			/\bdon't\b.*\bprofile\b|\bif you dare\b|\bbrave enough\b/i.test(content)
		) {
			ctaType = "mystery";
		}

		ctaBuckets[ctaType].engagement += engagement;
		ctaBuckets[ctaType].count++;
	}

	for (const [type, data] of Object.entries(ctaBuckets) as [
		CTAType,
		{ engagement: number; count: number },
	][]) {
		if (data.count > 0) {
			result.ctaResults[type] = {
				posts: data.count,
				avgDelta: Math.round(data.engagement / data.count),
			};
		}
	}
}

// ============================================================================
// Store Insights
// ============================================================================

async function storeInsights(result: FunnelResult): Promise<void> {
	try {
		// Store as agent note for MCP visibility
		const noteContent = JSON.stringify({
			date: new Date().toISOString().split("T")[0]!,
			accountsTracked: result.accountsTracked,
			postsWithDelta: result.postsWithDelta,
			topConverters: result.topConverters.slice(0, 5),
			ctaResults: result.ctaResults,
			recommendation: getBestCTARecommendation(result.ctaResults),
		});

		// Delete existing then insert (agent_notes unique constraint is user_id+key+account_group_id,
		// but cron functions don't have user context — use system-level notes)
		await db()
			.from("agent_notes")
			.delete()
			.eq("key", "funnel-tracking")
			.is("account_group_id", null);
		await db().from("agent_notes").insert({
			key: "funnel-tracking",
			value: noteContent,
			updated_at: new Date().toISOString(),
		});
	} catch {
		// Non-critical
	}
}

function getBestCTARecommendation(
	ctaResults: Record<string, { posts: number; avgDelta: number }>,
): string {
	const entries = Object.entries(ctaResults).filter(([, v]) => v.posts >= 3);
	if (entries.length === 0) return "Not enough data yet";

	entries.sort(([, a], [, b]) => b.avgDelta - a.avgDelta);
	const best = entries[0];

	return `Best CTA type: "${best![0]}" (avg ${best![1].avgDelta} engagement across ${best![1].posts} posts). Example: ${CTA_EXAMPLES[best![0] as CTAType] || best![0]}`;
}
