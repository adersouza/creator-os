/**
 * Unit tests for Inbox Mark Read handler
 * (api/_lib/handlers/inbox/mark-read.ts)
 *
 * Covers: method validation, messageId validation, all source types
 * (ig_comment, ig_mention, ig_dm, threads_reply, threads_mention, unknown),
 * ownership verification, durable read/unread, user_settings fallback
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockApiError = vi.fn();
const mockApiSuccess = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock()
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/supabase", () => ({
  getSupabase: () => ({ from: mockFrom }),
  getSupabaseAny: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/logger", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/api/_lib/apiResponse", () => ({
  apiError: (...args: unknown[]) => mockApiError(...args),
  apiSuccess: (...args: unknown[]) => mockApiSuccess(...args),
}));

vi.mock("@/api/_lib/middleware", () => ({
  withAuth: (handler: Function) => {
    return async (req: any, res: any) => {
      const user = { id: "user-1" };
      return handler(req, res, user);
    };
  },
  withAuthDb: (handler: Function) => {
    return async (req: any, res: any) => {
      const user = { id: "user-1" };
      const userDb = { from: mockFrom };
      return handler(req, res, { user, userDb });
    };
  },
}));

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import markReadHandler from "@/api/_lib/handlers/inbox/mark-read";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockReq(overrides: Record<string, unknown> = {}) {
  return {
    method: "POST",
    query: {},
    body: {},
    headers: {},
    ...overrides,
  };
}

function setupFromForSource(_source: string, config: {
	replyData?: any;
	postOwned?: boolean;
	existingReadIds?: string[];
} = {}) {
  mockFrom.mockImplementation((table: string) => {
    const chain: any = {};
    const methods = ["select", "eq", "update", "upsert", "in", "order", "limit", "delete"];
    for (const m of methods) {
      chain[m] = vi.fn().mockReturnValue(chain);
    }
    chain.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });

    if (table === "ig_mentions" || table === "mentions") {
      chain.update = vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockResolvedValue({ error: null }),
        }),
      });
      return chain;
    }

    if (table === "post_replies") {
      // For select("id, post_id").eq("id", id).maybeSingle()
      chain.select = vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({
            data: config.replyData ?? { id: "r1", post_id: "p1" },
          }),
        }),
      });
      chain.update = vi.fn().mockReturnValue({
        eq: vi.fn().mockResolvedValue({ error: null }),
      });
      return chain;
    }

    if (table === "ig_comments") {
      chain.select = vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({
            data: config.replyData ?? { id: "c1", post_id: "p1" },
          }),
        }),
      });
      chain.update = vi.fn().mockReturnValue({
        eq: vi.fn().mockResolvedValue({ error: null }),
      });
      return chain;
    }

    if (table === "inbox_dm_cache") {
      chain.update = vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockResolvedValue({ error: null }),
        }),
      });
      return chain;
    }

    if (table === "operator_tasks") {
      chain.update = vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockResolvedValue({ error: null }),
          }),
        }),
      });
      return chain;
    }

    if (table === "posts") {
      chain.select = vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: config.postOwned !== false ? { id: "p1" } : null,
            }),
          }),
        }),
      });
      return chain;
    }

    if (table === "user_settings") {
      chain.select = vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: config.existingReadIds
                ? { setting_value: config.existingReadIds }
                : null,
            }),
          }),
        }),
      });
      chain.upsert = vi.fn().mockResolvedValue({ error: null });
      return chain;
    }

    return chain;
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("inbox/mark-read handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Method validation ─────────────────────────────────────────────────────

  it("rejects non-POST methods", async () => {
    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await markReadHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 405, "Method not allowed");
  });

  // ── messageId validation ──────────────────────────────────────────────────

  it("rejects missing messageId", async () => {
    const req = mockReq({ body: {} });
    const res = mockRes();
    await markReadHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "messageId is required");
  });

  it("rejects non-string messageId", async () => {
    const req = mockReq({ body: { messageId: 123 } });
    const res = mockRes();
    await markReadHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "messageId is required");
  });

  // ── ig_mention source ─────────────────────────────────────────────────────

  it("marks ig_mention as read via ig_mentions table", async () => {
    setupFromForSource("ig_mention");
    const req = mockReq({ body: { messageId: "ig_mention_abc123" } });
    const res = mockRes();
    await markReadHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { success: true });
    expect(mockFrom).toHaveBeenCalledWith("ig_mentions");
  });

  // ── threads_mention source ────────────────────────────────────────────────

  it("marks threads_mention as read via mentions table", async () => {
    setupFromForSource("threads_mention");
    const req = mockReq({ body: { messageId: "threads_mention_xyz789" } });
    const res = mockRes();
    await markReadHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { success: true });
    expect(mockFrom).toHaveBeenCalledWith("mentions");
  });

  // ── threads_reply source ──────────────────────────────────────────────────

  it("marks threads_reply as read when post is owned", async () => {
    setupFromForSource("threads_reply", { postOwned: true });
    const req = mockReq({ body: { messageId: "threads_reply_r1" } });
    const res = mockRes();
    await markReadHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { success: true });
  });

  // ── ig_comment source ─────────────────────────────────────────────────────

  it("marks ig_comment as read after verifying post ownership", async () => {
    setupFromForSource("ig_comment", { postOwned: true });
    const req = mockReq({ body: { messageId: "ig_comment_c1" } });
    const res = mockRes();
    await markReadHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { success: true });
    expect(mockFrom).toHaveBeenCalledWith("ig_comments");
    expect(mockFrom).toHaveBeenCalledWith("operator_tasks");
  });

  it("marks ig_dm as read via inbox_dm_cache and resolves the operator task", async () => {
    setupFromForSource("ig_dm");
    const req = mockReq({ body: { messageId: "ig_dm_dm1" } });
    const res = mockRes();
    await markReadHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { success: true });
    expect(mockFrom).toHaveBeenCalledWith("inbox_dm_cache");
    expect(mockFrom).toHaveBeenCalledWith("operator_tasks");
  });

  it("can move a durable inbox item back to unread/open", async () => {
    setupFromForSource("ig_dm");
    const req = mockReq({ body: { messageId: "ig_dm_dm1", read: false } });
    const res = mockRes();
    await markReadHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { success: true });
    expect(mockFrom).toHaveBeenCalledWith("inbox_dm_cache");
    expect(mockFrom).toHaveBeenCalledWith("operator_tasks");
  });

  // ── Unknown source ────────────────────────────────────────────────────────

  it("unknown messageId format falls back to user_settings", async () => {
    setupFromForSource("unknown", { existingReadIds: [] });
    const req = mockReq({ body: { messageId: "some_random_id" } });
    const res = mockRes();
    await markReadHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { success: true });
    expect(mockFrom).toHaveBeenCalledWith("user_settings");
  });

  // ── Error handling ────────────────────────────────────────────────────────

  it("returns 500 on unexpected error", async () => {
    mockFrom.mockImplementation(() => {
      throw new Error("DB connection failed");
    });
    const req = mockReq({ body: { messageId: "ig_mention_xyz" } });
    const res = mockRes();
    await markReadHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 500, "Internal server error");
  });
});
