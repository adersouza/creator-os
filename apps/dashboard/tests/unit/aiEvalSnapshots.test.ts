import { describe, expect, it, vi } from "vitest";
import {
	AI_EVAL_DIRECT_GENERATIVE_SURFACES,
	AI_EVAL_DOCUMENTED_NON_GENERATIVE_SURFACES,
	buildAIEvalSnapshotRow,
	hashStableValue,
	recordDirectAIEvalSnapshot,
	recordAIEvalSnapshot,
} from "../../api/_lib/aiEvalSnapshots";

function makeInput() {
	return {
		userId: "00000000-0000-0000-0000-000000000001",
		workspaceId: "ws_1",
		groupId: "group_1",
		accountId: "acc_1",
		suiteName: "operator-ai-golden",
		caseId: "opq-001",
		category: "operator_question",
		prompt: "Which accounts need attention?",
		provider: "openai",
		model: "gpt-5.4",
		modelVersion: "2026-05-22",
		parameters: { temperature: 0.2, maxOutputTokens: 800 },
		candidateOutputs: [{ id: "candidate_1", text: "Review token health." }],
		filterResults: [{ id: "policy", passed: true }],
		judgeScores: [{ id: "usefulness", score: 0.94 }],
		selectedOutput: { id: "candidate_1", text: "Review token health." },
		selectedOutputId: "candidate_1",
		insertedIds: ["idea_1"],
		scheduledIds: ["post_1"],
		performanceSnapshot: { acceptedByOperator: true },
		regressionScore: 0.98,
		passed: true,
		failures: [],
		metadata: { promptId: "prompt_1" },
		capturedAt: "2026-05-22T18:00:00.000Z",
	};
}

describe("AI eval snapshots", () => {
	it("builds a complete persistent snapshot row", () => {
		const row = buildAIEvalSnapshotRow(makeInput());

		expect(row).toMatchObject({
			user_id: "00000000-0000-0000-0000-000000000001",
			workspace_id: "ws_1",
			group_id: "group_1",
			account_id: "acc_1",
			suite_name: "operator-ai-golden",
			case_id: "opq-001",
			category: "operator_question",
			provider: "openai",
			model: "gpt-5.4",
			model_version: "2026-05-22",
			selected_output_id: "candidate_1",
			inserted_ids: ["idea_1"],
			scheduled_ids: ["post_1"],
			regression_score: 0.98,
			passed: true,
			captured_at: "2026-05-22T18:00:00.000Z",
		});
		expect(row.prompt_hash).toMatch(/^[a-f0-9]{64}$/);
		expect(row.parameters).toEqual({ temperature: 0.2, maxOutputTokens: 800 });
		expect(row.candidate_outputs).toEqual([
			{ id: "candidate_1", text: "Review token health." },
		]);
		expect(row.filter_results).toEqual([{ id: "policy", passed: true }]);
		expect(row.judge_scores).toEqual([{ id: "usefulness", score: 0.94 }]);
	});

	it("hashes stable values independent of object key order", () => {
		expect(hashStableValue({ b: 2, a: { d: 4, c: 3 } })).toBe(
			hashStableValue({ a: { c: 3, d: 4 }, b: 2 }),
		);
	});

	it("persists through the expected Supabase table", async () => {
		const maybeSingle = vi.fn().mockResolvedValue({ data: { id: "snap_1" }, error: null });
		const select = vi.fn().mockReturnValue({ maybeSingle });
		const insert = vi.fn().mockReturnValue({ select });
		const from = vi.fn().mockReturnValue({ insert });

		const result = await recordAIEvalSnapshot(makeInput(), { from } as never);

		expect(from).toHaveBeenCalledWith("ai_eval_snapshots");
		expect(insert).toHaveBeenCalledWith(
			expect.objectContaining({
				suite_name: "operator-ai-golden",
				case_id: "opq-001",
				prompt_hash: expect.stringMatching(/^[a-f0-9]{64}$/),
			}),
		);
		expect(result).toEqual({
			ok: true,
			id: "snap_1",
			promptHash: expect.stringMatching(/^[a-f0-9]{64}$/),
		});
	});

	it("records direct provider snapshots with redaction and source metadata", async () => {
		const maybeSingle = vi.fn().mockResolvedValue({ data: { id: "snap_2" }, error: null });
		const select = vi.fn().mockReturnValue({ maybeSingle });
		const insert = vi.fn().mockReturnValue({ select });
		const from = vi.fn().mockReturnValue({ insert });

		const result = await recordDirectAIEvalSnapshot(
			{
				userId: "user-1",
				surface: "ai_alt_text",
				actionType: "generate_alt_text",
				prompt: "Write alt text for adercial@example.com with token juno_ak_secret",
				output: { altText: "Person holding a product", note: "call 555-123-4567" },
				provider: "gemini",
				model: "gemini-2.0-flash",
				passed: true,
			},
			{ from } as never,
		);

		expect(insert).toHaveBeenCalledWith(
			expect.objectContaining({
				user_id: "user-1",
				suite_name: "live:ai_alt_text",
				case_id: "generate_alt_text",
				category: "ai_alt_text",
				prompt: expect.stringContaining("[EMAIL]"),
				candidate_outputs: [
					expect.objectContaining({
						altText: "Person holding a product",
						note: "call [PHONE]",
					}),
				],
				metadata: expect.objectContaining({
					source: "directProvider",
					surface: "ai_alt_text",
				}),
			}),
		);
		expect(result.ok).toBe(true);
	});

	it("documents direct generative and non-generative AI surface coverage", () => {
		expect(AI_EVAL_DIRECT_GENERATIVE_SURFACES).toEqual(
			expect.arrayContaining([
				"ai_alt_text",
				"ai_vision_score",
				"media_vision",
				"inspiration_idea",
				"trend_pipeline_generator",
			]),
		);
		expect(AI_EVAL_DOCUMENTED_NON_GENERATIVE_SURFACES).toEqual(
			expect.arrayContaining([
				"ai_image_generation",
				"deterministic_publish_preflight",
			]),
		);
	});
});
