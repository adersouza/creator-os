// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Shared interfaces, constants, and utility functions for post handlers.
 */

import type { VercelResponse } from "@vercel/node";
import { checkMediaUrlAccessible } from "../../cron/scheduled-posts/mediaValidation.js";
import { logger } from "../../logger.js";
import { validateUrlNotPrivate } from "../../ssrfProtection.js";
import { getSupabase } from "../../supabase.js";

// ============================================================================
// Database helper
// ============================================================================

export const db = () => getSupabase();

// ============================================================================
// Shared interfaces for typed Supabase / API results
// ============================================================================

export interface ProfileRow {
	subscription_tier: string | null;
	extra_accounts?: number | null | undefined;
}

export interface AccountIdRow {
	id: string;
}

export interface AccountRow {
	id: string;
	user_id: string;
	threads_user_id: string;
	username: string;
	threads_access_token_encrypted: string;
}

export interface IgAccountRow {
	id: string;
	user_id: string;
	instagram_user_id: string;
	username: string;
	instagram_access_token_encrypted: string;
	facebook_page_access_token_encrypted?: string | null | undefined;
	login_type?: string | null | undefined;
	follower_count?: number | null | undefined;
}

export interface IgAccountTokenRow {
	instagram_access_token_encrypted: string;
	login_type?: string | null | undefined;
}

export interface ThreadsAccountTokenRow {
	threads_access_token_encrypted: string;
}

export interface PostRow {
	id: string;
	user_id: string;
	account_id: string | null;
	instagram_account_id: string | null;
	threads_post_id: string | null;
	instagram_post_id: string | null;
	platform: string;
	status: string;
}

export interface PostWithAccountsRow {
	id: string;
	threads_post_id: string | null;
	account_id: string;
	accounts: {
		id: string;
		threads_access_token_encrypted: string;
	} | null;
}

export interface MediaItem {
	type: string;
	url: string;
}

export interface LocationItem {
	id: string;
	name: string;
}

export interface ThreadsApiPostItem {
	id: string;
	text?: string | undefined;
	username?: string | undefined;
	media_url?: string | undefined;
	media_type?: string | undefined;
	timestamp?: string | undefined;
	permalink?: string | undefined;
}

export interface PostInsertData {
	user_id: string;
	content: string;
	status: string;
	platform: string;
	media_urls: string[];
	media_type: string;
	scheduled_for: string | null;
	account_id?: string | null;
	instagram_account_id?: string | null;
	hashtags?: string[];
}

export interface PostUpdateData {
	approval_status: string;
	approved_by?: string | null;
	approved_at?: string | null;
	rejected_by?: string | null;
	rejected_at?: string | null;
	approval_notes?: string | null;
	status?: string;
	scheduled_for?: string | null;
}

export interface PostPublishUpdateData {
	status: string;
	scheduled_for: null;
	instagram_post_id?: string | undefined;
	threads_post_id?: string | undefined;
	permalink?: string | null | undefined;
	published_at: string;
	updated_at: string;
	ig_impressions?: number | undefined;
	ig_reach?: number | undefined;
	ig_saved?: number | undefined;
	ig_shares?: number | undefined;
	likes_count?: number | undefined;
	replies_count?: number | undefined;
	ig_plays?: number | undefined;
	ig_video_views?: number | undefined;
	ig_replays?: number | undefined;
	ig_skip_rate?: number | undefined;
	engagement_rate?: number | undefined;
}

export interface OwnedPostRow {
	id: string;
}

const CANONICAL_POST_MEDIA_TYPE_MAP: Record<string, string> = {
	text: "text",
	text_post: "text",
	image: "image",
	video: "video",
	carousel: "carousel",
	carousel_album: "carousel",
	reel: "reel",
	reels: "reel",
	story: "story",
	stories: "story",
};

/**
 * Normalize app/platform media labels to the lowercase values enforced by
 * posts.media_type.
 */
export function normalizePostMediaType(
	mediaType: string | null | undefined,
	fallback = "text",
): string {
	const normalizedFallback =
		CANONICAL_POST_MEDIA_TYPE_MAP[fallback.trim().toLowerCase()] || "text";
	if (!mediaType) return normalizedFallback;

	const canonical =
		CANONICAL_POST_MEDIA_TYPE_MAP[mediaType.trim().toLowerCase()];
	return canonical || normalizedFallback;
}

// ============================================================================
// Subscription Tier Daily Post Limits
// ============================================================================

export const TIER_DAILY_POST_LIMITS: Record<string, number> = {
	free: 3,
	pro: 50,
	agency: 200,
	empire: Infinity, // unlimited
};

export type PostLimitCheckMode = "publish" | "schedule";

export interface PostLimitCheckOptions {
	/** UTC day to check. Defaults to the current UTC day. */
	targetDate?: Date | string | undefined;
	/** Publish mode counts already-published rows; schedule mode reserves scheduled/publishing rows too. */
	mode?: PostLimitCheckMode | undefined;
	/** Extra rows the caller is about to create/publish. */
	additionalCount?: number | undefined;
}

function utcDayRange(targetDate?: Date | string): {
	startIso: string;
	endIso: string;
} {
	const date =
		targetDate instanceof Date
			? new Date(targetDate)
			: targetDate
				? new Date(targetDate)
				: new Date();
	date.setUTCHours(0, 0, 0, 0);
	const end = new Date(date);
	end.setUTCDate(end.getUTCDate() + 1);
	return { startIso: date.toISOString(), endIso: end.toISOString() };
}

async function countUserPostsForDay(params: {
	userId: string;
	startIso: string;
	endIso: string;
	mode: PostLimitCheckMode;
}): Promise<number> {
	const { userId, startIso, endIso, mode } = params;
	const publishedQuery = db()
		.from("posts")
		.select("*", { count: "exact", head: true })
		.eq("user_id", userId)
		.eq("status", "published")
		.gte("published_at", startIso)
		.lt("published_at", endIso);
	const { count: publishedAtCount, error: publishedAtCountError } =
		await publishedQuery;
	if (publishedAtCountError) {
		logger.error("Failed to count daily posts by published_at for tier check", {
			userId,
			error: String(publishedAtCountError),
		});
		throw new Error("Failed to count daily posts for tier check");
	}

	const legacyQuery = db()
		.from("posts")
		.select("*", { count: "exact", head: true })
		.eq("user_id", userId)
		.eq("status", "published")
		.is("published_at", null)
		.gte("created_at", startIso)
		.lt("created_at", endIso);
	const { count: legacyCount, error: legacyCountError } = await legacyQuery;
	if (legacyCountError) {
		logger.error("Failed to count legacy daily posts for tier check", {
			userId,
			error: String(legacyCountError),
		});
		throw new Error("Failed to count legacy daily posts for tier check");
	}

	let scheduledCount = 0;
	if (mode === "schedule") {
		const scheduledQuery = db()
			.from("posts")
			.select("*", { count: "exact", head: true })
			.eq("user_id", userId)
			.in("status", ["scheduled", "publishing"])
			.gte("scheduled_for", startIso)
			.lt("scheduled_for", endIso);
		const { count, error } = await scheduledQuery;
		if (error) {
			logger.error("Failed to count scheduled posts for tier check", {
				userId,
				error: String(error),
			});
			throw new Error("Failed to count scheduled posts for tier check");
		}
		scheduledCount = count || 0;
	}

	return (publishedAtCount || 0) + (legacyCount || 0) + scheduledCount;
}

/**
 * Check if the user has exceeded their daily post limit based on subscription tier.
 * Returns { allowed, tier, used, limit } or throws on DB error.
 */
export async function checkSubscriptionPostLimit(
	userId: string,
	options: PostLimitCheckOptions = {},
): Promise<{
	allowed: boolean;
	tier: string;
	used: number;
	limit: number;
}> {
	// Fetch user profile to get subscription tier
	const { data: profile, error: profileError } = await db()
		.from("profiles")
		.select("subscription_tier")
		.eq("id", userId)
		.maybeSingle();

	if (profileError || !profile) {
		logger.error("Failed to fetch user profile for tier check", {
			userId,
			error: String(profileError),
		});
		throw new Error("Failed to fetch user profile for tier check");
	}

	const tier = (
		(profile as ProfileRow).subscription_tier || "free"
	).toLowerCase();
	const limit = TIER_DAILY_POST_LIMITS[tier] ?? TIER_DAILY_POST_LIMITS.free;

	// Empire tier has no limit
	if (limit === Infinity) {
		return { allowed: true, tier, used: 0, limit };
	}

	const { startIso, endIso } = utcDayRange(options.targetDate);
	const used = await countUserPostsForDay({
		userId,
		startIso,
		endIso,
		mode: options.mode || "publish",
	});
	const projected = used + Math.max(0, options.additionalCount || 0);
	return { allowed: projected <= limit!, tier, used, limit: limit! };
}

// ============================================================================
// Rate Limit Header Utility
// ============================================================================

/**
 * Set X-RateLimit-* headers on the response.
 * Call after a successful rate limit check so the frontend can display remaining quota.
 */
export function setRateLimitHeaders(
	res: VercelResponse,
	dailyLimit: number,
	dailyUsed: number,
): void {
	// Compute next midnight UTC as the reset timestamp
	const now = new Date();
	const midnightUtc = new Date(
		Date.UTC(
			now.getUTCFullYear(),
			now.getUTCMonth(),
			now.getUTCDate() + 1,
			0,
			0,
			0,
		),
	);
	const resetEpoch = Math.floor(midnightUtc.getTime() / 1000);

	res.setHeader("X-RateLimit-Limit", String(dailyLimit));
	res.setHeader(
		"X-RateLimit-Remaining",
		String(Math.max(0, dailyLimit - dailyUsed)),
	);
	res.setHeader("X-RateLimit-Reset", String(resetEpoch));
}

// ============================================================================
// Hashtag Extraction Utility
// ============================================================================

/**
 * Resolve media library UUIDs to publicly accessible URLs.
 * Falls back to signed storage URLs when no public URL exists.
 * Returns both a flat URL array (for cron paths) and typed MediaItem array (for publish handler).
 */
export async function resolveMediaUrls(
	mediaIds: string[],
	userId: string,
): Promise<{ urls: string[]; items: MediaItem[] }> {
	const { data: mediaRows } = await db()
		.from("media")
		.select("id, url, storage_url, storage_path, mime_type")
		.in("id", mediaIds)
		.eq("user_id", userId);

	const urls: string[] = [];
	const items: MediaItem[] = [];

	if (mediaRows?.length) {
		for (const row of mediaRows as {
			id: string;
			url: string | null;
			storage_url: string | null;
			storage_path: string | null;
			mime_type: string | null;
		}[]) {
			let mediaUrl = row.url || row.storage_url;
			if (!mediaUrl && row.storage_path) {
				// Videos need longer TTL — Meta's processing can take minutes for transcoding
				const isVideo = (row.mime_type || "").startsWith("video/");
				const ttlSeconds = isVideo ? 14400 : 3600; // 4 hours for video, 1 hour for images
				const { data: signedData } = await db()
					.storage.from("media")
					.createSignedUrl(row.storage_path, ttlSeconds);
				mediaUrl = signedData?.signedUrl ?? null;
			}
			if (mediaUrl) {
				const mimeType = row.mime_type || "";
				urls.push(mediaUrl);
				items.push({
					type: mimeType.startsWith("video/") ? "video" : "image",
					url: mediaUrl,
				});
			}
		}
	}

	return { urls, items };
}

function appStoragePathFromUrl(url: string): string | null {
	try {
		const parsed = new URL(url);
		if (parsed.protocol !== "https:") return null;
		const configuredHost = process.env.SUPABASE_URL
			? new URL(process.env.SUPABASE_URL).hostname
			: null;
		if (configuredHost && parsed.hostname !== configuredHost) return null;
		const marker = "/storage/v1/object/";
		const markerIndex = parsed.pathname.indexOf(marker);
		if (markerIndex < 0) return null;
		const objectPath = parsed.pathname.slice(markerIndex + marker.length);
		const withoutVisibility = objectPath.replace(/^(public|sign)\//, "");
		if (!withoutVisibility.startsWith("media/")) return null;
		return decodeURIComponent(withoutVisibility.slice("media/".length));
	} catch {
		return null;
	}
}

async function rawAppStorageUrlIsOwned(
	userId: string,
	url: string,
): Promise<boolean> {
	const storagePath = appStoragePathFromUrl(url);
	if (!storagePath) return false;

	const byUrl = await db()
		.from("media")
		.select("id")
		.eq("user_id", userId)
		.eq("url", url)
		.limit(1)
		.maybeSingle();
	if (byUrl.data?.id) return true;

	const byStorageUrl = await db()
		.from("media")
		.select("id")
		.eq("user_id", userId)
		.eq("storage_url", url)
		.limit(1)
		.maybeSingle();
	if (byStorageUrl.data?.id) return true;

	const byPath = await db()
		.from("media")
		.select("id")
		.eq("user_id", userId)
		.eq("storage_path", storagePath)
		.limit(1)
		.maybeSingle();
	return !!byPath.data?.id;
}

export async function validateRawMediaItemsForUser(
	userId: string,
	mediaItems: Array<{ url?: string | undefined; type?: string | undefined }> | undefined,
): Promise<string | null> {
	if (!mediaItems?.length) return null;

	for (const item of mediaItems) {
		if (!item.url) continue;
		let parsed: URL;
		try {
			parsed = new URL(item.url);
		} catch {
			return "Media URL is invalid";
		}
		if (parsed.protocol !== "https:") {
			return "Media URL must use HTTPS";
		}

		const appStoragePath = appStoragePathFromUrl(item.url);
		if (appStoragePath) {
			if (!(await rawAppStorageUrlIsOwned(userId, item.url))) {
				return "App storage media URL is not owned by this account. Use mediaIds from the media library.";
			}
			continue;
		}

		const ssrfError = await validateUrlNotPrivate(item.url);
		if (ssrfError) return ssrfError;

		const mediaError = await checkMediaUrlAccessible([item.url]);
		if (mediaError) return mediaError;
	}

	return null;
}

/**
 * Extract hashtags from content text
 * Returns array of hashtags without the # symbol (e.g., ["travel", "photography"])
 */
export function extractHashtags(content: string): string[] {
	if (!content) return [];
	// Match hashtags: # followed by letters, numbers, underscores, or non-ASCII characters
	const hashtagRegex = /#([\w\u00C0-\u024F\u1E00-\u1EFF]+)/g;
	const matches = content.match(hashtagRegex);
	if (!matches) return [];

	// Remove # and deduplicate (case-insensitive)
	const seen = new Set<string>();
	const hashtags: string[] = [];
	for (const match of matches) {
		const tag = match.slice(1).toLowerCase();
		if (tag && !seen.has(tag)) {
			seen.add(tag);
			hashtags.push(tag);
		}
	}
	return hashtags;
}
