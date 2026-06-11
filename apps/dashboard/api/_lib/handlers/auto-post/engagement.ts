// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Auto-Post Engagement Module
 *
 * Handles engagement tracking and snapshot recording.
 */

import { getInstagramPostMetrics } from "../../instagramApi.js";
import { logger } from "../../logger.js";
import type { Platform } from "../../platform.js";
import { withRetry } from "../../retryUtils.js";
import { getSupabase } from "../../supabase.js";

const db = () => getSupabase();

// ============================================================================
// Engagement Snapshots
// ============================================================================

export async function takeEngagementSnapshot(
	queueItemId: string,
	threadsPostId: string,
	token: string,
	postedAt: string,
	options?: {
		platform?: Platform | undefined;
		encryptedToken?: string | undefined;
		loginType?: string | undefined;
	},
): Promise<{ velocity: number; trend: string } | null> {
	try {
		const metrics: Record<string, number> = {};

		// ---- Instagram path ----
		if (options?.platform === "instagram" && options?.encryptedToken) {
			logger.info("[engagement:ig] Fetching IG post metrics", {
				mediaId: threadsPostId,
			});
			const igResult = await getInstagramPostMetrics(
				options.encryptedToken,
				threadsPostId,
				options.loginType,
			);
			if (!igResult.success || !igResult.metrics) return null;
			metrics.views = igResult.metrics.views;
			metrics.likes = igResult.metrics.likes;
			metrics.replies = igResult.metrics.comments;
			metrics.reposts = igResult.metrics.shares;
		} else {
			// ---- Threads path (original) ----
			// Fix 8: Wrap with withRetry for consistent retry handling on Meta API calls
			const metricsUrl = `https://graph.threads.net/v1.0/${threadsPostId}/insights?metric=views,likes,replies,reposts,quotes,shares`;
			const response = await withRetry(
				() =>
					fetch(metricsUrl, {
						headers: { Authorization: `Bearer ${token}` },
						signal: AbortSignal.timeout(10000),
					}),
				{ label: "engagement-snapshot:threads-insights" },
			);
			const data = await response.json();

			if (!data.data) return null;

			for (const m of data.data) {
				metrics[m.name] = m.values?.[0]?.value || 0;
			}
		}

		const cumulative =
			(metrics.likes || 0) +
			(metrics.replies || 0) * 2 +
			(metrics.reposts || 0) * 1.5;
		const hoursSincePost =
			(Date.now() - new Date(postedAt).getTime()) / (1000 * 60 * 60);

		const { data: prevSnapshots } = await (
			db() as ReturnType<typeof getSupabase>
		)
			.from("auto_post_engagement_snapshots")
			.select("cumulative_engagement, snapshot_at")
			.eq("queue_item_id", queueItemId)
			.order("snapshot_at", { ascending: false })
			.limit(1);

		let velocity = hoursSincePost > 0 ? cumulative / hoursSincePost : 0;
		let trend = "stable";

		if (prevSnapshots && prevSnapshots.length > 0) {
			const prev = prevSnapshots[0];
			const prevCumulative =
				parseFloat(String(prev!.cumulative_engagement)) || 0;
			const hoursSincePrev =
				(Date.now() - new Date(prev!.snapshot_at || "").getTime()) /
				(1000 * 60 * 60);
			if (hoursSincePrev > 0) {
				velocity = (cumulative - prevCumulative) / hoursSincePrev;
			}
			if (velocity > 3) trend = "accelerating";
			else if (velocity < 0.5) trend = "declining";
		}

		await (db() as ReturnType<typeof getSupabase>)
			.from("auto_post_engagement_snapshots")
			.insert({
				queue_item_id: queueItemId,
				hours_since_post: hoursSincePost,
				views_count: metrics.views || 0,
				likes_count: metrics.likes || 0,
				replies_count: metrics.replies || 0,
				reposts_count: metrics.reposts || 0,
				cumulative_engagement: cumulative,
				engagement_velocity: velocity,
			});

		return { velocity, trend };
	} catch (err) {
		logger.error("Snapshot error", {
			queueItemId,
			error: err instanceof Error ? err.message : String(err),
		});
		return null;
	}
}
