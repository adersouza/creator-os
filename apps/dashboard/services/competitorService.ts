// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Competitor Analysis Service
 *
 * Handles all competitor-related operations using Vercel API
 * and Supabase for data persistence.
 */

import { subscribe } from "@/services/realtimeManager.js";
import type { Platform } from "../src/types/platform.js";
import logger from "@/utils/logger";
import { trackCompetitor } from "./analyticsService.js";
import { createConcurrencyLimiter } from "./api/shared.js";
import { supabase } from "./supabase.js";

/**
 * Safely parse JSON response, handling non-JSON responses gracefully
 */
// biome-ignore lint/suspicious/noExplicitAny: generic helper requires any as default type
const safeJsonParse = async <T = any>(
	response: Response,
	context: string,
): Promise<T> => {
	const contentType = response.headers.get("content-type");
	const isJson = contentType?.includes("application/json");

	if (response.status === 404) {
		throw new Error(`${context} API not available (requires deployment)`);
	}

	if (!isJson) {
		const isDev = import.meta.env.DEV;
		if (isDev) {
			throw new Error(`${context} API not available (requires deployment)`);
		}
		throw new Error(
			`Invalid response from ${context} API (${response.status})`,
		);
	}

	return response.json();
};

// Helper to get current user ID for Supabase
const getSupabaseUserId = async (): Promise<string | null> => {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	return session?.user?.id || null;
};

// Types
export interface Competitor {
	id: string;
	threadsUserId: string;
	threadsNumericId?: string | undefined; // Numeric ID for fetching posts (if available)
	username: string;
	displayName: string;
	avatarUrl: string;
	bio?: string | undefined;
	followerCount: number;
	isVerified: boolean;
	// 7-day engagement metrics from profile_lookup API
	likesCount7d?: number | undefined;
	quotesCount7d?: number | undefined;
	repliesCount7d?: number | undefined;
	repostsCount7d?: number | undefined;
	viewsCount7d?: number | undefined;
	addedAt: Date;
	lastSyncedAt: Date;
	// Instagram-specific fields
	platform?: Platform | undefined;
	instagramUserId?: string | undefined;
	mediaCount?: number | undefined;
	avgLikes?: number | undefined;
	avgComments?: number | undefined;
	engagementRate?: number | undefined;
	website?: string | undefined;
}

export interface CompetitorPost {
	id: string;
	threadsPostId: string;
	content: string;
	mediaType?: "IMAGE" | "VIDEO" | undefined;
	mediaUrl?: string | undefined;
	likeCount: number;
	replyCount: number;
	repostCount: number;
	publishedAt: Date;
	permalink?: string | undefined;
}

// Scored post for top posts feature
export interface ScoredPost {
	id: string;
	threadsPostId: string;
	content: string;
	mediaType?: string | undefined;
	mediaUrl?: string | undefined;
	likeCount: number;
	replyCount: number;
	repostCount: number;
	viewCount: number;
	engagementScore: number;
	publishedAt: Date;
	competitorId: string;
	competitorUsername: string;
	competitorAvatarUrl: string;
	platform?: Platform | undefined;
	permalink?: string | undefined;
}

export interface CompetitorSnapshot {
	date: string;
	followerCount: number;
}

export interface BenchmarkComparison {
	competitorCount: number;
	averages: {
		followers: number;
		engagementRate: number;
		avgLikes: number;
		avgComments: number;
		mediaCount: number;
	};
	userAccount: {
		followers: number;
		engagementRate: number;
		avgLikes: number;
		avgComments: number;
		mediaCount: number;
	} | null;
	competitors: Array<{
		id: string;
		username: string;
		followers: number;
		engagementRate: number;
		avgLikes: number;
		avgComments: number;
		mediaCount: number;
	}>;
}

export interface ContentTypeBreakdown {
	mediaType: string;
	count: number;
	avgLikes: number;
	avgComments: number;
	avgEngagementScore: number;
}

export interface ComparisonSeries {
	competitorId: string;
	username: string;
	data: Array<{
		date: string;
		followers: number;
		engagementRate: number | null;
	}>;
}

export interface CompetitorAlert {
	id: string;
	competitorId: string;
	alertType: "follower_milestone" | "growth_spike" | "engagement_spike";
	message: string;
	// biome-ignore lint/suspicious/noExplicitAny: metadata is an open-ended JSON blob
	metadata: Record<string, any>;
	read: boolean;
	createdAt: Date;
}

export interface SearchResult {
	threadsUserId: string;
	username: string;
	displayName: string;
	avatarUrl: string;
	bio?: string | undefined;
	followerCount: number;
	isVerified: boolean;
}

export interface SavedPost {
	id: string;
	postUrl: string;
	username: string;
	content?: string | undefined;
	notes?: string | undefined;
	tags?: string[] | undefined;
	savedAt: Date;
	// oEmbed preview data
	thumbnailUrl?: string | undefined;
	authorName?: string | undefined;
	authorAvatarUrl?: string | undefined;
	postText?: string | undefined;
	timestamp?: string | undefined;
	// Favorite status
	isFavorite?: boolean | undefined;
	// Engagement metrics (from auto-populated posts or manual entry)
	engagementScore?: number | undefined;
	likeCount?: number | undefined;
	replyCount?: number | undefined;
	repostCount?: number | undefined;
	viewCount?: number | undefined;
	// Source tracking
	autoPopulated?: boolean | undefined;
	sourceType?:
		| "manual"
        		| "competitor_top_post"
        		| "trend_hot_post"
        		| "keyword_search" | undefined;
	// Media type for filtering
	mediaType?: "IMAGE" | "VIDEO" | "TEXT" | "CAROUSEL" | undefined;
	mediaUrl?: string | undefined;
	threadsPostId?: string | undefined;
}

class CompetitorService {
	/**
	 * Search for a public Threads profile by username
	 */
	async searchProfile(username: string): Promise<SearchResult> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/competitors?action=search", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify({ query: username }),
		});

		const data = await safeJsonParse<{
			success: boolean;
			profile: SearchResult;
			error?: string | undefined;
		}>(response, "Competitor search");
		if (!data.success) {
			throw new Error(data.error || "Profile not found");
		}
		return data.profile;
	}

	/**
	 * Add a competitor to track
	 */
	async addCompetitor(username: string): Promise<Competitor> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/competitors?action=add", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify({ username }),
		});

		const data = await safeJsonParse<{
			success: boolean;
			// biome-ignore lint/suspicious/noExplicitAny: competitor shape varies by platform
			competitor: any;
			error?: string | undefined;
		}>(response, "Add competitor");
		if (!data.success) {
			throw new Error(data.error || "Failed to add competitor");
		}
		return this.parseCompetitor(data.competitor);
	}

	/**
	 * Remove a competitor
	 */
	async removeCompetitor(competitorId: string): Promise<void> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		// Look up username before deletion for analytics
		const { data: competitor } = await supabase
			.from("competitors")
			.select("username")
			.eq("id", competitorId)
			.eq("user_id", userId)
			.single();

		const { error } = await supabase
			.from("competitors")
			.delete()
			.eq("id", competitorId)
			.eq("user_id", userId);

		if (error) throw error;

		trackCompetitor("removed", competitor?.username || competitorId);
	}

	/**
	 * Sync competitor data (refresh profile and posts)
	 */
	async syncCompetitor(competitorId: string): Promise<void> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/competitors?action=sync", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify({ competitorId }),
		});

		const data = await safeJsonParse<{ success: boolean; error?: string | undefined }>(
			response,
			"Sync competitor",
		);
		if (!data.success) {
			throw new Error(data.error || "Failed to sync competitor");
		}
	}

	/**
	 * Queue sync for all competitors (background processing)
	 * Returns job info for tracking progress via Realtime
	 */
	async syncAllCompetitors(): Promise<{
		queued: boolean;
		existingJob?: boolean | undefined;
		job?: { id: string; status: string; competitorCount?: number | undefined } | undefined;
		message?: string | undefined;
	}> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/competitors?action=queue-sync-all", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
		});

		const data = await safeJsonParse<{
			success: boolean;
			queued: boolean;
			existingJob?: boolean | undefined;
			job?: { id: string; status: string; competitorCount?: number | undefined } | undefined;
			message?: string | undefined;
			error?: string | undefined;
		}>(response, "Sync all competitors");

		if (!data.success) {
			throw new Error(data.error || "Failed to queue competitor sync");
		}

		return {
			queued: data.queued,
			existingJob: data.existingJob,
			job: data.job,
			message: data.message,
		};
	}

	/**
	 * Get all competitors for the current user
	 */
	async getCompetitors(): Promise<Competitor[]> {
		const userId = await getSupabaseUserId();
		logger.log(`[getCompetitors] Supabase auth state:`, {
			hasUser: !!userId,
			uid: userId,
		});

		if (!userId) throw new Error("Not authenticated");

		try {
			const { data, error } = await supabase
				.from("competitors")
				.select("*")
				.eq("user_id", userId)
				.order("added_at", { ascending: false })
				.limit(200);

			if (error) throw error;

			if (!data || data.length === 0) {
				logger.warn(`[getCompetitors] No competitors found for user ${userId}`);
				return [];
			}

			return data.map((row) =>
				this.parseCompetitor({
					id: row.id,
					threadsUserId: row.threads_user_id,
					threadsNumericId: row.threads_numeric_id,
					username: row.username,
					displayName: row.display_name,
					avatarUrl: row.avatar_url,
					bio: row.bio,
					followerCount: row.follower_count,
					isVerified: row.is_verified,
					likesCount7d: row.likes_count_7d,
					quotesCount7d: row.quotes_count_7d,
					repliesCount7d: row.replies_count_7d,
					repostsCount7d: row.reposts_count_7d,
					viewsCount7d: row.views_count_7d,
					addedAt: row.added_at,
					lastSyncedAt: row.last_synced_at,
				}),
			);
		} catch (err: unknown) {
			logger.error(
				"[getCompetitors] Query failed:",
				err instanceof Error ? err.message : err,
			);
			throw err;
		}
	}

	/**
	 * Subscribe to competitors list (real-time updates)
	 */
	subscribeToCompetitors(
		onUpdate: (competitors: Competitor[]) => void,
		onError: (error: Error) => void,
	): () => void {
		let isCleanedUp = false;

		const fetchCompetitors = async () => {
			if (isCleanedUp) return;
			try {
				const competitors = await this.getCompetitors();
				if (!isCleanedUp) onUpdate(competitors);
			} catch (error) {
				if (!isCleanedUp) onError(error as Error);
			}
		};

		// Initial fetch
		fetchCompetitors();

		const unsub = subscribe(
			"competitors",
			async (signal) => {
				const userId = await getSupabaseUserId();
				if (signal.aborted || !userId) {
					if (!userId && !signal.aborted)
						onError(new Error("Not authenticated"));
					return null;
				}

				return supabase
					.channel(`competitors-${userId}`)
					.on(
						"postgres_changes",
						{
							event: "*",
							schema: "public",
							table: "competitors",
							filter: `user_id=eq.${userId}`,
						},
						() => fetchCompetitors(),
					)
					.subscribe();
			},
			fetchCompetitors,
		);

		return () => {
			isCleanedUp = true;
			unsub();
		};
	}

	/**
	 * Get competitor posts (from competitor_top_posts table)
	 */
	async getCompetitorPosts(
		competitorId: string,
		limit = 25,
	): Promise<CompetitorPost[]> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		const { data, error } = await supabase
			.from("competitor_top_posts")
			.select("*")
			.eq("competitor_id", competitorId)
			.eq("user_id", userId)
			.order("engagement_score", { ascending: false })
			.limit(limit);

		if (error) throw error;

		return (data || []).map((row) => ({
			id: row.threads_post_id,
			threadsPostId: row.threads_post_id,
			content: row.content || "",
			mediaType: row.media_type as "IMAGE" | "VIDEO" | undefined,
			likeCount: row.like_count || 0,
			replyCount: row.reply_count || 0,
			repostCount: row.repost_count || 0,
			publishedAt: row.published_at ? new Date(row.published_at) : new Date(),
		}));
	}

	/**
	 * Fetch a fresh media URL for a competitor post from the Threads API.
	 * Used to avoid storing CDN URLs that expire quickly.
	 */
	async getCompetitorPostMedia(threadsPostId: string): Promise<{
		mediaUrl: string | null;
		mediaType: string | null;
		thumbnailUrl: string | null;
	}> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch(
			`/api/competitor-media?threadsPostId=${encodeURIComponent(threadsPostId)}`,
			{
				headers: {
					Authorization: `Bearer ${session.access_token}`,
				},
			},
		);

		const data = await safeJsonParse(response, "Competitor media");
		if (!data.success) {
			return { mediaUrl: null, mediaType: null, thumbnailUrl: null };
		}

		return {
			mediaUrl: data.mediaUrl || null,
			mediaType: data.mediaType || null,
			thumbnailUrl: data.thumbnailUrl || null,
		};
	}

	/**
	 * Get competitor follower history
	 */
	async getCompetitorHistory(
		competitorId: string,
		days = 30,
	): Promise<CompetitorSnapshot[]> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		const startDate = new Date();
		startDate.setDate(startDate.getDate() - days);
		const startDateStr = startDate.toISOString().split("T")[0]!;

		const { data, error } = (await supabase
			.from("competitor_snapshots")
			.select("*")
			.eq("competitor_id", competitorId)
			.eq("user_id", userId)
			.gte("snapshot_date", startDateStr)
			.order("snapshot_date", { ascending: true })) as {
			data: { snapshot_date: string; follower_count: number | null }[] | null;
			// biome-ignore lint/suspicious/noExplicitAny: Supabase error type
			error: any;
		};

		if (error) throw error;

		return (data || []).map((row) => ({
			date: row.snapshot_date,
			followerCount: row.follower_count ?? 0,
		}));
	}

	// ==========================================
	// SAVED POSTS (Competitor Inspiration)
	// ==========================================

	/**
	 * Fetch oEmbed preview data for a Threads post URL
	 * Uses Vercel API to authenticate with Meta Graph API
	 */
	async fetchOEmbedPreview(postUrl: string): Promise<{
		thumbnailUrl?: string | undefined;
		authorName?: string | undefined;
		postText?: string | undefined;
	} | null> {
		try {
			const {
				data: { session },
			} = await supabase.auth.getSession();
			if (!session) return null;

			const response = await fetch("/api/competitors?action=oembed", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.access_token}`,
				},
				body: JSON.stringify({ postUrl }),
			});

			const data = await safeJsonParse(response, "oEmbed");
			if (!data.success || !data.preview) {
				logger.warn("oEmbed fetch failed:", data.error);
				return null;
			}

			return {
				thumbnailUrl: data.preview.thumbnailUrl || undefined,
				authorName: data.preview.authorName || undefined,
				postText: data.preview.postText || undefined,
			};
		} catch (error) {
			logger.warn("Failed to fetch oEmbed preview:", error);
			return null;
		}
	}

	/**
	 * Save a post for inspiration
	 */
	async savePost(postData: {
		postUrl: string;
		username: string;
		content?: string | undefined;
		notes?: string | undefined;
		tags?: string[] | undefined;
		thumbnailUrl?: string | undefined;
		authorName?: string | undefined;
		postText?: string | undefined;
		authorAvatarUrl?: string | undefined;
	}): Promise<SavedPost> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		const { data, error } = await supabase
			.from("saved_competitor_posts")
			.insert({
				user_id: userId,
				// Tracker: media workspace backfill still needs a DB migration before
				// competitor media can be assigned to a non-null workspace here.
				workspace_id: null,
				post_url: postData.postUrl,
				username: postData.username,
				content: postData.content || null,
				notes: postData.notes || null,
				tags: postData.tags || null,
				thumbnail_url: postData.thumbnailUrl || null,
				author_name: postData.authorName || null,
				post_text: postData.postText || null,
				author_avatar_url: postData.authorAvatarUrl || null,
			})
			.select()
			.maybeSingle();

		if (error) throw error;
		if (!data) throw new Error("Failed to save post");

		return this.parseSavedPostFromSupabase(data);
	}

	/**
	 * Get all saved posts
	 */
	async getSavedPosts(): Promise<SavedPost[]> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		const { data, error } = await supabase
			.from("saved_competitor_posts")
			.select("*")
			.eq("user_id", userId)
			.order("saved_at", { ascending: false });

		if (error) throw error;

		return (data || []).map((row) => this.parseSavedPostFromSupabase(row));
	}

	/**
	 * Subscribe to saved posts (real-time updates)
	 */
	subscribeToSavedPosts(
		onUpdate: (posts: SavedPost[]) => void,
		onError: (error: Error) => void,
	): () => void {
		let unsubscribed = false;

		const fetchSavedPosts = async () => {
			if (unsubscribed) return;
			try {
				const posts = await this.getSavedPosts();
				if (!unsubscribed) onUpdate(posts);
			} catch (error) {
				if (!unsubscribed) onError(error as Error);
			}
		};

		// Initial fetch
		fetchSavedPosts();

		const unsub = subscribe(
			"saved-posts",
			async (signal) => {
				const userId = await getSupabaseUserId();
				if (signal.aborted || !userId) {
					if (!userId && !signal.aborted)
						onError(new Error("Not authenticated"));
					return null;
				}

				return supabase
					.channel(`saved-posts-${userId}`)
					.on(
						"postgres_changes",
						{
							event: "*",
							schema: "public",
							table: "saved_competitor_posts",
							filter: `user_id=eq.${userId}`,
						},
						() => fetchSavedPosts(),
					)
					.subscribe();
			},
			fetchSavedPosts,
		);

		return () => {
			unsubscribed = true;
			unsub();
		};
	}

	/**
	 * Delete a saved post
	 */
	async deleteSavedPost(postId: string): Promise<void> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		const { error } = await supabase
			.from("saved_competitor_posts")
			.delete()
			.eq("id", postId)
			.eq("user_id", userId);

		if (error) throw error;
	}

	/**
	 * Update a saved post (notes, tags)
	 */
	async updateSavedPost(
		postId: string,
		updates: { notes?: string | undefined; tags?: string[] | undefined },
	): Promise<void> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		const { error } = await supabase
			.from("saved_competitor_posts")
			.update(updates)
			.eq("id", postId)
			.eq("user_id", userId);

		if (error) throw error;
	}

	/**
	 * Toggle favorite status of a saved post
	 */
	async toggleFavorite(postId: string, isFavorite: boolean): Promise<void> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		const { error } = await supabase
			.from("saved_competitor_posts")
			.update({ is_favorite: isFavorite })
			.eq("id", postId)
			.eq("user_id", userId);

		if (error) throw error;
	}

	/**
	 * Check if a post URL already exists in saved posts
	 */
	async checkDuplicateUrl(postUrl: string): Promise<SavedPost | null> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		// Normalize URL for comparison
		const normalizeUrl = (url: string) => {
			try {
				const parsed = new URL(url);
				return `${parsed.origin}${parsed.pathname}`.replace(/\/$/, "");
			} catch {
				return url.replace(/\/$/, "");
			}
		};

		const normalizedInput = normalizeUrl(postUrl);

		const { data, error } = await supabase
			.from("saved_competitor_posts")
			.select("*")
			.eq("user_id", userId);

		if (error) throw error;

		for (const row of data || []) {
			// biome-ignore lint/suspicious/noExplicitAny: Supabase row column not in generated types
			if (normalizeUrl((row as any).post_url) === normalizedInput) {
				return this.parseSavedPostFromSupabase(row);
			}
		}

		return null;
	}

	/**
	 * Parse Supabase row to SavedPost type
	 */
	// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
	private parseSavedPostFromSupabase(row: any): SavedPost {
		return {
			id: row.id,
			postUrl: row.post_url,
			username: row.username,
			content: row.content,
			notes: row.notes,
			tags: row.tags || [],
			savedAt: new Date(row.saved_at),
			// oEmbed preview data
			thumbnailUrl: row.thumbnail_url,
			authorName: row.author_name,
			authorAvatarUrl: row.author_avatar_url,
			postText: row.post_text,
			timestamp: row.timestamp,
			// Favorite status
			isFavorite: row.is_favorite || false,
			// Engagement metrics
			engagementScore: row.engagement_score,
			likeCount: row.like_count,
			replyCount: row.reply_count,
			repostCount: row.repost_count,
			viewCount: row.view_count,
			// Source tracking
			autoPopulated: row.auto_populated || false,
			sourceType: row.source_type || "manual",
			// Media type
			mediaType: row.media_type,
			mediaUrl: row.media_url,
		};
	}

	// ==========================================
	// TOP POSTS FEATURE
	// ==========================================

	/**
	 * Fetch and store top posts for a specific competitor
	 */
	async fetchTopPosts(
		competitorId: string,
		username: string,
	): Promise<{ topPostsCount: number; totalPostsAnalyzed: number }> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/competitors?action=fetch-top-posts", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify({ competitorId, username }),
		});

		const data = await safeJsonParse(response, "Fetch top posts");
		if (!data.success) {
			throw new Error(data.error || "Failed to fetch top posts");
		}

		return {
			topPostsCount: data.topPostsCount,
			totalPostsAnalyzed: data.totalPostsAnalyzed,
		};
	}

	/**
	 * Get aggregated top posts across all competitors
	 */
	async getAggregatedTopPosts(
		limit = 20,
		minEngagementScore = 0,
	): Promise<ScoredPost[]> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch(
			`/api/competitors?action=aggregated-top-posts&limit=${limit}&minEngagementScore=${minEngagementScore}`,
			{
				headers: {
					Authorization: `Bearer ${session.access_token}`,
				},
			},
		);

		const data = await safeJsonParse(response, "Aggregated top posts");
		logger.debug("[getAggregatedTopPosts] Raw response:", data);

		if (!data.success) {
			throw new Error(data.error || "Failed to get aggregated top posts");
		}

		// biome-ignore lint/suspicious/noExplicitAny: API response post shape not typed
		const parsed = data.posts.map((post: any) =>
			this.parseScoredPostFromSupabase(post),
		);
		logger.debug("[getAggregatedTopPosts] Parsed posts:", parsed);
		return parsed;
	}

	/**
	 * Get top posts for a single competitor
	 */
	async getTopPosts(competitorId: string, limit = 10): Promise<ScoredPost[]> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch(
			`/api/competitors?action=top-posts&competitorId=${competitorId}&limit=${limit}`,
			{
				headers: {
					Authorization: `Bearer ${session.access_token}`,
				},
			},
		);

		const data = await safeJsonParse(response, "Top posts");
		if (!data.success) {
			throw new Error(data.error || "Failed to get top posts");
		}

		// biome-ignore lint/suspicious/noExplicitAny: API response post shape not typed
		return data.posts.map((post: any) =>
			this.parseScoredPostFromSupabase(post),
		);
	}

	/**
	 * Sync top posts for all competitors (triggers backend cron manually)
	 */
	async syncAllTopPosts(): Promise<{
		synced: number;
		failed: number;
		total: number;
	}> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		// Get all competitors and fetch top posts for each
		const competitors = await this.getCompetitors();
		logger.log(
			`[syncAllTopPosts] Found ${competitors.length} competitors to sync`,
		);

		if (competitors.length === 0) {
			throw new Error(
				"No competitors found. Add competitors first to sync their top posts.",
			);
		}

		let synced = 0;
		let failed = 0;
		const errors: string[] = [];

		const limit = createConcurrencyLimiter(5);
		const results = await Promise.allSettled(
			competitors.map((competitor) =>
				limit(async () => {
					logger.log(
						`[syncAllTopPosts] Syncing top posts for ${competitor.username} (${competitor.id})`,
					);
					await this.fetchTopPosts(competitor.id, competitor.username);
					logger.log(
						`[syncAllTopPosts] Successfully synced ${competitor.username}`,
					);
					return competitor;
				}),
			),
		);

		for (let i = 0; i < results.length; i++) {
			const result = results[i];
			if (result!.status === "fulfilled") {
				synced++;
			} else {
				failed++;
				const competitor = competitors[i];
				const errorMsg =
					result!.reason instanceof Error
						? result!.reason.message
						: "Unknown error";
				logger.error(
					`[syncAllTopPosts] Failed to sync top posts for ${competitor!.username}:`,
					errorMsg,
				);
				errors.push(`@${competitor!.username}: ${errorMsg}`);
			}
		}

		logger.log(
			`[syncAllTopPosts] Sync complete. Synced: ${synced}, Failed: ${failed}`,
		);

		if (synced === 0 && failed > 0) {
			throw new Error(`Failed to sync all competitors: ${errors.join("; ")}`);
		}

		return { synced, failed, total: competitors.length };
	}

	/**
	 * Parse Supabase row to ScoredPost type
	 */
	// biome-ignore lint/suspicious/noExplicitAny: Supabase row shape not fully typed
	private parseScoredPostFromSupabase(row: any): ScoredPost {
		return {
			id: row.id,
			threadsPostId: row.threads_post_id,
			content: row.content || "",
			mediaType: row.media_type,
			likeCount: row.like_count || 0,
			replyCount: row.reply_count || 0,
			repostCount: row.repost_count || 0,
			viewCount: row.view_count || 0,
			engagementScore: row.engagement_score || 0,
			publishedAt: new Date(row.posted_at),
			competitorId: row.competitor_id,
			competitorUsername: row.competitor_username,
			competitorAvatarUrl: row.competitor_avatar_url,
			platform: (row.competitor_platform as Platform) || "threads",
			permalink: row.permalink,
		};
	}

	/**
	 * Parse data to Competitor type
	 */
	// biome-ignore lint/suspicious/noExplicitAny: API response shape not typed
	private parseCompetitor(data: any): Competitor {
		return {
			id: data.id,
			threadsUserId: data.threadsUserId,
			threadsNumericId: data.threadsNumericId || undefined,
			username: data.username,
			displayName: data.displayName,
			avatarUrl: data.avatarUrl,
			bio: data.bio,
			followerCount: data.followerCount || 0,
			isVerified: data.isVerified || false,
			// 7-day engagement metrics
			likesCount7d: data.likesCount7d || 0,
			quotesCount7d: data.quotesCount7d || 0,
			repliesCount7d: data.repliesCount7d || 0,
			repostsCount7d: data.repostsCount7d || 0,
			viewsCount7d: data.viewsCount7d || 0,
			// Instagram-specific fields
			platform: data.platform || "threads",
			instagramUserId: data.instagramUserId,
			mediaCount: data.mediaCount || 0,
			avgLikes: data.avgLikes || 0,
			avgComments: data.avgComments || 0,
			engagementRate: data.engagementRate || 0,
			website: data.website,
			addedAt:
				typeof data.addedAt === "string"
					? new Date(data.addedAt)
					: data.addedAt || new Date(),
			lastSyncedAt:
				typeof data.lastSyncedAt === "string"
					? new Date(data.lastSyncedAt)
					: data.lastSyncedAt || new Date(),
		};
	}

	/**
	 * Search for Threads posts by keyword or topic tag
	 * Uses the /api/trends endpoint
	 */
	async searchThreadsPosts(params: {
		query: string;
		searchType?: "RECENT" | "TOP" | undefined;
		searchMode?: "KEYWORD" | "TAG" | undefined;
		mediaType?: "TEXT" | "IMAGE" | "VIDEO" | undefined;
		limit?: number | undefined;
	}): Promise<{
		success: boolean;
		posts: Array<{
			id: string;
			text: string;
			mediaType: string;
			mediaUrl: string | null;
			permalink: string | null;
			timestamp: string | null;
			username: string;
			hasReplies: boolean;
			isQuotePost: boolean;
			isReply: boolean;
			likeCount: number;
			replyCount: number;
			repostCount: number;
		}>;
		error?: string | undefined;
	}> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		try {
			const response = await fetch("/api/trends?action=search", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.access_token}`,
				},
				body: JSON.stringify({
					query: params.query,
					searchType: params.searchType || "RECENT",
					searchMode: params.searchMode || "KEYWORD",
					mediaType: params.mediaType,
					limit: params.limit || 50,
				}),
			});

			const data = await safeJsonParse(response, "Trends search");
			if (!data.success) {
				return {
					success: false,
					posts: [],
					error: data.error || "Search failed",
				};
			}

			// Transform the response to match expected format
			// biome-ignore lint/suspicious/noExplicitAny: API response post shape not typed
			const posts = (data.posts || []).map((post: any) => ({
				id: post.id,
				text: post.content || "",
				mediaType: post.mediaType || "TEXT",
				mediaUrl: post.mediaUrl || null,
				permalink: post.permalink || null,
				timestamp: post.timestamp || null,
				username: post.username || "",
				hasReplies: false,
				isQuotePost: false,
				isReply: false,
				likeCount: post.likeCount || 0,
				replyCount: post.replyCount || 0,
				repostCount: post.repostCount || 0,
			}));

			return { success: true, posts };
		} catch (error: unknown) {
			logger.error("Error searching Threads posts:", error);
			return {
				success: false,
				posts: [],
				error: error instanceof Error ? error.message : "Search failed",
			};
		}
	}
	// ============================================================================
	// Instagram Competitor Methods
	// ============================================================================

	/**
	 * Search for an Instagram profile by username
	 */
	async searchInstagramProfile(
		accountId: string,
		username: string,
	): Promise<SearchResult> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/competitors?action=ig-search", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify({ accountId, targetUsername: username }),
		});

		const data = await safeJsonParse<{
			success: boolean;
			profile: SearchResult;
			error?: string | undefined;
		}>(response, "IG search");
		if (!data.success) {
			throw new Error(data.error || "Profile not found");
		}
		return data.profile;
	}

	/**
	 * Add an Instagram competitor
	 */
	async addInstagramCompetitor(
		accountId: string,
		username: string,
	): Promise<Competitor> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/competitors?action=ig-add", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify({ accountId, targetUsername: username }),
		});

		const data = await safeJsonParse(response, "IG add competitor");
		if (!data.success) {
			throw new Error(data.error || "Failed to add competitor");
		}
		return this.parseCompetitor(data.competitor);
	}

	/**
	 * Sync an Instagram competitor's data
	 */
	async syncInstagramCompetitor(
		competitorId: string,
		accountId: string,
	): Promise<void> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/competitors?action=ig-sync", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify({ competitorId, accountId }),
		});

		const data = await safeJsonParse(response, "IG sync competitor");
		if (!data.success) {
			throw new Error(data.error || "Failed to sync competitor");
		}
	}

	/**
	 * Get all Instagram competitors for the current user
	 */
	async getInstagramCompetitors(): Promise<Competitor[]> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		const { data, error } = await supabase
			.from("competitors")
			.select("*")
			.eq("user_id", userId)
			.eq("platform", "instagram")
			.order("added_at", { ascending: false })
			.limit(200);

		if (error) throw error;
		if (!data || data.length === 0) return [];

		return data.map((row) =>
			this.parseCompetitor({
				id: row.id,
				threadsUserId: row.threads_user_id,
				username: row.username,
				displayName: row.display_name,
				avatarUrl: row.avatar_url,
				bio: row.bio,
				followerCount: row.follower_count,
				isVerified: row.is_verified,
				platform: "instagram",
				// biome-ignore lint/suspicious/noExplicitAny: Supabase row has Instagram-specific columns not in Threads type
				instagramUserId: (row as any).instagram_user_id,
				// biome-ignore lint/suspicious/noExplicitAny: Supabase row has Instagram-specific columns not in Threads type
				mediaCount: (row as any).media_count,
				// biome-ignore lint/suspicious/noExplicitAny: Supabase row has Instagram-specific columns not in Threads type
				avgLikes: (row as any).avg_likes,
				// biome-ignore lint/suspicious/noExplicitAny: Supabase row has Instagram-specific columns not in Threads type
				avgComments: (row as any).avg_comments,
				// biome-ignore lint/suspicious/noExplicitAny: Supabase row has Instagram-specific columns not in Threads type
				engagementRate: (row as any).engagement_rate,
				// biome-ignore lint/suspicious/noExplicitAny: Supabase row has Instagram-specific columns not in Threads type
				website: (row as any).website,
				addedAt: row.added_at,
				lastSyncedAt: row.last_synced_at,
			}),
		);
	}

	/**
	 * Subscribe to Instagram competitors list (real-time updates)
	 */
	subscribeToInstagramCompetitors(
		onUpdate: (competitors: Competitor[]) => void,
		onError: (error: Error) => void,
	): () => void {
		let isCleanedUp = false;

		const fetchCompetitors = async () => {
			if (isCleanedUp) return;
			try {
				const competitors = await this.getInstagramCompetitors();
				if (!isCleanedUp) onUpdate(competitors);
			} catch (error) {
				if (!isCleanedUp) onError(error as Error);
			}
		};

		fetchCompetitors();

		const unsub = subscribe(
			"ig-competitors",
			async (signal) => {
				const userId = await getSupabaseUserId();
				if (signal.aborted || !userId) {
					if (!userId && !signal.aborted)
						onError(new Error("Not authenticated"));
					return null;
				}

				return supabase
					.channel(`ig-competitors-${userId}`)
					.on(
						"postgres_changes",
						{
							event: "*",
							schema: "public",
							table: "competitors",
							filter: `user_id=eq.${userId}`,
						},
						() => fetchCompetitors(),
					)
					.subscribe();
			},
			fetchCompetitors,
		);

		return () => {
			isCleanedUp = true;
			unsub();
		};
	}

	/**
	 * Get Instagram competitor top posts
	 */
	async getInstagramCompetitorPosts(
		competitorId: string,
		limit = 12,
	): Promise<ScoredPost[]> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		const { data, error } = (await supabase
			.from("competitor_top_posts")
			.select("*")
			.eq("competitor_id", competitorId)
			.eq("platform", "instagram")
			.order("engagement_score", { ascending: false })
			// biome-ignore lint/suspicious/noExplicitAny: Supabase query cast to known response shape
			.limit(limit)) as { data: any[] | null; error: any };

		if (error) throw error;
		return (data || []).map((row) => this.parseScoredPostFromSupabase(row));
	}

	// ============================================================================
	// Instagram Benchmarking Methods
	// ============================================================================

	async getIgBenchmarks(
		accountId: string,
	): Promise<BenchmarkComparison | null> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch(
			`/api/competitors?action=ig-benchmarks&accountId=${encodeURIComponent(accountId)}`,
			{
				headers: { Authorization: `Bearer ${session.access_token}` },
			},
		);

		const data = await safeJsonParse<{
			success: boolean;
			benchmarks: BenchmarkComparison;
			error?: string | undefined;
		}>(response, "IG benchmarks");
		if (!data.success) return null;
		return data.benchmarks;
	}

	async getIgContentBreakdown(): Promise<ContentTypeBreakdown[]> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch(
			`/api/competitors?action=ig-content-breakdown`,
			{
				headers: { Authorization: `Bearer ${session.access_token}` },
			},
		);

		const data = await safeJsonParse<{
			success: boolean;
			breakdown: ContentTypeBreakdown[];
			error?: string | undefined;
		}>(response, "IG content breakdown");
		if (!data.success) return [];
		return data.breakdown || [];
	}

	async getIgComparisonHistory(
		competitorIds: string[],
		days = 30,
	): Promise<ComparisonSeries[]> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch(
			`/api/competitors?action=ig-comparison-history&competitorIds=${competitorIds.join(",")}&days=${days}`,
			{
				headers: { Authorization: `Bearer ${session.access_token}` },
			},
		);

		const data = await safeJsonParse<{
			success: boolean;
			series: ComparisonSeries[];
			error?: string | undefined;
		}>(response, "IG comparison history");
		if (!data.success) return [];
		return data.series || [];
	}

	async getCompetitorAlerts(unreadOnly = false): Promise<CompetitorAlert[]> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		let query = supabase
			.from("competitor_alerts")
			.select("*")
			.eq("user_id", userId)
			.order("created_at", { ascending: false })
			.limit(50);

		if (unreadOnly) {
			query = query.eq("read", false);
		}

		const { data, error } = await query;
		if (error) throw error;

		return (data || []).map((row) => ({
			id: row.id,
			competitorId: row.competitor_id,
			// biome-ignore lint/suspicious/noExplicitAny: alert_type is a DB enum not reflected in generated types
			alertType: row.alert_type as any,
			message: row.message,
			// biome-ignore lint/suspicious/noExplicitAny: metadata is an open-ended JSON blob
			metadata: (row.metadata as Record<string, any>) || {},
			read: row.read || false,
			// biome-ignore lint/suspicious/noExplicitAny: Supabase date field type
			createdAt: new Date(row.created_at as any),
		}));
	}

	async markAlertRead(alertId: string): Promise<void> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		await supabase
			.from("competitor_alerts")
			.update({ read: true })
			.eq("id", alertId)
			.eq("user_id", userId);
	}

	async markAllAlertsRead(): Promise<void> {
		const userId = await getSupabaseUserId();
		if (!userId) throw new Error("Not authenticated");

		await supabase
			.from("competitor_alerts")
			.update({ read: true })
			.eq("user_id", userId)
			.eq("read", false);
	}

	async detectIgAlerts(): Promise<number> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch(`/api/competitors?action=ig-detect-alerts`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
		});

		const data = await safeJsonParse<{
			success: boolean;
			alertsCreated: number;
			error?: string | undefined;
		}>(response, "IG detect alerts");
		return data.alertsCreated || 0;
	}
}

export const competitorService = new CompetitorService();
