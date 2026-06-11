/**
 * Unit tests for Instagram Messages handler
 * (api/_lib/handlers/instagram/messages.ts)
 *
 * Covers: conversations, messages, send, send-media, sender-action,
 * send-images, reaction, share-post, heart-sticker, sync-inbox,
 * plus validation, auth, rate limiting, and error paths.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns — declared before vi.mock() calls
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockRpc = vi.fn();

const mockGetConversations = vi.fn();
const mockGetConversationMessages = vi.fn();
const mockSendMessage = vi.fn();
const mockSendMediaMessage = vi.fn();
const mockSendSenderAction = vi.fn();
const mockSendMultiImageMessage = vi.fn();
const mockSendMessageReaction = vi.fn();
const mockSendPostShare = vi.fn();
const mockSendHeartSticker = vi.fn();
const mockSendButtonTemplate = vi.fn();
const mockGetUserProfile = vi.fn();
const mockSendQuickReplies = vi.fn();
const mockSendGenericTemplate = vi.fn();
const mockCreateNotification = vi.fn().mockResolvedValue(undefined);
const mockTrackUsage = vi.fn();
const mockHandleIgAuthError = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock() — before importing module under test
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
  apiSuccess: (res: any, data: unknown) =>
    res.status(200).json({ data }),
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

vi.mock("@/api/_lib/auditLog.js", () => ({
  trackUsage: (...args: unknown[]) => mockTrackUsage(...args),
}));

vi.mock("@/api/_lib/rateLimiter.js", () => ({
  checkRateLimit: vi.fn().mockResolvedValue({ allowed: true, remaining: 29 }),
}));

vi.mock("@/api/_lib/instagramApi.js", () => ({
  getConversations: (...args: unknown[]) => mockGetConversations(...args),
  getConversationMessages: (...args: unknown[]) => mockGetConversationMessages(...args),
  sendMessage: (...args: unknown[]) => mockSendMessage(...args),
  sendMediaMessage: (...args: unknown[]) => mockSendMediaMessage(...args),
  sendSenderAction: (...args: unknown[]) => mockSendSenderAction(...args),
  sendMultiImageMessage: (...args: unknown[]) => mockSendMultiImageMessage(...args),
  sendMessageReaction: (...args: unknown[]) => mockSendMessageReaction(...args),
  sendPostShare: (...args: unknown[]) => mockSendPostShare(...args),
  sendHeartSticker: (...args: unknown[]) => mockSendHeartSticker(...args),
  sendButtonTemplate: (...args: unknown[]) => mockSendButtonTemplate(...args),
  getUserProfile: (...args: unknown[]) => mockGetUserProfile(...args),
  sendQuickReplies: (...args: unknown[]) => mockSendQuickReplies(...args),
  sendGenericTemplate: (...args: unknown[]) => mockSendGenericTemplate(...args),
}));

vi.mock("@/api/_lib/createNotification.js", () => ({
  createNotification: (...args: unknown[]) => mockCreateNotification(...args),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import handler from "@/api/_lib/handlers/instagram/messages";
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

/** Configure mockFrom to return a valid IG account for ownership checks */
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
        update: vi.fn().mockReturnValue({
          eq: vi.fn().mockResolvedValue({ error: null }),
        }),
        upsert: vi.fn().mockResolvedValue({ error: null }),
      };
    }
    if (table === "ig_endpoint_rate_limits") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              maybeSingle: vi.fn().mockResolvedValue({
                data: { requests_this_hour: 5, requests_today: 10 },
                error: null,
              }),
            }),
          }),
        }),
      };
    }
    // Fallback for inbox tables
    return {
      upsert: vi.fn().mockResolvedValue({ error: null }),
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
    };
  });
}

function stubIgAccountNotFound() {
  mockFrom.mockImplementation((_table: string) => ({
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
                  instagram_user_id: "ig-user-1",
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
              data: { requests_this_hour: 0 },
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

describe("Instagram Messages handler", () => {
  // =========================================================================
  // Method guard
  // =========================================================================

  it("rejects non-POST methods with 405", async () => {
    const req = { method: "GET", query: { action: "conversations" }, body: {}, headers: {} } as any;
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
  // Conversations
  // =========================================================================

  describe("conversations", () => {
    it("returns 400 when accountId missing", async () => {
      const res = mockRes();
      await invokeHandler(makeReq("conversations", {}), res, TEST_USER);
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns 404 when account not found", async () => {
      stubIgAccountNotFound();
      const res = mockRes();
      await invokeHandler(makeReq("conversations", { accountId: "acc-1" }), res, TEST_USER);
      expect(res.status).toHaveBeenCalledWith(404);
    });

    it("returns 400 when account has no token", async () => {
      stubIgAccountNoToken();
      const res = mockRes();
      await invokeHandler(makeReq("conversations", { accountId: "acc-1" }), res, TEST_USER);
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns conversations on success", async () => {
      stubIgAccount();
      mockGetConversations.mockResolvedValue({
        success: true,
        conversations: [{ id: "conv-1" }],
        paging: { next: "cursor" },
      });

      const res = mockRes();
      await invokeHandler(makeReq("conversations", { accountId: "acc-1" }), res, TEST_USER);
      expect(res.status).toHaveBeenCalledWith(200);
      expect(res.json).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({
            conversations: [{ id: "conv-1" }],
          }),
        }),
      );
    });

    it("calls handleIgAuthError when API fails", async () => {
      stubIgAccount();
      mockGetConversations.mockResolvedValue({
        success: false,
        error: "Token expired",
      });

      const res = mockRes();
      await invokeHandler(makeReq("conversations", { accountId: "acc-1" }), res, TEST_USER);
      expect(mockHandleIgAuthError).toHaveBeenCalledWith(
        res,
        "acc-1",
        "user-1",
        "Token expired",
      );
    });
  });

  // =========================================================================
  // Messages
  // =========================================================================

  describe("messages", () => {
    it("returns 400 when conversationId missing", async () => {
      const res = mockRes();
      await invokeHandler(
        makeReq("messages", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("fetches messages for a conversation", async () => {
      stubIgAccount();
      mockGetConversationMessages.mockResolvedValue({
        success: true,
        messages: [{ id: "msg-1", message: "hello" }],
        paging: null,
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("messages", { accountId: "acc-1", conversationId: "conv-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(mockGetConversationMessages).toHaveBeenCalled();
    });
  });

  // =========================================================================
  // Send
  // =========================================================================

  describe("send", () => {
    it("returns 400 when message is empty", async () => {
      const res = mockRes();
      await invokeHandler(
        makeReq("send", { accountId: "acc-1", recipientId: "r-1", message: "" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns 429 when rate limited", async () => {
      mockRpc.mockResolvedValue({
        data: [{ allowed: false, reason: "Hourly limit exceeded" }],
        error: null,
      });
      stubIgAccount();

      const res = mockRes();
      await invokeHandler(
        makeReq("send", { accountId: "acc-1", recipientId: "r-1", message: "hi" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(429);
    });

    it("sends message and creates notification on success", async () => {
      stubIgAccount();
      mockSendMessage.mockResolvedValue({
        success: true,
        messageId: "msg-sent-1",
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("send", { accountId: "acc-1", recipientId: "r-1", message: "hello" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(mockSendMessage).toHaveBeenCalled();
      expect(mockCreateNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          userId: "user-1",
          type: "dm_sent",
        }),
      );
    });

    it("tracks usage for send action", async () => {
      stubIgAccount();
      mockSendMessage.mockResolvedValue({
        success: true,
        messageId: "msg-sent-1",
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("send", { accountId: "acc-1", recipientId: "r-1", message: "hello" }),
        res,
        TEST_USER,
      );
      expect(mockTrackUsage).toHaveBeenCalledWith("user-1", "instagram.messages.send");
    });

    it("validates message max length (1000 chars)", async () => {
      const res = mockRes();
      const longMessage = "x".repeat(1001);
      await invokeHandler(
        makeReq("send", { accountId: "acc-1", recipientId: "r-1", message: longMessage }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });
  });

  // =========================================================================
  // Send Media
  // =========================================================================

  describe("send-media", () => {
    it("returns 400 for invalid mediaUrl", async () => {
      const res = mockRes();
      await invokeHandler(
        makeReq("send-media", {
          accountId: "acc-1",
          recipientId: "r-1",
          mediaUrl: "not-a-url",
          mediaType: "image",
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("sends media message on success", async () => {
      stubIgAccount();
      mockSendMediaMessage.mockResolvedValue({
        success: true,
        messageId: "media-msg-1",
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("send-media", {
          accountId: "acc-1",
          recipientId: "r-1",
          mediaUrl: "https://example.com/img.jpg",
          mediaType: "image",
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
    });
  });

  // =========================================================================
  // Sender Action (typing indicator)
  // =========================================================================

  describe("sender-action", () => {
    it("sends typing indicator on success", async () => {
      stubIgAccount();
      mockSendSenderAction.mockResolvedValue({ success: true });

      const res = mockRes();
      await invokeHandler(
        makeReq("sender-action", {
          accountId: "acc-1",
          recipientId: "r-1",
          action: "typing_on",
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
    });
  });

  // =========================================================================
  // Send Images (multi-image)
  // =========================================================================

  describe("send-images", () => {
    it("returns 400 for empty imageUrls array", async () => {
      const res = mockRes();
      await invokeHandler(
        makeReq("send-images", {
          accountId: "acc-1",
          recipientId: "r-1",
          imageUrls: [],
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns 400 when imageUrls exceeds 10", async () => {
      const res = mockRes();
      const urls = Array.from({ length: 11 }, (_, i) => `https://example.com/img${i}.jpg`);
      await invokeHandler(
        makeReq("send-images", {
          accountId: "acc-1",
          recipientId: "r-1",
          imageUrls: urls,
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("sends multiple images on success", async () => {
      stubIgAccount();
      mockSendMultiImageMessage.mockResolvedValue({
        success: true,
        messageId: "multi-img-1",
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("send-images", {
          accountId: "acc-1",
          recipientId: "r-1",
          imageUrls: ["https://example.com/a.jpg", "https://example.com/b.jpg"],
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
    });
  });

  // =========================================================================
  // Reaction
  // =========================================================================

  describe("reaction", () => {
    it("sends reaction on success", async () => {
      stubIgAccount();
      mockSendMessageReaction.mockResolvedValue({ success: true });

      const res = mockRes();
      await invokeHandler(
        makeReq("reaction", {
          accountId: "acc-1",
          recipientId: "r-1",
          messageId: "msg-1",
          reaction: "love",
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
    });

    it("supports nullable reaction (remove reaction)", async () => {
      stubIgAccount();
      mockSendMessageReaction.mockResolvedValue({ success: true });

      const res = mockRes();
      await invokeHandler(
        makeReq("reaction", {
          accountId: "acc-1",
          recipientId: "r-1",
          messageId: "msg-1",
          reaction: null,
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
    });
  });

  // =========================================================================
  // Share Post
  // =========================================================================

  describe("share-post", () => {
    it("shares post via DM on success", async () => {
      stubIgAccount();
      mockSendPostShare.mockResolvedValue({
        success: true,
        messageId: "share-msg-1",
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("share-post", {
          accountId: "acc-1",
          recipientId: "r-1",
          postId: "post-1",
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
    });
  });

  // =========================================================================
  // Heart Sticker
  // =========================================================================

  describe("heart-sticker", () => {
    it("sends heart sticker on success", async () => {
      stubIgAccount();
      mockSendHeartSticker.mockResolvedValue({
        success: true,
        messageId: "heart-1",
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("heart-sticker", {
          accountId: "acc-1",
          recipientId: "r-1",
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
    });
  });

  // =========================================================================
  // Sync Inbox
  // =========================================================================

  describe("sync-inbox", () => {
    it("returns 400 when accountId missing", async () => {
      const res = mockRes();
      await invokeHandler(makeReq("sync-inbox", {}), res, TEST_USER);
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("syncs conversations and messages to local DB", async () => {
      stubIgAccount();
      mockGetConversations.mockResolvedValue({
        success: true,
        conversations: [
          {
            id: "conv-1",
            participants: { data: [{ id: "p1", username: "user_a" }] },
            messages: { data: [{ id: "msg-1", message: "hi", created_time: "2026-01-01T00:00:00Z" }] },
            updated_time: "2026-01-01T00:00:00Z",
          },
        ],
        paging: { cursors: { after: null } },
      });
      mockGetConversationMessages.mockResolvedValue({
        success: true,
        messages: [
          {
            id: "msg-1",
            message: "hello",
            from: { id: "p1", username: "user_a" },
            created_time: "2026-01-01T00:00:00Z",
          },
        ],
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("sync-inbox", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(res.json).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({
            synced: true,
            conversations: 1,
            messages: 1,
          }),
        }),
      );
    });
  });

  // =========================================================================
  // Button Template
  // =========================================================================

  describe("button-template", () => {
    it("tracks usage", async () => {
      stubIgAccount();
      mockSendButtonTemplate.mockResolvedValue({
        success: true,
        messageId: "btn-1",
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("button-template", {
          accountId: "acc-1",
          recipientId: "r-1",
          text: "Pick one",
          buttons: [{ type: "postback", title: "Option A", payload: "opt_a" }],
        }),
        res,
        TEST_USER,
      );
      expect(mockTrackUsage).toHaveBeenCalledWith(
        "user-1",
        "instagram.messages.buttonTemplate",
      );
      expect(res.status).toHaveBeenCalledWith(200);
    });

    it("validates max 3 buttons", async () => {
      const res = mockRes();
      await invokeHandler(
        makeReq("button-template", {
          accountId: "acc-1",
          recipientId: "r-1",
          text: "Pick",
          buttons: [
            { type: "postback", title: "A", payload: "a" },
            { type: "postback", title: "B", payload: "b" },
            { type: "postback", title: "C", payload: "c" },
            { type: "postback", title: "D", payload: "d" },
          ],
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });
  });

  // =========================================================================
  // Quick Replies
  // =========================================================================

  describe("quick-replies", () => {
    it("returns 400 when quickReplies exceeds 13", async () => {
      const res = mockRes();
      const replies = Array.from({ length: 14 }, (_, i) => ({
        content_type: "text",
        title: `opt${i}`,
        payload: `p${i}`,
      }));
      await invokeHandler(
        makeReq("quick-replies", {
          accountId: "acc-1",
          recipientId: "r-1",
          text: "Choose",
          quickReplies: replies,
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });
  });

  // =========================================================================
  // Generic Template
  // =========================================================================

  describe("generic-template", () => {
    it("returns 400 when elements exceed 10", async () => {
      const res = mockRes();
      const elements = Array.from({ length: 11 }, (_, i) => ({
        title: `Element ${i}`,
      }));
      await invokeHandler(
        makeReq("generic-template", {
          accountId: "acc-1",
          recipientId: "r-1",
          elements,
        }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });
  });

  // =========================================================================
  // User Profile
  // =========================================================================

  describe("user-profile", () => {
    it("returns user profile on success", async () => {
      stubIgAccount();
      mockGetUserProfile.mockResolvedValue({
        success: true,
        profile: { name: "Test User", profile_pic: "https://example.com/pic.jpg" },
      });

      const res = mockRes();
      await invokeHandler(
        makeReq("user-profile", { accountId: "acc-1", igsid: "igsid-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(200);
      expect(res.json).toHaveBeenCalledWith(
        expect.objectContaining({
          data: expect.objectContaining({
            profile: expect.objectContaining({ name: "Test User" }),
          }),
        }),
      );
    });

    it("returns 400 when igsid missing", async () => {
      const res = mockRes();
      await invokeHandler(
        makeReq("user-profile", { accountId: "acc-1" }),
        res,
        TEST_USER,
      );
      expect(res.status).toHaveBeenCalledWith(400);
    });
  });
});
