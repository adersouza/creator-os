/**
 * Inspiration Service
 * Manages AI-generated content ideas from competitor top posts
 * Features: Daily scans, viral scoring, queue integration, tier limits
 */

import { subscribe } from "@/services/realtimeManager.js";
import {
	createServiceLogger,
	dbQuery,
	getUserIdAsync,
	supabase,
} from "./api/shared.js";
import { addToAutoQueue } from "./autoPostService.js";

const log = createServiceLogger("inspirationService");

// Helper to get current user ID
const getSupabaseUserId = async (): Promise<string | null> => {
	try {
		return await getUserIdAsync();
	} catch {
		return null;
	}
};

// Adaptation styles for AI generation
export type AdaptationStyle =
	| "casual"
	| "professional"
	| "witty"
	| "inspirational"
	| "edgy";

// Adaptation angles for variety
export type AdaptationAngle =
	| "direct"
	| "counter"
	| "story"
	| "list"
	| "meme"
	| "question";

export const ADAPTATION_ANGLE_LABELS: Record<AdaptationAngle, string> = {
	direct: "Direct",
	counter: "Counter",
	story: "Story",
	list: "List",
	meme: "Meme",
	question: "Question",
};

// Status of an inspiration idea
export type InspirationStatus =
	| "pending"
	| "saved"
	| "queued"
	| "posted"
	| "dismissed";

// Original post data from competitor
export interface OriginalPost {
	id: string;
	content: string;
	mediaUrl?: string | undefined;
	mediaType?: string | undefined;
	permalink?: string | undefined;
	engagementScore: number;
	likes?: number | undefined;
	replies?: number | undefined;
	reposts?: number | undefined;
}

// Inspiration idea interface
export interface InspirationIdea {
	id: string;
	userId: string;
	workspaceId?: string | undefined;
	originalPost: OriginalPost;
	competitorId?: string | undefined;
	competitorUsername: string;
	competitorAvatarUrl?: string | undefined;
	adaptedContent: string;
	viralScore: number;
	aiInsight: string;
	topicTags: string[];
	adaptationStyle: AdaptationStyle;
	adaptationAngle?: AdaptationAngle | undefined; // The angle used for this adaptation
	viralFormula?: string | undefined; // The extracted viral formula (e.g. "Contrarian + curiosity + one-liner")
	status: InspirationStatus;
	saved: boolean;
	queued: boolean;
	queuedAt?: Date | undefined;
	postedAt?: Date | undefined;
	generatedAt: Date;
	expiresAt: Date;
	createdAt: Date;
}

// Configuration for inspiration generation
export interface InspirationConfig {
	id: string;
	userId: string;
	workspaceId?: string | undefined;
	enabled: boolean;
	ideasPerCompetitor: number;
	adaptationStyle: AdaptationStyle;
	topicFilters: string[];
	notifyNewIdeas: boolean;
	dailyDigestEnabled: boolean;
	lastScanAt?: Date | undefined;
	ideasGeneratedToday: number;
	lastGenerationReset?: string | undefined;
}

// Filters for querying ideas
export interface InspirationFilters {
	competitor?: string | undefined;
	minScore?: number | undefined;
	maxScore?: number | undefined;
	status?: InspirationStatus | InspirationStatus[] | undefined;
	saved?: boolean | undefined;
	queued?: boolean | undefined;
	topicTag?: string | undefined;
	angle?: AdaptationAngle | undefined; // Filter by adaptation angle
	sortBy?: "viral_score" | "generated_at" | "competitor_username" | undefined;
	sortOrder?: "asc" | "desc" | undefined;
	limit?: number | undefined;
	offset?: number | undefined;
}

// Default configuration
export const DEFAULT_INSPIRATION_CONFIG: Omit<
	InspirationConfig,
	"id" | "userId"
> = {
	enabled: true,
	ideasPerCompetitor: 10,
	adaptationStyle: "casual",
	topicFilters: [],
	notifyNewIdeas: true,
	dailyDigestEnabled: false,
	ideasGeneratedToday: 0,
};

// Tier limits for idea generation
export const TIER_LIMITS = {
	free: { dailyIdeas: 10, manualRefreshCooldown: 24 * 60 }, // 24 hours
	pro: { dailyIdeas: 50, manualRefreshCooldown: 60 }, // 1 hour
	agency: { dailyIdeas: Infinity, manualRefreshCooldown: 30 }, // 30 min
	empire: { dailyIdeas: Infinity, manualRefreshCooldown: 0 }, // No limit
};

/**
 * Get the workspace ID for the current user
 */
const getWorkspaceId = async (): Promise<string | null> => {
	const userId = await getSupabaseUserId();
	if (!userId) return null;

	const { data, error } = await supabase
		.from("workspaces")
		.select("id")
		.eq("owner_id", userId)
		.limit(1)
		.maybeSingle();

	if (error || !data) return null;
	return data.id;
};

/**
 * Convert database row to InspirationIdea interface
 */
const mapRowToIdea = (row: Record<string, unknown>): InspirationIdea => {
	// Get competitor data from joined table if available
	const competitor = row.competitors as {
		username?: string | undefined;
		avatar_url?: string | undefined;
	} | null;

	return {
		id: row.id as string,
		userId: row.user_id as string,
		workspaceId: row.workspace_id as string | undefined,
		originalPost: row.original_post as OriginalPost,
		competitorId: row.competitor_id as string | undefined,
		// Use joined competitor data as fallback if direct field is null
		competitorUsername:
			(row.competitor_username as string) || competitor?.username || "unknown",
		competitorAvatarUrl:
			(row.competitor_avatar_url as string) ||
			competitor?.avatar_url ||
			undefined,
		adaptedContent: row.adapted_content as string,
		viralScore: row.viral_score as number,
		aiInsight: row.ai_insight as string,
		topicTags: (row.topic_tags as string[]) || [],
		adaptationStyle: row.adaptation_style as AdaptationStyle,
		adaptationAngle: row.adaptation_angle as AdaptationAngle | undefined,
		viralFormula: row.viral_formula as string | undefined,
		status: row.status as InspirationStatus,
		saved: row.saved as boolean,
		queued: row.queued as boolean,
		queuedAt: row.queued_at ? new Date(row.queued_at as string) : undefined,
		postedAt: row.posted_at ? new Date(row.posted_at as string) : undefined,
		generatedAt: new Date(row.generated_at as string),
		expiresAt: new Date(row.expires_at as string),
		createdAt: new Date(row.created_at as string),
	};
};

/**
 * Convert database row to InspirationConfig interface
 */
const mapRowToConfig = (row: Record<string, unknown>): InspirationConfig => ({
	id: row.id as string,
	userId: row.user_id as string,
	workspaceId: row.workspace_id as string | undefined,
	enabled: row.enabled as boolean,
	ideasPerCompetitor: row.ideas_per_competitor as number,
	adaptationStyle: row.adaptation_style as AdaptationStyle,
	topicFilters: (row.topic_filters as string[]) || [],
	notifyNewIdeas: row.notify_new_ideas as boolean,
	dailyDigestEnabled: row.daily_digest_enabled as boolean,
	lastScanAt: row.last_scan_at
		? new Date(row.last_scan_at as string)
		: undefined,
	ideasGeneratedToday: row.ideas_generated_today as number,
	lastGenerationReset: row.last_generation_reset as string | undefined,
});

/**
 * Get inspiration ideas with optional filters
 */
export const getIdeas = async (
	filters?: InspirationFilters,
): Promise<InspirationIdea[]> => {
	const userId = await getSupabaseUserId();
	if (!userId) {
		log.error("No user logged in");
		return [];
	}

	try {
		// Join with competitors to get username/avatar if missing from idea
		let query = supabase
			.from("inspiration_ideas")
			.select("*, competitors(username, avatar_url)")
			.eq("user_id", userId)
			.or("status.is.null,status.neq.dismissed");

		// Apply filters
		if (filters?.competitor) {
			query = query.eq("competitor_username", filters.competitor);
		}
		if (filters?.minScore !== undefined) {
			query = query.gte("viral_score", filters.minScore);
		}
		if (filters?.maxScore !== undefined) {
			query = query.lte("viral_score", filters.maxScore);
		}
		if (filters?.status) {
			if (Array.isArray(filters.status)) {
				query = query.in("status", filters.status);
			} else {
				query = query.eq("status", filters.status);
			}
		}
		if (filters?.saved !== undefined) {
			query = query.eq("saved", filters.saved);
		}
		if (filters?.queued !== undefined) {
			query = query.eq("queued", filters.queued);
		}
		if (filters?.topicTag) {
			query = query.contains("topic_tags", [filters.topicTag]);
		}

		// Sorting
		const sortBy = filters?.sortBy || "viral_score";
		const sortOrder = filters?.sortOrder || "desc";
		query = query.order(sortBy, { ascending: sortOrder === "asc" });

		// Pagination
		if (filters?.limit) {
			query = query.limit(filters.limit);
		}
		if (filters?.offset) {
			query = query.range(
				filters.offset,
				filters.offset + (filters.limit || 50) - 1,
			);
		}

		const data = await dbQuery(
			query,
			"[inspirationService] Error fetching ideas",
		);

		return (data || []).map(mapRowToIdea);
	} catch (error) {
		log.error("Failed to get ideas:", error);
		return [];
	}
};

/**
 * Get ideas for a specific competitor
 */
export const getIdeasByCompetitor = async (
	competitorUsername: string,
): Promise<InspirationIdea[]> => {
	return getIdeas({ competitor: competitorUsername });
};

/**
 * Get a single idea by ID
 */
export const getIdea = async (id: string): Promise<InspirationIdea | null> => {
	const userId = await getSupabaseUserId();
	if (!userId) return null;

	const { data, error } = await supabase
		.from("inspiration_ideas")
		.select("*")
		.eq("id", id)
		.eq("user_id", userId)
		.maybeSingle();

	if (error || !data) return null;
	return mapRowToIdea(data);
};

/**
 * Save an idea (mark as favorite)
 */
export const saveIdea = async (id: string): Promise<boolean> => {
	const userId = await getSupabaseUserId();
	if (!userId) return false;

	try {
		const { error } = await supabase
			.from("inspiration_ideas")
			.update({ saved: true, status: "saved" })
			.eq("id", id)
			.eq("user_id", userId);

		if (error) throw error;
		log.info("Idea saved:", id);
		return true;
	} catch (error) {
		log.error("Failed to save idea:", error);
		return false;
	}
};

/**
 * Unsave an idea
 */
export const unsaveIdea = async (id: string): Promise<boolean> => {
	const userId = await getSupabaseUserId();
	if (!userId) return false;

	try {
		const { error } = await supabase
			.from("inspiration_ideas")
			.update({ saved: false, status: "pending" })
			.eq("id", id)
			.eq("user_id", userId);

		if (error) throw error;
		return true;
	} catch (error) {
		log.error("Failed to unsave idea:", error);
		return false;
	}
};

/**
 * Dismiss an idea (hide from view)
 */
export const dismissIdea = async (id: string): Promise<boolean> => {
	const userId = await getSupabaseUserId();
	if (!userId) return false;

	try {
		const { error } = await supabase
			.from("inspiration_ideas")
			.update({ status: "dismissed" })
			.eq("id", id)
			.eq("user_id", userId);

		if (error) throw error;
		log.info("Idea dismissed:", id);
		return true;
	} catch (error) {
		log.error("Failed to dismiss idea:", error);
		return false;
	}
};

/**
 * Queue an idea for auto-posting (Empire tier only)
 */
export const queueIdea = async (id: string): Promise<boolean> => {
	const userId = await getSupabaseUserId();
	if (!userId) return false;

	try {
		// Get the idea
		const idea = await getIdea(id);
		if (!idea) {
			log.error("Idea not found:", id);
			return false;
		}

		// Add to auto-poster queue
		const queueResult = await addToAutoQueue(idea.adaptedContent);
		if (!queueResult.success) {
			log.error("Failed to add to auto-queue");
			return false;
		}

		// Update idea status
		const { error } = await supabase
			.from("inspiration_ideas")
			.update({
				status: "queued",
				queued: true,
				queued_at: new Date().toISOString(),
			})
			.eq("id", id)
			.eq("user_id", userId);

		if (error) throw error;
		log.info("Idea queued:", id);
		return true;
	} catch (error) {
		log.error("Failed to queue idea:", error);
		return false;
	}
};

/**
 * Bulk queue top N ideas by viral score (Empire tier only)
 */
export const bulkQueueTop = async (
	count: number = 20,
): Promise<{ queued: number; failed: number }> => {
	const userId = await getSupabaseUserId();
	if (!userId) return { queued: 0, failed: 0 };

	try {
		// Get top ideas that aren't already queued
		const ideas = await getIdeas({
			status: ["pending", "saved"],
			queued: false,
			sortBy: "viral_score",
			sortOrder: "desc",
			limit: count,
		});

		let queued = 0;
		let failed = 0;

		for (const idea of ideas) {
			const success = await queueIdea(idea.id);
			if (success) {
				queued++;
			} else {
				failed++;
			}
		}

		log.info(`Bulk queue complete: ${queued} queued, ${failed} failed`);
		return { queued, failed };
	} catch (error) {
		log.error("Bulk queue failed:", error);
		return { queued: 0, failed: 0 };
	}
};

/**
 * Get inspiration configuration for current user
 */
export const getConfig = async (): Promise<InspirationConfig | null> => {
	const userId = await getSupabaseUserId();
	if (!userId) return null;

	try {
		const { data, error } = await supabase
			.from("inspiration_config")
			.select("*")
			.eq("user_id", userId)
			.maybeSingle();

		if (error) throw error;

		if (!data) {
			// Create default config
			const workspaceId = await getWorkspaceId();
			const newConfig = {
				user_id: userId,
				workspace_id: workspaceId,
				enabled: DEFAULT_INSPIRATION_CONFIG.enabled,
				ideas_per_competitor: DEFAULT_INSPIRATION_CONFIG.ideasPerCompetitor,
				adaptation_style: DEFAULT_INSPIRATION_CONFIG.adaptationStyle,
				topic_filters: DEFAULT_INSPIRATION_CONFIG.topicFilters,
				notify_new_ideas: DEFAULT_INSPIRATION_CONFIG.notifyNewIdeas,
				daily_digest_enabled: DEFAULT_INSPIRATION_CONFIG.dailyDigestEnabled,
				ideas_generated_today: 0,
			};

			const { data: created, error: createError } = await supabase
				.from("inspiration_config")
				.insert(newConfig)
				.select()
				.maybeSingle();

			if (createError) throw createError;
			if (!created) throw new Error("Failed to create inspiration config");
			return mapRowToConfig(created);
		}

		return mapRowToConfig(data);
	} catch (error) {
		log.error("Failed to get config:", error);
		return null;
	}
};

/**
 * Update inspiration configuration
 */
export const updateConfig = async (
	updates: Partial<InspirationConfig>,
): Promise<boolean> => {
	const userId = await getSupabaseUserId();
	if (!userId) return false;

	try {
		// Map to database column names
		const dbUpdates: Record<string, unknown> = {};
		if (updates.enabled !== undefined) dbUpdates.enabled = updates.enabled;
		if (updates.ideasPerCompetitor !== undefined)
			dbUpdates.ideas_per_competitor = updates.ideasPerCompetitor;
		if (updates.adaptationStyle !== undefined)
			dbUpdates.adaptation_style = updates.adaptationStyle;
		if (updates.topicFilters !== undefined)
			dbUpdates.topic_filters = updates.topicFilters;
		if (updates.notifyNewIdeas !== undefined)
			dbUpdates.notify_new_ideas = updates.notifyNewIdeas;
		if (updates.dailyDigestEnabled !== undefined)
			dbUpdates.daily_digest_enabled = updates.dailyDigestEnabled;

		const { error } = await supabase
			.from("inspiration_config")
			.update(dbUpdates)
			.eq("user_id", userId);

		if (error) throw error;
		return true;
	} catch (error) {
		log.error("Failed to update config:", error);
		return false;
	}
};

/**
 * Get count of ideas by status
 */
export const getIdeaCounts = async (): Promise<{
	total: number;
	pending: number;
	saved: number;
	queued: number;
}> => {
	const userId = await getSupabaseUserId();
	if (!userId) return { total: 0, pending: 0, saved: 0, queued: 0 };

	try {
		const { data, error } = await supabase
			.from("inspiration_ideas")
			.select("status")
			.eq("user_id", userId)
			.or("status.is.null,status.neq.dismissed");

		if (error) throw error;

		const counts = {
			total: data?.length || 0,
			pending: data?.filter((d) => d.status === "pending").length || 0,
			saved: data?.filter((d) => d.status === "saved").length || 0,
			queued: data?.filter((d) => d.status === "queued").length || 0,
		};

		return counts;
	} catch (error) {
		log.error("Failed to get counts:", error);
		return { total: 0, pending: 0, saved: 0, queued: 0 };
	}
};

/**
 * Get unique competitors from ideas
 */
export const getCompetitorsWithIdeas = async (): Promise<
	Array<{ username: string; avatarUrl?: string | undefined; count: number }>
> => {
	const userId = await getSupabaseUserId();
	if (!userId) return [];

	try {
		const { data, error } = await supabase
			.from("inspiration_ideas")
			.select("competitor_username, competitor_avatar_url")
			.eq("user_id", userId)
			.or("status.is.null,status.neq.dismissed");

		if (error) throw error;

		// Group by username
		const grouped = (data || []).reduce(
			(acc, row) => {
				const username = row.competitor_username;
				if (!acc[username]) {
					acc[username] = {
						username,
						avatarUrl: row.competitor_avatar_url ?? undefined,
						count: 0,
					};
				}
				acc[username].count++;
				return acc;
			},
			{} as Record<
				string,
				{ username: string; avatarUrl?: string | undefined; count: number }
			>,
		);

		return Object.values(grouped).sort((a, b) => b.count - a.count);
	} catch (error) {
		log.error("Failed to get competitors:", error);
		return [];
	}
};

/**
 * Get unique topic tags from ideas
 */
export const getTopicTags = async (): Promise<
	Array<{ tag: string; count: number }>
> => {
	const userId = await getSupabaseUserId();
	if (!userId) return [];

	try {
		const { data, error } = await supabase
			.from("inspiration_ideas")
			.select("topic_tags")
			.eq("user_id", userId)
			.or("status.is.null,status.neq.dismissed");

		if (error) throw error;

		// Flatten and count tags
		const tagCounts: Record<string, number> = {};
		for (const row of data || []) {
			for (const tag of row.topic_tags || []) {
				tagCounts[tag] = (tagCounts[tag] || 0) + 1;
			}
		}

		return Object.entries(tagCounts)
			.map(([tag, count]) => ({ tag, count }))
			.sort((a, b) => b.count - a.count);
	} catch (error) {
		log.error("Failed to get topic tags:", error);
		return [];
	}
};

/**
 * Subscribe to real-time updates for ideas
 */
export const subscribeToIdeas = (
	onUpdate: (ideas: InspirationIdea[]) => void,
	onError: (error: Error) => void,
): (() => void) => {
	let isCleanedUp = false;

	const fetchIdeas = async () => {
		if (isCleanedUp) return;
		try {
			const ideas = await getIdeas();
			if (!isCleanedUp) onUpdate(ideas);
		} catch (err) {
			if (!isCleanedUp)
				onError(err instanceof Error ? err : new Error(String(err)));
		}
	};

	// Initial setup — verify auth + fetch
	(async () => {
		const userId = await getSupabaseUserId();
		if (isCleanedUp) return;
		if (!userId) {
			onError(new Error("No user logged in"));
			return;
		}
		await fetchIdeas();
	})();

	const unsub = subscribe(
		"inspiration-ideas",
		() =>
			supabase
				.channel("inspiration_ideas_changes")
				.on(
					"postgres_changes",
					{
						event: "*",
						schema: "public",
						table: "inspiration_ideas",
					},
					async (payload) => {
						if (isCleanedUp) return;
						log.debug("Real-time update:", payload);
						const ideas = await getIdeas();
						if (!isCleanedUp) onUpdate(ideas);
					},
				)
				.subscribe(),
		fetchIdeas,
	);

	return () => {
		isCleanedUp = true;
		unsub();
	};
};

/**
 * Delete expired ideas (cleanup function for cron)
 */
export const deleteExpiredIdeas = async (): Promise<number> => {
	try {
		const { data, error } = await supabase
			.from("inspiration_ideas")
			.delete()
			.lt("expires_at", new Date().toISOString())
			.eq("status", "pending") // Only delete pending, not saved
			.select("id");

		if (error) throw error;
		return data?.length || 0;
	} catch (error) {
		log.error("Failed to delete expired:", error);
		return 0;
	}
};

/**
 * Save an external post (from search results) to inspiration
 */
export interface ExternalPost {
	id: string;
	content: string;
	username: string;
	mediaUrl?: string | undefined;
	mediaType?: string | undefined;
	permalink?: string | undefined;
	likeCount?: number | undefined;
	replyCount?: number | undefined;
	repostCount?: number | undefined;
	viewCount?: number | undefined;
}

export const saveExternalPost = async (
	post: ExternalPost,
): Promise<boolean> => {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session) {
		log.error("No session for saveExternalPost");
		return false;
	}

	try {
		const response = await fetch("/api/inspiration?action=save-external", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify({ post }),
		});

		const data = await response.json();

		if (!response.ok) {
			if (response.status === 409) {
				// Already saved - not an error
				log.info("Post already saved");
				return true;
			}
			throw new Error(data.error || "Failed to save post");
		}

		log.info("External post saved:", post.id);
		return true;
	} catch (error) {
		log.error("Failed to save external post:", error);
		throw error;
	}
};

// Export as a service object for convenience
export const inspirationService = {
	getIdeas,
	getIdeasByCompetitor,
	getIdea,
	saveIdea,
	unsaveIdea,
	dismissIdea,
	queueIdea,
	bulkQueueTop,
	getConfig,
	updateConfig,
	getIdeaCounts,
	getCompetitorsWithIdeas,
	getTopicTags,
	subscribeToIdeas,
	deleteExpiredIdeas,
	saveExternalPost,
	TIER_LIMITS,
	DEFAULT_INSPIRATION_CONFIG,
};

export default inspirationService;
