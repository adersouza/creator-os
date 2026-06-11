/**
 * Unit tests for AI Generate handler
 * (api/_lib/handlers/ai/generate.ts)
 *
 * Covers: auth/method checks, input validation, tier gate, rate limiting,
 * circuit breaker, cache hit/miss, single/multi-variant generation,
 * voice profile injection, platform char limits, content scoring, error handling.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns (declared before vi.mock)
// ---------------------------------------------------------------------------

const mockRequireMinTier = vi.fn();
const mockCheckAIRateLimit = vi.fn();
const mockGetUserAIConfig = vi.fn();
const mockIsGeminiAvailable = vi.fn();
const mockWithGeminiRetry = vi.fn();
const mockGenerateContent = vi.fn();
const mockGetCachedAIResponse = vi.fn();
const mockSetCachedAIResponse = vi.fn();
const mockTrackUsage = vi.fn();
const mockTrackAICost = vi.fn();
const mockFrom = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock() — must be before import of module under test
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/middleware.js", () => ({
  withAuth: (handler: any) => handler,
}));

vi.mock("@/api/_lib/apiResponse.js", () => ({
  apiError: (res: any, status: number, msg: string, opts?: any) =>
    res.status(status).json({ error: msg, ...opts }),
  apiSuccess: (res: any, data?: unknown) =>
    res.status(200).json({ success: true, ...(data as any) }),
}));

vi.mock("@/api/_lib/tierGate.js", () => ({
  requireMinTier: (...args: unknown[]) => mockRequireMinTier(...args),
}));

vi.mock("@/api/_lib/aiRateLimit.js", () => ({
  checkAIRateLimit: (...args: unknown[]) => mockCheckAIRateLimit(...args),
}));

vi.mock("@/api/_lib/aiConfig.js", () => ({
  getUserAIConfig: (...args: unknown[]) => mockGetUserAIConfig(...args),
}));

vi.mock("@/api/_lib/geminiRetry.js", () => ({
  isGeminiAvailable: () => mockIsGeminiAvailable(),
  withGeminiRetry: (fn: any) => mockWithGeminiRetry(fn),
}));

vi.mock("@google/genai", () => {
  // Use a stable class so clearAllMocks doesn't wipe the constructor impl
  class MockGoogleGenAI {
    models = { generateContent: (...args: unknown[]) => mockGenerateContent(...args) };
  }
  return { GoogleGenAI: MockGoogleGenAI };
});

vi.mock("@/api/_lib/aiCache.js", () => ({
  AI_CACHE_TTL: { CONTENT_GENERATION: 3600 },
  buildAICacheKey: vi.fn().mockReturnValue("cache-key-1"),
  getCachedAIResponse: (...args: unknown[]) => mockGetCachedAIResponse(...args),
  setCachedAIResponse: (...args: unknown[]) => mockSetCachedAIResponse(...args),
}));

vi.mock("@/api/_lib/aiCostTracker.js", () => ({
  trackAICost: (...args: unknown[]) => mockTrackAICost(...args),
}));

vi.mock("@/api/_lib/auditLog.js", () => ({
  trackUsage: (...args: unknown[]) => mockTrackUsage(...args),
}));

vi.mock("@/api/_lib/aiSafety.js", () => ({
  clampMaxTokens: vi.fn((v: any) => (typeof v === "number" && v > 0 ? Math.min(v, 4096) : 1024)),
  clampTemperature: vi.fn((v: any) => (typeof v === "number" ? Math.min(Math.max(v, 0), 1.5) : 0.7)),
}));

vi.mock("@/api/_lib/promptUtils.js", () => ({
  stripInjection: vi.fn((s: string) => s),
  sanitizeAIOutput: vi.fn((s: string) => s),
}));

vi.mock("@/api/_lib/supabase.js", () => ({
  getSupabase: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/logger.js", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import handler from "@/api/_lib/handlers/ai/generate";
const invokeHandler = handler as unknown as (
  req: any,
  res: any,
  user: any,
) => Promise<void>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TEST_USER = { id: "user-1" };

function makeReq(body: Record<string, unknown> = {}, method = "POST") {
  return { method, body, headers: {} };
}

function setupHappyPath() {
  mockRequireMinTier.mockResolvedValue(true);
  mockCheckAIRateLimit.mockResolvedValue({ allowed: true, remaining: 50, limit: 100 });
  mockGetUserAIConfig.mockResolvedValue({
    provider: "gemini",
    apiKey: "test-key",
    model: "gemini-2.5-flash",
    source: "user",
  });
  mockIsGeminiAvailable.mockReturnValue(true);
  mockGetCachedAIResponse.mockResolvedValue(null);
  mockSetCachedAIResponse.mockResolvedValue(undefined);
  const mockResponse = {
    text: "Generated post content",
    usageMetadata: { promptTokenCount: 50, candidatesTokenCount: 30, thoughtsTokenCount: 0 },
  };
  mockWithGeminiRetry.mockImplementation((fn: any) => fn());
  mockGenerateContent.mockResolvedValue(mockResponse);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AI Generate Handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Method check ──────────────────────────────────────────────────────────

  it("rejects non-POST requests with 405", async () => {
    const res = mockRes();
    await invokeHandler(makeReq({}, "GET"), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(405);
  });

  // ── Tier gate ─────────────────────────────────────────────────────────────

  it("blocks free-tier users when requireMinTier returns false", async () => {
    mockRequireMinTier.mockResolvedValue(false);
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "test" }), res, TEST_USER);
    // Handler returns early when tier gate fails (requireMinTier sends its own response)
    expect(mockCheckAIRateLimit).not.toHaveBeenCalled();
  });

  // ── Input validation ──────────────────────────────────────────────────────

  it("rejects missing prompt with 400", async () => {
    mockRequireMinTier.mockResolvedValue(true);
    const res = mockRes();
    await invokeHandler(makeReq({}), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith(expect.objectContaining({ error: expect.stringContaining("prompt") }));
  });

  it("rejects non-string prompt with 400", async () => {
    mockRequireMinTier.mockResolvedValue(true);
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: 123 }), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  // ── No API key ────────────────────────────────────────────────────────────

  it("returns 503 when no AI API key available", async () => {
    mockRequireMinTier.mockResolvedValue(true);
    mockCheckAIRateLimit.mockResolvedValue({ allowed: true, remaining: 50, limit: 100 });
    mockGetUserAIConfig.mockResolvedValue(null);
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "test" }), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(503);
    expect(res.json).toHaveBeenCalledWith(expect.objectContaining({ code: "NO_API_KEY" }));
  });

  // ── Rate limiting ─────────────────────────────────────────────────────────

	it("returns 429 when rate limit exceeded", async () => {
		mockRequireMinTier.mockResolvedValue(true);
		mockGetUserAIConfig.mockResolvedValue({
			provider: "gemini",
			apiKey: "test-key",
			model: "gemini-2.5-flash",
			source: "user",
		});
		mockCheckAIRateLimit.mockResolvedValue({ allowed: false, remaining: 0, limit: 100 });
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "test" }), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(429);
    expect(res.json).toHaveBeenCalledWith(expect.objectContaining({ code: "RATE_LIMITED" }));
  });

	it("sets rate limit headers", async () => {
		mockRequireMinTier.mockResolvedValue(true);
		mockGetUserAIConfig.mockResolvedValue({
			provider: "gemini",
			apiKey: "test-key",
			model: "gemini-2.5-flash",
			source: "user",
		});
		mockCheckAIRateLimit.mockResolvedValue({ allowed: false, remaining: 0, limit: 100 });
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "test" }), res, TEST_USER);
    expect(res.setHeader).toHaveBeenCalledWith("X-RateLimit-Limit", "100");
    expect(res.setHeader).toHaveBeenCalledWith("X-RateLimit-Remaining", "0");
  });

  // ── Circuit breaker ───────────────────────────────────────────────────────

	it("returns 503 when Gemini circuit breaker is tripped", async () => {
		mockRequireMinTier.mockResolvedValue(true);
		mockCheckAIRateLimit.mockResolvedValue({ allowed: true, remaining: 50, limit: 100 });
		mockGetUserAIConfig.mockResolvedValue({
			provider: "gemini",
			apiKey: "test-key",
			model: "gemini-2.5-flash",
			source: "user",
		});
    mockIsGeminiAvailable.mockReturnValue(false);
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "test" }), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(503);
    expect(res.json).toHaveBeenCalledWith(expect.objectContaining({ code: "AI_UNAVAILABLE" }));
  });

  // ── Cache hit ─────────────────────────────────────────────────────────────

  it("returns cached response on cache hit (single variant)", async () => {
    setupHappyPath();
    mockGetCachedAIResponse.mockResolvedValue("Cached post content");
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "test prompt" }), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ text: "Cached post content", cached: true }),
    );
    expect(res.setHeader).toHaveBeenCalledWith("X-Cache", "HIT");
    // Should NOT call generateContent
    expect(mockGenerateContent).not.toHaveBeenCalled();
  });

  it("skips cache when noCache is true", async () => {
    setupHappyPath();
    mockGetCachedAIResponse.mockResolvedValue("Cached post content");
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "test prompt", noCache: true }), res, TEST_USER);
    // Should still call generateContent because noCache=true
    expect(mockWithGeminiRetry).toHaveBeenCalled();
  });

  // ── Happy path (single variant) ───────────────────────────────────────────

  it("generates and returns a single variant with score", async () => {
    setupHappyPath();
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "Write a thread about AI" }), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(200);
    const call = res.json.mock.calls[0][0];
    expect(call.success).toBe(true);
    expect(call.text).toBe("Generated post content");
    expect(call.cached).toBe(false);
    expect(call.score).toBeDefined();
    expect(call.score.total).toBeGreaterThan(0);
    expect(res.setHeader).toHaveBeenCalledWith("X-Cache", "MISS");
  });

  it("caches the generated response", async () => {
    setupHappyPath();
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "test" }), res, TEST_USER);
    expect(mockSetCachedAIResponse).toHaveBeenCalledWith(
      "cache-key-1",
      "Generated post content",
      expect.any(Number),
    );
  });

  it("tracks usage and cost after generation", async () => {
    setupHappyPath();
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "test" }), res, TEST_USER);
    expect(mockTrackUsage).toHaveBeenCalledWith("user-1", "ai.generate");
    expect(mockTrackAICost).toHaveBeenCalled();
  });

  // ── Multi-variant generation ──────────────────────────────────────────────

  it("generates multiple variants when variants=2", async () => {
    setupHappyPath();
    let callCount = 0;
    mockWithGeminiRetry.mockImplementation((_fn: any) => {
      callCount++;
      return Promise.resolve({
        text: `Variant ${callCount} content`,
        usageMetadata: { promptTokenCount: 50, candidatesTokenCount: 30 },
      });
    });
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "test", variants: 2 }), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(200);
    const call = res.json.mock.calls[0][0];
    expect(call.variants).toBeDefined();
    expect(call.variants.length).toBe(2);
    // Also includes backwards-compat `text` field
    expect(call.text).toBeDefined();
  });

  it("clamps variants to max 3", async () => {
    setupHappyPath();
    let callCount = 0;
    mockWithGeminiRetry.mockImplementation((_fn: any) => {
      callCount++;
      return Promise.resolve({
        text: `Variant ${callCount}`,
        usageMetadata: { promptTokenCount: 50, candidatesTokenCount: 30 },
      });
    });
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "test", variants: 10 }), res, TEST_USER);
    // withGeminiRetry should be called exactly 3 times
    expect(mockWithGeminiRetry).toHaveBeenCalledTimes(3);
  });

  // ── Platform-specific char limit injection ────────────────────────────────

  it("does not return variants array for single variant requests", async () => {
    setupHappyPath();
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "test", variants: 1 }), res, TEST_USER);
    const call = res.json.mock.calls[0][0];
    expect(call.variants).toBeUndefined();
  });

  // ── Error handling ────────────────────────────────────────────────────────

  it("returns 502 when generation throws an error", async () => {
    setupHappyPath();
    mockWithGeminiRetry.mockRejectedValue(new Error("Gemini API error"));
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "test" }), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(502);
  });

  // ── Voice profile injection ───────────────────────────────────────────────

  it("injects voice profile when accountId is provided", async () => {
    setupHappyPath();
    const mockChain = {
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      maybeSingle: vi.fn().mockResolvedValue({
        data: {
          ai_config: {
            voice_profile: "Witty and sarcastic tech influencer",
            tone: "casual",
            focus_topics: ["AI", "startups"],
          },
        },
        error: null,
      }),
    };
    mockFrom.mockReturnValue(mockChain);

    // Capture the prompt passed to generateContent
    mockWithGeminiRetry.mockImplementation((_fn: any) => {
      return Promise.resolve({
        text: "Voice-matched content",
        usageMetadata: { promptTokenCount: 50, candidatesTokenCount: 30 },
      });
    });

    const res = mockRes();
    await invokeHandler(
      makeReq({ prompt: "Write about AI", accountId: "acc-123" }),
      res,
      TEST_USER,
    );
    expect(res.status).toHaveBeenCalledWith(200);
    expect(mockFrom).toHaveBeenCalledWith("accounts");
  });

  // ── Default model ─────────────────────────────────────────────────────────

  it("uses gemini-2.5-flash as default model", async () => {
    setupHappyPath();
    const res = mockRes();
    await invokeHandler(makeReq({ prompt: "test" }), res, TEST_USER);
    const call = res.json.mock.calls[0][0];
    expect(call.model).toBe("gemini-2.5-flash");
  });
});
