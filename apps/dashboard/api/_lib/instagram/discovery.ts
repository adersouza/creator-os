/**
 * Instagram Discovery — business discovery and hashtag search/media retrieval.
 * Facebook Login only features.
 */

import {
	decrypt,
	getGraphBaseUrl,
	type IGMediaItem,
	igFetch,
	logger,
} from "./shared.js";

// ============================================================================
// Business Discovery
// ============================================================================

/**
 * Business Discovery — Facebook Login only.
 * Requires instagram_basic + pages_read_engagement (old API scopes).
 */
export async function getBusinessDiscovery(
	encryptedToken: string,
	igUserId: string,
	_targetUsername: string,
	mediaLimit: number = 12,
	loginType?: string,
): Promise<{
	success: boolean;
	profile?: Record<string, unknown> | undefined;
	error?: string | undefined;
}> {
	try {
		if (loginType === "instagram") {
			return {
				success: false,
				error: "Business Discovery requires Facebook Login",
			};
		}
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const fields = `business_discovery.fields(username,name,biography,followers_count,media_count,profile_picture_url,website,media.limit(${mediaLimit}){id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count,views,view_count,total_like_count,total_comments_count,total_views_count})`;
		const url = `${graphBase}/v25.0/${igUserId}?fields=${encodeURIComponent(fields)}`;

		const response = await igFetch(
			url,
			undefined,
			"igApi:businessDiscovery",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Business discovery failed",
			};
		}

		return { success: true, profile: data.business_discovery };
	} catch (error: unknown) {
		logger.error("IG getBusinessDiscovery error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

// ============================================================================
// Hashtag Search (Facebook Login only)
// ============================================================================

/**
 * Search for a hashtag ID by name.
 * GET /ig_hashtag_search?user_id={ig-user-id}&q={hashtag-name}
 * Requires: instagram_basic permission (Facebook Login only).
 * Rate limit: 30 searches per 7-day rolling window.
 */
export async function searchHashtag(
	encryptedToken: string,
	igUserId: string,
	hashtagName: string,
	loginType?: string,
): Promise<{ success: boolean; hashtagId?: string | undefined; error?: string | undefined }> {
	try {
		if (loginType === "instagram") {
			return {
				success: false,
				error: "Hashtag search requires Facebook Login",
			};
		}
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const cleanName = hashtagName.replace(/^#/, "").trim().toLowerCase();

		const url = `${graphBase}/v25.0/ig_hashtag_search?user_id=${igUserId}&q=${encodeURIComponent(cleanName)}`;
		const response = await igFetch(
			url,
			undefined,
			"igApi:searchHashtag",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Hashtag search failed",
			};
		}

		const hashtagId = data.data?.[0]?.id;
		if (!hashtagId) {
			return {
				success: false,
				error: `No results found for hashtag "${cleanName}"`,
			};
		}

		return { success: true, hashtagId };
	} catch (error: unknown) {
		logger.error("IG searchHashtag error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

/**
 * Get top media for a hashtag.
 * GET /{hashtag-id}/top_media?user_id={ig-user-id}&fields=...
 * Requires: instagram_basic permission (Facebook Login only).
 */
export async function getHashtagTopMedia(
	encryptedToken: string,
	hashtagId: string,
	igUserId: string,
	limit: number = 25,
	loginType?: string,
): Promise<{ success: boolean; media?: IGMediaItem[] | undefined; error?: string | undefined }> {
	try {
		if (loginType === "instagram") {
			return { success: false, error: "Hashtag media requires Facebook Login" };
		}
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const fields =
			"id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count";
		const url = `${graphBase}/v25.0/${hashtagId}/top_media?user_id=${igUserId}&fields=${fields}&limit=${limit}`;

		const response = await igFetch(
			url,
			undefined,
			"igApi:hashtagTopMedia",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to fetch top media",
			};
		}

		return { success: true, media: data.data || [] };
	} catch (error: unknown) {
		logger.error("IG getHashtagTopMedia error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}

/**
 * Get recent media for a hashtag.
 * GET /{hashtag-id}/recent_media?user_id={ig-user-id}&fields=...
 * Requires: instagram_basic permission (Facebook Login only).
 */
export async function getHashtagRecentMedia(
	encryptedToken: string,
	hashtagId: string,
	igUserId: string,
	limit: number = 25,
	loginType?: string,
): Promise<{ success: boolean; media?: IGMediaItem[] | undefined; error?: string | undefined }> {
	try {
		if (loginType === "instagram") {
			return { success: false, error: "Hashtag media requires Facebook Login" };
		}
		const graphBase = getGraphBaseUrl(loginType);
		const token = decrypt(encryptedToken);
		const fields =
			"id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count";
		const url = `${graphBase}/v25.0/${hashtagId}/recent_media?user_id=${igUserId}&fields=${fields}&limit=${limit}`;

		const response = await igFetch(
			url,
			undefined,
			"igApi:hashtagRecentMedia",
			token,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			return {
				success: false,
				error: data.error?.message || "Failed to fetch recent media",
			};
		}

		return { success: true, media: data.data || [] };
	} catch (error: unknown) {
		logger.error("IG getHashtagRecentMedia error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : "Unknown error",
		};
	}
}
