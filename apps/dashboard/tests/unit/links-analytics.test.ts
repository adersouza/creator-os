/**
 * Unit tests for Links getAnalytics handler
 * (api/_lib/handlers/links/getAnalytics.ts)
 *
 * Covers: missing pageId, page ownership, no clicks data, happy path
 * with aggregation (source, device, crawler filtering), pagination,
 * custom days parameter, DB error handling.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock()
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/apiResponse.js", () => ({
  apiError: (res: any, status: number, msg: string, opts?: any) =>
    res.status(status).json({ error: msg, ...opts }),
  apiSuccess: (res: any, data?: unknown) =>
    res.status(200).json({ success: true, ...(data as any) }),
}));

vi.mock("@/api/_lib/supabase.js", () => ({
  getSupabase: () => ({ from: mockFrom }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { handleGetAnalytics } from "@/api/_lib/handlers/links/getAnalytics";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TEST_USER_ID = "user-1";

function makeReq(query: Record<string, string> = {}) {
  return { method: "GET", query, body: {}, headers: {} };
}

/** Mock the page ownership check and click data query */
function setupMocks(overrides: {
  page?: { id: string; view_count: number } | null;
  clicks?: Array<{
    source_app: string | null;
    device_type: string | null;
    is_crawler: boolean;
  }>;
  clicksError?: any;
} = {}) {
  const pageResult = {
    data: overrides.page !== undefined ? overrides.page : { id: "page-1", view_count: 42 },
    error: null,
  };

  const clicksResult = {
    data: overrides.clicks ?? [],
    error: overrides.clicksError ?? null,
  };

  mockFrom.mockImplementation((table: string) => {
    if (table === "link_pages") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              maybeSingle: vi.fn().mockResolvedValue(pageResult),
            }),
          }),
        }),
      };
    }
    if (table === "link_clicks") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            gte: vi.fn().mockReturnValue({
              range: vi.fn().mockResolvedValue(clicksResult),
            }),
          }),
        }),
      };
    }
    return { select: vi.fn().mockReturnThis() };
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("handleGetAnalytics", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Missing pageId ────────────────────────────────────────────────────────

  it("returns 400 when pageId is missing", async () => {
    const res = mockRes();
    await handleGetAnalytics(makeReq({}) as any, res as any, TEST_USER_ID);
    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: expect.stringContaining("pageId") }),
    );
  });

  // ── Page ownership ────────────────────────────────────────────────────────

  it("returns 404 when page not found (wrong owner)", async () => {
    setupMocks({ page: null });
    const res = mockRes();
    await handleGetAnalytics(
      makeReq({ pageId: "nonexistent" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(404);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: "Page not found" }),
    );
  });

  // ── No clicks ─────────────────────────────────────────────────────────────

  it("returns zero counts when no click data exists", async () => {
    setupMocks({ clicks: [] });
    const res = mockRes();
    await handleGetAnalytics(
      makeReq({ pageId: "page-1" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(200);
    const call = res.json.mock.calls[0][0];
    expect(call.totalClicks).toBe(0);
    expect(call.crawlerClicks).toBe(0);
    expect(call.pageViews).toBe(42);
  });

  // ── Happy path with aggregation ───────────────────────────────────────────

  it("aggregates clicks by source and device, excluding crawlers", async () => {
    setupMocks({
      clicks: [
        { source_app: "instagram", device_type: "mobile", is_crawler: false },
        { source_app: "instagram", device_type: "mobile", is_crawler: false },
        { source_app: "twitter", device_type: "desktop", is_crawler: false },
        { source_app: null, device_type: null, is_crawler: false },
        { source_app: "googlebot", device_type: "desktop", is_crawler: true },
        { source_app: "bingbot", device_type: "desktop", is_crawler: true },
      ],
    });

    const res = mockRes();
    await handleGetAnalytics(
      makeReq({ pageId: "page-1" }) as any,
      res as any,
      TEST_USER_ID,
    );

    expect(res.status).toHaveBeenCalledWith(200);
    const call = res.json.mock.calls[0][0];
    expect(call.totalClicks).toBe(4); // 6 total - 2 crawlers
    expect(call.crawlerClicks).toBe(2);
    expect(call.bySource).toEqual({
      instagram: 2,
      twitter: 1,
      direct: 1,
    });
    expect(call.byDevice).toEqual({
      mobile: 2,
      desktop: 1,
      unknown: 1,
    });
  });

  // ── Default days parameter ────────────────────────────────────────────────

  it("defaults to 30 days when days param not specified", async () => {
    setupMocks({ clicks: [] });
    const res = mockRes();
    await handleGetAnalytics(
      makeReq({ pageId: "page-1" }) as any,
      res as any,
      TEST_USER_ID,
    );
    const call = res.json.mock.calls[0][0];
    expect(call.period).toBe("30 days");
  });

  it("uses custom days parameter", async () => {
    setupMocks({ clicks: [] });
    const res = mockRes();
    await handleGetAnalytics(
      makeReq({ pageId: "page-1", days: "7" }) as any,
      res as any,
      TEST_USER_ID,
    );
    const call = res.json.mock.calls[0][0];
    expect(call.period).toBe("7 days");
  });

  it("falls back to 30 for invalid days param", async () => {
    setupMocks({ clicks: [] });
    const res = mockRes();
    await handleGetAnalytics(
      makeReq({ pageId: "page-1", days: "abc" }) as any,
      res as any,
      TEST_USER_ID,
    );
    const call = res.json.mock.calls[0][0];
    expect(call.period).toBe("30 days");
  });

  // ── DB error ──────────────────────────────────────────────────────────────

  it("returns 500 on DB query error for clicks", async () => {
    setupMocks({ clicksError: { message: "connection error" } });
    const res = mockRes();
    await handleGetAnalytics(
      makeReq({ pageId: "page-1" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(500);
  });

  // ── Page view count ───────────────────────────────────────────────────────

  it("returns 0 pageViews when view_count is null", async () => {
    setupMocks({
      page: { id: "page-1", view_count: null as any },
      clicks: [],
    });
    const res = mockRes();
    await handleGetAnalytics(
      makeReq({ pageId: "page-1" }) as any,
      res as any,
      TEST_USER_ID,
    );
    const call = res.json.mock.calls[0][0];
    expect(call.pageViews).toBe(0);
  });

  // ── All crawlers ──────────────────────────────────────────────────────────

  it("returns 0 totalClicks when all clicks are crawlers", async () => {
    setupMocks({
      clicks: [
        { source_app: "googlebot", device_type: "desktop", is_crawler: true },
        { source_app: "bingbot", device_type: "desktop", is_crawler: true },
      ],
    });
    const res = mockRes();
    await handleGetAnalytics(
      makeReq({ pageId: "page-1" }) as any,
      res as any,
      TEST_USER_ID,
    );
    const call = res.json.mock.calls[0][0];
    expect(call.totalClicks).toBe(0);
    expect(call.crawlerClicks).toBe(2);
    expect(call.bySource).toEqual({});
    expect(call.byDevice).toEqual({});
  });
});
