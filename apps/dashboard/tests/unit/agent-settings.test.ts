/**
 * Unit tests for Agent Settings handler
 * (api/_lib/handlers/agent/settings.ts)
 *
 * Covers: GET agent_paused, PATCH toggle, circuit breaker reset on unpause,
 * validation, error handling
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockApiError = vi.fn();
const mockApiSuccess = vi.fn();
const mockCircuitBreakerReset = vi.fn();

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

vi.mock("@/api/_lib/agentCircuitBreaker", () => ({
  reset: (...args: unknown[]) => mockCircuitBreakerReset(...args),
}));

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import settingsHandler from "@/api/_lib/handlers/agent/settings";

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

function setupProfileMock(config: {
  agentPaused?: boolean;
  selectError?: any;
  updateError?: any;
}) {
  mockFrom.mockImplementation((table: string) => {
    if (table === "profiles") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: { agent_paused: config.agentPaused ?? false },
              error: config.selectError ?? null,
            }),
          }),
        }),
        update: vi.fn().mockReturnValue({
          eq: vi.fn().mockResolvedValue({
            error: config.updateError ?? null,
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

describe("agent/settings handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Method validation ─────────────────────────────────────────────────────

  it("rejects unsupported HTTP methods", async () => {
    const req = mockReq({ method: "POST" });
    const res = mockRes();
    await settingsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 405, "Method not allowed");
  });

  it("rejects DELETE method", async () => {
    const req = mockReq({ method: "DELETE" });
    const res = mockRes();
    await settingsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 405, "Method not allowed");
  });

  // ── GET ───────────────────────────────────────────────────────────────────

  it("GET returns agent_paused = false by default", async () => {
    setupProfileMock({ agentPaused: false });
    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await settingsHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { agent_paused: false });
  });

  it("GET returns agent_paused = true when paused", async () => {
    setupProfileMock({ agentPaused: true });
    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await settingsHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { agent_paused: true });
  });

  it("GET returns 500 on DB error", async () => {
    setupProfileMock({ selectError: { message: "db failure" } });
    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await settingsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 500, "Failed to fetch agent settings");
  });

  it("GET defaults to false when data is null", async () => {
    mockFrom.mockImplementation(() => ({
      select: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
        }),
      }),
    }));
    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await settingsHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { agent_paused: false });
  });

  // ── PATCH ─────────────────────────────────────────────────────────────────

  it("PATCH updates agent_paused to true", async () => {
    setupProfileMock({});
    const req = mockReq({ method: "PATCH", body: { agent_paused: true } });
    const res = mockRes();
    await settingsHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { agent_paused: true });
  });

  it("PATCH updates agent_paused to false and resets circuit breaker", async () => {
    setupProfileMock({});
    mockCircuitBreakerReset.mockResolvedValue(undefined);

    const req = mockReq({ method: "PATCH", body: { agent_paused: false } });
    const res = mockRes();
    await settingsHandler(req as any, res as any);

    expect(mockApiSuccess).toHaveBeenCalledWith(res, { agent_paused: false });
    expect(mockCircuitBreakerReset).toHaveBeenCalledWith("user-1");
  });

  it("PATCH does NOT reset circuit breaker when pausing", async () => {
    setupProfileMock({});
    const req = mockReq({ method: "PATCH", body: { agent_paused: true } });
    const res = mockRes();
    await settingsHandler(req as any, res as any);
    expect(mockCircuitBreakerReset).not.toHaveBeenCalled();
  });

  it("PATCH rejects non-boolean agent_paused", async () => {
    const req = mockReq({ method: "PATCH", body: { agent_paused: "yes" } });
    const res = mockRes();
    await settingsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "agent_paused must be a boolean");
  });

  it("PATCH rejects missing agent_paused", async () => {
    const req = mockReq({ method: "PATCH", body: {} });
    const res = mockRes();
    await settingsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "agent_paused must be a boolean");
  });

  it("PATCH returns 500 on update error", async () => {
    setupProfileMock({ updateError: { message: "db error" } });
    const req = mockReq({ method: "PATCH", body: { agent_paused: true } });
    const res = mockRes();
    await settingsHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 500, "Failed to update agent settings");
  });

  it("PATCH still succeeds when circuit breaker reset fails", async () => {
    setupProfileMock({});
    mockCircuitBreakerReset.mockRejectedValue(new Error("redis down"));

    const req = mockReq({ method: "PATCH", body: { agent_paused: false } });
    const res = mockRes();
    await settingsHandler(req as any, res as any);

    expect(mockApiSuccess).toHaveBeenCalledWith(res, { agent_paused: false });
  });
});
