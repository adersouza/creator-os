// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * trendEngine.ts — Compute trend forecasts from historical data.
 *
 * Analyzes account_analytics snapshots + post performance to produce:
 * - Follower growth projection (30-day linear regression + confidence bands)
 * - Engagement trend classification (rising/stable/falling)
 * - Best posting windows (hour × dayOfWeek engagement matrix)
 * - Content type performance ranking
 * - Topic/hashtag trend detection (rising vs declining)
 * - Seasonal day-of-week patterns
 * - Actionable signals (alerts + opportunities)
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { logger } from "./logger.js";

interface AnalyticsRow {
	date?: string | undefined;
	followers_count?: number | undefined;
	total_views?: number | undefined;
	total_likes?: number | undefined;
	total_replies?: number | undefined;
	engagement_rate?: number | undefined;
	[key: string]: unknown;
}

interface PostRow {
	id?: string | undefined;
	content?: string | undefined;
	published_at?: string | undefined;
	views_count?: number | undefined;
	likes_count?: number | undefined;
	replies_count?: number | undefined;
	reposts_count?: number | undefined;
	engagement_rate?: number | undefined;
	media_type?: string | undefined;
	hashtags?: string[] | undefined;
	platform?: string | undefined;
	[key: string]: unknown;
}

interface FollowerHistoryRow {
	date?: string | undefined;
	follower_count?: number | undefined;
	followers_count?: number | undefined;
}

interface TrendKeywordRow {
	keyword?: string | undefined;
	category?: string | undefined;
	is_active?: boolean | undefined;
}

interface TopicEntry {
	topic: string;
	growthPct: number;
	volume: number;
}

interface DecliningTopicEntry {
	topic: string;
	declinePct: number;
	volume: number;
}

interface SignalEntry {
	type: string;
	severity: string;
	message: string;
}

const MS_PER_DAY = 86_400_000;

// ── Linear regression (server-side duplicate of growthForecast.ts) ───────

interface DataPoint {
	x: number;
	y: number;
}

interface RegressionResult {
	slope: number;
	intercept: number;
	r2: number;
}

function linearRegression(points: DataPoint[]): RegressionResult {
	const n = points.length;
	if (n < 2) return { slope: 0, intercept: points[0]?.y ?? 0, r2: 0 };

	let sumX = 0,
		sumY = 0,
		sumXY = 0,
		sumXX = 0;
	for (const { x, y } of points) {
		sumX += x;
		sumY += y;
		sumXY += x * y;
		sumXX += x * x;
	}

	const denom = n * sumXX - sumX * sumX;
	if (denom === 0) return { slope: 0, intercept: sumY / n, r2: 0 };

	const slope = (n * sumXY - sumX * sumY) / denom;
	const intercept = (sumY - slope * sumX) / n;

	const meanY = sumY / n;
	let ssTot = 0,
		ssRes = 0;
	for (const { x, y } of points) {
		ssTot += (y - meanY) ** 2;
		ssRes += (y - (slope * x + intercept)) ** 2;
	}

	return { slope, intercept, r2: ssTot === 0 ? 1 : 1 - ssRes / ssTot };
}

// ── Main forecast generator ─────────────────────────────────────────────

export async function generateForecast(
	supabase: SupabaseClient,
	userId: string,
	accountId: string,
): Promise<Record<string, unknown>> {
	const now = new Date();
	const todayStr = now.toISOString().slice(0, 10);
	const day90Ago = new Date(now.getTime() - 90 * MS_PER_DAY).toISOString();
	const day30Ago = new Date(now.getTime() - 30 * MS_PER_DAY).toISOString();

	// ── Fetch data in parallel ──────────────────────────────────────────

	const [analyticsRes, postsRes, followerRes, trendKeywordsRes] =
		await Promise.all([
			supabase
				.from("account_analytics")
				.select(
					"date, followers_count, total_views, total_likes, total_replies, engagement_rate",
				)
				.eq("account_id", accountId)
				.gte("date", day90Ago.slice(0, 10))
				.order("date", { ascending: true }),
			supabase
				.from("posts")
				.select(
					"id, content, published_at, views_count, likes_count, replies_count, reposts_count, engagement_rate, media_type, hashtags, platform",
				)
				.eq("account_id", accountId)
				.eq("user_id", userId)
				.eq("status", "published")
				.gte("published_at", day90Ago)
				.order("published_at", { ascending: true }),
			supabase
				.from("follower_history")
				.select("date, follower_count")
				.eq("account_id", accountId)
				.gte("date", day90Ago.slice(0, 10))
				.order("date", { ascending: true }),
			// #506: Fetch user's custom trend keywords to include in topic analysis
			supabase
				.from("trend_keywords")
				.select("keyword, category, is_active")
				.eq("user_id", userId)
				.eq("is_active", true),
		]);

	const analytics: AnalyticsRow[] = analyticsRes.data || [];
	const posts: PostRow[] = postsRes.data || [];
	const followerHistory: FollowerHistoryRow[] = followerRes.data || [];
	const trendKeywords: TrendKeywordRow[] = trendKeywordsRes.data || [];

	const dataPointsUsed = analytics.length + posts.length;

	// ── 1. Follower forecast (30-day projection) ────────────────────────

	const followerSource = (
		followerHistory.length > 0 ? followerHistory : analytics
	) as (FollowerHistoryRow | AnalyticsRow)[];
	const followerPoints: DataPoint[] = followerSource
		.filter((r) => r.follower_count || r.followers_count)
		.map((r, i) => ({
			x: i,
			y:
				(r as FollowerHistoryRow).follower_count ||
				(r as AnalyticsRow).followers_count ||
				0,
		}));

	const followerReg = linearRegression(followerPoints);
	const lastFollowerX = followerPoints.length - 1;
	const residuals = followerPoints.map(
		(p) => p.y - (followerReg.slope * p.x + followerReg.intercept),
	);
	const stddev = Math.sqrt(
		residuals.reduce((s, r) => s + r * r, 0) / Math.max(1, residuals.length),
	);

	const followerForecast = Array.from({ length: 30 }, (_, d) => {
		const x = lastFollowerX + d + 1;
		const predicted = Math.max(
			0,
			Math.round(followerReg.slope * x + followerReg.intercept),
		);
		const forecastDate = new Date(now);
		forecastDate.setDate(forecastDate.getDate() + d + 1);
		return {
			date: forecastDate.toISOString().slice(0, 10),
			predicted,
			upper: Math.round(predicted + stddev),
			lower: Math.max(0, Math.round(predicted - stddev)),
		};
	});

	// Classify follower trend via velocity change
	let followerTrend: string = "steady";
	let followerVelocity = followerReg.slope;
	if (followerPoints.length >= 14) {
		const halfIdx = Math.floor(followerPoints.length / 2);
		const firstHalf = linearRegression(followerPoints.slice(0, halfIdx));
		const secondHalf = linearRegression(followerPoints.slice(halfIdx));
		const accel = secondHalf.slope - firstHalf.slope;
		followerVelocity = secondHalf.slope;

		if (secondHalf.slope < 0) followerTrend = "declining";
		else if (accel > 0.5) followerTrend = "accelerating";
		else if (accel < -0.5) followerTrend = "decelerating";
		else followerTrend = "steady";
	}

	// ── 2. Engagement trend ─────────────────────────────────────────────

	const engagementPoints: DataPoint[] = analytics
		.filter((r: AnalyticsRow) => r.engagement_rate != null)
		.map((r: AnalyticsRow, i: number) => ({
			x: i,
			y: Number(r.engagement_rate),
		}));

	const engagementReg = linearRegression(engagementPoints);
	const engagementForecast = Array.from({ length: 14 }, (_, d) => {
		const x = engagementPoints.length + d;
		const forecastDate = new Date(now);
		forecastDate.setDate(forecastDate.getDate() + d + 1);
		return {
			date: forecastDate.toISOString().slice(0, 10),
			predicted: Math.max(
				0,
				Number((engagementReg.slope * x + engagementReg.intercept).toFixed(4)),
			),
		};
	});

	let engagementTrend: string = "stable";
	if (engagementReg.slope > 0.0005) engagementTrend = "rising";
	else if (engagementReg.slope < -0.0005) engagementTrend = "falling";

	const avgEngagement =
		engagementPoints.length > 0
			? engagementPoints.reduce((s, p) => s + p.y, 0) / engagementPoints.length
			: 0;

	// ── 3. Best posting windows ─────────────────────────────────────────

	const hourDayMap: Map<string, { total: number; count: number }> = new Map();
	for (const post of posts) {
		if (!post.published_at) continue;
		const d = new Date(post.published_at);
		const hour = d.getUTCHours();
		const dow = d.getUTCDay();
		const key = `${dow}-${hour}`;
		const entry = hourDayMap.get(key) || { total: 0, count: 0 };
		entry.total += Number(post.engagement_rate || 0);
		entry.count += 1;
		hourDayMap.set(key, entry);
	}

	const bestHours = Array.from(hourDayMap.entries())
		.map(([key, val]) => {
			const [dow, hour] = key.split("-").map(Number);
			return {
				dayOfWeek: dow,
				hour,
				avgEngagement: val.total / val.count,
				postCount: val.count,
			};
		})
		.filter((h) => h.postCount >= 2)
		.sort((a, b) => b.avgEngagement - a.avgEngagement)
		.slice(0, 10);

	// ── 4. Content type performance ─────────────────────────────────────

	const typeMap: Map<string, { total: number; count: number }> = new Map();
	for (const post of posts) {
		const type = post.media_type || "text";
		const entry = typeMap.get(type) || { total: 0, count: 0 };
		entry.total += Number(post.engagement_rate || 0);
		entry.count += 1;
		typeMap.set(type, entry);
	}

	const bestContentTypes = Array.from(typeMap.entries())
		.map(([type, val]) => ({
			type,
			avgEngagement: Number((val.total / val.count).toFixed(4)),
			count: val.count,
		}))
		.sort((a, b) => b.avgEngagement - a.avgEngagement);

	// ── 5. Topic/hashtag trends ─────────────────────────────────────────

	const recentCutoff = new Date(now.getTime() - 14 * MS_PER_DAY).toISOString();

	const topicRecent: Map<string, { engagement: number; count: number }> =
		new Map();
	const topicOlder: Map<string, { engagement: number; count: number }> =
		new Map();

	// #506: Build a set of user's custom trend keywords for cross-referencing
	const userKeywordSet = new Set(
		trendKeywords.map((tk: TrendKeywordRow) =>
			(tk.keyword || "").toLowerCase().trim(),
		),
	);

	for (const post of posts) {
		const tags: string[] = post.hashtags || [];
		// #506: Also scan post content for user's custom trend keywords
		const contentKeywordMatches: string[] = [];
		if (post.content && userKeywordSet.size > 0) {
			const lowerContent = post.content.toLowerCase();
			for (const kw of userKeywordSet) {
				if (kw && lowerContent.includes(kw)) {
					contentKeywordMatches.push(kw);
				}
			}
		}
		const allTopics = [...tags, ...contentKeywordMatches];
		if (allTopics.length === 0) continue;
		const isRecent = (post.published_at ?? "") >= recentCutoff;
		const map = isRecent ? topicRecent : topicOlder;
		for (const tag of allTopics) {
			const t = tag.toLowerCase().replace(/^#/, "");
			const entry = map.get(t) || { engagement: 0, count: 0 };
			entry.engagement += Number(post.engagement_rate || 0);
			entry.count += 1;
			map.set(t, entry);
		}
	}

	const risingTopics: TopicEntry[] = [];
	const decliningTopics: DecliningTopicEntry[] = [];

	for (const [topic, recent] of topicRecent.entries()) {
		const older = topicOlder.get(topic);
		if (!older || older.count < 2) continue;
		const recentAvg = recent.engagement / recent.count;
		const olderAvg = older.engagement / older.count;
		const growthPct =
			olderAvg > 0 ? ((recentAvg - olderAvg) / olderAvg) * 100 : 0;

		if (growthPct > 20) {
			risingTopics.push({
				topic,
				growthPct: Math.round(growthPct),
				volume: recent.count,
			});
		} else if (growthPct < -20) {
			decliningTopics.push({
				topic,
				declinePct: Math.round(Math.abs(growthPct)),
				volume: recent.count,
			});
		}
	}

	risingTopics.sort((a, b) => b.growthPct - a.growthPct);
	decliningTopics.sort((a, b) => b.declinePct - a.declinePct);

	// ── 6. Seasonal patterns (day-of-week) ──────────────────────────────

	const dowMap: Map<
		number,
		{ views: number; likes: number; engagement: number; count: number }
	> = new Map();
	for (const post of posts) {
		if (!post.published_at) continue;
		const dow = new Date(post.published_at).getUTCDay();
		const entry = dowMap.get(dow) || {
			views: 0,
			likes: 0,
			engagement: 0,
			count: 0,
		};
		entry.views += Number(post.views_count || 0);
		entry.likes += Number(post.likes_count || 0);
		entry.engagement += Number(post.engagement_rate || 0);
		entry.count += 1;
		dowMap.set(dow, entry);
	}

	const DOW_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
	const seasonalPattern: Record<
		string,
		{
			avgViews: number;
			avgLikes: number;
			avgEngagement: number;
			postCount: number;
		}
	> = {};
	for (const [dow, val] of dowMap.entries()) {
		seasonalPattern[DOW_NAMES[dow]!] = {
			avgViews: Math.round(val.views / val.count),
			avgLikes: Math.round(val.likes / val.count),
			avgEngagement: Number((val.engagement / val.count).toFixed(4)),
			postCount: val.count,
		};
	}

	// ── 7. Generate signals ─────────────────────────────────────────────

	const signals: SignalEntry[] = [];

	if (followerTrend === "declining") {
		signals.push({
			type: "follower_decline",
			severity: "high",
			message: `Followers are declining at ${Math.abs(followerVelocity).toFixed(1)}/day. Review recent content strategy.`,
		});
	}
	if (followerTrend === "accelerating") {
		signals.push({
			type: "growth_acceleration",
			severity: "info",
			message: `Growth is accelerating. Keep doing what's working — your recent content strategy is paying off.`,
		});
	}
	if (engagementTrend === "falling" && avgEngagement > 0) {
		signals.push({
			type: "engagement_decline",
			severity: "medium",
			message: `Engagement trending down over the last ${engagementPoints.length} days. Consider varying content types or posting times.`,
		});
	}
	if (risingTopics.length > 0) {
		signals.push({
			type: "trending_topic",
			severity: "info",
			message: `#${risingTopics[0]!.topic} is trending up ${risingTopics[0]!.growthPct}%. Double down on this topic.`,
		});
	}
	if (decliningTopics.length > 0) {
		signals.push({
			type: "declining_topic",
			severity: "low",
			message: `#${decliningTopics[0]!.topic} engagement is down ${decliningTopics[0]!.declinePct}%. Consider fresh angles or retiring it.`,
		});
	}

	// #506: Signal when user's tracked trend keywords are rising or declining
	if (userKeywordSet.size > 0) {
		const risingTracked = risingTopics.filter((t: TopicEntry) =>
			userKeywordSet.has(t.topic),
		);
		const decliningTracked = decliningTopics.filter((t: DecliningTopicEntry) =>
			userKeywordSet.has(t.topic),
		);
		for (const kw of risingTracked) {
			signals.push({
				type: "tracked_keyword_rising",
				severity: "info",
				message: `Your tracked keyword "${kw.topic}" is trending up ${kw.growthPct}% — great time to create content around it.`,
			});
		}
		for (const kw of decliningTracked) {
			signals.push({
				type: "tracked_keyword_declining",
				severity: "low",
				message: `Your tracked keyword "${kw.topic}" is declining ${kw.declinePct}% — consider pivoting your angle.`,
			});
		}
	}
	if (bestHours.length > 0) {
		const top = bestHours[0];
		signals.push({
			type: "optimal_timing",
			severity: "info",
			message: `Your best posting window is ${DOW_NAMES[top!.dayOfWeek!]} at ${top!.hour}:00 UTC (${top!.avgEngagement.toFixed(2)}% avg engagement).`,
		});
	}

	// Check posting consistency (last 14 days)
	const recentPosts = posts.filter(
		(p: PostRow) => (p.published_at ?? "") >= day30Ago,
	);
	if (recentPosts.length < 4) {
		signals.push({
			type: "low_frequency",
			severity: "medium",
			message: `Only ${recentPosts.length} posts in the last 30 days. Algorithms favor consistent posting (3-5x/week).`,
		});
	}

	// Engagement outlier — find if any content type massively outperforms
	if (bestContentTypes.length >= 2) {
		const best = bestContentTypes[0];
		const secondBest = bestContentTypes[1];
		if (
			secondBest!.avgEngagement > 0 &&
			best!.avgEngagement / secondBest!.avgEngagement > 1.5
		) {
			signals.push({
				type: "content_type_winner",
				severity: "info",
				message: `"${best!.type}" posts get ${Math.round((best!.avgEngagement / secondBest!.avgEngagement - 1) * 100)}% more engagement than "${secondBest!.type}". Shift your content mix.`,
			});
		}
	}

	// ── 8. Persist forecast ─────────────────────────────────────────────

	const forecastRow = {
		user_id: userId,
		account_id: accountId,
		forecast_date: todayStr,
		follower_forecast: followerForecast,
		follower_trend: followerTrend,
		follower_velocity: Number(followerVelocity.toFixed(2)),
		engagement_forecast: engagementForecast,
		engagement_trend: engagementTrend,
		avg_engagement_rate: Number(avgEngagement.toFixed(4)),
		best_hours: bestHours,
		best_content_types: bestContentTypes,
		rising_topics: risingTopics.slice(0, 10),
		declining_topics: decliningTopics.slice(0, 10),
		seasonal_pattern: seasonalPattern,
		signals,
		data_points_used: dataPointsUsed,
		r_squared: Number(followerReg.r2.toFixed(4)),
	};

	const { data, error } = await supabase
		.from("trend_forecasts")
		.upsert(forecastRow, { onConflict: "user_id,account_id,forecast_date" })
		.select()
		.maybeSingle();

	if (error) {
		logger.error("[trendEngine] Failed to persist forecast", {
			error: error.message,
		});
		return forecastRow; // Return computed data even if persistence fails
	}

	return data;
}
