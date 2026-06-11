// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Creator Event Detector
 *
 * Auto-detects significant events in a creator's journey:
 * - Viral posts (>5× average engagement)
 * - Follower spikes (>3× normal daily gain)
 * - Engagement drops (>30% sustained 7+ days)
 *
 * Deduplicates: no duplicate events of same type within 7 days.
 */

import { logger } from "./logger.js";
import { getSupabase } from "./supabase.js";

interface PostData {
	id: string;
	content?: string | null | undefined;
	media_type?: string | null | undefined;
	published_at?: string | null | undefined;
	views_count?: number | null | undefined;
	likes_count?: number | null | undefined;
	replies_count?: number | null | undefined;
	reposts_count?: number | null | undefined;
	shares_count?: number | null | undefined;
	engagement_rate?: number | null | undefined;
}

interface AnalyticsData {
	date: string;
	followers_count?: number | null | undefined;
	follower_growth?: number | null | undefined;
	total_views?: number | null | undefined;
	engagement_rate?: number | null | undefined;
}

interface CreatorEvent {
	user_id: string;
	account_id: string;
	event_type: string;
	event_date: string;
	description: string;
	metrics_snapshot: Record<string, unknown>;
	impact_duration_days?: number | undefined;
}

const DEDUP_WINDOW_DAYS = 7;

async function getRecentEventTypes(
	accountId: string,
	userId: string,
): Promise<Map<string, Date>> {
	const db = getSupabase();
	const cutoff = new Date(
		Date.now() - DEDUP_WINDOW_DAYS * 24 * 60 * 60 * 1000,
	).toISOString();

	const { data } = await db
		.from("creator_events")
		.select("event_type, event_date")
		.eq("account_id", accountId)
		.eq("user_id", userId)
		.gte("event_date", cutoff);

	const map = new Map<string, Date>();
	if (data) {
		for (const row of data) {
			const existing = map.get(row.event_type);
			const rowDate = new Date(row.event_date);
			if (!existing || rowDate > existing) {
				map.set(row.event_type, rowDate);
			}
		}
	}
	return map;
}

function computeAverageEngagement(posts: PostData[]): number {
	if (posts.length === 0) return 0;
	const total = posts.reduce((sum, p) => {
		return (
			sum +
			(p.likes_count || 0) +
			(p.replies_count || 0) +
			(p.reposts_count || 0) +
			(p.shares_count || 0)
		);
	}, 0);
	return total / posts.length;
}

export async function detectEvents(
	accountId: string,
	userId: string,
	recentPosts: PostData[],
	accountAnalytics: AnalyticsData[],
): Promise<void> {
	try {
		const recentTypes = await getRecentEventTypes(accountId, userId);
		const events: CreatorEvent[] = [];
		const now = new Date().toISOString();

		// --- Viral Post Detection ---
		if (!recentTypes.has("viral_post") && recentPosts.length >= 5) {
			const avgEngagement = computeAverageEngagement(recentPosts);
			if (avgEngagement > 0) {
				// #613: Adaptive threshold — 3× for small accounts (<50 avg), 5× for larger
				const viralThreshold = avgEngagement < 50 ? 3 : 5;
				for (const post of recentPosts.slice(0, 10)) {
					const postEngagement =
						(post.likes_count || 0) +
						(post.replies_count || 0) +
						(post.reposts_count || 0) +
						(post.shares_count || 0);
					if (postEngagement > avgEngagement * viralThreshold) {
						events.push({
							user_id: userId,
							account_id: accountId,
							event_type: "viral_post",
							event_date: post.published_at || now,
							// #606: Don't store post content in DB — privacy concern
							description: `Viral ${post.media_type || "post"}: ${postEngagement} total engagements (${Math.round(postEngagement / avgEngagement)}× your average).`,
							metrics_snapshot: {
								views: post.views_count || 0,
								likes: post.likes_count || 0,
								replies: post.replies_count || 0,
								reposts: post.reposts_count || 0,
								shares: post.shares_count || 0,
								engagement_rate: post.engagement_rate || 0,
								average_engagement: Math.round(avgEngagement),
								multiplier: Math.round(postEngagement / avgEngagement),
							},
						});
						break; // Only log the most viral one
					}
				}
			}
		}

		// --- Follower Spike Detection ---
		if (!recentTypes.has("follower_spike") && accountAnalytics.length >= 7) {
			const sorted = [...accountAnalytics].sort((a, b) =>
				a.date.localeCompare(b.date),
			);
			const gains = sorted
				.map((d) => d.follower_growth || 0)
				.filter((g) => g > 0);

			if (gains.length >= 3) {
				const avgGain = gains.reduce((s, g) => s + g, 0) / gains.length;
				const latest = sorted[sorted.length - 1];
				const latestGain = latest!.follower_growth || 0;

				if (avgGain > 0 && latestGain > avgGain * 3) {
					events.push({
						user_id: userId,
						account_id: accountId,
						event_type: "follower_spike",
						event_date: latest!.date,
						description: `Follower spike: +${latestGain} followers in one day (${Math.round(latestGain / avgGain)}× your daily average of +${Math.round(avgGain)}).`,
						metrics_snapshot: {
							daily_gain: latestGain,
							average_daily_gain: Math.round(avgGain),
							multiplier: Math.round(latestGain / avgGain),
							followers_count: latest!.followers_count || 0,
						},
					});
				}
			}
		}

		// --- Engagement Drop Detection ---
		if (!recentTypes.has("engagement_drop") && accountAnalytics.length >= 14) {
			const sorted = [...accountAnalytics].sort((a, b) =>
				a.date.localeCompare(b.date),
			);
			const recent7 = sorted.slice(-7);
			const prev7 = sorted.slice(-14, -7);

			const avgRecent =
				recent7.reduce((s, d) => s + (d.engagement_rate || 0), 0) /
				recent7.length;
			const avgPrev =
				prev7.reduce((s, d) => s + (d.engagement_rate || 0), 0) / prev7.length;

			if (avgPrev > 0) {
				const dropPct = ((avgPrev - avgRecent) / avgPrev) * 100;
				if (dropPct > 30) {
					events.push({
						user_id: userId,
						account_id: accountId,
						event_type: "engagement_drop",
						event_date: now,
						description: `Engagement dropped ${Math.round(dropPct)}% over the last 7 days (${avgRecent.toFixed(2)}%) compared to the previous week (${avgPrev.toFixed(2)}%).`,
						metrics_snapshot: {
							recent_7d_avg: Number(avgRecent.toFixed(2)),
							previous_7d_avg: Number(avgPrev.toFixed(2)),
							drop_percentage: Math.round(dropPct),
						},
						impact_duration_days: 7,
					});
				}
			}
		}

		// --- Insert events ---
		if (events.length > 0) {
			const db = getSupabase();
			// biome-ignore lint/suspicious/noExplicitAny: local event shape not in generated Supabase types
			const { error } = await db.from("creator_events").insert(events as any);
			if (error) {
				logger.warn("Failed to insert creator events", {
					error: error.message,
					count: events.length,
				});
			} else {
				logger.info("Creator events detected", {
					accountId,
					count: events.length,
					types: events.map((e) => e.event_type),
				});
			}
		}
	} catch (err: unknown) {
		logger.warn("Creator event detection failed (non-fatal)", {
			accountId,
			error: err instanceof Error ? err.message : String(err),
		});
	}
}
