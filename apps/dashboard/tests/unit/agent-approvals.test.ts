/**
 * Unit tests for Agent Approvals handler
 * (api/_lib/handlers/agent/approvals.ts)
 *
 * Covers: POST create, GET list, PATCH decide,
 * validation, auto-expiry, notification fire-and-forget
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockApiError = vi.fn();
const mockApiSuccess = vi.fn();
const mockCreateNotification = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock()
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/supabase", () => ({
  getSupabase: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/logger", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/api/_lib/apiResponse", () => ({
  apiError: (...args: unknown[]) => mockApiError(...args),
  apiSuccess: (...args: unknown[]) => mockApiSuccess(...args),
}));

vi.mock("@/api/_lib/zodCompat", () => {
  const { z } = require("zod");
  return {
    z,
    zEnum: (values: string[]) => (z as any).enum(values),
    zUnknown: () => z.any(),
    zArray: (schema: any) => z.array(schema),
  };
});

vi.mock("@/api/_lib/middleware", () => ({
  withAuthDb: (handler: Function) => {
    return async (req: any, res: any) => {
      const user = { id: "user-1" };
      const db = { from: mockFrom };
      return handler(req, res, {
        user,
        userDb: db,
        adminDb: db,
        adminDbAny: db,
      });
    };
  },
}));

vi.mock("@/api/_lib/createNotification", () => ({
  createNotification: (...args: unknown[]) => mockCreateNotification(...args),
}));

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import approvalsHandler from "@/api/_lib/handlers/agent/approvals";

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

function setupInsertMock(result: { data: any; error: any }) {
  const selectFn = vi.fn().mockReturnValue({
    single: vi.fn().mockResolvedValue(result),
  });
  const insertFn = vi.fn().mockReturnValue({ select: selectFn });

  mockFrom.mockImplementation((table: string) => {
    if (table === "agent_approvals") {
      return { insert: insertFn };
    }
    return {
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
    };
  });
  return insertFn;
}

function setupGetListMock(config: {
  approvals?: any[];
  approvalsError?: any;
  updateResult?: { data: any; error: any };
}) {
  const maybeSingleFn = vi.fn().mockResolvedValue(config.updateResult ?? { data: null, error: null });

  mockFrom.mockImplementation((table: string) => {
    if (table === "agent_approvals") {
      return {
        // For GET list
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            order: vi.fn().mockReturnValue({
              limit: vi.fn().mockReturnValue({
                eq: vi.fn().mockResolvedValue({
                  data: config.approvals ?? [],
                  error: config.approvalsError ?? null,
                }),
              }),
            }),
            eq: vi.fn().mockReturnValue({
              select: vi.fn().mockReturnValue({
                maybeSingle: maybeSingleFn,
              }),
            }),
          }),
        }),
        // For auto-expire update
        update: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              lt: vi.fn().mockResolvedValue({ error: null }),
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

function setupPatchMock(result: { data: any; error: any }) {
  const singleFn = vi.fn().mockResolvedValue(result);
  const selectFn = vi.fn().mockReturnValue({ single: singleFn });

  mockFrom.mockImplementation((table: string) => {
    if (table === "agent_approvals") {
      return {
        update: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              eq: vi.fn().mockReturnValue({
                select: selectFn,
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

describe("agent/approvals handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Method validation ─────────────────────────────────────────────────────

  it("rejects unsupported HTTP methods", async () => {
    const req = mockReq({ method: "DELETE" });
    const res = mockRes();
    await approvalsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 405, "Method not allowed");
  });

	// ── POST: create approval ─────────────────────────────────────────────────

	it("POST creates an approval request with valid input", async () => {
		setupInsertMock({
			data: { id: "approval-1" },
			error: null,
		});

    const req = mockReq({
      method: "POST",
      body: {
        context: "Need to schedule 5 posts for group A",
        urgency: "medium",
        expires_in_hours: 24,
      },
    });
    const res = mockRes();
    await approvalsHandler(req as any, res as any);

    expect(mockApiSuccess).toHaveBeenCalledWith(
      res,
      expect.objectContaining({
        approvalId: "approval-1",
        status: "pending",
        urgency: "medium",
      }),
    );
  });

  it("POST rejects empty context", async () => {
    const req = mockReq({
      method: "POST",
      body: { context: "" },
    });
    const res = mockRes();
    await approvalsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, expect.any(String));
  });

  it("POST rejects context longer than 2000 chars", async () => {
    const req = mockReq({
      method: "POST",
      body: { context: "a".repeat(2001) },
    });
    const res = mockRes();
    await approvalsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, expect.any(String));
  });

  it("POST rejects invalid urgency", async () => {
    const req = mockReq({
      method: "POST",
      body: { context: "test context", urgency: "critical" },
    });
    const res = mockRes();
    await approvalsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, expect.any(String));
  });

  it("POST returns 500 on insert error", async () => {
    setupInsertMock({ data: null, error: { message: "db error" } });

    const req = mockReq({
      method: "POST",
      body: { context: "test context" },
    });
    const res = mockRes();
    await approvalsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 500, "Failed to create approval request");
  });

  // ── GET: list approvals ───────────────────────────────────────────────────

  it("GET returns 500 on query error", async () => {
    setupGetListMock({ approvalsError: { message: "db error" } });

    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await approvalsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 500, "Failed to fetch approvals");
  });

  it("GET quick-action links do not mutate approval state", async () => {
    const req = mockReq({
      method: "GET",
      query: { id: "d8c9b0a1-2345-6789-abcd-ef0123456789", action: "approve" },
    });
    const res = mockRes();
    await approvalsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(
      res,
      405,
      "Approval decisions require authenticated PATCH from the approval queue.",
    );
    expect(mockFrom).not.toHaveBeenCalled();
  });

  // ── PATCH: decide ─────────────────────────────────────────────────────────

  it("PATCH approves with valid UUID and decision", async () => {
    setupPatchMock({
      data: {
        id: "d8c9b0a1-2345-6789-abcd-ef0123456789",
        status: "approved",
        decided_at: "2026-04-15T00:00:00Z",
      },
      error: null,
    });

    const req = mockReq({
      method: "PATCH",
      body: {
        id: "d8c9b0a1-2345-6789-abcd-ef0123456789",
        decision: "approved",
      },
    });
    const res = mockRes();
    await approvalsHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(
      res,
      expect.objectContaining({
        id: "d8c9b0a1-2345-6789-abcd-ef0123456789",
        status: "approved",
      }),
    );
  });

  it("PATCH rejects non-UUID id", async () => {
    const req = mockReq({
      method: "PATCH",
      body: { id: "not-a-uuid", decision: "approved" },
    });
    const res = mockRes();
    await approvalsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, expect.any(String));
  });

  it("PATCH rejects invalid decision value", async () => {
    const req = mockReq({
      method: "PATCH",
      body: {
        id: "d8c9b0a1-2345-6789-abcd-ef0123456789",
        decision: "maybe",
      },
    });
    const res = mockRes();
    await approvalsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, expect.any(String));
  });

  it("PATCH returns 404 for already-decided approval", async () => {
    setupPatchMock({ data: null, error: null });

    const req = mockReq({
      method: "PATCH",
      body: {
        id: "d8c9b0a1-2345-6789-abcd-ef0123456789",
        decision: "rejected",
      },
    });
    const res = mockRes();
    await approvalsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 404, "Approval not found or already decided");
  });
});
