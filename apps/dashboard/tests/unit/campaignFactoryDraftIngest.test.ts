import { describe, expect, it } from "vitest";
import { validateCampaignFactoryDraftIngest } from "../../api/_lib/handlers/campaign-factory/draftIngest.js";
import { CAMPAIGN_DRAFT_PAYLOAD_SCHEMA_ID } from "../../pipeline_contracts/typescript.js";

function campaignFactoryMetadata(overrides: Record<string, unknown> = {}) {
	const captionOutcomeContext = {
		schema: "campaign_factory.caption_outcome_context.v1",
		caption_hash: "caption_hash_1",
	};
	return {
		asset_state: "exportable",
		content_surface: "reel",
		ig_media_type: "REELS",
		approved: true,
		captioned_render_present: true,
		visible_caption_verification: "pass",
		expected_visual_verification: "pass",
		content_fingerprint: "fingerprint_1",
		caption_hash: "caption_hash_1",
		captionOutcomeContext,
		audio_intent: {
			schema: "pipeline.audio_intent.v1",
			mode: "native_platform_audio",
			required: false,
			status: "not_required",
			platform: "instagram",
			recommendations: [],
			gates: { allow_draft_export: true, allow_publish: true },
		},
		readiness_checks_pass: true,
		instagram_post_caption: "lmk #fyp",
		visualQcStatus: "passed",
		identityVerificationStatus: "passed",
		surfaceReadiness: { canHandoff: true, blockingReasons: [] },
		handoff_manifest: {
			manifest_version: 2,
			asset_id: "asset_1",
			render_file_id: "render_1",
			content_fingerprint: "fingerprint_1",
			caption_hash: "caption_hash_1",
			instagram_post_caption: "lmk #fyp",
			captionOutcomeContext,
			visual_verification_id: "visual_1",
			caption_verification_id: "caption_1",
			audio_id: "audio_not_required",
			distribution_plan_id: "dist_1",
			exported_by_system: "campaign_factory",
			exported_at: "2026-06-16T00:00:00+00:00",
			content_surface: "reel",
			ig_media_type: "REELS",
			visualQcStatus: "passed",
			identityVerificationStatus: "passed",
			mediaItems: [{ type: "video", url: "https://cdn.example.com/reel.mp4" }],
			surfaceReadiness: { canHandoff: true, blockingReasons: [] },
		},
		...overrides,
	};
}

function payload(campaignFactory: Record<string, unknown> = campaignFactoryMetadata()) {
	return {
		schema: CAMPAIGN_DRAFT_PAYLOAD_SCHEMA_ID,
		campaign: "stacey",
		drafts: [
			{
				platform: "instagram",
				status: "draft",
				content: "lmk #fyp",
				content_surface: "reel",
				ig_media_type: "REELS",
				media: [{ type: "video", url: "https://cdn.example.com/reel.mp4" }],
				metadata: { campaign_factory: campaignFactory },
			},
		],
	};
}

describe("validateCampaignFactoryDraftIngest", () => {
	it("accepts a valid schedule-safe Campaign Factory Reel envelope without writing", () => {
		const result = validateCampaignFactoryDraftIngest(payload());

		expect(result).toMatchObject({
			ok: true,
			acceptedDrafts: 1,
			rejectedDrafts: 0,
			wouldWrite: false,
		});
		expect(result.items[0]).toMatchObject({
			ok: true,
			contentSurface: "reel",
			igMediaType: "REELS",
			wouldWrite: false,
		});
	});

	it("rejects stale manifest versions at ingest", () => {
		const cf = campaignFactoryMetadata({
			handoff_manifest: {
				...(campaignFactoryMetadata().handoff_manifest as Record<string, unknown>),
				manifest_version: 1,
			},
		});

		const result = validateCampaignFactoryDraftIngest(payload(cf));

		expect(result.ok).toBe(false);
		expect(result.items[0]?.blockers).toContain("handoff_manifest_v2_required");
	});

	it("rejects non-Story drafts without explicit Instagram post captions", () => {
		const cf = campaignFactoryMetadata({
			instagram_post_caption: "",
			handoff_manifest: {
				...(campaignFactoryMetadata().handoff_manifest as Record<string, unknown>),
				instagram_post_caption: "",
			},
		});

		const result = validateCampaignFactoryDraftIngest(payload(cf));

		expect(result.ok).toBe(false);
		expect(result.items[0]?.blockers).toContain("instagram_post_caption_missing");
	});

	it("does not treat draft content as an Instagram post caption fallback", () => {
		const cf = campaignFactoryMetadata({
			instagram_post_caption: "",
			instagramPostCaption: "",
			handoff_manifest: {
				...(campaignFactoryMetadata().handoff_manifest as Record<string, unknown>),
				instagram_post_caption: "",
				instagramPostCaption: "",
			},
		});
		const body = payload(cf);
		body.drafts[0].content = "burned overlay text should not become a post caption";

		const result = validateCampaignFactoryDraftIngest(body);

		expect(result.ok).toBe(false);
		expect(result.items[0]?.blockers).toContain("instagram_post_caption_missing");
	});

	it("rejects visual QC or identity verification that has not passed", () => {
		const cf = campaignFactoryMetadata({
			visualQcStatus: "unavailable",
			identityVerificationStatus: "failed",
			handoff_manifest: {
				...(campaignFactoryMetadata().handoff_manifest as Record<string, unknown>),
				visualQcStatus: "unavailable",
				identityVerificationStatus: "failed",
			},
		});

		const result = validateCampaignFactoryDraftIngest(payload(cf));

		expect(result.ok).toBe(false);
		expect(result.items[0]?.blockers).toEqual(
			expect.arrayContaining(["visual_qc_unavailable", "identity_verification_failed"]),
		);
		expect(result.contractErrors).toEqual(
			expect.arrayContaining([
				"drafts[0].metadata.campaign_factory.handoff_manifest.visualQcStatus must be passed",
				"drafts[0].metadata.campaign_factory.handoff_manifest.identityVerificationStatus must be passed",
			]),
		);
	});

	it("rejects surface mismatches before Campaign Factory drafts can be ingested", () => {
		const cf = campaignFactoryMetadata({
			content_surface: "story",
			ig_media_type: "STORIES",
			handoff_manifest: {
				...(campaignFactoryMetadata().handoff_manifest as Record<string, unknown>),
				content_surface: "story",
				ig_media_type: "STORIES",
			},
		});

		const result = validateCampaignFactoryDraftIngest(payload(cf));

		expect(result.ok).toBe(false);
		expect(result.items[0]?.blockers).toEqual(
			expect.arrayContaining([
				"content_surface_source_mismatch:reel:story",
				"ig_media_type_source_mismatch:REELS:STORIES",
			]),
		);
	});

	it("rejects quarantined or non-schedule-safe assets", () => {
		const cf = campaignFactoryMetadata({
			quarantined: true,
			surfaceReadiness: { canHandoff: false, blockingReasons: ["quarantined_asset"] },
			handoff_manifest: {
				...(campaignFactoryMetadata().handoff_manifest as Record<string, unknown>),
				surfaceReadiness: { canHandoff: false, blockingReasons: ["quarantined_asset"] },
			},
		});

		const result = validateCampaignFactoryDraftIngest(payload(cf));

		expect(result.ok).toBe(false);
		expect(result.items[0]?.blockers).toEqual(
			expect.arrayContaining([
				"publishability_quarantined_asset",
				"schedule_safe_readiness_missing_or_blocked",
			]),
		);
	});
});
