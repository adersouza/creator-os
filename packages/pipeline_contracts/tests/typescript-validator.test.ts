import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
	generatedPipelineContractSchemaManifest,
	validateAudioIntentContract,
	validateCampaignFactoryDraftPayload,
	validateFrontGenerationPlan,
	validateGeneratedAssetLineage,
	validateMotionEditRender,
	validatePerformanceSync,
	validatePostMetricHistoryRead,
	validateRepurposingPlan,
	validateRecommendationAccuracyReport,
	validateVariantAssignment,
} from "../typescript/index";

const schemaRoot = resolve(__dirname, "../schemas");

function example(name: string) {
	return JSON.parse(
		readFileSync(resolve(schemaRoot, `${name}.v1.example.json`), "utf-8"),
	);
}

describe("TypeScript pipeline contract validators", () => {
	it("loads generated schemas for every canonical contract", () => {
		expect(generatedPipelineContractSchemaManifest.map((schema) => schema.filename)).toContain(
			"campaign_draft_payload.v1.schema.json",
		);
		expect(generatedPipelineContractSchemaManifest).toHaveLength(18);
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
