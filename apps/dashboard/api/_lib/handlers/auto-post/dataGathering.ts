/**
 * Data Gathering for AI Content Generation
 *
 * All Supabase queries that fetch context for the AI prompt:
 * - Competitor posts for style examples
 * - Trending topics from trend forecasts
 * - Own top-performing posts
 * - Own engagement patterns (question vs statement, length, emoji, hours)
 * - Recent post context for dedup
 *
 * Extracted from contentSelection.ts for separation of concerns.
 */

import { logger, serializeError } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";

const db = () => getSupabaseAny();
const isRankableCompetitorMetric = (quality?: string | null) =>
	quality === "valid_engagement" || quality === "scraper_estimated";
const hasReusableCompetitorFrame = (content: string | null | undefined) => {
	const text = String(content || "")
		.toLowerCase()
		.replace(/[’']/g, "'")
		.trim();
	if (!text) return false;
	if (/https?:\/\/|www\.|telegram|snap[: ]|@\w/.test(text)) return false;
	if (/\b(fashionnova|promo code|discount code|link in bio)\b/.test(text))
		return false;
	const words = text.split(/\s+/).filter(Boolean);
	const profileCuriositySignal =
		/\b(would you date|date a girl|am i|still cute|cute|pretty|single|girls? who|girl who|red flag|toxic|lose interest|crop top|gym gains?|anime|gaming|headset|music|playlist|gatekeep|gatekeeping|top\s*3|drop your|pre-?workout|underrated|prove me wrong|check my profile|talk to me|text me|dm me|horny|dick)\b/.test(
			text,
		);
	if (profileCuriositySignal) return true;
	if (words.length <= 3) return false;
	if (/^blessed\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/.test(text))
		return false;
	return words.length >= 4 && text.length >= 24;
};

// ============================================================================
// Competitor Posts for AI Style Examples
// ============================================================================

export async function getCompetitorTopPostsForAI(
	ownerId: string,
	limit = 20,
	workspaceId?: string,
	allowedCompetitorIds?: string[],
): Promise<
	{
		id?: string | undefined;
		content: string;
		username: string;
		engagement: number;
		media_type?: string | undefined;
		competitor_id?: string | undefined;
		metric_quality?: string | undefined;
		hook_type?: string | undefined;
		topic_label?: string | undefined;
		format_type?: string | undefined;
		media_style?: string | undefined;
		posting_hour?: number | undefined;
	}[]
> {
	try {
		let compQuery = db()
			.from("competitors")
			.select("id, username")
			.eq("user_id", ownerId)
			.or("sync_status.eq.active,sync_status.is.null");

		if (allowedCompetitorIds && allowedCompetitorIds.length > 0) {
			compQuery = compQuery.in("id", allowedCompetitorIds);
		}

		const { data: competitors, error: compError } = await compQuery;

		if (compError || !competitors || competitors.length === 0) {
			logger.warn("No competitors found for AI content generation", {
				ownerId,
				workspaceId,
				error: compError ? String(compError) : undefined,
				competitorCount: competitors?.length ?? 0,
				hint: "Add competitors via bulk_add_competitors to enable competitor-sourced content",
			});
			return [];
		}

		logger.info("Competitor style examples lookup", {
			ownerId,
			competitorCount: competitors.length,
		});

		const competitorIds = competitors.map((c) => c.id);

		// Dedup: get source_content already used in this workspace's queue (last 14 days)
		let usedSourceContents: Set<string> = new Set();
		if (workspaceId) {
			const sevenDaysAgo = new Date(
				Date.now() - 14 * 24 * 60 * 60 * 1000,
			).toISOString();
			const { data: usedItems } = await db()
				.from("auto_post_queue")
				.select("source_content")
				.eq("workspace_id", workspaceId)
				.in("status", ["published", "pending", "queued"])
				.not("source_content", "is", null)
				.gte("created_at", sevenDaysAgo);

			if (usedItems) {
				usedSourceContents = new Set(
					usedItems
						.map((item) => item.source_content as string)
						.filter(Boolean),
				);
			}
		}

		// Pull competitor corpus by recency. Threads competitor engagement from the
		// official profile_posts endpoint is usually unavailable, so performance
		// weighting is only allowed for rows explicitly marked rankable.
		const { data: recentPosts, error: postsError } = await db()
			.from("competitor_top_posts")
			.select(
				"id, content, competitor_username, engagement_score, media_type, competitor_id, scraped_at, metric_quality, hook_type, topic_label, format_type, content_length_bucket, media_style, posting_hour, account_size_bucket",
			)
			.in("competitor_id", competitorIds)
			.not("content", "is", null)
			.neq("content", "")
			.order("scraped_at", { ascending: false })
			.limit(200);

		const corpusPosts = (recentPosts ?? [])
			.filter((post) => hasReusableCompetitorFrame(post.content as string | null))
			.slice(0, 200);

		// Weighted random shuffle — higher engagement only matters when the metric
		// quality says it is valid. Unknown Threads stats remain corpus examples.
		function weightedShuffle<
			T extends {
				engagement_score?: number | null | undefined;
				metric_quality?: string | null | undefined;
				hook_type?: string | null | undefined;
				topic_label?: string | null | undefined;
			},
		>(arr: T[]): T[] {
			const weighted = arr.map((item) => ({
				item,
				weight:
					Math.random() *
					(isRankableCompetitorMetric(item.metric_quality)
						? Math.max(1, item.engagement_score || 1) ** 0.5
						: 1),
			}));
			weighted.sort((a, b) => b.weight - a.weight);
			return weighted.map((w) => w.item);
		}

		const posts = weightedShuffle(corpusPosts);

		if (postsError || !posts || posts.length === 0) {
			logger.warn("No competitor posts available for style examples", {
				ownerId,
				competitorCount: competitors.length,
				postsError: postsError ? String(postsError) : undefined,
				postsFound: posts?.length ?? 0,
			});
			return [];
		}

		// Filter out already-adapted posts
		const fresh = posts.filter(
			(p) => p.content && !usedSourceContents.has(p.content),
		);

		const pool = fresh.length > 0 ? fresh : posts;

		// Spread across competitors (don't take 20 from the same person)
		const perCompetitor = new Map<string, number>();
		const maxPerCompetitor = Math.max(
			3,
			Math.ceil(limit / Math.min(competitors.length, 10)),
		);
		const selected: typeof pool = [];
		const patternSeen = new Set<string>();

		for (const p of pool) {
			if (selected.length >= limit) break;
			const cid = p.competitor_id as string;
			const count = perCompetitor.get(cid) || 0;
			if (count >= maxPerCompetitor) continue;
			const patternKey = `${p.hook_type || "unknown"}:${p.topic_label || "uncategorized"}`;
			const patternPenalty =
				patternSeen.has(patternKey) && selected.length < Math.floor(limit * 0.75);
			if (patternPenalty) continue;
			perCompetitor.set(cid, count + 1);
			patternSeen.add(patternKey);
			selected.push(p);
		}

		if (selected.length < limit) {
			const selectedContents = new Set(selected.map((p) => p.content));
			for (const p of pool) {
				if (selected.length >= limit) break;
				if (!p.content || selectedContents.has(p.content)) continue;
				selectedContents.add(p.content);
				selected.push(p);
			}
		}

		logger.info("Competitor style examples selected", {
			totalPool: pool.length,
			selected: selected.length,
			uniqueCompetitors: perCompetitor.size,
			rankableMetricRows: selected.filter((p) =>
				isRankableCompetitorMetric(p.metric_quality),
			).length,
			patterns: patternSeen.size,
		});

		return selected.map((p) => ({
			content: p.content || "",
			id: (p.id as string) || undefined,
			username: p.competitor_username || "competitor",
			engagement: p.engagement_score || 0,
			media_type: p.media_type || undefined,
			competitor_id: (p.competitor_id as string) || undefined,
			metric_quality: (p.metric_quality as string) || undefined,
			hook_type: (p.hook_type as string) || undefined,
			topic_label: (p.topic_label as string) || undefined,
			format_type: (p.format_type as string) || undefined,
			media_style: (p.media_style as string) || undefined,
			posting_hour:
				typeof p.posting_hour === "number"
					? (p.posting_hour as number)
					: undefined,
		}));
	} catch (err) {
		logger.warn("Failed to fetch competitor posts for AI generation", {
			ownerId,
			error: String(err),
		});
		return [];
	}
}

// ============================================================================
// Competitor Velocity Detection
// ============================================================================

/**
 * Detect fast-rising competitor posts for priority adaptation.
 * A post is "trending" if it's from the last 48h and has engagement > 2x
 * that competitor's average. This only uses rows with valid metric quality;
 * Threads corpus rows with unavailable stats are intentionally ignored.
 * These should get priority in the AI prompt
 * because they represent what's working RIGHT NOW in the niche.
 *
 * Returns top 5 trending posts sorted by velocity score (engagement / age_hours).
 */
export async function getCompetitorTrendingPosts(
	ownerId: string,
	workspaceId?: string,
	allowedCompetitorIds?: string[],
): Promise<
	Array<{
		content: string;
		username: string;
		engagement: number;
		velocity: number;
		competitor_id: string;
		hoursOld: number;
	}>
> {
	try {
		// Get active competitors
		const { data: competitors } = await db()
			.from("competitors")
			.select("id, username")
			.eq("user_id", ownerId)
			.or("sync_status.eq.active,sync_status.is.null");

		let activeCompetitors = competitors || [];
		if (allowedCompetitorIds && allowedCompetitorIds.length > 0) {
			const allowed = new Set(allowedCompetitorIds);
			activeCompetitors = activeCompetitors.filter((c) => allowed.has(c.id));
		}

		if (activeCompetitors.length === 0) return [];

		const competitorIds = activeCompetitors.map((c) => c.id);
		const fortyEightHoursAgo = new Date(
			Date.now() - 48 * 60 * 60 * 1000,
		).toISOString();
		const fourteenDaysAgo = new Date(
			Date.now() - 14 * 86_400_000,
		).toISOString();

		// Get recent posts (last 48h) with engagement
		const { data: recentPosts } = await db()
			.from("competitor_top_posts")
			.select(
				"id, content, competitor_id, competitor_username, engagement_score, scraped_at, published_at",
			)
			.in("competitor_id", competitorIds)
			.not("content", "is", null)
			.gte("scraped_at", fortyEightHoursAgo)
			.in("metric_quality", ["valid_engagement", "scraper_estimated"])
			.gt("engagement_score", 0)
			.order("engagement_score", { ascending: false })
			.limit(50);

		if (!recentPosts || recentPosts.length < 3) return [];

		// Get each competitor's 14-day average engagement for baseline
		const { data: baselinePosts } = await db()
			.from("competitor_top_posts")
			.select("competitor_id, engagement_score")
			.in("competitor_id", competitorIds)
			.gte("scraped_at", fourteenDaysAgo)
			.in("metric_quality", ["valid_engagement", "scraper_estimated"])
			.gt("engagement_score", 0)
			.limit(500);

		const competitorAvg = new Map<string, number>();
		if (baselinePosts && baselinePosts.length > 0) {
			const buckets = new Map<string, number[]>();
			for (const p of baselinePosts) {
				const cid = p.competitor_id as string;
				const scores = buckets.get(cid) || [];
				scores.push((p.engagement_score as number) || 0);
				buckets.set(cid, scores);
			}
			for (const [cid, scores] of buckets) {
				if (scores.length >= 3) {
					competitorAvg.set(
						cid,
						scores.reduce((a, b) => a + b, 0) / scores.length,
					);
				}
			}
		}

		// Dedup: skip posts already adapted in this workspace
		let usedContents = new Set<string>();
		if (workspaceId) {
			const sevenDaysAgo = new Date(Date.now() - 7 * 86_400_000).toISOString();
			const { data: usedItems } = await db()
				.from("auto_post_queue")
				.select("source_content")
				.eq("workspace_id", workspaceId)
				.in("status", ["published", "pending", "queued"])
				.not("source_content", "is", null)
				.gte("created_at", sevenDaysAgo);
			if (usedItems) {
				usedContents = new Set(
					usedItems.map((i) => i.source_content as string).filter(Boolean),
				);
			}
		}

		// Score: engagement relative to competitor average × recency
		const trending: Array<{
			content: string;
			username: string;
			engagement: number;
			velocity: number;
			competitor_id: string;
			hoursOld: number;
		}> = [];

		for (const post of recentPosts) {
			if (!hasReusableCompetitorFrame(post.content as string | null)) continue;
			if (!post.content || usedContents.has(post.content)) continue;

			const cid = post.competitor_id as string;
			const avg = competitorAvg.get(cid);
			if (!avg || avg <= 0) continue;

			const engagement = (post.engagement_score as number) || 0;
			const ratio = engagement / avg;

			// Must be at least 2x competitor's average to be "trending"
			if (ratio < 2) continue;

			const publishedAt = post.published_at || post.scraped_at;
			const hoursOld = Math.max(
				1,
				(Date.now() - new Date(publishedAt as string).getTime()) /
					(60 * 60 * 1000),
			);
			const velocity = engagement / hoursOld;

			trending.push({
				content: post.content as string,
				username: (post.competitor_username as string) || "competitor",
				engagement,
				velocity,
				competitor_id: cid,
				hoursOld: Math.round(hoursOld),
			});
		}

		// Sort by velocity (highest first), return top 5
		trending.sort((a, b) => b.velocity - a.velocity);
		const result = trending.slice(0, 5);

		if (result.length > 0) {
			logger.info("[dataGathering] Competitor trending posts detected", {
				count: result.length,
				top: result[0]
					? `${result[0].username}: ${result[0].engagement} eng, ${result[0].hoursOld}h old`
					: "none",
			});
		}

		return result;
	} catch (err) {
		logger.warn(
			"[dataGathering] Competitor trending detection failed (non-critical)",
			{
				error: String(err),
			},
		);
		return [];
	}
}

// ============================================================================
// Trending Topics
// ============================================================================

/**
 * Fetch trending topics from trend_forecasts + hot competitor posts.
 * Returns a short list of topics the AI should weave into 1-2 posts per batch.
 * Lightweight: single DB query, cached by the fill cycle's lifetime.
 */
export async function getTrendingTopics(
	ownerId: string,
	_workspaceId?: string,
	allowedCompetitorIds?: string[],
): Promise<string[]> {
	const topics: string[] = [];
	try {
		// Source 1: Rising topics from trend_forecasts (from trend scanner cron)
		const { data: forecasts } = await db()
			.from("trend_forecasts")
			.select("rising_topics")
			.eq("user_id", ownerId)
			.not("rising_topics", "is", null)
			.order("forecast_date", { ascending: false })
			.limit(3);

		if (forecasts) {
			for (const f of forecasts) {
				const rising = f.rising_topics as string[] | null;
				if (Array.isArray(rising)) {
					for (const t of rising.slice(0, 5)) {
						if (t && !topics.includes(t)) topics.push(t);
					}
				}
			}
		}

		// Source 2: Recent competitor corpus from last 24h. This is pattern
		// discovery, not a fake performance benchmark.
		if (topics.length < 5) {
			let compQuery = db()
				.from("competitors")
				.select("id")
				.eq("user_id", ownerId)
				.or("sync_status.eq.active,sync_status.is.null");

			if (allowedCompetitorIds && allowedCompetitorIds.length > 0) {
				compQuery = compQuery.in("id", allowedCompetitorIds);
			}

			const { data: competitors } = await compQuery;
			const competitorIds = (competitors ?? [])
				.map((c) => c.id)
				.filter(Boolean);
			if (competitorIds.length === 0) return topics.slice(0, 8);

			const { data: hotPosts } = await db()
				.from("competitor_top_posts")
				.select("content")
				.in("competitor_id", competitorIds)
				.not("content", "is", null)
				.gte(
					"scraped_at",
					new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
				)
				.order("scraped_at", { ascending: false })
				.limit(10);

			if (hotPosts) {
				// Extract topic themes from hot posts (simple: grab question topics)
				for (const p of hotPosts) {
					const content = (p.content || "") as string;
					if (
						content.includes("?") &&
						content.length > 20 &&
						content.length < 120
					) {
						topics.push(content);
						if (topics.length >= 8) break;
					}
				}
			}
		}
	} catch (err) {
		logger.debug("Trending topics fetch failed, non-blocking", {
			error: String(err),
		});
	}
	return topics.slice(0, 8);
}

// ============================================================================
// Own Performance Data
// ============================================================================

/**
 * Fetch our OWN top-performing posts from the last 7 days.
 * This is real engagement data we own — views, replies, likes.
 * Used to tell the AI "here's what actually works for us."
 */
export async function getOwnTopPerformingPosts(
	_ownerId: string,
	groupAccountIds: string[],
	limit = 10,
): Promise<
	{
		content: string;
		username: string;
		views: number;
		replies: number;
		likes: number;
		publishedAt: string;
	}[]
> {
	try {
		// Only use posts after content overhaul (March 20 2026).
		// Old sandcastle/meeting posts would teach the AI the wrong patterns.
		const contentOverhaulDate = "2026-03-20T00:00:00Z";
		const threeDaysAgo = new Date(
			Date.now() - 3 * 24 * 60 * 60 * 1000,
		).toISOString();
		const cutoff =
			contentOverhaulDate > threeDaysAgo ? contentOverhaulDate : threeDaysAgo;

		const { data: posts, error } = await db()
			.from("posts")
			.select(
				"content, views_count, replies_count, likes_count, published_at, accounts(username)",
			)
			.eq("platform", "threads")
			.eq("status", "published")
			.in("account_id", groupAccountIds)
			.not("views_count", "is", null)
			.gte("views_count", 1)
			.gte("published_at", cutoff)
			.order("views_count", { ascending: false })
			.limit(limit);

		if (error) {
			logger.warn("[dataGathering] recent posts fetch failed", {
				error: serializeError(error),
			});
			return [];
		}
		if (!posts || posts.length === 0) return [];

		return posts.map((p) => ({
			content: p.content || "",
			username:
				(((p as Record<string, unknown>).accounts as Record<string, unknown>)
					?.username as string) || "unknown",
			views: p.views_count || 0,
			replies: p.replies_count || 0,
			likes: p.likes_count || 0,
			publishedAt: p.published_at || "",
		}));
	} catch (err) {
		logger.warn("[dataGathering] recent posts threw", {
			error: serializeError(err),
		});
		return [];
	}
}

/**
 * Compute engagement patterns from our own post data.
 * Returns insights like character length sweet spot, question vs statement
 * performance, emoji usage patterns, and time-of-day analysis.
 */
export async function getOwnEngagementPatterns(
	groupAccountIds: string[],
): Promise<{
	avgLengthWinners: number;
	avgLengthAll: number;
	questionAvgViews: number;
	statementAvgViews: number;
	shortPostAvgViews: number;
	longPostAvgViews: number;
	bestHours: number[];
	emojiPostAvgViews: number;
	noEmojiPostAvgViews: number;
	totalPosts: number;
} | null> {
	try {
		const sevenDaysAgo = new Date(
			Date.now() - 7 * 24 * 60 * 60 * 1000,
		).toISOString();

		const { data: posts, error } = await db()
			.from("posts")
			.select("content, views_count, replies_count, published_at")
			.eq("platform", "threads")
			.eq("status", "published")
			.in("account_id", groupAccountIds)
			.not("views_count", "is", null)
			.gte("views_count", 0)
			.not("content", "is", null)
			.gte("published_at", sevenDaysAgo);

		if (error) {
			logger.warn("[dataGathering] engagement-patterns fetch failed", {
				error: serializeError(error),
			});
			return null;
		}
		if (!posts || posts.length < 10) return null;

		// Separate questions vs statements
		const questions = posts.filter((p) => (p.content || "").includes("?"));
		const statements = posts.filter((p) => !(p.content || "").includes("?"));

		const avgViews = (arr: typeof posts) =>
			arr.length > 0
				? arr.reduce((sum, p) => sum + (p.views_count || 0), 0) / arr.length
				: 0;

		// Short vs long
		const short = posts.filter((p) => (p.content || "").length < 60);
		const long = posts.filter((p) => (p.content || "").length >= 60);

		// Top 20% by views
		const sorted = [...posts].sort(
			(a, b) => (b.views_count || 0) - (a.views_count || 0),
		);
		const top20 = sorted.slice(0, Math.max(1, Math.floor(sorted.length * 0.2)));
		const avgLenWinners =
			top20.reduce((sum, p) => sum + (p.content || "").length, 0) /
			top20.length;

		// Emoji posts
		const emojiRegex =
			/[\u{1F600}-\u{1F64F}\u{1F300}-\u{1F5FF}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u;
		const withEmoji = posts.filter((p) => emojiRegex.test(p.content || ""));
		const noEmoji = posts.filter((p) => !emojiRegex.test(p.content || ""));

		// Best hours
		const hourBuckets: Record<number, { views: number; count: number }> = {};
		for (const p of posts) {
			if (!p.published_at) continue;
			const hour = new Date(p.published_at).getUTCHours();
			if (!hourBuckets[hour]) hourBuckets[hour] = { views: 0, count: 0 };
			hourBuckets[hour].views += p.views_count || 0;
			hourBuckets[hour].count++;
		}
		const bestHours = Object.entries(hourBuckets)
			.filter(([, d]) => d.count >= 3)
			.map(([h, d]) => ({ hour: Number(h), avg: d.views / d.count }))
			.sort((a, b) => b.avg - a.avg)
			.slice(0, 3)
			.map((h) => h.hour);

		return {
			avgLengthWinners: Math.round(avgLenWinners),
			avgLengthAll: Math.round(
				posts.reduce((s, p) => s + (p.content || "").length, 0) / posts.length,
			),
			questionAvgViews: Math.round(avgViews(questions)),
			statementAvgViews: Math.round(avgViews(statements)),
			shortPostAvgViews: Math.round(avgViews(short)),
			longPostAvgViews: Math.round(avgViews(long)),
			bestHours,
			emojiPostAvgViews: Math.round(avgViews(withEmoji)),
			noEmojiPostAvgViews: Math.round(avgViews(noEmoji)),
			totalPosts: posts.length,
		};
	} catch (err) {
		logger.warn("[dataGathering] engagement-patterns threw", {
			error: serializeError(err),
		});
		return null;
	}
}

// ============================================================================
// Recent Post Context (for dedup + anti-pattern detection)
// ============================================================================

/**
 * Check recent posts for anti-pattern detection:
 * - Similar content in last 24h
 * - Recent post lengths for variety
 */
export async function getRecentPostContext(workspaceId: string): Promise<{
	recentContents: string[];
	recentLengths: number[];
	recentPostTimes: Date[];
	recentTopicTags: string[];
}> {
	try {
		const oneDayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
		// Check published + all claimable ready statuses to prevent cross-group
		// looping. Production ready rows use `queued`; omitting it made the AI
		// blind to the actual future queue, so duplicate variants were generated
		// and then rejected later by the trigram RPC.
		const { data } = await db()
			.from("auto_post_queue")
			.select("content, posted_at, topic_tag")
			.eq("workspace_id", workspaceId)
			.in("status", ["published", "pending", "queued"])
			.gte("created_at", oneDayAgo)
			.order("created_at", { ascending: false })
			.limit(200);

		if (!data)
			return {
				recentContents: [],
				recentLengths: [],
				recentPostTimes: [],
				recentTopicTags: [],
			};
		return {
			recentContents: data.map(
				(p: { content?: string | undefined }) => p.content || "",
			),
			recentLengths: data.map(
				(p: { content?: string | undefined }) => (p.content || "").length,
			),
			recentPostTimes: data
				.filter((p: { posted_at?: string | undefined }) => p.posted_at)
				.map((p: { posted_at: string }) => new Date(p.posted_at)),
			recentTopicTags: data
				.map((p: { topic_tag?: string | undefined }) => p.topic_tag || "")
				.filter((t: string) => t.length > 0),
		};
	} catch (err) {
		logger.debug("Failed to fetch recent post context for workspace", {
			workspaceId,
			error: String(err),
		});
		return {
			recentContents: [],
			recentLengths: [],
			recentPostTimes: [],
			recentTopicTags: [],
		};
	}
}
