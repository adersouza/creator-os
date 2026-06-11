/**
 * Unit tests for AI Copilot handler
 * (api/_lib/handlers/ai/copilot.ts)
 *
 * Covers: method check, input validation, tier gate, rate limiting,
 * no API key, intent detection, data context fetching, cache hit/miss,
 * memory integration, model selection, error handling.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockRequireMinTier = vi.fn();
const mockCheckAIRateLimit = vi.fn();
const mockGetUserAIConfig = vi.fn();
const mockFrom = vi.fn();
const mockGenerateContent = vi.fn();
const mockGenerateWithProvider = vi.fn();
const mockGetCachedAIResponse = vi.fn();
const mockSetCachedAIResponse = vi.fn();
const mockTrackAICost = vi.fn();
const mockLoadMemory = vi.fn();
const mockStoreMemory = vi.fn();
const mockExtractPreferences = vi.fn();
const mockDetectPreferenceDrift = vi.fn();
const mockGetMemoryContext = vi.fn();
const mockRedisGet = vi.fn();
const mockRedisSet = vi.fn();
const mockRecordDirectAIEvalSnapshot = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock()
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

vi.mock("@google/genai", () => {
  class MockGoogleGenAI {
    models = { generateContent: (...args: unknown[]) => mockGenerateContent(...args) };
  }
  return { GoogleGenAI: MockGoogleGenAI };
});

vi.mock("@/api/_lib/aiCache.js", () => ({
  AI_CACHE_TTL: { CONTENT_GENERATION: 3600 },
  buildAICacheKey: vi.fn().mockReturnValue("copilot-cache-key"),
  getCachedAIResponse: (...args: unknown[]) => mockGetCachedAIResponse(...args),
  setCachedAIResponse: (...args: unknown[]) => mockSetCachedAIResponse(...args),
}));

vi.mock("@/api/_lib/aiCostTracker.js", () => ({
  trackAICost: (...args: unknown[]) => mockTrackAICost(...args),
}));

vi.mock("@/api/_lib/aiEvalSnapshots.js", () => ({
  recordDirectAIEvalSnapshot: (...args: unknown[]) =>
    mockRecordDirectAIEvalSnapshot(...args),
}));

vi.mock("@/api/_lib/handlers/auto-post/aiProviders.js", () => ({
  generateWithProvider: (...args: unknown[]) => mockGenerateWithProvider(...args),
}));

vi.mock("@/api/_lib/supabase.js", () => ({
  getSupabase: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/logger.js", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/api/_lib/promptUtils.js", () => ({
  escapeForPrompt: vi.fn((s: string) => s),
  sanitizeAIOutput: vi.fn((s: string) => s),
}));

vi.mock("@/api/_lib/sanitizeForAI.js", () => ({
  describeAnalyticsTrend: vi.fn().mockReturnValue("steady"),
  describeEngagementRate: vi.fn().mockReturnValue("moderate"),
  describeValue: vi.fn((v: number) => String(v)),
  sanitizeMetrics: vi.fn().mockReturnValue("views: moderate, likes: moderate"),
}));

vi.mock("@/api/_lib/copilotMemory.js", () => ({
  loadMemory: (...args: unknown[]) => mockLoadMemory(...args),
  storeMemory: (...args: unknown[]) => mockStoreMemory(...args),
  extractPreferences: (...args: unknown[]) => mockExtractPreferences(...args),
  detectPreferenceDrift: (...args: unknown[]) => mockDetectPreferenceDrift(...args),
}));

vi.mock("@/api/_lib/creatorMemory.js", () => ({
  getMemoryContext: (...args: unknown[]) => mockGetMemoryContext(...args),
}));

vi.mock("@/api/_lib/redis.js", () => ({
  getRedis: () => ({
    get: (...args: unknown[]) => mockRedisGet(...args),
    set: (...args: unknown[]) => mockRedisSet(...args),
  }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import handler from "@/api/_lib/handlers/ai/copilot";
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

/** Set up all mocks for a successful copilot call */
function setupHappyPath() {
  mockRequireMinTier.mockResolvedValue(true);
  mockCheckAIRateLimit.mockResolvedValue({ allowed: true, remaining: 50, limit: 100 });
  mockGetUserAIConfig.mockResolvedValue({
    provider: "gemini",
    apiKey: "test-key",
    model: "gemini-2.0-flash",
    source: "user",
  });
  mockGetCachedAIResponse.mockResolvedValue(null);
  mockSetCachedAIResponse.mockResolvedValue(undefined);
  mockLoadMemory.mockResolvedValue("");
  mockExtractPreferences.mockReturnValue([]);
  mockDetectPreferenceDrift.mockResolvedValue([]);
  mockGetMemoryContext.mockResolvedValue("");
  mockRedisGet.mockResolvedValue(null);
  mockRedisSet.mockResolvedValue("OK");
  mockRecordDirectAIEvalSnapshot.mockResolvedValue({
    ok: true,
    id: "snap-1",
    promptHash: "hash",
  });

  // Supabase: return an account on first query
  const accountChain = {
    select: vi.fn().mockReturnThis(),
    eq: vi.fn().mockReturnThis(),
    limit: vi.fn().mockReturnThis(),
    order: vi.fn().mockReturnThis(),
    gte: vi.fn().mockReturnThis(),
    maybeSingle: vi.fn().mockResolvedValue({
      data: { id: "acc-1", username: "testuser", platform: "threads", followers_count: 500 },
      error: null,
    }),
  };
  mockFrom.mockReturnValue(accountChain);

  mockGenerateContent.mockResolvedValue({
    text: "Here are some insights based on your data.",
    usageMetadata: { promptTokenCount: 100, candidatesTokenCount: 60, thoughtsTokenCount: 0 },
  });
  mockGenerateWithProvider.mockImplementation(async () => {
    mockTrackAICost("user-1", 100, 60, "gemini-2.0-flash", "copilot", "user", 0);
    return "Here are some insights based on your data.";
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AI Copilot Handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Method check ──────────────────────────────────────────────────────────

  it("rejects non-POST requests with 405", async () => {
    const res = mockRes();
    await invokeHandler(makeReq({}, "GET"), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(405);
  });

  // ── Input validation ──────────────────────────────────────────────────────

  it("rejects missing message with 400", async () => {
    const res = mockRes();
    await invokeHandler(makeReq({}), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith(expect.objectContaining({ error: expect.stringContaining("message") }));
  });

  it("rejects non-string message with 400", async () => {
    const res = mockRes();
    await invokeHandler(makeReq({ message: 42 }), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  // ── Tier gate ─────────────────────────────────────────────────────────────

  it("blocks free-tier users when requireMinTier returns false", async () => {
    mockRequireMinTier.mockResolvedValue(false);
    const res = mockRes();
    await invokeHandler(makeReq({ message: "How am I doing?" }), res, TEST_USER);
    expect(mockCheckAIRateLimit).not.toHaveBeenCalled();
  });

  // ── Rate limiting ─────────────────────────────────────────────────────────

  it("returns 429 when rate limit exceeded", async () => {
    mockRequireMinTier.mockResolvedValue(true);
    mockCheckAIRateLimit.mockResolvedValue({ allowed: false, remaining: 0, limit: 100 });
    const res = mockRes();
    await invokeHandler(makeReq({ message: "test" }), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(429);
    expect(res.json).toHaveBeenCalledWith(expect.objectContaining({ code: "RATE_LIMITED" }));
  });

  it("sets rate limit headers", async () => {
    mockRequireMinTier.mockResolvedValue(true);
    mockCheckAIRateLimit.mockResolvedValue({ allowed: false, remaining: 5, limit: 100 });
    const res = mockRes();
    await invokeHandler(makeReq({ message: "test" }), res, TEST_USER);
    expect(res.setHeader).toHaveBeenCalledWith("X-RateLimit-Limit", "100");
    expect(res.setHeader).toHaveBeenCalledWith("X-RateLimit-Remaining", "5");
  });

  // ── No API key ────────────────────────────────────────────────────────────

  it("returns 503 when no AI API key available", async () => {
    mockRequireMinTier.mockResolvedValue(true);
    mockCheckAIRateLimit.mockResolvedValue({ allowed: true, remaining: 50, limit: 100 });
    mockGetUserAIConfig.mockResolvedValue(null);
    const res = mockRes();
    await invokeHandler(makeReq({ message: "test" }), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(503);
    expect(res.json).toHaveBeenCalledWith(expect.objectContaining({ code: "NO_API_KEY" }));
  });

  // ── Cache hit ─────────────────────────────────────────────────────────────

  it("returns cached response on cache hit", async () => {
    setupHappyPath();
    mockGetCachedAIResponse.mockResolvedValue("Cached copilot response");
    const res = mockRes();
    await invokeHandler(makeReq({ message: "How is my engagement?" }), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ response: "Cached copilot response", cached: true }),
    );
    expect(mockGenerateWithProvider).not.toHaveBeenCalled();
  });

  // ── Happy path ────────────────────────────────────────────────────────────

  it("generates and returns a copilot response", async () => {
    setupHappyPath();
    const res = mockRes();
    await invokeHandler(makeReq({ message: "How is my engagement doing?" }), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(200);
    const call = res.json.mock.calls[0][0];
    expect(call.success).toBe(true);
    expect(call.response).toBe("Here are some insights based on your data.");
    expect(call.dataUsed).toBeDefined();
  });

  it("records live eval snapshots for copilot responses", async () => {
    setupHappyPath();
    const res = mockRes();
    await invokeHandler(makeReq({ message: "How is my engagement doing?", accountId: "acc-1" }), res, TEST_USER);
    expect(mockRecordDirectAIEvalSnapshot).toHaveBeenCalledWith(
      expect.objectContaining({
        userId: "user-1",
        accountId: "acc-1",
        surface: "copilot",
        actionType: "copilot_response",
        category: "operator_command",
        output: "Here are some insights based on your data.",
        metadata: expect.objectContaining({
          streamed: false,
          dataUsed: expect.any(Array),
        }),
      }),
    );
  });

  it("caches the generated response", async () => {
    setupHappyPath();
    const res = mockRes();
    await invokeHandler(makeReq({ message: "test" }), res, TEST_USER);
    expect(mockSetCachedAIResponse).toHaveBeenCalled();
  });

  it("extracts and stores user preferences from exchange", async () => {
    setupHappyPath();
    mockExtractPreferences.mockReturnValue([
      { key: "preferred_tone", value: "casual" },
    ]);
    const res = mockRes();
    await invokeHandler(makeReq({ message: "I prefer casual tone" }), res, TEST_USER);
    expect(mockStoreMemory).toHaveBeenCalledWith("user-1", "preferred_tone", "casual");
  });

  // ── Error handling ────────────────────────────────────────────────────────

  it("returns 502 when generation throws an error", async () => {
    setupHappyPath();
    mockGenerateWithProvider.mockRejectedValue(new Error("AI provider error"));
    const res = mockRes();
    await invokeHandler(makeReq({ message: "test" }), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(502);
  });

  // ── Fallback account ──────────────────────────────────────────────────────

  it("falls back to first account when no accountId provided", async () => {
    setupHappyPath();
    const res = mockRes();
    await invokeHandler(makeReq({ message: "How am I doing?" }), res, TEST_USER);
    // Verifies that accounts were queried even without explicit accountId
    expect(mockFrom).toHaveBeenCalledWith("accounts");
  });

  // ── Cost tracking ─────────────────────────────────────────────────────────

  it("tracks AI cost after generation", async () => {
    setupHappyPath();
    const res = mockRes();
    await invokeHandler(makeReq({ message: "test" }), res, TEST_USER);
    expect(mockTrackAICost).toHaveBeenCalled();
  });
});
