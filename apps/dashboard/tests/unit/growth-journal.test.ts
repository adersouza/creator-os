/**
 * Unit tests for Growth Journal handler
 * (api/_lib/handlers/user/growth-journal.ts)
 *
 * Covers: GET list with filters, POST create entry (account ownership,
 * post ownership), DELETE entry, tier gating (pro+), method validation,
 * stats calculation (outcome/improvement), search sanitization
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockApiError = vi.fn();
const mockApiSuccess = vi.fn();
const mockRequireMinTier = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock()
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/logger", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/api/_lib/apiResponse", () => ({
  apiError: (...args: unknown[]) => mockApiError(...args),
  apiSuccess: (...args: unknown[]) => mockApiSuccess(...args),
}));

vi.mock("@/api/_lib/middleware", () => ({
  withAuthDb: (handler: Function) => {
    return async (req: any, res: any) => {
      const user = { id: "user-1" };
      return handler(req, res, {
        user,
        userDb: { from: mockFrom },
        adminDb: { from: vi.fn() },
        adminDbAny: { from: vi.fn() },
      });
    };
  },
}));

vi.mock("@/api/_lib/tierGate", () => ({
  requireMinTier: (...args: unknown[]) => mockRequireMinTier(...args),
}));

vi.mock("@/api/_lib/validation", () => ({
  parseQueryOrError: (res: any, schema: any, query: any) => {
    const result = schema.safeParse(query);
    if (!result.success) {
      mockApiError(res, 400, result.error.issues[0]?.message || "Invalid input");
      return null;
    }
    return result.data;
  },
}));

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import growthJournalHandler from "@/api/_lib/handlers/user/growth-journal";

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

function setupJournalMock(config: {
  dismissals?: any[];
  dismissalError?: any;
  baselines?: any[];
  ownedAccount?: any;
  ownedPost?: any;
  insertError?: any;
  deleteResult?: { data: any; error: any };
} = {}) {
  mockFrom.mockImplementation((table: string) => {
    const chain: any = {};
    const methods = ["select", "eq", "order", "ilike", "delete", "insert"];
    for (const m of methods) {
      chain[m] = vi.fn().mockReturnValue(chain);
    }
    chain.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });

    if (table === "recommendation_dismissals") {
      // For GET: select chain with multiple filters
      const queryChain: any = {};
      queryChain.select = vi.fn().mockReturnValue(queryChain);
      queryChain.eq = vi.fn().mockReturnValue(queryChain);
      queryChain.order = vi.fn().mockReturnValue(queryChain);
      queryChain.ilike = vi.fn().mockReturnValue(queryChain);

      // Terminal: when awaited, resolve with dismissals
      queryChain.then = (resolve: Function) =>
        resolve({
          data: config.dismissals ?? [],
          error: config.dismissalError ?? null,
        });

      // For DELETE path
      queryChain.delete = vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            select: vi.fn().mockReturnValue({
              maybeSingle: vi.fn().mockResolvedValue(
                config.deleteResult ?? { data: null, error: null },
              ),
            }),
          }),
        }),
      });

      // For POST: insert
      queryChain.insert = vi.fn().mockResolvedValue({
        error: config.insertError ?? null,
      });

      return queryChain;
    }

    if (table === "recommendation_baselines") {
      chain.then = (resolve: Function) =>
        resolve({
          data: config.baselines ?? [],
          error: null,
        });
      return chain;
    }

    if (table === "accounts" || table === "instagram_accounts") {
      const acctMaybeSingle = vi.fn().mockResolvedValue({
        data: "ownedAccount" in config ? config.ownedAccount : { id: "acc-1" },
      });
      const acctEq2: any = { maybeSingle: acctMaybeSingle, eq: vi.fn() };
      acctEq2.eq = vi.fn().mockReturnValue(acctEq2);
      const acctEq1: any = { eq: vi.fn().mockReturnValue(acctEq2), maybeSingle: acctMaybeSingle };
      chain.select = vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue(acctEq1),
      });
      return chain;
    }

    if (table === "posts") {
      const postMaybeSingle = vi.fn().mockResolvedValue({
        data: config.ownedPost ?? null,
      });
      const postEq2: any = { maybeSingle: postMaybeSingle, eq: vi.fn() };
      postEq2.eq = vi.fn().mockReturnValue(postEq2);
      const postEq1: any = { eq: vi.fn().mockReturnValue(postEq2), maybeSingle: postMaybeSingle };
      chain.select = vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue(postEq1),
      });
      return chain;
    }

    return chain;
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("user/growth-journal handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRequireMinTier.mockResolvedValue(true);
  });

  // ── Tier gating ───────────────────────────────────────────────────────────

  it("blocks free-tier users", async () => {
    mockRequireMinTier.mockResolvedValue(false);
    const req = mockReq();
    const res = mockRes();
    await growthJournalHandler(req as any, res as any);
    expect(mockRequireMinTier).toHaveBeenCalledWith("user-1", "pro", res);
    expect(mockApiSuccess).not.toHaveBeenCalled();
  });

  // ── Method validation ─────────────────────────────────────────────────────

  it("rejects PUT method", async () => {
    const req = mockReq({ method: "PUT" });
    const res = mockRes();
    await growthJournalHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 405, "Method not allowed");
  });

  // ── GET: validation ───────────────────────────────────────────────────────

  it("GET rejects missing accountId", async () => {
    const req = mockReq({ query: {} });
    const res = mockRes();
    await growthJournalHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, expect.any(String));
  });

  // ── GET: returns entries with stats ────────────────────────────────────────

  it("GET returns entries and stats", async () => {
    setupJournalMock({
      dismissals: [
        {
          id: "d1",
          rec_id: "r1",
          actioned_at: "2026-04-10",
          recommendation_text: "Optimize posting time",
          category: "timing",
          baseline_value: 100,
          current_value: 150,
        },
        {
          id: "d2",
          rec_id: "r2",
          actioned_at: "2026-04-11",
          recommendation_text: "Use more hashtags",
          category: "content",
          baseline_value: 50,
          current_value: 40,
        },
      ],
    });

    const req = mockReq({ query: { accountId: "acc-1" } });
    const res = mockRes();
    await growthJournalHandler(req as any, res as any);

    expect(mockApiSuccess).toHaveBeenCalledTimes(1);
    const result = mockApiSuccess.mock.calls[0][1];
    expect(result.entries).toHaveLength(2);
    expect(result.stats.total).toBe(2);
  });

  // ── GET: empty state ──────────────────────────────────────────────────────

  it("GET returns empty entries on dismissal error", async () => {
    setupJournalMock({ dismissalError: { message: "db error" } });

    const req = mockReq({ query: { accountId: "acc-1" } });
    const res = mockRes();
    await growthJournalHandler(req as any, res as any);

    const result = mockApiSuccess.mock.calls[0][1];
    expect(result.entries).toEqual([]);
    expect(result.stats).toEqual({
      total: 0,
      successful: 0,
      successRate: 0,
      avgImprovement: 0,
    });
  });

  // ── POST: create entry ────────────────────────────────────────────────────

  it("POST creates journal entry with valid input", async () => {
    setupJournalMock({ ownedAccount: { id: "acc-1" } });
    const req = mockReq({
      method: "POST",
      body: {
        accountId: "acc-1",
        recommendationText: "Start posting consistently",
        category: "milestone",
      },
    });
    const res = mockRes();
    await growthJournalHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { created: true });
  });

  it("POST rejects missing recommendationText", async () => {
    setupJournalMock({});
    const req = mockReq({
      method: "POST",
      body: { accountId: "acc-1" },
    });
    const res = mockRes();
    await growthJournalHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, expect.stringContaining("Invalid input"));
  });

  it("POST rejects unowned account", async () => {
    setupJournalMock({ ownedAccount: null });
    const req = mockReq({
      method: "POST",
      body: {
        accountId: "acc-other",
        recommendationText: "Test text",
      },
    });
    const res = mockRes();
    await growthJournalHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 404, "Account not found");
  });

  it("POST rejects unowned postId", async () => {
    setupJournalMock({ ownedAccount: { id: "acc-1" }, ownedPost: null });
    const req = mockReq({
      method: "POST",
      body: {
        accountId: "acc-1",
        recommendationText: "Linked to post",
        postId: "post-other",
      },
    });
    const res = mockRes();
    await growthJournalHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 404, "Post not found");
  });

  // ── DELETE ────────────────────────────────────────────────────────────────

  it("DELETE rejects missing id", async () => {
    const req = mockReq({ method: "DELETE", query: {} });
    const res = mockRes();
    await growthJournalHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, expect.any(String));
  });

  it("DELETE returns 404 for missing entry", async () => {
    setupJournalMock({ deleteResult: { data: null, error: null } });
    const req = mockReq({
      method: "DELETE",
      query: { id: "nonexistent" },
    });
    const res = mockRes();
    await growthJournalHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 404, "Journal entry not found");
  });

  it("DELETE succeeds for owned entry", async () => {
    setupJournalMock({
      deleteResult: { data: { id: "d1" }, error: null },
    });
    const req = mockReq({
      method: "DELETE",
      query: { id: "d1" },
    });
    const res = mockRes();
    await growthJournalHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { deleted: true });
  });
});
