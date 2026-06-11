/**
 * Unit tests for Recap Generate handler
 * (api/_lib/handlers/recap/generate.ts)
 *
 * Covers: method validation, account_id validation, account ownership,
 * metric aggregation, best post selection, streak calculation,
 * headline generation, period formatting, error handling
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockApiError = vi.fn();
const mockApiSuccess = vi.fn();
const mockResolveAccount = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock()
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/supabase", () => ({
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
}));

vi.mock("@/api/_lib/resolveAccount", () => ({
  resolveAccount: (...args: unknown[]) => mockResolveAccount(...args),
}));

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import recapHandler from "@/api/_lib/handlers/recap/generate";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockReq(overrides: Record<string, unknown> = {}) {
  return {
    method: "GET",
    query: {},
    body: {},
    headers: {},
    ...overrides,
  };
}

function setupRecapMock(config: {
	posts?: any[];
	quickWinsCount?: number;
	followerSnapshots?: any[];
} = {}) {
	mockFrom.mockImplementation((table: string) => {
    const chain: any = {};
    const methods = [
      "select", "eq", "gte", "not", "order", "limit", "in",
    ];
    for (const m of methods) {
      chain[m] = vi.fn().mockReturnValue(chain);
    }

    if (table === "posts") {
      // Terminal: resolves with post data
      chain.limit = vi.fn().mockResolvedValue({
        data: config.posts ?? [],
        error: null,
      });
      return chain;
    }

    if (table === "quick_wins") {
      chain.select = vi.fn().mockResolvedValue({
        count: config.quickWinsCount ?? 0,
        error: null,
      });
      return chain;
    }

    if (table === "account_analytics" || table === "ig_account_analytics") {
      chain.limit = vi.fn().mockResolvedValue({
        data: config.followerSnapshots ?? [],
        error: null,
      });
      return chain;
    }

    // Fallback
    chain.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
    return chain;
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("recap/generate handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockResolveAccount.mockResolvedValue({
      username: "testaccount",
      platform: "threads",
    });
  });

  // ── Method validation ─────────────────────────────────────────────────────

  it("rejects non-GET methods", async () => {
    const req = mockReq({ method: "POST" });
    const res = mockRes();
    await recapHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 405, "Method not allowed");
  });

  // ── Input validation ──────────────────────────────────────────────────────

  it("requires account_id", async () => {
    const req = mockReq({ query: {} });
    const res = mockRes();
    await recapHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "account_id is required");
  });

  // ── Account ownership ─────────────────────────────────────────────────────

  it("rejects when account not found", async () => {
    mockResolveAccount.mockResolvedValue(null);
    const req = mockReq({ query: { account_id: "acc-unknown" } });
    const res = mockRes();
    await recapHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(
      res, 403, "Account not found or not authorized",
    );
  });

  // ── Happy path: basic recap ───────────────────────────────────────────────

  it("returns recap with posts data", async () => {
    const now = new Date();
    const yesterday = new Date(now.getTime() - 86400000);
    const twoDaysAgo = new Date(now.getTime() - 2 * 86400000);

    setupRecapMock({
      posts: [
        {
          id: "p1",
          content: "First post with lots of views",
          views: 5000,
          likes: 200,
          replies_count: 50,
          reposts: 30,
          saved: 10,
          published_at: yesterday.toISOString(),
        },
        {
          id: "p2",
          content: "Second post",
          views: 1000,
          likes: 50,
          replies_count: 10,
          reposts: 5,
          saved: 2,
          published_at: twoDaysAgo.toISOString(),
        },
      ],
    });

    const req = mockReq({ query: { account_id: "acc-1", period: "7d" } });
    const res = mockRes();
    await recapHandler(req as any, res as any);

    expect(mockApiSuccess).toHaveBeenCalledTimes(1);
    const data = mockApiSuccess.mock.calls[0][1].data;

    expect(data.accountHandle).toBe("testaccount");
    expect(data.platform).toBe("threads");
    expect(data.totalPosts).toBe(2);
    expect(data.totalViews).toBe(6000);
    expect(data.totalEngagement).toBe(357); // 200+50+30+10 + 50+10+5+2
    expect(data.bestPost).toBeTruthy();
    expect(data.bestPost.views).toBe(5000);
    expect(data.headline).toBeTruthy();
    expect(data.periodDays).toBe(7);
  });

  // ── Empty state ───────────────────────────────────────────────────────────

  it("returns zero-state recap when no posts", async () => {
    setupRecapMock({ posts: [] });

    const req = mockReq({ query: { account_id: "acc-1" } });
    const res = mockRes();
    await recapHandler(req as any, res as any);

    const data = mockApiSuccess.mock.calls[0][1].data;
    expect(data.totalPosts).toBe(0);
    expect(data.totalViews).toBe(0);
    expect(data.totalEngagement).toBe(0);
    expect(data.bestPost).toBeNull();
    expect(data.avgEngagementRate).toBe(0);
    expect(data.streak).toBe(0);
  });

  // ── Period handling ───────────────────────────────────────────────────────

  it("handles 30d period", async () => {
    setupRecapMock({ posts: [] });

    const req = mockReq({ query: { account_id: "acc-1", period: "30d" } });
    const res = mockRes();
    await recapHandler(req as any, res as any);

    const data = mockApiSuccess.mock.calls[0][1].data;
    expect(data.periodDays).toBe(30);
  });

  it("handles all period", async () => {
    setupRecapMock({ posts: [] });

    const req = mockReq({ query: { account_id: "acc-1", period: "all" } });
    const res = mockRes();
    await recapHandler(req as any, res as any);

    const data = mockApiSuccess.mock.calls[0][1].data;
    expect(data.periodDays).toBe(365);
  });

  it("defaults to 7d period", async () => {
    setupRecapMock({ posts: [] });

    const req = mockReq({ query: { account_id: "acc-1" } });
    const res = mockRes();
    await recapHandler(req as any, res as any);

    const data = mockApiSuccess.mock.calls[0][1].data;
    expect(data.periodDays).toBe(7);
  });

  // ── Streak calculation ────────────────────────────────────────────────────

  it("calculates posting streak from consecutive days", async () => {
    const now = new Date();
    const d1 = new Date(now.getTime() - 1 * 86400000);
    const d2 = new Date(now.getTime() - 2 * 86400000);
    const d3 = new Date(now.getTime() - 3 * 86400000);
    // Gap day (no post on day 4 ago)
    const d5 = new Date(now.getTime() - 5 * 86400000);

    setupRecapMock({
      posts: [
        { id: "p1", content: "a", views: 10, likes: 1, published_at: d1.toISOString() },
        { id: "p2", content: "b", views: 10, likes: 1, published_at: d2.toISOString() },
        { id: "p3", content: "c", views: 10, likes: 1, published_at: d3.toISOString() },
        { id: "p4", content: "d", views: 10, likes: 1, published_at: d5.toISOString() },
      ],
    });

    const req = mockReq({ query: { account_id: "acc-1" } });
    const res = mockRes();
    await recapHandler(req as any, res as any);

    const data = mockApiSuccess.mock.calls[0][1].data;
    expect(data.streak).toBe(3); // 3 consecutive days, then gap
  });

  // ── Error handling ────────────────────────────────────────────────────────

  it("returns 500 on unexpected error", async () => {
    mockResolveAccount.mockRejectedValue(new Error("Network error"));

    const req = mockReq({ query: { account_id: "acc-1" } });
    const res = mockRes();
    await recapHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 500, "Internal server error");
  });
});
