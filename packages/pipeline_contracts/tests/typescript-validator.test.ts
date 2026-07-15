import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
	generatedPipelineContractSchemaManifest,
	validateAudioIntentContract,
	validateCampaignFactoryDraftPayload,
	validateFrontGenerationPlan,
	validateGenerationExecutionPlan,
	validateGeneratedAssetLineage,
	validateMotionEditRender,
	validatePerformanceSync,
	validatePostMetricHistoryRead,
	validateReferenceVideoMotionAnalysis,
	validateReferenceVideoRemixPlan,
	validateRepurposingPlan,
	validateRecommendationAccuracyReport,
	validateVariantAssignment,
} from "../typescript/index";

const schemaRoot = resolve(__dirname, "../pipeline_contracts/schemas");

function example(name: string) {
	return JSON.parse(
		readFileSync(resolve(schemaRoot, `${name}.v1.example.json`), "utf-8"),
	);
}

function versionedExample(name: string, version: number) {
	return JSON.parse(
		readFileSync(resolve(schemaRoot, `${name}.v${version}.example.json`), "utf-8"),
	);
}

describe("TypeScript pipeline contract validators", () => {
	it("uses emitted JavaScript specifiers for generated schema imports", () => {
		const source = readFileSync(resolve(__dirname, "../typescript/index.ts"), "utf-8");

		expect(source).toContain('from "./generated-schemas.js"');
		expect(source).not.toContain('from "./generated-schemas";');
	});

	it("loads generated schemas for every canonical contract", () => {
		expect(generatedPipelineContractSchemaManifest.map((schema) => schema.filename)).toContain(
			"campaign_draft_payload.v1.schema.json",
		);
		expect(generatedPipelineContractSchemaManifest.map((schema) => schema.filename)).toContain(
			"campaign_draft_payload.v2.schema.json",
		);
		expect(generatedPipelineContractSchemaManifest.map((schema) => schema.filename)).toContain(
			"owned_library_lineage.v1.schema.json",
		);
		expect(generatedPipelineContractSchemaManifest.map((schema) => schema.filename)).toContain(
			"reference_video_motion_analysis.v1.schema.json",
		);
		expect(generatedPipelineContractSchemaManifest.map((schema) => schema.filename)).toContain(
			"reference_video_remix_plan.v1.schema.json",
		);
		expect(generatedPipelineContractSchemaManifest.map((schema) => schema.filename)).toContain(
			"reference_factory_knowledge_pack.v1.schema.json",
		);
		expect(generatedPipelineContractSchemaManifest.map((schema) => schema.filename)).toContain(
			"provider_spend_authorization.v1.schema.json",
		);
		expect(generatedPipelineContractSchemaManifest.map((schema) => schema.filename)).toContain(
			"threadsdash_handshake.v1.schema.json",
		);
		expect(generatedPipelineContractSchemaManifest.map((schema) => schema.filename)).toContain(
			"generation_worker_lineage.v1.schema.json",
		);
		const canonicalSchemaCount = readdirSync(schemaRoot).filter((filename) =>
			filename.endsWith(".schema.json"),
		).length;
		expect(generatedPipelineContractSchemaManifest).toHaveLength(canonicalSchemaCount);
	});

	it("validates structural reference-video analysis and remix plans", () => {
		expect(validateReferenceVideoMotionAnalysis(example("reference_video_motion_analysis"))).toEqual([]);
		expect(validateReferenceVideoRemixPlan(example("reference_video_remix_plan"))).toEqual([]);
	});

	it("keeps paid generation and publishing blocked in remix plans", () => {
		const payload = example("reference_video_remix_plan");
		payload.animation.paidGenerationAuthorized = true;
		payload.approval.publishingAllowed = true;

		expect(validateReferenceVideoRemixPlan(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("paidGenerationAuthorized"),
				expect.stringContaining("publishingAllowed"),
			]),
		);
	});

	it("requires integer provider duration while retaining fractional source timing", () => {
		const payload = example("reference_video_remix_plan");
		expect(payload.scope.sourceDurationSeconds).toBe(7.5);
		expect(payload.scope.outputDurationSeconds).toBe(8);
		payload.animation.inputs.durationSeconds = 7.5;

		expect(validateReferenceVideoRemixPlan(payload)).toEqual(
			expect.arrayContaining([expect.stringContaining("durationSeconds")]),
		);
	});

	it("rejects missing required fields through AJV", () => {
		const payload = example("audio_intent");
		delete payload.gates.allow_publish;

		expect(validateAudioIntentContract(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("allow_publish"),
			]),
		);
	});

	it("uses generated nested draft payload schemas, not hand-written shallow stubs", () => {
		const payload = example("campaign_draft_payload");
		payload.drafts[0].distributionSurface = 123;

		expect(validateCampaignFactoryDraftPayload(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("distributionSurface"),
			]),
		);
	});

	it("dual-accepts v1 and v2 draft payloads", () => {
		expect(validateCampaignFactoryDraftPayload(versionedExample("campaign_draft_payload", 1))).toEqual([]);
		expect(validateCampaignFactoryDraftPayload(versionedExample("campaign_draft_payload", 2))).toEqual([]);
	});

	it("requires promptId in v2 lineage", () => {
		const payload = versionedExample("campaign_draft_payload", 2);
		delete payload.drafts[0].metadata.campaign_factory.generated_asset_lineage.source.promptId;

		expect(validateCampaignFactoryDraftPayload(payload)).toEqual(
			expect.arrayContaining([expect.stringContaining("promptId")]),
		);
	});

	it("rejects invalid enum values through AJV", () => {
		const payload = example("repurposing_plan");
		payload.preset_name = "unknown";

		expect(validateRepurposingPlan(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("preset_name"),
			]),
		);
	});

	it("rejects out-of-range integer values through AJV", () => {
		const payload = example("repurposing_plan");
		payload.target_count = 0;

		expect(validateRepurposingPlan(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("target_count"),
			]),
		);
	});

	it("rejects extra top-level properties through AJV", () => {
		const payload = example("repurposing_plan");
		payload.unexpected = true;

		expect(validateRepurposingPlan(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("unexpected"),
			]),
		);
	});

	it("rejects bad string patterns through AJV", () => {
		const payload = example("repurposing_plan");
		payload.master_asset_id = "asset id with spaces";

		expect(validateRepurposingPlan(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("master_asset_id"),
			]),
		);
	});

	it("validates variant assignment account bindings through AJV", () => {
		const payload = example("variant_assignment");
		delete payload.assignments[0].account_id;

		expect(validateVariantAssignment(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("account_id"),
			]),
		);
	});

	it("rejects invalid variant assignment scores through AJV", () => {
		const payload = example("variant_assignment");
		payload.assignments[0].distinctness_scores.master_ssim = 1.2;

		expect(validateVariantAssignment(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("master_ssim"),
			]),
		);
	});

	it("validates motion edit render zero-cost requirements through AJV", () => {
		const payload = example("motion_edit_render");
		payload.paidGeneration = true;

		expect(validateMotionEditRender(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("paidGeneration"),
			]),
		);
	});

	it("rejects invalid motion edit quality payloads through AJV", () => {
		const payload = example("motion_edit_render");
		delete payload.quality.width;

		expect(validateMotionEditRender(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("width"),
			]),
		);
	});

	it("validates front generation plan review and publishing gates", () => {
		const payload = example("front_generation_plan");
		payload.publishingAllowed = true;

		expect(validateFrontGenerationPlan(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("publishingAllowed"),
			]),
		);
	});

	it("validates the canonical generation execution policy", () => {
		const payload = example("generation_execution_plan");
		expect(validateGenerationExecutionPlan(payload)).toEqual([]);

		payload.motionStrategy = "local_motion_edit";
		expect(validateGenerationExecutionPlan(payload)).toEqual(
			expect.arrayContaining([expect.stringContaining("motionStrategy")]),
		);
	});

	it("rejects invalid front generation budget status through AJV", () => {
		const payload = example("front_generation_plan");
		payload.budgetStatus = "ignored";

		expect(validateFrontGenerationPlan(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("budgetStatus"),
			]),
		);
	});

	it("requires generated asset lineage trace IDs", () => {
		const payload = example("generated_asset_lineage");
		delete payload.pipelineTraceId;

		expect(validateGeneratedAssetLineage(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("pipelineTraceId"),
			]),
		);
	});

	it("requires generated asset lineage inside Campaign Factory draft packages", () => {
		const payload = example("campaign_draft_payload");
		delete payload.drafts[0].metadata.campaign_factory.generated_asset_lineage;

		expect(validateCampaignFactoryDraftPayload(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("generated_asset_lineage"),
			]),
		);
	});

	it("requires recommendation accuracy graph IDs", () => {
		const payload = example("recommendation_accuracy_report");
		delete payload.reportGraphId;

		expect(validateRecommendationAccuracyReport(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("reportGraphId"),
			]),
		);
	});

	it("requires performance sync pipeline causal IDs", () => {
		const payload = example("performance_sync");
		delete payload.pipelineJobId;

		expect(validatePerformanceSync(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("pipelineJobId"),
			]),
		);
	});

	it("requires post metric history selected source columns", () => {
		const payload = example("post_metric_history.read");
		delete payload.rows[0].views_count;

		expect(validatePostMetricHistoryRead(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("views_count"),
			]),
		);
	});
});
