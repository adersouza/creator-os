import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

/**
 * Unit tests for POST /api/competitors/analyze — "Steal Their Strategy"
 *
 * Tests the AI-powered competitor analysis handler that generates
 * adapted content ideas based on a competitor's top posts.
 */

// ---------------------------------------------------------------------------
// Mocks — set up before module import
// ---------------------------------------------------------------------------

const mockGetAuthUserOrError = vi.fn();

vi.mock("../../api/_lib/apiResponse", () => ({
	apiError: (res: any, status: number, message: string, opts?: any) =>
		res.status(status).json({ success: false, error: message, ...opts }),
	apiSuccess: (res: any, data: Record<string, unknown>) =>
		res.status(200).json({ success: true, ...data }),
	getAuthUserOrError: (...args: unknown[]) => mockGetAuthUserOrError(...args),
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: {
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

const mockCheckRateLimit = vi.fn();
vi.mock("../../api/_lib/rateLimiter", () => ({
	checkRateLimit: (...args: unknown[]) => mockCheckRateLimit(...args),
}));

const mockGetSupabaseFrom = vi.fn();
vi.mock("../../api/_lib/supabase", () => ({
	getSupabase: () => ({
		from: (...args: unknown[]) => mockGetSupabaseFrom(...args),
	}),
}));

const mockVerifyAccountOwnership = vi.fn();
const mockVerifyCompetitorOwnership = vi.fn();
vi.mock("../../api/_lib/handlers/helpers/verifyOwnership", () => ({
	verifyAccountOwnership: (...args: unknown[]) =>
		mockVerifyAccountOwnership(...args),
	verifyCompetitorOwnership: (...args: unknown[]) =>
		mockVerifyCompetitorOwnership(...args),
}));

const mockGetUserAIConfig = vi.fn();
vi.mock("../../api/_lib/aiConfig", () => ({
	getUserAIConfig: (...args: unknown[]) => mockGetUserAIConfig(...args),
}));

vi.mock("../../api/_lib/promptUtils", () => ({
	escapeForPrompt: (s: string) => s,
	sanitizeAIOutput: (s: string) => s,
}));

vi.mock("../../api/_lib/sanitizeForAI", () => ({
	describeValue: (v: unknown) => String(v),
}));

// withAuth extracts user and passes to handler
vi.mock("../../api/_lib/middleware", () => ({
	withAuth: (handler: any) => {
		return async (req: any, res: any) => {
			const user = await mockGetAuthUserOrError(req, res);
			if (!user) return;
			return handler(req, res, user);
		};
	},
}));

const mockGenerateWithProvider = vi.fn();
vi.mock("../../api/_lib/handlers/auto-post/aiProviders", () => ({
	generateWithProvider: (...args: unknown[]) =>
		mockGenerateWithProvider(...args),
}));

// Import module under test AFTER mocks
const { default: analyzeHandler } = await import(
	"../../api/_lib/handlers/competitors-sub/analyze"
);
const invokeAnalyzeHandler = analyzeHandler as unknown as (req: any, res: any) => Promise<void>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeReq(
	overrides: { method?: string; body?: Record<string, unknown> } = {},
) {
	return {
		method: overrides.method || "POST",
		body: overrides.body || {},
		headers: { authorization: "Bearer test-token" },
	} as any;
}

const COMPETITOR_INFO = {
	id: "comp-1",
	username: "competitor1",
	display_name: "Competitor One",
	follower_count: 10000,
	bio: "Competitor bio",
	platform: "threads",
};

const COMPETITOR_POSTS = [
	{
		content: "Great post about growth",
		media_type: "TEXT",
		like_count: 100,
		reply_count: 20,
		repost_count: 10,
		view_count: 5000,
		engagement_score: 220,
		published_at: "2026-04-10T10:00:00Z",
	},
];

const AI_RESPONSE = {
	ideas: [
		{
			topic: "Growth strategies",
			format: "Text Post",
			caption: "Here's how to grow your audience...",
			bestTimeToPost: "Tuesday 9am",
			reasoning: "Adapts competitor's educational format",
		},
	],
	competitorInsight:
		"This competitor excels at educational content with strong hooks.",
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("competitor analyze handler (steal their strategy)", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockGetAuthUserOrError.mockResolvedValue({ id: "user-1" });
		mockCheckRateLimit.mockResolvedValue({ allowed: true });
	});

	it("returns 405 for non-POST requests", async () => {
		const res = mockRes();
		await invokeAnalyzeHandler(makeReq({ method: "GET" }), res);
		expect(res.status).toHaveBeenCalledWith(405);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "Method not allowed" }),
		);
	});

	it("returns 401 when user is not authenticated", async () => {
		mockGetAuthUserOrError.mockResolvedValue(null);
		const res = mockRes();
		await invokeAnalyzeHandler(
			makeReq({
				body: { competitorId: "comp-1", accountId: "acc-1" },
			}),
			res,
		);
		expect(mockGetAuthUserOrError).toHaveBeenCalled();
	});

	it("returns 400 when competitorId is missing", async () => {
		const res = mockRes();
		await invokeAnalyzeHandler(
			makeReq({ body: { accountId: "acc-1" } }),
			res,
		);
		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "competitorId is required" }),
		);
	});

	it("returns 400 when accountId is missing", async () => {
		const res = mockRes();
		await invokeAnalyzeHandler(
			makeReq({ body: { competitorId: "comp-1" } }),
			res,
		);
		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ error: "accountId is required" }),
		);
	});

	it("returns 400 when competitorId is not a string", async () => {
		const res = mockRes();
		await invokeAnalyzeHandler(
			makeReq({ body: { competitorId: 123, accountId: "acc-1" } }),
			res,
		);
		expect(res.status).toHaveBeenCalledWith(400);
	});

	it("returns 429 when rate limited", async () => {
		mockCheckRateLimit.mockResolvedValue({ allowed: false });
		const res = mockRes();
		await invokeAnalyzeHandler(
			makeReq({
				body: { competitorId: "comp-1", accountId: "acc-1" },
			}),
			res,
		);
		expect(res.status).toHaveBeenCalledWith(429);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				error: expect.stringContaining("Rate limit"),
			}),
		);
	});

	it("returns early when account ownership verification fails", async () => {
		mockVerifyAccountOwnership.mockResolvedValue(null);
		const res = mockRes();
		await invokeAnalyzeHandler(
			makeReq({
				body: { competitorId: "comp-1", accountId: "acc-1" },
			}),
			res,
		);
		expect(mockVerifyAccountOwnership).toHaveBeenCalledWith(
			res,
			"acc-1",
			"user-1",
		);
		expect(mockGetUserAIConfig).not.toHaveBeenCalled();
	});

	it("returns 503 when AI key is unavailable", async () => {
		mockVerifyAccountOwnership.mockResolvedValue({ id: "acc-1" });
		mockGetUserAIConfig.mockResolvedValue(null);

		const res = mockRes();
		await invokeAnalyzeHandler(
			makeReq({
				body: { competitorId: "comp-1", accountId: "acc-1" },
			}),
			res,
		);
		expect(res.status).toHaveBeenCalledWith(503);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				error: expect.stringContaining("AI features temporarily unavailable"),
			}),
		);
	});

	it("returns early when competitor ownership verification fails", async () => {
		mockVerifyAccountOwnership.mockResolvedValue({ id: "acc-1" });
		mockGetUserAIConfig.mockResolvedValue({
			provider: "gemini",
			apiKey: "test-key",
			source: "user",
			model: "gemini-2.5-flash",
		});
		mockVerifyCompetitorOwnership.mockResolvedValue(null);

		const res = mockRes();
		await invokeAnalyzeHandler(
			makeReq({
				body: { competitorId: "comp-1", accountId: "acc-1" },
			}),
			res,
		);
		expect(mockVerifyCompetitorOwnership).toHaveBeenCalled();
	});

	it("returns 400 when competitor has no posts", async () => {
		mockVerifyAccountOwnership.mockResolvedValue({ id: "acc-1" });
		mockGetUserAIConfig.mockResolvedValue({
			provider: "gemini",
			apiKey: "test-key",
			source: "user",
			model: "gemini-2.5-flash",
		});
		mockVerifyCompetitorOwnership.mockResolvedValue(COMPETITOR_INFO);

		mockGetSupabaseFrom.mockImplementation((table: string) => {
			if (table === "competitor_top_posts") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							order: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [] }),
							}),
						}),
					}),
				};
			}
			return {
				select: vi.fn().mockReturnValue({
					eq: vi.fn().mockReturnValue({
						order: vi.fn().mockReturnValue({
							limit: vi.fn().mockResolvedValue({ data: [] }),
						}),
					}),
				}),
			};
		});

		const res = mockRes();
		await invokeAnalyzeHandler(
			makeReq({
				body: { competitorId: "comp-1", accountId: "acc-1" },
			}),
			res,
		);
		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				error: expect.stringContaining("No competitor posts"),
			}),
		);
	});

	it("returns AI-generated ideas on success", async () => {
		mockVerifyAccountOwnership.mockResolvedValue({ id: "acc-1" });
		mockGetUserAIConfig.mockResolvedValue({
			provider: "gemini",
			apiKey: "test-key",
			source: "user",
			model: "gemini-2.5-flash",
		});
		mockVerifyCompetitorOwnership.mockResolvedValue(COMPETITOR_INFO);

		mockGetSupabaseFrom.mockImplementation((table: string) => {
			if (table === "competitor_top_posts") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							order: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({
									data: COMPETITOR_POSTS,
								}),
							}),
						}),
					}),
				};
			}
			if (table === "posts") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							order: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [] }),
							}),
						}),
					}),
				};
			}
			if (table === "account_groups") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							not: vi.fn().mockResolvedValue({ data: [] }),
						}),
					}),
				};
			}
			return {};
		});

		mockGenerateWithProvider.mockResolvedValue(JSON.stringify(AI_RESPONSE));

		const res = mockRes();
		await invokeAnalyzeHandler(
			makeReq({
				body: { competitorId: "comp-1", accountId: "acc-1" },
			}),
			res,
		);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				success: true,
				ideas: expect.arrayContaining([
					expect.objectContaining({
						topic: "Growth strategies",
						format: "Text Post",
					}),
				]),
				competitorInsight: expect.any(String),
				competitor: expect.objectContaining({
					username: "competitor1",
					displayName: "Competitor One",
				}),
			}),
		);
	});

	it("handles malformed AI JSON by extracting JSON from text", async () => {
		mockVerifyAccountOwnership.mockResolvedValue({ id: "acc-1" });
		mockGetUserAIConfig.mockResolvedValue({
			provider: "gemini",
			apiKey: "test-key",
			source: "user",
			model: "gemini-2.5-flash",
		});
		mockVerifyCompetitorOwnership.mockResolvedValue(COMPETITOR_INFO);

		mockGetSupabaseFrom.mockImplementation((table: string) => {
			if (table === "competitor_top_posts") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							order: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({
									data: COMPETITOR_POSTS,
								}),
							}),
						}),
					}),
				};
			}
			if (table === "posts") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							order: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [] }),
							}),
						}),
					}),
				};
			}
			if (table === "account_groups") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							not: vi.fn().mockResolvedValue({ data: [] }),
						}),
					}),
				};
			}
			return {};
		});

		// Return JSON embedded in extra text (like markdown code blocks)
		mockGenerateWithProvider.mockResolvedValue(
			`Here is the analysis:\n\`\`\`json\n${JSON.stringify(AI_RESPONSE)}\n\`\`\``,
		);

		const res = mockRes();
		await invokeAnalyzeHandler(
			makeReq({
				body: { competitorId: "comp-1", accountId: "acc-1" },
			}),
			res,
		);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ideas: expect.any(Array) }),
		);
	});

	it("returns 500 when AI generation fails completely", async () => {
		mockVerifyAccountOwnership.mockResolvedValue({ id: "acc-1" });
		mockGetUserAIConfig.mockResolvedValue({
			provider: "gemini",
			apiKey: "test-key",
			source: "user",
			model: "gemini-2.5-flash",
		});
		mockVerifyCompetitorOwnership.mockResolvedValue(COMPETITOR_INFO);

		mockGetSupabaseFrom.mockImplementation((table: string) => {
			if (table === "competitor_top_posts") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							order: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({
									data: COMPETITOR_POSTS,
								}),
							}),
						}),
					}),
				};
			}
			if (table === "posts") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							order: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [] }),
							}),
						}),
					}),
				};
			}
			if (table === "account_groups") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							not: vi.fn().mockResolvedValue({ data: [] }),
						}),
					}),
				};
			}
			return {};
		});

		mockGenerateWithProvider.mockRejectedValue(new Error("API key invalid"));

		const res = mockRes();
		await invokeAnalyzeHandler(
			makeReq({
				body: { competitorId: "comp-1", accountId: "acc-1" },
			}),
			res,
		);

		expect(res.status).toHaveBeenCalledWith(500);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				error: "AI analysis failed. Please try again.",
			}),
		);
	});

	it("includes voice profile in prompt when available", async () => {
		mockVerifyAccountOwnership.mockResolvedValue({ id: "acc-1" });
		mockGetUserAIConfig.mockResolvedValue({
			provider: "gemini",
			apiKey: "test-key",
			source: "user",
			model: "gemini-2.5-flash",
		});
		mockVerifyCompetitorOwnership.mockResolvedValue(COMPETITOR_INFO);

		mockGetSupabaseFrom.mockImplementation((table: string) => {
			if (table === "competitor_top_posts") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							order: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({
									data: COMPETITOR_POSTS,
								}),
							}),
						}),
					}),
				};
			}
			if (table === "posts") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							order: vi.fn().mockReturnValue({
								limit: vi.fn().mockResolvedValue({ data: [] }),
							}),
						}),
					}),
				};
			}
			if (table === "account_groups") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							not: vi.fn().mockResolvedValue({
								data: [
									{
										voice_profile: "Casual and witty",
										account_ids: ["acc-1"],
									},
								],
							}),
						}),
					}),
				};
			}
			return {};
		});

		mockGenerateWithProvider.mockResolvedValue(JSON.stringify(AI_RESPONSE));

		const res = mockRes();
		await invokeAnalyzeHandler(
			makeReq({
				body: { competitorId: "comp-1", accountId: "acc-1" },
			}),
			res,
		);

		// Verify the prompt included voice profile
		expect(mockGenerateWithProvider).toHaveBeenCalled();
		const callArgs = mockGenerateWithProvider.mock.calls[0][0];
		expect(callArgs).toContain("Casual and witty");
	});

	it("passes rate limit check with correct key pattern", async () => {
		mockCheckRateLimit.mockResolvedValue({ allowed: true });
		mockVerifyAccountOwnership.mockResolvedValue({ id: "acc-1" });
		mockGetUserAIConfig.mockResolvedValue({
			provider: "gemini",
			apiKey: "test-key",
			source: "user",
			model: "gemini-2.5-flash",
		});
		mockVerifyCompetitorOwnership.mockResolvedValue(COMPETITOR_INFO);

		mockGetSupabaseFrom.mockReturnValue({
			select: vi.fn().mockReturnValue({
				eq: vi.fn().mockReturnValue({
					order: vi.fn().mockReturnValue({
						limit: vi.fn().mockResolvedValue({ data: COMPETITOR_POSTS }),
					}),
					not: vi.fn().mockResolvedValue({ data: [] }),
				}),
			}),
		});

		mockGenerateWithProvider.mockResolvedValue(JSON.stringify(AI_RESPONSE));

		const res = mockRes();
		await invokeAnalyzeHandler(
			makeReq({
				body: { competitorId: "comp-1", accountId: "acc-1" },
			}),
			res,
		);

		expect(mockCheckRateLimit).toHaveBeenCalledWith(
			expect.objectContaining({
				key: "steal-strategy:user-1",
				limit: 5,
				windowSeconds: 3600,
			}),
		);
	});
});
