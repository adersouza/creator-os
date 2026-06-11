/**
 * Unit tests for Smart Link Analytics handler
 * (api/_lib/handlers/smart-links/analytics.ts)
 *
 * Covers: validation, ownership verification, range parsing,
 * RPC aggregation, estimated revenue calculation, and error paths.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockRpc = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock()
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/supabase.js", () => ({
  getSupabase: () => ({ from: mockFrom, rpc: mockRpc }),
  getSupabaseAny: () => ({ from: mockFrom, rpc: mockRpc }),
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
}));

vi.mock("@/api/_lib/handlers/smart-links/shared.js", async () => {
  const { z } = await import("zod");

  return {
    AnalyticsQuerySchema: z.object({
      linkId: z.string().min(1, "linkId is required"),
      range: z.enum(["7d", "30d", "90d"]).optional().default("7d"),
    }),
    db: () => ({ from: mockFrom }),
  };
});

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { handleAnalytics } from "@/api/_lib/handlers/smart-links/analytics";
const invokeHandleAnalytics = handleAnalytics as unknown as (req: any, res: any, userId: string) => Promise<void>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const USER_ID = "user-1";

function makeReq(query: Record<string, unknown> = {}) {
  return {
    method: "POST",
    query,
    body: {},
    headers: {},
  } as any;
}

function stubSmartLinkOwned(overrides: {
  click_count?: number;
  est_conversion_rate?: number | null;
  est_conversion_value?: number | null;
} = {}) {
  const linkBasic = {
    id: "link-1",
    click_count: overrides.click_count ?? 42,
  };
  const linkFull = {
    est_conversion_rate: overrides.est_conversion_rate ?? 0.05,
    est_conversion_value: overrides.est_conversion_value ?? 20,
  };

  let selectCallCount = 0;
  mockFrom.mockImplementation((table: string) => {
    if (table === "smart_links") {
      return {
        select: vi.fn().mockImplementation((_cols: string) => {
          selectCallCount++;
          // First call: ownership check (id, click_count)
          // Second call: est_conversion fields
          const data = selectCallCount <= 1 ? linkBasic : linkFull;
          return {
            eq: vi.fn().mockImplementation((_field: string, _val: string) => {
              return {
                eq: vi.fn().mockReturnValue({
                  maybeSingle: vi.fn().mockResolvedValue({
                    data,
                    error: null,
                  }),
                }),
                maybeSingle: vi.fn().mockResolvedValue({
                  data,
                  error: null,
                }),
              };
            }),
          };
        }),
      };
    }
    return {
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      gte: vi.fn().mockResolvedValue({ data: [], error: null }),
      maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
    };
  });
}

function stubSmartLinkNotOwned() {
  mockFrom.mockImplementation(() => ({
    select: vi.fn().mockReturnValue({
      eq: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
        }),
        maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
      }),
    }),
  }));
}

function stubRpcSuccess(overrides: Record<string, unknown> = {}) {
  mockRpc.mockResolvedValue({
    data: {
      clicks_by_day: overrides.clicks_by_day ?? [
        { day: "2026-04-14", clicks: 10 },
        { day: "2026-04-15", clicks: 15 },
      ],
      by_platform: overrides.by_platform ?? [
        { platform: "instagram", count: 20 },
      ],
      by_device: overrides.by_device ?? [{ device: "mobile", count: 18 }],
      by_country: overrides.by_country ?? [{ country: "US", count: 15 }],
      unique_visitors: overrides.unique_visitors ?? 30,
      total_clicks: overrides.total_clicks ?? 25,
      deep_link_attempts: overrides.deep_link_attempts ?? 10,
      conversions: overrides.conversions ?? { count: 2, total_value: 50.0 },
    },
    error: null,
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

describe("Smart Link Analytics handler", () => {
  // =========================================================================
  // Validation
  // =========================================================================

  it("returns 400 when linkId is missing", async () => {
    const res = mockRes();
    await invokeHandleAnalytics(makeReq({}), res, USER_ID);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("returns 400 when linkId is empty string", async () => {
    const res = mockRes();
    await invokeHandleAnalytics(makeReq({ linkId: "" }), res, USER_ID);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  // =========================================================================
  // Ownership
  // =========================================================================

  it("returns 404 when smart link not found or not owned", async () => {
    stubSmartLinkNotOwned();
    stubRpcSuccess();

    const res = mockRes();
    await invokeHandleAnalytics(makeReq({ linkId: "link-1" }), res, USER_ID);
    expect(res.status).toHaveBeenCalledWith(404);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: "Smart link not found" }),
    );
  });

  // =========================================================================
  // RPC Errors
  // =========================================================================

  it("returns 500 when analytics RPC fails", async () => {
    stubSmartLinkOwned();
    mockRpc.mockResolvedValue({
      data: null,
      error: { message: "RPC function not found" },
    });

    const res = mockRes();
    await invokeHandleAnalytics(makeReq({ linkId: "link-1" }), res, USER_ID);
    expect(res.status).toHaveBeenCalledWith(500);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({
        error: expect.stringContaining("Failed to load analytics"),
      }),
    );
  });

  // =========================================================================
  // Range Parsing
  // =========================================================================

  it("defaults to 7d range", async () => {
    stubSmartLinkOwned();
    stubRpcSuccess();

    const res = mockRes();
    await invokeHandleAnalytics(makeReq({ linkId: "link-1" }), res, USER_ID);
    expect(res.status).toHaveBeenCalledWith(200);
    // RPC should have been called with a date ~7 days ago
    expect(mockRpc).toHaveBeenCalledWith(
      "smart_link_analytics",
      expect.objectContaining({
        p_link_id: "link-1",
        p_since: expect.any(String),
      }),
    );
  });

  it("accepts 30d range", async () => {
    stubSmartLinkOwned();
    stubRpcSuccess();

    const res = mockRes();
    await invokeHandleAnalytics(
      makeReq({ linkId: "link-1", range: "30d" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(200);
  });

  it("accepts 90d range", async () => {
    stubSmartLinkOwned();
    stubRpcSuccess();

    const res = mockRes();
    await invokeHandleAnalytics(
      makeReq({ linkId: "link-1", range: "90d" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(200);
  });

  // =========================================================================
  // Response Shape
  // =========================================================================

  it("returns full analytics response with correct shape", async () => {
    stubSmartLinkOwned({ click_count: 42 });
    stubRpcSuccess({ total_clicks: 25, unique_visitors: 30, deep_link_attempts: 10 });

    const res = mockRes();
    await invokeHandleAnalytics(makeReq({ linkId: "link-1" }), res, USER_ID);
    expect(res.status).toHaveBeenCalledWith(200);

    const responseData = res.json.mock.calls[0][0].data;
    expect(responseData).toHaveProperty("total_clicks", 42);
    expect(responseData).toHaveProperty("period_clicks", 25);
    expect(responseData).toHaveProperty("unique_visitors", 30);
    expect(responseData).toHaveProperty("clicks_per_day");
    expect(responseData).toHaveProperty("platforms");
    expect(responseData).toHaveProperty("devices");
    expect(responseData).toHaveProperty("countries");
    expect(responseData).toHaveProperty("deep_link_ratio");
    expect(responseData.deep_link_ratio).toEqual({
      attempted: 10,
      fallback: 15,
      total: 25,
    });
  });

  // =========================================================================
  // Revenue
  // =========================================================================

  it("calculates estimated revenue from clicks * rate * value", async () => {
    stubSmartLinkOwned({
      click_count: 100,
      est_conversion_rate: 0.1,
      est_conversion_value: 50,
    });
    stubRpcSuccess({
      total_clicks: 200,
      conversions: { count: 5, total_value: 250 },
    });

    const res = mockRes();
    await invokeHandleAnalytics(makeReq({ linkId: "link-1" }), res, USER_ID);
    expect(res.status).toHaveBeenCalledWith(200);

    const responseData = res.json.mock.calls[0][0].data;
    expect(responseData.revenue).toEqual({
      actual_conversions: 5,
      actual_revenue: 250,
      estimated_revenue: 200 * 0.1 * 50, // 1000
    });
  });

  it("returns 0 estimated revenue when no conversion fields set", async () => {
    // Use a custom mock to ensure both queries return null est fields
    let callIdx = 0;
    mockFrom.mockImplementation((table: string) => {
      if (table === "smart_links") {
        return {
          select: vi.fn().mockImplementation(() => {
            callIdx++;
            const data = callIdx <= 1
              ? { id: "link-1", click_count: 50 }
              : { est_conversion_rate: null, est_conversion_value: null };
            return {
              eq: vi.fn().mockImplementation(() => ({
                eq: vi.fn().mockReturnValue({
                  maybeSingle: vi.fn().mockResolvedValue({ data, error: null }),
                }),
                maybeSingle: vi.fn().mockResolvedValue({ data, error: null }),
              })),
            };
          }),
        };
      }
      return {
        select: vi.fn().mockReturnThis(),
        eq: vi.fn().mockReturnThis(),
        gte: vi.fn().mockResolvedValue({ data: [], error: null }),
        maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
      };
    });
    stubRpcSuccess({
      total_clicks: 100,
      conversions: { count: 0, total_value: 0 },
    });

    const res = mockRes();
    await invokeHandleAnalytics(makeReq({ linkId: "link-1" }), res, USER_ID);
    expect(res.status).toHaveBeenCalledWith(200);

    const responseData = res.json.mock.calls[0][0].data;
    expect(responseData.revenue.estimated_revenue).toBe(0);
    expect(responseData.revenue.actual_conversions).toBe(0);
  });

  it("includes actual conversions from RPC data", async () => {
    stubSmartLinkOwned({ click_count: 200 });
    stubRpcSuccess({
      total_clicks: 150,
      conversions: { count: 10, total_value: 500 },
    });

    const res = mockRes();
    await invokeHandleAnalytics(makeReq({ linkId: "link-1" }), res, USER_ID);
    expect(res.status).toHaveBeenCalledWith(200);

    const responseData = res.json.mock.calls[0][0].data;
    expect(responseData.revenue.actual_conversions).toBe(10);
    expect(responseData.revenue.actual_revenue).toBe(500);
  });

  // =========================================================================
  // Deep Link Ratio
  // =========================================================================

  it("calculates deep link fallback as total minus attempted", async () => {
    stubSmartLinkOwned();
    stubRpcSuccess({
      total_clicks: 50,
      deep_link_attempts: 30,
    });

    const res = mockRes();
    await invokeHandleAnalytics(makeReq({ linkId: "link-1" }), res, USER_ID);
    expect(res.status).toHaveBeenCalledWith(200);

    const responseData = res.json.mock.calls[0][0].data;
    expect(responseData.deep_link_ratio).toEqual({
      attempted: 30,
      fallback: 20,
      total: 50,
    });
  });

  // =========================================================================
  // Edge Cases
  // =========================================================================

  it("handles empty aggregation data gracefully", async () => {
    stubSmartLinkOwned();
    mockRpc.mockResolvedValue({
      data: {
        clicks_by_day: null,
        by_platform: null,
        by_device: null,
        by_country: null,
        unique_visitors: null,
        total_clicks: null,
        deep_link_attempts: null,
        conversions: null,
      },
      error: null,
    });

    const res = mockRes();
    await invokeHandleAnalytics(makeReq({ linkId: "link-1" }), res, USER_ID);
    expect(res.status).toHaveBeenCalledWith(200);

    const responseData = res.json.mock.calls[0][0].data;
    expect(responseData.clicks_per_day).toEqual([]);
    expect(responseData.platforms).toEqual([]);
    expect(responseData.devices).toEqual([]);
    expect(responseData.countries).toEqual([]);
    expect(responseData.unique_visitors).toBe(0);
    expect(responseData.period_clicks).toBe(0);
  });
});
