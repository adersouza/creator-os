import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
	campaignFactoryAssetStateAllowsExport,
	campaignFactoryPublishabilityFailureReasons,
	explainCampaignFactoryPublishability,
	nativeAudioStatusAllowsPublish,
	validateAudioCatalogExport,
	validateAudioIntentContract,
	validateCampaignFactoryDraftPayload,
	validateHandoffManifestContract,
	validatePerformanceSync,
} from "../src/lib/pipelineContracts";

const pipelineContractsRoot = resolve(__dirname, "../pipeline_contracts");

function readPipelineSchemaExample(name: string) {
	return JSON.parse(
		readFileSync(resolve(pipelineContractsRoot, "schemas", name), "utf-8"),
	);
}

describe("shared pipeline contracts", () => {
	it("accepts the Campaign Factory audio intent example", () => {
		const example = readPipelineSchemaExample("audio_intent.v1.example.json");

		expect(validateAudioIntentContract(example)).toEqual([]);
	});

	it("accepts the Campaign Factory ThreadsDashboard draft example", () => {
		const example = readPipelineSchemaExample("campaign_draft_payload.v1.example.json");

		expect(validateCampaignFactoryDraftPayload(example)).toEqual([]);
		expect(validateCampaignFactoryDraftPayload(example, { strictGraphIds: true })).toEqual([]);
	});

	it("requires graph IDs in strict Campaign Factory draft mode", () => {
		const example = readPipelineSchemaExample("campaign_draft_payload.v1.example.json");
		delete example.drafts[0].metadata.campaign_factory.graph_id;

		expect(validateCampaignFactoryDraftPayload(example)).toEqual([]);
		expect(validateCampaignFactoryDraftPayload(example, { strictGraphIds: true })).toContain(
			"drafts[0].metadata.campaign_factory.graph_id is required",
		);
	});

	it("requires explicit Instagram post captions for non-Story Campaign Factory drafts", () => {
		const example = readPipelineSchemaExample("campaign_draft_payload.v1.example.json");
		const campaignFactory = example.drafts[0].metadata.campaign_factory;
		example.drafts[0].content = "burned overlay text is not a post caption";
		campaignFactory.instagram_post_caption = "";
		campaignFactory.instagramPostCaption = "";
		campaignFactory.handoff_manifest.instagram_post_caption = "";
		campaignFactory.handoff_manifest.instagramPostCaption = "";

		expect(validateCampaignFactoryDraftPayload(example)).toContain(
			"drafts[0].metadata.campaign_factory.instagram_post_caption is required for non-Story Instagram surfaces",
		);
	});

	it("requires passed visual QC and identity verification for Campaign Factory handoff", () => {
		const example = readPipelineSchemaExample("campaign_draft_payload.v1.example.json");
		const campaignFactory = example.drafts[0].metadata.campaign_factory;
		campaignFactory.visualQcStatus = "unavailable";
		campaignFactory.identityVerificationStatus = "failed";
		campaignFactory.handoff_manifest.visualQcStatus = "unavailable";
		campaignFactory.handoff_manifest.identityVerificationStatus = "failed";

		expect(validateCampaignFactoryDraftPayload(example)).toEqual(
			expect.arrayContaining([
				"drafts[0].metadata.campaign_factory.handoff_manifest.visualQcStatus must be passed",
				"drafts[0].metadata.campaign_factory.handoff_manifest.identityVerificationStatus must be passed",
			]),
		);
	});

	it("accepts the Reference Factory audio catalog export example", () => {
		const example = readPipelineSchemaExample("audio_catalog_export.v1.example.json");

		expect(validateAudioCatalogExport(example)).toEqual([]);
	});

	it("accepts the Campaign Factory performance sync example", () => {
		const example = readPipelineSchemaExample("performance_sync.v1.example.json");

		expect(validatePerformanceSync(example)).toEqual([]);
	});

	it("keeps only final native-audio statuses publish-safe", () => {
		for (const status of ["recommended", "needs_operator_selection", "selected", "needs_review", "blocked", "burned"]) {
			expect(nativeAudioStatusAllowsPublish(status)).toBe(false);
		}
		for (const status of ["attached", "verified", "skipped", "not_required"]) {
			expect(nativeAudioStatusAllowsPublish(status)).toBe(true);
		}
	});

	it("blocks approved assets from export until they become publishable candidates", () => {
		const example = readPipelineSchemaExample("campaign_draft_payload.v1.example.json");
		const campaignFactory = example.drafts[0].metadata.campaign_factory;
		campaignFactory.asset_state = "approved_but_not_publishable";
		campaignFactory.captioned_render_present = false;
		campaignFactory.visible_caption_verification = "fail";
		delete campaignFactory.content_fingerprint;
		delete campaignFactory.caption_hash;
		delete campaignFactory.captionOutcomeContext;
		delete campaignFactory.caption_outcome_context;
		campaignFactory.audio_intent.status = "recommended";
		delete campaignFactory.audio_intent.operator_selection;
		campaignFactory.readiness_checks_pass = false;

		expect(campaignFactoryAssetStateAllowsExport(campaignFactory.asset_state)).toBe(false);
		expect(explainCampaignFactoryPublishability(campaignFactory)).toMatchObject({
			decision: "blocked",
			state: "approved_but_not_publishable",
			checks: {
				captioned_render_present: false,
				visible_caption_verification: false,
				audio_assigned: false,
				readiness_checks_pass: false,
			},
		});
		expect(campaignFactoryPublishabilityFailureReasons(campaignFactory)).toEqual(
			expect.arrayContaining([
				"missing_burned_captions",
				"missing_caption_hash",
				"missing_caption_outcome_context",
				"missing_content_fingerprint",
				"missing_audio",
				"readiness_failed",
			]),
		);
		expect(validateCampaignFactoryDraftPayload(example)).toEqual(
			expect.arrayContaining([
				"drafts[0].metadata.campaign_factory.asset_state must be publishable_candidate or exportable, got approved_but_not_publishable",
				"drafts[0].metadata.campaign_factory.publishable_candidate missing missing_burned_captions",
				"drafts[0].metadata.campaign_factory.publishable_candidate missing missing_caption_hash",
				"drafts[0].metadata.campaign_factory.publishable_candidate missing missing_caption_outcome_context",
				"drafts[0].metadata.campaign_factory.publishable_candidate missing missing_content_fingerprint",
				"drafts[0].metadata.campaign_factory.publishable_candidate missing missing_audio",
				"drafts[0].metadata.campaign_factory.publishable_candidate missing readiness_failed",
			]),
		);
	});

	it("requires a complete immutable handoff manifest for draft export", () => {
		const example = readPipelineSchemaExample("campaign_draft_payload.v1.example.json");
		const campaignFactory = example.drafts[0].metadata.campaign_factory;

		delete campaignFactory.handoff_manifest;
		expect(validateHandoffManifestContract(campaignFactory)).toEqual([
			"handoff_manifest is required",
		]);
		expect(validateCampaignFactoryDraftPayload(example)).toContain(
			"drafts[0].metadata.campaign_factory.handoff_manifest is required",
		);

		campaignFactory.handoff_manifest = {
			manifest_version: 1,
			asset_id: "wrong_asset",
			render_file_id: "render_file_smoke",
			content_fingerprint: "wrong_fp",
			caption_hash: "wrong_caption",
			captionOutcomeContext: {
				schema: "campaign_factory.caption_outcome_context.v1",
				caption_hash: "wrong_caption",
			},
			visual_verification_id: "visual_verify_smoke",
			caption_verification_id: "caption_verify_smoke",
			audio_id: "ig_runway_pop",
			distribution_plan_id: "dist_smoke",
			exported_by_system: "campaign_factory",
			exported_at: "2026-06-04T12:05:00Z",
		};

		expect(validateHandoffManifestContract(campaignFactory)).toEqual(
			expect.arrayContaining([
				"handoff_manifest.asset_id mismatch",
				"handoff_manifest.content_fingerprint mismatch",
				"handoff_manifest.caption_hash mismatch",
				"handoff_manifest.captionOutcomeContext.caption_hash mismatch",
			]),
		);
	});

	it("accepts additive variant lineage and rejects handoff mismatches when present", () => {
		const example = readPipelineSchemaExample("campaign_draft_payload.v1.example.json");
		const campaignFactory = example.drafts[0].metadata.campaign_factory;
		campaignFactory.concept_id = "concept_1";
		campaignFactory.parent_asset_id = "asset_parent";
		campaignFactory.variant_family_id = "vfam_1";
		campaignFactory.variant_id = "variant_1";
		campaignFactory.handoff_manifest.concept_id = "concept_1";
		campaignFactory.handoff_manifest.parent_asset_id = "asset_parent";
		campaignFactory.handoff_manifest.variant_family_id = "vfam_1";
		campaignFactory.handoff_manifest.variant_id = "variant_1";

		expect(validateCampaignFactoryDraftPayload(example)).toEqual([]);

		campaignFactory.handoff_manifest.variant_family_id = "wrong_family";
		expect(validateHandoffManifestContract(campaignFactory)).toContain(
			"handoff_manifest.variant_family_id mismatch",
		);
	});
});
