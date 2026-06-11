// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Trends Service
 * Manages trend analysis with Supabase backend
 * Features: Keyword tracking, search, snapshots, real-time subscriptions
 */

import { subscribe } from "@/services/realtimeManager.js";
import type { TrendingTopic } from "../types/analytics.js";
import type { VoiceProfile } from "../types/voice.js";
import {
	createServiceLogger,
	dbQuery,
	getSession,
	getUserIdAsync,
	supabase,
} from "./api/shared.js";

const log = createServiceLogger("trendsService");

// Helper to get current user ID
const getSupabaseUserId = async (): Promise<string | null> => {
	try {
		return await getUserIdAsync();
	} catch {
		return null;
	}
};

// Get auth token for API calls
const getAuthToken = async (): Promise<string | null> => {
	const session = await getSession();
	return session?.access_token || null;
};

// Types
export interface TrendKeyword {
	id: string;
	keyword: string;
	category?: string | undefined;
	isActive: boolean;
	lastSyncedAt?: Date | undefined;
	postCount: number;
	totalEngagement: number;
	createdAt: Date;
}

export interface TrendPost {
	id: string;
	threadsPostId: string;
	content: string;
	username: string;
	mediaUrl?: string | undefined;
	mediaType?: string | undefined;
	likeCount: number;
	replyCount: number;
	repostCount: number;
	viewCount: number;
	engagementScore: number;
	permalink?: string | undefined;
	timestamp: Date;
	keyword: string;
}

export interface TopHashtag {
	tag: string;
	count: number;
	engagement: number;
}

export interface KeywordTrend {
	keyword: string;
	dates: string[];
	engagements: number[];
	posts: number[];
	totalEngagement: number;
	totalPosts: number;
}

export interface TrendData {
	trends: KeywordTrend[];
	topHashtags: TopHashtag[];
	hotPosts: TrendPost[];
	dateRange: { start: string; end: string };
}

export interface TrendSnapshot {
	date: string;
	keyword: string;
	totalPosts: number;
	totalEngagement: number;
	avgEngagement: number;
	topHashtags: TopHashtag[];
	topPosts: TrendPost[];
}

// Unsubscribe function type
type Unsubscribe = () => void;

// Map database row to TrendKeyword
const mapRowToKeyword = (row: Record<string, unknown>): TrendKeyword => ({
	id: row.id as string,
	keyword: row.keyword as string,
	category: row.category as string | undefined,
	isActive: row.is_active as boolean,
	lastSyncedAt: row.last_synced_at
		? new Date(row.last_synced_at as string)
		: undefined,
	postCount: (row.post_count as number) || 0,
	totalEngagement: (row.total_engagement as number) || 0,
	createdAt: new Date(row.created_at as string),
});

// Map database row to TrendPost
const mapRowToPost = (row: Record<string, unknown>): TrendPost => ({
	id: row.id as string,
	threadsPostId: row.threads_post_id as string,
	content: (row.content as string) || "",
	username: row.username as string,
	mediaUrl: row.media_url as string | undefined,
	mediaType: row.media_type as string | undefined,
	likeCount: (row.like_count as number) || 0,
	replyCount: (row.reply_count as number) || 0,
	repostCount: (row.repost_count as number) || 0,
	viewCount: (row.view_count as number) || 0,
	engagementScore: (row.engagement_score as number) || 0,
	permalink: row.permalink as string | undefined,
	timestamp: new Date(row.posted_at as string),
	keyword: row.keyword as string,
});

// Extract hashtags from content
const extractHashtags = (content: string): string[] => {
	const matches = content.match(/#[a-zA-Z0-9_]+/g);
	return matches ? matches.map((tag) => tag.toLowerCase()) : [];
};

// Calculate engagement score
const calculateEngagementScore = (post: {
	likeCount: number;
	replyCount: number;
	repostCount: number;
	viewCount: number;
}): number => {
	return (
		post.likeCount +
		post.replyCount * 3 +
		post.repostCount * 2 +
		Math.floor(post.viewCount / 100)
	);
};

class TrendsService {
	private unsubscribeRealtime: (() => void) | null = null;

	// ==========================================
	// KEYWORD MANAGEMENT
	// ==========================================

	/**
	 * Add a new trend keyword to track
	 */
	async addKeyword(keyword: string, category?: string): Promise<TrendKeyword> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		const normalizedKeyword = keyword.trim().toLowerCase();

		const { data, error } = await supabase
			.from("trend_keywords")
			.insert({
				user_id: userId,
				keyword: normalizedKeyword,
				category: category?.trim() || null,
				is_active: true,
			})
			.select()
			.maybeSingle();

		if (error) {
			if (error.code === "23505") {
				throw new Error("You are already tracking this keyword");
			}
			log.error("Failed to add keyword:", error);
			throw new Error("Failed to add keyword");
		}
		if (!data) throw new Error("Failed to add keyword: no data returned");

		return mapRowToKeyword(data);
	}

	/**
	 * Remove a trend keyword
	 */
	async removeKeyword(keywordId: string): Promise<void> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		const { error } = await supabase
			.from("trend_keywords")
			.delete()
			.eq("id", keywordId)
			.eq("user_id", userId);

		if (error) {
			log.error("Failed to remove keyword:", error);
			throw new Error("Failed to remove keyword");
		}
	}

	/**
	 * Toggle keyword active status
	 */
	async toggleKeyword(keywordId: string, isActive: boolean): Promise<void> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		const { error } = await supabase
			.from("trend_keywords")
			.update({ is_active: isActive })
			.eq("id", keywordId)
			.eq("user_id", userId);

		if (error) {
			log.error("Failed to toggle keyword:", error);
			throw new Error("Failed to toggle keyword");
		}
	}

	/**
	 * Get all trend keywords for current user
	 */
	async getKeywords(): Promise<TrendKeyword[]> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		const data = await dbQuery(
			supabase
				.from("trend_keywords")
				.select("*")
				.eq("user_id", userId)
				.order("created_at", { ascending: false }),
			"[trendsService] Failed to get keywords",
		);

		return (data || []).map(mapRowToKeyword);
	}

	/**
	 * Subscribe to keywords (real-time updates)
	 */
	subscribeToKeywords(
		onUpdate: (keywords: TrendKeyword[]) => void,
		onError: (error: Error) => void,
	): Unsubscribe {
		let isCleanedUp = false;

		// Get initial data
		this.getKeywords()
			.then((kw) => {
				if (!isCleanedUp) onUpdate(kw);
			})
			.catch((err) => {
				if (!isCleanedUp) onError(err);
			});

		// Clean up any previous subscription
		this.unsubscribeRealtime?.();

		this.unsubscribeRealtime = subscribe(
			"trend-keywords",
			async (signal) => {
				const userId = await getSupabaseUserId();
				if (signal.aborted || !userId) {
					if (!userId && !signal.aborted)
						onError(new Error("Not authenticated"));
					return null;
				}

				return supabase
					.channel("trend_keywords_changes")
					.on(
						"postgres_changes",
						{
							event: "*",
							schema: "public",
							table: "trend_keywords",
							filter: `user_id=eq.${userId}`,
						},
						() => {
							if (!isCleanedUp) {
								this.getKeywords()
									.then((kw) => {
										if (!isCleanedUp) onUpdate(kw);
									})
									.catch((err) => {
										if (!isCleanedUp) onError(err);
									});
							}
						},
					)
					.subscribe();
			},
			() => {
				this.getKeywords()
					.then((kw) => {
						if (!isCleanedUp) onUpdate(kw);
					})
					.catch((err) => {
						if (!isCleanedUp) onError(err);
					});
			},
		);

		return () => {
			isCleanedUp = true;
			this.unsubscribeRealtime?.();
			this.unsubscribeRealtime = null;
		};
	}

	// ==========================================
	// TREND DATA / SEARCH
	// ==========================================

	/**
	 * Search for a specific keyword using the API
	 */
	async searchKeyword(
		keyword: string,
		limit = 50,
		authorUsername?: string,
	): Promise<{
		posts: TrendPost[];
		hashtags: TopHashtag[];
		totalEngagement: number;
	}> {
		const token = await getAuthToken();
		if (!token) throw new Error("Not authenticated");

		const response = await fetch("/api/trends?action=search", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${token}`,
			},
			body: JSON.stringify({
				query: keyword,
				searchType: "RECENT",
				searchMode: "KEYWORD",
				limit,
				...(authorUsername ? { authorUsername } : {}),
			}),
		});

		if (!response.ok) {
			const error = await response.json();
			throw new Error(error.error || "Search failed");
		}

		const data = await response.json();
		const posts: TrendPost[] = (data.posts || []).map(
			(post: Record<string, unknown>) => ({
				id: post.id as string,
				threadsPostId: post.id as string,
				content: (post.content as string) || "",
				username: post.username as string,
				mediaUrl: post.mediaUrl as string | undefined,
				mediaType: post.mediaType as string | undefined,
				likeCount: (post.likeCount as number) || 0,
				replyCount: (post.replyCount as number) || 0,
				repostCount: (post.repostCount as number) || 0,
				viewCount: (post.viewCount as number) || 0,
				engagementScore: calculateEngagementScore({
					likeCount: (post.likeCount as number) || 0,
					replyCount: (post.replyCount as number) || 0,
					repostCount: (post.repostCount as number) || 0,
					viewCount: (post.viewCount as number) || 0,
				}),
				permalink: post.permalink as string | undefined,
				timestamp: new Date(post.timestamp as string),
				keyword,
			}),
		);

		// Extract and count hashtags
		const hashtagCounts = new Map<
			string,
			{ count: number; engagement: number }
		>();
		for (const post of posts) {
			const tags = extractHashtags(post.content);
			for (const tag of tags) {
				const existing = hashtagCounts.get(tag) || { count: 0, engagement: 0 };
				hashtagCounts.set(tag, {
					count: existing.count + 1,
					engagement: existing.engagement + post.engagementScore,
				});
			}
		}

		const hashtags: TopHashtag[] = Array.from(hashtagCounts.entries())
			.map(([tag, data]) => ({
				tag,
				count: data.count,
				engagement: data.engagement,
			}))
			.sort((a, b) => b.engagement - a.engagement)
			.slice(0, 20);

		const totalEngagement = posts.reduce(
			(sum, p) => sum + p.engagementScore,
			0,
		);

		return { posts, hashtags, totalEngagement };
	}

	/**
	 * Get aggregated trend data from all tracked keywords
	 */
	async getTrendData(days = 7): Promise<TrendData> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		const startDate = new Date();
		startDate.setDate(startDate.getDate() - days);
		const endDate = new Date();

		// Get active keywords
		const keywords = await this.getKeywords();
		const activeKeywords = keywords.filter((k) => k.isActive);

		if (activeKeywords.length === 0) {
			return {
				trends: [],
				topHashtags: [],
				hotPosts: [],
				dateRange: {
					start: startDate.toISOString().split("T")[0]!,
					end: endDate.toISOString().split("T")[0]!,
				},
			};
		}

		// Get snapshots for the date range
		const keywordIds = activeKeywords.map((k) => k.id);
		const { data: snapshots } = await supabase
			.from("trend_snapshots")
			.select("*")
			.in("keyword_id", keywordIds)
			.gte("snapshot_date", startDate.toISOString().split("T")[0]!)
			.lte("snapshot_date", endDate.toISOString().split("T")[0]!)
			.order("snapshot_date", { ascending: true });

		// Build trends from snapshots
		const keywordMap = new Map(activeKeywords.map((k) => [k.id, k.keyword]));
		const trendMap = new Map<
			string,
			{ dates: string[]; engagements: number[]; posts: number[] }
		>();

		for (const snapshot of snapshots || []) {
			const keyword = keywordMap.get(snapshot.keyword_id);
			if (!keyword) continue;

			if (!trendMap.has(keyword)) {
				trendMap.set(keyword, { dates: [], engagements: [], posts: [] });
			}

			const trend = trendMap.get(keyword)!;
			trend.dates.push(snapshot.snapshot_date);
			trend.engagements.push(snapshot.total_engagement || 0);
			trend.posts.push(snapshot.total_posts || 0);
		}

		const trends: KeywordTrend[] = Array.from(trendMap.entries()).map(
			([keyword, data]) => ({
				keyword,
				dates: data.dates,
				engagements: data.engagements,
				posts: data.posts,
				totalEngagement: data.engagements.reduce((a, b) => a + b, 0),
				totalPosts: data.posts.reduce((a, b) => a + b, 0),
			}),
		);

		// Get top hashtags from most recent snapshots
		const allHashtags = new Map<
			string,
			{ count: number; engagement: number }
		>();
		for (const snapshot of snapshots || []) {
			const topHashtags = (snapshot.top_hashtags as TopHashtag[] | null) || [];
			for (const ht of topHashtags) {
				const existing = allHashtags.get(ht.tag) || { count: 0, engagement: 0 };
				allHashtags.set(ht.tag, {
					count: existing.count + ht.count,
					engagement: existing.engagement + ht.engagement,
				});
			}
		}

		const topHashtags: TopHashtag[] = Array.from(allHashtags.entries())
			.map(([tag, data]) => ({ tag, ...data }))
			.sort((a, b) => b.engagement - a.engagement)
			.slice(0, 10);

		// Get hot posts (most recent, highest engagement)
		const { data: postRows } = await supabase
			.from("trend_posts")
			.select("*")
			.eq("user_id", userId)
			.in("keyword_id", keywordIds)
			.order("engagement_score", { ascending: false })
			.limit(20);

		const hotPosts = (postRows || []).map((row) => ({
			...mapRowToPost(row),
			keyword: keywordMap.get(row.keyword_id) || "",
		}));

		return {
			trends,
			topHashtags,
			hotPosts,
			dateRange: {
				start: startDate.toISOString().split("T")[0]!,
				end: endDate.toISOString().split("T")[0]!,
			},
		};
	}

	/**
	 * Sync a single keyword's trend data
	 */
	async syncKeyword(keywordId: string): Promise<TrendSnapshot> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		// Get the keyword
		const { data: keywordRow, error: keywordError } = await supabase
			.from("trend_keywords")
			.select("*")
			.eq("id", keywordId)
			.eq("user_id", userId)
			.maybeSingle();

		if (keywordError || !keywordRow) {
			throw new Error("Keyword not found");
		}

		// Search for posts with this keyword
		const { posts, hashtags, totalEngagement } = await this.searchKeyword(
			keywordRow.keyword,
			100,
		);

		// Delete old posts for this keyword (keep last 7 days)
		const sevenDaysAgo = new Date();
		sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);

		await supabase
			.from("trend_posts")
			.delete()
			.eq("keyword_id", keywordId)
			.lt("fetched_at", sevenDaysAgo.toISOString());

		// Insert/update posts
		for (const post of posts) {
			await supabase.from("trend_posts").upsert(
				{
					keyword_id: keywordId,
					user_id: userId,
					threads_post_id: post.threadsPostId,
					content: post.content,
					username: post.username,
					media_url: post.mediaUrl,
					media_type: post.mediaType,
					permalink: post.permalink,
					like_count: post.likeCount,
					reply_count: post.replyCount,
					repost_count: post.repostCount,
					view_count: post.viewCount,
					engagement_score: post.engagementScore,
					posted_at: post.timestamp.toISOString(),
					fetched_at: new Date().toISOString(),
				},
				{ onConflict: "keyword_id,threads_post_id" },
			);
		}

		// Update keyword stats
		await supabase
			.from("trend_keywords")
			.update({
				last_synced_at: new Date().toISOString(),
				post_count: posts.length,
				total_engagement: totalEngagement,
			})
			.eq("id", keywordId);

		// Create/update today's snapshot
		const today = new Date().toISOString().split("T")[0]!;
		const avgEngagement = posts.length > 0 ? totalEngagement / posts.length : 0;

		const topPosts = posts
			.sort((a, b) => b.engagementScore - a.engagementScore)
			.slice(0, 5);

		await supabase.from("trend_snapshots").upsert(
			{
				keyword_id: keywordId,
				user_id: userId,
				snapshot_date: today,
				total_posts: posts.length,
				total_engagement: totalEngagement,
				avg_engagement: avgEngagement,
				// biome-ignore lint/suspicious/noExplicitAny: Supabase JSONB array column requires cast
				top_hashtags: hashtags.slice(0, 10) as unknown as any,
				// biome-ignore lint/suspicious/noExplicitAny: Supabase JSONB array column requires cast
				top_post_ids: topPosts.map((p) => p.id) as unknown as any,
			},
			{ onConflict: "keyword_id,snapshot_date" },
		);

		return {
			date: today!,
			keyword: keywordRow.keyword,
			totalPosts: posts.length,
			totalEngagement,
			avgEngagement,
			topHashtags: hashtags.slice(0, 10),
			topPosts,
		};
	}

	/**
	 * Sync all active keywords
	 */
	async syncAllKeywords(): Promise<void> {
		const keywords = await this.getKeywords();
		const activeKeywords = keywords.filter((k) => k.isActive);

		for (const keyword of activeKeywords) {
			try {
				await this.syncKeyword(keyword.id);
				// Add small delay between syncs to avoid rate limiting
				await new Promise((resolve) => setTimeout(resolve, 500));
			} catch (error) {
				log.error(`Failed to sync keyword ${keyword.keyword}:`, error);
			}
		}
	}

	// ==========================================
	// TRENDING TOPICS WIDGET
	// ==========================================

	/**
	 * Get trending topics for the dashboard widget
	 * Aggregates data from tracked keywords and their posts
	 */
	async getTrendingTopics(limit = 10): Promise<TrendingTopic[]> {
		const userId = await getSupabaseUserId();
		if (!userId) return [];

		try {
			// Get active keywords with their stats
			const { data: keywords, error } = await supabase
				.from("trend_keywords")
				.select("*")
				.eq("user_id", userId)
				.eq("is_active", true)
				.order("total_engagement", { ascending: false })
				.limit(limit);

			if (error) {
				log.error("Failed to get trending topics:", error);
				return [];
			}

			if (!keywords || keywords.length === 0) {
				return [];
			}

			// Get previous day's snapshots for trend calculation
			const yesterday = new Date();
			yesterday.setDate(yesterday.getDate() - 1);
			const yesterdayStr = yesterday.toISOString().split("T")[0]!;

			const keywordIds = keywords.map((k) => k.id);
			const { data: snapshots } = await supabase
				.from("trend_snapshots")
				.select("keyword_id, total_engagement")
				.in("keyword_id", keywordIds)
				.eq("snapshot_date", yesterdayStr);

			const previousEngagement = new Map<string, number>();
			for (const snapshot of snapshots || []) {
				previousEngagement.set(
					snapshot.keyword_id,
					snapshot.total_engagement || 0,
				);
			}

			// Map to TrendingTopic format
			const topics: TrendingTopic[] = keywords.map((k) => {
				const prevEngagement = previousEngagement.get(k.id) || 0;
				const currentEngagement = k.total_engagement || 0;
				const percentChange =
					prevEngagement > 0
						? ((currentEngagement - prevEngagement) / prevEngagement) * 100
						: currentEngagement > 0
							? 100
							: 0;

				let trend: "up" | "down" | "stable" = "stable";
				if (percentChange > 5) trend = "up";
				else if (percentChange < -5) trend = "down";

				return {
					id: k.id,
					name: k.keyword.startsWith("#") ? k.keyword : `#${k.keyword}`,
					engagementScore: currentEngagement,
					postCount: k.post_count || 0,
					trend,
					percentChange: Math.round(percentChange),
					category: k.category || undefined,
				};
			});

			return topics;
		} catch (error) {
			log.error("Error getting trending topics:", error);
			return [];
		}
	}

	/**
	 * Generate an AI post idea based on a trending topic
	 * Uses the user's voice profile for personalization
	 */
	async generateTopicIdea(
		topicName: string,
		voiceProfile?: VoiceProfile,
	): Promise<string> {
		try {
			// Lazy import to avoid circular dependencies
			const { generateContent } = await import("./aiService.js");

			// Build the prompt with voice profile context
			const voiceContext = voiceProfile
				? `
Voice Profile:
- Tone: ${voiceProfile.tone || "casual"}
- Voice: ${voiceProfile.voice_profile || "conversational"}
- Emoji Usage: ${voiceProfile.emoji_usage || "moderate"}
- Focus Topics: ${voiceProfile.focus_topics?.join(", ") || "engaging, relatable"}
`
				: "";

			const prompt = `Create a viral Threads post about the trending topic "${topicName}".

${voiceContext}

Requirements:
- Make it engaging and shareable
- Include relevant hashtags naturally
- Keep it under 280 characters
- Match the voice profile style
- Add a hook that grabs attention
- End with engagement trigger (question or call-to-action)

Return ONLY the post content, no explanations.`;

			const idea = await generateContent(prompt);
			return idea.trim();
		} catch (error) {
			log.error("Failed to generate topic idea:", error);
			throw new Error("Failed to generate post idea");
		}
	}
}

export const trendsService = new TrendsService();
