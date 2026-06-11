import { describe, expect, it } from "vitest";
import {
	buildAIEvalReport,
	evaluateAIEvalThresholds,
	type AIEvalSuiteRow,
} from "../../api/_lib/aiEvalReporting";

describe("AI eval reporting", () => {
	it("groups eval trends by suite, surface, and day", () => {
		const report = buildAIEvalReport([
			{
				id: "snap-1",
				suite_name: "operator-ai-golden",
				case_id: "opq-001",
				category: "operator_question",
				model: "gpt-5.4",
				regression_score: 1,
				passed: true,
				failures: [],
				captured_at: "2026-05-22T09:00:00.000Z",
			},
			{
				id: "snap-2",
				suite_name: "operator-ai-golden",
				case_id: "opq-002",
				category: "operator_question",
				model: "gpt-5.4",
				regression_score: 0.5,
				passed: false,
				failures: ["missing scope"],
				captured_at: "2026-05-22T13:00:00.000Z",
			},
			{
				id: "snap-3",
				suite_name: "live:ai_alt_text",
				case_id: "generate_alt_text",
				category: "ai_alt_text",
				model: "gemini-2.0-flash",
				regression_score: 0.9,
				passed: true,
				failures: [],
				captured_at: "2026-05-23T01:00:00.000Z",
			},
		]);

		expect(report).toMatchObject({
			total: 3,
			passed: 2,
			failed: 1,
			passRate: 67,
			avgRegressionScore: 0.8,
		});
		expect(report.trend).toEqual([
			expect.objectContaining({
				day: "2026-05-22",
				suiteName: "operator-ai-golden",
				surface: "operator_question",
				total: 2,
				passed: 1,
				failed: 1,
				passRate: 50,
				avgRegressionScore: 0.75,
			}),
			expect.objectContaining({
				day: "2026-05-23",
				suiteName: "live:ai_alt_text",
				surface: "ai_alt_text",
				total: 1,
				passRate: 100,
			}),
		]);
		expect(report.suites).toEqual([
			expect.objectContaining({
				suiteName: "live:ai_alt_text",
				surface: "ai_alt_text",
				passRate: 100,
			}),
			expect.objectContaining({
				suiteName: "operator-ai-golden",
				surface: "operator_question",
				passRate: 50,
				lastCapturedAt: "2026-05-22T13:00:00.000Z",
			}),
		]);
		expect(report.latestFailures).toEqual([
			expect.objectContaining({
				id: "snap-2",
				suiteName: "operator-ai-golden",
				caseId: "opq-002",
				failures: ["missing scope"],
			}),
		]);
	});

	it("enforces deterministic suite thresholds for CI", () => {
		const suites: AIEvalSuiteRow[] = [
			{
				suiteName: "operator-ai-golden",
				surface: "operator_question",
				total: 40,
				passed: 39,
				failed: 1,
				passRate: 98,
				avgRegressionScore: 0.98,
				lastCapturedAt: "2026-05-23T00:00:00.000Z",
			},
			{
				suiteName: "live:ai_alt_text",
				surface: "ai_alt_text",
				total: 10,
				passed: 8,
				failed: 2,
				passRate: 80,
				avgRegressionScore: 0.8,
				lastCapturedAt: "2026-05-23T00:00:00.000Z",
			},
		];

		expect(evaluateAIEvalThresholds(suites)).toEqual({
			passed: false,
			failures: [
				"operator-ai-golden pass rate 98% is below 100% threshold",
			],
		});
	});
});
