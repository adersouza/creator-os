/**
 * Unit tests for AI Generate Single handler
 * (api/_lib/handlers/ai/generate-single.ts)
 *
 * Covers: method check, auth, input validation (Zod),
 * group ownership, no API key, happy path, generation failure, error handling.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockGetAuthUserOrError = vi.fn();
const mockFrom = vi.fn();
const mockGetUserAIConfig = vi.fn();
const mockGenerateSinglePost = vi.fn();
const mockRequireMinTier = vi.fn();
const mockCheckAIRateLimit = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock()
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/apiResponse.js", () => ({
  apiError: (res: any, status: number, msg: string, opts?: any) =>
    res.status(status).json({ error: msg, ...opts }),
  apiSuccess: (res: any, data?: unknown) =>
    res.status(200).json({ success: true, ...(data as any) }),
  getAuthUserOrError: (...args: unknown[]) => mockGetAuthUserOrError(...args),
}));

vi.mock("@/api/_lib/supabase.js", () => ({
  getSupabase: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/tierGate.js", () => ({
  requireMinTier: (...args: unknown[]) => mockRequireMinTier(...args),
}));

vi.mock("@/api/_lib/aiRateLimit.js", () => ({
  checkAIRateLimit: (...args: unknown[]) => mockCheckAIRateLimit(...args),
}));

vi.mock("@/api/_lib/logger.js", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/api/_lib/validation.js", () => {
  return {
    parseBodyOrError: (res: any, schema: any, body: any) => {
      const result = schema.safeParse(body);
      if (!result.success) {
        res.status(400).json({ error: result.error.issues[0]?.message || "Validation error" });
        return null;
      }
      return result.data;
    },
  };
});

vi.mock("@/api/_lib/zodCompat.js", () => ({
  z: require("zod").z,
  zEnum: (...args: any[]) => {
    const { z } = require("zod");
    return z.enum(...args);
  },
}));

// Mock the dynamic import of contentSelection
vi.mock("@/api/_lib/handlers/auto-post/contentSelection.js", () => ({
  getUserAIConfig: (...args: unknown[]) => mockGetUserAIConfig(...args),
  generateSinglePost: (...args: unknown[]) => mockGenerateSinglePost(...args),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import handler from "@/api/_lib/handlers/ai/generate-single";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TEST_USER = { id: "user-1", email: "test@test.com" };

function makeReq(body: Record<string, unknown> = {}, method = "POST") {
  return { method, body, headers: { authorization: "Bearer test-token" } };
}

/** Build a Supabase chain mock for account_groups */
function mockGroupChain(groupData: Record<string, unknown> | null) {
  return {
    select: vi.fn().mockReturnThis(),
    eq: vi.fn().mockReturnThis(),
    maybeSingle: vi.fn().mockResolvedValue({
      data: groupData,
      error: null,
    }),
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AI Generate Single Handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetAuthUserOrError.mockResolvedValue(TEST_USER);
    mockRequireMinTier.mockResolvedValue(true);
    mockCheckAIRateLimit.mockResolvedValue({ allowed: true, remaining: 99, limit: 100 });
  });

  // ── Method check ──────────────────────────────────────────────────────────

  it("rejects non-POST requests with 405", async () => {
    const res = mockRes();
    await handler(makeReq({}, "GET") as any, res as any);
    expect(res.status).toHaveBeenCalledWith(405);
  });

  // ── Auth check ────────────────────────────────────────────────────────────

  it("returns early when auth fails (no user)", async () => {
    mockGetAuthUserOrError.mockResolvedValue(null);
    const res = mockRes();
    await handler(makeReq({ groupId: "g1" }) as any, res as any);
    // Should return early without calling supabase
    expect(mockFrom).not.toHaveBeenCalled();
  });

  // ── Input validation ──────────────────────────────────────────────────────

  it("rejects missing groupId with 400", async () => {
    const res = mockRes();
    await handler(makeReq({}) as any, res as any);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("rejects empty groupId with 400", async () => {
    const res = mockRes();
    await handler(makeReq({ groupId: "" }) as any, res as any);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("accepts valid optional fields", async () => {
    mockFrom.mockReturnValue(mockGroupChain({
      voice_profile: "casual creator",
      content_strategy: { topics: ["tech"] },
    }));
    mockGetUserAIConfig.mockResolvedValue({ apiKey: "key-1" });
    mockGenerateSinglePost.mockResolvedValue({ content: "Generated post", contentType: "hot-take" });

    const res = mockRes();
    await handler(
      makeReq({
        groupId: "g1",
        contentType: "hot-take",
        mediaDescription: "A sunset photo",
        trendingTopic: "AI boom",
        platform: "instagram",
      }) as any,
      res as any,
    );
    expect(res.status).toHaveBeenCalledWith(200);
  });

  it("rejects invalid platform value with 400", async () => {
    const res = mockRes();
    await handler(makeReq({ groupId: "g1", platform: "tiktok" }) as any, res as any);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  // ── Group not found ───────────────────────────────────────────────────────

  it("returns 404 when group not found", async () => {
    mockFrom.mockReturnValue(mockGroupChain(null));
    const res = mockRes();
    await handler(makeReq({ groupId: "nonexistent" }) as any, res as any);
    expect(res.status).toHaveBeenCalledWith(404);
    expect(res.json).toHaveBeenCalledWith(expect.objectContaining({ error: "Group not found" }));
  });

  // ── No API key ────────────────────────────────────────────────────────────

  it("returns 400 when no AI API key configured", async () => {
    mockFrom.mockReturnValue(mockGroupChain({
      voice_profile: "casual creator",
      content_strategy: null,
    }));
    mockGetUserAIConfig.mockResolvedValue(null);
    const res = mockRes();
    await handler(makeReq({ groupId: "g1" }) as any, res as any);
    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith(expect.objectContaining({ error: expect.stringContaining("API key") }));
  });

  it("returns 400 when AI config has no apiKey", async () => {
    mockFrom.mockReturnValue(mockGroupChain({
      voice_profile: "casual creator",
      content_strategy: null,
    }));
    mockGetUserAIConfig.mockResolvedValue({ provider: "gemini" }); // no apiKey
    const res = mockRes();
    await handler(makeReq({ groupId: "g1" }) as any, res as any);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  // ── Happy path ────────────────────────────────────────────────────────────

  it("generates and returns a single post on success", async () => {
    mockFrom.mockReturnValue(mockGroupChain({
      voice_profile: "Witty tech reviewer",
      content_strategy: { topics: ["AI", "startups"] },
    }));
    mockGetUserAIConfig.mockResolvedValue({ apiKey: "key-1" });
    mockGenerateSinglePost.mockResolvedValue({
      content: "AI is changing everything and here's why.",
      contentType: "hot-take",
      score: 85,
    });

    const res = mockRes();
    await handler(makeReq({ groupId: "g1" }) as any, res as any);
    expect(res.status).toHaveBeenCalledWith(200);
    const call = res.json.mock.calls[0][0];
    expect(call.success).toBe(true);
    expect(call.content).toBe("AI is changing everything and here's why.");
  });

  it("passes voice profile and content strategy to generateSinglePost", async () => {
    const voiceProfile = { voice_profile: "Sarcastic millennial" };
    const contentStrategy = { topics: ["fitness"], tone: "motivational" };
    mockFrom.mockReturnValue(mockGroupChain({
      voice_profile: voiceProfile,
      content_strategy: contentStrategy,
    }));
    mockGetUserAIConfig.mockResolvedValue({ apiKey: "key-1" });
    mockGenerateSinglePost.mockResolvedValue({ content: "Get moving!" });

    const res = mockRes();
    await handler(makeReq({ groupId: "g1", contentType: "motivational" }) as any, res as any);

    expect(mockGenerateSinglePost).toHaveBeenCalledWith(
      "user-1",
      "key-1",
      expect.objectContaining({ groupId: "g1", contentType: "motivational", platform: "threads" }),
      voiceProfile,
      contentStrategy,
    );
  });

  // ── Generation failure ────────────────────────────────────────────────────

  it("returns 422 when generateSinglePost returns null", async () => {
    mockFrom.mockReturnValue(mockGroupChain({
      voice_profile: "casual",
      content_strategy: null,
    }));
    mockGetUserAIConfig.mockResolvedValue({ apiKey: "key-1" });
    mockGenerateSinglePost.mockResolvedValue(null);

    const res = mockRes();
    await handler(makeReq({ groupId: "g1" }) as any, res as any);
    expect(res.status).toHaveBeenCalledWith(422);
    expect(res.json).toHaveBeenCalledWith(expect.objectContaining({
      error: expect.stringContaining("Failed to generate"),
    }));
  });

  // ── Error handling ────────────────────────────────────────────────────────

  it("returns 500 when an unexpected error occurs", async () => {
    mockFrom.mockReturnValue(mockGroupChain({
      voice_profile: "casual",
      content_strategy: null,
    }));
    mockGetUserAIConfig.mockResolvedValue({ apiKey: "key-1" });
    mockGenerateSinglePost.mockRejectedValue(new Error("Provider timeout"));

    const res = mockRes();
    await handler(makeReq({ groupId: "g1" }) as any, res as any);
    expect(res.status).toHaveBeenCalledWith(500);
  });

  // ── String voice_profile handling ─────────────────────────────────────────

  it("wraps string voice_profile in an object", async () => {
    mockFrom.mockReturnValue(mockGroupChain({
      voice_profile: "Witty tech bro",
      content_strategy: null,
    }));
    mockGetUserAIConfig.mockResolvedValue({ apiKey: "key-1" });
    mockGenerateSinglePost.mockResolvedValue({ content: "test" });

    const res = mockRes();
    await handler(makeReq({ groupId: "g1" }) as any, res as any);

    expect(mockGenerateSinglePost).toHaveBeenCalledWith(
      "user-1",
      "key-1",
      expect.anything(),
      { voice_profile: "Witty tech bro" },
      null,
    );
  });

  // ── Default platform ──────────────────────────────────────────────────────

  it("defaults platform to threads when not specified", async () => {
    mockFrom.mockReturnValue(mockGroupChain({
      voice_profile: "test",
      content_strategy: null,
    }));
    mockGetUserAIConfig.mockResolvedValue({ apiKey: "key-1" });
    mockGenerateSinglePost.mockResolvedValue({ content: "test" });

    const res = mockRes();
    await handler(makeReq({ groupId: "g1" }) as any, res as any);

    expect(mockGenerateSinglePost).toHaveBeenCalledTimes(1);
    const callArgs = mockGenerateSinglePost.mock.calls[0];
    expect(callArgs[2].platform).toBe("threads");
  });
});
