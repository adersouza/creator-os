import { normalizeIGMediaType } from "../../instagram/shared.js";
import { validateDiscoverabilitySafeContent } from "../../discoverabilitySafety.js";

export type CampaignContentSurface = "feed_single" | "story" | "feed_carousel";

export interface CampaignSurfaceMediaItem {
	type?: string | null | undefined;
	url?: string | null | undefined;
	altText?: string | null | undefined;
}

export interface CampaignSurfaceDraftPayload {
	content?: string | null | undefined;
	content_surface?: string | null | undefined;
	ig_media_type?: string | null | undefined;
	media_type?: string | null | undefined;
	media_urls?: string[] | null | undefined;
	mediaItems?: CampaignSurfaceMediaItem[] | null | undefined;
	metadata?: Record<string, unknown> | null | undefined;
	campaign_factory?: Record<string, unknown> | null | undefined;
}

export interface CampaignSurfaceDraftValidationResult {
	ok: boolean;
	contentSurface: CampaignContentSurface | null;
	igMediaType: "IMAGE" | "STORIES" | "CAROUSEL" | null;
	mediaItemCount: number;
	blockers: string[];
	warnings: string[];
	discoverabilitySafe: boolean;
	blockedTerms: Array<{ reason: string; matchedText: string }>;
	blockedReason: string;
	preservedFields: {
		handoffManifestV2: boolean;
		orderedMediaItems: boolean;
		instagramPostCaption: boolean;
		discoverabilitySafe: boolean;
	};
	wouldWrite: false;
}

const SURFACE_TO_IG_MEDIA_TYPE: Record<CampaignContentSurface, "IMAGE" | "STORIES" | "CAROUSEL"> = {
	feed_single: "IMAGE",
	story: "STORIES",
	feed_carousel: "CAROUSEL",
};

function recordValue(value: unknown): Record<string, unknown> | null {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function stringValue(value: unknown): string {
	return typeof value === "string" ? value.trim() : "";
}

function normalizeSurface(value: unknown): CampaignContentSurface | null {
	const raw = stringValue(value).toLowerCase();
	if (raw === "feed_single" || raw === "image" || raw === "feed_image") return "feed_single";
	if (raw === "story" || raw === "stories") return "story";
	if (raw === "feed_carousel" || raw === "carousel" || raw === "carousel_album") return "feed_carousel";
	return null;
}

function campaignFactoryPayload(payload: CampaignSurfaceDraftPayload): Record<string, unknown> {
	if (payload.campaign_factory && typeof payload.campaign_factory === "object") {
		return payload.campaign_factory;
	}
	const metadata = recordValue(payload.metadata);
	const campaignFactory = recordValue(metadata?.campaign_factory);
	return campaignFactory ?? {};
}

function campaignManifest(campaignFactory: Record<string, unknown>): Record<string, unknown> | null {
	return recordValue(campaignFactory.handoff_manifest);
}

function manifestString(manifest: Record<string, unknown> | null, ...keys: string[]): string {
	if (!manifest) return "";
	for (const key of keys) {
		const value = stringValue(manifest[key]);
		if (value) return value;
	}
	return "";
}

function payloadMediaItems(payload: CampaignSurfaceDraftPayload, manifest: Record<string, unknown> | null): CampaignSurfaceMediaItem[] {
	const explicit = Array.isArray(payload.mediaItems) ? payload.mediaItems : null;
	if (explicit) return explicit;
	const manifestItems = manifest?.mediaItems ?? manifest?.media_items;
	if (Array.isArray(manifestItems)) {
		return manifestItems.filter((item): item is CampaignSurfaceMediaItem => !!recordValue(item));
	}
	return (payload.media_urls ?? [])
		.filter((url): url is string => typeof url === "string" && url.trim().length > 0)
		.map((url) => ({ url }));
}

function mediaKind(item: CampaignSurfaceMediaItem): "image" | "video" | "unknown" {
	const type = stringValue(item.type).toLowerCase();
	const url = stringValue(item.url);
	if (type.includes("video") || /\.(mp4|mov)(\?|$)/i.test(url)) return "video";
	if (type.includes("image") || /\.(jpe?g|png|bmp|heic|heif)(\?|$)/i.test(url)) return "image";
	return "unknown";
}

function hasInstagramPostCaption(payload: CampaignSurfaceDraftPayload, campaignFactory: Record<string, unknown>, manifest: Record<string, unknown> | null): boolean {
	return Boolean(
		stringValue(campaignFactory.instagram_post_caption) ||
			stringValue(campaignFactory.instagramPostCaption) ||
			manifestString(manifest, "instagram_post_caption", "instagramPostCaption") ||
			stringValue(payload.content),
	);
}

function discoverabilityTexts(
	payload: CampaignSurfaceDraftPayload,
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
): string[] {
	return [
		payload.content,
		campaignFactory.instagram_post_caption,
		campaignFactory.instagramPostCaption,
		campaignFactory.burned_caption_text,
		campaignFactory.burnedCaptionText,
		campaignFactory.story_text,
		campaignFactory.storyText,
		campaignFactory.story_cta_text,
		campaignFactory.storyCtaText,
		campaignFactory.cta_text,
		campaignFactory.ctaText,
		manifestString(manifest, "instagram_post_caption", "instagramPostCaption"),
		manifestString(manifest, "burned_caption_text", "burnedCaptionText"),
		manifestString(manifest, "story_text", "storyText"),
		manifestString(manifest, "story_cta_text", "storyCtaText"),
	]
		.filter((value): value is string => typeof value === "string")
		.filter((value) => value.trim().length > 0);
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

function storySurfaceReadiness(
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
): Record<string, unknown> | null {
	return recordValue(campaignFactory.surfaceReadiness) || recordValue(manifest?.surfaceReadiness);
}

function storyProofBlockers(
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
): string[] {
	const blockers: string[] = [];
	if (!booleanProof(campaignFactory, manifest, "storyQualityGatePassed")) {
		blockers.push("story_quality_gate_failed");
	}
	if (!booleanProof(campaignFactory, manifest, "storySourceNative")) {
		blockers.push("story_source_not_native");
	}
	if (
		booleanProof(campaignFactory, manifest, "storyNoTextRequired") &&
		!booleanProof(campaignFactory, manifest, "storyNoTextPassed")
	) {
		blockers.push("story_no_text_failed");
	}
	if (!booleanProof(campaignFactory, manifest, "storyStyleApproved")) {
		blockers.push("story_style_not_approved");
	}
	const lineageBlockers = [
		...arrayValue(campaignFactory.sourceLineageBlockers),
		...arrayValue(manifest?.sourceLineageBlockers),
	].filter((item) => String(item || "").trim().length > 0);
	if (lineageBlockers.length > 0) {
		blockers.push("story_source_lineage_blocked");
	}
	const visualQualityStatus = stringValue(campaignFactory.visualQualityStatus || manifest?.visualQualityStatus).toLowerCase();
	if (visualQualityStatus === "rejected") {
		blockers.push("story_visual_quality_rejected");
	}
	const readiness = storySurfaceReadiness(campaignFactory, manifest);
	if (readiness && readiness.canHandoff !== true) {
		blockers.push("surface_readiness_blocked");
	}
	return blockers;
}

/**
 * Dry-run validation for Campaign Factory non-Reel surface drafts.
 *
 * This helper deliberately has no database, scheduler, or publisher side effects.
 * It validates only the payload contract ThreadsDashboard must preserve before
 * live feed/story/carousel publishing can be enabled.
 */
export function validateCampaignSurfaceDraftPayload(
	payload: CampaignSurfaceDraftPayload,
): CampaignSurfaceDraftValidationResult {
	const campaignFactory = campaignFactoryPayload(payload);
	const manifest = campaignManifest(campaignFactory);
	const manifestVersion = Number(manifest?.manifest_version ?? manifest?.manifestVersion ?? 0);
	const contentSurface =
		normalizeSurface(payload.content_surface) ||
		normalizeSurface((payload as Record<string, unknown>).contentSurface) ||
		normalizeSurface(campaignFactory.content_surface) ||
		normalizeSurface(campaignFactory.contentSurface) ||
		normalizeSurface(manifest?.content_surface) ||
		normalizeSurface(manifest?.contentSurface);
	const expectedIgMediaType = contentSurface ? SURFACE_TO_IG_MEDIA_TYPE[contentSurface] : null;
	const explicitIgMediaType = normalizeIGMediaType(
		stringValue(payload.ig_media_type) ||
			stringValue((payload as Record<string, unknown>).igMediaType) ||
			stringValue(campaignFactory.ig_media_type) ||
			stringValue(campaignFactory.igMediaType) ||
			manifestString(manifest, "ig_media_type", "igMediaType") ||
			stringValue(payload.media_type),
	);
	const mediaItems = payloadMediaItems(payload, manifest);
	const blockers: string[] = [];
	const warnings: string[] = [];
	const discoverability = validateDiscoverabilitySafeContent(
		...discoverabilityTexts(payload, campaignFactory, manifest),
	);

	if (!contentSurface) blockers.push("content_surface_missing_or_invalid");
	if (!expectedIgMediaType || !explicitIgMediaType) blockers.push("ig_media_type_unresolvable");
	if (explicitIgMediaType && expectedIgMediaType && explicitIgMediaType !== expectedIgMediaType) {
		blockers.push(`ig_media_type_surface_mismatch:${explicitIgMediaType}:${expectedIgMediaType}`);
	}
	if (!manifest) blockers.push("handoff_manifest_missing");
	if (manifest && manifestVersion !== 2) blockers.push("handoff_manifest_v2_required");
	if (manifest && manifest.exported_by_system !== "campaign_factory") blockers.push("handoff_manifest_exported_by_system_invalid");

	if (mediaItems.length === 0) blockers.push("media_items_required");
	for (const [index, item] of mediaItems.entries()) {
		if (!stringValue(item.url)) blockers.push(`media_item_${index}_url_missing`);
		if (mediaKind(item) === "unknown") warnings.push(`media_item_${index}_type_unknown`);
	}

	if (contentSurface === "feed_single") {
		if (mediaItems.length !== 1) blockers.push("feed_single_requires_one_media_item");
		if (mediaItems[0] && mediaKind(mediaItems[0]) !== "image") blockers.push("feed_single_requires_image_media");
		if (!hasInstagramPostCaption(payload, campaignFactory, manifest)) blockers.push("feed_single_instagram_post_caption_missing");
	}

		if (contentSurface === "story") {
			if (mediaItems.length !== 1) blockers.push("story_requires_one_media_item");
			if (mediaItems[0] && !["image", "video"].includes(mediaKind(mediaItems[0]))) blockers.push("story_requires_image_or_video_media");
			blockers.push(...storyProofBlockers(campaignFactory, manifest));
		}

	if (contentSurface === "feed_carousel") {
		if (mediaItems.length < 2 || mediaItems.length > 10) blockers.push("feed_carousel_requires_2_to_10_media_items");
		if (!Array.isArray(manifest?.mediaItems) && !Array.isArray(manifest?.media_items)) {
			blockers.push("feed_carousel_ordered_media_items_missing");
		}
		if (!hasInstagramPostCaption(payload, campaignFactory, manifest)) blockers.push("feed_carousel_instagram_post_caption_missing");
	}
	if (!discoverability.discoverabilitySafe) blockers.push("discoverability_safety_failed");

	return {
		ok: blockers.length === 0,
		contentSurface,
		igMediaType: expectedIgMediaType,
		mediaItemCount: mediaItems.length,
		blockers,
		warnings,
		discoverabilitySafe: discoverability.discoverabilitySafe,
		blockedTerms: discoverability.blockedTerms,
		blockedReason: discoverability.blockedReason,
		preservedFields: {
			handoffManifestV2: !!manifest && manifestVersion === 2,
			orderedMediaItems: Array.isArray(manifest?.mediaItems) || Array.isArray(manifest?.media_items),
			instagramPostCaption: hasInstagramPostCaption(payload, campaignFactory, manifest),
			discoverabilitySafe: discoverability.discoverabilitySafe,
		},
		wouldWrite: false,
	};
}
