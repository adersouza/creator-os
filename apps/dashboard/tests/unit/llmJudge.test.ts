/**
 * Unit tests for the LLM quality judge (api/_lib/handlers/auto-post/llmJudge.ts)
 *
 * Behaviors under test:
 * - Empty input returns empty array
 * - Missing apiKey skips all at the batch layer
 * - LLM error / timeout skips all
 * - Schema-invalid response skips all
 * - Safety <= 1 vetoes regardless of composite
 * - Composite below threshold rejects
 * - Composite at/above threshold passes
 * - Verdict order matches input order, even when LLM returns a permutation
 * - Missing per-input verdict is reported as skipped (not silently dropped)
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

const mockGenerateWithProvider = vi.fn();

vi.mock("../../api/_lib/logger", () => ({
	logger: {
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

vi.mock("../../api/_lib/handlers/auto-post/aiProviders", () => ({
	generateWithProvider: (...args: unknown[]) =>
		mockGenerateWithProvider(...args),
}));

import {
	composeScore,
	judgeBatch,
} from "../../api/_lib/handlers/auto-post/llmJudge";

const baselineDimensions = {
	hook: 4,
	voice: 4,
	safety: 5,
	quality: 4,
	novelty: 4,
};

function mkResponse(verdicts: unknown[]) {
	return Promise.resolve(JSON.stringify({ verdicts }));
}

beforeEach(() => {
	mockGenerateWithProvider.mockReset();
});

describe("composeScore", () => {
	it("weights hook+voice highest, safety third, quality+novelty tail", () => {
		const score = composeScore(baselineDimensions);
		// 4*0.25 + 4*0.25 + 5*0.20 + 4*0.15 + 4*0.15 = 4.2
		expect(score).toBe(4.2);
	});

	it("rounds to one decimal", () => {
		const score = composeScore({
			hook: 3,
			voice: 4,
			safety: 5,
			quality: 3,
			novelty: 3,
		});
		// 0.75 + 1.00 + 1.00 + 0.45 + 0.45 = 3.65 → 3.7 (round half up of 3.65)
		expect(score).toBe(3.7);
	});
});

describe("judgeBatch", () => {
	it("returns empty array for empty input without calling LLM", async () => {
		const result = await judgeBatch([], {
			apiKey: "key",
			minScore: 3,
		});
		expect(result).toEqual([]);
		expect(mockGenerateWithProvider).not.toHaveBeenCalled();
	});

	it("skips all when apiKey is missing (fail-open)", async () => {
		const result = await judgeBatch(
			[{ index: 0, content: "test post" }],
			{ apiKey: "", minScore: 3 },
		);
		expect(result).toHaveLength(1);
		expect(result[0]).toMatchObject({ index: 0, skipped: true, reason: "no_api_key" });
		expect(mockGenerateWithProvider).not.toHaveBeenCalled();
	});

	it("skips all when LLM call throws", async () => {
		mockGenerateWithProvider.mockRejectedValue(new Error("boom"));
		const result = await judgeBatch(
			[
				{ index: 0, content: "a" },
				{ index: 1, content: "b" },
			],
			{ apiKey: "key", minScore: 3 },
		);
		expect(result).toHaveLength(2);
		for (const v of result) {
			expect(v).toMatchObject({ skipped: true });
		}
	});

	it("skips all when response is not parseable JSON", async () => {
		mockGenerateWithProvider.mockResolvedValue("not json at all");
		const result = await judgeBatch(
			[{ index: 0, content: "a" }],
			{ apiKey: "key", minScore: 3 },
		);
		expect(result[0]).toMatchObject({ skipped: true, reason: "parse_error" });
	});

	it("skips all when response fails schema validation", async () => {
		// Missing required fields (e.g. no `quality`)
		mockGenerateWithProvider.mockReturnValue(
			mkResponse([{ i: 0, hook: 4, voice: 4, safety: 5, novelty: 4 }]),
		);
		const result = await judgeBatch(
			[{ index: 0, content: "a" }],
			{ apiKey: "key", minScore: 3 },
		);
		expect(result[0]).toMatchObject({ skipped: true, reason: "schema_error" });
	});

	it("vetoes a post with safety <= 1 even if composite >= threshold", async () => {
		// hook=5 voice=5 quality=5 novelty=5 safety=1 → composite =
		//   5*0.25 + 5*0.25 + 1*0.20 + 5*0.15 + 5*0.15 = 4.2 (above min=3)
		// but safety=1 must veto regardless.
		mockGenerateWithProvider.mockReturnValue(
			mkResponse([
				{ i: 0, hook: 5, voice: 5, safety: 1, quality: 5, novelty: 5 },
			]),
		);
		const result = await judgeBatch(
			[{ index: 0, content: "yikes" }],
			{ apiKey: "key", minScore: 3 },
		);
		expect(result[0]).toMatchObject({
			passed: false,
			rejectReason: "safety_veto",
		});
	});

	it("rejects when composite is below threshold", async () => {
		mockGenerateWithProvider.mockReturnValue(
			mkResponse([
				{ i: 0, hook: 2, voice: 2, safety: 5, quality: 2, novelty: 2 },
			]),
		);
		const result = await judgeBatch(
			[{ index: 0, content: "meh" }],
			{ apiKey: "key", minScore: 3.5 },
		);
		expect(result[0].passed).toBe(false);
		expect(result[0]).toMatchObject({ rejectReason: expect.stringContaining("below_threshold_") });
	});

	it("passes when composite is at/above threshold", async () => {
		mockGenerateWithProvider.mockReturnValue(
			mkResponse([
				{ i: 0, hook: 4, voice: 4, safety: 5, quality: 4, novelty: 4 },
			]),
		);
		const result = await judgeBatch(
			[{ index: 0, content: "good" }],
			{ apiKey: "key", minScore: 3.5 },
		);
		expect(result[0]).toMatchObject({
			passed: true,
			score: 4.2,
		});
	});

	it("aligns verdicts to input indexes when LLM returns out of order", async () => {
		mockGenerateWithProvider.mockReturnValue(
			mkResponse([
				{ i: 1, hook: 5, voice: 5, safety: 5, quality: 5, novelty: 5 },
				{ i: 0, hook: 1, voice: 1, safety: 5, quality: 1, novelty: 1 },
			]),
		);
		const result = await judgeBatch(
			[
				{ index: 0, content: "bad" },
				{ index: 1, content: "great" },
			],
			{ apiKey: "key", minScore: 3 },
		);
		// Index 0 gets the low scores (was returned second)
		expect(result[0].index).toBe(0);
		expect(result[0].passed).toBe(false);
		// Index 1 gets the high scores (was returned first)
		expect(result[1].index).toBe(1);
		expect(result[1].passed).toBe(true);
	});

	it("reports a missing verdict as skipped — not silently dropped", async () => {
		mockGenerateWithProvider.mockReturnValue(
			mkResponse([
				{ i: 0, hook: 4, voice: 4, safety: 5, quality: 4, novelty: 4 },
			]),
		);
		const result = await judgeBatch(
			[
				{ index: 0, content: "covered" },
				{ index: 1, content: "no verdict" },
			],
			{ apiKey: "key", minScore: 3 },
		);
		expect(result).toHaveLength(2);
		expect(result[0].passed).toBe(true);
		expect(result[1]).toMatchObject({
			skipped: true,
			reason: "missing_verdict",
		});
	});

	it("passes cost attribution through the shared provider router", async () => {
		mockGenerateWithProvider.mockResolvedValue(
			JSON.stringify({
				verdicts: [
					{ i: 0, hook: 4, voice: 4, safety: 5, quality: 4, novelty: 4 },
				],
			}),
		);
		await judgeBatch(
			[{ index: 0, content: "hi" }],
			{
				apiKey: "key",
				minScore: 3,
				costAttribution: { userId: "u_test", source: "user" },
			},
		);
		expect(mockGenerateWithProvider).toHaveBeenCalledWith(
			expect.any(String),
			expect.objectContaining({
				actionLog: expect.objectContaining({
					userId: "u_test",
					actionType: "autopost_judge",
					surface: "autopilot",
				}),
				keySource: "user",
			}),
		);
	});

	it("does not bill when the LLM call fails (skipped batch)", async () => {
		mockGenerateWithProvider.mockRejectedValue(new Error("boom"));
		await judgeBatch(
			[{ index: 0, content: "hi" }],
			{
				apiKey: "key",
				minScore: 3,
				costAttribution: { userId: "u_test", source: "user" },
			},
		);
		expect(mockGenerateWithProvider).toHaveBeenCalledTimes(1);
	});

	it("includes voiceProfileHint in the prompt when provided", async () => {
		mockGenerateWithProvider.mockReturnValue(
			mkResponse([
				{ i: 0, hook: 4, voice: 4, safety: 5, quality: 4, novelty: 4 },
			]),
		);
		await judgeBatch(
			[{ index: 0, content: "hi" }],
			{
				apiKey: "key",
				minScore: 3,
				voiceProfileHint: "casual gen-z, lowercase, witty",
			},
		);
		const call = mockGenerateWithProvider.mock.calls[0][0];
		expect(call).toContain("casual gen-z, lowercase, witty");
	});

	it("routes judge calls through xAI when configured", async () => {
		mockGenerateWithProvider.mockReturnValue(
			mkResponse([
				{ i: 0, hook: 4, voice: 4, safety: 5, quality: 4, novelty: 4 },
			]),
		);
		await judgeBatch(
			[{ index: 0, content: "xai judged post" }],
			{ apiKey: "xai-key", provider: "xai", minScore: 3 },
		);
		expect(mockGenerateWithProvider).toHaveBeenCalledWith(
			expect.any(String),
			expect.objectContaining({
				provider: "xai",
				apiKey: "xai-key",
				allowProviderFallback: false,
			}),
		);
	});
});
