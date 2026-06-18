import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
	validateAudioIntentContract,
	validateRepurposingPlan,
	validateVariantAssignment,
} from "../typescript/index";

const schemaRoot = resolve(__dirname, "../schemas");

function example(name: string) {
	return JSON.parse(
		readFileSync(resolve(schemaRoot, `${name}.v1.example.json`), "utf-8"),
	);
}

describe("TypeScript pipeline contract validators", () => {
	it("rejects missing required fields through AJV", () => {
		const payload = example("audio_intent");
		delete payload.gates.allow_publish;

		expect(validateAudioIntentContract(payload)).toEqual(
			expect.arrayContaining([
				expect.stringContaining("allow_publish"),
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
});
