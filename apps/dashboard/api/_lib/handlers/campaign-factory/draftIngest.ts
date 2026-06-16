import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, methodNotAllowed } from "../../apiResponse.js";
import { normalizeIGMediaType } from "../../instagram/shared.js";
import {
	campaignFactoryAssetStateAllowsExport,
	explainCampaignFactoryPublishability,
	validateCampaignFactoryDraftPayload,
} from "../../../../pipeline_contracts/typescript.js";
import {
	type CampaignSurfaceDraftPayload,
	validateCampaignSurfaceDraftPayload,
} from "../posts/campaignSurfaceValidation.js";

type DraftRecord = Record<string, unknown>;

type IngestValidationItem = {
	index: number;
	ok: boolean;
	blockers: string[];
	warnings: string[];
	contentSurface: string;
	igMediaType: string;
	wouldWrite: false;
};

export type CampaignFactoryDraftIngestResult = {
	schema: "threadsdashboard.campaign_factory_draft_ingest.v1";
	ok: boolean;
	campaign: string;
	acceptedDrafts: number;
	rejectedDrafts: number;
	items: IngestValidationItem[];
	contractErrors: string[];
	wouldWrite: false;
};

function recordValue(value: unknown): Record<string, unknown> | null {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: null;
}

function stringValue(value: unknown): string {
	return typeof value === "string" ? value.trim() : "";
}

function draftCampaignFactory(draft: DraftRecord): Record<string, unknown> | null {
	const metadata = recordValue(draft.metadata);
	return recordValue(metadata?.campaign_factory);
}

function handoffManifest(campaignFactory: Record<string, unknown>): Record<string, unknown> | null {
	return recordValue(campaignFactory.handoff_manifest);
}

function firstString(...values: unknown[]): string {
	for (const value of values) {
		const text = stringValue(value);
		if (text) return text;
	}
	return "";
}

function normalizeContentSurface(...values: unknown[]): string {
	const raw = firstString(...values).toLowerCase().replace(/-/g, "_");
	if (raw === "reel" || raw === "reels" || raw === "regular_reel") return "reel";
	if (raw === "story" || raw === "stories") return "story";
	if (raw === "feed_single" || raw === "image" || raw === "feed_image") return "feed_single";
	if (raw === "feed_carousel" || raw === "carousel" || raw === "carousel_album") return "feed_carousel";
	return "";
}

function normalizedSurfaceValues(...values: unknown[]): string[] {
	return [
		...new Set(values.map((value) => normalizeContentSurface(value)).filter((value) => value.length > 0)),
	];
}

function normalizedIgMediaTypeValues(...values: unknown[]): string[] {
	const normalized: string[] = [];
	for (const value of values) {
		const mediaType = normalizeIGMediaType(stringValue(value));
		if (mediaType) normalized.push(mediaType);
	}
	return [...new Set(normalized)];
}

function hasExplicitInstagramPostCaption(
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
): boolean {
	return Boolean(
		firstString(
			campaignFactory.instagram_post_caption,
			campaignFactory.instagramPostCaption,
			manifest?.instagram_post_caption,
			manifest?.instagramPostCaption,
		),
	);
}

function surfaceReadiness(campaignFactory: Record<string, unknown>, manifest: Record<string, unknown> | null): Record<string, unknown> | null {
	return recordValue(campaignFactory.surfaceReadiness) || recordValue(manifest?.surfaceReadiness);
}

function hasScheduleSafeProof(campaignFactory: Record<string, unknown>, manifest: Record<string, unknown> | null): boolean {
	const readiness = surfaceReadiness(campaignFactory, manifest);
	return readiness?.canHandoff === true || campaignFactory.scheduleSafe === true || campaignFactory.schedule_safe === true;
}

function mediaCount(draft: DraftRecord, manifest: Record<string, unknown> | null): number {
	const media = draft.media;
	if (Array.isArray(media)) return media.length;
	const mediaItems = draft.mediaItems;
	if (Array.isArray(mediaItems)) return mediaItems.length;
	const mediaUrls = draft.media_urls;
	if (Array.isArray(mediaUrls)) return mediaUrls.length;
	const manifestItems = manifest?.mediaItems || manifest?.media_items;
	if (Array.isArray(manifestItems)) return manifestItems.length;
	return 0;
}

function validateReelDraft(
	draft: DraftRecord,
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
): { blockers: string[]; warnings: string[]; igMediaType: string } {
	const blockers: string[] = [];
	const warnings: string[] = [];
	const igMediaType = normalizeIGMediaType(
		firstString(
			draft.ig_media_type,
			draft.igMediaType,
			draft.media_type,
			campaignFactory.ig_media_type,
			campaignFactory.igMediaType,
			manifest?.ig_media_type,
			manifest?.igMediaType,
		),
	);
	if (igMediaType !== "REELS") blockers.push("reel_requires_ig_media_type_reels");
	if (mediaCount(draft, manifest) !== 1) blockers.push("reel_requires_one_media_item");
	return { blockers, warnings, igMediaType: igMediaType || "" };
}

function draftPayloadForSurfaceValidator(draft: DraftRecord): CampaignSurfaceDraftPayload {
	return {
		content: stringValue(draft.content),
		content_surface: stringValue(draft.content_surface || draft.contentSurface),
		ig_media_type: stringValue(draft.ig_media_type || draft.igMediaType),
		media_type: stringValue(draft.media_type || draft.mediaType),
		media_urls: Array.isArray(draft.media_urls) ? (draft.media_urls as string[]) : null,
		mediaItems: Array.isArray(draft.mediaItems) ? (draft.mediaItems as CampaignSurfaceDraftPayload["mediaItems"]) : null,
		metadata: recordValue(draft.metadata),
	};
}

export function validateCampaignFactoryDraftIngest(value: unknown): CampaignFactoryDraftIngestResult {
	const contractErrors = validateCampaignFactoryDraftPayload(value);
	const envelope = recordValue(value);
	const campaign = stringValue(envelope?.campaign);
	const drafts = Array.isArray(envelope?.drafts) ? (envelope.drafts as unknown[]) : [];
	const items: IngestValidationItem[] = [];

	for (const [index, rawDraft] of drafts.entries()) {
		const blockers: string[] = [];
		const warnings: string[] = [];
		const draft = recordValue(rawDraft) || {};
		const campaignFactory = draftCampaignFactory(draft);
		if (!campaignFactory) {
			items.push({
				index,
				ok: false,
				blockers: ["campaign_factory_metadata_missing"],
				warnings,
				contentSurface: "",
				igMediaType: "",
				wouldWrite: false,
			});
			continue;
		}
		const manifest = handoffManifest(campaignFactory);
		const manifestVersion = Number(manifest?.manifest_version ?? manifest?.manifestVersion ?? 0);
		const contentSurface = normalizeContentSurface(
			draft.content_surface,
			draft.contentSurface,
			campaignFactory.content_surface,
			campaignFactory.contentSurface,
			manifest?.content_surface,
			manifest?.contentSurface,
		);
		const declaredSurfaces = normalizedSurfaceValues(
			draft.content_surface,
			draft.contentSurface,
			campaignFactory.content_surface,
			campaignFactory.contentSurface,
			manifest?.content_surface,
			manifest?.contentSurface,
		);
		if (declaredSurfaces.length > 1) {
			blockers.push(`content_surface_source_mismatch:${declaredSurfaces.join(":")}`);
		}
		const declaredIgMediaTypes = normalizedIgMediaTypeValues(
			draft.ig_media_type,
			draft.igMediaType,
			draft.media_type,
			campaignFactory.ig_media_type,
			campaignFactory.igMediaType,
			manifest?.ig_media_type,
			manifest?.igMediaType,
		);
		if (declaredIgMediaTypes.length > 1) {
			blockers.push(`ig_media_type_source_mismatch:${declaredIgMediaTypes.join(":")}`);
		}
		if (manifestVersion !== 2) blockers.push("handoff_manifest_v2_required");
		if (!campaignFactoryAssetStateAllowsExport(campaignFactory.asset_state)) {
			blockers.push("asset_state_not_exportable");
		}
		const publishability = explainCampaignFactoryPublishability(campaignFactory);
		if (publishability.decision !== "pass") {
			blockers.push(...publishability.reasons.map((reason) => `publishability_${reason}`));
		}
		if (!hasScheduleSafeProof(campaignFactory, manifest)) blockers.push("schedule_safe_readiness_missing_or_blocked");
		if (contentSurface !== "story" && !hasExplicitInstagramPostCaption(campaignFactory, manifest)) {
			blockers.push("instagram_post_caption_missing");
		}

		let igMediaType = "";
		if (contentSurface === "reel") {
			const reel = validateReelDraft(draft, campaignFactory, manifest);
			blockers.push(...reel.blockers);
			warnings.push(...reel.warnings);
			igMediaType = reel.igMediaType;
		} else {
			const surface = validateCampaignSurfaceDraftPayload(draftPayloadForSurfaceValidator(draft));
			blockers.push(...surface.blockers);
			warnings.push(...surface.warnings);
			igMediaType = surface.igMediaType || "";
		}
		items.push({
			index,
			ok: blockers.length === 0,
			blockers: [...new Set(blockers)].sort(),
			warnings: [...new Set(warnings)].sort(),
			contentSurface,
			igMediaType,
			wouldWrite: false,
		});
	}

	return {
		schema: "threadsdashboard.campaign_factory_draft_ingest.v1",
		ok: contractErrors.length === 0 && items.every((item) => item.ok),
		campaign,
		acceptedDrafts: items.filter((item) => item.ok).length,
		rejectedDrafts: items.filter((item) => !item.ok).length,
		items,
		contractErrors,
		wouldWrite: false,
	};
}

export default async function handleCampaignFactoryDraftIngest(
	req: VercelRequest,
	res: VercelResponse,
): Promise<VercelResponse> {
	if (req.method !== "POST") return methodNotAllowed(res);
	const result = validateCampaignFactoryDraftIngest(req.body);
	if (!result.ok) {
		return apiError(res, 422, "Campaign Factory draft ingest validation failed", {
			code: "CAMPAIGN_FACTORY_DRAFT_INGEST_REJECTED",
			extra: result,
		});
	}
	return apiSuccess(res, result);
}
