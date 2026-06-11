/**
 * Unit tests for Instagram Comments handler
 * (api/_lib/handlers/instagram/comments.ts)
 *
 * Covers: list, list-local, reply, hide, delete, toggle-comments,
 * private-reply, plus validation, auth, rate limiting, and error paths.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockRpc = vi.fn();

const mockGetMediaComments = vi.fn();
const mockReplyToComment = vi.fn();
const mockHideComment = vi.fn();
const mockDeleteComment = vi.fn();
const mockToggleCommentEnabled = vi.fn();
const mockSendPrivateReply = vi.fn();
const mockCreateNotification = vi.fn().mockResolvedValue(undefined);
const mockHandleIgAuthError = vi.fn();
const mockVerifyIgAccountOwnership = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock()
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/supabase.js", () => ({
  getSupabase: () => ({ from: mockFrom, rpc: mockRpc }),
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

vi.mock("@/api/_lib/idempotency.js", () => ({
  withIdempotency: async (_req: any, _res: any, _options: any, handler: any) =>
    handler(),
}));

vi.mock("@/api/_lib/sanitize.js", () => ({
  sanitizeMessage: (s: string) => s,
}));

vi.mock("@/api/_lib/instagramApi.js", () => ({
  getMediaComments: (...args: unknown[]) => mockGetMediaComments(...args),
  replyToComment: (...args: unknown[]) => mockReplyToComment(...args),
  hideComment: (...args: unknown[]) => mockHideComment(...args),
  deleteComment: (...args: unknown[]) => mockDeleteComment(...args),
  toggleCommentEnabled: (...args: unknown[]) => mockToggleCommentEnabled(...args),
  sendPrivateReply: (...args: unknown[]) => mockSendPrivateReply(...args),
}));

vi.mock("@/api/_lib/createNotification.js", () => ({
  createNotification: (...args: unknown[]) => mockCreateNotification(...args),
}));

vi.mock("@/api/_lib/handlers/helpers/verifyOwnership.js", () => ({
  verifyIgAccountOwnership: (...args: unknown[]) =>
    mockVerifyIgAccountOwnership(...args),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import handler from "@/api/_lib/handlers/instagram/comments";
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
    ...overrides,
  };
  mockFrom.mockImplementation((table: string) => {
    if (table === "instagram_accounts") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              maybeSingle: vi.fn().mockResolvedValue({ data: account, error: null }),
            }),
          }),
        }),
      };
    }
    if (table === "ig_endpoint_rate_limits") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              maybeSingle: vi.fn().mockResolvedValue({
                data: { requests_this_hour: 2, requests_today: 10 },
                error: null,
              }),
            }),
          }),
        }),
      };
    }
    if (table === "ig_comments") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: { post_id: "post-1", media_id: "media-1" },
              error: null,
            }),
            order: vi.fn().mockReturnValue({
              limit: vi.fn().mockResolvedValue({
                data: [],
                error: null,
              }),
            }),
          }),
        }),
        upsert: vi.fn().mockResolvedValue({ error: null }),
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

function stubIgAccountNoToken() {
  mockFrom.mockImplementation((table: string) => {
    if (table === "instagram_accounts") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              maybeSingle: vi.fn().mockResolvedValue({
                data: {
                  instagram_access_token_encrypted: null,
                  login_type: "instagram",
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
            maybeSingle: vi.fn().mockResolvedValue({
              data: { requests_this_hour: 0, requests_today: 0 },
              error: null,
            }),
          }),
        }),
      }),
    };
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockRpc.mockResolvedValue({
    data: [{ allowed: true, reason: null }],
    error: null,
  });
});

describe("Instagram Comments handler", () => {
  // =========================================================================
  // Method guard
  // =========================================================================

  it("rejects non-POST methods with 405", async () => {
    const req = { method: "GET", query: { action: "list" }, body: {}, headers: {} } as any;
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
  // List
  // =========================================================================

  describe("list", () => {
    it("returns 400 when accountId missing", async () => {
      const res = mockRes();
      await invokeHandler(makeReq("list", { mediaId: "m-1" }), res, TEST_USER);
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns 400 when mediaId missing", async () => {
      const res = mockRes();
      await invokeHandler(makeReq("list", { accountId: "acc-1" }), res, TEST_USER);
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns 404 when account not found", async () => {
      stubIgAccountNotFound();
      const res = mockRes();
      await invokeHandler(
        makeReq("list", { accountId: "acc-1", mediaId: "m-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(404);
    });

    it("returns 400 when account has no token", async () => {
      stubIgAccountNoToken();
      const res = mockRes();
      await invokeHandler(
        makeReq("list", { accountId: "acc-1", mediaId: "m-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns comments on success", async () => {
      stubIgAccount();
      mockGetMediaComments.mockResolvedValue({
        success: true,
        comments: [{ id: "c-1", text: "nice!", username: "fan" }],
        paging: null,
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("list", { accountId: "acc-1", mediaId: "m-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(res.json).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({
            comments: expect.arrayContaining([
              expect.objectContaining({ id: "c-1" }),
            ]),
          }),
        }),
      );
    });

    it("calls handleIgAuthError when API fails", async () => {
      stubIgAccount();
      mockGetMediaComments.mockResolvedValue({
        success: false,
        error: "Rate limit hit",
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("list", { accountId: "acc-1", mediaId: "m-1" }),
        res,
        TEST_USER,
      );
      expect(mockHandleIgAuthError).toHaveBeenCalledWith(
        res,
        "acc-1",
        "user-1",
        "Rate limit hit",
      );
    });
  });

  // =========================================================================
  // List Local
  // =========================================================================

  describe("list-local", () => {
    it("returns 400 when mediaId missing", async () => {
      const res = mockRes();
      await invokeHandler(
        makeReq("list-local", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns comments from local DB when ownership verified", async () => {
      mockVerifyIgAccountOwnership.mockResolvedValue({ id: "acc-1" });
      let localCommentsQuery: any = null;

      mockFrom.mockImplementation((table: string) => {
        if (table === "ig_comments") {
          const query: any = {
            select: vi.fn(() => query),
            eq: vi.fn(() => query),
            order: vi.fn(() => query),
            limit: vi.fn().mockResolvedValue({
              data: [
                {
                  comment_id: "c-1",
                  username: "fan",
                  text: "great post!",
                  created_at: "2026-01-01T00:00:00Z",
                  like_count: 5,
                  ig_user_id: "ig-1",
                },
              ],
              error: null,
            }),
          };
          localCommentsQuery = query;
          return {
            select: query.select,
          };
        }
        return {
          select: vi.fn().mockReturnThis(),
          eq: vi.fn().mockReturnThis(),
          maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
        };
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("list-local", { accountId: "acc-1", mediaId: "m-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(mockVerifyIgAccountOwnership).toHaveBeenCalled();
      expect(mockFrom).toHaveBeenCalledWith("ig_comments");
      expect(localCommentsQuery.eq).toHaveBeenCalledWith("media_id", "m-1");
      expect(localCommentsQuery.eq).toHaveBeenCalledWith("account_id", "acc-1");
    });

    it("returns early when ownership check fails", async () => {
      // When verifyIgAccountOwnership returns falsy, handler returns early
      mockVerifyIgAccountOwnership.mockResolvedValue(null);

      const res = mockRes();
      await invokeHandler(
        makeReq("list-local", { accountId: "acc-1", mediaId: "m-1" }),
        res,
        TEST_USER,
      );
      // The ownership helper already sent the 404, so no additional status call
      expect(mockVerifyIgAccountOwnership).toHaveBeenCalled();
    });
  });

  // =========================================================================
  // Reply
  // =========================================================================

  describe("reply", () => {
    it("returns 400 when commentId missing", async () => {
      const res = mockRes();
      await invokeHandler(
        makeReq("reply", { accountId: "acc-1", message: "thanks!" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns 400 when message missing", async () => {
      const res = mockRes();
      await invokeHandler(
        makeReq("reply", { accountId: "acc-1", commentId: "c-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns 429 when rate limited", async () => {
      mockRpc.mockResolvedValue({
        data: [{ allowed: false, reason: "Daily limit exceeded" }],
        error: null,
      });
      stubIgAccount();

      const res = mockRes();
      await invokeHandler(
        makeReq("reply", { accountId: "acc-1", commentId: "c-1", message: "thanks!" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(429);
    });

    it("replies and creates notification on success", async () => {
      stubIgAccount();
      mockReplyToComment.mockResolvedValue({
        success: true,
        commentId: "reply-c-1",
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("reply", { accountId: "acc-1", commentId: "c-1", message: "thanks!" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(mockReplyToComment).toHaveBeenCalled();
      expect(mockCreateNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          userId: "user-1",
          type: "comment_replied",
        }),
      );
    });

    it("calls handleIgAuthError when reply fails", async () => {
      stubIgAccount();
      mockReplyToComment.mockResolvedValue({
        success: false,
        error: "Permission denied",
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("reply", { accountId: "acc-1", commentId: "c-1", message: "thanks!" }),
        res,
        TEST_USER,
      );
      expect(mockHandleIgAuthError).toHaveBeenCalledWith(
        res,
        "acc-1",
        "user-1",
        "Permission denied",
      );
    });
  });

  // =========================================================================
  // Hide
  // =========================================================================

  describe("hide", () => {
    it("returns 400 when hide boolean missing", async () => {
      const res = mockRes();
      await invokeHandler(
        makeReq("hide", { accountId: "acc-1", commentId: "c-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("hides comment on success", async () => {
      stubIgAccount();
      mockHideComment.mockResolvedValue({ success: true });

      const res = mockRes();
      await invokeHandler(
        makeReq("hide", { accountId: "acc-1", commentId: "c-1", hide: true }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(mockHideComment).toHaveBeenCalledWith(
        "enc-token",
        "c-1",
        true,
        "instagram",
      );
    });

    it("unhides comment when hide=false", async () => {
      stubIgAccount();
      mockHideComment.mockResolvedValue({ success: true });

      const res = mockRes();
      await invokeHandler(
        makeReq("hide", { accountId: "acc-1", commentId: "c-1", hide: false }),
        res,
        TEST_USER,
      );
      expect(mockHideComment).toHaveBeenCalledWith(
        "enc-token",
        "c-1",
        false,
        "instagram",
      );
    });
  });

  // =========================================================================
  // Delete
  // =========================================================================

  describe("delete", () => {
    it("deletes comment on success", async () => {
      stubIgAccount();
      mockDeleteComment.mockResolvedValue({ success: true });

      const res = mockRes();
      await invokeHandler(
        makeReq("delete", { accountId: "acc-1", commentId: "c-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(mockDeleteComment).toHaveBeenCalled();
    });

    it("returns 404 when account not found", async () => {
      stubIgAccountNotFound();
      const res = mockRes();
      await invokeHandler(
        makeReq("delete", { accountId: "acc-1", commentId: "c-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(404);
    });
  });

  // =========================================================================
  // Toggle Comments
  // =========================================================================

  describe("toggle-comments", () => {
    it("returns 400 when enabled boolean missing", async () => {
      const res = mockRes();
      await invokeHandler(
        makeReq("toggle-comments", { accountId: "acc-1", mediaId: "m-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("enables comments on success", async () => {
      stubIgAccount();
      mockToggleCommentEnabled.mockResolvedValue({ success: true });

      const res = mockRes();
      await invokeHandler(
        makeReq("toggle-comments", {
          accountId: "acc-1",
          mediaId: "m-1",
          enabled: true,
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(mockToggleCommentEnabled).toHaveBeenCalledWith(
        "enc-token",
        "m-1",
        true,
        "instagram",
      );
    });
  });

  // =========================================================================
  // Private Reply
  // =========================================================================

  describe("private-reply", () => {
    it("sends private reply on success", async () => {
      stubIgAccount();
      mockSendPrivateReply.mockResolvedValue({ success: true });

      const res = mockRes();
      await invokeHandler(
        makeReq("private-reply", {
          accountId: "acc-1",
          commentId: "c-1",
          message: "Check your DMs!",
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(mockSendPrivateReply).toHaveBeenCalled();
    });

    it("returns 404 when account not found", async () => {
      stubIgAccountNotFound();
      const res = mockRes();
      await invokeHandler(
        makeReq("private-reply", {
          accountId: "acc-1",
          commentId: "c-1",
          message: "hi",
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(404);
    });
  });
});
