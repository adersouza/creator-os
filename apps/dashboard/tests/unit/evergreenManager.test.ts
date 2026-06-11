import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockFrom = vi.fn();
const mockGenerateContent = vi.fn();
const mockCheckDailySpendLimit = vi.fn();
const mockTrackAICost = vi.fn();

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

vi.mock("@google/genai", () => ({
	GoogleGenAI: vi.fn(function GoogleGenAI() {
		return { models: { generateContent: mockGenerateContent } };
	}),
}));

vi.mock("../../api/_lib/aiCostTracker.js", () => ({
	checkDailySpendLimit: () => mockCheckDailySpendLimit(),
	trackAICost: (...args: unknown[]) => mockTrackAICost(...args),
}));

import {
	detectTopicTag,
	humanizePost,
	insertProvenTemplate,
	recycleEvergreenPosts,
} from "../../api/_lib/handlers/auto-post/evergreenManager";

function selectQuery(data: unknown) {
	const query = {
		select: vi.fn(() => query),
		eq: vi.fn(() => query),
		in: vi.fn(() => query),
		not: vi.fn(() => query),
		gte: vi.fn(() => query),
		or: vi.fn(() => query),
		order: vi.fn(() => query),
		limit: vi.fn().mockResolvedValue({ data, error: null }),
		maybeSingle: vi.fn().mockResolvedValue({ data, error: null }),
	};
	return query;
}

function insertQuery(error: unknown = null) {
	return {
		insert: vi.fn().mockResolvedValue({ data: null, error }),
	};
}

function updateQuery() {
	const query = {
		update: vi.fn(() => query),
		eq: vi.fn().mockResolvedValue({ data: null, error: null }),
	};
	return query;
}

function setRandom(values: number[]) {
	let i = 0;
	return vi.spyOn(Math, "random").mockImplementation(() => {
		const value = values[Math.min(i, values.length - 1)];
		i++;
		return value;
	});
}

beforeEach(() => {
	vi.clearAllMocks();
	vi.useFakeTimers();
	vi.setSystemTime(new Date("2026-05-05T12:00:00Z"));
	delete process.env.AUTOPOSTER_AI_RECYCLE_REWRITES;
	delete process.env.GEMINI_API_KEY;
	mockCheckDailySpendLimit.mockResolvedValue({ allowed: true, spentUsd: 0, limitUsd: 10 });
	mockGenerateContent.mockResolvedValue({
		text: "fresh rewritten hook",
		usageMetadata: { promptTokenCount: 10, candidatesTokenCount: 5 },
	});
});

afterEach(() => {
	vi.useRealTimers();
	vi.restoreAllMocks();
});

describe("evergreenManager", () => {
	it("detects specific Threads topic tags before broad categories", () => {
		expect(detectTopicTag("valorant ranked made me uninstall")).toBe("Gaming");
		expect(detectTopicTag("mercury retrograde ruined my group chat")).toBe("Astrology");
		expect(detectTopicTag("would you date someone who hates brunch")).toBe(
			"Dating & Relationships",
		);
		expect(detectTopicTag("this sentence has no mapped niche")).toBeNull();
	});

	it("humanizes text while preserving the grammar fix", () => {
		setRandom([0.9, 0.9, 0.9, 0.9, 0.9, 0.9]);

		const result = humanizePost("I found a apple, really.");

		expect(result).not.toBe("I found a apple, really.");
		expect(result).toMatch(/\ban apple\b/i);
	});

	it("skips proven templates when randomness or capacity says no", async () => {
		setRandom([0.9]);
		expect(await insertProvenTemplate("workspace-1", "group-1", 5)).toBe(0);

		setRandom([0.1]);
		expect(await insertProvenTemplate("workspace-1", "group-1", 1)).toBe(0);
		expect(mockFrom).not.toHaveBeenCalled();
	});

	it("inserts a proven template with group metadata", async () => {
		setRandom([0.1, 0, 0.9, 0.9, 0.5]);
		const queueInsert = insertQuery();
		mockFrom.mockReturnValueOnce(queueInsert);

		const inserted = await insertProvenTemplate("workspace-1", "group-1", 3);

		expect(inserted).toBe(1);
		expect(mockFrom).toHaveBeenCalledWith("auto_post_queue");
		expect(queueInsert.insert).toHaveBeenCalledWith(
			expect.objectContaining({
				workspace_id: "workspace-1",
				content: "i'm single. i don't need your money. i can cook",
				status: "pending",
				predicted_viral_score: 85,
				source_type: "template",
				source_id: "proven_template:0",
				content_type: "identity_statement",
				group_id: "group-1",
				provenance_status: "pass",
				provenance_error: null,
				content_fingerprint: expect.any(String),
				publish_fingerprint: expect.any(String),
				normalized_text_hash: expect.any(String),
				media_fingerprint: expect.any(String),
				metadata: expect.objectContaining({
					source_id: "proven_template:0",
					provenance: expect.objectContaining({
						source_type: "template",
						source_id: "proven_template:0",
						content_fingerprint: expect.any(String),
						publish_fingerprint: expect.any(String),
						quality_gate_result: "system_template_pass",
					}),
					quality_gate: expect.objectContaining({
						decision: "pass",
						lane: "system_template",
					}),
				}),
			}),
		);
	});

	it("returns no recycle work when capacity, group accounts, or average views do not qualify", async () => {
		expect(await recycleEvergreenPosts("workspace-1", "group-1", 5, "threads")).toEqual({
			insertCount: 0,
			failedCount: 0,
			errors: [],
		});

		mockFrom.mockReturnValueOnce(selectQuery({ account_ids: [] }));
		expect(await recycleEvergreenPosts("workspace-1", "group-1", 10, "threads")).toEqual({
			insertCount: 0,
			failedCount: 0,
			errors: [],
		});

		mockFrom
			.mockReturnValueOnce(selectQuery({ account_ids: ["acct-1"] }))
			.mockReturnValueOnce(selectQuery([{ views_count: 0 }, { views_count: 0 }, { views_count: 0 }, { views_count: 0 }, { views_count: 0 }]));
		expect(await recycleEvergreenPosts("workspace-1", "group-1", 10, "threads")).toEqual({
			insertCount: 0,
			failedCount: 0,
			errors: [],
		});
	});

	it("recycles eligible evergreen posts and updates recycle tracking", async () => {
		setRandom([0.5]);
		const queueInsert = insertQuery();
		const postUpdate = updateQuery();
		mockFrom
			.mockReturnValueOnce(selectQuery({ account_ids: ["acct-1", "acct-2"] }))
			.mockReturnValueOnce(selectQuery([
				{ views_count: 100 },
				{ views_count: 120 },
				{ views_count: 80 },
				{ views_count: 100 },
				{ views_count: 100 },
			]))
			.mockReturnValueOnce(selectQuery([
				{
					id: "post-1",
					content: "original viral question",
					views_count: 400,
					saves_count: 2,
					recycle_count: 1,
					max_recycles: 5,
					media_urls: ["a.jpg", "b.jpg"],
					media_type: "CAROUSEL_ALBUM",
				},
				{
					id: "post-maxed",
					content: "do not use",
					views_count: 500,
					recycle_count: 5,
					max_recycles: 5,
				},
			]))
			.mockReturnValueOnce(selectQuery([]))
			.mockReturnValueOnce(queueInsert)
			.mockReturnValueOnce(postUpdate);

		const result = await recycleEvergreenPosts("workspace-1", "group-1", 10, "instagram");

		expect(result).toEqual({ insertCount: 1, failedCount: 0, errors: [] });
		expect(queueInsert.insert).toHaveBeenCalledWith(
			expect.objectContaining({
				workspace_id: "workspace-1",
				content: "original viral question",
				status: "pending",
				predicted_viral_score: 40,
				source_type: "recycled",
				source_content: "original viral question",
				media_urls: ["a.jpg"],
				media_type: "IMAGE",
				group_id: "group-1",
			}),
		);
		expect(postUpdate.update).toHaveBeenCalledWith(
			expect.objectContaining({
				recycle_count: 2,
				last_recycled_at: expect.any(String),
			}),
		);
		expect(postUpdate.eq).toHaveBeenCalledWith("id", "post-1");
	});

	it("uses AI rewrites and records spend when recycling is enabled", async () => {
		process.env.AUTOPOSTER_AI_RECYCLE_REWRITES = "1";
		process.env.GEMINI_API_KEY = "gemini-key";
		const queueInsert = insertQuery();
		mockFrom
			.mockReturnValueOnce(selectQuery({ account_ids: ["acct-1"] }))
			.mockReturnValueOnce(selectQuery([
				{ views_count: 100 },
				{ views_count: 100 },
				{ views_count: 100 },
				{ views_count: 100 },
				{ views_count: 100 },
			]))
			.mockReturnValueOnce(selectQuery([
				{
					id: "post-1",
					content: "original viral question",
					views_count: 400,
					recycle_count: 0,
					max_recycles: 5,
				},
			]))
			.mockReturnValueOnce(selectQuery([]))
			.mockReturnValueOnce(queueInsert)
			.mockReturnValueOnce(updateQuery());

		const result = await recycleEvergreenPosts("workspace-1", "group-1", 10, "threads");

		expect(result.insertCount).toBe(1);
		expect(mockGenerateContent).toHaveBeenCalledWith(
			expect.objectContaining({
				model: "gemini-2.0-flash",
				contents: expect.stringContaining("Original: original viral question"),
			}),
		);
		expect(mockTrackAICost).toHaveBeenCalledWith(
			"platform",
			10,
			5,
			"gemini-2.0-flash",
			"evergreen_recycle_queuefill",
			"env_fallback",
		);
		expect(queueInsert.insert).toHaveBeenCalledWith(
			expect.objectContaining({
				content: expect.any(String),
				source_content: "original viral question",
			}),
		);
	});
});
