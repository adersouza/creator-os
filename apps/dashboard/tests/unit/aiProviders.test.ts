import { beforeEach, describe, expect, it, vi } from "vitest";

const mockCheckDailySpendLimit = vi.fn();
const mockTrackAICost = vi.fn();
const mockActionLogInsert = vi.fn();
const mockEvalSnapshotInsert = vi.fn();
const mockEvalSnapshotSelect = vi.fn();
const mockEvalSnapshotMaybeSingle = vi.fn();

vi.mock("../../api/_lib/logger.js", () => ({
	logger: {
		debug: vi.fn(),
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
	},
}));

vi.mock("../../api/_lib/aiCostTracker.js", () => ({
	checkDailySpendLimit: () => mockCheckDailySpendLimit(),
	estimateAICostUsd: () => 0.000123,
	trackAICost: (...args: unknown[]) => mockTrackAICost(...args),
}));

vi.mock("../../api/_lib/supabase.js", () => ({
	getSupabaseAny: () => ({
		from: vi.fn((table: string) => {
			if (table === "ai_eval_snapshots") {
				return {
					insert: mockEvalSnapshotInsert.mockReturnValue({
						select: mockEvalSnapshotSelect.mockReturnValue({
							maybeSingle: mockEvalSnapshotMaybeSingle,
						}),
					}),
				};
			}
			return { insert: mockActionLogInsert };
		}),
	}),
}));

import {
	adjustContentForPlatform,
	generateWithProvider,
} from "../../api/_lib/handlers/auto-post/aiProviders";

function response(body: unknown, ok = true, status = ok ? 200 : 500): Response {
	return {
		ok,
		status,
		headers: new Headers({ "content-type": "application/json" }),
		json: vi.fn().mockResolvedValue(body),
		text: vi.fn().mockResolvedValue(typeof body === "string" ? body : JSON.stringify(body)),
	} as unknown as Response;
}

beforeEach(() => {
	vi.clearAllMocks();
	delete process.env.XAI_API_KEY;
	delete process.env.GEMINI_API_KEY;
	mockCheckDailySpendLimit.mockResolvedValue({ allowed: true, spentUsd: 0, limitUsd: 10 });
	mockTrackAICost.mockResolvedValue(undefined);
	mockActionLogInsert.mockResolvedValue({ data: null, error: null });
	mockEvalSnapshotMaybeSingle.mockResolvedValue({ data: { id: "eval-1" }, error: null });
	global.fetch = vi.fn() as any;
});

describe("aiProviders", () => {
	it("calls Gemini with structured output, system instruction, and cost tracking", async () => {
		(global.fetch as any).mockResolvedValueOnce(response({
			candidates: [{
				content: {
					parts: [
						{ thought: true, text: "hidden thinking" },
						{ text: '[{"content":"hello"}]' },
					],
				},
			}],
			usageMetadata: {
				promptTokenCount: 12,
				candidatesTokenCount: 6,
				thoughtsTokenCount: 2,
			},
		}));

		const result = await generateWithProvider("make posts", {
			provider: "gemini",
			apiKey: "gemini-key",
			ideaCount: 3,
			systemInstruction: "write in voice",
			useStructuredOutput: true,
			actionLog: {
				userId: "user-1",
				accountId: "acct-1",
				surface: "autopilot",
				actionType: "generate",
				metadata: { groupId: "group-1" },
			},
		});

		expect(result).toBe('[{"content":"hello"}]');
		expect(global.fetch).toHaveBeenCalledWith(
			"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=gemini-key",
			expect.objectContaining({ method: "POST" }),
		);
		const body = JSON.parse((global.fetch as any).mock.calls[0][1].body);
		expect(body.systemInstruction.parts[0].text).toBe("write in voice");
		expect(body.generationConfig.responseMimeType).toBe("application/json");
		expect(mockTrackAICost).toHaveBeenCalledWith(
			"user-1",
			12,
			6,
			"gemini-2.5-flash",
			"generate",
			undefined,
			2,
		);
		expect(mockActionLogInsert).toHaveBeenCalledWith(
			expect.objectContaining({
				user_id: "user-1",
				account_id: "acct-1",
				surface: "autopilot",
				action_type: "generate",
				output_text: '[{"content":"hello"}]',
				provider: "gemini",
				tokens_in: 12,
				tokens_out: 6,
				cost_usd: 0.000123,
			}),
		);
		expect(mockEvalSnapshotInsert).toHaveBeenCalledWith(
			expect.objectContaining({
				user_id: "user-1",
				account_id: "acct-1",
				group_id: "group-1",
				suite_name: "live:autopilot",
				case_id: "generate",
				category: "autopilot",
				provider: "gemini",
				model: "gemini-2.5-flash",
				passed: true,
				candidate_outputs: [{ text: '[{"content":"hello"}]' }],
				selected_output: { text: '[{"content":"hello"}]' },
			}),
		);
		expect(mockEvalSnapshotSelect).toHaveBeenCalledWith("id");
	});

	it("falls back from Gemini to xAI when the primary provider fails", async () => {
		process.env.XAI_API_KEY = "xai-env-key";
		(global.fetch as any)
			.mockResolvedValueOnce(response({ error: "gemini unavailable" }, false, 500))
			.mockResolvedValueOnce(response({
				choices: [{ message: { content: "xai fallback copy" } }],
			}));

		const result = await generateWithProvider("prompt", {
			provider: "gemini",
			apiKey: "bad-gemini",
			ideaCount: 2,
		});

		expect(result).toBe("xai fallback copy");
		expect((global.fetch as any).mock.calls[1][0]).toBe("https://api.x.ai/v1/chat/completions");
		expect(JSON.parse((global.fetch as any).mock.calls[1][1].body)).toMatchObject({
			model: "grok-4-1-fast",
			store: false,
			messages: [
				expect.objectContaining({ role: "system" }),
				{ role: "user", content: "prompt" },
			],
		});
	});

	it("routes xAI, OpenAI, and Anthropic providers to their expected endpoints", async () => {
		(global.fetch as any)
			.mockResolvedValueOnce(response({ choices: [{ message: { content: "xai copy " } }] }))
			.mockResolvedValueOnce(response({ choices: [{ message: { content: "openai copy " } }] }))
			.mockResolvedValueOnce(response({ content: [{ text: "anthropic copy " }] }));

		await expect(generateWithProvider("x", {
			provider: "xai",
			apiKey: "xai-key",
			ideaCount: 1,
			baseUrl: "https://x.example/",
			model: "grok-test",
		})).resolves.toBe("xai copy");

		await expect(generateWithProvider("o", {
			provider: "openai",
			apiKey: "openai-key",
			ideaCount: 1,
		})).resolves.toBe("openai copy");

		await expect(generateWithProvider("a", {
			provider: "anthropic",
			apiKey: "anthropic-key",
			ideaCount: 1,
			systemInstruction: "cached system",
		})).resolves.toBe("anthropic copy");

		expect((global.fetch as any).mock.calls.map((call: any[]) => call[0])).toEqual([
			"https://x.example/chat/completions",
			"https://api.openai.com/v1/chat/completions",
			"https://api.anthropic.com/v1/messages",
		]);
		const anthropicBody = JSON.parse((global.fetch as any).mock.calls[2][1].body);
		expect(anthropicBody.system[0]).toMatchObject({
			type: "text",
			text: "cached system",
			cache_control: { type: "ephemeral" },
		});
	});

	it("falls back from OpenAI to Gemini when xAI is unavailable", async () => {
		process.env.GEMINI_API_KEY = "gemini-env-key";
		(global.fetch as any)
			.mockResolvedValueOnce(response({ error: "openai down" }, false, 503))
			.mockResolvedValueOnce(response({
				candidates: [{ content: { parts: [{ text: "gemini fallback copy" }] } }],
			}));

		const result = await generateWithProvider("prompt", {
			provider: "openai",
			apiKey: "openai-key",
			ideaCount: 1,
		});

		expect(result).toBe("gemini fallback copy");
		expect((global.fetch as any).mock.calls[1][0]).toContain(
			"generativelanguage.googleapis.com",
		);
	});

	it("returns null when Gemini spend limit blocks generation and no fallback exists", async () => {
		mockCheckDailySpendLimit.mockResolvedValueOnce({
			allowed: false,
			spentUsd: 10.5,
			limitUsd: 10,
		});

		const result = await generateWithProvider("prompt", {
			provider: "gemini",
			apiKey: "gemini-key",
			ideaCount: 1,
		});

		expect(result).toBeNull();
		expect(global.fetch).not.toHaveBeenCalled();
	});

	it("normalizes platform copy without hashtags on Threads", () => {
		expect(adjustContentForPlatform("  hello   #tag world  ", "threads" as any)).toBe(
			"hello world",
		);
		expect(adjustContentForPlatform("  keep #tags on instagram  ", "instagram" as any)).toBe(
			"keep #tags on instagram",
		);
	});
});
