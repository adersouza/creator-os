/**
 * Schedule handlers — schedule, reschedule, and update draft posts.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { normalizeIGMediaType } from "../../instagram/shared.js";
import { logger } from "../../logger.js";
import {
	type PreflightAccountStatus,
	type PreflightInput,
	type PreflightMediaItem,
	runPublishPreflight,
} from "../../publishPreflight.js";
import { sanitizeHtml } from "../../sanitize.js";
import { getSupabaseAny } from "../../supabase.js";
import { SchedulePostSchema, parseBodyOrError } from "../../validation.js";
import {
	checkSubscriptionPostLimit,
	db,
	normalizePostMediaType,
	resolveMediaUrls,
	validateRawMediaItemsForUser,
} from "./shared.js";

const MIN_SCHEDULE_LEAD_MS = 2 * 60 * 1000;
const MAX_SCHEDULE_MONTHS = 6;

interface ScheduleWindowResult {
	date: Date | null;
	error?: { status: number; message: string; code: string } | undefined;
}

interface ScheduleAccountRow {
	id: string;
	instagram_user_id?: string | null;
	instagram_access_token_encrypted?: string | null;
	facebook_page_access_token_encrypted?: string | null;
	threads_user_id?: string | null;
	threads_access_token_encrypted?: string | null;
	login_type?: string | null;
	is_active?: boolean | null;
	needs_reauth?: boolean | null;
	status?: string | null;
	token_expires_at?: string | null;
	follower_count?: number | null;
}

interface StoredScheduledPost {
	id: string;
	status: string;
	platform: string;
	account_id: string | null;
	instagram_account_id: string | null;
	content: string | null;
	media_ids: string[] | null;
	media_urls: unknown[] | null;
	ig_media_type: string | null;
	media_type: string | null;
	content_surface?: string | null | undefined;
	poll_options: string[] | null;
	quoted_post_id: string | null;
	link_url: string | null;
	gif_attachment: unknown;
	text_attachment: { plaintext?: string } | null;
	location_id: string | null;
	topic_tag: string | null;
	alt_text: string | null;
	scheduled_for: string | null;
	publish_mode: "auto" | "notify" | null;
	metadata: Record<string, unknown> | null;
}

function addMonths(date: Date, months: number): Date {
	const next = new Date(date.getTime());
	next.setMonth(next.getMonth() + months);
	return next;
}

function parseScheduleWindow(
	scheduledFor: string | null | undefined,
): ScheduleWindowResult {
	if (!scheduledFor) return { date: null };

	const date = new Date(scheduledFor);
	if (Number.isNaN(date.getTime())) {
		return {
			date: null,
			error: {
				status: 400,
				message: "scheduledFor must be a valid ISO date",
				code: "INVALID_SCHEDULE_DATE",
			},
		};
	}

	const now = new Date();
	if (date <= now) {
		return {
			date: null,
			error: {
				status: 400,
				message: "scheduledFor must be in the future",
				code: "SCHEDULE_IN_PAST",
			},
		};
	}
	if (date.getTime() - now.getTime() < MIN_SCHEDULE_LEAD_MS) {
		return {
			date: null,
			error: {
				status: 400,
				message: "scheduledFor must be at least 2 minutes in the future",
				code: "SCHEDULE_TOO_SOON",
			},
		};
	}
	if (date > addMonths(now, MAX_SCHEDULE_MONTHS)) {
		return {
			date: null,
			error: {
				status: 400,
				message: "scheduledFor cannot be more than 6 months in the future",
				code: "SCHEDULE_TOO_FAR",
			},
		};
	}

	return { date };
}

function accountToPreflightStatus(
	platform: "threads" | "instagram",
	account: ScheduleAccountRow | null,
): PreflightAccountStatus {
	if (!account) return { found: false };
	if (platform === "instagram") {
		return {
			found: true,
			isActive: account.is_active,
			needsReauth: account.needs_reauth,
			status: account.status,
			tokenExpiresAt: account.token_expires_at,
				hasAccessToken: !!account.instagram_access_token_encrypted,
				hasPlatformUserId: !!account.instagram_user_id,
				loginType: account.login_type,
				followerCount: account.follower_count,
			};
	}

	return {
		found: true,
		isActive: account.is_active,
		needsReauth: account.needs_reauth,
		status: account.status,
		tokenExpiresAt: account.token_expires_at,
		hasAccessToken: !!account.threads_access_token_encrypted,
		hasPlatformUserId: !!account.threads_user_id,
	};
}

async function fetchScheduleAccount(
	userId: string,
	platform: "threads" | "instagram",
	accountId: string,
): Promise<ScheduleAccountRow | null> {
	const table = platform === "instagram" ? "instagram_accounts" : "accounts";
	const select =
		platform === "instagram"
			? "id, instagram_user_id, instagram_access_token_encrypted, facebook_page_access_token_encrypted, login_type, is_active, needs_reauth, status, token_expires_at, follower_count"
			: "id, threads_user_id, threads_access_token_encrypted, is_active, needs_reauth, status, token_expires_at";
	const { data } = (await db()
		.from(table)
		.select(select)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: ScheduleAccountRow | null };
	return data;
}

function pollAttachmentFromOptions(
	pollOptions: string[] | null | undefined,
): PreflightInput["pollAttachment"] {
	return (pollOptions?.length ?? 0) > 0 ? { options: pollOptions ?? [] } : null;
}

function metadataArray<T = unknown>(
	metadata: Record<string, unknown> | null | undefined,
	key: string,
): T[] | undefined {
	const value = metadata?.[key];
	return Array.isArray(value) ? (value as T[]) : undefined;
}

function metadataString(
	metadata: Record<string, unknown> | null | undefined,
	key: string,
): string | null | undefined {
	const value = metadata?.[key];
	return typeof value === "string" ? value : null;
}

function metadataBoolean(
	metadata: Record<string, unknown> | null | undefined,
	key: string,
): boolean | undefined {
	const value = metadata?.[key];
	return typeof value === "boolean" ? value : undefined;
}

function metadataNumber(
	metadata: Record<string, unknown> | null | undefined,
	key: string,
): number | undefined {
	const value = metadata?.[key];
	return typeof value === "number" ? value : undefined;
}

function sanitizeComposerMetadata(
	metadata: Record<string, unknown>,
): Record<string, unknown> {
	const safe: Record<string, unknown> = {};
	const campaignFactory = metadata.campaign_factory;
	if (
		campaignFactory &&
		typeof campaignFactory === "object" &&
		!Array.isArray(campaignFactory)
	) {
		safe.campaign_factory = {
			...(campaignFactory as Record<string, unknown>),
			platform_state: "platform_draft_validated",
			platform_draft_validated_at: new Date().toISOString(),
		};
	}
	const score = metadata.post_health_score;
	if (typeof score === "number" && Number.isFinite(score)) {
		safe.post_health_score = Math.max(0, Math.min(100, Math.round(score)));
	}
	const issues = metadata.post_health_issues;
	if (Array.isArray(issues)) {
		safe.post_health_issues = issues
			.filter((issue): issue is string => typeof issue === "string")
			.slice(0, 8)
			.map((issue) => issue.slice(0, 160));
	}
	const previewSurface = metadata.preview_surface;
	if (typeof previewSurface === "string") {
		safe.preview_surface = previewSurface.slice(0, 32);
	}
	const setupState = metadata.manual_publish_setup_state;
	if (typeof setupState === "string") {
		safe.manual_publish_setup_state = setupState.slice(0, 32);
	}
	const wizardStep = metadata.first_post_wizard_step;
	if (typeof wizardStep === "string") {
		safe.first_post_wizard_step = wizardStep.slice(0, 32);
	}
	const readinessState = metadata.readiness_state;
	if (typeof readinessState === "string") {
		safe.readiness_state = readinessState.slice(0, 32);
	}
	const readinessIssueIds = metadata.readiness_issue_ids;
	if (Array.isArray(readinessIssueIds)) {
		safe.readiness_issue_ids = readinessIssueIds
			.filter((issue): issue is string => typeof issue === "string")
			.slice(0, 12)
			.map((issue) => issue.slice(0, 80));
	}
	const followUp = metadata.post_publish_follow_up;
	if (followUp && typeof followUp === "object" && !Array.isArray(followUp)) {
		const value = followUp as Record<string, unknown>;
		safe.post_publish_follow_up = {
			...(typeof value.instagramUrl === "string"
				? { instagramUrl: value.instagramUrl.slice(0, 240) }
				: {}),
			...(typeof value.notes === "string" ? { notes: value.notes.slice(0, 500) } : {}),
			...(typeof value.savedAt === "string" ? { savedAt: value.savedAt.slice(0, 40) } : {}),
		};
	}
	return safe;
}

function normalizeContentSurface(value: unknown): string | null {
	const raw = typeof value === "string" ? value.trim().toLowerCase() : "";
	if (!raw) return null;
	if (raw === "reel" || raw === "reels") return "reel";
	if (raw === "story" || raw === "stories") return "story";
	if (raw === "feed_single" || raw === "image" || raw === "feed_image") return "feed_single";
	if (raw === "feed_carousel" || raw === "carousel" || raw === "carousel_album") return "feed_carousel";
	return null;
}

function contentSurfaceFromMetadata(metadata: Record<string, unknown> | null | undefined): string | null {
	const campaignFactory = metadata?.campaign_factory;
	if (!campaignFactory || typeof campaignFactory !== "object" || Array.isArray(campaignFactory)) return null;
	const cf = campaignFactory as Record<string, unknown>;
	const manifest = cf.handoff_manifest;
	const mf = manifest && typeof manifest === "object" && !Array.isArray(manifest)
		? (manifest as Record<string, unknown>)
		: {};
	return normalizeContentSurface(cf.content_surface) || normalizeContentSurface(cf.contentSurface) || normalizeContentSurface(mf.content_surface) || normalizeContentSurface(mf.contentSurface);
}

function inferContentSurface(igMediaType: string | null | undefined, metadata?: Record<string, unknown> | null): string | null {
	const metadataSurface = contentSurfaceFromMetadata(metadata);
	if (metadataSurface) return metadataSurface;
	const normalized = normalizeIGMediaType(igMediaType || "");
	if (normalized === "REELS" || normalized === "VIDEO") return "reel";
	if (normalized === "STORIES") return "story";
	if (normalized === "CAROUSEL") return "feed_carousel";
	if (normalized === "IMAGE") return "feed_single";
	return null;
}

function storedMediaUrlsToItems(mediaUrls: unknown[] | null): PreflightMediaItem[] {
	return (mediaUrls || [])
		.map((item): PreflightMediaItem | null => {
			if (typeof item === "string") return { url: item };
			if (item && typeof item === "object") {
				const row = item as { url?: unknown; type?: unknown; altText?: unknown };
				if (typeof row.url !== "string") return null;
				const mediaItem: PreflightMediaItem = { url: row.url };
				if (typeof row.type === "string") mediaItem.type = row.type;
				if (typeof row.altText === "string") mediaItem.altText = row.altText;
				return mediaItem;
			}
			return null;
		})
		.filter((item): item is PreflightMediaItem => item !== null);
}

async function resolvePreflightMedia(
	mediaIds: string[] | null | undefined,
	userId: string,
	fallbackUrls?: unknown[] | null,
): Promise<PreflightMediaItem[]> {
	if ((mediaIds?.length ?? 0) > 0) {
		const { items } = await resolveMediaUrls(mediaIds ?? [], userId);
		return items;
	}
	return storedMediaUrlsToItems(fallbackUrls ?? null);
}

async function runSchedulePreflightOrRespond(
	res: VercelResponse,
	input: PreflightInput,
	account: ScheduleAccountRow | null,
): Promise<boolean> {
	const platform = input.platform || "threads";
	const result = await runPublishPreflight(input, {
		account: accountToPreflightStatus(platform, account),
		checkMediaUrls: true,
	});
	if (!result.ok) {
		apiError(res, 422, "Publish preflight failed", {
			code: "PUBLISH_PREFLIGHT_FAILED",
			extra: { preflight: result },
		});
		return false;
	}
	return true;
}

function buildPreflightFromStoredPost(
	post: StoredScheduledPost,
	media: PreflightMediaItem[],
	overrides: Partial<PreflightInput> = {},
): PreflightInput {
	const metadata = post.metadata || {};
	const platform =
		post.platform === "instagram" ? "instagram" : ("threads" as const);
	return {
		platform,
		mode:
			platform === "instagram" && post.publish_mode === "notify"
				? "native-handoff"
				: "api",
		accountId: platform === "threads" ? post.account_id : undefined,
		instagramAccountId:
			platform === "instagram" ? post.instagram_account_id : undefined,
		content: post.content || "",
		media,
		igMediaType: post.ig_media_type || undefined,
		mediaType: post.media_type || undefined,
		collaborators: metadataArray<string>(metadata, "collaborators"),
		isTrialReel: metadataBoolean(metadata, "isTrialReel"),
		trialReels: metadataBoolean(metadata, "trialReels"),
		instagramTrialReels: metadataBoolean(metadata, "instagramTrialReels"),
		instagram_trial_reels: metadataBoolean(metadata, "instagram_trial_reels"),
		trialGraduationStrategy: metadataString(metadata, "trialGraduationStrategy") || undefined,
		brandedContentSponsorIds: metadataArray<string>(
			metadata,
			"brandedContentSponsorIds",
		),
		isPaidPartnership: metadataBoolean(metadata, "isPaidPartnership"),
		linkUrl: post.link_url,
		gifAttachment: post.gif_attachment,
		pollAttachment: pollAttachmentFromOptions(post.poll_options),
		textAttachment: post.text_attachment,
		topicTag: post.topic_tag,
		crossreshareToIg: metadataBoolean(metadata, "crossreshareToIg"),
		crossreshareToIgDarkMode: metadataBoolean(
			metadata,
			"crossreshareToIgDarkMode",
		),
		coverUrl: metadataString(metadata, "coverUrl"),
		shareToFeed: metadataBoolean(metadata, "shareToFeed"),
		userTags: metadataArray(metadata, "userTags"),
		productTags: metadataArray(metadata, "productTags"),
		thumbOffset: metadataNumber(metadata, "thumbOffset"),
		audioName: metadataString(metadata, "audioName"),
		igAudioId: metadataString(metadata, "igAudioId"),
		commentEnabled: metadataBoolean(metadata, "commentEnabled"),
		firstComment: metadataString(metadata, "firstComment"),
		textSpoilers: metadataArray(metadata, "textSpoilers"),
		metadata,
		...overrides,
	};
}

const SCHEDULED_POST_SELECT =
	"id, status, platform, account_id, instagram_account_id, content, media_ids, media_urls, ig_media_type, media_type, content_surface, poll_options, quoted_post_id, link_url, gif_attachment, text_attachment, location_id, topic_tag, alt_text, scheduled_for, publish_mode, metadata";

/**
 * Schedule a post for future publishing without calling Meta API.
 * The scheduled-posts cron picks it up at the right time.
 * Supports Threads (accountId) and Instagram (instagramAccountId).
 */
export async function handleSchedule(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = parseBodyOrError(res, SchedulePostSchema, req.body);
	if (!parsed) return;
	const {
		accountId,
		instagramAccountId,
		content,
		platform,
		publishMode,
		scheduledFor,
		mediaIds,
		media,
		mediaType,
		pollOptions,
		quotePostId,
		linkUrl,
		gifAttachment,
		textAttachment,
		locationId,
		topicTag,
		textSpoilers,
		isSpoilerMedia,
		crossreshareToIg,
		crossreshareToIgDarkMode,
		settings,
		groupId,
		altText,
		collaborators,
		replyApprovalMode,
		isGhostPost,
		threadChain,
		replyToId,
		persona,
		coverUrl,
		shareToFeed,
		userTags,
		trialReels,
		isTrialReel,
		instagramTrialReels,
		instagram_trial_reels,
		thumbOffset,
		audioName,
		igAudioId,
		productTags,
		brandedContentSponsorIds,
		isPaidPartnership,
		commentEnabled,
		graduation,
		firstComment,
		ghostDuration,
		metadata,
	} = parsed;

	const scheduleWindow = parseScheduleWindow(scheduledFor);
	if (scheduleWindow.error) {
		return apiError(res, scheduleWindow.error.status, scheduleWindow.error.message, {
			code: scheduleWindow.error.code,
		});
	}
	const scheduledDate = scheduleWindow.date;
	const resolvedPlatform = platform || "threads";
	const resolvedPublishMode = publishMode || "auto";
	const directMedia = media ?? [];
	const directMediaUrls = directMedia
		.map((item) => item.url)
		.filter((url): url is string => typeof url === "string" && url.length > 0);
	const hasAnyMedia = (mediaIds?.length ?? 0) > 0 || directMediaUrls.length > 0;
	if (!content?.trim() && !(resolvedPlatform === "instagram" && hasAnyMedia)) {
		return apiError(
			res,
			400,
			resolvedPlatform === "instagram"
				? "Instagram posts need media or a caption"
				: "content is required",
		);
	}
	if (resolvedPublishMode === "notify") {
		if (resolvedPlatform !== "instagram") {
			return apiError(res, 400, "Notify Me is only available for Instagram", {
				code: "NOTIFY_MODE_INSTAGRAM_ONLY",
			});
		}
		if (!scheduledDate) {
			return apiError(res, 400, "Notify Me requires a scheduled time", {
				code: "NOTIFY_MODE_REQUIRES_SCHEDULE",
			});
		}
	}
	// Reserve daily plan capacity for the scheduled UTC day, not just today.
	const tierCheck = await checkSubscriptionPostLimit(userId, {
		targetDate: scheduledDate ?? undefined,
		mode: "schedule",
		additionalCount: 1,
	});
	if (!tierCheck.allowed) {
		return apiError(res, 429, "Daily post limit exceeded", {
			code: "POST_LIMIT_EXCEEDED",
			details: `${tierCheck.tier} tier: ${tierCheck.used}/${tierCheck.limit} posts for that day`,
		});
	}

	const targetId =
		resolvedPlatform === "instagram" ? instagramAccountId : accountId;
	if (!targetId) {
		return apiError(
			res,
			400,
			resolvedPlatform === "instagram"
				? "instagramAccountId is required"
				: "accountId is required",
		);
	}

	const account = await fetchScheduleAccount(
		userId,
		resolvedPlatform,
		targetId,
	);
	if (!account) {
		return apiError(res, 404, "Account not found");
	}

	let instagramPublishingQuota:
		| { usage: number; limit: number; remaining: number; windowHours: number }
		| undefined;
	if (
		resolvedPublishMode === "auto" &&
		resolvedPlatform === "instagram" &&
		scheduledDate &&
		account.login_type === "facebook" &&
		account.instagram_access_token_encrypted &&
		account.instagram_user_id
	) {
		const { checkPublishingLimit } = await import("../../instagramApi.js");
		const quotaResult = await checkPublishingLimit(
			account.instagram_access_token_encrypted,
			account.instagram_user_id,
			account.login_type,
		);
		if (quotaResult.success && quotaResult.quota) {
			instagramPublishingQuota = quotaResult.quota;
			if (instagramPublishingQuota.remaining <= 0) {
				return apiError(
					res,
					429,
					"Instagram publishing cap reached. Facebook Login accounts can schedule again after quota frees up in the 24-hour window.",
					{
						code: "INSTAGRAM_PUBLISHING_CAP_REACHED",
						extra: { publishingQuota: instagramPublishingQuota },
					},
				);
			}
		} else {
			logger.warn("IG publishing quota unavailable before schedule", {
				accountId: targetId,
				error: quotaResult.error,
			});
		}
	}

	if (directMedia.length > 0) {
		const mediaValidationError = await validateRawMediaItemsForUser(
			userId,
			directMedia,
		);
		if (mediaValidationError) {
			return apiError(res, 400, mediaValidationError, {
				code: "INVALID_MEDIA_URL",
			});
		}
	}
	const mediaCount = (mediaIds?.length ?? 0) || directMediaUrls.length;
	const firstDirectMediaType = directMedia[0]?.type;
	const preflightMedia = await resolvePreflightMedia(
		mediaIds,
		userId,
		directMedia,
	);
	const hasCampaignFactoryMetadata =
		metadata?.campaign_factory &&
		typeof metadata.campaign_factory === "object" &&
		!Array.isArray(metadata.campaign_factory);
	if (scheduledDate || hasCampaignFactoryMetadata) {
		const preflightOk = await runSchedulePreflightOrRespond(
			res,
			{
				platform: resolvedPlatform,
				mode:
					resolvedPlatform === "instagram" && resolvedPublishMode === "notify"
						? "native-handoff"
						: "api",
				accountId: resolvedPlatform === "threads" ? accountId : undefined,
				instagramAccountId:
					resolvedPlatform === "instagram" ? instagramAccountId : undefined,
				content,
				media: preflightMedia,
				igMediaType: mediaType,
				mediaType,
				collaborators,
				isTrialReel,
				trialReels,
				brandedContentSponsorIds,
				isPaidPartnership,
				linkUrl,
				gifAttachment,
				pollAttachment: pollAttachmentFromOptions(pollOptions),
				textAttachment,
				topicTag,
				crossreshareToIg,
				crossreshareToIgDarkMode,
				coverUrl,
				shareToFeed,
				userTags,
				productTags,
				thumbOffset,
				audioName,
				igAudioId,
				commentEnabled,
				firstComment,
				textSpoilers,
				metadata: metadata ? sanitizeComposerMetadata(metadata) : undefined,
			},
			account,
		);
		if (!preflightOk) return;
	}

	const cleanContent = sanitizeHtml(content);
	const now = new Date().toISOString();

	// Build insert record
	const isDraft = !scheduledDate;

	// biome-ignore lint/suspicious/noExplicitAny: Supabase insert type workaround
	const insertData: any = {
		user_id: userId,
		content: cleanContent,
		platform: resolvedPlatform,
		status: isDraft ? "draft" : "scheduled",
		publish_mode: resolvedPublishMode,
		scheduled_for: scheduledDate ? scheduledDate.toISOString() : null,
		created_at: now,
		updated_at: now,
	};
	if (persona) insertData.persona = persona;
	if (replyToId) insertData.reply_to_id = replyToId;
	if (threadChain) insertData.thread_chain = true;

	if (resolvedPlatform === "instagram") {
		const canonicalIgMediaType = normalizeIGMediaType(mediaType) || "IMAGE";
		insertData.instagram_account_id = instagramAccountId;
		insertData.account_id = null;
		insertData.ig_media_type = canonicalIgMediaType;
		insertData.media_type = normalizePostMediaType(canonicalIgMediaType, "image");
		if (altText) insertData.alt_text = altText;
		if (locationId) insertData.location_id = locationId;
	} else {
		insertData.account_id = accountId;
		insertData.media_type = normalizePostMediaType(
			mediaCount > 1
				? "CAROUSEL"
				: mediaCount === 1
					? firstDirectMediaType === "video"
						? "VIDEO"
						: "IMAGE"
					: "TEXT",
		);
		if ((pollOptions?.length ?? 0) >= 2) insertData.poll_options = pollOptions;
		if (quotePostId) {
			insertData.quoted_post_id = quotePostId;
			insertData.is_quote = true;
		}
		if (linkUrl) insertData.link_url = linkUrl;
		if (gifAttachment) insertData.gif_attachment = gifAttachment;
		if (textAttachment) insertData.text_attachment = textAttachment;
		if (locationId) insertData.location_id = locationId;
	}

	if ((mediaIds?.length ?? 0) > 0) insertData.media_ids = mediaIds;
	if (directMediaUrls.length > 0) insertData.media_urls = directMediaUrls;

	// Topic tag, text spoilers, media spoiler — stored for publish path
	if (topicTag) insertData.topic_tag = topicTag;
	if (groupId) insertData.group_id = groupId;
	const explicitTrialReel = instagramTrialReels === true || instagram_trial_reels === true;
	const resolvedTrialReel = explicitTrialReel && (isTrialReel || trialReels || explicitTrialReel);

	// Store optional features in metadata JSONB
	const metaFields: Record<string, unknown> = {
		...(insertData.metadata || {}),
		...(metadata ? sanitizeComposerMetadata(metadata) : {}),
		...(textSpoilers ? { textSpoilers } : {}),
		...(isSpoilerMedia ? { isSpoiler: true } : {}),
		...(crossreshareToIg ? { crossreshareToIg: true } : {}),
		...(crossreshareToIgDarkMode ? { crossreshareToIgDarkMode: true } : {}),
		...(settings ? { settings } : {}),
		...(replyApprovalMode ? { replyApprovalMode } : {}),
		...(isGhostPost ? { isGhostPost: true } : {}),
		...(threadChain ? { threadChain: true } : {}),
		...(replyToId ? { replyToId } : {}),
		...(persona ? { persona } : {}),
		// IG-specific features stored in metadata (no dedicated columns)
		...((collaborators?.length ?? 0) > 0 ? { collaborators } : {}),
		...(coverUrl ? { coverUrl } : {}),
		...(shareToFeed !== undefined ? { shareToFeed } : {}),
		...((userTags?.length ?? 0) > 0 ? { userTags } : {}),
		...(resolvedTrialReel ? { trialReels: true, instagramTrialReels: true, instagram_trial_reels: true } : {}),
		...(resolvedTrialReel
			? { trialGraduationStrategy: graduation }
			: {}),
		...(thumbOffset !== undefined ? { thumbOffset } : {}),
		...(audioName ? { audioName } : {}),
		...(igAudioId ? { igAudioId } : {}),
		...((productTags?.length ?? 0) > 0 ? { productTags } : {}),
		...((brandedContentSponsorIds?.length ?? 0) > 0
			? { brandedContentSponsorIds }
			: {}),
		...(isPaidPartnership ? { isPaidPartnership: true } : {}),
		...(commentEnabled !== undefined ? { commentEnabled } : {}),
		...(firstComment ? { firstComment } : {}),
		...(ghostDuration ? { ghostDuration } : {}),
	};
	if (Object.keys(metaFields).length > 0) {
		insertData.metadata = metaFields;
	}
	if (resolvedPlatform === "instagram") {
		insertData.content_surface = inferContentSurface(
			insertData.ig_media_type,
			insertData.metadata,
		);
	}

	const { data: post, error: insertErr } = (await db()
		.from("posts")
		.insert(insertData)
		.select("id")
		.maybeSingle()) as {
		data: { id: string } | null;
		error: { message?: string | undefined } | null;
	};

	if (insertErr || !post) {
		logger.error("Schedule post insert error", { error: String(insertErr) });
		return apiError(res, 500, "Failed to schedule post", {
			details: insertErr?.message || "",
		});
	}

	// Dispatch QStash for exact-time delivery (cron is fallback)
	let qstashMessageId: string | null = null;
	if (scheduledDate) {
		const { dispatchPostPublish } = await import("../../qstashSchedule.js");
		qstashMessageId = await dispatchPostPublish(post.id, scheduledDate);
		if (!qstashMessageId) {
			await db()
				.from("posts")
				.update({
					status: "draft",
					scheduled_for: null,
					error_message:
						"Exact-time scheduler unavailable. Schedule this post again once QStash is healthy.",
					updated_at: new Date().toISOString(),
				})
				.eq("id", post.id)
				.eq("user_id", userId);
			return apiError(
				res,
				503,
				"Exact-time scheduler unavailable. The post was saved as a draft; try scheduling again shortly.",
				{
					code: "EXACT_SCHEDULE_UNAVAILABLE",
					extra: { postId: post.id },
				},
			);
		}
	}

	return apiSuccess(res, {
		postId: post.id,
		scheduledFor: scheduledDate ? scheduledDate.toISOString() : null,
		status: isDraft ? "draft" : "scheduled",
		platform: resolvedPlatform,
		publishMode: resolvedPublishMode,
		exactDispatchScheduled: Boolean(qstashMessageId),
		...(qstashMessageId ? { qstashMessageId } : {}),
		...(instagramPublishingQuota ? { publishingQuota: instagramPublishingQuota } : {}),
	});
}

/**
 * Reschedule a scheduled or draft post to a new time (or unschedule to draft).
 * Accepts { postId, scheduledFor? } — null/omit scheduledFor to move to draft.
 */
export async function handleReschedule(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { postId, scheduledFor } = req.body ?? {};
	if (!postId || typeof postId !== "string") {
		return apiError(res, 400, "postId is required");
	}

	let newScheduledFor: string | null = null;
	let newStatus: string;

	if (scheduledFor) {
		const scheduleWindow = parseScheduleWindow(scheduledFor);
		if (scheduleWindow.error) {
			return apiError(
				res,
				scheduleWindow.error.status,
				scheduleWindow.error.message,
				{ code: scheduleWindow.error.code },
			);
		}
		newScheduledFor = scheduleWindow.date?.toISOString() ?? null;
		newStatus = "scheduled";
	} else {
		newScheduledFor = null;
		newStatus = "draft";
	}

	const { data: post, error: fetchErr } = (await db()
		.from("posts")
		.select(SCHEDULED_POST_SELECT)
		.eq("id", postId)
		.eq("user_id", userId)
		.maybeSingle()) as {
		data: StoredScheduledPost | null;
		error: unknown;
	};

	if (fetchErr || !post) {
		return apiError(res, 404, "Post not found");
	}
	if (!["scheduled", "draft"].includes(post.status)) {
		return apiError(
			res,
			400,
			"Only scheduled or draft posts can be rescheduled",
		);
	}

	let account: ScheduleAccountRow | null = null;
	if (newScheduledFor) {
		const platform =
			post.platform === "instagram" ? "instagram" : ("threads" as const);
		const targetId =
			platform === "instagram" ? post.instagram_account_id : post.account_id;
		if (!targetId) {
			return apiError(res, 422, "Publish preflight failed", {
				code: "PUBLISH_PREFLIGHT_FAILED",
				extra: {
					preflight: {
						ok: false,
						issues: [
							{
								severity: "error",
								category: "account",
								code: "missing_account",
								message: "Choose an account before scheduling this post.",
							},
						],
						summary: { errors: 1, warnings: 0, infos: 0 },
					},
				},
			});
		}
		account = await fetchScheduleAccount(userId, platform, targetId);
		const media = await resolvePreflightMedia(
			post.media_ids,
			userId,
			post.media_urls,
		);
		const preflightOk = await runSchedulePreflightOrRespond(
			res,
			buildPreflightFromStoredPost(post, media),
			account,
		);
		if (!preflightOk) return;
	}

	const previousScheduledFor = post.scheduled_for;
	const previousStatus = post.status;
	const previousMetadata = post.metadata;
	const previousMessageId =
		typeof post.metadata?.qstash_message_id === "string"
			? post.metadata.qstash_message_id
			: null;

	const { error: updateErr } = await db()
		.from("posts")
		.update({
			scheduled_for: newScheduledFor,
			status: newStatus,
			updated_at: new Date().toISOString(),
		})
		.eq("id", postId)
		.eq("user_id", userId);

	if (updateErr) {
		return apiError(res, 500, "Failed to reschedule post");
	}

	// Dispatch new QStash if rescheduling (not moving to draft)
	let qstashMessageId: string | null = null;
	if (newScheduledFor) {
		const { cancelQStashMessage, dispatchPostPublish } = await import(
			"../../qstashSchedule.js"
		);
		qstashMessageId = await dispatchPostPublish(
			postId,
			new Date(newScheduledFor),
		);
		if (!qstashMessageId) {
			await getSupabaseAny()
				.from("posts")
				.update({
					status: previousStatus,
					scheduled_for: previousScheduledFor,
					metadata: previousMetadata,
					updated_at: new Date().toISOString(),
				})
				.eq("id", postId)
				.eq("user_id", userId);
			return apiError(
				res,
				503,
				"Exact-time scheduler unavailable. The previous schedule was kept; try again shortly.",
				{ code: "EXACT_SCHEDULE_UNAVAILABLE" },
			);
		}
		if (previousMessageId && previousMessageId !== qstashMessageId) {
			await cancelQStashMessage(previousMessageId, { postId });
		}
	} else {
		const { cancelPostPublish } = await import("../../qstashSchedule.js");
		await cancelPostPublish(postId);
	}

	return apiSuccess(res, {
		postId,
		scheduledFor: newScheduledFor,
		status: newStatus,
		exactDispatchScheduled: Boolean(qstashMessageId),
		...(qstashMessageId ? { qstashMessageId } : {}),
	});
}

/**
 * Update an existing draft or scheduled post — content, media, poll options, or schedule time.
 * Only works on status: draft or scheduled.
 */
export async function handleUpdateDraft(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const {
		postId,
		content,
		mediaIds,
		pollOptions,
		scheduledFor,
		mediaType,
		altText,
		locationId,
		collaborators,
		coverUrl,
		shareToFeed,
		userTags,
		trialReels: updateTrialReels,
		instagramTrialReels: updateInstagramTrialReels,
		instagram_trial_reels: updateInstagramTrialReelsSnake,
		topicTag,
		thumbOffset,
		audioName,
		igAudioId,
		productTags,
		commentEnabled,
		graduation,
	} = req.body ?? {};
	if (!postId || typeof postId !== "string") {
		return apiError(res, 400, "postId is required");
	}

	const { data: post, error: fetchErr } = (await db()
		.from("posts")
		.select(SCHEDULED_POST_SELECT)
		.eq("id", postId)
		.eq("user_id", userId)
		.maybeSingle()) as {
		data: StoredScheduledPost | null;
		error: unknown;
	};

	if (fetchErr || !post) {
		return apiError(res, 404, "Post not found");
	}
	if (!["draft", "scheduled"].includes(post.status)) {
		return apiError(res, 400, "Only draft or scheduled posts can be updated");
	}

	const updates: Record<string, unknown> = {
		updated_at: new Date().toISOString(),
	};
	if (content !== undefined) updates.content = content;
	if (mediaIds !== undefined) updates.media_ids = mediaIds;
	if (pollOptions !== undefined) updates.poll_options = pollOptions;
	// IG-specific updates
	if (mediaType !== undefined && post.platform === "instagram") {
		const canonicalIgMediaType = normalizeIGMediaType(mediaType) || "IMAGE";
		updates.ig_media_type = canonicalIgMediaType;
		updates.media_type = normalizePostMediaType(canonicalIgMediaType, "image");
		updates.content_surface = inferContentSurface(
			canonicalIgMediaType,
			post.metadata,
		);
	}
	if (altText !== undefined) updates.alt_text = altText;
	if (locationId !== undefined) updates.location_id = locationId;
	if (topicTag !== undefined) updates.topic_tag = topicTag;

	// IG metadata updates (collaborators, coverUrl, shareToFeed, userTags, trialReels)
	if (post.platform === "instagram") {
		const existingMeta = (post.metadata || {}) as Record<string, unknown>;
		const metaUpdates: Record<string, unknown> = { ...existingMeta };
		let metaChanged = false;
		if (collaborators !== undefined) {
			metaUpdates.collaborators = collaborators;
			metaChanged = true;
		}
		if (coverUrl !== undefined) {
			metaUpdates.coverUrl = coverUrl;
			metaChanged = true;
		}
		if (shareToFeed !== undefined) {
			metaUpdates.shareToFeed = shareToFeed;
			metaChanged = true;
		}
		if (userTags !== undefined) {
			metaUpdates.userTags = userTags;
			metaChanged = true;
		}
		if (updateTrialReels !== undefined) {
			metaUpdates.trialReels = updateTrialReels;
			metaChanged = true;
		}
		if (updateInstagramTrialReels !== undefined || updateInstagramTrialReelsSnake !== undefined) {
			const enabled = updateInstagramTrialReels === true || updateInstagramTrialReelsSnake === true;
			metaUpdates.instagramTrialReels = enabled;
			metaUpdates.instagram_trial_reels = enabled;
			metaUpdates.trialReels = enabled;
			metaChanged = true;
		}
		if (graduation !== undefined) {
			metaUpdates.trialGraduationStrategy = graduation;
			metaChanged = true;
		}
		if (thumbOffset !== undefined) {
			metaUpdates.thumbOffset = thumbOffset;
			metaChanged = true;
		}
		if (audioName !== undefined) {
			metaUpdates.audioName = audioName;
			metaChanged = true;
		}
		if (igAudioId !== undefined) {
			metaUpdates.igAudioId = igAudioId;
			metaChanged = true;
		}
		if (productTags !== undefined) {
			metaUpdates.productTags = productTags;
			metaChanged = true;
		}
		if (commentEnabled !== undefined) {
			metaUpdates.commentEnabled = commentEnabled;
			metaChanged = true;
		}
		if (metaChanged) updates.metadata = metaUpdates;
	}

	if (scheduledFor !== undefined) {
		if (scheduledFor) {
			const scheduleWindow = parseScheduleWindow(scheduledFor);
			if (scheduleWindow.error) {
				return apiError(
					res,
					scheduleWindow.error.status,
					scheduleWindow.error.message,
					{ code: scheduleWindow.error.code },
				);
			}
			updates.scheduled_for = scheduleWindow.date?.toISOString() ?? null;
			updates.status = "scheduled";
		} else {
			updates.scheduled_for = null;
			updates.status = "draft";
		}
	}

	const finalStatus = (updates.status as string | undefined) ?? post.status;
	const finalPost: StoredScheduledPost = {
		...post,
		content: (updates.content as string | undefined) ?? post.content,
		media_ids: (updates.media_ids as string[] | undefined) ?? post.media_ids,
		poll_options:
			(updates.poll_options as string[] | undefined) ?? post.poll_options,
		ig_media_type:
			(updates.ig_media_type as string | undefined) ?? post.ig_media_type,
		media_type: (updates.media_type as string | undefined) ?? post.media_type,
		alt_text: (updates.alt_text as string | undefined) ?? post.alt_text,
		location_id:
			(updates.location_id as string | undefined) ?? post.location_id,
		topic_tag: (updates.topic_tag as string | undefined) ?? post.topic_tag,
		metadata:
			(updates.metadata as Record<string, unknown> | undefined) ??
			post.metadata,
		scheduled_for:
			(updates.scheduled_for as string | null | undefined) ??
			post.scheduled_for,
		status: finalStatus,
	};
	let account: ScheduleAccountRow | null = null;
	if (finalStatus === "scheduled") {
		const platform =
			finalPost.platform === "instagram" ? "instagram" : ("threads" as const);
		const targetId =
			platform === "instagram"
				? finalPost.instagram_account_id
				: finalPost.account_id;
		if (!targetId) {
			return apiError(res, 422, "Publish preflight failed", {
				code: "PUBLISH_PREFLIGHT_FAILED",
				extra: {
					preflight: {
						ok: false,
						issues: [
							{
								severity: "error",
								category: "account",
								code: "missing_account",
								message: "Choose an account before scheduling this post.",
							},
						],
						summary: { errors: 1, warnings: 0, infos: 0 },
					},
				},
			});
		}
		account = await fetchScheduleAccount(userId, platform, targetId);
		const media = await resolvePreflightMedia(
			finalPost.media_ids,
			userId,
			finalPost.media_urls,
		);
		const preflightOk = await runSchedulePreflightOrRespond(
			res,
			buildPreflightFromStoredPost(finalPost, media),
			account,
		);
		if (!preflightOk) return;
	}

	const previousMessageId =
		typeof post.metadata?.qstash_message_id === "string"
			? post.metadata.qstash_message_id
			: null;

	const { error: updateErr } = await getSupabaseAny()
		.from("posts")
		.update(updates)
		.eq("id", postId)
		.eq("user_id", userId);

	if (updateErr) {
		return apiError(res, 500, "Failed to update draft");
	}

	// Dispatch new QStash AFTER successful DB update.
	let qstashMessageId: string | null = null;
	if (scheduledFor !== undefined && scheduledFor) {
		const { cancelQStashMessage, dispatchPostPublish } = await import(
			"../../qstashSchedule.js"
		);
		qstashMessageId = await dispatchPostPublish(
			postId,
			new Date(updates.scheduled_for as string),
		);
		if (!qstashMessageId) {
			const fallbackUpdate =
				post.status === "scheduled"
					? {
							status: post.status,
							scheduled_for: post.scheduled_for,
							metadata: post.metadata,
							updated_at: new Date().toISOString(),
						}
					: {
							status: "draft",
							scheduled_for: null,
							metadata: post.metadata,
							updated_at: new Date().toISOString(),
						};
			await getSupabaseAny()
				.from("posts")
				.update(fallbackUpdate)
				.eq("id", postId)
				.eq("user_id", userId);
			return apiError(
				res,
				503,
				post.status === "scheduled"
					? "Exact-time scheduler unavailable. The previous schedule was kept; try again shortly."
					: "Exact-time scheduler unavailable. The post was kept as a draft; try scheduling again shortly.",
				{ code: "EXACT_SCHEDULE_UNAVAILABLE" },
			);
		}
		if (previousMessageId && previousMessageId !== qstashMessageId) {
			await cancelQStashMessage(previousMessageId, { postId });
		}
	} else if (scheduledFor !== undefined && !scheduledFor) {
		const { cancelPostPublish } = await import("../../qstashSchedule.js");
		await cancelPostPublish(postId);
	}

	return apiSuccess(res, {
		postId,
		updated: Object.keys(updates).filter((k) => k !== "updated_at"),
		exactDispatchScheduled: Boolean(qstashMessageId),
		...(qstashMessageId ? { qstashMessageId } : {}),
	});
}
