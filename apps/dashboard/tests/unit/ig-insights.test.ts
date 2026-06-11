/**
 * Unit tests for Instagram Insights handler
 * (api/_lib/handlers/instagram/insights.ts)
 *
 * Covers: account-insights, post-insights, carousel-children,
 * publishing-limit, tagged-posts, mentioned-media,
 * plus validation, auth, caching, needs_reauth, and error paths.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();

const mockGetInstagramAccountInsights = vi.fn();
const mockGetInstagramPostMetrics = vi.fn();
const mockGetCarouselChildInsights = vi.fn();
const mockCheckPublishingLimit = vi.fn();
const mockGetTaggedMedia = vi.fn();
const mockGetMentionedMedia = vi.fn();
const mockHandleIgAuthError = vi.fn();

const mockRedisGet = vi.fn();
const mockRedisSet = vi.fn().mockResolvedValue("OK");

// ---------------------------------------------------------------------------
// vi.mock()
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/supabase.js", () => ({
  getSupabase: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/logger.js", () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}));

vi.mock("@/api/_lib/apiResponse.js", () => ({
  apiError: (res: any, status: number, msg: string) =>
    res.status(status).json({ error: msg }),
  apiSuccess: (res: any, data?: unknown) =>
    res.status(200).json({ data: data ?? {} }),
  handleIgAuthError: (...args: unknown[]) => mockHandleIgAuthError(...args),
}));

vi.mock("@/api/_lib/middleware.js", () => ({
  withAuth: (handler: any) => handler,
}));

vi.mock("@/api/_lib/redis.js", () => ({
  getRedis: () => ({
    get: (...args: unknown[]) => mockRedisGet(...args),
    set: (...args: unknown[]) => mockRedisSet(...args),
  }),
}));

vi.mock("@/api/_lib/zodCompat.js", () => ({
  z: require("zod").z,
  zEnum: (...args: any[]) => {
    const { z } = require("zod");
    return z.enum(...args);
  },
}));

vi.mock("@/api/_lib/instagramApi.js", () => ({
  getInstagramAccountInsights: (...args: unknown[]) =>
    mockGetInstagramAccountInsights(...args),
  getInstagramPostMetrics: (...args: unknown[]) =>
    mockGetInstagramPostMetrics(...args),
  getCarouselChildInsights: (...args: unknown[]) =>
    mockGetCarouselChildInsights(...args),
  checkPublishingLimit: (...args: unknown[]) =>
    mockCheckPublishingLimit(...args),
  getTaggedMedia: (...args: unknown[]) => mockGetTaggedMedia(...args),
  getMentionedMedia: (...args: unknown[]) => mockGetMentionedMedia(...args),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import handler from "@/api/_lib/handlers/instagram/insights";
const invokeHandler = handler as unknown as (req: any, res: any, user: any) => Promise<void>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TEST_USER = { id: "user-1" };

function makeReq(action: string, body: Record<string, unknown> = {}) {
  return {
    method: "POST",
    query: { action },
    body,
    headers: {},
  } as any;
}

function stubIgAccount(overrides: Record<string, unknown> = {}) {
  const account = {
    instagram_access_token_encrypted: "enc-token",
    instagram_user_id: "ig-user-1",
    login_type: "instagram",
    needs_reauth: false,
    ...overrides,
  };
  mockFrom.mockImplementation((table: string) => {
    if (table === "instagram_accounts") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              maybeSingle: vi.fn().mockResolvedValue({
                data: account,
                error: null,
              }),
            }),
          }),
        }),
      };
    }
    if (table === "posts") {
      const postQuery = {
        eq: vi.fn(() => postQuery),
        maybeSingle: vi.fn().mockResolvedValue({
          data: {
            instagram_post_id: "ig-post-123",
            ig_media_type: "CAROUSEL_ALBUM",
          },
          error: null,
        }),
      };
      return {
        select: vi.fn().mockReturnValue(postQuery),
      };
    }
    return {
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
    };
  });
}

function stubIgAccountNotFound() {
  mockFrom.mockImplementation(() => ({
    select: vi.fn().mockReturnValue({
      eq: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
        }),
      }),
    }),
  }));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockRedisGet.mockResolvedValue(null); // no cache by default
});

describe("Instagram Insights handler", () => {
  // =========================================================================
  // Method guard
  // =========================================================================

  it("rejects non-POST methods with 405", async () => {
    const req = { method: "GET", query: { action: "account-insights" }, body: {}, headers: {} } as any;
    const res = mockRes();
    await invokeHandler(req, res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(405);
  });

  it("returns 400 for unknown action", async () => {
    const res = mockRes();
    await invokeHandler(makeReq("nonexistent"), res, TEST_USER);
    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: expect.stringContaining("Unknown action") }),
    );
  });

  // =========================================================================
  // Account Insights
  // =========================================================================

  describe("account-insights", () => {
    it("returns 400 when accountId missing", async () => {
      const res = mockRes();
      await invokeHandler(makeReq("account-insights", {}), res, TEST_USER);
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns 404 when account not found", async () => {
      stubIgAccountNotFound();
      const res = mockRes();
      await invokeHandler(
        makeReq("account-insights", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(404);
    });

    it("returns 400 when account has no token", async () => {
      stubIgAccount({ instagram_access_token_encrypted: null });
      const res = mockRes();
      await invokeHandler(
        makeReq("account-insights", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns 401 when account needs re-authentication", async () => {
      stubIgAccount({ needs_reauth: true });
      const res = mockRes();
      await invokeHandler(
        makeReq("account-insights", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(401);
      expect(res.json).toHaveBeenCalledWith(
        expect.objectContaining({
          error: expect.stringContaining("re-authentication"),
        }),
      );
    });

    it("returns cached insights when available", async () => {
      stubIgAccount();
      const cachedInsights = { impressions: 500, reach: 300 };
      mockRedisGet.mockResolvedValue(cachedInsights);

      const res = mockRes();
      await invokeHandler(
        makeReq("account-insights", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(res.json).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({
            insights: cachedInsights,
            cached: true,
          }),
        }),
      );
      // Should not call the Meta API
      expect(mockGetInstagramAccountInsights).not.toHaveBeenCalled();
    });

    it("fetches fresh insights and caches them", async () => {
      stubIgAccount();
      mockRedisGet.mockResolvedValue(null);
      const freshInsights = { impressions: 1000, reach: 600 };
      mockGetInstagramAccountInsights.mockResolvedValue({
        success: true,
        insights: freshInsights,
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("account-insights", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(mockGetInstagramAccountInsights).toHaveBeenCalled();
      // Verify cache write
      expect(mockRedisSet).toHaveBeenCalledWith(
        expect.stringContaining("ig-insights:"),
        expect.any(String),
        { ex: 300 },
      );
    });

    it("proceeds without cache when Redis is down", async () => {
      stubIgAccount();
      mockRedisGet.mockRejectedValue(new Error("Redis connection refused"));
      mockGetInstagramAccountInsights.mockResolvedValue({
        success: true,
        insights: { impressions: 100 },
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("account-insights", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(mockGetInstagramAccountInsights).toHaveBeenCalled();
    });

    it("calls handleIgAuthError when API fails", async () => {
      stubIgAccount();
      mockGetInstagramAccountInsights.mockResolvedValue({
        success: false,
        error: "Token expired",
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("account-insights", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(mockHandleIgAuthError).toHaveBeenCalledWith(
        res,
        "acc-1",
        "user-1",
        "Token expired",
      );
    });

    it("passes period parameter to API", async () => {
      stubIgAccount();
      mockGetInstagramAccountInsights.mockResolvedValue({
        success: true,
        insights: {},
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("account-insights", { accountId: "acc-1", period: "days_28" }),
        res,
        TEST_USER,
      );
      expect(mockGetInstagramAccountInsights).toHaveBeenCalledWith(
        "enc-token",
        "ig-user-1",
        "days_28",
        "instagram",
      );
    });

    it("defaults period to 'day' when not specified", async () => {
      stubIgAccount();
      mockGetInstagramAccountInsights.mockResolvedValue({
        success: true,
        insights: {},
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("account-insights", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(mockGetInstagramAccountInsights).toHaveBeenCalledWith(
        "enc-token",
        "ig-user-1",
        "day",
        "instagram",
      );
    });
  });

  // =========================================================================
  // Post Insights
  // =========================================================================

  describe("post-insights", () => {
    it("returns 400 when mediaId missing", async () => {
      const res = mockRes();
      await invokeHandler(
        makeReq("post-insights", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns post metrics on success", async () => {
      stubIgAccount();
      const metrics = { impressions: 500, reach: 200, likes: 50 };
      mockGetInstagramPostMetrics.mockResolvedValue({
        success: true,
        metrics,
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("post-insights", { accountId: "acc-1", mediaId: "m-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(res.json).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({ metrics }),
        }),
      );
    });
  });

  // =========================================================================
  // Carousel Children
  // =========================================================================

  describe("carousel-children", () => {
    it("returns 400 when postId missing", async () => {
      const res = mockRes();
      await invokeHandler(
        makeReq("carousel-children", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns 404 when post has no instagram_post_id", async () => {
      mockFrom.mockImplementation((table: string) => {
        if (table === "posts") {
          return {
            select: vi.fn().mockReturnValue({
              eq: vi.fn().mockReturnValue({
                eq: vi.fn().mockReturnValue({
                  maybeSingle: vi.fn().mockResolvedValue({
                    data: { instagram_post_id: null, ig_media_type: "IMAGE" },
                    error: null,
                  }),
                }),
              }),
            }),
          };
        }
        return {
          select: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              eq: vi.fn().mockReturnValue({
                maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
              }),
            }),
          }),
        };
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("carousel-children", { postId: "p-1", accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(404);
    });

    it("returns 400 when post is not a carousel", async () => {
      mockFrom.mockImplementation((table: string) => {
        if (table === "posts") {
          return {
            select: vi.fn().mockReturnValue({
              eq: vi.fn().mockReturnValue({
                eq: vi.fn().mockReturnValue({
                  maybeSingle: vi.fn().mockResolvedValue({
                    data: {
                      instagram_post_id: "ig-p-1",
                      ig_media_type: "IMAGE",
                    },
                    error: null,
                  }),
                }),
              }),
            }),
          };
        }
        return {
          select: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              eq: vi.fn().mockReturnValue({
                maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
              }),
            }),
          }),
        };
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("carousel-children", { postId: "p-1", accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
      expect(res.json).toHaveBeenCalledWith(
        expect.objectContaining({
          error: expect.stringContaining("not a carousel"),
        }),
      );
    });

    it("returns children insights for a carousel post", async () => {
      stubIgAccount();
      mockGetCarouselChildInsights.mockResolvedValue({
        success: true,
        children: [
          { id: "child-1", impressions: 100 },
          { id: "child-2", impressions: 200 },
        ],
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("carousel-children", { postId: "p-1", accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(res.json).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({
            children: expect.arrayContaining([
              expect.objectContaining({ id: "child-1" }),
            ]),
          }),
        }),
      );
    });
  });

  // =========================================================================
  // Publishing Limit
  // =========================================================================

  describe("publishing-limit", () => {
    it("returns quota on success", async () => {
      stubIgAccount();
      mockCheckPublishingLimit.mockResolvedValue({
        success: true,
        quota: { quota_usage: 5, quota_total: 25 },
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("publishing-limit", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(res.json).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({
            quota: { quota_usage: 5, quota_total: 25 },
          }),
        }),
      );
    });

    it("returns 404 when account not found", async () => {
      stubIgAccountNotFound();
      const res = mockRes();
      await invokeHandler(
        makeReq("publishing-limit", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(404);
    });
  });

  // =========================================================================
  // Tagged Posts
  // =========================================================================

  describe("tagged-posts", () => {
    it("returns tagged media on success", async () => {
      stubIgAccount();
      mockGetTaggedMedia.mockResolvedValue({
        success: true,
        media: [{ id: "tagged-1", media_type: "IMAGE" }],
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("tagged-posts", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(res.json).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({
            media: [{ id: "tagged-1", media_type: "IMAGE" }],
            count: 1,
          }),
        }),
      );
    });

    it("returns empty array when no tagged media", async () => {
      stubIgAccount();
      mockGetTaggedMedia.mockResolvedValue({
        success: true,
        media: null,
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("tagged-posts", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(res.json).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({
            media: [],
            count: 0,
          }),
        }),
      );
    });

    it("returns 400 when account has no token", async () => {
      stubIgAccount({ instagram_access_token_encrypted: null });
      const res = mockRes();
      await invokeHandler(
        makeReq("tagged-posts", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });
  });

  // =========================================================================
  // Mentioned Media
  // =========================================================================

  describe("mentioned-media", () => {
    it("returns mentioned media on success", async () => {
      stubIgAccount();
      mockGetMentionedMedia.mockResolvedValue({
        success: true,
        media: { id: "mention-1", caption: "tagged you" },
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("mentioned-media", { accountId: "acc-1", mediaId: "m-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(res.json).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({
            media: { id: "mention-1", caption: "tagged you" },
          }),
        }),
      );
    });

    it("returns null when mentioned media not found", async () => {
      stubIgAccount();
      mockGetMentionedMedia.mockResolvedValue({
        success: true,
        media: null,
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("mentioned-media", { accountId: "acc-1", mediaId: "m-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(res.json).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({ media: null }),
        }),
      );
    });

    it("returns 400 when mediaId missing", async () => {
      const res = mockRes();
      await invokeHandler(
        makeReq("mentioned-media", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });
  });
});
