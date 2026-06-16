import { logger } from "./logger.js";
import { validateDiscoverabilitySafeContent } from "./discoverabilitySafety.js";
import { checkMediaUrlAccessible } from "./cron/scheduled-posts/mediaValidation.js";
import { normalizeIGMediaType } from "./instagram/shared.js";
import {
	hasInternalTrialLanguage,
	resolveInstagramTrialReelIntent,
} from "./instagramTrialReels.js";
import {
	campaignFactoryAssetStateAllowsExport,
	validateHandoffManifestContract,
} from "../../pipeline_contracts/typescript.js";

export type PreflightPlatform = "threads" | "instagram";
export type PreflightMode = "api" | "native-handoff";
export type PreflightSeverity = "error" | "warning" | "info";
export type PreflightCategory =
	| "account"
	| "audio"
	| "campaign_factory"
	| "caption"
	| "instagram"
	| "media"
	| "threads"
	| "token";

export interface PreflightIssue {
	severity: PreflightSeverity;
	category: PreflightCategory;
	code: string;
	message: string;
}

export interface PreflightMediaItem {
	type?: string | undefined;
	url?: string | undefined;
	altText?: string | null | undefined;
}

export interface PreflightInput {
	platform?: PreflightPlatform | undefined;
	mode?: PreflightMode | undefined;
	accountId?: string | null | undefined;
	instagramAccountId?: string | null | undefined;
	content?: string | undefined;
	media?: PreflightMediaItem[] | undefined;
	topics?: string[] | undefined;
	igMediaType?: string | undefined;
	mediaType?: string | undefined;
	collaborators?: string[] | undefined;
	isTrialReel?: boolean | undefined;
	trialReels?: boolean | undefined;
	instagramTrialReels?: boolean | undefined;
	instagram_trial_reels?: boolean | undefined;
	trialGraduationStrategy?: string | undefined;
	brandedContentSponsorIds?: string[] | undefined;
	isPaidPartnership?: boolean | undefined;
	linkUrl?: string | null | undefined;
	gifAttachment?: unknown;
	pollAttachment?:
		| {
				options?: string[] | undefined;
				option_a?: string | undefined;
				option_b?: string | undefined;
				option_c?: string | undefined;
				option_d?: string | undefined;
		  }
		| null
		| undefined;
	textAttachment?: { plaintext?: string | undefined } | null | undefined;
	topicTag?: string | null | undefined;
	crossreshareToIg?: boolean | undefined;
	crossreshareToIgDarkMode?: boolean | undefined;
	coverUrl?: string | null | undefined;
	shareToFeed?: boolean | undefined;
	userTags?: unknown[] | undefined;
	productTags?: unknown[] | undefined;
	thumbOffset?: number | undefined;
	reelCover?: number | undefined;
	audioName?: string | null | undefined;
	igAudioId?: string | null | undefined;
	commentEnabled?: boolean | undefined;
	firstComment?: string | null | undefined;
	replyToId?: string | null | undefined;
	metadata?: Record<string, unknown> | null | undefined;
	campaignFactory?: Record<string, unknown> | null | undefined;
	allowlistedCountryCodes?: string[] | undefined;
	textSpoilers?: unknown[] | undefined;
}

export interface PreflightAccountStatus {
	found?: boolean | undefined;
	isActive?: boolean | null | undefined;
	needsReauth?: boolean | null | undefined;
	status?: string | null | undefined;
	tokenExpiresAt?: string | null | undefined;
	hasAccessToken?: boolean | undefined;
	hasPlatformUserId?: boolean | undefined;
	loginType?: string | null | undefined;
	followerCount?: number | null | undefined;
}

export interface PreflightResult {
	ok: boolean;
	issues: PreflightIssue[];
	summary: {
		errors: number;
		warnings: number;
		infos: number;
	};
}

const IG_CAPTION_LIMIT = 2200;
const IG_HASHTAG_LIMIT = 30;
const IG_MENTION_LIMIT = 20;
const THREADS_TEXT_LIMIT = 500;
const THREADS_LINK_LIMIT = 5;
const URL_PATTERN = /https?:\/\/[^\s)}\]>]+/gi;
const HASHTAG_PATTERN = /#[\p{L}\p{N}_]+/gu;
const MENTION_PATTERN = /(^|[^\w])@[\p{L}\p{N}_.]+/gu;
const UNSUPPORTED_VIDEO_PATTERN =
	/\.(webm|avi|mkv|wmv|flv|3gp|ts|m4v|ogv)(\?|$)/i;
const IG_UNSUPPORTED_IMAGE_PATTERN = /\.(gif|webp)(\?|$)/i;
const THREADS_UNSUPPORTED_IMAGE_PATTERN = /\.(gif|webp)(\?|$)/i;
const SOON_EXPIRY_MS = 72 * 60 * 60 * 1000;
const INSTAGRAM_USERNAME_PATTERN = /^[A-Za-z0-9._]{1,30}$/;
const NUMERIC_ID_PATTERN = /^\d+$/;
const IG_TRIAL_REEL_MIN_FOLLOWERS = 1000;

function add(
	issues: PreflightIssue[],
	severity: PreflightSeverity,
	category: PreflightCategory,
	code: string,
	message: string,
) {
	issues.push({ severity, category, code, message });
}

function isInstagramNativeHandoff(input: PreflightInput): boolean {
	return input.platform === "instagram" && input.mode === "native-handoff";
}

function addApiOnlyIssue(
	input: PreflightInput,
	issues: PreflightIssue[],
	category: PreflightCategory,
	code: string,
	apiMessage: string,
	handoffMessage = apiMessage,
) {
	add(
		issues,
		isInstagramNativeHandoff(input) ? "warning" : "error",
		category,
		code,
		isInstagramNativeHandoff(input)
			? `${handoffMessage} You can still finish this manually in Instagram.`
			: apiMessage,
	);
}

function mediaKind(item: PreflightMediaItem): "image" | "video" | "unknown" {
	const type = (item.type || "").toLowerCase();
	const url = item.url || "";
	if (
		type.includes("video") ||
		/\.(mp4|mov|webm|avi|mkv|wmv|flv|m4v|ogv)(\?|$)/i.test(url)
	)
		return "video";
	if (
		type.includes("image") ||
		/\.(png|jpe?g|webp|gif|bmp|heic|heif)(\?|$)/i.test(url)
	)
		return "image";
	return "unknown";
}

function normalizedIgMediaType(input: PreflightInput): string {
	const rawExplicit = input.igMediaType || input.mediaType || "";
	const explicit = normalizeIGMediaType(rawExplicit);
	if (explicit) return explicit;
	if (rawExplicit.trim()) return rawExplicit.trim().toUpperCase();
	const media = input.media || [];
	if (media.length > 1) return "CAROUSEL";
	const firstMedia = media[0];
	if (firstMedia && mediaKind(firstMedia) === "video") return "REELS";
	return "IMAGE";
}

function pollOptionCount(poll: PreflightInput["pollAttachment"]): number {
	if (!poll) return 0;
	if (Array.isArray(poll.options)) {
		return poll.options.filter((option) => option.trim()).length;
	}
	return [poll.option_a, poll.option_b, poll.option_c, poll.option_d].filter(
		(option) => typeof option === "string" && option.trim(),
	).length;
}

function buildThreadsText(
	content: string,
	topics: string[] | undefined,
): string {
	let finalContent = content;
	const hashtags = (topics || [])
		.map((topic) => topic.trim().replace(/^#/, ""))
		.map((topic) => topic.replace(/\s+/g, "").replace(/[^a-zA-Z0-9_]/g, ""))
		.filter(Boolean)
		.map((topic) => `#${topic}`)
		.filter((tag) => !finalContent.toLowerCase().includes(tag.toLowerCase()));
	if (hashtags.length > 0) {
		finalContent = `${finalContent}\n\n${hashtags.join(" ")}`.trim();
	}
	return finalContent;
}

function countMatches(value: string, pattern: RegExp): number {
	return [...value.matchAll(pattern)].length;
}

function validateAccount(
	input: PreflightInput,
	account: PreflightAccountStatus | null | undefined,
	issues: PreflightIssue[],
) {
	const platform = input.platform || "threads";
	const targetId =
		platform === "instagram" ? input.instagramAccountId : input.accountId;
	if (!targetId) {
		add(
			issues,
			"error",
			"account",
			"missing_account",
			platform === "instagram"
				? "Choose an Instagram account before posting."
				: "Choose a Threads account before posting.",
		);
		return;
	}
	if (!account?.found) {
		add(
			issues,
			"error",
			"account",
			"account_not_found",
			"Account not found or not connected.",
		);
		return;
	}
	if (account.isActive === false) {
		add(
			issues,
			"error",
			"account",
			"account_inactive",
			"This account is inactive. Reconnect or reactivate it before posting.",
		);
	}
	if (account.needsReauth || account.status === "needs_reauth") {
		addApiOnlyIssue(
			input,
			issues,
			"token",
			"account_needs_reauth",
			"This account needs to be reconnected before posting.",
			"This account needs to be reconnected before auto-publishing.",
		);
	}
	if (!account.hasAccessToken || !account.hasPlatformUserId) {
		addApiOnlyIssue(
			input,
			issues,
			"token",
			"account_missing_token",
			"This account is missing the token or platform user ID needed to publish.",
			"This account is missing the token or platform user ID needed to auto-publish.",
		);
	}
	if (
		account.tokenExpiresAt &&
		new Date(account.tokenExpiresAt) <= new Date()
	) {
		addApiOnlyIssue(
			input,
			issues,
			"token",
			"token_expired",
			"This account token has expired. Reconnect before posting.",
			"This account token has expired, so auto-publishing is unavailable.",
		);
	}
	if (account.tokenExpiresAt) {
		const expiresAt = Date.parse(account.tokenExpiresAt);
		if (
			Number.isFinite(expiresAt) &&
			expiresAt > Date.now() &&
			expiresAt - Date.now() <= SOON_EXPIRY_MS
		) {
			add(
				issues,
				"warning",
				"token",
				"token_expires_soon",
				"This account token expires within 72 hours. Publishing can proceed, but reconnect soon to avoid queue failures.",
			);
		}
	}
}

function validateInstagram(input: PreflightInput, issues: PreflightIssue[]) {
	const content = input.content || "";
	const media = input.media || [];
	const igMediaType = normalizedIgMediaType(input);
	const hasVideo = media.some((item) => mediaKind(item) === "video");
	const trialReels = input.isTrialReel || input.trialReels;

	if (!normalizeIGMediaType(igMediaType)) {
		add(
			issues,
			"error",
			"instagram",
			"ig_media_type_invalid",
			"Instagram media type must be IMAGE, VIDEO, REELS, CAROUSEL, or STORIES.",
		);
	}
	if (content.length > IG_CAPTION_LIMIT) {
		add(
			issues,
			"error",
			"caption",
			"ig_caption_too_long",
			`Instagram captions max out at ${IG_CAPTION_LIMIT} characters.`,
		);
	}
	const hashtagCount = countMatches(content, HASHTAG_PATTERN);
	if (hashtagCount > IG_HASHTAG_LIMIT) {
		add(
			issues,
			"error",
			"caption",
			"ig_too_many_hashtags",
			`Instagram allows up to ${IG_HASHTAG_LIMIT} hashtags; this caption has ${hashtagCount}.`,
		);
	}
	const mentionCount = countMatches(content, MENTION_PATTERN);
	if (mentionCount > IG_MENTION_LIMIT) {
		add(
			issues,
			"error",
			"caption",
			"ig_too_many_mentions",
			`Instagram allows up to ${IG_MENTION_LIMIT} @ mentions; this caption has ${mentionCount}.`,
		);
	}
	if (media.length === 0) {
		add(
			issues,
			"error",
			"instagram",
			"ig_media_required",
			"Instagram publishing requires at least one media item.",
		);
	}
	if (igMediaType === "STORIES" && media.length !== 1) {
		add(
			issues,
			"error",
			"instagram",
			"ig_story_single_media",
			"Instagram Stories require exactly one image or video.",
		);
	}
	if (igMediaType === "CAROUSEL" && (media.length < 2 || media.length > 10)) {
		add(
			issues,
			"error",
			"instagram",
			"ig_carousel_count",
			"Instagram carousels require 2-10 media items.",
		);
	}
	if (igMediaType === "REELS" && (media.length !== 1 || !hasVideo)) {
		add(
			issues,
			"error",
			"instagram",
			"ig_reel_video_required",
			"Instagram Reels require exactly one video.",
		);
	}
	if ((input.collaborators?.length || 0) > 3) {
		add(
			issues,
			"error",
			"instagram",
			"ig_collaborator_limit",
			"Instagram supports up to 3 collaborators.",
		);
	}
	for (const collaborator of input.collaborators || []) {
		const username = collaborator.trim().replace(/^@/, "");
		if (!INSTAGRAM_USERNAME_PATTERN.test(username)) {
			add(
				issues,
				"error",
				"instagram",
				"ig_collaborator_format",
				"Instagram collaborator usernames can only contain letters, numbers, periods, and underscores.",
			);
			break;
		}
	}
	if ((input.brandedContentSponsorIds?.length || 0) > 2) {
		add(
			issues,
			"error",
			"instagram",
			"ig_sponsor_limit",
			"Paid partnership publishing supports up to 2 brand partners.",
		);
	}
	for (const sponsorId of input.brandedContentSponsorIds || []) {
		if (!NUMERIC_ID_PATTERN.test(sponsorId.trim())) {
			add(
				issues,
				"error",
				"instagram",
				"ig_sponsor_id_format",
				"Paid partnership sponsor IDs must be Instagram user IDs, not usernames.",
			);
			break;
		}
	}
	if (input.brandedContentSponsorIds?.length && !input.isPaidPartnership) {
		add(
			issues,
			"warning",
			"instagram",
			"ig_sponsor_without_label",
			"Brand partner IDs are present, but the paid partnership label is off.",
		);
	}
	if (input.isPaidPartnership && igMediaType === "STORIES") {
		add(
			issues,
			"warning",
			"instagram",
			"ig_story_partnership_ignored",
			"Paid partnership fields are ignored for Instagram Stories by the publisher.",
		);
	}
	const campaignFactory = campaignFactoryMetadata(input);
	const unsafeTexts = campaignFactory
		? campaignFactoryCaptionTexts(input, campaignFactory)
		: [content, input.firstComment].filter(
				(value): value is string =>
					typeof value === "string" && value.trim().length > 0,
			);
	if (igMediaType !== "STORIES" || unsafeTexts.length > 0) {
		const discoverability = validateDiscoverabilitySafeContent(...unsafeTexts);
		if (!discoverability.discoverabilitySafe) {
			add(
				issues,
				"error",
				"caption",
				"ig_caption_link_or_dm_reference",
				"Instagram captions and Story text must not mention DMs, links, bio links, or off-platform contact destinations. Remove all DM/link/contact CTA language before scheduling or publishing.",
			);
		}
	}
	const trialIntent = resolveInstagramTrialReelIntent({
		metadata: input.metadata,
		campaignFactory,
		instagramTrialReels: input.instagramTrialReels,
		instagram_trial_reels: input.instagram_trial_reels,
		trialGraduationStrategy: input.trialGraduationStrategy,
	});
	if ((trialReels || hasInternalTrialLanguage({ metadata: input.metadata, campaignFactory })) && !trialIntent.enabled) {
		add(
			issues,
			"error",
			"instagram",
			"campaign_internal_trial_reel_not_instagram_trial",
			"Internal trial/proof/test labels must not send Instagram Trial Reel params unless instagram_trial_reels is explicitly true.",
		);
	}
	if (trialIntent.enabled) {
		if (igMediaType !== "REELS") {
			add(
				issues,
				"error",
				"instagram",
				"ig_trial_reel_type",
				"Trial Reels can only be published as Reels.",
			);
		}
		if (!trialIntent.strategy) {
			add(
				issues,
				"error",
				"instagram",
				"ig_trial_reel_graduation_strategy_missing_or_invalid",
				"Instagram Trial Reels require trialGraduationStrategy MANUAL or SS_PERFORMANCE.",
			);
		}
		if (campaignFactory) {
			const surface = campaignContentSurface(campaignFactory);
			const campaignType = campaignIgMediaType(campaignFactory);
			if (surface && surface !== "reel") {
				add(
					issues,
					"error",
					"instagram",
					"ig_trial_reel_surface_mismatch",
					"Instagram Trial Reels require Campaign content_surface = reel.",
				);
			}
			if (campaignType && campaignType !== "REELS") {
				add(
					issues,
					"error",
					"instagram",
					"ig_trial_reel_manifest_media_type_mismatch",
					"Instagram Trial Reels require Campaign ig_media_type = REELS.",
				);
			}
		}
		if (media.length !== 1 || !hasVideo) {
			add(
				issues,
				"error",
				"instagram",
				"ig_trial_reel_single_video",
				"Trial Reels require exactly one video.",
			);
		}
		if (input.collaborators?.length) {
			add(
				issues,
				"error",
				"instagram",
				"ig_trial_reel_collaborators",
				"Trial Reels cannot include collaborators.",
			);
		}
	}
	for (const item of media) {
		if (!item.url) continue;
		const kind = mediaKind(item);
		if (kind === "video" && UNSUPPORTED_VIDEO_PATTERN.test(item.url)) {
			add(
				issues,
				"error",
				"media",
				"ig_video_format",
				"Instagram video publishing requires MP4/MOV-compatible video URLs.",
			);
		}
		if (
			kind === "video" &&
			trialIntent.enabled &&
			!/\.(mp4|mov)(\?|$)/i.test(item.url)
		) {
			add(
				issues,
				"error",
				"media",
				"ig_trial_reel_format",
				"Trial Reels require an MP4 or MOV video URL.",
			);
		}
		if (kind === "image" && IG_UNSUPPORTED_IMAGE_PATTERN.test(item.url)) {
			add(
				issues,
				"error",
				"media",
				"ig_image_format",
				"Instagram image publishing supports JPEG/PNG URLs; GIF/WebP images need conversion first.",
			);
		}
	}
	if (input.firstComment && input.firstComment.length > IG_CAPTION_LIMIT) {
		add(
			issues,
			"error",
			"instagram",
			"ig_first_comment_too_long",
			`First comments max out at ${IG_CAPTION_LIMIT} characters.`,
		);
	}
}

function validateInstagramAccountSurfaceAccess(
	input: PreflightInput,
	account: PreflightAccountStatus | null | undefined,
	issues: PreflightIssue[],
) {
	if (input.platform !== "instagram") return;
	const campaignFactory = campaignFactoryMetadata(input);
	const trialIntent = resolveInstagramTrialReelIntent({
		metadata: input.metadata,
		campaignFactory,
		instagramTrialReels: input.instagramTrialReels,
		instagram_trial_reels: input.instagram_trial_reels,
		trialGraduationStrategy: input.trialGraduationStrategy,
	});
	if (!trialIntent.enabled) return;
	const followerCount =
		typeof account?.followerCount === "number" ? account.followerCount : null;
	if (followerCount !== null && followerCount < IG_TRIAL_REEL_MIN_FOLLOWERS) {
		add(
			issues,
			"error",
			"account",
			"ig_trial_reel_account_not_eligible",
			`Instagram Trial Reels require account-level Trial Reel access; this account has ${followerCount} followers, below the ${IG_TRIAL_REEL_MIN_FOLLOWERS}+ follower eligibility floor used by the platform rollout.`,
		);
	}
}

function recordValue(value: unknown): Record<string, unknown> | null {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function surfaceValue(value: unknown): string {
	const raw = stringValue(value).toLowerCase();
	if (raw === "reel" || raw === "reels") return "reel";
	if (raw === "story" || raw === "stories") return "story";
	if (raw === "feed_single" || raw === "image") return "feed_single";
	if (raw === "feed_carousel" || raw === "carousel") return "feed_carousel";
	return raw;
}

function campaignContentSurface(campaignFactory: Record<string, unknown> | null): string {
	const manifest = recordValue(campaignFactory?.handoff_manifest);
	return (
		surfaceValue(campaignFactory?.content_surface) ||
		surfaceValue(campaignFactory?.contentSurface) ||
		surfaceValue(manifest?.content_surface) ||
		surfaceValue(manifest?.contentSurface)
	);
}

function campaignIgMediaType(campaignFactory: Record<string, unknown> | null): string {
	const manifest = recordValue(campaignFactory?.handoff_manifest);
	return (
		stringValue(campaignFactory?.ig_media_type) ||
		stringValue(campaignFactory?.igMediaType) ||
		stringValue(manifest?.ig_media_type) ||
		stringValue(manifest?.igMediaType)
	).toUpperCase();
}

function campaignFactoryMetadata(
	input: PreflightInput,
): Record<string, unknown> | null {
	if (input.campaignFactory) return input.campaignFactory;
	const metadata = recordValue(input.metadata);
	return recordValue(metadata?.campaign_factory);
}

function stringValue(value: unknown): string {
	return typeof value === "string" ? value.trim() : "";
}

function campaignFactoryInstagramPostCaption(
	input: PreflightInput,
	campaignFactory: Record<string, unknown>,
): string {
	const manifest = recordValue(campaignFactory.handoff_manifest);
	return (
		stringValue(campaignFactory.instagram_post_caption) ||
		stringValue(campaignFactory.instagramPostCaption) ||
		stringValue(manifest?.instagram_post_caption) ||
		stringValue(manifest?.instagramPostCaption)
	);
}

function campaignFactoryCaptionTexts(
	input: PreflightInput,
	campaignFactory: Record<string, unknown>,
): string[] {
	const manifest = recordValue(campaignFactory.handoff_manifest);
	const context = recordValue(campaignFactory.captionOutcomeContext) ||
		recordValue(campaignFactory.caption_outcome_context);
	const manifestContext = recordValue(manifest?.captionOutcomeContext) ||
		recordValue(manifest?.caption_outcome_context);
	return [
		input.content,
		campaignFactoryInstagramPostCaption(input, campaignFactory),
		campaignFactory.burned_caption_text,
		campaignFactory.burnedCaptionText,
		context?.caption_text,
		context?.captionText,
		manifest?.burned_caption_text,
		manifest?.burnedCaptionText,
		manifestContext?.caption_text,
		manifestContext?.captionText,
	].filter((value): value is string => typeof value === "string" && value.trim().length > 0);
}

function campaignFactoryAllowsEmptyInstagramPostCaption(
	campaignFactory: Record<string, unknown>,
): boolean {
	const manifest = recordValue(campaignFactory.handoff_manifest);
	return (
		campaignFactory.allow_empty_instagram_post_caption === true ||
		campaignFactory.allowEmptyInstagramPostCaption === true ||
		manifest?.allow_empty_instagram_post_caption === true ||
		manifest?.allowEmptyInstagramPostCaption === true
	);
}

function booleanProof(
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
	key: string,
	fallback = false,
): boolean {
	const value = campaignFactory[key] ?? manifest?.[key];
	return typeof value === "boolean" ? value : fallback;
}

function arrayValue(value: unknown): unknown[] {
	return Array.isArray(value) ? value : [];
}

function validateCampaignFactoryStoryProof(
	campaignFactory: Record<string, unknown>,
	issues: PreflightIssue[],
) {
	const manifest = recordValue(campaignFactory.handoff_manifest);
	const contentSurface = campaignContentSurface(campaignFactory);
	const igMediaType = campaignIgMediaType(campaignFactory);
	if (contentSurface !== "story" && igMediaType !== "STORIES") return;
	if (!booleanProof(campaignFactory, manifest, "storyQualityGatePassed")) {
		add(
			issues,
			"error",
			"campaign_factory",
			"campaign_factory_story_quality_failed",
			"Campaign Factory Story quality gate did not pass; do not schedule or publish this Story.",
		);
	}
	if (!booleanProof(campaignFactory, manifest, "storySourceNative")) {
		add(
			issues,
			"error",
			"campaign_factory",
			"campaign_factory_story_source_not_native",
			"Campaign Factory Story source is not marked story-native.",
		);
	}
	if (
		booleanProof(campaignFactory, manifest, "storyNoTextRequired") &&
		!booleanProof(campaignFactory, manifest, "storyNoTextPassed")
	) {
		add(
			issues,
			"error",
			"campaign_factory",
			"campaign_factory_story_no_text_failed",
			"Campaign Factory Story was requested with no rendered words but text was detected or the check failed.",
		);
	}
	if (!booleanProof(campaignFactory, manifest, "storyStyleApproved")) {
		add(
			issues,
			"error",
			"campaign_factory",
			"campaign_factory_story_style_not_approved",
			"Campaign Factory Story is missing approved story-native style metadata.",
		);
	}
	const lineageBlockers = [
		...arrayValue(campaignFactory.sourceLineageBlockers),
		...arrayValue(manifest?.sourceLineageBlockers),
	].filter((item) => String(item || "").trim().length > 0);
	if (lineageBlockers.length > 0) {
		add(
			issues,
			"error",
			"campaign_factory",
			"campaign_factory_story_source_lineage_blocked",
			`Campaign Factory Story source lineage is blocked: ${lineageBlockers.join(", ")}.`,
		);
	}
	const visualQualityStatus = stringValue(campaignFactory.visualQualityStatus || manifest?.visualQualityStatus).toLowerCase();
	if (visualQualityStatus === "rejected") {
		add(
			issues,
			"error",
			"campaign_factory",
			"campaign_factory_visual_quality_rejected",
			"Campaign Factory marked this Story visual quality as rejected.",
		);
	}
	const readiness = recordValue(campaignFactory.surfaceReadiness) || recordValue(manifest?.surfaceReadiness);
	if (readiness && readiness.canHandoff !== true) {
		add(
			issues,
			"error",
			"campaign_factory",
			"campaign_factory_surface_readiness_blocked",
			"Campaign Factory surface readiness is blocked; do not schedule or publish this Story.",
		);
	}
}

function validateCampaignFactoryContentTrustProof(
	campaignFactory: Record<string, unknown>,
	issues: PreflightIssue[],
) {
	const manifest = recordValue(campaignFactory.handoff_manifest);
	const visualQcStatus = stringValue(campaignFactory.visualQcStatus || manifest?.visualQcStatus).toLowerCase();
	const identityVerificationStatus = stringValue(
		campaignFactory.identityVerificationStatus || manifest?.identityVerificationStatus,
	).toLowerCase();
	if (!visualQcStatus || visualQcStatus === "failed" || visualQcStatus === "unavailable") {
		add(
			issues,
			"error",
			"campaign_factory",
			`campaign_factory_${visualQcStatus === "failed" ? "visual_qc_failed" : "visual_qc_unavailable"}`,
			"Campaign Factory visual QC proof did not pass; do not schedule or publish this asset.",
		);
	}
	if (!identityVerificationStatus || identityVerificationStatus === "failed" || identityVerificationStatus === "unavailable") {
		add(
			issues,
			"error",
			"campaign_factory",
			`campaign_factory_${identityVerificationStatus === "failed" ? "identity_verification_failed" : "identity_verification_unavailable"}`,
			"Campaign Factory identity verification proof did not pass; do not schedule or publish this asset.",
		);
	}
}

function nativeAudioStatusAllowsPublish(status: unknown): boolean {
	return ["attached", "verified", "skipped", "not_required"].includes(
		String(status || "")
			.trim()
			.toLowerCase(),
	);
}

function hasNativeAudioProof(audioIntent: Record<string, unknown>): boolean {
	const status = String(audioIntent.status || "")
		.trim()
		.toLowerCase();
	if (status === "skipped" || status === "not_required") return true;
	if (status !== "attached" && status !== "verified") return false;
	const selection = recordValue(audioIntent.operator_selection);
	if (!selection) return false;
	const hasNativeLocator = [
		selection.platform_audio_id,
		selection.platform_url,
		selection.native_audio_id,
		selection.native_audio_url,
		selection.audio_id,
	].some((value) => typeof value === "string" && value.trim().length > 0);
	const hasSelectedAt =
		typeof selection.selected_at === "string" &&
		selection.selected_at.trim().length > 0;
	const finalTimestampKey =
		status === "verified" ? "verified_at" : "attached_at";
	const hasFinalTimestamp =
		typeof selection[finalTimestampKey] === "string" &&
		String(selection[finalTimestampKey]).trim().length > 0;
	return hasNativeLocator && hasSelectedAt && hasFinalTimestamp;
}

function validateNativeAudioGate(
	input: PreflightInput,
	issues: PreflightIssue[],
) {
	if (input.platform !== "instagram") return;
	const campaignFactory = campaignFactoryMetadata(input);
	const audioIntent = recordValue(campaignFactory?.audio_intent);
	if (!audioIntent || audioIntent.required !== true) return;
	if (
		nativeAudioStatusAllowsPublish(audioIntent.status) &&
		hasNativeAudioProof(audioIntent)
	)
		return;
	if (nativeAudioStatusAllowsPublish(audioIntent.status)) {
		add(
			issues,
			"error",
			"audio",
			"native_audio_proof_missing",
			"Native audio must include a platform audio ID or URL plus selection and attachment/verification timestamps before this Campaign Factory post can publish.",
		);
		return;
	}
	add(
		issues,
		"error",
		"audio",
		"native_audio_unresolved",
		"Attach, verify, skip, or mark native audio not required before this Campaign Factory post can be scheduled or published.",
	);
	if (input.audioName?.trim()) {
		add(
			issues,
			"info",
			"audio",
			"audio_name_not_native_verification",
			"Renaming or labeling local audio does not satisfy the native audio gate.",
		);
	}
}

function validateCampaignFactoryGate(
	input: PreflightInput,
	issues: PreflightIssue[],
) {
	const campaignFactory = campaignFactoryMetadata(input);
	if (!campaignFactory) return;
	const assetState = String(campaignFactory.asset_state || "")
		.trim()
		.toLowerCase();
	if (!campaignFactoryAssetStateAllowsExport(assetState)) {
		add(
			issues,
			"error",
			"campaign_factory",
			"campaign_factory_not_exportable",
			`Campaign Factory asset_state must be publishable_candidate or exportable before scheduling or publishing; got ${assetState || "missing"}.`,
		);
	}
	const failures = Array.isArray(campaignFactory.publishability_failure_reasons)
		? campaignFactory.publishability_failure_reasons
				.map((reason) => String(reason || "").trim())
				.filter(Boolean)
		: [];
	for (const reason of failures) {
		add(
			issues,
			"error",
			"campaign_factory",
			"campaign_factory_publishability_failure",
			`Campaign Factory publishability is blocked: ${reason}.`,
		);
	}
	if (
		campaignFactory.quarantined === true ||
		String(campaignFactory.asset_state || "")
			.trim()
			.toLowerCase() === "invalid_retired_draft"
	) {
		add(
			issues,
			"error",
			"campaign_factory",
			"campaign_factory_asset_quarantined",
			"Campaign Factory marked this asset as quarantined or retired; do not schedule or publish it.",
		);
	}
	for (const error of validateHandoffManifestContract(campaignFactory)) {
		add(
			issues,
			"error",
			"campaign_factory",
			"campaign_factory_handoff_manifest_invalid",
			error,
		);
	}
	validateCampaignFactoryStoryProof(campaignFactory, issues);
	validateCampaignFactoryContentTrustProof(campaignFactory, issues);
	const igMediaType = normalizedIgMediaType(input);
	if (
		input.platform === "instagram" &&
		igMediaType !== "STORIES" &&
		!campaignFactoryAllowsEmptyInstagramPostCaption(campaignFactory) &&
		!campaignFactoryInstagramPostCaption(input, campaignFactory)
	) {
		add(
			issues,
			"error",
			"campaign_factory",
			"campaign_factory_instagram_post_caption_missing",
			"Campaign Factory Instagram post caption is empty. Add instagram_post_caption or explicitly allow an empty platform caption before publishing.",
		);
	}
}

function validateThreads(input: PreflightInput, issues: PreflightIssue[]) {
	const content = input.content || "";
	const media = input.media || [];
	const finalContent = buildThreadsText(content, input.topics);
	const hasMedia = media.length > 0;
	const pollCount = pollOptionCount(input.pollAttachment);

	if (Buffer.byteLength(finalContent, "utf8") > THREADS_TEXT_LIMIT) {
		add(
			issues,
			"error",
			"caption",
			"threads_caption_too_long",
			`Threads posts max out at ${THREADS_TEXT_LIMIT} characters after topic tags are added.`,
		);
	}
	const linkCount = countMatches(finalContent, URL_PATTERN);
	if (linkCount > THREADS_LINK_LIMIT) {
		add(
			issues,
			"error",
			"threads",
			"threads_too_many_links",
			`Threads allows up to ${THREADS_LINK_LIMIT} links per post; this has ${linkCount}.`,
		);
	}
	if (media.length > 20) {
		add(
			issues,
			"error",
			"threads",
			"threads_carousel_count",
			"Threads carousels support a maximum of 20 media items.",
		);
	}
	if (input.linkUrl?.trim() && hasMedia) {
		add(
			issues,
			"error",
			"threads",
			"threads_link_text_only",
			"Threads link attachments only work on text-only posts.",
		);
	}
	if (input.gifAttachment && hasMedia) {
		add(
			issues,
			"error",
			"threads",
			"threads_gif_text_only",
			"Threads GIF attachments only work on text-only posts.",
		);
	}
	if (input.textAttachment && hasMedia) {
		add(
			issues,
			"error",
			"threads",
			"threads_text_attachment_text_only",
			"Threads text attachments only work on text-only posts.",
		);
	}
	if (input.pollAttachment && hasMedia) {
		add(
			issues,
			"error",
			"threads",
			"threads_poll_text_only",
			"Threads polls only work on text-only posts.",
		);
	}
	if (input.pollAttachment && (pollCount < 2 || pollCount > 4)) {
		add(
			issues,
			"error",
			"threads",
			"threads_poll_options",
			"Threads polls require 2-4 options.",
		);
	}
	if (
		input.pollAttachment &&
		(input.linkUrl?.trim() || input.gifAttachment || input.textAttachment)
	) {
		add(
			issues,
			"error",
			"threads",
			"threads_poll_exclusive",
			"Threads polls cannot be combined with link, GIF, or text attachments.",
		);
	}
	const topicTag = input.topicTag?.trim().replace(/^#/, "");
	if (topicTag && /[.&]/.test(topicTag)) {
		add(
			issues,
			"error",
			"threads",
			"threads_topic_tag_chars",
			"Threads topic tags cannot include periods or ampersands.",
		);
	}
	if (topicTag && topicTag.length > 50) {
		add(
			issues,
			"error",
			"threads",
			"threads_topic_tag_length",
			"Threads topic tags must be 50 characters or fewer.",
		);
	}
	if (input.replyToId && input.crossreshareToIg) {
		add(
			issues,
			"warning",
			"threads",
			"threads_reply_cross_share",
			"Cross-sharing a reply to Instagram Stories may be rejected by Threads if the parent post is not eligible.",
		);
	}
	for (const item of media) {
		if (!item.url) continue;
		const kind = mediaKind(item);
		if (kind === "video" && UNSUPPORTED_VIDEO_PATTERN.test(item.url)) {
			add(
				issues,
				"error",
				"media",
				"threads_video_format",
				"Threads video publishing requires MP4/MOV-compatible video URLs.",
			);
		}
		if (kind === "image" && THREADS_UNSUPPORTED_IMAGE_PATTERN.test(item.url)) {
			add(
				issues,
				"error",
				"media",
				"threads_image_format",
				"Threads image publishing supports JPEG/PNG URLs; GIF/WebP images need conversion or a GIF attachment.",
			);
		}
	}
}

export async function runPublishPreflight(
	input: PreflightInput,
	options: {
		account?: PreflightAccountStatus | null | undefined;
		checkMediaUrls?: boolean | undefined;
	} = {},
): Promise<PreflightResult> {
	const platform = input.platform || "threads";
	const issues: PreflightIssue[] = [];

	const hasMedia = (input.media || []).length > 0;
	if (!input.content?.trim() && !(platform === "instagram" && hasMedia)) {
		add(
			issues,
			"error",
			"caption",
			"content_required",
			"Write a caption before posting.",
		);
	}

	validateAccount(input, options.account, issues);
	if (platform === "instagram") validateInstagram(input, issues);
	else validateThreads(input, issues);
	validateInstagramAccountSurfaceAccess(input, options.account, issues);
	validateCampaignFactoryGate(input, issues);
	validateNativeAudioGate(input, issues);

	if (options.checkMediaUrls) {
		const urls = (input.media || [])
			.map((item) => item.url)
			.filter((url): url is string => Boolean(url));
		if (urls.length > 0) {
			try {
				const accessibilityError = await checkMediaUrlAccessible(urls);
				if (accessibilityError) {
					add(
						issues,
						"error",
						"media",
						"media_url_inaccessible",
						accessibilityError,
					);
				}
			} catch (error) {
				logger.warn("Publish preflight media accessibility check failed", {
					error: String(error),
				});
				add(
					issues,
					"warning",
					"media",
					"media_url_check_unavailable",
					"Media URL accessibility could not be checked right now.",
				);
			}
		}
	}

	const summary = {
		errors: issues.filter((issue) => issue.severity === "error").length,
		warnings: issues.filter((issue) => issue.severity === "warning").length,
		infos: issues.filter((issue) => issue.severity === "info").length,
	};
	return {
		ok: summary.errors === 0,
		issues,
		summary,
	};
}
