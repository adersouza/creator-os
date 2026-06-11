/**
 * Discover Service
 * Handles keyword search and saved searches management
 */

import logger from "@/utils/logger.js";
import { supabase } from "./supabase.js";

type JsonObject = Record<string, unknown>;

const getString = (value: unknown): string | undefined =>
	typeof value === "string" ? value : undefined;

const getNumber = (value: unknown, fallback = 0): number =>
	typeof value === "number"
		? value
		: typeof value === "string"
			? Number.parseFloat(value) || fallback
			: fallback;

const getBoolean = (value: unknown, fallback = false): boolean =>
	typeof value === "boolean" ? value : fallback;

const getArray = <T>(value: unknown): T[] =>
	Array.isArray(value) ? (value as T[]) : [];

const getObject = (value: unknown): JsonObject | undefined =>
	value && typeof value === "object" && !Array.isArray(value)
		? (value as JsonObject)
		: undefined;

// Helper to safely parse JSON response
const safeJsonParse = async (response: Response): Promise<JsonObject> => {
	const text = await response.text();
	try {
		const parsed: unknown = JSON.parse(text);
		if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
			return parsed as JsonObject;
		}
		throw new Error("Unexpected non-object JSON response");
	} catch {
		// API not available (likely in development mode)
		if (text.includes("vite") || text.includes("<!DOCTYPE")) {
			throw new Error(
				"API not available. Run 'vercel dev' instead of 'npm run dev' to test API routes locally.",
			);
		}
		if (text.includes("FUNCTION_INVOCATION_TIMEOUT")) {
			throw new Error(
				"Search timed out. Try a shorter or more specific query.",
			);
		}
		throw new Error(`Invalid JSON response: ${text.substring(0, 100)}`);
	}
};

// ============================================================================
// Types
// ============================================================================

export interface SearchParams {
	query: string;
	searchMode?: "KEYWORD" | "TAG" | undefined;
	searchType?: "RECENT" | "TOP" | undefined;
	mediaType?: "TEXT" | "IMAGE" | "VIDEO" | "ALL" | undefined;
	authorUsername?: string | undefined;
	limit?: number | undefined;
}

export interface SearchResultPost {
	id: string;
	content: string;
	mediaUrl?: string | undefined;
	mediaType?: string | undefined;
	permalink?: string | undefined;
	timestamp: string;
	username: string;
	likeCount: number;
	replyCount: number;
	repostCount: number;
	viewCount: number;
	engagementScore: number;
}

export interface SearchResults {
	posts: SearchResultPost[];
	totalFound: number;
	totalEngagement: number;
	avgEngagement: number;
}

export interface SavedSearch {
	id: string;
	name: string;
	query: string;
	searchMode: "KEYWORD" | "TAG";
	searchType: "RECENT" | "TOP";
	mediaType?: "TEXT" | "IMAGE" | "VIDEO" | undefined;
	lastVolume: number;
	volumeChange: number;
	volumeChangePercent: number;
	lastRefreshedAt?: Date | undefined;
	alertsEnabled: boolean;
	alertThreshold: number;
	createdAt: Date;
	updatedAt: Date;
}

export interface SavedSearchInput {
	name: string;
	query: string;
	searchMode?: "KEYWORD" | "TAG" | undefined;
	searchType?: "RECENT" | "TOP" | undefined;
	mediaType?: "TEXT" | "IMAGE" | "VIDEO" | undefined;
}

export interface SearchSnapshot {
	id: string;
	snapshotDate: string;
	postVolume: number;
	totalEngagement: number;
	avgEngagement: number;
}

export interface SearchLimits {
	allowed: boolean;
	limit: number;
	current: number;
	alertsEnabled?: boolean | undefined;
	tier?: string | undefined;
}

interface SavedSearchRow {
	id: string;
	name: string;
	query: string;
	search_mode?: "KEYWORD" | "TAG" | null | undefined;
	search_type?: "RECENT" | "TOP" | null | undefined;
	media_type?: "TEXT" | "IMAGE" | "VIDEO" | null | undefined;
	last_volume?: number | null | undefined;
	volume_change?: number | null | undefined;
	volume_change_percent?: string | number | null | undefined;
	last_refreshed_at?: string | null | undefined;
	alerts_enabled?: boolean | null | undefined;
	alert_threshold?: number | null | undefined;
	created_at: string;
	updated_at: string;
}

interface SearchSnapshotRow {
	id: string;
	snapshot_date: string;
	post_volume?: number | null | undefined;
	total_engagement?: number | null | undefined;
	avg_engagement?: string | number | null | undefined;
}

const parseSavedSearchRow = (value: unknown): SavedSearchRow => {
	const row = getObject(value);
	if (!row) {
		throw new Error("Missing saved search payload");
	}

	const id = getString(row.id);
	const name = getString(row.name);
	const query = getString(row.query);
	const createdAt = getString(row.created_at);
	const updatedAt = getString(row.updated_at);

	if (!id || !name || !query || !createdAt || !updatedAt) {
		throw new Error("Invalid saved search payload");
	}

	return {
		id,
		name,
		query,
		search_mode:
			row.search_mode === "KEYWORD" || row.search_mode === "TAG"
				? row.search_mode
				: null,
		search_type:
			row.search_type === "RECENT" || row.search_type === "TOP"
				? row.search_type
				: null,
		media_type:
			row.media_type === "TEXT" ||
			row.media_type === "IMAGE" ||
			row.media_type === "VIDEO"
				? row.media_type
				: null,
		last_volume: typeof row.last_volume === "number" ? row.last_volume : null,
		volume_change:
			typeof row.volume_change === "number" ? row.volume_change : null,
		volume_change_percent:
			typeof row.volume_change_percent === "number" ||
			typeof row.volume_change_percent === "string"
				? row.volume_change_percent
				: null,
		last_refreshed_at: getString(row.last_refreshed_at) || null,
		alerts_enabled:
			typeof row.alerts_enabled === "boolean" ? row.alerts_enabled : null,
		alert_threshold:
			typeof row.alert_threshold === "number" ? row.alert_threshold : null,
		created_at: createdAt,
		updated_at: updatedAt,
	};
};

/** Instagram media item returned from hashtag search */
export interface IGMediaItem {
	id: string;
	media_type?: string | undefined;
	media_url?: string | undefined;
	caption?: string | undefined;
	permalink?: string | undefined;
	like_count?: number | undefined;
	comments_count?: number | undefined;
	timestamp?: string | undefined;
}

/** Instagram hashtag search result */
export interface IGHashtagResult {
	id?: string | undefined;
	name?: string | undefined;
}

// ============================================================================
// Service Class
// ============================================================================

class DiscoverService {
	// --------------------------------------------------------------------------
	// Search Execution
	// --------------------------------------------------------------------------

	/**
	 * Execute a keyword search with 1-retry resilience for transient failures
	 */
	async search(params: SearchParams): Promise<SearchResults> {
		const executeFetch = async (retryCount = 0): Promise<Response> => {
			const {
				data: { session },
			} = await supabase.auth.getSession();
			if (!session) throw new Error("Not authenticated");

			const controller = new AbortController();
			const timeoutId = setTimeout(() => controller.abort(), 12000);

			try {
				const response = await fetch("/api/discover?action=search", {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						Authorization: `Bearer ${session.access_token}`,
					},
					body: JSON.stringify({
						query: params.query,
						searchMode: params.searchMode || "KEYWORD",
						searchType: params.searchType || "RECENT",
						mediaType: params.mediaType === "ALL" ? null : params.mediaType,
						authorUsername: params.authorUsername || undefined,
						limit: params.limit || 25,
					}),
					signal: controller.signal,
				});

				// Retry on 5xx transient server errors
				if (response.status >= 500 && retryCount === 0) {
					logger.warn(
						`Search failed with ${response.status}, retrying once...`,
					);
					clearTimeout(timeoutId);
					await new Promise((r) => setTimeout(r, 1000)); // 1s delay
					return executeFetch(1);
				}

				return response;
			} catch (e: unknown) {
				if (e instanceof Error && e.name === "AbortError") {
					if (retryCount === 0) {
						logger.warn("Search timed out, retrying once...");
						clearTimeout(timeoutId);
						return executeFetch(1);
					}
					throw new Error(
						"Search timed out. Try a shorter or more specific query.",
					);
				}
				throw e;
			} finally {
				clearTimeout(timeoutId);
			}
		};

		const response = await executeFetch();
		const data = await safeJsonParse(response);
		if (!getBoolean(data.success)) {
			throw new Error(getString(data.error) || "Search failed");
		}

		return {
			posts: getArray<SearchResultPost>(data.posts),
			totalFound: getNumber(data.totalFound),
			totalEngagement: getNumber(data.totalEngagement),
			avgEngagement: getNumber(data.avgEngagement),
		};
	}

	// --------------------------------------------------------------------------
	// Saved Searches CRUD
	// --------------------------------------------------------------------------

	/**
	 * Save a search query
	 */
	async saveSearch(input: SavedSearchInput): Promise<SavedSearch> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/discover?action=save-search", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify(input),
		});

		const data = await safeJsonParse(response);
		if (!getBoolean(data.success)) {
			throw new Error(getString(data.error) || "Failed to save search");
		}

		return this.parseSearchFromSupabase(parseSavedSearchRow(data.savedSearch));
	}

	/**
	 * Get all saved searches for current user
	 */
	async getSavedSearches(): Promise<{
		searches: SavedSearch[];
		limits: { current: number; max: number };
	}> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/discover?action=get-searches", {
			headers: {
				Authorization: `Bearer ${session.access_token}`,
			},
		});

		const data = await safeJsonParse(response);
		if (!getBoolean(data.success)) {
			throw new Error(getString(data.error) || "Failed to get searches");
		}

		const limits = getObject(data.limits);
		return {
			searches: getArray<SavedSearchRow>(data.searches).map((search) =>
				this.parseSearchFromSupabase(search),
			),
			limits: {
				current: getNumber(limits?.current),
				max: getNumber(limits?.max, 5),
			},
		};
	}

	/**
	 * Delete a saved search
	 */
	async deleteSavedSearch(searchId: string): Promise<void> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/discover?action=delete-search", {
			method: "DELETE",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify({ searchId }),
		});

		const data = await safeJsonParse(response);
		if (!getBoolean(data.success)) {
			throw new Error(getString(data.error) || "Failed to delete search");
		}
	}

	/**
	 * Manually refresh a saved search's metrics
	 */
	async refreshSavedSearch(searchId: string): Promise<SavedSearch> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/discover?action=refresh-search", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify({ searchId }),
		});

		const data = await safeJsonParse(response);
		if (!getBoolean(data.success)) {
			throw new Error(getString(data.error) || "Failed to refresh search");
		}

		return this.parseSearchFromSupabase(parseSavedSearchRow(data.savedSearch));
	}

	// --------------------------------------------------------------------------
	// Snapshots
	// --------------------------------------------------------------------------

	/**
	 * Get snapshot history for a saved search
	 */
	async getSearchSnapshots(
		searchId: string,
		days = 30,
	): Promise<SearchSnapshot[]> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch(
			`/api/discover?action=get-snapshots&searchId=${searchId}&days=${days}`,
			{
				headers: {
					Authorization: `Bearer ${session.access_token}`,
				},
			},
		);

		const data = await safeJsonParse(response);
		if (!getBoolean(data.success)) {
			throw new Error(getString(data.error) || "Failed to get snapshots");
		}

		const snapshotRows = getArray<SearchSnapshotRow>(data.snapshots);
		return snapshotRows.map((snapshot) => ({
			id: snapshot.id,
			snapshotDate: snapshot.snapshot_date,
			postVolume: snapshot.post_volume || 0,
			totalEngagement: snapshot.total_engagement || 0,
			avgEngagement:
				Number.parseFloat(String(snapshot.avg_engagement || 0)) || 0,
		}));
	}

	// --------------------------------------------------------------------------
	// Tier Limits
	// --------------------------------------------------------------------------

	/**
	 * Check if user can save more searches
	 */
	async canSaveSearch(): Promise<SearchLimits> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/discover?action=check-limits", {
			headers: {
				Authorization: `Bearer ${session.access_token}`,
			},
		});

		const data = await safeJsonParse(response);
		if (!getBoolean(data.success)) {
			throw new Error(getString(data.error) || "Failed to check limits");
		}

		return {
			allowed: getBoolean(data.allowed),
			limit: getNumber(data.limit),
			current: getNumber(data.current),
			alertsEnabled: getBoolean(data.alertsEnabled),
			tier: getString(data.tier),
		};
	}

	// --------------------------------------------------------------------------
	// Real-time Subscriptions
	// --------------------------------------------------------------------------

	/**
	 * Subscribe to real-time updates for saved searches
	 * NOTE: saved_searches table was dropped — stub returns no-op unsubscribe
	 */
	subscribeToSavedSearches(
		_onUpdate: (searches: SavedSearch[]) => void,
		_onError: (error: Error) => void,
	): () => void {
		return () => {};
	}

	// --------------------------------------------------------------------------
	// Instagram Hashtag Search
	// --------------------------------------------------------------------------

	/**
	 * Search for an Instagram hashtag by name
	 */
	async searchInstagramHashtag(
		query: string,
		accountId: string,
	): Promise<{ hashtag: IGHashtagResult | null }> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/instagram/hashtags?action=search", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify({ accountId, query }),
		});

		const data = await safeJsonParse(response);
		if (!getBoolean(data.success)) {
			throw new Error(getString(data.error) || "Hashtag search failed");
		}

		return {
			hashtag: (getObject(data.hashtag) as IGHashtagResult | undefined) || null,
		};
	}

	/**
	 * Get top media for an Instagram hashtag
	 */
	async getInstagramHashtagTopMedia(
		hashtagId: string,
		accountId: string,
	): Promise<{ media: IGMediaItem[] }> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/instagram/hashtags?action=top-media", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify({ accountId, hashtagId }),
		});

		const data = await safeJsonParse(response);
		if (!getBoolean(data.success)) {
			throw new Error(getString(data.error) || "Failed to get top media");
		}

		return { media: getArray<IGMediaItem>(data.media) };
	}

	/**
	 * Get recent media for an Instagram hashtag
	 */
	async getInstagramHashtagRecentMedia(
		hashtagId: string,
		accountId: string,
	): Promise<{ media: IGMediaItem[] }> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch(
			"/api/instagram/hashtags?action=recent-media",
			{
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${session.access_token}`,
				},
				body: JSON.stringify({ accountId, hashtagId }),
			},
		);

		const data = await safeJsonParse(response);
		if (!getBoolean(data.success)) {
			throw new Error(getString(data.error) || "Failed to get recent media");
		}

		return { media: getArray<IGMediaItem>(data.media) };
	}

	// --------------------------------------------------------------------------
	// Alert Toggle
	// --------------------------------------------------------------------------

	/**
	 * Toggle alerts on/off for a saved search
	 */
	async toggleSearchAlerts(
		searchId: string,
		alertsEnabled: boolean,
	): Promise<void> {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session) throw new Error("Not authenticated");

		const response = await fetch("/api/discover?action=update-search", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify({ searchId, alertsEnabled }),
		});

		const data = await safeJsonParse(response);
		if (!getBoolean(data.success)) {
			throw new Error(
				getString(data.error) || "Failed to update search alerts",
			);
		}
	}

	// --------------------------------------------------------------------------
	// Private Helpers
	// --------------------------------------------------------------------------

	private parseSearchFromSupabase(row: SavedSearchRow): SavedSearch {
		return {
			id: row.id,
			name: row.name,
			query: row.query,
			searchMode: row.search_mode || "KEYWORD",
			searchType: row.search_type || "RECENT",
			mediaType: row.media_type || undefined,
			lastVolume: row.last_volume || 0,
			volumeChange: row.volume_change || 0,
			volumeChangePercent: getNumber(row.volume_change_percent),
			lastRefreshedAt: row.last_refreshed_at
				? new Date(row.last_refreshed_at)
				: undefined,
			alertsEnabled: row.alerts_enabled || false,
			alertThreshold: row.alert_threshold || 100,
			createdAt: new Date(row.created_at),
			updatedAt: new Date(row.updated_at),
		};
	}
}

// Export singleton instance
export const discoverService = new DiscoverService();
