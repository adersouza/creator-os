/**
 * Unit tests for Agent Weekly State handler
 * (api/_lib/handlers/agent/weekly-state.ts)
 *
 * Covers: method validation, auth, parallel queries, data summarization,
 * approval tallying, agent log aggregation, error resilience
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockApiError = vi.fn();
const mockApiSuccess = vi.fn();
const mockGetAuthUserOrError = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock()
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/supabase", () => ({
  getSupabase: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/dbContext", () => ({
  createDbContext: (_req: unknown, user: { id: string }) => ({
    user,
    userDb: { from: mockFrom },
    adminDb: { from: mockFrom },
    adminDbAny: { from: mockFrom },
  }),
}));

vi.mock("@/api/_lib/logger", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/api/_lib/apiResponse", () => ({
  apiError: (...args: unknown[]) => mockApiError(...args),
  apiSuccess: (...args: unknown[]) => mockApiSuccess(...args),
  getAuthUserOrError: (...args: unknown[]) => mockGetAuthUserOrError(...args),
}));

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import handleWeeklyState from "@/api/_lib/handlers/agent/weekly-state";

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

function setupAllQueries(config: {
  agentPaused?: boolean;
  publishedPosts?: any[];
  publishedCount?: number;
  scheduledPosts?: any[];
  approvals?: any[];
  logEntries?: any[];
  totalPublished?: number;
}) {
  // Each call to db().from(table) in the handler triggers a query chain.
  // The handler calls Promise.all with 7 parallel queries.
  // We need mockFrom to return appropriate chains for each table.

  const makeChain = (resolvedValue: any) => {
    const chain: any = {};
    const methods = ["select", "eq", "or", "gte", "not", "order", "limit", "lt", "maybeSingle"];
    for (const m of methods) {
      if (m === "maybeSingle") {
        chain[m] = vi.fn().mockResolvedValue(resolvedValue);
      } else {
        chain[m] = vi.fn().mockReturnValue(chain);
      }
    }
    // Terminal resolution for when await is called on the chain directly
    chain.then = (resolve: Function) => resolve(resolvedValue);
    return chain;
  };

  let postsCallCount = 0;
  mockFrom.mockImplementation((table: string) => {
    if (table === "posts") {
      postsCallCount++;
      // First call: published posts preview (data query)
      // Second call: published count (head:true)
      // Third call: total published (head:true)
      // Fourth call: scheduled posts
      if (postsCallCount <= 1) {
        return makeChain({
          data: config.publishedPosts ?? [],
          error: null,
        });
      }
      if (postsCallCount === 2) {
        return makeChain({
          count: config.publishedCount ?? 0,
          data: null,
          error: null,
        });
      }
      if (postsCallCount === 3) {
        return makeChain({
          count: config.totalPublished ?? 0,
          data: null,
          error: null,
        });
      }
      // scheduled posts
      return makeChain({
        data: config.scheduledPosts ?? [],
        error: null,
      });
    }

    if (table === "agent_approvals") {
      return makeChain({
        data: config.approvals ?? [],
        error: null,
      });
    }

    if (table === "agent_actions") {
      return makeChain({
        data: config.logEntries ?? [],
        error: null,
      });
    }

    if (table === "profiles") {
      return makeChain({
        data: { agent_paused: config.agentPaused ?? false },
        error: null,
      });
    }

    return makeChain({ data: null, error: null });
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("agent/weekly-state handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetAuthUserOrError.mockResolvedValue({ id: "user-1" });
  });

  // ── Method validation ─────────────────────────────────────────────────────

  it("rejects non-GET methods", async () => {
    const req = mockReq({ method: "POST" });
    const res = mockRes();
    await handleWeeklyState(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 405, "Method not allowed");
  });

  // ── Auth ──────────────────────────────────────────────────────────────────

  it("returns early when auth fails", async () => {
    mockGetAuthUserOrError.mockResolvedValue(null);
    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await handleWeeklyState(req as any, res as any);
    expect(mockApiSuccess).not.toHaveBeenCalled();
  });

  // ── Happy path ────────────────────────────────────────────────────────────

  it("returns structured weekly state with all sections", async () => {
    setupAllQueries({
      agentPaused: false,
      publishedPosts: [
        {
          id: "p1",
          content: "Hello world post",
          account_id: "acc-1",
          instagram_account_id: null,
          platform: "threads",
          published_at: "2026-04-14T10:00:00Z",
          created_at: "2026-04-14T10:00:00Z",
        },
      ],
      publishedCount: 5,
      totalPublished: 100,
      scheduledPosts: [
        {
          id: "s1",
          content: "Upcoming post",
          account_id: "acc-1",
          instagram_account_id: null,
          platform: "threads",
          scheduled_for: "2026-04-16T09:00:00Z",
        },
      ],
      approvals: [
        { id: "a1", status: "pending", urgency: "medium", context: "Schedule 3 posts", created_at: "2026-04-14T00:00:00Z" },
        { id: "a2", status: "approved", urgency: "low", context: "Draft 2 posts", created_at: "2026-04-13T00:00:00Z" },
      ],
      logEntries: [
        { tool_name: "schedule_threads_post", success: true, duration_ms: 1200 },
        { tool_name: "schedule_threads_post", success: true, duration_ms: 800 },
        { tool_name: "get_posts", success: false, duration_ms: 500 },
      ],
    });

    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await handleWeeklyState(req as any, res as any);

    expect(mockApiSuccess).toHaveBeenCalledTimes(1);
    const data = mockApiSuccess.mock.calls[0][1];

    expect(data.agentPaused).toBe(false);
    expect(data.weekStart).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(data.generatedAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);

    // Posts section
    expect(data.postsThisWeek.published).toBe(5);
    expect(data.postsThisWeek.scheduled).toBe(1);
    expect(data.postsThisWeek.totalPublished).toBe(100);
    expect(data.postsThisWeek.nextScheduled).toBeTruthy();
    expect(data.postsThisWeek.nextScheduled.platform).toBe("threads");

    // Approvals section
    expect(data.approvals.pending).toBe(1);
    expect(data.approvals.approvedThisWeek).toBe(1);

    // Agent activity section
    expect(data.agentActivity.callsLast24h).toBe(3);
    expect(data.agentActivity.successRate).toBe(67);
    expect(data.agentActivity.topTools.length).toBe(2);
    expect(data.agentActivity.avgDurationMs).toBeGreaterThan(0);
  });

  // ── Empty state ───────────────────────────────────────────────────────────

  it("returns zero-state when no data exists", async () => {
    setupAllQueries({});
    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await handleWeeklyState(req as any, res as any);

    const data = mockApiSuccess.mock.calls[0][1];
    expect(data.postsThisWeek.published).toBe(0);
    expect(data.postsThisWeek.scheduled).toBe(0);
    expect(data.postsThisWeek.nextScheduled).toBeNull();
    expect(data.approvals.pending).toBe(0);
    expect(data.agentActivity.callsLast24h).toBe(0);
    expect(data.agentActivity.successRate).toBe(100); // default when no calls
    expect(data.agentActivity.avgDurationMs).toBe(0);
  });

  // ── Agent paused flag ─────────────────────────────────────────────────────

  it("reflects agentPaused = true", async () => {
    setupAllQueries({ agentPaused: true });
    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await handleWeeklyState(req as any, res as any);
    const data = mockApiSuccess.mock.calls[0][1];
    expect(data.agentPaused).toBe(true);
  });
});
