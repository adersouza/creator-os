// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * History-based recommendations powered by account_analytics and post_metric_history.
 * Includes engagement trend analysis, optimal posting hour detection, and
 * high-velocity post pattern recognition.
 */

import { logger } from "../logger.js";
import { postAccountFilter } from "../postQueryHelper.js";
import type { Recommendation } from "./shared.js";
import { dbAny } from "./shared.js";

// ── Local Types ─────────────────────────────────────────────────────────────

interface AnalyticsRow {
	date?: string | undefined;
	followers_count?: number | undefined;
	total_views?: number | undefined;
	total_likes?: number | undefined;
	total_replies?: number | undefined;
	total_reposts?: number | undefined;
	engagement_rate?: number | undefined;
}

interface MetricHistoryRow {
	post_id?: string | undefined;
	hours_since_publish?: number | undefined;
	views_count?: number | undefined;
}

interface PostWithPublishedAt {
	id?: string | undefined;
	published_at?: string | undefined;
	content?: string | undefined;
	views_count?: number | undefined;
}

// ── Main Function ───────────────────────────────────────────────────────────

/**
 * Generate recommendations powered by historical account_analytics and
 * post_metric_history data. Runs independently of the main checks — failures
 * here never break existing recommendations.
 */
export async function getHistoryBasedRecommendations(
	accountId: string,
	_userId: string,
	platform: string,
): Promise<Recommendation[]> {
	const recs: Recommendation[] = [];

	// ── 1. Engagement trend alert (14-day account_analytics) ──────────
	try {
		const fourteenDaysAgo = new Date(Date.now() - 14 * 24 * 60 * 60 * 1000)
			.toISOString()
			.split("T")[0]!;
		const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000)
			.toISOString()
			.split("T")[0]!;

		const { data: analyticsRaw } = await dbAny()
			.from("account_analytics")
			.select(
				"date, total_views, total_likes, total_replies, total_reposts, engagement_rate",
			)
			.eq("account_id", accountId)
			.gte("date", fourteenDaysAgo)
			.order("date", { ascending: true });

		const analytics = (analyticsRaw || []) as AnalyticsRow[];

		if (analytics.length >= 10) {
			const prevWeek = analytics.filter((r) => r.date && r.date < sevenDaysAgo!);
			const thisWeek = analytics.filter(
				(r) => r.date && r.date >= sevenDaysAgo!,
			);

			if (prevWeek.length >= 3 && thisWeek.length >= 3) {
				// Use engagement_rate if available, otherwise compute from views+likes+replies
				const avgER = (rows: AnalyticsRow[]): number => {
					const withER = rows.filter(
						(r) => r.engagement_rate != null && r.engagement_rate > 0,
					);
					if (withER.length > 0) {
						return (
							withER.reduce((s, r) => s + (r.engagement_rate || 0), 0) /
							withER.length
						);
					}
					// Fallback: compute from totals
					const totalViews = rows.reduce((s, r) => s + (r.total_views || 0), 0);
					const totalEng = rows.reduce(
						(s, r) =>
							s +
							(r.total_likes || 0) +
							(r.total_replies || 0) +
							(r.total_reposts || 0),
						0,
					);
					return totalViews > 0 ? (totalEng / totalViews) * 100 : 0;
				};

				const prevER = avgER(prevWeek);
				const thisER = avgER(thisWeek);

				if (prevER > 0 && thisER < prevER) {
					const pctDrop = Math.round(((prevER - thisER) / prevER) * 100);
					if (pctDrop > 15) {
						recs.push({
							id: "engagement-decline",
							title: "Engagement rate declining",
							description: `Your engagement dropped ${pctDrop}% this week vs last. Consider refreshing content style or testing new formats.`,
							impactScore: 8,
							effortScore: 3,
							roi: 8 / 3,
							dataPoint: `${pctDrop}% ER decline week-over-week`,
							icon: "\u{1F4C9}",
							confidence: "high",
							confidenceLabel: "Based on 14-day account analytics trend",
							ctaPath: "/ai-studio",
							category: "content",
							baselineValue: thisER,
						});
					}
				}
			}
		}
	} catch (err) {
		logger.warn(
			"[lowHangingFruit] History rec: engagement trend check failed",
			{
				error: String(err),
				accountId,
			},
		);
	}

	// ── 2. Best posting hour (from post_metric_history) ───────────────
	try {
		// Get posts with their published_at for hour bucketing
		let postsQ = dbAny().from("posts").select("id, published_at, views_count");
		postsQ = postAccountFilter(postsQ, platform, accountId);
		const { data: postsRaw } = await postsQ
			.eq("status", "published")
			.not("published_at", "is", null)
			.order("published_at", { ascending: false })
			.limit(200);

		const postsData = (postsRaw || []) as PostWithPublishedAt[];

		if (postsData.length >= 10) {
			// Try post_metric_history for more granular views data
			const postIds = postsData
				.map((p) => p.id)
				.filter(Boolean)
				.slice(0, 100);

			let viewsByPostId: Map<string, number> | null = null;
			try {
				// Get the latest snapshot per post (most accurate view count)
				const { data: historyRaw } = await dbAny()
					.from("post_metric_history")
					.select("post_id, views_count")
					.in("post_id", postIds)
					.gte("hours_since_publish", 24)
					.order("hours_since_publish", { ascending: false });

				const history = (historyRaw || []) as MetricHistoryRow[];
				if (history.length > 0) {
					viewsByPostId = new Map<string, number>();
					for (const row of history) {
						if (
							row.post_id &&
							!viewsByPostId.has(row.post_id) &&
							row.views_count != null
						) {
							viewsByPostId.set(row.post_id, row.views_count);
						}
					}
				}
			} catch {
				// post_metric_history may not exist — fall through to posts.views_count
			}

			// Group posts by hour-of-day
			const hourBuckets: Record<number, { totalViews: number; count: number }> =
				{};
			let postsAnalyzed = 0;

			for (const p of postsData) {
				if (!p.published_at || !p.id) continue;
				const hour = new Date(p.published_at).getUTCHours();
				const views = (viewsByPostId?.get(p.id) ?? p.views_count) || 0;
				if (!hourBuckets[hour]) hourBuckets[hour] = { totalViews: 0, count: 0 };
				hourBuckets[hour].totalViews += views;
				hourBuckets[hour].count++;
				postsAnalyzed++;
			}

			const hourEntries = Object.entries(hourBuckets)
				.filter(([_h, v]) => v.count >= 2)
				.map(([h, v]) => ({
					hour: parseInt(h, 10),
					avgViews: v.totalViews / v.count,
					count: v.count,
				}));

			if (hourEntries.length >= 3) {
				hourEntries.sort((a, b) => b.avgViews - a.avgViews);
				const bestEntry = hourEntries[0];
				const overallAvg =
					hourEntries.reduce((s, e) => s + e.avgViews, 0) / hourEntries.length;

				if (overallAvg > 0 && bestEntry!.avgViews > overallAvg * 1.2) {
					const improvement = Math.round(
						((bestEntry!.avgViews - overallAvg) / overallAvg) * 100,
					);
					const hr = bestEntry!.hour % 12 || 12;
					const ampm = bestEntry!.hour < 12 ? "AM" : "PM";
					const bestHourLabel = `${hr} ${ampm}`;

					recs.push({
						id: "optimal-timing",
						title: `Post at ${bestHourLabel} UTC for maximum reach`,
						description: `Posts at ${bestHourLabel} UTC get ${improvement}% more views on average. Based on ${postsAnalyzed} posts analyzed.`,
						impactScore: 7,
						effortScore: 1,
						roi: 7,
						dataPoint: `${improvement}% more views at ${bestHourLabel} UTC`,
						icon: "\u23F0",
						confidence: postsAnalyzed >= 30 ? "high" : "medium",
						confidenceLabel:
							postsAnalyzed >= 30
								? `Strong evidence from ${postsAnalyzed} posts`
								: `Based on ${postsAnalyzed} recent posts`,
						ctaPath: "/compose",
						category: "timing",
						baselineValue: overallAvg,
					});
				}
			}
		}
	} catch (err) {
		logger.warn(
			"[lowHangingFruit] History rec: best posting hour check failed",
			{
				error: String(err),
				accountId,
			},
		);
	}

	// ── 3. High-velocity post pattern ─────────────────────────────────
	try {
		// Find posts with velocity data from post_metric_history
		let velocityQ = dbAny()
			.from("posts")
			.select("id, published_at, content, views_count");
		velocityQ = postAccountFilter(velocityQ, platform, accountId);
		const { data: postsForVelocity } = await velocityQ
			.eq("status", "published")
			.not("published_at", "is", null)
			.order("published_at", { ascending: false })
			.limit(100);

		const velocityPosts = (postsForVelocity || []) as PostWithPublishedAt[];

		if (velocityPosts.length >= 15) {
			const postIds = velocityPosts.map((p) => p.id).filter(Boolean);

			// Get the ~24h snapshot for velocity calculation
			const { data: snapshotsRaw } = await dbAny()
				.from("post_metric_history")
				.select("post_id, hours_since_publish, views_count")
				.in("post_id", postIds)
				.gte("hours_since_publish", 12)
				.lte("hours_since_publish", 48)
				.order("hours_since_publish", { ascending: true });

			const snapshots = (snapshotsRaw || []) as MetricHistoryRow[];

			if (snapshots.length >= 10) {
				// Take earliest snapshot per post in the 12-48h window
				const velocityByPost = new Map<
					string,
					{ viewsPerHour: number; content: string }
				>();
				const seenPosts = new Set<string>();

				for (const snap of snapshots) {
					if (!snap.post_id || seenPosts.has(snap.post_id)) continue;
					seenPosts.add(snap.post_id);

					const hoursElapsed = snap.hours_since_publish || 24;
					const views = snap.views_count || 0;
					if (hoursElapsed > 0) {
						const post = velocityPosts.find((p) => p.id === snap.post_id);
						velocityByPost.set(snap.post_id, {
							viewsPerHour: views / hoursElapsed,
							content: post?.content || "",
						});
					}
				}

				if (velocityByPost.size >= 10) {
					const sorted = [...velocityByPost.entries()].sort(
						(a, b) => b[1].viewsPerHour - a[1].viewsPerHour,
					);

					// Top 10% by velocity
					const topCount = Math.max(2, Math.floor(sorted.length * 0.1));
					const topPosts = sorted.slice(0, topCount);
					const avgVelocity = Math.round(
						topPosts.reduce((s, [_id, v]) => s + v.viewsPerHour, 0) /
							topPosts.length,
					);

					// Detect patterns in top velocity posts
					const topContents = topPosts.map(([_id, v]) => v.content);
					const pattern = detectContentPattern(topContents);

					if (pattern) {
						recs.push({
							id: "velocity-pattern",
							title: "Your fastest-growing posts share a pattern",
							description: `Posts that go viral fastest tend to be ${pattern}. Your top velocity posts averaged ${avgVelocity} views/hour.`,
							impactScore: 9,
							effortScore: 2,
							roi: 4.5,
							dataPoint: `Top velocity: ${avgVelocity} views/hr`,
							icon: "\u{1F680}",
							confidence: "medium",
							confidenceLabel: `Pattern detected across ${topCount} top-performing posts`,
							ctaPath: "/ai-studio",
							category: "content",
							baselineValue: avgVelocity,
						});
					}
				}
			}
		}
	} catch (err) {
		logger.warn(
			"[lowHangingFruit] History rec: velocity pattern check failed",
			{
				error: String(err),
				accountId,
			},
		);
	}

	return recs;
}

/**
 * Detect simple patterns in a set of high-performing post contents.
 * Returns a human-readable pattern string or null if no clear pattern is found.
 */
function detectContentPattern(contents: string[]): string | null {
	if (contents.length < 2) return null;

	// Check if most are questions
	const questionCount = contents.filter((c) => {
		const firstLine = c.split("\n")[0] || "";
		return (
			firstLine.endsWith("?") ||
			/^(what|why|how|who|when|where|which|do you|have you|would you)/i.test(
				firstLine,
			)
		);
	}).length;
	if (questionCount / contents.length >= 0.6) return "questions or polls";

	// Check if most are short (< 100 chars)
	const shortCount = contents.filter((c) => c.length < 100).length;
	if (shortCount / contents.length >= 0.7)
		return "short and punchy (under 100 characters)";

	// Check if most are long (> 300 chars)
	const longCount = contents.filter((c) => c.length > 300).length;
	if (longCount / contents.length >= 0.7)
		return "longer-form storytelling (300+ characters)";

	// Check if most contain lists/numbered items
	const listCount = contents.filter(
		(c) => /^\d+[.)]/m.test(c) || /^[-•]/m.test(c),
	).length;
	if (listCount / contents.length >= 0.6) return "lists or numbered tips";

	// Check if most contain hashtags
	const hashtagCount = contents.filter(
		(c) => (c.match(/#\w+/g) || []).length >= 2,
	).length;
	if (hashtagCount / contents.length >= 0.7) return "hashtag-rich posts";

	// Check if most contain mentions
	const mentionCount = contents.filter((c) => /@\w+/.test(c)).length;
	if (mentionCount / contents.length >= 0.6)
		return "posts mentioning other accounts";

	return null;
}
