import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, methodNotAllowed } from "../../apiResponse.js";
import { normalizeIGMediaType } from "../../instagram/shared.js";
import { getSupabaseAny } from "../../supabase.js";
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
	wouldWrite: boolean;
	postId?: string;
	writeAction?: "validated" | "inserted" | "updated";
};

export type CampaignFactoryDraftIngestResult = {
	schema: "threadsdashboard.campaign_factory_draft_ingest.v1";
	ok: boolean;
	campaign: string;
	acceptedDrafts: number;
	rejectedDrafts: number;
	items: IngestValidationItem[];
	contractErrors: string[];
	wouldWrite: boolean;
	dryRun: boolean;
	writtenDrafts: number;
	postIds: string[];
};

type SupabaseLike = {
	from: (table: string) => {
		select: (columns?: string) => unknown;
		insert: (row: Record<string, unknown>) => unknown;
		update: (row: Record<string, unknown>) => unknown;
	};
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

function instagramPostCaption(
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
): string {
	return firstString(
		campaignFactory.instagram_post_caption,
		campaignFactory.instagramPostCaption,
		manifest?.instagram_post_caption,
		manifest?.instagramPostCaption,
	);
}

function statusValue(...values: unknown[]): string {
	for (const value of values) {
		const text = stringValue(value).toLowerCase();
		if (text) return text;
	}
	return "";
}

function proofObject(...values: unknown[]): Record<string, unknown> {
	for (const value of values) {
		const record = recordValue(value);
		if (record) return record;
	}
	return {};
}

function visualQcStatus(
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
): string {
	const visualQc = proofObject(
		campaignFactory.visualQc,
		campaignFactory.visual_qc,
		manifest?.visualQc,
		manifest?.visual_qc,
	);
	return statusValue(
		campaignFactory.visualQcStatus,
		campaignFactory.visual_qc_status,
		manifest?.visualQcStatus,
		manifest?.visual_qc_status,
		visualQc.visualQcStatus,
		visualQc.visual_qc_status,
		visualQc.status,
	);
}

function identityVerificationStatus(
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
): string {
	const identity = proofObject(
		campaignFactory.identityVerification,
		campaignFactory.identity_verification,
		manifest?.identityVerification,
		manifest?.identity_verification,
	);
	return statusValue(
		campaignFactory.identityVerificationStatus,
		campaignFactory.identity_verification_status,
		manifest?.identityVerificationStatus,
		manifest?.identity_verification_status,
		identity.identityVerificationStatus,
		identity.identity_verification_status,
		identity.status,
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

function mediaUrls(draft: DraftRecord, manifest: Record<string, unknown> | null): string[] {
	const urls: string[] = [];
	for (const value of [draft.media, draft.mediaItems, draft.media_urls, manifest?.mediaItems, manifest?.media_items]) {
		if (!Array.isArray(value)) continue;
		for (const item of value) {
			if (typeof item === "string" && item.trim()) {
				urls.push(item.trim());
			} else if (item && typeof item === "object") {
				const record = item as Record<string, unknown>;
				const url = firstString(record.url, record.publicUrl, record.public_url, record.file_url, record.storage_url);
				if (url) urls.push(url);
			}
		}
	}
	return [...new Set(urls)];
}

function bodyDryRun(value: unknown): boolean {
	const envelope = recordValue(value);
	return envelope?.dryRun === false ? false : true;
}

function ingestSecretFromRequest(req: VercelRequest): string {
	const header = req.headers["x-campaign-factory-ingest-secret"];
	if (typeof header === "string" && header.trim()) return header.trim();
	const authorization = req.headers.authorization;
	const match = typeof authorization === "string" ? authorization.match(/^Bearer\s+(.+)$/i) : null;
	return match?.[1]?.trim() || "";
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
		const visualStatus = visualQcStatus(campaignFactory, manifest);
		if (visualStatus !== "passed") {
			blockers.push(visualStatus ? `visual_qc_${visualStatus}` : "visual_qc_unavailable");
		}
		const identityStatus = identityVerificationStatus(campaignFactory, manifest);
		if (identityStatus !== "passed") {
			blockers.push(identityStatus ? `identity_verification_${identityStatus}` : "identity_verification_unavailable");
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
			writeAction: "validated",
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
		dryRun: true,
		writtenDrafts: 0,
		postIds: [],
	};
}

function postKeyForDraft(
	draft: DraftRecord,
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
): string {
	return firstString(
		draft.campaignFactoryPostKey,
		draft.campaign_factory_post_key,
		campaignFactory.post_key,
		campaignFactory.draft_key,
		campaignFactory.rendered_asset_id,
		campaignFactory.asset_id,
		manifest?.asset_id,
		manifest?.rendered_asset_id,
	);
}

function userIdForDraft(envelope: Record<string, unknown>, draft: DraftRecord): string {
	return firstString(draft.userId, draft.user_id, envelope.userId, envelope.user_id);
}

function draftPostRow(
	envelope: Record<string, unknown>,
	draft: DraftRecord,
	campaignFactory: Record<string, unknown>,
	manifest: Record<string, unknown> | null,
): { row: Record<string, unknown>; postKey: string } {
	const postKey = postKeyForDraft(draft, campaignFactory, manifest);
	const userId = userIdForDraft(envelope, draft);
	if (!userId) throw new Error("user_id_missing_for_write");
	if (!postKey) throw new Error("campaign_factory_post_key_missing_for_write");
	const contentSurface = normalizeContentSurface(
		draft.content_surface,
		draft.contentSurface,
		campaignFactory.content_surface,
		campaignFactory.contentSurface,
		manifest?.content_surface,
		manifest?.contentSurface,
	);
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
	const metadata = recordValue(draft.metadata) || {};
	const urls = mediaUrls(draft, manifest);
	return {
		postKey,
		row: {
			user_id: userId,
			account_id: firstString(draft.accountId, draft.account_id) || null,
			instagram_account_id: firstString(draft.instagramAccountId, draft.instagram_account_id) || null,
			platform: "instagram",
			content: instagramPostCaption(campaignFactory, manifest),
			media_urls: urls,
			media_type: contentSurface === "reel" ? "video" : "image",
			ig_media_type: igMediaType,
			content_surface: contentSurface,
			status: "draft",
			hashtags: Array.isArray(draft.hashtags) ? draft.hashtags : Array.isArray(draft.topics) ? draft.topics : [],
			source: "campaign_factory",
			metadata,
			scheduled_for: null,
			campaign_factory_asset_id: firstString(campaignFactory.rendered_asset_id, campaignFactory.asset_id),
			campaign_factory_distribution_plan_id: firstString(campaignFactory.distribution_plan_id, draft.distributionPlanId),
			campaign_factory_post_key: postKey,
			campaign_factory_content_fingerprint: firstString(campaignFactory.content_fingerprint, campaignFactory.contentFingerprint),
			campaign_factory_caption_hash: firstString(campaignFactory.caption_hash, draft.captionHash),
			campaign_factory_concept_id: firstString(campaignFactory.concept_id, campaignFactory.conceptId) || null,
			campaign_factory_parent_asset_id: firstString(campaignFactory.parent_asset_id, campaignFactory.parentAssetId) || null,
			campaign_factory_variant_family_id: firstString(campaignFactory.variant_family_id, campaignFactory.variantFamilyId) || null,
			campaign_factory_variant_id: firstString(campaignFactory.variant_id, campaignFactory.variantId) || null,
			platform_draft_validated: true,
		},
	};
}

async function maybeSingle<T>(query: unknown): Promise<{ data: T | null; error?: { message?: string } | null }> {
	const q = query as {
		eq?: (column: string, value: unknown) => unknown;
		maybeSingle?: () => Promise<{ data: T | null; error?: { message?: string } | null }>;
	};
	if (!q.maybeSingle) return { data: null, error: null };
	const result = await q.maybeSingle();
	return result || { data: null, error: null };
}

async function selectExistingPost(
	db: SupabaseLike,
	userId: string,
	postKey: string,
): Promise<Record<string, unknown> | null> {
	const query = db.from("posts").select("id,status,campaign_factory_post_key,user_id") as {
		eq?: (column: string, value: unknown) => unknown;
	};
	let chained: unknown = query;
	if (query.eq) chained = query.eq("user_id", userId);
	if ((chained as { eq?: (column: string, value: unknown) => unknown }).eq) {
		chained = (chained as { eq: (column: string, value: unknown) => unknown }).eq("campaign_factory_post_key", postKey);
	}
	const result = await maybeSingle<Record<string, unknown>>(chained);
	if (result.error) throw new Error(result.error.message || "campaign_factory_ingest_select_failed");
	return result.data;
}

async function mutatePost(
	db: SupabaseLike,
	existing: Record<string, unknown> | null,
	row: Record<string, unknown>,
): Promise<{ id: string; action: "inserted" | "updated" }> {
	if (existing?.id) {
		const query = db.from("posts").update(row) as {
			eq?: (column: string, value: unknown) => unknown;
			select?: (columns?: string) => unknown;
		};
		let chained: unknown = query;
		if (query.eq) chained = query.eq("id", existing.id);
		if ((chained as { select?: (columns?: string) => unknown }).select) {
			chained = (chained as { select: (columns?: string) => unknown }).select("id");
		}
		const result = await maybeSingle<Record<string, unknown>>(chained);
		if (result.error) throw new Error(result.error.message || "campaign_factory_ingest_update_failed");
		return { id: String(result.data?.id || existing.id), action: "updated" };
	}
	const query = db.from("posts").insert(row) as {
		select?: (columns?: string) => unknown;
	};
	let chained: unknown = query;
	if (query.select) chained = query.select("id");
	const result = await maybeSingle<Record<string, unknown>>(chained);
	if (result.error) throw new Error(result.error.message || "campaign_factory_ingest_insert_failed");
	return { id: String(result.data?.id || ""), action: "inserted" };
}

export async function writeCampaignFactoryDraftIngest(
	value: unknown,
	db: SupabaseLike = getSupabaseAny(),
): Promise<CampaignFactoryDraftIngestResult> {
	const validation = validateCampaignFactoryDraftIngest(value);
	if (!validation.ok) return validation;
	const envelope = recordValue(value) || {};
	const drafts = Array.isArray(envelope.drafts) ? (envelope.drafts as unknown[]) : [];
	const items: IngestValidationItem[] = [];
	const postIds: string[] = [];
	for (const [index, rawDraft] of drafts.entries()) {
		const draft = recordValue(rawDraft) || {};
		const campaignFactory = draftCampaignFactory(draft);
		if (!campaignFactory) throw new Error("campaign_factory_metadata_missing");
		const manifest = handoffManifest(campaignFactory);
		const { row, postKey } = draftPostRow(envelope, draft, campaignFactory, manifest);
		const existing = await selectExistingPost(db, String(row.user_id), postKey);
		const mutation = await mutatePost(db, existing, row);
		const validationItem = validation.items[index];
		if (!validationItem) throw new Error("campaign_factory_validation_item_missing");
		postIds.push(mutation.id);
		items.push({
			...validationItem,
			wouldWrite: true,
			postId: mutation.id,
			writeAction: mutation.action,
		});
	}
	return {
		...validation,
		items,
		wouldWrite: true,
		dryRun: false,
		writtenDrafts: items.length,
		postIds,
	};
}

export default async function handleCampaignFactoryDraftIngest(
	req: VercelRequest,
	res: VercelResponse,
): Promise<VercelResponse> {
	if (req.method !== "POST") return methodNotAllowed(res);
	const dryRun = bodyDryRun(req.body);
	if (!dryRun) {
		const expected = stringValue(process.env.CAMPAIGN_FACTORY_INGEST_SECRET);
		if (!expected) {
			return apiError(res, 503, "Campaign Factory ingest writes are not configured", {
				code: "CAMPAIGN_FACTORY_INGEST_SECRET_MISSING",
			});
		}
		if (ingestSecretFromRequest(req) !== expected) {
			return apiError(res, 401, "Campaign Factory ingest secret is invalid", {
				code: "CAMPAIGN_FACTORY_INGEST_UNAUTHORIZED",
			});
		}
	}
	const result = dryRun
		? validateCampaignFactoryDraftIngest(req.body)
		: await writeCampaignFactoryDraftIngest(req.body);
	if (!result.ok) {
		return apiError(res, 422, "Campaign Factory draft ingest validation failed", {
			code: "CAMPAIGN_FACTORY_DRAFT_INGEST_REJECTED",
			extra: result,
		});
	}
	return apiSuccess(res, result);
}
