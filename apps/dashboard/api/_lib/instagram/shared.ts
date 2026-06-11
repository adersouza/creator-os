// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Shared types, interfaces, constants, and utilities used across all Instagram API sub-modules.
 * Contains error handling, the retried fetch wrapper, and the Graph API base URL resolver.
 */

import { decrypt } from "../encryption.js";
import { logger } from "../logger.js";
import { type ClassifiedError, classifyMetaError } from "../metaErrors.js";
import { withRetry } from "../retryUtils.js";

import type { BatchRequest, BatchResponse } from "../types.js";

export type { BatchRequest, BatchResponse };
// Re-export for sub-modules that need these
export { decrypt, logger, withRetry };

// ============================================================================
// Internal Types for API responses
// ============================================================================

/** A carousel child item with its insight metrics */
export interface IGCarouselChild {
	id: string;
	mediaType?: string | undefined;
	mediaUrl?: string | undefined;
	position: number;
	metrics: {
		impressions: number;
		reach: number;
		likes: number;
		comments: number;
		shares: number;
		saved: number;
	};
}

/** Raw carousel child data from the Graph API children edge */
export interface IGCarouselChildRaw {
	id: string;
	media_type?: string | undefined;
	media_url?: string | undefined;
	timestamp?: string | undefined;
}

/** Generic IG media item returned by the Graph API */
export interface IGMediaItem {
	id: string;
	caption?: string | undefined;
	media_type?: string | undefined;
	/** MUSIC for licensed catalog tracks, ORIGINAL_SOUND for original audio. */
	media_audio_type?: "MUSIC" | "ORIGINAL_SOUND" | string | undefined;
	/**
	 * Media surface bucket: "FEED" | "REELS" | "STORY" | "AD".
	 * media_type alone returns "VIDEO" for both Reels and feed videos —
	 * media_product_type is the only authoritative way to flag a Reel,
	 * and downstream insight selection (REEL_INSIGHT_METRICS vs
	 * POST_INSIGHT_METRICS) depends on it.
	 */
	media_product_type?: string | undefined;
	media_url?: string | undefined;
	permalink?: string | undefined;
	timestamp?: string | undefined;
	thumbnail_url?: string | undefined;
	like_count?: number | undefined;
	comments_count?: number | undefined;
	username?: string | undefined;
	children?: {
        		data: Array<{
        			id: string;
        			media_type?: string | undefined;
        			media_url?: string | undefined;
        			timestamp?: string | undefined;
        		}>;
        	} | undefined;
	views?: number | undefined;
	view_count?: number | undefined;
	reposts_count?: number | undefined;
	saved_count?: number | undefined;
	shares_count?: number | undefined;
	total_like_count?: number | undefined;
	total_comments_count?: number | undefined;
	total_views_count?: number | undefined;
}

/** Paging cursor from Graph API pagination */
export interface IGPaging {
	cursors?: { before?: string | undefined; after?: string | undefined } | undefined;
	next?: string | undefined;
}

/** IG comment returned from the comments edge */
export interface IGComment {
	id: string;
	text?: string | undefined;
	username?: string | undefined;
	timestamp?: string | undefined;
	like_count?: number | undefined;
	parent_id?: string | undefined;
	from?: { id: string; username: string } | undefined;
	replies?: { data: IGComment[] } | undefined;
	hidden?: boolean | undefined;
}

/** IG conversation returned from the conversations edge */
export interface IGConversation {
	id: string;
	participants?: { data: Array<{ id: string; username?: string | undefined }> } | undefined;
	messages?: { data: Array<IGMessage> } | undefined;
	updated_time?: string | undefined;
}

/** IG message returned from the messages edge */
export interface IGMessage {
	id: string;
	message?: string | undefined;
	created_time?: string | undefined;
	from?: { id: string; username?: string | undefined } | undefined;
	to?: { data: Array<{ id: string; username?: string | undefined }> } | undefined;
	is_unsupported?: boolean | undefined;
}

/** Welcome message flow item */
export interface IGWelcomeFlow {
	id?: string | undefined;
	flow_id?: string | undefined;
	[key: string]: unknown;
}

// ============================================================================
// Error Handling
// ============================================================================

export class IGApiError extends Error {
	code: string;
	userMessage: string;
	retryable: boolean;

	constructor(
		code: string,
		message: string,
		userMessage: string,
		retryable: boolean = false,
	) {
		super(message);
		this.name = "IGApiError";
		this.code = code;
		this.userMessage = userMessage;
		this.retryable = retryable;
	}
}

const ERROR_MAP: Record<string, { userMessage: string; retryable: boolean }> = {
	// OAuthException REMOVED from here — subcodes 463/467 in SUBCODE_MAP handle
	// real session expiry. All other OAuthExceptions are Meta transient 500s
	// and should fall through to the default retryable handler.
	"(#100)": {
		userMessage:
			"Invalid content. Check your post meets Instagram's guidelines.",
		retryable: false,
	},
	"(#9004)": {
		userMessage:
			"Media could not be fetched from the provided URL. Check the link and try again.",
		retryable: false,
	},
	"(#36000)": {
		userMessage:
			"Media processing failed. The file may be corrupted or unsupported.",
		retryable: false,
	},
	MEDIA_CREATION_ERROR: {
		userMessage:
			"Failed to create post. The media may be unsupported or too large.",
		retryable: false,
	},
	"Invalid collaborator": {
		userMessage:
			"Invalid collaborator username. Please check the username and try again.",
		retryable: false,
	},
	collaborator_usernames: {
		userMessage:
			"One or more collaborator usernames are invalid. Max 3 collaborators allowed.",
		retryable: false,
	},
};

// Subcode-specific error mappings (per Meta docs)
const SUBCODE_MAP: Record<number, { userMessage: string; retryable: boolean }> =
	{
		2207042: {
			userMessage:
				"You've reached the daily publishing limit. Try again tomorrow.",
			retryable: false,
		},
		2207027: {
			userMessage: "Media is still processing. Please wait and try again.",
			retryable: true,
		},
		2207008: {
			userMessage: "A temporary error occurred. Please try again.",
			retryable: true,
		},
		2207050: {
			userMessage:
				"Your account is restricted. Check your Instagram account status.",
			retryable: false,
		},
		2207051: {
			userMessage:
				"This action was flagged as spam. Please review your content.",
			retryable: false,
		},
		2207052: {
			userMessage:
				"Media could not be fetched from the provided URL. Check the link.",
			retryable: false,
		},
		463: {
			userMessage:
				"Your Instagram session has expired. Please reconnect your account.",
			retryable: false,
		},
		467: {
			userMessage:
				"Your Instagram access token is invalid. Please reconnect your account.",
			retryable: false,
		},
		2207026: {
			userMessage: "Media is still processing. Please wait and try again.",
			retryable: true,
		},
	};

export function mapIGError(apiError: {
	message?: string | undefined;
	type?: string | undefined;
	code?: number | undefined;
	error_subcode?: number | undefined;
}): IGApiError {
	const rawMessage = apiError.message || "Unknown Instagram API error";
	const errorType = apiError.type || "";

	// Check error_subcode first (most specific)
	if (apiError.error_subcode && SUBCODE_MAP[apiError.error_subcode]) {
		const mapping = SUBCODE_MAP[apiError.error_subcode];
		return new IGApiError(
			String(apiError.error_subcode),
			rawMessage,
			mapping!.userMessage,
			mapping!.retryable,
		);
	}

	// Check error map for known patterns
	for (const [pattern, mapping] of Object.entries(ERROR_MAP)) {
		if (rawMessage.includes(pattern) || errorType.includes(pattern)) {
			return new IGApiError(
				pattern,
				rawMessage,
				mapping.userMessage,
				mapping.retryable,
			);
		}
	}

	// Log unmapped errors so we can add them to ERROR_MAP/SUBCODE_MAP
	logger.warn("[mapIGError] Unmapped IG error — falling back to generic", {
		code: apiError.code,
		subcode: apiError.error_subcode,
		type: apiError.type,
		message: rawMessage.substring(0, 300),
	});

	return new IGApiError(
		String(apiError.code || "UNKNOWN"),
		rawMessage,
		"An unexpected Instagram error occurred. Please try again.",
		true,
	);
}

// ============================================================================
// Types
// ============================================================================

// TODO: Missing features available in Meta API that we could implement:
// - Trial Reels publishing (DONE - media_type=REELS with trial_params, Feb 2025)
// - Resumable video uploads (DONE - ruploadService.ts, auto-triggers for videos > 50MB)
// - Alt text for images (DONE - supported via alt_text param, March 2025)
// - Copyright detection for videos (GET /{container_id}?fields=copyright_check_status)
// - Upcoming Events (Facebook Login only - POST /{ig_user_id}/upcoming_events)
// - Creator Marketplace API (Facebook Login only)
// - Business Discovery (Facebook Login only - already implemented)
// - Product Tagging (Facebook Login only)
// - Disable/enable comments on media (DONE - toggleCommentEnabled, Feb 2025)
// - Private replies to comments (DONE - sendPrivateReply, Feb 2025)
//
// Threads API missing features:
// - Topic tags for posts (topic_tag parameter)
// - GIF attachments (gif_attachment with Tenor GIF ID)
// - Spoiler content (is_spoiler_media, text_entities with SPOILER type)
// - Geo-gated content (allowlisted_country_codes)
// - Text attachments / long-form content (text_attachment up to 10K chars)
// - Polls (poll_attachment)
// - Ghost posts
// - Location tagging (location_id from /location_search)
// - Profile discovery (GET /profile_lookup, GET /profile_posts)
// - Keyword/topic search (GET /keyword_search with search_mode=TAG)
// - Post deletion (DELETE /{media_id}, 100 deletes/day)

export type IGMediaType = "IMAGE" | "VIDEO" | "REELS" | "CAROUSEL" | "STORIES";

const IG_MEDIA_TYPE_ALIASES: Record<string, IGMediaType> = {
	IMAGE: "IMAGE",
	PHOTO: "IMAGE",
	VIDEO: "VIDEO",
	REEL: "REELS",
	REELS: "REELS",
	CAROUSEL: "CAROUSEL",
	CAROUSEL_ALBUM: "CAROUSEL",
	STORY: "STORIES",
	STORIES: "STORIES",
};

export function normalizeIGMediaType(
	input: string | null | undefined,
): IGMediaType | null {
	if (!input) return null;
	return IG_MEDIA_TYPE_ALIASES[input.trim().toUpperCase()] || null;
}

export interface IGPostData {
	caption: string;
	mediaType: IGMediaType;
	imageUrl?: string | undefined;
	videoUrl?: string | undefined;
	coverUrl?: string | undefined; // Cover image for Reels
	altText?: string | undefined; // Accessibility alt text for images
	children?: { type: "image" | "video"; url: string; altText?: string | undefined }[] | undefined; // Carousel items (max 10)
	useFacebookToken?: boolean | undefined; // Use Facebook Page token (required for Stories)
	locationId?: string | undefined; // Facebook Places location ID
	collaborators?: string[] | undefined; // Up to 3 Instagram usernames to invite as collaborators
	trialReels?: boolean | undefined; // Publish as Trial Reel (non-followers first)
	trialGraduationStrategy?: "MANUAL" | "SS_PERFORMANCE" | undefined; // Trial Reel graduation strategy
	shareToFeed?: boolean | undefined; // Reels only: true = Feed + Reels tabs, false = Reels tab only
	userTags?: Array<{ username: string; x: number; y: number }> | undefined; // Tag users in images (x,y: 0-1 coordinates)
	useResumableUpload?: boolean | undefined; // Force resumable upload (auto-detected for videos > 50MB)
	duration?: number | undefined; // Video duration in seconds (used for validation)
	thumbOffset?: number | undefined; // Video/Reels: millisecond offset for cover thumbnail (default 0)
	audioName?: string | undefined; // Reels only: name the audio track (can only be renamed once)
	igAudioId?: string | undefined; // Reels only: Meta-native audio selected through /ig_audio
	productTags?: Array<{ product_id: string; x?: number | undefined; y?: number | undefined }> | undefined; // Shopping: tag products (max 5, x/y for images)
	commentEnabled?: boolean | undefined; // Toggle comments on/off after publish (default: enabled)
	firstComment?: string | undefined; // Optional first comment to add immediately after publish
	brandedContentSponsorIds?: string[] | undefined; // Paid partnership brand partner IG user IDs (max 2)
	isPaidPartnership?: boolean | undefined; // Adds paid partnership disclosure label
}

export interface IGPostingResult {
	success: boolean;
	mediaId?: string | undefined;
	containerId?: string | undefined; // Returned when container created but still processing
	permalink?: string | undefined;
	error?: string | undefined;
	retryable?: boolean | undefined;
	timestamp: Date;
}

export interface IGPostMetrics {
	metricContractVersion?: string | undefined;
	metricSurface?: string | undefined;
	metricFallbackUsed?: boolean | undefined;
	metricNames?: string[] | undefined;
	views: number; // v21+ primary metric (replaces impressions)
	/** @deprecated Deprecated in v22+, replaced by `views`. Kept for backwards compatibility — will be 0. */
	impressions: number;
	reach: number;
	likes: number;
	comments: number;
	shares: number;
	saved: number;
	engagementRate: number;
	/** @deprecated Deprecated in Meta API. Kept for backwards compatibility — will be 0. */
	plays: number;
	/** @deprecated Deprecated, replaced by `views`. Kept for backwards compatibility — will be 0. */
	video_views: number;
	facebook_views: number;
	reposts: number;
	total_likes: number;
	total_comments: number;
	total_views: number;
	reels_skip_rate: number;
	crossposted_views: number;
	ig_reels_avg_watch_time: number;
	ig_reels_video_view_total_time: number;
	clips_replays_count: number;
	ig_reels_aggregated_all_plays_count: number;
	/** Post-attributed follows — native field from /media/insights (requires `follows` in metric list). */
	follows: number;
	profileActivity?: { action_type: string; value: number }[] | undefined;
	/** Profile visits attributed to this post — derived from the profile_activity action_type breakdown. */
	profile_visits?: number | undefined;
}

export interface IGAccountInsights {
	reach: number;
	views: number; // v21+ primary metric (replaces deprecated impressions)
	followerCount: number;
	accountsEngaged: number;
	totalInteractions: number;
	profileLinksTaps: number; // v21+ replaces deprecated website_clicks
	reposts: number;
	// Deprecated fields kept for backwards compatibility
	impressions: number;
	profileViews: number;
	websiteClicks: number;
	emailContacts: number;
	// Optional breakdown fields (populated by extended insight calls)
	nonFollowerReachPct?: number | undefined;
	followerReach?: number | undefined;
	nonFollowerReach?: number | undefined;
	newFollows?: number | undefined;
	unfollows?: number | undefined;
	contentTypeBreakdown?: {
        		feed?: Record<string, number> | undefined;
        		reels?: Record<string, number> | undefined;
        		story?: Record<string, number> | undefined;
        	} | undefined;
}

export type ContainerStatus =
	| "FINISHED"
	| "IN_PROGRESS"
	| "TIMED_OUT"
	| "ERROR"
	| "EXPIRED"
	| "PUBLISHED";

/**
 * Returns the Graph API base URL based on login type.
 *
 * There are TWO valid ways to access Instagram Graph API:
 *
 * 1. Instagram Business Login (loginType="instagram"):
 *    - Uses graph.instagram.com
 *    - Direct Instagram OAuth, no Facebook Page required
 *    - For Business/Creator accounts authenticating directly
 *
 * 2. Facebook Login (loginType="facebook"):
 *    - Uses graph.facebook.com
 *    - Requires Instagram account linked to Facebook Page
 *    - More features (hashtag search, product tagging, etc.)
 *
 * NOTE: The deprecated API was Instagram Basic Display API (api.instagram.com)
 * for PERSONAL accounts. The Business Login at graph.instagram.com still works.
 */
export function getGraphBaseUrl(loginType?: string): string {
	// Use the correct Graph API base based on authentication method
	const base =
		loginType === "facebook"
			? "https://graph.facebook.com"
			: "https://graph.instagram.com";
	return base;
}

// ============================================================================
// Retried Fetch — wraps all Meta API calls with exponential backoff
// ============================================================================

/**
 * Fetch wrapper that retries transient Meta API errors (rate limits, 500s, timeouts).
 * Drop-in replacement for `fetch()` in this module.
 * When `token` is provided, adds an Authorization: Bearer header (keeps tokens out of URLs).
 */
export async function igFetch(
	url: string | URL,
	init?: RequestInit,
	label = "igApi",
	token?: string,
): Promise<Response> {
	const headers: Record<string, string> = {};
	if (token) headers.Authorization = `Bearer ${token}`;
	const mergedInit: RequestInit = {
		...init,
		signal: init?.signal || AbortSignal.timeout(30_000),
		headers: {
			...headers,
			...((init?.headers as Record<string, string>) || {}),
		},
	};
	const response = await withRetry(() => fetch(url, mergedInit), { label });
	// Apply x-app-usage backpressure on every IG API response.
	// Delays at >=70%, throws MetaRateLimitError at >=95% to abort the current batch.
	const { checkMetaAppUsage } = await import("../metaApiConfig.js");
	await checkMetaAppUsage(response, label);
	const { getSupabaseAny } = await import("../supabase.js");
	const { recordMetaApiUsageSnapshot } = await import("../reliability.js");
	await recordMetaApiUsageSnapshot(getSupabaseAny(), {
		userId: null,
		accountId: null,
		platform: "instagram",
		endpointFamily: label,
		response,
		requestId: response.headers.get("x-fb-trace-id") ?? response.headers.get("x-request-id"),
	});
	return response;
}

/**
 * Retry a Meta API container-creation call inline on transient errors (code 1/2).
 * Meta's "An unexpected error has occurred" resolves in seconds — retrying
 * immediately avoids a 15-minute post reschedule for a momentary blip.
 *
 * Wraps igFetch (which already handles transport retries) and adds
 * application-level retry for HTTP-200-with-error-payload responses.
 */
export async function fetchContainerWithRetry(
	url: string,
	init: RequestInit,
	rateLimitKey: string,
	token: string,
	maxRetries = 2,
): Promise<{
	ok: boolean;
	data: Record<string, unknown>;
	classified?: ClassifiedError | undefined;
}> {
	for (let attempt = 0; attempt <= maxRetries; attempt++) {
		const response = await igFetch(url, init, rateLimitKey, token);
		const data = await response.json();

		if (response.ok && !data.error) {
			return { ok: true, data };
		}

		const classified = data.error
			? classifyMetaError({ ...data.error, httpStatus: response.status })
			: ({
					category: "unknown" as const,
					retryable: true,
					action: "investigate" as const,
					reason: "No error object",
				} as ClassifiedError);

		if (classified.category === "transient" && attempt < maxRetries) {
			const delayMs = (attempt + 1) * 3000; // 3s, 6s
			logger.info("Retrying container creation on transient Meta error", {
				attempt: attempt + 1,
				maxRetries,
				delayMs,
				errorCode: data.error?.code,
			});
			await new Promise((r) => setTimeout(r, delayMs));
			continue;
		}

		return { ok: false, data, classified };
	}

	return {
		ok: false,
		data: {},
		classified: {
			category: "unknown",
			retryable: true,
			action: "investigate",
			reason: "Exhausted retries",
		} as ClassifiedError,
	};
}

// ============================================================================
// Story Types
// ============================================================================

export interface IGStoryMetrics {
	views: number;
	reach: number;
	replies: number;
	navigation: number;
	follows: number;
	shares: number;
	total_interactions: number;
	profile_activity?: { action_type: string; value: number }[] | undefined;
	profile_visits?: number | undefined;
	/** Legacy field — no longer returned by API (v18.0+). Always 0 from new fetches. */
	exits: number;
	/** Legacy field — no longer returned by API (v18.0+). Always 0 from new fetches. */
	taps_forward: number;
	/** Legacy field — no longer returned by API (v18.0+). Always 0 from new fetches. */
	taps_back: number;
}

export interface IGStory {
	id: string;
	media_type: string;
	media_url?: string | undefined;
	timestamp: string;
	permalink?: string | undefined;
	thumbnail_url?: string | undefined;
}

// ============================================================================
// Collaboration Types
// ============================================================================

export interface IGCollaborationInvite {
	media_id: string;
	media_owner_username?: string | undefined;
	caption?: string | undefined;
	media_url?: string | undefined;
}

// ============================================================================
// Demographics Types
// ============================================================================

export interface IGDemographicsBreakdown {
	breakdown_type: string;
	values: { value: string; count: number }[];
}

// ============================================================================
// User Profile Types (messaging context)
// ============================================================================

export interface IGUserProfile {
	name?: string | null | undefined;
	username?: string | undefined;
	profile_pic?: string | null | undefined;
	follower_count?: number | undefined;
	is_user_follow_business?: boolean | undefined;
	is_business_follow_user?: boolean | undefined;
	is_verified_user?: boolean | undefined;
}

// ============================================================================
// Messaging Types
// ============================================================================

export interface QuickReply {
	content_type: string;
	title: string;
	payload: string;
}

export interface TemplateButton {
	type: string;
	title: string;
	url?: string | undefined;
	payload?: string | undefined;
}

export interface TemplateElement {
	title: string;
	subtitle?: string | undefined;
	image_url?: string | undefined;
	default_action?: { type: string; url: string } | undefined;
	buttons?: TemplateButton[] | undefined;
}

export interface ButtonTemplateButton {
	type: string;
	title: string;
	url?: string | undefined;
	payload?: string | undefined;
}

// ============================================================================
// Messenger Profile Types
// ============================================================================

export interface PersistentMenuItem {
	type: string;
	title: string;
	url?: string | undefined;
	payload?: string | undefined;
	webview_height_ratio?: string | undefined;
}

export interface PersistentMenuLocale {
	locale: string;
	composer_input_disabled: boolean;
	call_to_actions: PersistentMenuItem[];
}

export interface IceBreaker {
	question: string;
	payload: string;
}

export interface IceBreakerLocale {
	locale?: string | undefined;
	call_to_actions: IceBreaker[];
}

export interface WelcomeFlowQuickReply {
	content_type: string;
	title: string;
	payload: string;
}
