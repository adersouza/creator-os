import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFrom = vi.fn();
const mockFilterAndLog = vi.fn();
const mockScoreContent = vi.fn();
const mockCheckSemanticDedup = vi.fn();
const mockJudgeBatch = vi.fn();
const mockRunPrefilter = vi.fn();

vi.mock("../../api/_lib/logger.js", () => ({
	logger: {
		debug: vi.fn(),
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
	},
}));

vi.mock("../../api/_lib/supabase.js", () => ({
	getSupabaseAny: () => ({ from: mockFrom }),
}));

vi.mock("../../api/_lib/handlers/auto-post/contentFilter.js", () => ({
	filterAndLog: (...args: unknown[]) => mockFilterAndLog(...args),
}));

vi.mock("../../api/_lib/handlers/auto-post/contentScorer.js", () => ({
	scoreContent: (...args: unknown[]) => mockScoreContent(...args),
}));

vi.mock("../../api/_lib/handlers/auto-post/embeddingGate.js", () => ({
	checkSemanticDedup: (...args: unknown[]) => mockCheckSemanticDedup(...args),
}));

vi.mock("../../api/_lib/handlers/auto-post/llmJudge.js", () => ({
	judgeBatch: (...args: unknown[]) => mockJudgeBatch(...args),
}));

vi.mock("../../api/_lib/handlers/auto-post/prefilterGate.js", () => ({
	runPrefilter: (...args: unknown[]) => mockRunPrefilter(...args),
}));

import {
	loadRecentVariationPosts,
	runEmbeddingDedupPhase,
	runFastFilterPhase,
	runLLMJudgePhase,
	type FilterSurvivor,
} from "../../api/_lib/handlers/auto-post/pipelineFilters";

function insertOnlyQuery() {
	return {
		insert: vi.fn().mockResolvedValue({ data: null, error: null }),
	};
}

function recentVariationQuery(rows: Array<{ content: string; content_type?: string | null }>) {
	const query = {
		select: vi.fn(() => query),
		eq: vi.fn(() => query),
		in: vi.fn(() => query),
		order: vi.fn(() => query),
		limit: vi.fn().mockResolvedValue({ data: rows, error: null }),
	};
	return query;
}

function survivor(content: string, index = 0): FilterSurvivor {
	return {
		index,
		scheduledFor: `2026-05-0${index + 1}T12:00:00Z`,
		idea: { content, contentType: "question" },
	};
}

beforeEach(() => {
	vi.clearAllMocks();
	vi.useRealTimers();
	mockFrom.mockReturnValue(insertOnlyQuery());
	mockFilterAndLog.mockReturnValue({ passed: true });
	mockScoreContent.mockReturnValue({
		passed: true,
		replyTrigger: 8,
		emotionalWarmth: 8,
	});
	mockRunPrefilter.mockResolvedValue({ passed: true });
	mockCheckSemanticDedup.mockResolvedValue({ passed: true });
	mockJudgeBatch.mockResolvedValue([]);
});

describe("pipelineFilters", () => {
	it("loads recent variation posts from queue rows", async () => {
		mockFrom.mockReturnValueOnce(recentVariationQuery([
			{ content: "Hello world", content_type: "question" },
			{ content: "second post", content_type: null },
		]));

		const posts = await loadRecentVariationPosts("workspace-1");

		expect(mockFrom).toHaveBeenCalledWith("auto_post_queue");
		expect(posts).toEqual([
			{
				content: "Hello world",
				charLen: 11,
				openingWord: "hello",
				contentType: "question",
			},
			{
				content: "second post",
				charLen: 11,
				openingWord: "second",
				contentType: null,
			},
		]);
	});

	it("normalizes content and keeps fast-filter survivors", async () => {
		const result = await runFastFilterPhase(
			[{ content: '"This is a warm reply trigger."' }],
			["2026-05-01T12:00:00Z"],
			2,
			{ enabled: true, blockedWords: [] } as any,
			[],
			"workspace-1",
			"group-1",
			Date.now(),
		);

		expect(result.rejectedCount).toBe(0);
		expect(result.survivors).toHaveLength(1);
		expect(result.survivors[0].idea.content).toBe("This is a warm reply trigger");
		expect(mockFilterAndLog).toHaveBeenCalledWith(
			"This is a warm reply trigger",
			"ai",
			expect.any(Object),
			{ workspaceId: "workspace-1", groupId: "group-1" },
			undefined,
			undefined,
		);
		expect(mockScoreContent).toHaveBeenCalledWith(
			"This is a warm reply trigger",
			null,
		);
	});

	it("records fast-filter rejection reasons for length, content filter, and scorer failures", async () => {
		mockFilterAndLog
			.mockReturnValueOnce({ passed: false, reason: "blocked_word", matchedText: "spam" })
			.mockReturnValue({ passed: true });
		mockScoreContent.mockReturnValueOnce({
			passed: false,
			rejectReason: "not_replyable",
			replyTrigger: 1,
			emotionalWarmth: 2,
		});

		const long = "x".repeat(151);
		const result = await runFastFilterPhase(
			[
				{ content: long },
				{ content: "blocked but short" },
				{ content: "low quality" },
				{ content: "good question?" },
			],
			[],
			4,
			{ enabled: true, blockedWords: [] } as any,
			[],
			"workspace-1",
			"group-1",
			Date.now(),
			["spam"],
		);

		expect(result.survivors.map((s) => s.idea.content)).toEqual(["low quality", "good question?"]);
		expect(result.survivors[0].idea.qualityGate?.decision).toBe("needs_review");
		expect(result.rejectedCount).toBe(2);
		expect(result.rejectionReasons).toMatchObject({
			too_long: 1,
			blocked_word: 1,
		});
		expect(mockFrom).toHaveBeenCalledWith("auto_post_queue");
	});

	it("fails closed on skipped judge verdicts, stamps passing verdicts, and logs rejects", async () => {
		mockJudgeBatch.mockResolvedValue([
			{ passed: true, score: 87, dimensions: { hook: 9 } },
			{ skipped: true, reason: "no_api_key" },
			{
				passed: false,
				score: 45,
				rejectReason: "unsafe",
				dimensions: { safety: 1 },
				rationale: "too risky",
			},
		]);

		const input = [survivor("strong hook", 0), survivor("skip me", 1), survivor("bad", 2)];
		const result = await runLLMJudgePhase(
			input,
			{ enabled: true, apiKey: "gemini", minScore: 70 },
			"workspace-1",
			"group-1",
		);

		expect(mockJudgeBatch).toHaveBeenCalledWith(
			[
				{ index: 0, content: "strong hook" },
				{ index: 1, content: "skip me" },
				{ index: 2, content: "bad" },
			],
			expect.objectContaining({ apiKey: "gemini", minScore: 70 }),
		);
		expect(result.survivors.map((s) => s.idea.content)).toEqual(["strong hook"]);
		expect((result.survivors[0].idea as any).judgeResult.score).toBe(87);
		expect(result.rejectedCount).toBe(2);
		expect(result.rejectionReasons).toEqual({
			"judge:no_api_key": 1,
			"judge:unsafe": 1,
		});
	});

	it("short-circuits the judge when disabled", async () => {
		const input = [survivor("keep", 0)];
		const result = await runLLMJudgePhase(
			input,
			{ enabled: false, apiKey: "gemini", minScore: 70 },
			"workspace-1",
			undefined,
		);

		expect(result).toEqual({
			survivors: input,
			rejectedCount: 0,
			rejectionReasons: {},
		});
		expect(mockJudgeBatch).not.toHaveBeenCalled();
	});

	it("runs prefilter and semantic dedup before returning insert candidates", async () => {
		mockRunPrefilter
			.mockResolvedValueOnce({ passed: false, reason: "banned_phrase" })
			.mockResolvedValue({ passed: true });
		mockCheckSemanticDedup
			.mockResolvedValueOnce({ passed: false, reason: "near_duplicate", maxSimilarity: 0.931 })
			.mockResolvedValue({ passed: true });

		const result = await runEmbeddingDedupPhase(
			[
				survivor("blocked phrase", 0),
				survivor("same idea rewritten", 1),
				survivor("fresh idea", 2),
			],
			2,
			{ recentContents: ["a", "b", "c", "d", "e"] },
			"gemini-key",
			"workspace-1",
			"group-1",
			Date.now(),
		);

		expect(result.candidates.map((c) => c.idea.content)).toEqual(["fresh idea"]);
		expect(result.rejectedCount).toBe(2);
		expect(result.rejectionReasons).toEqual({
			"prefilter:banned_phrase": 1,
			"semantic-dedup:near_duplicate": 1,
		});
		expect(mockCheckSemanticDedup).toHaveBeenCalledWith(
			"same idea rewritten",
			["a", "b", "c", "d", "e"],
			"gemini-key",
		);
	});

	it("uses a higher trigram threshold for high-curiosity profile posts only", async () => {
		mockRunPrefilter.mockResolvedValue({ passed: true });
		mockCheckSemanticDedup.mockResolvedValue({
			passed: true,
			reason: null,
			maxSimilarity: 0,
		});

		await runEmbeddingDedupPhase(
			[
				survivor("would you date a girl who's obsessed with anime lore?", 0),
				survivor("what's your comfort anime for when you're feeling down?", 1),
			],
			2,
			{ recentContents: ["a", "b", "c", "d", "e"] },
			"gemini-key",
			"workspace-1",
			"group-1",
			Date.now(),
		);

		expect(mockRunPrefilter).toHaveBeenNthCalledWith(
			1,
			"would you date a girl who's obsessed with anime lore?",
			"workspace-1",
			{ trigramThreshold: 0.86 },
		);
		expect(mockRunPrefilter).toHaveBeenNthCalledWith(
			2,
			"what's your comfort anime for when you're feeling down?",
			"workspace-1",
			{},
		);
	});
});
