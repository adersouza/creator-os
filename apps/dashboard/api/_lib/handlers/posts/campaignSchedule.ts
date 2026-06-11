// biome-ignore-all lint/suspicious/noExplicitAny: Supabase generated types do not include Campaign scheduling columns yet.
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { isAccountPublishable } from "../../accountEligibility.js";
import { runPublishPreflight, type PreflightMediaItem } from "../../publishPreflight.js";
import { getSupabaseAny } from "../../supabase.js";
import { parseBodyOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";
import { resolveInstagramTrialReelIntent } from "../../instagramTrialReels.js";
import { validateCampaignSurfaceDraftPayload } from "./campaignSurfaceValidation.js";
import { restrictionProjectionsForUser } from "../../instagramAccountRestrictions.js";

const db = () => getSupabaseAny();

const MIN_SCHEDULE_LEAD_MS = 2 * 60 * 1000;
const DEFAULT_MISSED_GRACE_MS = 5 * 60 * 1000;
const DEFAULT_VARIANT_SIBLING_COOLDOWN_DAYS = 14;
const DEFAULT_PARENT_REEL_COOLDOWN_DAYS = 14;
const DEFAULT_PARENT_ASSET_COOLDOWN_DAYS = 14;
const DEFAULT_SOURCE_ASSET_COOLDOWN_DAYS = 14;
const CAMPAIGN_DUPLICATE_STATUSES = ["draft", "scheduled", "publishing", "published"];

const CampaignScheduleItemSchema = z.object({
	postId: z.string().min(1),
	scheduledFor: z.string().min(1),
});

const CampaignScheduleSchema = z.object({
	dryRun: z.boolean().optional(),
	items: z.array(CampaignScheduleItemSchema).min(1).max(100),
	batchMetadata: z.record(z.unknown()).optional(),
});

const CampaignSchedulePlanSchema = z.object({
	creator: z.string().optional(),
	requestedCount: z.number().int().min(1).max(100).optional(),
	startAt: z.string().optional(),
	jitterMinutes: z.object({
		min: z.number().int().min(0).optional(),
		max: z.number().int().min(0).optional(),
	}).optional(),
});

const CampaignScheduleTimePlanSchema = z.object({
	creator: z.string().optional(),
	requestedCount: z.number().int().min(1).max(100).optional(),
	startAt: z.string().optional(),
	timezone: z.string().optional(),
	defaultWindow: z.string().optional(),
	minimumSpacingMinutes: z.number().int().min(1).max(180).optional(),
});

type CampaignScheduleItem = {
	postId: string;
	scheduledFor: string;
};

type CampaignMeta = Record<string, any>;
type CampaignRecoveryMode =
	| "reset_to_draft"
	| "reschedule"
	| "recover_same_row_publish";
type AccountBucket =
	| "safe_to_schedule_today"
	| "already_scheduled_today"
	| "blocked_reauth"
	| "blocked_token_expired"
	| "blocked_disabled"
	| "blocked_recent_failure"
	| "blocked_account_health"
	| "blocked_unknown";
type AccountCadenceState = "warming" | "normal" | "high-performing" | "resting" | "blocked";

function parseScheduleDate(value: string): { date: Date | null; error?: string | undefined; code?: string | undefined } {
	const date = new Date(value);
	if (Number.isNaN(date.getTime())) {
		return { date: null, error: "scheduledFor must be a valid ISO date", code: "INVALID_SCHEDULE_DATE" };
	}
	if (date.getTime() - Date.now() < MIN_SCHEDULE_LEAD_MS) {
		return { date: null, error: "scheduledFor must be at least 2 minutes in the future", code: "SCHEDULE_TOO_SOON" };
	}
	return { date };
}

function campaignMeta(post: Record<string, any>): CampaignMeta {
	const metadata = post.metadata && typeof post.metadata === "object" ? post.metadata : {};
	const campaignFactory = metadata.campaign_factory;
	return campaignFactory && typeof campaignFactory === "object" && !Array.isArray(campaignFactory)
		? campaignFactory
		: {};
}

function campaignString(meta: CampaignMeta, ...keys: string[]): string | null {
	for (const key of keys) {
		const value = meta[key];
		if (typeof value === "string" && value.trim()) return value.trim();
	}
	return null;
}

function requestString(req: VercelRequest, key: string): string | null {
	const queryValue = req.query?.[key];
	if (typeof queryValue === "string" && queryValue.trim()) return queryValue.trim();
	if (Array.isArray(queryValue) && typeof queryValue[0] === "string" && queryValue[0].trim()) return queryValue[0].trim();
	const bodyValue = req.body?.[key];
	if (typeof bodyValue === "string" && bodyValue.trim()) return bodyValue.trim();
	return null;
}

function requestNumber(req: VercelRequest, key: string): number | null {
	const raw = requestString(req, key);
	if (!raw) return null;
	const parsed = Number(raw);
	return Number.isFinite(parsed) ? parsed : null;
}

function normalizeCreator(value: string | null | undefined): string | null {
	if (!value) return null;
	const normalized = value.trim().toLowerCase();
	if (!normalized) return null;
	if (normalized.includes("stacey") || normalized.includes("bennett")) return "Stacey";
	if (normalized.includes("larissa")) return "Larissa";
	if (normalized.includes("lola")) return "Lola";
	return value.trim();
}

function inferCreator(account: Record<string, any>, group: Record<string, any> | null): { creator: string | null; source: string | null } {
	const groupCreator = normalizeCreator(group?.name);
	if (groupCreator) return { creator: groupCreator, source: "account_group_name" };
	const usernameCreator = normalizeCreator(account.username);
	if (usernameCreator) return { creator: usernameCreator, source: "username_hint" };
	return { creator: null, source: null };
}

function accountBucket(input: {
	eligible: boolean;
	eligibilityReason?: string | undefined;
	hasScheduleToday: boolean;
	hasRecentFailure: boolean;
	accountHealthBlockers?: string[] | undefined;
}): { bucket: AccountBucket; blockingReason: string | null; safeToSchedule: boolean; needsPostToday: boolean } {
	if (input.hasScheduleToday) {
		return {
			bucket: "already_scheduled_today",
			blockingReason: "already_scheduled_today",
			safeToSchedule: false,
			needsPostToday: false,
		};
	}
	if (input.hasRecentFailure) {
		return {
			bucket: "blocked_recent_failure",
			blockingReason: "recent_publish_failure",
			safeToSchedule: false,
			needsPostToday: true,
		};
	}
	if ((input.accountHealthBlockers ?? []).length > 0) {
		return {
			bucket: "blocked_account_health",
			blockingReason: input.accountHealthBlockers?.[0] ?? "account_health_blocked",
			safeToSchedule: false,
			needsPostToday: true,
		};
	}
	if (!input.eligible) {
		if (input.eligibilityReason === "needs_reauth") {
			return { bucket: "blocked_reauth", blockingReason: "needs_reauth", safeToSchedule: false, needsPostToday: true };
		}
		if (input.eligibilityReason === "token_expired") {
			return { bucket: "blocked_token_expired", blockingReason: "token_expired", safeToSchedule: false, needsPostToday: true };
		}
		if (input.eligibilityReason === "account_inactive" || input.eligibilityReason === "suspended") {
			return { bucket: "blocked_disabled", blockingReason: input.eligibilityReason, safeToSchedule: false, needsPostToday: true };
		}
		return { bucket: "blocked_unknown", blockingReason: input.eligibilityReason || "account_not_publishable", safeToSchedule: false, needsPostToday: true };
	}
	return { bucket: "safe_to_schedule_today", blockingReason: null, safeToSchedule: true, needsPostToday: true };
}

function stableJitterMinutes(index: number, min: number, max: number): number {
	const normalizedMin = Math.max(0, min);
	const normalizedMax = Math.max(normalizedMin, max);
	const span = normalizedMax - normalizedMin + 1;
	return normalizedMin + ((index * 7) % span);
}

function mediaItems(post: Record<string, any>): PreflightMediaItem[] {
	const mediaUrls = Array.isArray(post.media_urls) ? post.media_urls : [];
	return mediaUrls
		.map((url: unknown): PreflightMediaItem | null => {
			if (typeof url !== "string" || !url.trim()) return null;
			return {
				url,
				type: /\.(mp4|mov)(\?|$)/i.test(url) ? "video" : undefined,
			};
		})
		.filter((item: PreflightMediaItem | null): item is PreflightMediaItem => item !== null);
}

function normalizeCampaignContentSurface(value: unknown): string | null {
	const raw = typeof value === "string" ? value.trim().toLowerCase() : "";
	if (!raw) return null;
	if (raw === "reel" || raw === "reels") return "reel";
	if (raw === "story" || raw === "stories") return "story";
	if (raw === "feed_single" || raw === "image" || raw === "feed_image") return "feed_single";
	if (raw === "feed_carousel" || raw === "carousel" || raw === "carousel_album") return "feed_carousel";
	return null;
}

function campaignManifest(meta: CampaignMeta): Record<string, any> | null {
	const manifest = meta.handoff_manifest;
	return manifest && typeof manifest === "object" && !Array.isArray(manifest)
		? manifest
		: null;
}

function resolvedCampaignSurface(post: Record<string, any>, meta: CampaignMeta): string | null {
	const manifest = campaignManifest(meta);
	return (
		normalizeCampaignContentSurface(post.content_surface) ||
		normalizeCampaignContentSurface(meta.content_surface) ||
		normalizeCampaignContentSurface(meta.contentSurface) ||
		normalizeCampaignContentSurface(manifest?.content_surface) ||
		normalizeCampaignContentSurface(manifest?.contentSurface) ||
		(post.ig_media_type === "REELS" ? "reel" : null) ||
		(Number(manifest?.manifest_version ?? 0) === 1 ? "reel" : null)
	);
}

function resolvedCampaignIgMediaType(post: Record<string, any>, meta: CampaignMeta): string | null {
	const manifest = campaignManifest(meta);
	const raw =
		post.ig_media_type ||
		meta.ig_media_type ||
		meta.igMediaType ||
		manifest?.ig_media_type ||
		manifest?.igMediaType;
	return typeof raw === "string" && raw.trim() ? raw.trim().toUpperCase() : null;
}

function validateManifest(meta: CampaignMeta, post: Record<string, any>): string[] {
	const blockers: string[] = [];
	const assetState = String(meta.asset_state || "").trim().toLowerCase();
	if (!["publishable_candidate", "exportable"].includes(assetState)) {
		blockers.push(`asset_state_not_exportable:${assetState || "missing"}`);
	}
	if (meta.quarantined === true) blockers.push("quarantined_asset");
	if (Array.isArray(meta.publishability_failure_reasons) && meta.publishability_failure_reasons.length > 0) {
		blockers.push("publishability_failure_reasons_present");
	}
	const manifest = meta.handoff_manifest;
	if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) {
		blockers.push("handoff_manifest_missing");
		return blockers;
	}
	const manifestVersion = Number(manifest.manifest_version ?? manifest.manifestVersion ?? 0);
	const surface = resolvedCampaignSurface(post, meta);
	const igMediaType = resolvedCampaignIgMediaType(post, meta);
	if (!surface) blockers.push("content_surface_missing");
	if (!igMediaType) blockers.push("ig_media_type_missing");
	if (manifestVersion === 2) {
		const surfaceValidation = validateCampaignSurfaceDraftPayload({
			content: post.content,
			content_surface: surface,
			ig_media_type: igMediaType,
			media_type: post.media_type,
			media_urls: Array.isArray(post.media_urls) ? post.media_urls : [],
			metadata: post.metadata,
		});
		blockers.push(...surfaceValidation.blockers);
		return Array.from(new Set(blockers));
	}
	if (manifestVersion !== 1) blockers.push("handoff_manifest_version_invalid");
	if (surface !== "reel") blockers.push("handoff_manifest_v2_required_for_surface");
	if (igMediaType !== "REELS") blockers.push("reel_surface_requires_reels_media_type");
	if (manifest.exported_by_system !== "campaign_factory") blockers.push("handoff_manifest_exported_by_system_invalid");
	const assetId = campaignString(meta, "asset_id", "rendered_asset_id") || post.campaign_factory_asset_id;
	if (assetId && manifest.asset_id !== assetId) blockers.push("handoff_manifest_asset_id_mismatch");
	const contentFingerprint = campaignString(meta, "content_fingerprint", "content_hash") || post.campaign_factory_content_fingerprint;
	if (contentFingerprint && manifest.content_fingerprint !== contentFingerprint) blockers.push("handoff_manifest_content_fingerprint_mismatch");
	const captionHash = campaignString(meta, "caption_hash") || post.campaign_factory_caption_hash;
	if (captionHash && manifest.caption_hash !== captionHash) blockers.push("handoff_manifest_caption_hash_mismatch");
	return blockers;
}

function variantString(post: Record<string, any>, meta: CampaignMeta, column: string, snakeKey: string, camelKey?: string): string | null {
	const columnValue = post[column];
	if (typeof columnValue === "string" && columnValue.trim()) return columnValue.trim();
	const direct = campaignString(meta, snakeKey, ...(camelKey ? [camelKey] : []));
	if (direct) return direct;
	const manifest = meta.handoff_manifest;
	if (manifest && typeof manifest === "object" && !Array.isArray(manifest)) {
		const manifestValue = manifest[snakeKey] ?? (camelKey ? manifest[camelKey] : undefined);
		if (typeof manifestValue === "string" && manifestValue.trim()) return manifestValue.trim();
	}
	return null;
}

function manifestString(meta: CampaignMeta, snakeKey: string, camelKey?: string): string | null {
	const manifest = meta.handoff_manifest;
	if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) return null;
	const value = manifest[snakeKey] ?? (camelKey ? manifest[camelKey] : undefined);
	return typeof value === "string" && value.trim() ? value.trim() : null;
}

function campaignLineage(post: Record<string, any>, meta = campaignMeta(post)) {
	return {
		assetId: campaignString(meta, "asset_id", "rendered_asset_id") || post.campaign_factory_asset_id || post.renderedAssetId || post.campaignFactoryAssetId || null,
		contentFingerprint: campaignString(meta, "content_fingerprint", "content_hash") || post.campaign_factory_content_fingerprint || post.contentFingerprint || null,
		sourceAssetId: campaignString(meta, "source_asset_id", "sourceAssetId") || manifestString(meta, "source_asset_id", "sourceAssetId"),
		parentAssetId: variantString(post, meta, "campaign_factory_parent_asset_id", "parent_asset_id", "parentAssetId") || post.parentAssetId || null,
		parentReelId: campaignString(meta, "parent_reel_id", "parentReelId") || manifestString(meta, "parent_reel_id", "parentReelId") || post.parentReelId || null,
		variantFamilyId: variantString(post, meta, "campaign_factory_variant_family_id", "variant_family_id", "variantFamilyId") || post.variantFamilyId || null,
		variantId: variantString(post, meta, "campaign_factory_variant_id", "variant_id", "variantId") || post.variantId || null,
		distributionPlanId: campaignString(meta, "distribution_plan_id") || post.campaign_factory_distribution_plan_id || post.distributionPlanId || null,
	};
}

function lineageTimestamp(row: Record<string, any>): number | null {
	const raw = row.published_at || row.scheduled_for || row.created_at;
	if (!raw) return null;
	const time = new Date(raw).getTime();
	return Number.isFinite(time) ? time : null;
}

function withinCooldown(scheduledMs: number, row: Record<string, any>, cooldownDays: number): boolean {
	const rowTime = lineageTimestamp(row);
	if (rowTime == null) return true;
	return Math.abs(scheduledMs - rowTime) < cooldownDays * 24 * 60 * 60 * 1000;
}

function duplicateVisualRisk(post: Record<string, any>, candidates: Record<string, any>[]) {
	const lineage = campaignLineage(post);
	const scheduledMs = lineageTimestamp(post) ?? Date.now();
	let sameContentHashRecentlyPosted = false;
	let sameParentRecentlyPosted = false;
	let sameVariantFamilyRecentlyPosted = false;
	for (const candidate of candidates) {
		if (candidate.id === post.id) continue;
		if (candidate.instagram_account_id !== post.instagram_account_id) continue;
		if (!CAMPAIGN_DUPLICATE_STATUSES.includes(candidate.status)) continue;
		const candidateLineage = campaignLineage(candidate);
		if (lineage.contentFingerprint && candidateLineage.contentFingerprint === lineage.contentFingerprint) {
			sameContentHashRecentlyPosted = true;
		}
		if (
			(
				(lineage.parentReelId && candidateLineage.parentReelId === lineage.parentReelId)
				|| (lineage.parentAssetId && candidateLineage.parentAssetId === lineage.parentAssetId)
			)
			&& withinCooldown(scheduledMs, candidate, DEFAULT_PARENT_REEL_COOLDOWN_DAYS)
		) {
			sameParentRecentlyPosted = true;
		}
		if (
			lineage.variantFamilyId
			&& candidateLineage.variantFamilyId === lineage.variantFamilyId
			&& withinCooldown(scheduledMs, candidate, DEFAULT_VARIANT_SIBLING_COOLDOWN_DAYS)
		) {
			sameVariantFamilyRecentlyPosted = true;
		}
	}
	return {
		duplicateVisualRisk: sameContentHashRecentlyPosted || sameParentRecentlyPosted || sameVariantFamilyRecentlyPosted,
		sameParentRecentlyPosted,
		sameContentHashRecentlyPosted,
		sameVariantFamilyRecentlyPosted,
	};
}

async function fetchCampaignDraft(userId: string, postId: string): Promise<Record<string, any> | null> {
	const { data } = await db()
		.from("posts")
		.select("id,user_id,status,platform,content,media_urls,media_type,ig_media_type,content_surface,instagram_account_id,metadata,campaign_factory_asset_id,campaign_factory_distribution_plan_id,campaign_factory_post_key,campaign_factory_content_fingerprint,campaign_factory_caption_hash,campaign_factory_concept_id,campaign_factory_variant_family_id,campaign_factory_variant_id,campaign_factory_parent_asset_id,platform_draft_validated")
		.eq("id", postId)
		.eq("user_id", userId)
		.maybeSingle();
	return data ?? null;
}

async function fetchInstagramAccount(userId: string, accountId: string): Promise<Record<string, any> | null> {
	const { data } = await db()
		.from("instagram_accounts")
			.select("id,username,group_id,instagram_user_id,instagram_access_token_encrypted,facebook_page_access_token_encrypted,login_type,is_active,needs_reauth,status,token_expires_at,last_synced_at,follower_count")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle();
	return data ?? null;
}

async function hasActiveDuplicate(userId: string, post: Record<string, any>, scheduledFor: string, meta: CampaignMeta): Promise<string | null> {
	const lineage = campaignLineage(post, meta);
	const distributionPlanId = lineage.distributionPlanId;
	const assetId = lineage.assetId;
	if (distributionPlanId) {
		const { data } = await db()
			.from("posts")
			.select("id")
			.eq("user_id", userId)
			.eq("campaign_factory_distribution_plan_id", distributionPlanId)
			.in("status", CAMPAIGN_DUPLICATE_STATUSES)
			.neq("id", post.id)
			.limit(1);
		if ((data ?? []).length > 0) return "duplicate_distribution_plan";
	}
	if (!post.instagram_account_id) return null;
	const { data } = await db()
		.from("posts")
		.select("id,status,scheduled_for,published_at,created_at,campaign_factory_asset_id,campaign_factory_distribution_plan_id,campaign_factory_content_fingerprint,campaign_factory_parent_asset_id,campaign_factory_variant_family_id,campaign_factory_variant_id,metadata")
		.eq("user_id", userId)
		.eq("instagram_account_id", post.instagram_account_id)
		.in("status", CAMPAIGN_DUPLICATE_STATUSES)
		.neq("id", post.id)
		.limit(100);
	const scheduledMs = new Date(scheduledFor).getTime();
	for (const row of (data ?? []) as Record<string, any>[]) {
		const rowLineage = campaignLineage(row);
		if (assetId && rowLineage.assetId === assetId) return "duplicate_campaign_asset_account";
		if (lineage.contentFingerprint && rowLineage.contentFingerprint === lineage.contentFingerprint) return "same_content_fingerprint_account";
		if (
			lineage.sourceAssetId
			&& rowLineage.sourceAssetId === lineage.sourceAssetId
			&& withinCooldown(scheduledMs, row, DEFAULT_SOURCE_ASSET_COOLDOWN_DAYS)
		) return "same_source_asset_recently_posted";
		if (
			lineage.parentAssetId
			&& rowLineage.parentAssetId === lineage.parentAssetId
			&& withinCooldown(scheduledMs, row, DEFAULT_PARENT_ASSET_COOLDOWN_DAYS)
		) return "same_parent_asset_recently_posted";
		if (
			lineage.parentReelId
			&& rowLineage.parentReelId === lineage.parentReelId
			&& withinCooldown(scheduledMs, row, DEFAULT_PARENT_REEL_COOLDOWN_DAYS)
		) return "same_parent_reel_recently_posted";
		if (assetId && rowLineage.assetId === assetId && row.scheduled_for === scheduledFor) return "duplicate_asset_account_time";
	}
	return null;
}

async function hasVariantLineageConflict(userId: string, post: Record<string, any>, scheduledFor: string, meta: CampaignMeta): Promise<string | null> {
	const variantId = variantString(post, meta, "campaign_factory_variant_id", "variant_id", "variantId");
	const familyId = variantString(post, meta, "campaign_factory_variant_family_id", "variant_family_id", "variantFamilyId");
	if (!post.instagram_account_id) return null;
	if (variantId) {
		const { data } = await db()
			.from("posts")
			.select("id")
			.eq("user_id", userId)
			.eq("instagram_account_id", post.instagram_account_id)
			.eq("campaign_factory_variant_id", variantId)
			.in("status", ["draft", "scheduled", "publishing", "published"])
			.neq("id", post.id)
			.limit(1);
		if ((data ?? []).length > 0) return "duplicate_variant_account";
	}
	if (familyId) {
		const { data } = await db()
			.from("posts")
			.select("id,status,scheduled_for,published_at,created_at,campaign_factory_variant_id,campaign_factory_variant_family_id,metadata")
			.eq("user_id", userId)
			.eq("instagram_account_id", post.instagram_account_id)
			.eq("campaign_factory_variant_family_id", familyId)
			.in("status", ["draft", "scheduled", "publishing", "published"])
			.neq("id", post.id)
			.limit(50);
		const scheduledTime = new Date(scheduledFor).getTime();
		const cooldownMs = DEFAULT_VARIANT_SIBLING_COOLDOWN_DAYS * 24 * 60 * 60 * 1000;
		for (const row of (data ?? []) as Record<string, any>[]) {
			const rowMeta = campaignMeta(row);
			const rowFamilyId = variantString(row, rowMeta, "campaign_factory_variant_family_id", "variant_family_id", "variantFamilyId");
			if (rowFamilyId !== familyId) continue;
			const whenRaw = row.published_at || row.scheduled_for || row.created_at;
			if (!whenRaw) return "sibling_variant_cooldown";
			const when = new Date(whenRaw).getTime();
			if (!Number.isFinite(when) || Math.abs(scheduledTime - when) < cooldownMs) return "sibling_variant_cooldown";
		}
	}
	return null;
}

async function validateCampaignScheduleItem(userId: string, item: CampaignScheduleItem): Promise<Record<string, any>> {
	const schedule = parseScheduleDate(item.scheduledFor);
	if (!schedule.date) {
		return { ok: false, postId: item.postId, code: schedule.code, reason: schedule.error };
	}
	const post = await fetchCampaignDraft(userId, item.postId);
	if (!post) return { ok: false, postId: item.postId, reason: "draft_not_found" };
	if (post.status !== "draft") return { ok: false, postId: item.postId, reason: `draft_status_not_schedulable:${post.status}` };
	if (post.platform !== "instagram") return { ok: false, postId: item.postId, reason: "campaign_scheduler_instagram_only" };
	if (!post.instagram_account_id) return { ok: false, postId: item.postId, reason: "missing_instagram_account_id" };
	const meta = campaignMeta(post);
	if (!Object.keys(meta).length) return { ok: false, postId: item.postId, reason: "campaign_factory_metadata_missing" };
	const manifestBlockers = validateManifest(meta, post);
	if (manifestBlockers.length > 0) {
		return { ok: false, postId: item.postId, reason: "campaign_factory_manifest_blocked", blockingReasons: manifestBlockers };
	}
	const surface = resolvedCampaignSurface(post, meta);
	const igMediaType = resolvedCampaignIgMediaType(post, meta);
	if (!["reel", "feed_single"].includes(surface || "")) {
		return { ok: false, postId: item.postId, reason: "surface_scheduling_not_enabled", contentSurface: surface };
	}
	if (!igMediaType) {
		return { ok: false, postId: item.postId, reason: "ig_media_type_missing" };
	}
	if (surface === "feed_single" && igMediaType !== "IMAGE") {
		return { ok: false, postId: item.postId, reason: "feed_single_requires_image", contentSurface: surface, igMediaType };
	}
	const account = await fetchInstagramAccount(userId, post.instagram_account_id);
	if (!account) return { ok: false, postId: item.postId, reason: "instagram_account_not_found" };
	const eligibility = isAccountPublishable({
		is_active: account.is_active !== false,
		status: account.status,
		needs_reauth: account.needs_reauth,
		token_expires_at: account.token_expires_at,
	});
	if (!eligibility.eligible) return { ok: false, postId: item.postId, reason: eligibility.reason || "account_not_publishable" };
	const restrictionProjection = (await restrictionProjectionsForUser(userId)).get(post.instagram_account_id);
	if ((restrictionProjection?.blockers ?? []).length > 0) {
		return {
			ok: false,
			postId: item.postId,
			reason: restrictionProjection?.blockers[0] ?? "account_health_blocked",
			accountHealth: restrictionProjection,
		};
	}
	const preflight = await runPublishPreflight(
		{
			platform: "instagram",
			mode: "api",
			instagramAccountId: post.instagram_account_id,
		content: post.content || "",
			media: mediaItems(post),
			igMediaType,
			mediaType: post.media_type || "reel",
			metadata: post.metadata,
		},
		{
			account: {
				found: true,
				isActive: account.is_active,
				needsReauth: account.needs_reauth,
				status: account.status,
				tokenExpiresAt: account.token_expires_at,
					hasAccessToken: !!account.instagram_access_token_encrypted,
					hasPlatformUserId: !!account.instagram_user_id,
					loginType: account.login_type,
					followerCount: account.follower_count,
				},
				checkMediaUrls: true,
		},
	);
	if (!preflight.ok) {
		return { ok: false, postId: item.postId, reason: "publish_preflight_failed", preflight };
	}
	const duplicateReason = await hasActiveDuplicate(userId, post, schedule.date.toISOString(), meta);
	if (duplicateReason) return { ok: false, postId: item.postId, reason: duplicateReason };
	const variantConflictReason = await hasVariantLineageConflict(userId, post, schedule.date.toISOString(), meta);
	if (variantConflictReason) return { ok: false, postId: item.postId, reason: variantConflictReason };
	return {
		ok: true,
		postId: item.postId,
		scheduledFor: schedule.date.toISOString(),
		instagramAccountId: post.instagram_account_id,
		contentSurface: surface,
		campaignFactoryAssetId: campaignString(meta, "asset_id", "rendered_asset_id") || post.campaign_factory_asset_id,
		distributionPlanId: campaignString(meta, "distribution_plan_id") || post.campaign_factory_distribution_plan_id,
		campaignFactoryPostKey: campaignString(meta, "post_key") || post.campaign_factory_post_key,
		contentFingerprint: campaignString(meta, "content_fingerprint", "content_hash") || post.campaign_factory_content_fingerprint,
		captionHash: campaignString(meta, "caption_hash") || post.campaign_factory_caption_hash,
		conceptId: variantString(post, meta, "campaign_factory_concept_id", "concept_id", "conceptId"),
		parentAssetId: variantString(post, meta, "campaign_factory_parent_asset_id", "parent_asset_id", "parentAssetId"),
		variantFamilyId: variantString(post, meta, "campaign_factory_variant_family_id", "variant_family_id", "variantFamilyId"),
		variantId: variantString(post, meta, "campaign_factory_variant_id", "variant_id", "variantId"),
		accountUsername: account.username,
		post,
	};
}

async function insertBatch(userId: string, dryRun: boolean, requestedCount: number, metadata: Record<string, unknown>): Promise<string | null> {
	if (dryRun) return null;
	const { data } = await db()
		.from("campaign_schedule_batches")
		.insert({
			user_id: userId,
			status: dryRun ? "dry_run" : "committing",
			dry_run: dryRun,
			requested_count: requestedCount,
			metadata,
		})
		.select("id")
		.maybeSingle();
	return data?.id ?? null;
}

export async function handleCampaignSchedule(req: VercelRequest, res: VercelResponse, userId: string) {
	const parsed = parseBodyOrError(res, CampaignScheduleSchema, req.body);
	if (!parsed) return;
	const dryRun = parsed.dryRun !== false;
	const batchId = await insertBatch(userId, dryRun, parsed.items.length, parsed.batchMetadata ?? {});
	const results = [];
	let scheduledCount = 0;
	let failedCount = 0;
	for (const item of parsed.items as CampaignScheduleItem[]) {
		const validation = await validateCampaignScheduleItem(userId, item);
		if (!validation.ok) {
			failedCount++;
			results.push(validation);
			continue;
		}
		if (dryRun) {
			results.push({ ...validation, post: undefined, status: "validated" });
			continue;
		}
		const updatePayload = {
			status: "scheduled",
			scheduled_for: validation.scheduledFor,
			campaign_factory_asset_id: validation.campaignFactoryAssetId,
			campaign_factory_distribution_plan_id: validation.distributionPlanId,
			campaign_factory_post_key: validation.campaignFactoryPostKey,
			campaign_factory_content_fingerprint: validation.contentFingerprint,
			campaign_factory_caption_hash: validation.captionHash,
			campaign_factory_concept_id: validation.conceptId,
			campaign_factory_parent_asset_id: validation.parentAssetId,
			campaign_factory_variant_family_id: validation.variantFamilyId,
			campaign_factory_variant_id: validation.variantId,
			content_surface: validation.contentSurface,
			platform_draft_validated: true,
			qstash_dispatch_status: "pending",
			qstash_failure_reason: null,
			updated_at: new Date().toISOString(),
		};
		const { data: updated, error: updateError } = await db()
			.from("posts")
			.update(updatePayload)
			.eq("id", validation.postId)
			.eq("user_id", userId)
			.eq("status", "draft")
			.select("id")
			.maybeSingle();
		if (updateError || !updated) {
			failedCount++;
			results.push({ ok: false, postId: validation.postId, reason: updateError?.message || "schedule_update_failed" });
			continue;
		}
		const { dispatchPostPublish } = await import("../../qstashSchedule.js");
		const qstashMessageId = await dispatchPostPublish(validation.postId, new Date(validation.scheduledFor));
		if (!qstashMessageId) {
			await db()
				.from("posts")
				.update({
					status: "draft",
					scheduled_for: null,
					qstash_dispatch_status: "failed",
					qstash_failure_reason: "dispatch_failed",
					updated_at: new Date().toISOString(),
				})
				.eq("id", validation.postId)
				.eq("user_id", userId);
			failedCount++;
			results.push({ ok: false, postId: validation.postId, reason: "qstash_dispatch_failed" });
			continue;
		}
		scheduledCount++;
		results.push({ ...validation, post: undefined, status: "scheduled", qstashMessageId });
		if (batchId) {
			await db().from("campaign_schedule_batch_items").insert({
				batch_id: batchId,
				user_id: userId,
				post_id: validation.postId,
				campaign_factory_asset_id: validation.campaignFactoryAssetId,
				campaign_factory_distribution_plan_id: validation.distributionPlanId,
				instagram_account_id: validation.instagramAccountId,
				scheduled_for: validation.scheduledFor,
				status: "scheduled",
				qstash_message_id: qstashMessageId,
				metadata: {
					accountUsername: validation.accountUsername,
					conceptId: validation.conceptId,
					parentAssetId: validation.parentAssetId,
					variantFamilyId: validation.variantFamilyId,
					variantId: validation.variantId,
				},
			});
		}
	}
	if (batchId) {
		await db()
			.from("campaign_schedule_batches")
			.update({
				status: dryRun ? "dry_run" : (failedCount > 0 ? "partial" : "committed"),
				scheduled_count: scheduledCount,
				failed_count: failedCount,
				updated_at: new Date().toISOString(),
			})
			.eq("id", batchId);
	}
	return apiSuccess(res, {
		schema: "threadsdashboard.campaign_schedule.v1",
		dryRun,
		batchId,
		totalRequested: parsed.items.length,
		scheduledCount,
		failedCount,
		items: results,
	});
}

export async function missedCampaignDispatches(userId: string, graceMs = DEFAULT_MISSED_GRACE_MS): Promise<Record<string, any>[]> {
	const cutoff = new Date(Date.now() - graceMs).toISOString();
	const { data } = await db()
		.from("posts")
		.select("id,user_id,status,platform,scheduled_for,instagram_account_id,ig_publish_attempts,qstash_message_id,qstash_dispatched_at,qstash_dispatch_status,qstash_failure_reason,campaign_factory_asset_id,campaign_factory_distribution_plan_id,metadata")
		.eq("user_id", userId)
		.eq("platform", "instagram")
		.eq("status", "scheduled")
		.lt("scheduled_for", cutoff)
		.or("ig_publish_attempts.is.null,ig_publish_attempts.eq.0")
		.not("campaign_factory_asset_id", "is", null)
		.limit(100);
	return ((data ?? []) as Record<string, any>[]).map((row) => ({
		...row,
		blockingReason: "overdue_dispatch_no_publish_attempt",
		nextOperatorAction: "reschedule_or_recover_same_row",
	}));
}

export async function recoverMissedCampaignDispatches(
	userId: string,
	options: { mode?: CampaignRecoveryMode; rescheduleFor?: string } = {},
): Promise<{ recovered: number; failed: Array<{ postId: string; reason: string }> }> {
	const rows = await missedCampaignDispatches(userId, 0);
	const failed: Array<{ postId: string; reason: string }> = [];
	let recovered = 0;
	const mode = options.mode ?? "reset_to_draft";
	for (const row of rows) {
		if (!row.scheduled_for) {
			failed.push({ postId: row.id, reason: "missing_scheduled_for" });
			continue;
		}
		if (mode === "reset_to_draft") {
			const { data: updated } = await db()
				.from("posts")
				.update({
					status: "draft",
					scheduled_for: null,
					qstash_message_id: null,
					qstash_dispatched_at: null,
					qstash_dispatch_status: null,
					qstash_failure_reason: "overdue_dispatch_no_publish_attempt",
					updated_at: new Date().toISOString(),
				})
				.eq("id", row.id)
				.eq("user_id", userId)
				.eq("status", "scheduled")
				.select("id");
			if (!updated || updated.length === 0) {
				failed.push({ postId: row.id, reason: "reset_to_draft_failed" });
				continue;
			}
			recovered++;
			continue;
		}
		if (mode === "reschedule") {
			if (!options.rescheduleFor) {
				failed.push({ postId: row.id, reason: "missing_reschedule_for" });
				continue;
			}
			const schedule = parseScheduleDate(options.rescheduleFor);
			if (!schedule.date) {
				failed.push({ postId: row.id, reason: schedule.error || "invalid_reschedule_for" });
				continue;
			}
			const { data: updated } = await db()
				.from("posts")
				.update({
					scheduled_for: schedule.date.toISOString(),
					qstash_message_id: null,
					qstash_dispatched_at: null,
					qstash_dispatch_status: "pending",
					qstash_failure_reason: null,
					updated_at: new Date().toISOString(),
				})
				.eq("id", row.id)
				.eq("user_id", userId)
				.eq("status", "scheduled")
				.select("id");
			if (!updated || updated.length === 0) {
				failed.push({ postId: row.id, reason: "reschedule_failed" });
				continue;
			}
			const { dispatchPostPublish } = await import("../../qstashSchedule.js");
			const qstashMessageId = await dispatchPostPublish(row.id, schedule.date);
			if (!qstashMessageId) {
				await db()
					.from("posts")
					.update({
						qstash_dispatch_status: "failed",
						qstash_failure_reason: "recovery_dispatch_failed",
						updated_at: new Date().toISOString(),
					})
					.eq("id", row.id)
					.eq("user_id", userId)
					.eq("status", "scheduled");
				failed.push({ postId: row.id, reason: "qstash_dispatch_failed" });
				continue;
			}
			recovered++;
			continue;
		}
		const { dispatchPostPublish } = await import("../../qstashSchedule.js");
		const qstashMessageId = await dispatchPostPublish(row.id, new Date(row.scheduled_for));
		if (!qstashMessageId) {
			await db()
				.from("posts")
				.update({ qstash_dispatch_status: "failed", qstash_failure_reason: "recovery_dispatch_failed", updated_at: new Date().toISOString() })
				.eq("id", row.id)
				.eq("user_id", userId)
				.eq("status", "scheduled");
			failed.push({ postId: row.id, reason: "qstash_dispatch_failed" });
			continue;
		}
		recovered++;
	}
	return { recovered, failed };
}

async function buildCampaignScheduleManagerReport(userId: string, creatorFilter: string | null) {
	const now = new Date();
	const startOfDay = new Date(now);
	startOfDay.setHours(0, 0, 0, 0);
	const endOfDay = new Date(startOfDay);
	endOfDay.setDate(endOfDay.getDate() + 1);
	const [accountsResp, groupsResp, upcomingResp, publishedResp, missed] = await Promise.all([
		db().from("instagram_accounts").select("id,username,group_id,is_active,needs_reauth,status,token_expires_at,last_synced_at").eq("user_id", userId),
		db().from("account_groups").select("id,name,account_ids").eq("user_id", userId),
		db().from("posts").select("id,instagram_account_id,scheduled_for,status,campaign_factory_asset_id,campaign_factory_distribution_plan_id,campaign_factory_post_key,campaign_factory_concept_id,campaign_factory_parent_asset_id,campaign_factory_variant_family_id,campaign_factory_variant_id,qstash_message_id,qstash_dispatch_status,qstash_failure_reason,platform_draft_validated,metadata").eq("user_id", userId).eq("platform", "instagram").in("status", ["scheduled", "publishing"]).gte("scheduled_for", startOfDay.toISOString()).lt("scheduled_for", endOfDay.toISOString()),
		db().from("posts").select("id,instagram_account_id,scheduled_for,published_at,created_at,status,error_message,campaign_factory_asset_id,campaign_factory_distribution_plan_id,campaign_factory_post_key,campaign_factory_concept_id,campaign_factory_parent_asset_id,campaign_factory_variant_family_id,campaign_factory_variant_id,campaign_factory_content_fingerprint,metadata").eq("user_id", userId).eq("platform", "instagram").in("status", ["published", "failed"]).order("published_at", { ascending: false }).limit(1000),
		missedCampaignDispatches(userId),
	]);
	const restrictionProjectionByAccount = await restrictionProjectionsForUser(userId);
	const groupById = new Map<string, Record<string, any>>();
	for (const group of (groupsResp.data ?? []) as Record<string, any>[]) {
		if (group.id) groupById.set(String(group.id), group);
	}
	const visualRiskCandidates = [
		...((upcomingResp.data ?? []) as Record<string, any>[]),
		...((publishedResp.data ?? []) as Record<string, any>[]),
	];
	const scheduledCampaignPosts = ((upcomingResp.data ?? []) as Record<string, any>[])
		.filter((post) => post.campaign_factory_asset_id || campaignMeta(post).asset_id || campaignMeta(post).rendered_asset_id)
		.map((post) => {
			const meta = campaignMeta(post);
			const trialIntent = resolveInstagramTrialReelIntent({ metadata: post.metadata, campaignFactory: meta });
			const risk = duplicateVisualRisk(post, visualRiskCandidates);
			return {
				postId: post.id,
				campaignId: campaignString(meta, "campaign_id"),
				contentSurface: resolvedCampaignSurface(post, meta),
				distributionSurface: campaignString(meta, "distribution_surface", "distributionSurface"),
				instagramTrialReels: trialIntent.enabled,
				trialGraduationStrategy: trialIntent.strategy ?? null,
				reelMode: trialIntent.enabled ? "trial_reel" : "normal_reel",
				distributionPlanId: post.campaign_factory_distribution_plan_id || campaignString(meta, "distribution_plan_id"),
				renderedAssetId: post.campaign_factory_asset_id || campaignString(meta, "asset_id", "rendered_asset_id"),
				conceptId: variantString(post, meta, "campaign_factory_concept_id", "concept_id", "conceptId"),
				parentAssetId: variantString(post, meta, "campaign_factory_parent_asset_id", "parent_asset_id", "parentAssetId"),
				variantFamilyId: variantString(post, meta, "campaign_factory_variant_family_id", "variant_family_id", "variantFamilyId"),
				variantId: variantString(post, meta, "campaign_factory_variant_id", "variant_id", "variantId"),
				accountId: post.instagram_account_id,
				scheduledFor: post.scheduled_for,
				status: post.status,
				qstashMessageId: post.qstash_message_id,
				qstashDispatchStatus: post.qstash_dispatch_status,
				qstashFailureReason: post.qstash_failure_reason,
				platformDraftValidated: post.platform_draft_validated === true,
				campaignFactoryPostKey: post.campaign_factory_post_key || campaignString(meta, "post_key"),
				...risk,
			};
		});
	const duplicateDistributionPlans = new Set<string>();
	const seenDistributionPlans = new Map<string, string>();
	const duplicateAssetAccountTimes = new Set<string>();
	const seenAssetAccountTimes = new Map<string, string>();
	for (const post of scheduledCampaignPosts) {
		if (post.distributionPlanId) {
			const key = String(post.distributionPlanId);
			if (seenDistributionPlans.has(key)) duplicateDistributionPlans.add(key);
			seenDistributionPlans.set(key, post.postId);
		}
		if (post.renderedAssetId && post.accountId && post.scheduledFor) {
			const key = [post.renderedAssetId, post.accountId, post.scheduledFor].join(":");
			if (seenAssetAccountTimes.has(key)) duplicateAssetAccountTimes.add(key);
			seenAssetAccountTimes.set(key, post.postId);
		}
	}
	const upcomingByAccount = new Map<string, any[]>();
	for (const post of upcomingResp.data ?? []) {
		const key = post.instagram_account_id;
		if (!key) continue;
		const list = upcomingByAccount.get(key) ?? [];
		list.push(post);
		upcomingByAccount.set(key, list);
	}
	const lastByAccount = new Map<string, any>();
	for (const post of publishedResp.data ?? []) {
		const key = post.instagram_account_id;
		if (key && !lastByAccount.has(key)) lastByAccount.set(key, post);
	}
	const allAccounts = ((accountsResp.data ?? []) as Record<string, any>[]).map((account) => {
		const group = account.group_id ? groupById.get(account.group_id) ?? null : null;
		const creator = inferCreator(account, group);
		const eligibility = isAccountPublishable({
			is_active: account.is_active !== false,
			needs_reauth: account.needs_reauth,
			status: account.status,
			token_expires_at: account.token_expires_at,
		});
		const upcoming = upcomingByAccount.get(account.id) ?? [];
		const nextScheduled = upcoming.sort((a, b) => String(a.scheduled_for).localeCompare(String(b.scheduled_for)))[0] ?? null;
		const last = lastByAccount.get(account.id) ?? null;
		const classification = accountBucket({
			eligible: eligibility.eligible,
			eligibilityReason: eligibility.reason,
			hasScheduleToday: upcoming.length > 0,
			hasRecentFailure: last?.status === "failed",
			accountHealthBlockers: restrictionProjectionByAccount.get(String(account.id))?.blockers,
		});
		const restrictionProjection = restrictionProjectionByAccount.get(String(account.id));
		const blockers = Array.from(new Set([
			...(restrictionProjection?.blockers ?? []),
			...(classification.blockingReason ? [classification.blockingReason] : []),
		]));
		return {
			accountId: account.id,
			username: account.username,
			groupId: account.group_id,
			groupName: group?.name ?? null,
			creator: creator.creator,
			creatorSource: creator.source,
			connected: Boolean(account.id),
			publishable: eligibility.eligible,
			needsReauth: Boolean(account.needs_reauth) || account.status === "needs_reauth",
			tokenExpiresAt: account.token_expires_at,
			lastSyncedAt: account.last_synced_at,
			nextScheduledPost: nextScheduled,
			lastPublishedPost: last?.status === "published" ? last : null,
			openFailureReason: last?.status === "failed" ? last.error_message : null,
			needsPostToday: classification.needsPostToday,
			safeToSchedule: classification.safeToSchedule,
			bucket: classification.bucket,
			blockingReason: classification.blockingReason,
			blockers,
			restrictionStatus: restrictionProjection?.restrictionStatus ?? {
				active: false,
				type: "",
				status: "clear",
				severity: "",
				startedAt: null,
				endsAt: null,
			},
			activeRestrictionCount: restrictionProjection?.activeRestrictionCount ?? 0,
			restrictionTypes: restrictionProjection?.restrictionTypes ?? [],
			linkSharingRestricted: restrictionProjection?.linkSharingRestricted ?? false,
			recommendationEligibilityState: restrictionProjection?.recommendationEligibilityState ?? "eligible",
			reviewRequired: restrictionProjection?.reviewRequired ?? false,
			needsReviewAfterExpiry: restrictionProjection?.needsReviewAfterExpiry ?? false,
			accountTrustState: restrictionProjection?.accountTrustState ?? "normal",
		};
	});
	const accounts = creatorFilter
		? allAccounts.filter((account) => normalizeCreator(account.creator) === creatorFilter)
		: allAccounts;
	const accountBuckets: Record<AccountBucket, any[]> = {
		safe_to_schedule_today: [],
		already_scheduled_today: [],
		blocked_reauth: [],
		blocked_token_expired: [],
		blocked_disabled: [],
		blocked_recent_failure: [],
		blocked_account_health: [],
		blocked_unknown: [],
	};
	for (const account of accounts) {
		accountBuckets[account.bucket as AccountBucket].push(account);
	}
	return {
		schema: "threadsdashboard.campaign_schedule_manager_report.v1",
		generatedAt: new Date().toISOString(),
		filters: { creator: creatorFilter },
		accounts,
		accountBuckets,
		scheduledCampaignPosts,
		missedDispatches: missed,
		summary: {
			accountCount: accounts.length,
			safeToScheduleCount: accounts.filter((account) => account.safeToSchedule).length,
			needsPostTodayCount: accounts.filter((account) => account.needsPostToday).length,
			alreadyScheduledTodayCount: accountBuckets.already_scheduled_today.length,
			blockedCount: accountBuckets.blocked_reauth.length
				+ accountBuckets.blocked_token_expired.length
				+ accountBuckets.blocked_disabled.length
				+ accountBuckets.blocked_recent_failure.length
				+ accountBuckets.blocked_account_health.length
				+ accountBuckets.blocked_unknown.length,
			bucketCounts: Object.fromEntries(Object.entries(accountBuckets).map(([bucket, rows]) => [bucket, rows.length])),
			missedDispatchCount: missed.length,
			campaignScheduledCount: scheduledCampaignPosts.length,
			campaignScheduleDuplicateCount: duplicateDistributionPlans.size + duplicateAssetAccountTimes.size,
			duplicateDistributionPlanIds: Array.from(duplicateDistributionPlans),
			duplicateAssetAccountTimeKeys: Array.from(duplicateAssetAccountTimes),
			duplicateVisualRiskCount: scheduledCampaignPosts.filter((post) => post.duplicateVisualRisk).length,
			sameParentRecentlyPostedCount: scheduledCampaignPosts.filter((post) => post.sameParentRecentlyPosted).length,
			sameContentHashRecentlyPostedCount: scheduledCampaignPosts.filter((post) => post.sameContentHashRecentlyPosted).length,
			sameVariantFamilyRecentlyPostedCount: scheduledCampaignPosts.filter((post) => post.sameVariantFamilyRecentlyPosted).length,
			restrictedAccountCount: accounts.filter((account) => account.activeRestrictionCount > 0 || account.linkSharingRestricted).length,
			manualReviewAccountCount: accounts.filter((account) => account.reviewRequired || account.recommendationEligibilityState === "manual_review_required").length,
		},
	};
}

export async function handleCampaignScheduleReport(req: VercelRequest, res: VercelResponse, userId: string) {
	return apiSuccess(res, await buildCampaignScheduleManagerReport(userId, normalizeCreator(requestString(req, "creator"))));
}

function draftInventoryRow(post: Record<string, any>, safeAccountsById: Map<string, Record<string, any>>) {
	const meta = campaignMeta(post);
	const manifest = meta.handoff_manifest && typeof meta.handoff_manifest === "object" && !Array.isArray(meta.handoff_manifest)
		? meta.handoff_manifest
		: {};
	const manifestBlockers = validateManifest(meta, post);
	const trialIntent = resolveInstagramTrialReelIntent({ metadata: post.metadata, campaignFactory: meta });
	const safeAccount = safeAccountsById.get(post.instagram_account_id);
	const assetState = String(meta.asset_state || "").trim().toLowerCase();
	const handoffManifestOk = manifestBlockers.length === 0;
	const accountCompatible = Boolean(safeAccount);
	return {
		postId: post.id,
		accountId: post.instagram_account_id,
		username: safeAccount?.username ?? null,
		creator: safeAccount?.creator ?? null,
		contentSurface: resolvedCampaignSurface(post, meta),
		distributionSurface: campaignString(meta, "distribution_surface", "distributionSurface"),
		instagramTrialReels: trialIntent.enabled,
		trialGraduationStrategy: trialIntent.strategy ?? null,
		reelMode: trialIntent.enabled ? "trial_reel" : "normal_reel",
		igMediaType: resolvedCampaignIgMediaType(post, meta),
		renderedAssetId: post.campaign_factory_asset_id || campaignString(meta, "asset_id", "rendered_asset_id"),
		conceptId: variantString(post, meta, "campaign_factory_concept_id", "concept_id", "conceptId"),
		parentAssetId: variantString(post, meta, "campaign_factory_parent_asset_id", "parent_asset_id", "parentAssetId"),
		variantFamilyId: variantString(post, meta, "campaign_factory_variant_family_id", "variant_family_id", "variantFamilyId"),
		variantId: variantString(post, meta, "campaign_factory_variant_id", "variant_id", "variantId"),
		distributionPlanId: post.campaign_factory_distribution_plan_id || campaignString(meta, "distribution_plan_id"),
		campaignFactoryPostKey: post.campaign_factory_post_key || campaignString(meta, "post_key"),
		contentFingerprint: post.campaign_factory_content_fingerprint || campaignString(meta, "content_fingerprint", "content_hash"),
		captionHash: post.campaign_factory_caption_hash || campaignString(meta, "caption_hash"),
		instagramPostCaption: campaignString(meta, "instagram_post_caption", "instagramPostCaption") || manifestString(meta, "instagram_post_caption", "instagramPostCaption"),
		burnedCaptionText: campaignString(meta, "burned_caption_text", "burnedCaptionText") || manifestString(meta, "burned_caption_text", "burnedCaptionText"),
		captionFamilyId: campaignString(meta, "caption_family_id", "captionFamilyId") || manifestString(meta, "caption_family_id", "captionFamilyId"),
		captionVersionId: campaignString(meta, "caption_version_id", "captionVersionId") || manifestString(meta, "caption_version_id", "captionVersionId"),
		handoffManifest: manifest,
		publishabilityState: assetState || null,
		platformDraftValidated: post.platform_draft_validated === true,
		handoffManifestOk,
		accountCompatible,
		qstashEligible: post.platform_draft_validated === true && handoffManifestOk && accountCompatible && post.status === "draft" && ["reel", "feed_single"].includes(resolvedCampaignSurface(post, meta) || ""),
		duplicateCheck: "not_checked",
		blockingReasons: [
			...(post.status === "draft" ? [] : [`draft_status_not_schedulable:${post.status || "missing"}`]),
			...(post.platform === "instagram" ? [] : ["campaign_scheduler_instagram_only"]),
			...(post.platform_draft_validated === true ? [] : ["platform_draft_not_validated"]),
			...manifestBlockers,
			...(accountCompatible ? [] : ["account_not_safe_for_creator_or_already_scheduled"]),
			...(["reel", "feed_single"].includes(resolvedCampaignSurface(post, meta) || "") ? [] : ["surface_scheduling_not_enabled"]),
		],
	};
}

function creatorDefaultWindow(creator: string, timezone: string): string {
	if (normalizeCreator(creator) === "Stacey") return `11:00-22:00 ${timezone}`;
	return `10:00-21:00 ${timezone}`;
}

function parseWindowHours(window: string | null | undefined): { startHour: number; endHour: number } {
	const match = String(window || "").match(/(\d{1,2})(?::\d{2})?\s*-\s*(\d{1,2})(?::\d{2})?/);
	if (!match) return { startHour: 11, endHour: 22 };
	const startHour = Math.min(23, Math.max(0, Number(match[1])));
	const endHour = Math.min(24, Math.max(startHour + 1, Number(match[2])));
	return { startHour, endHour };
}

function localParts(date: Date, timezone: string): Record<string, number> {
	const parts = new Intl.DateTimeFormat("en-US", {
		timeZone: timezone,
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
		hour12: false,
	}).formatToParts(date);
	const values: Record<string, number> = {};
	for (const part of parts) {
		if (part.type !== "literal") values[part.type] = Number(part.value);
	}
	return values;
}

function localDateKey(date: Date, timezone: string): string {
	const parts = localParts(date, timezone);
	return `${parts.year}-${String(parts.month).padStart(2, "0")}-${String(parts.day).padStart(2, "0")}`;
}

function localTimeLabel(date: Date, timezone: string): string {
	return new Intl.DateTimeFormat("en-US", {
		timeZone: timezone,
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
		hour: "2-digit",
		minute: "2-digit",
		second: "2-digit",
		hour12: false,
	}).format(date);
}

function isWithinWindow(date: Date, timezone: string, window: string): boolean {
	const parts = localParts(date, timezone);
	const { startHour, endHour } = parseWindowHours(window);
	const hour = parts.hour ?? -1;
	return hour >= startHour && hour < endHour;
}

function nextWindowStart(anchor: Date, timezone: string, window: string): Date {
	const start = new Date(Math.max(Date.now() + MIN_SCHEDULE_LEAD_MS, anchor.getTime()));
	for (let offset = 0; offset <= 48 * 60; offset += 5) {
		const candidate = new Date(start.getTime() + offset * 60 * 1000);
		if (isWithinWindow(candidate, timezone, window)) return candidate;
	}
	return new Date(start.getTime() + 30 * 60 * 1000);
}

function stableMinuteOffset(seed: string, modulo: number): number {
	let hash = 0;
	for (const char of seed) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
	return modulo > 0 ? hash % modulo : 0;
}

function metricViews(post: Record<string, any>): number {
	const metadata = post.metadata && typeof post.metadata === "object" ? post.metadata : {};
	const candidates = [
		post.views,
		post.view_count,
		metadata.views,
		metadata.view_count,
		metadata.metrics?.views,
		metadata.metrics?.plays,
		metadata.performance?.views,
	];
	for (const candidate of candidates) {
		const value = Number(candidate);
		if (Number.isFinite(value)) return value;
	}
	return 0;
}

function publishedHour(post: Record<string, any>, timezone: string): number | null {
	const raw = post.published_at || post.scheduled_for || post.created_at;
	if (!raw) return null;
	const date = new Date(raw);
	if (Number.isNaN(date.getTime())) return null;
	return localParts(date, timezone).hour ?? null;
}

function average(values: number[]): number {
	if (!values.length) return 0;
	return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function deriveCadence(account: Record<string, any>, history: Record<string, any>[], creatorHistory: Record<string, any>[]): {
	accountState: AccountCadenceState;
	postsPerDay: number;
	minimumGapHours: number;
	reason: string;
} {
	if (!account.safeToSchedule) {
		return { accountState: "blocked", postsPerDay: 0, minimumGapHours: 24, reason: account.blockingReason || "account_not_safe" };
	}
	if (account.openFailureReason) {
		return { accountState: "resting", postsPerDay: 0, minimumGapHours: 24, reason: "recent_publish_failure" };
	}
	if (history.length < 3) {
		return { accountState: "warming", postsPerDay: 1, minimumGapHours: 24, reason: `limited_account_history:${history.length}_posts` };
	}
	const accountAvg = average(history.slice(0, 20).map(metricViews));
	const creatorAvg = average(creatorHistory.slice(0, 200).map(metricViews));
	if (accountAvg >= 10 && creatorAvg > 0 && accountAvg >= creatorAvg * 1.5) {
		return { accountState: "high-performing", postsPerDay: 2, minimumGapHours: 6, reason: `account_avg_views_${Math.round(accountAvg)}_above_creator_avg_${Math.round(creatorAvg)}` };
	}
	return { accountState: "normal", postsPerDay: 1, minimumGapHours: 12, reason: history.length >= 3 ? "normal_history" : "default_normal" };
}

function bestPerformanceHour(input: {
	accountHistory: Record<string, any>[];
	creatorHistory: Record<string, any>[];
	timezone: string;
	window: string;
}): { hour: number | null; reason: string; fallbackUsed: boolean } {
	const scoreByHour = (rows: Record<string, any>[], minRows: number) => {
		const buckets = new Map<number, number[]>();
		const { startHour, endHour } = parseWindowHours(input.window);
		for (const row of rows) {
			const hour = publishedHour(row, input.timezone);
			if (hour == null) continue;
			if (hour < startHour || hour >= endHour) continue;
			const values = buckets.get(hour) ?? [];
			values.push(metricViews(row));
			buckets.set(hour, values);
		}
		let best: { hour: number; avg: number; count: number } | null = null;
		for (const [hour, values] of buckets.entries()) {
			if (values.length < minRows) continue;
			const avg = average(values);
			if (!best || avg > best.avg) best = { hour, avg, count: values.length };
		}
		return best;
	};
	const accountBest = scoreByHour(input.accountHistory, 3);
	if (accountBest) return { hour: accountBest.hour, reason: `account_history_hour_${accountBest.hour}_avg_views_${Math.round(accountBest.avg)}_n_${accountBest.count}`, fallbackUsed: false };
	const creatorBest = scoreByHour(input.creatorHistory, 5);
	if (creatorBest) return { hour: creatorBest.hour, reason: `creator_history_hour_${creatorBest.hour}_avg_views_${Math.round(creatorBest.avg)}_n_${creatorBest.count}`, fallbackUsed: false };
	const { startHour, endHour } = parseWindowHours(input.window);
	return { hour: Math.floor((startHour + endHour) / 2), reason: "fallback_default_window_midpoint_insufficient_metrics", fallbackUsed: true };
}

function alignToPreferredHour(base: Date, timezone: string, window: string, preferredHour: number | null, seed: string): Date {
	const windowStart = nextWindowStart(base, timezone, window);
	const targetLocalDate = localDateKey(windowStart, timezone);
	const minuteOffset = stableMinuteOffset(seed, 50) + 5;
	if (preferredHour == null) return new Date(windowStart.getTime() + minuteOffset * 60 * 1000);
	for (let offset = 0; offset <= 48 * 60; offset += 5) {
		const candidate = new Date(windowStart.getTime() + offset * 60 * 1000);
		const parts = localParts(candidate, timezone);
		if (localDateKey(candidate, timezone) !== targetLocalDate) continue;
		if (!isWithinWindow(candidate, timezone, window)) continue;
		if (parts.hour === preferredHour && (parts.minute ?? 0) >= minuteOffset % 60) return candidate;
	}
	return new Date(windowStart.getTime() + minuteOffset * 60 * 1000);
}

function avoidScheduleCollisions(candidate: Date, scheduled: Date[], minimumSpacingMinutes: number, timezone: string, window: string): { date: Date; reason: string } {
	let adjusted = new Date(candidate);
	let bumps = 0;
	while (scheduled.some((existing) => Math.abs(existing.getTime() - adjusted.getTime()) < minimumSpacingMinutes * 60 * 1000) || !isWithinWindow(adjusted, timezone, window)) {
		adjusted = new Date(adjusted.getTime() + minimumSpacingMinutes * 60 * 1000);
		bumps++;
		if (bumps > 96) break;
	}
	return {
		date: adjusted,
		reason: bumps === 0
			? `unique_time_min_spacing_${minimumSpacingMinutes}m`
			: `shifted_${bumps}_slots_to_preserve_${minimumSpacingMinutes}m_spacing_and_window`,
	};
}

async function fetchPublishedTimingHistory(userId: string): Promise<Record<string, any>[]> {
	const { data } = await db()
		.from("posts")
		.select("id,instagram_account_id,published_at,scheduled_for,created_at,status,metadata")
		.eq("user_id", userId)
		.eq("platform", "instagram")
		.in("status", ["published"])
		.order("published_at", { ascending: false })
		.limit(2000);
	return (data ?? []) as Record<string, any>[];
}

export async function handleCampaignSchedulePlan(req: VercelRequest, res: VercelResponse, userId: string) {
	const parsed = parseBodyOrError(res, CampaignSchedulePlanSchema, {
		creator: requestString(req, "creator") ?? req.body?.creator,
		requestedCount: requestNumber(req, "requestedCount") ?? req.body?.requestedCount,
		startAt: requestString(req, "startAt") ?? req.body?.startAt,
		jitterMinutes: req.body?.jitterMinutes,
	});
	if (!parsed) return;
	const creator = normalizeCreator(parsed.creator) || "Stacey";
	const requestedCount = parsed.requestedCount ?? 10;
	const jitterMin = parsed.jitterMinutes?.min ?? 3;
	const jitterMax = parsed.jitterMinutes?.max ?? 12;
	const startAt = parsed.startAt ? new Date(parsed.startAt) : new Date(Date.now() + 30 * 60 * 1000);
	if (Number.isNaN(startAt.getTime())) {
		return apiError(res, 400, "startAt must be a valid ISO date");
	}
	const report = await buildCampaignScheduleManagerReport(userId, creator);
	const safeAccounts = report.accountBuckets.safe_to_schedule_today;
	const safeAccountsById = new Map<string, Record<string, any>>(safeAccounts.map((account: Record<string, any>) => [account.accountId, account]));
	const { data } = await db()
		.from("posts")
		.select("id,user_id,status,platform,scheduled_for,instagram_account_id,metadata,media_urls,media_type,ig_media_type,content_surface,campaign_factory_asset_id,campaign_factory_distribution_plan_id,campaign_factory_post_key,campaign_factory_content_fingerprint,campaign_factory_caption_hash,campaign_factory_concept_id,campaign_factory_parent_asset_id,campaign_factory_variant_family_id,campaign_factory_variant_id,platform_draft_validated")
		.eq("user_id", userId)
		.eq("platform", "instagram")
		.eq("status", "draft")
		.eq("platform_draft_validated", true)
		.not("campaign_factory_asset_id", "is", null)
		.limit(Math.max(100, requestedCount * 4));
	const inventory = ((data ?? []) as Record<string, any>[]).map((post) => draftInventoryRow(post, safeAccountsById));
	const validatedDrafts = inventory.filter((draft) => draft.qstashEligible);
	const status = validatedDrafts.length >= requestedCount ? "ready" : "blocked";
	const blockingReason = status === "ready" ? null : "insufficient_validated_drafts";
	const selectedDrafts = status === "ready" ? validatedDrafts.slice(0, requestedCount) : [];
	const items = [];
	for (const [index, draft] of selectedDrafts.entries()) {
		const jitterMinutes = stableJitterMinutes(index, jitterMin, jitterMax);
		const scheduledFor = new Date(startAt.getTime() + jitterMinutes * 60 * 1000).toISOString();
		const duplicateReason = await hasActiveDuplicate(userId, { ...draft, id: draft.postId, instagram_account_id: draft.accountId, campaign_factory_asset_id: draft.renderedAssetId, campaign_factory_distribution_plan_id: draft.distributionPlanId }, scheduledFor, {
			asset_id: draft.renderedAssetId,
			distribution_plan_id: draft.distributionPlanId,
		});
		const variantConflictReason = await hasVariantLineageConflict(userId, {
			...draft,
			id: draft.postId,
			instagram_account_id: draft.accountId,
			campaign_factory_variant_family_id: draft.variantFamilyId,
			campaign_factory_variant_id: draft.variantId,
		}, scheduledFor, {
			variant_family_id: draft.variantFamilyId,
			variant_id: draft.variantId,
		});
		items.push({
			...draft,
			scheduledFor,
			jitterMinutes,
			duplicateCheck: duplicateReason || variantConflictReason || "clear",
			qstashEligible: draft.qstashEligible && !duplicateReason && !variantConflictReason,
			wouldWrite: false,
		});
	}
	return apiSuccess(res, {
		schema: "threadsdashboard.campaign_schedule_plan.v1",
		creator,
		requestedCount,
		status,
		blockingReason,
		safeAccountsAvailable: safeAccounts.length,
		validatedDraftsAvailable: validatedDrafts.length,
		inventoryCount: inventory.length,
		jitter: { minMinutes: jitterMin, maxMinutes: jitterMax },
		startAt: startAt.toISOString(),
		items,
		inventory: inventory.slice(0, Math.max(requestedCount, 10)),
		wouldWrite: false,
	});
}

export async function handleCampaignScheduleTimePlan(req: VercelRequest, res: VercelResponse, userId: string) {
	const parsed = parseBodyOrError(res, CampaignScheduleTimePlanSchema, {
		creator: requestString(req, "creator") ?? req.body?.creator,
		requestedCount: requestNumber(req, "requestedCount") ?? req.body?.requestedCount,
		startAt: requestString(req, "startAt") ?? req.body?.startAt,
		timezone: requestString(req, "timezone") ?? req.body?.timezone,
		defaultWindow: requestString(req, "defaultWindow") ?? req.body?.defaultWindow,
		minimumSpacingMinutes: requestNumber(req, "minimumSpacingMinutes") ?? req.body?.minimumSpacingMinutes,
	});
	if (!parsed) return;
	const creator = normalizeCreator(parsed.creator) || "Stacey";
	const requestedCount = parsed.requestedCount ?? 10;
	const timezone = parsed.timezone || "America/New_York";
	const recommendedWindow = parsed.defaultWindow || creatorDefaultWindow(creator, timezone);
	const minimumSpacingMinutes = parsed.minimumSpacingMinutes ?? 12;
	const anchor = parsed.startAt ? new Date(parsed.startAt) : new Date(Date.now() + 30 * 60 * 1000);
	if (Number.isNaN(anchor.getTime())) {
		return apiError(res, 400, "startAt must be a valid ISO date");
	}

	const [report, timingHistory] = await Promise.all([
		buildCampaignScheduleManagerReport(userId, creator),
		fetchPublishedTimingHistory(userId),
	]);
	const safeAccounts = report.accountBuckets.safe_to_schedule_today;
	const creatorAccountIds = new Set(report.accounts.map((account: Record<string, any>) => account.accountId));
	const creatorHistory = timingHistory.filter((post) => creatorAccountIds.has(post.instagram_account_id));
	const safeAccountsById = new Map<string, Record<string, any>>(safeAccounts.map((account: Record<string, any>) => [account.accountId, account]));
	const { data } = await db()
		.from("posts")
		.select("id,user_id,status,platform,scheduled_for,instagram_account_id,metadata,media_urls,media_type,ig_media_type,content_surface,campaign_factory_asset_id,campaign_factory_distribution_plan_id,campaign_factory_post_key,campaign_factory_content_fingerprint,campaign_factory_caption_hash,campaign_factory_concept_id,campaign_factory_parent_asset_id,campaign_factory_variant_family_id,campaign_factory_variant_id,platform_draft_validated")
		.eq("user_id", userId)
		.eq("platform", "instagram")
		.eq("status", "draft")
		.eq("platform_draft_validated", true)
		.not("campaign_factory_asset_id", "is", null)
		.limit(Math.max(100, requestedCount * 4));
	const inventory = ((data ?? []) as Record<string, any>[]).map((post) => draftInventoryRow(post, safeAccountsById));
	const validatedDrafts = inventory.filter((draft) => draft.qstashEligible);
	let status = "ready";
	let blockingReason: string | null = null;
	if (safeAccounts.length < requestedCount) {
		status = "blocked";
		blockingReason = "insufficient_safe_accounts";
	} else if (validatedDrafts.length < requestedCount) {
		status = "blocked";
		blockingReason = "insufficient_validated_drafts";
	}

	const selectedDrafts = status === "ready" ? validatedDrafts.slice(0, requestedCount) : [];
	const scheduledDates: Date[] = [];
	const items = [];
	for (const draft of selectedDrafts) {
		const account = safeAccountsById.get(draft.accountId) ?? {};
		const accountHistory = timingHistory.filter((post) => post.instagram_account_id === draft.accountId);
		const cadence = deriveCadence(account, accountHistory, creatorHistory);
		const performance = bestPerformanceHour({
			accountHistory,
			creatorHistory,
			timezone,
			window: recommendedWindow,
		});
		const proposed = alignToPreferredHour(anchor, timezone, recommendedWindow, performance.hour, `${draft.postId}:${draft.accountId}`);
		const spaced = avoidScheduleCollisions(proposed, scheduledDates, minimumSpacingMinutes, timezone, recommendedWindow);
		scheduledDates.push(spaced.date);
		const scheduledFor = spaced.date.toISOString();
		const duplicateReason = await hasActiveDuplicate(userId, { ...draft, id: draft.postId, instagram_account_id: draft.accountId, campaign_factory_asset_id: draft.renderedAssetId, campaign_factory_distribution_plan_id: draft.distributionPlanId }, scheduledFor, {
			asset_id: draft.renderedAssetId,
			distribution_plan_id: draft.distributionPlanId,
		});
		const variantConflictReason = await hasVariantLineageConflict(userId, {
			...draft,
			id: draft.postId,
			instagram_account_id: draft.accountId,
			campaign_factory_variant_family_id: draft.variantFamilyId,
			campaign_factory_variant_id: draft.variantId,
		}, scheduledFor, {
			variant_family_id: draft.variantFamilyId,
			variant_id: draft.variantId,
		});
		items.push({
			...draft,
			accountState: cadence.accountState,
			postsPerDay: cadence.postsPerDay,
			minimumGapHours: cadence.minimumGapHours,
			reasonSafe: `${account.bucket || "safe_to_schedule_today"}; cadence=${cadence.reason}`,
			recommendedWindow,
			scheduledFor,
			localScheduledFor: `${localTimeLabel(spaced.date, timezone)} ${timezone}`,
			spacingReason: spaced.reason,
			performanceTimingReason: performance.reason,
			fallbackUsed: performance.fallbackUsed,
			duplicateCheck: duplicateReason || "clear",
			variantCooldownCheck: variantConflictReason || "clear",
			qstashEligible: draft.qstashEligible && !duplicateReason && !variantConflictReason && cadence.accountState !== "blocked" && cadence.accountState !== "resting",
			wouldWrite: false,
		});
	}

	return apiSuccess(res, {
		schema: "threadsdashboard.campaign_schedule_time_plan.v1",
		creator,
		requestedCount,
		status,
		blockingReason,
		generatedAt: new Date().toISOString(),
		timezone,
		defaultWindow: recommendedWindow,
		minimumSpacingMinutes,
		safeAccountsAvailable: safeAccounts.length,
		validatedDraftsAvailable: validatedDrafts.length,
		inventoryCount: inventory.length,
		items,
		inventory: inventory.slice(0, Math.max(requestedCount, 10)),
		audit: {
			currentTimingBehavior: {
				scheduleWindowDefinedBy: "request_startAt_or_default_now_plus_30_minutes_in_legacy_campaign_schedule_plan",
				actualPostTimesChosenBy: "ThreadsDashboard_campaign_schedule_plan_or_campaign_schedule_time_plan",
				legacyTimingMode: "single_startAt_plus_stable_jitter_minutes",
				legacyConsidersAccountHistory: false,
				legacyConsidersCreatorHistory: false,
				legacyConsidersMetricsByHour: false,
				legacyConsidersWarmupOrAccountAge: false,
				v1TimingMode: "creator_window_plus_cadence_plus_performance_fallback_plus_min_spacing",
			},
			cooldowns: {
				sameVariantSameAccount: "never",
				sameVariantFamilySameAccountDays: DEFAULT_VARIANT_SIBLING_COOLDOWN_DAYS,
				parentReelCooldown: "proposed_for_v2_not_enforced_by_schedule_api_yet",
				conceptCooldown: "proposed_for_v2_not_enforced_by_schedule_api_yet",
			},
		},
		wouldWrite: false,
	});
}
