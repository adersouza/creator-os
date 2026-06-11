/**
 * Zod Validation Schemas for API Request Bodies
 *
 * Usage:
 *   import { parseBodyOrError, PublishPostSchema } from "./_lib/validation.js";
 *   const parsed = parseBodyOrError(res, PublishPostSchema, req.body);
 *   if (!parsed) return;
 *   const { accountId, content, ... } = parsed;
 */

import { extendZodWithOpenApi } from "@asteasolutions/zod-to-openapi";
import { z, zEnum, zRecord, zUnknown } from "./zodCompat.js";
import type { Infer, ZodTypeAny } from "./zodCompat.js";

extendZodWithOpenApi(z);

// ============================================================================
// Helpers
// ============================================================================

import type { VercelResponse } from "@vercel/node";
import { apiError } from "./apiResponse.js";

/**
 * Validate a request body against a Zod schema.
 * Returns { data } on success or { error } on failure.
 */
export function validateBody<T extends ZodTypeAny>(
	schema: T,
	body: unknown,
): { data: Infer<T> } | { error: string } {
	const result = schema.safeParse(body);
	if (!result.success) {
		const messages = result.error.issues
			.map((i) => `${i.path.join(".")}: ${i.message}`)
			.join("; ");
		return { error: messages };
	}
	return { data: result.data };
}

/**
 * Validate request query params against a Zod schema.
 * Returns { data } on success or { error } on failure.
 */
export function validateQuery<T extends ZodTypeAny>(
	schema: T,
	query: unknown,
): { data: Infer<T> } | { error: string } {
	const result = schema.safeParse(query);
	if (!result.success) {
		const messages = result.error.issues
			.map((i) => `${i.path.join(".")}: ${i.message}`)
			.join("; ");
		return { error: messages };
	}
	return { data: result.data };
}

/**
 * Parse request body or send 400 error. Returns parsed data or null.
 * Reduces the 3-line validate-check-destructure pattern to 1 line.
 */
export function parseBodyOrError<T extends ZodTypeAny>(
	res: VercelResponse,
	schema: T,
	body: unknown,
): Infer<T> | null {
	const result = schema.safeParse(body);
	if (!result.success) {
		const messages = result.error.issues
			.map((i) => `${i.path.join(".")}: ${i.message}`)
			.join("; ");
		apiError(res, 400, messages);
		return null;
	}
	return result.data;
}

/**
 * Parse request query or send 400 error. Returns parsed data or null.
 */
export function parseQueryOrError<T extends ZodTypeAny>(
	res: VercelResponse,
	schema: T,
	query: unknown,
): Infer<T> | null {
	const result = schema.safeParse(query);
	if (!result.success) {
		const messages = result.error.issues
			.map((i) => `${i.path.join(".")}: ${i.message}`)
			.join("; ");
		apiError(res, 400, messages);
		return null;
	}
	return result.data;
}

// ============================================================================
// Shared sub-schemas
// ============================================================================

const MediaItemSchema = z.object({
	url: z.string().url(),
	type: z.string().optional(),
	altText: z.string().optional(),
});

const PollAttachmentSchema = z.object({
	options: z.array(z.string()).max(4).optional(),
	option_a: z.string().optional(),
	option_b: z.string().optional(),
	option_c: z.string().optional(),
	option_d: z.string().optional(),
	duration: z.number().optional(),
});

const TextSpoilerEntitySchema = z.object({
	entity_type: zEnum(["SPOILER"]),
	offset: z.number().int().min(0),
	length: z.number().int().min(1),
});

const TextAttachmentSchema = z.object({
	plaintext: z.string().min(1),
	link_attachment_url: z.string().url().optional(),
	text_with_styling_info: z
		.array(
			z.object({
				offset: z.number().int().min(0),
				length: z.number().int().min(1),
				styling_info: z.array(z.string()).max(8),
			}),
		)
		.optional(),
});

const InstagramUserTagSchema = z.object({
	username: z.string(),
	x: z.number().min(0).max(1),
	y: z.number().min(0).max(1),
});

const InstagramProductTagSchema = z.object({
	product_id: z.string(),
	x: z.number().min(0).max(1).optional(),
	y: z.number().min(0).max(1).optional(),
});

const PostSettingsSchema = z.object({
	allowReplies: z.boolean().optional(),
	whoCanReply: z.string().optional(),
});

// ============================================================================
// Posts API Schemas
// ============================================================================

/**
 * Schema for POST /api/posts?action=publish
 * Covers both Threads and Instagram publish paths.
 */
export const PublishPostSchema = z
	.object({
		accountId: z
			.string()
			.openapi({
				description: "Threads account ID (required when platform=threads)",
				example: "17841401234567890",
			})
			.optional(),
		content: z.string().optional().default("").openapi({
			description:
				"Post text. Max 500 chars (Threads) or 2200 chars (Instagram).",
			example: "Hello from the automated pipeline!",
		}),
		media: z
			.array(MediaItemSchema)
			.max(10)
			.openapi({
				description: "Optional media attachments",
			})
			.optional(),
		topics: z
			.array(z.string())
			.max(20)
			.openapi({
				description: "Hashtag topics (Threads)",
			})
			.optional(),
		linkUrl: z
			.string()
			.url()
			.openapi({
				description: "Link attachment URL",
			})
			.optional()
			.nullable(),
		locationId: z
			.string()
			.openapi({
				description: "Location ID for geo-tagging",
			})
			.optional()
			.nullable(),
		quotePostId: z
			.string()
			.openapi({
				description: "Threads post ID to quote",
			})
			.optional()
			.nullable(),
		gifAttachment: z
			.object({ gifId: z.string(), provider: z.string().optional() })
			.optional()
			.nullable(),
		pollAttachment: PollAttachmentSchema.optional().nullable(),
		isSpoiler: z.boolean().optional(),
		isGhostPost: z.boolean().optional(),
		textSpoilers: z.array(TextSpoilerEntitySchema).max(20).optional(),
		allowlistedCountryCodes: z.array(z.string()).max(20).optional(),
		textAttachment: TextAttachmentSchema.optional().nullable(),
		settings: PostSettingsSchema.optional(),
		// Instagram-specific fields
		platform: zEnum(["threads", "instagram"])
			.openapi({
				default: "threads",
			})
			.optional(),
		publishMode: zEnum(["auto", "notify"]).optional(),
		instagramAccountId: z
			.string()
			.openapi({
				description: "Required when platform=instagram",
			})
			.optional(),
		igMediaType: z.string().optional(),
		mediaType: z.string().optional(), // alias for igMediaType (MCP sends this)
		altText: z.string().optional().nullable(),
		collaborators: z.array(z.string()).max(3).optional(),
		replyApprovalMode: z.string().optional(),
		isTrialReel: z.boolean().optional(),
		trialReels: z.boolean().optional(), // alias for isTrialReel (MCP sends this)
		instagramTrialReels: z.boolean().optional(),
		instagram_trial_reels: z.boolean().optional(),
		coverUrl: z.string().optional().nullable(),
		shareToFeed: z.boolean().optional(),
		userTags: z.array(InstagramUserTagSchema).optional(),
		productTags: z.array(InstagramProductTagSchema).max(5).optional(),
		brandedContentSponsorIds: z.array(z.string()).max(2).optional(),
		isPaidPartnership: z.boolean().optional(),
		thumbOffset: z.number().optional(),
		reelCover: z.number().optional(),
		audioName: z.string().optional().nullable(),
		igAudioId: z.string().optional().nullable(),
		commentEnabled: z.boolean().optional(),
		graduation: zEnum(["MANUAL", "SS_PERFORMANCE"]).optional(),
		firstComment: z.string().max(2200).optional().nullable(),
		crossPostGroupId: z.string().optional(),
		crossreshareToIg: z.boolean().optional(),
		crossreshareToIgDarkMode: z.boolean().optional(),
		topicTag: z.string().max(50).optional().nullable(),
		ghostDuration: zEnum(["24h", "48h", "7d"]).optional(),
		mediaIds: z
			.array(z.string())
			.max(10)
			.openapi({
				description:
					"Media library IDs to attach (resolved to URLs server-side). Alternative to media[].",
			})
			.optional(),
		metadata: zRecord(z.string(), zUnknown()).optional(),
	})
	.openapi("PublishPostRequest");

/**
 * Schema for POST /api/posts?action=schedule
 *
 * Mirrors PublishPostSchema but adds scheduledFor + groupId + spoiler flag,
 * since the schedule path inserts a draft/scheduled row instead of publishing
 * to Meta directly. Without this guard, callers can write arbitrary JSONB into
 * posts.metadata via the unvalidated destructure.
 */
export const SchedulePostSchema = z.object({
	accountId: z.string().optional(),
	instagramAccountId: z.string().optional(),
	content: z.string().optional().default(""),
	platform: zEnum(["threads", "instagram"]).optional(),
	publishMode: zEnum(["auto", "notify"]).optional(),
	scheduledFor: z.string().optional().nullable(),
	mediaIds: z.array(z.string()).max(10).optional(),
	media: z.array(MediaItemSchema).max(10).optional(),
	mediaType: z.string().optional(),
	pollOptions: z.array(z.string()).max(4).optional(),
	quotePostId: z.string().optional().nullable(),
	linkUrl: z.string().url().optional().nullable(),
	gifAttachment: z
		.object({ gifId: z.string(), provider: z.string().optional() })
		.optional()
		.nullable(),
	locationId: z.string().optional().nullable(),
	topicTag: z.string().max(50).optional().nullable(),
	textSpoilers: z.array(TextSpoilerEntitySchema).max(20).optional(),
	isSpoilerMedia: z.boolean().optional(),
	crossreshareToIg: z.boolean().optional(),
	crossreshareToIgDarkMode: z.boolean().optional(),
	textAttachment: TextAttachmentSchema.optional().nullable(),
	settings: PostSettingsSchema.optional(),
	groupId: z.string().optional().nullable(),
	altText: z.string().optional().nullable(),
	collaborators: z.array(z.string()).max(3).optional(),
	replyApprovalMode: z.string().optional(),
	isGhostPost: z.boolean().optional(),
	threadChain: z.boolean().optional(),
	replyToId: z.string().optional().nullable(),
	persona: z.string().optional().nullable(),
	coverUrl: z.string().optional().nullable(),
	shareToFeed: z.boolean().optional(),
	userTags: z.array(InstagramUserTagSchema).optional(),
	trialReels: z.boolean().optional(),
	isTrialReel: z.boolean().optional(),
	instagramTrialReels: z.boolean().optional(),
	instagram_trial_reels: z.boolean().optional(),
	thumbOffset: z.number().optional(),
	audioName: z.string().optional().nullable(),
	igAudioId: z.string().optional().nullable(),
	productTags: z.array(InstagramProductTagSchema).max(5).optional(),
	brandedContentSponsorIds: z.array(z.string()).max(2).optional(),
	isPaidPartnership: z.boolean().optional(),
	commentEnabled: z.boolean().optional(),
	graduation: zEnum(["MANUAL", "SS_PERFORMANCE"]).optional(),
	firstComment: z.string().max(2200).optional().nullable(),
	ghostDuration: zEnum(["24h", "48h", "7d"]).optional(),
	metadata: zRecord(z.string(), zUnknown()).optional(),
});

/**
 * Schema for POST /api/posts?action=delete
 */
export const DeletePostSchema = z.object({
	postId: z.string().min(1, "postId is required"),
});

// ============================================================================
// Import Posts Schema
// ============================================================================

const ImportPostItemSchema = z.object({
	content: z.string().min(1, "content is required"),
	scheduled_for: z.string().optional(),
	platform: zEnum(["threads", "instagram"]).optional(),
	media_url: z.string().optional(),
});

/**
 * Schema for POST /api/posts?action=import-posts
 */
export const ImportPostsSchema = z.object({
	posts: z
		.array(ImportPostItemSchema)
		.min(1, "At least one post is required")
		.max(100, "Maximum 100 posts per import"),
	accountId: z.string().optional(),
});

// ============================================================================
// Auto-Post API Schemas
// ============================================================================

export const AutoPostGroupConfigInnerSchema = z.object({
	posts_per_account_per_day: z.number().int().min(1).max(50).optional(),
	min_interval_minutes: z.number().int().min(1).max(1440).optional(),
	max_interval_minutes: z.number().int().min(1).max(1440).optional(),
	active_hours_start: z.number().int().min(0).max(23).optional(),
	active_hours_end: z.number().int().min(0).max(23).optional(),
	timezone: z.string().optional(),
	post_on_weekends: z.boolean().optional(),
	enabled: z.boolean().optional(),
	// Auto-reply config (lives on same table)
	enable_auto_reply: z.boolean().optional(),
	auto_reply_trigger_count: z.number().int().min(1).max(100).optional(),
	auto_reply_window_hours: z.number().int().min(1).max(168).optional(),
	auto_reply_daily_limit: z.number().int().min(1).max(50).optional(),
	auto_reply_ratio: z.number().min(0).max(1).optional(),
	// Cross-reshare to Instagram Story
	crossreshare_to_ig: z.boolean().optional(),
	crossreshare_to_ig_dark_mode: z.boolean().optional(),
});

/**
 * Schema for POST /api/auto-post?action=upsert-group-config
 */
export const AutoPostConfigSchema = z.object({
	workspaceId: z.string().min(1, "workspaceId is required"),
	groupId: z.string().min(1, "groupId is required"),
	config: AutoPostGroupConfigInnerSchema.optional(),
});

/**
 * Schema for POST /api/auto-post?action=upsert-workspace-config
 * Workspace-level auto-post settings (auto_post_config table)
 */
export const WorkspaceConfigSchema = z.object({
	workspaceId: z.string().min(1, "workspaceId is required"),
	is_enabled: z.boolean().optional(),
	posting_times: zRecord(z.string(), zUnknown()).optional(),
	enable_ai_queue_fill: z.boolean().optional(),
	ai_queue_min_threshold: z.number().int().min(1).max(50).optional(),
	ai_posts_per_fill: z.number().int().min(1).max(50).optional(),
	ai_daily_generation_limit: z.number().int().min(1).max(5000).optional(),
	ai_style_guidelines: z.string().optional().nullable(),
	group_mode_enabled: z.boolean().optional(),
	pause_on_low_performance: z.boolean().optional(),
	performance_threshold: z.number().min(0).max(100).optional(),
	enable_velocity_monitoring: z.boolean().optional(),
	boost_on_viral: z.boolean().optional(),
	viral_interval_reduction_pct: z.number().min(0).max(100).optional(),
	use_smart_timing: z.boolean().optional(),
	competitor_copy_ratio: z.number().min(0).max(1).optional(),
	competitor_copy_max_words: z.number().int().min(1).max(50).optional(),
	// Content filter settings
	content_filter_patterns: z
		.array(
			z.object({
				pattern: z.string(),
				label: z.string(),
			}),
		)
		.optional()
		.nullable(),
	content_filter_min_length: z.number().int().min(0).optional(),
	content_filter_max_length: z.number().int().min(1).optional(),
	content_filter_max_emojis: z.number().int().min(0).optional(),
	discord_webhook_url: z
		.string()
		.refine(
			(url) => {
				if (!url) return true;
				return (
					url.startsWith("https://discord.com/api/webhooks/") ||
					url.startsWith("https://discordapp.com/api/webhooks/")
				);
			},
			{
				message:
					"Discord webhook URL must start with https://discord.com/api/webhooks/ or https://discordapp.com/api/webhooks/",
			},
		)
		.optional()
		.nullable(),
	ai_provider: z.string().optional().nullable(),
});

// ============================================================================
// Competitors API Schemas
// ============================================================================

/**
 * Schema for POST /api/competitors?action=add
 */
export const CompetitorAddSchema = z.object({
	username: z.string().min(1, "username is required"),
});

/**
 * Schema for POST /api/competitors?action=search
 */
export const CompetitorSearchSchema = z.object({
	query: z.string().min(1, "query is required"),
});

/**
 * Schema for POST /api/competitors?action=sync
 */
export const CompetitorSyncSchema = z.object({
	competitorId: z.string().min(1, "competitorId is required"),
});

/**
 * Schema for POST /api/competitors?action=oembed
 */
export const CompetitorOembedSchema = z.object({
	url: z.string().min(1, "url is required"),
});

/**
 * Schema for POST /api/competitors?action=fetch-top-posts
 */
export const CompetitorFetchTopPostsSchema = z.object({
	competitorId: z.string().min(1, "competitorId is required"),
	username: z.string().min(1, "username is required"),
});

/**
 * Schema for POST /api/competitors?action=lookup-post
 */
export const CompetitorLookupPostSchema = z.object({
	postUrl: z.string().min(1, "postUrl is required"),
});

/**
 * Schema for POST /api/competitors?action=ig-search | ig-business-discovery
 */
export const CompetitorIgSearchSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	targetUsername: z.string().min(1, "targetUsername is required"),
});

/**
 * Schema for POST /api/competitors?action=ig-add
 */
export const CompetitorIgAddSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	targetUsername: z.string().min(1, "targetUsername is required"),
});

/**
 * Schema for POST /api/competitors?action=ig-sync
 */
export const CompetitorIgSyncSchema = z.object({
	competitorId: z.string().min(1, "competitorId is required"),
	accountId: z.string().min(1, "accountId is required"),
});
