/**
 * Cross-Platform Performance Monitor
 *
 * Compares engagement metrics between Threads and Instagram accounts
 * within a workspace. Surfaces which platform is performing better
 * and by how much, so volume allocation can be adjusted.
 *
 * Used by:
 * - Queue fill orchestrator: logs platform performance gap
 * - MCP tools: get_cross_account_insights
 * - Future: auto-adjust platform volume split
 */

import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";

const db = () => getSupabaseAny();

// ============================================================================
// Types
// ============================================================================

export interface PlatformPerformance {
	platform: "threads" | "instagram";
	accountCount: number;
	avgEngagementRate: number;
	avgViewsPerPost: number;
	totalPosts: number;
	totalViews: number;
}

export interface CrossPlatformReport {
	threads: PlatformPerformance | null;
	instagram: PlatformPerformance | null;
	/** Which platform is performing better (null if insufficient data) */
	winningPlatform: "threads" | "instagram" | null;
	/** How much better (e.g., 1.5 = winning platform is 50% better) */
	performanceRatio: number;
	/** Recommended volume adjustment: >1 means boost winning platform */
	recommendedVolumeMultiplier: number;
	/** Reason for recommendation */
	recommendation: string;
}

// ============================================================================
// Core Analysis
// ============================================================================

/**
 * Compare Threads vs Instagram performance for accounts in a workspace.
 * Uses last 14 days of post data from the `posts` table.
 *
 * Returns null if one or both platforms have insufficient data (<5 posts).
 */
export async function analyzeCrossPlatformPerformance(
	_workspaceId: string,
	ownerId: string,
): Promise<CrossPlatformReport> {
	const fourteenDaysAgo = new Date(Date.now() - 14 * 86_400_000).toISOString();

	// Get all Threads accounts for this user
	const { data: threadsAccounts } = await db()
		.from("accounts")
		.select("id")
		.eq("user_id", ownerId)
		.eq("is_active", true);

	const threadsAccountIds = (threadsAccounts || []).map(
		(a: { id: string }) => a.id,
	);

	// Get all IG accounts for this user
	const { data: igAccounts } = await db()
		.from("instagram_accounts")
		.select("id")
		.eq("user_id", ownerId);

	const igAccountIds = (igAccounts || []).map((a: { id: string }) => a.id);

	// Query Threads posts performance
	let threadsPerfData: PlatformPerformance | null = null;
	if (threadsAccountIds.length > 0) {
		const { data: threadsPosts } = await db()
			.from("posts")
			.select("views_count, likes_count, replies_count")
			.in("account_id", threadsAccountIds)
			.eq("status", "published")
			.eq("platform", "threads")
			.gte("published_at", fourteenDaysAgo)
			.limit(500);

		if (threadsPosts && threadsPosts.length >= 5) {
			const totalViews = threadsPosts.reduce(
				(s: number, p: Record<string, unknown>) =>
					s + ((p.views_count as number) || 0),
				0,
			);
			const totalLikes = threadsPosts.reduce(
				(s: number, p: Record<string, unknown>) =>
					s + ((p.likes_count as number) || 0),
				0,
			);
			const totalReplies = threadsPosts.reduce(
				(s: number, p: Record<string, unknown>) =>
					s + ((p.replies_count as number) || 0),
				0,
			);
			const avgViews = totalViews / threadsPosts.length;
			const avgEngagement =
				totalViews > 0 ? (totalLikes + totalReplies) / totalViews : 0;

			threadsPerfData = {
				platform: "threads",
				accountCount: threadsAccountIds.length,
				avgEngagementRate: avgEngagement,
				avgViewsPerPost: avgViews,
				totalPosts: threadsPosts.length,
				totalViews,
			};
		}
	}

	// Query IG posts performance
	let igPerfData: PlatformPerformance | null = null;
	if (igAccountIds.length > 0) {
		const { data: igPosts } = await db()
			.from("posts")
			.select("views_count, likes_count, replies_count")
			.in("account_id", igAccountIds)
			.eq("status", "published")
			.eq("platform", "instagram")
			.gte("published_at", fourteenDaysAgo)
			.limit(500);

		if (igPosts && igPosts.length >= 5) {
			const totalViews = igPosts.reduce(
				(s: number, p: Record<string, unknown>) =>
					s + ((p.views_count as number) || 0),
				0,
			);
			const totalLikes = igPosts.reduce(
				(s: number, p: Record<string, unknown>) =>
					s + ((p.likes_count as number) || 0),
				0,
			);
			const totalReplies = igPosts.reduce(
				(s: number, p: Record<string, unknown>) =>
					s + ((p.replies_count as number) || 0),
				0,
			);
			const avgViews = totalViews / igPosts.length;
			const avgEngagement =
				totalViews > 0 ? (totalLikes + totalReplies) / totalViews : 0;

			igPerfData = {
				platform: "instagram",
				accountCount: igAccountIds.length,
				avgEngagementRate: avgEngagement,
				avgViewsPerPost: avgViews,
				totalPosts: igPosts.length,
				totalViews,
			};
		}
	}

	// Compare platforms
	if (!threadsPerfData && !igPerfData) {
		return {
			threads: null,
			instagram: null,
			winningPlatform: null,
			performanceRatio: 1,
			recommendedVolumeMultiplier: 1,
			recommendation: "Insufficient data on both platforms",
		};
	}

	if (!threadsPerfData) {
		return {
			threads: null,
			instagram: igPerfData,
			winningPlatform: "instagram",
			performanceRatio: 1,
			recommendedVolumeMultiplier: 1,
			recommendation:
				"Only Instagram has sufficient data — continue current allocation",
		};
	}

	if (!igPerfData) {
		return {
			threads: threadsPerfData,
			instagram: null,
			winningPlatform: "threads",
			performanceRatio: 1,
			recommendedVolumeMultiplier: 1,
			recommendation:
				"Only Threads has sufficient data — continue current allocation",
		};
	}

	// Both platforms have data — compare engagement rates
	const threadsScore = threadsPerfData.avgEngagementRate;
	const igScore = igPerfData.avgEngagementRate;

	let winningPlatform: "threads" | "instagram";
	let performanceRatio: number;

	if (threadsScore > igScore && igScore > 0) {
		winningPlatform = "threads";
		performanceRatio = threadsScore / igScore;
	} else if (igScore > threadsScore && threadsScore > 0) {
		winningPlatform = "instagram";
		performanceRatio = igScore / threadsScore;
	} else {
		// Equal or one is zero
		winningPlatform =
			threadsPerfData.avgViewsPerPost >= igPerfData.avgViewsPerPost
				? "threads"
				: "instagram";
		performanceRatio = 1;
	}

	// Recommend volume adjustment
	// <1.3x difference → no change (within noise)
	// 1.3-2x → mild boost (1.2x to winner)
	// >2x → strong boost (1.5x to winner)
	let recommendedVolumeMultiplier = 1;
	let recommendation =
		"Platforms performing similarly — maintain current split";

	if (performanceRatio >= 2) {
		recommendedVolumeMultiplier = 1.5;
		recommendation = `${winningPlatform} outperforming by ${performanceRatio.toFixed(1)}x — recommend shifting 50% more volume to ${winningPlatform}`;
	} else if (performanceRatio >= 1.3) {
		recommendedVolumeMultiplier = 1.2;
		recommendation = `${winningPlatform} outperforming by ${performanceRatio.toFixed(1)}x — recommend shifting 20% more volume to ${winningPlatform}`;
	}

	return {
		threads: threadsPerfData,
		instagram: igPerfData,
		winningPlatform,
		performanceRatio,
		recommendedVolumeMultiplier,
		recommendation,
	};
}

/**
 * Log cross-platform performance during queue fill (lightweight check).
 * Only runs for workspaces with platform="both".
 * Non-blocking — failures are silently caught.
 */
export async function logCrossPlatformInsight(
	workspaceId: string,
	ownerId: string,
): Promise<{
	winningPlatform: "threads" | "instagram" | null;
	multiplier: number;
}> {
	try {
		const report = await analyzeCrossPlatformPerformance(workspaceId, ownerId);

		if (report.winningPlatform && report.performanceRatio >= 1.3) {
			logger.info("[crossPlatformMonitor] Performance gap detected", {
				workspaceId,
				winning: report.winningPlatform,
				ratio: report.performanceRatio.toFixed(2),
				recommendation: report.recommendation,
				threadsEngagement: report.threads?.avgEngagementRate.toFixed(4),
				igEngagement: report.instagram?.avgEngagementRate.toFixed(4),
				threadsAvgViews: report.threads?.avgViewsPerPost.toFixed(0),
				igAvgViews: report.instagram?.avgViewsPerPost.toFixed(0),
			});
		}

		return {
			winningPlatform: report.winningPlatform,
			multiplier: report.recommendedVolumeMultiplier,
		};
	} catch {
		return { winningPlatform: null, multiplier: 1 };
	}
}
