/**
 * Unit tests for Listening Alerts handler
 * (api/_lib/handlers/listening/alerts.ts)
 *
 * Covers: CRUD (GET list, POST create, PUT update, DELETE),
 * tier gating (pro+), rate limiting, workspace IDOR, validation,
 * Zod schema enforcement
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
const mockCheckRateLimit = vi.fn();
const mockVerifyWorkspaceAccess = vi.fn();

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

vi.mock("@/api/_lib/rateLimiter", () => ({
  checkRateLimit: (...args: unknown[]) => mockCheckRateLimit(...args),
}));

vi.mock("@/api/_lib/workspaceAccess", () => ({
  verifyWorkspaceAccess: (...args: unknown[]) => mockVerifyWorkspaceAccess(...args),
}));

vi.mock("@/api/_lib/zodCompat", () => {
  const { z } = require("zod");
  return {
    z,
    zEnum: (values: string[]) => (z as any).enum(values),
  };
});

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import alertsHandler from "@/api/_lib/handlers/listening/alerts";

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

function setupAlertsMock(config: {
  alerts?: any[];
  alertsError?: any;
  insertedAlert?: any;
  insertError?: any;
  updatedAlert?: any;
  updateError?: any;
  deleteResult?: { data: any; error: any };
}) {
  mockFrom.mockImplementation((table: string) => {
    if (table === "listening_alerts") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            order: vi.fn().mockResolvedValue({
              data: config.alerts ?? [],
              error: config.alertsError ?? null,
            }),
            eq: vi.fn().mockReturnValue({
              order: vi.fn().mockResolvedValue({
                data: config.alerts ?? [],
                error: config.alertsError ?? null,
              }),
            }),
          }),
        }),
        insert: vi.fn().mockReturnValue({
          select: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: config.insertedAlert ?? { id: "alert-1" },
              error: config.insertError ?? null,
            }),
          }),
        }),
        update: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              select: vi.fn().mockReturnValue({
	                maybeSingle: vi.fn().mockResolvedValue({
	                  data: "updatedAlert" in config ? config.updatedAlert : { id: "alert-1" },
	                  error: config.updateError ?? null,
	                }),
              }),
            }),
          }),
        }),
        delete: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              select: vi.fn().mockReturnValue({
                maybeSingle: vi.fn().mockResolvedValue(
                  config.deleteResult ?? { data: { id: "alert-1" }, error: null },
                ),
              }),
            }),
          }),
        }),
      };
    }
    return {
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
    };
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("listening/alerts handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRequireMinTier.mockResolvedValue(true);
    mockCheckRateLimit.mockResolvedValue({ allowed: true });
    mockVerifyWorkspaceAccess.mockResolvedValue(true);
  });

  // ── Tier gating ───────────────────────────────────────────────────────────

  it("blocks free-tier users", async () => {
    mockRequireMinTier.mockResolvedValue(false);
    const req = mockReq();
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockRequireMinTier).toHaveBeenCalledWith("user-1", "pro", res);
    expect(mockApiSuccess).not.toHaveBeenCalled();
  });

  // ── Method validation ─────────────────────────────────────────────────────

  it("rejects unsupported HTTP method", async () => {
    const req = mockReq({ method: "PATCH" });
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 405, "Method not allowed");
  });

  // ── Rate limiting (non-GET) ───────────────────────────────────────────────

  it("rate limits POST requests", async () => {
    mockCheckRateLimit.mockResolvedValue({ allowed: false });
    setupAlertsMock({});
    const req = mockReq({
      method: "POST",
      body: { keyword: "test" },
    });
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 429, expect.any(String));
  });

  it("does not rate limit GET requests", async () => {
    setupAlertsMock({ alerts: [] });
    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockCheckRateLimit).not.toHaveBeenCalled();
  });

  // ── GET: list alerts ──────────────────────────────────────────────────────

  it("GET returns alerts list", async () => {
    const alerts = [{ id: "a1", keyword: "crypto" }];
    setupAlertsMock({ alerts });
    const req = mockReq();
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { alerts });
  });

  it("GET returns empty array when no alerts", async () => {
    setupAlertsMock({ alerts: [] });
    const req = mockReq();
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { alerts: [] });
  });

  it("GET returns 500 on DB error", async () => {
    setupAlertsMock({ alertsError: { message: "db error" } });
    const req = mockReq();
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 500, "Failed to load alerts");
  });

  // ── POST: create alert ────────────────────────────────────────────────────

  it("POST creates alert with valid keyword", async () => {
    setupAlertsMock({ insertedAlert: { id: "alert-1", keyword: "crypto" } });
    const req = mockReq({
      method: "POST",
      body: { keyword: "crypto" },
    });
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, {
      alert: { id: "alert-1", keyword: "crypto" },
    });
  });

  it("POST rejects empty keyword", async () => {
    setupAlertsMock({});
    const req = mockReq({
      method: "POST",
      body: { keyword: "" },
    });
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, expect.any(String));
  });

  it("POST rejects keyword over 200 chars", async () => {
    setupAlertsMock({});
    const req = mockReq({
      method: "POST",
      body: { keyword: "a".repeat(201) },
    });
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, expect.any(String));
  });

  it("POST rejects workspace IDOR", async () => {
    mockVerifyWorkspaceAccess.mockResolvedValue(false);
    setupAlertsMock({});
    const req = mockReq({
      method: "POST",
      body: { keyword: "test", workspace_id: "ws-other" },
    });
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 403, "Not authorized for this workspace");
  });

  it("POST returns 500 on insert error", async () => {
    setupAlertsMock({ insertError: { message: "db error" } });
    const req = mockReq({
      method: "POST",
      body: { keyword: "crypto" },
    });
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 500, "Failed to create alert");
  });

  // ── PUT: update alert ─────────────────────────────────────────────────────

  it("PUT requires id query parameter", async () => {
    setupAlertsMock({});
    const req = mockReq({
      method: "PUT",
      body: { keyword: "updated" },
    });
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "id required");
  });

  it("PUT returns 404 for non-existent alert", async () => {
    setupAlertsMock({ updatedAlert: null });
    const req = mockReq({
      method: "PUT",
      query: { id: "nonexistent" },
      body: { keyword: "updated" },
    });
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 404, "Alert not found");
  });

  // ── DELETE ────────────────────────────────────────────────────────────────

  it("DELETE requires id query parameter", async () => {
    setupAlertsMock({});
    const req = mockReq({ method: "DELETE" });
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "id required");
  });

  it("DELETE returns 404 for non-existent alert", async () => {
    setupAlertsMock({ deleteResult: { data: null, error: null } });
    const req = mockReq({
      method: "DELETE",
      query: { id: "nonexistent" },
    });
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 404, "Alert not found");
  });

  it("DELETE succeeds for owned alert", async () => {
    setupAlertsMock({
      deleteResult: { data: { id: "alert-1" }, error: null },
    });
    const req = mockReq({
      method: "DELETE",
      query: { id: "alert-1" },
    });
    const res = mockRes();
    await alertsHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { deleted: true });
  });
});
