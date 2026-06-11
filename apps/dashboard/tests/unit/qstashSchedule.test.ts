/**
 * Tests for api/_lib/qstashSchedule.ts
 *
 * Validates QStash dispatch utilities: post publishing, engagement fetching,
 * post-publish syncs, cross-reply dispatch, reply harvest, and cancellation.
 * All functions are fire-and-forget (never throw).
 */

import { describe, it, expect, beforeEach, vi } from "vitest";

// Mock logger
vi.mock("../../api/_lib/logger.js", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

// Mock QStash client
const mockPublishJSON = vi.fn().mockResolvedValue({ messageId: "msg-123" });
const mockMessagesDelete = vi.fn().mockResolvedValue(undefined);

vi.mock("../../api/_lib/qstash.js", () => ({
  getQStashClient: () => ({
    publishJSON: mockPublishJSON,
    messages: { delete: mockMessagesDelete },
  }),
}));

// Mock QStash defaults
vi.mock("../../api/_lib/qstashDefaults.js", () => ({
  getRequiredAppBaseUrl: () => "https://juno33.com",
  RETRIES: { CRITICAL: 3, STANDARD: 2, LOW: 1 },
  getFailureCallbackUrl: () => "https://juno33.com/api/qstash-failure",
}));

// Mock Supabase
const mockPostData: Record<string, unknown> = {};
const mockSupabaseUpdate = vi.fn().mockReturnValue({
  eq: vi.fn().mockResolvedValue({ error: null }),
});

const mockSupabase = {
  from: vi.fn().mockImplementation((table: string) => {
    if (table === "posts") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: mockPostData,
              error: null,
            }),
          }),
        }),
        update: mockSupabaseUpdate,
      };
    }
    return { select: vi.fn().mockReturnThis() };
  }),
};

vi.mock("../../api/_lib/supabase.js", () => ({
  getSupabase: () => mockSupabase,
}));

import {
  dispatchPostPublish,
  dispatchEngagementFetch,
  schedulePostPublishSyncs,
  dispatchCrossReply,
  dispatchReplyHarvest,
  cancelPostPublish,
} from "@/api/_lib/qstashSchedule";

describe("qstashSchedule", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.keys(mockPostData).forEach((k) => delete mockPostData[k]);
  });

  // ============================================================
  // dispatchPostPublish
  // ============================================================
  describe("dispatchPostPublish()", () => {
    it("publishes to QStash with correct URL and notBefore", async () => {
      const scheduledFor = new Date("2026-04-15T10:00:00Z");
      const result = await dispatchPostPublish("post-1", scheduledFor);

      expect(result).toBe("msg-123");
      expect(mockPublishJSON).toHaveBeenCalledWith(
        expect.objectContaining({
          url: "https://juno33.com/api/scheduled-post-publish",
          body: expect.objectContaining({ postId: "post-1" }),
          notBefore: Math.floor(scheduledFor.getTime() / 1000),
          retries: 3,
          deduplicationId: `post-post-1-${Math.floor(scheduledFor.getTime() / 1000)}`,
        })
      );
    });

    it("stores messageId in post metadata", async () => {
      mockPostData.metadata = { existing: "value" };
      await dispatchPostPublish("post-1", new Date());

      expect(mockSupabaseUpdate).toHaveBeenCalledWith(
        expect.objectContaining({
          metadata: expect.objectContaining({
            existing: "value",
            qstash_message_id: "msg-123",
          }),
        })
      );
    });

    it("returns null on QStash failure without throwing", async () => {
      mockPublishJSON.mockRejectedValueOnce(new Error("QStash down"));

      const result = await dispatchPostPublish("post-1", new Date());
      expect(result).toBeNull();
    });
  });

  // ============================================================
  // dispatchEngagementFetch
  // ============================================================
  describe("dispatchEngagementFetch()", () => {
    it("dispatches with correct delay and dedup ID", async () => {
      await dispatchEngagementFetch("post-1", "threads-123", 3600);

      expect(mockPublishJSON).toHaveBeenCalledWith(
        expect.objectContaining({
          url: "https://juno33.com/api/sync?action=post-engagement",
          body: { postId: "post-1", threadsPostId: "threads-123" },
          delay: 3600,
          retries: 2,
          deduplicationId: "engagement-post-1-3600",
        })
      );
    });

    it("does not throw on failure", async () => {
      mockPublishJSON.mockRejectedValueOnce(new Error("Network error"));
      await expect(
        dispatchEngagementFetch("post-1", "t-1", 3600)
      ).resolves.toBeUndefined();
    });
  });

  // ============================================================
  // schedulePostPublishSyncs
  // ============================================================
  describe("schedulePostPublishSyncs()", () => {
    it("schedules 3 syncs at 1h, 6h, 24h for threads", async () => {
      await schedulePostPublishSyncs("post-1", "acc-1", "user-1", "threads");

      expect(mockPublishJSON).toHaveBeenCalledTimes(3);

      const delays = mockPublishJSON.mock.calls.map((c: any) => c[0].delay);
      expect(delays).toContain(3600);
      expect(delays).toContain(21600);
      expect(delays).toContain(86400);
    });

    it("uses threads sync URL for threads platform", async () => {
      await schedulePostPublishSyncs("post-1", "acc-1", "user-1", "threads");

      expect(mockPublishJSON.mock.calls[0][0].url).toContain("/api/sync/threads-account");
    });

    it("uses instagram sync URL for instagram platform", async () => {
      await schedulePostPublishSyncs("post-1", "acc-1", "user-1", "instagram");

      expect(mockPublishJSON.mock.calls[0][0].url).toContain("/api/sync/ig-account");
    });

    it("includes userId in body when provided", async () => {
      await schedulePostPublishSyncs("post-1", "acc-1", "user-1", "threads");

      expect(mockPublishJSON.mock.calls[0][0].body).toHaveProperty("userId", "user-1");
    });

    it("omits userId when undefined", async () => {
      await schedulePostPublishSyncs("post-1", "acc-1", undefined, "threads");

      expect(mockPublishJSON.mock.calls[0][0].body).not.toHaveProperty("userId");
    });

    it("does not throw on failure", async () => {
      mockPublishJSON.mockRejectedValueOnce(new Error("QStash error"));
      await expect(
        schedulePostPublishSyncs("post-1", "acc-1", "user-1", "threads")
      ).resolves.toBeUndefined();
    });
  });

  // ============================================================
  // dispatchCrossReply
  // ============================================================
  describe("dispatchCrossReply()", () => {
    it("dispatches to cross-reply-publish endpoint", async () => {
      const payload = {
        queueItemId: "qi-1",
        workspaceId: "ws-1",
        groupId: "g-1",
        ownerId: "u-1",
        targetAccountId: "acc-2",
        targetThreadsPostId: "tp-1",
        postContent: "test content",
      };

      await dispatchCrossReply(payload);

      expect(mockPublishJSON).toHaveBeenCalledWith(
        expect.objectContaining({
          url: "https://juno33.com/api/cross-reply-publish",
          body: payload,
          retries: 1,
          deduplicationId: "cross-reply-qi-1",
        })
      );
    });

    it("uses delay between 30-60 seconds", async () => {
      await dispatchCrossReply({
        queueItemId: "qi-1",
        workspaceId: "ws-1",
        groupId: "g-1",
        ownerId: "u-1",
        targetAccountId: "acc-2",
        targetThreadsPostId: "tp-1",
        postContent: "test",
      });

      const delay = mockPublishJSON.mock.calls[0][0].delay;
      expect(delay).toBeGreaterThanOrEqual(30);
      expect(delay).toBeLessThanOrEqual(60);
    });
  });

  // ============================================================
  // dispatchReplyHarvest
  // ============================================================
  describe("dispatchReplyHarvest()", () => {
    it("dispatches with 15-minute delay", async () => {
      await dispatchReplyHarvest({
        queueItemId: "qi-1",
        workspaceId: "ws-1",
        groupId: "g-1",
        ownerId: "u-1",
        accountId: "acc-1",
        postId: "post-1",
      });

      expect(mockPublishJSON).toHaveBeenCalledWith(
        expect.objectContaining({
          url: "https://juno33.com/api/auto-reply-harvest",
          delay: 900,
          retries: 1,
        })
      );
    });

    it("defaults sourceTable to auto_post_queue", async () => {
      await dispatchReplyHarvest({
        queueItemId: "qi-1",
        workspaceId: "ws-1",
        groupId: "g-1",
        ownerId: "u-1",
        accountId: "acc-1",
        postId: "post-1",
      });

      expect(mockPublishJSON.mock.calls[0][0].body.sourceTable).toBe("auto_post_queue");
    });

    it("uses provided sourceTable", async () => {
      await dispatchReplyHarvest({
        queueItemId: "qi-1",
        workspaceId: "ws-1",
        groupId: "g-1",
        ownerId: "u-1",
        accountId: "acc-1",
        postId: "post-1",
        sourceTable: "posts",
      });

      expect(mockPublishJSON.mock.calls[0][0].body.sourceTable).toBe("posts");
      expect(mockPublishJSON.mock.calls[0][0].deduplicationId).toBe("reply-harvest-posts-qi-1");
    });
  });

  // ============================================================
  // cancelPostPublish
  // ============================================================
  describe("cancelPostPublish()", () => {
    it("deletes QStash message and clears metadata", async () => {
      mockPostData.metadata = { qstash_message_id: "msg-abc", other: "val" };

      await cancelPostPublish("post-1");

      expect(mockMessagesDelete).toHaveBeenCalledWith("msg-abc");
      expect(mockSupabaseUpdate).toHaveBeenCalledWith(
        expect.objectContaining({
          metadata: expect.not.objectContaining({
            qstash_message_id: expect.anything(),
          }),
        })
      );
    });

    it("does nothing when post has no qstash_message_id", async () => {
      mockPostData.metadata = { something: "else" };

      await cancelPostPublish("post-1");

      expect(mockMessagesDelete).not.toHaveBeenCalled();
    });

    it("does not throw when QStash delete fails", async () => {
      mockPostData.metadata = { qstash_message_id: "msg-expired" };
      mockMessagesDelete.mockRejectedValueOnce(new Error("Already fired"));

      await expect(cancelPostPublish("post-1")).resolves.toBeUndefined();
    });
  });
});
