/**
 * Unit tests for Push Subscribe handler
 * (api/_lib/handlers/push/subscribe.ts)
 *
 * Covers: POST subscribe, DELETE unsubscribe, method validation,
 * rate limiting, subscription validation, DB upsert/delete
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockApiError = vi.fn();
const mockApiSuccess = vi.fn();
const mockBadRequest = vi.fn();
const mockMethodNotAllowed = vi.fn();
const mockCheckRateLimit = vi.fn();

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
  badRequest: (res: any, msg: string) => mockBadRequest(res, msg),
  methodNotAllowed: (res: any) => mockMethodNotAllowed(res),
}));

vi.mock("@/api/_lib/middleware", () => ({
  withAuth: (handler: Function) => {
    return async (req: any, res: any) => {
      const user = { id: "user-1", email: "test@example.com" };
      return handler(req, res, user);
    };
  },
}));

vi.mock("@/api/_lib/rateLimiter", () => ({
  checkRateLimit: (...args: unknown[]) => mockCheckRateLimit(...args),
}));

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import subscribeHandler from "@/api/_lib/handlers/push/subscribe";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockReq(overrides: Record<string, unknown> = {}) {
  return {
    method: "POST",
    query: {},
    body: {},
    headers: { "user-agent": "TestBrowser/1.0" },
    ...overrides,
  };
}

function setupPushMock(config: {
  upsertError?: any;
  deleteError?: any;
} = {}) {
  mockFrom.mockImplementation((table: string) => {
    if (table === "push_subscriptions") {
      return {
        upsert: vi.fn().mockResolvedValue({
          error: config.upsertError ?? null,
        }),
        delete: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockResolvedValue({
              error: config.deleteError ?? null,
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

describe("push/subscribe handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCheckRateLimit.mockResolvedValue({ allowed: true });
    setupPushMock();
  });

  // ── Method validation ─────────────────────────────────────────────────────

  it("rejects unsupported methods", async () => {
    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await subscribeHandler(req as any, res as any);
    expect(mockMethodNotAllowed).toHaveBeenCalledWith(res);
  });

  it("rejects PATCH method", async () => {
    const req = mockReq({ method: "PATCH" });
    const res = mockRes();
    await subscribeHandler(req as any, res as any);
    expect(mockMethodNotAllowed).toHaveBeenCalledWith(res);
  });

  // ── POST: subscribe ───────────────────────────────────────────────────────

  it("subscribes with valid subscription object", async () => {
    const req = mockReq({
      body: {
        subscription: {
          endpoint: "https://fcm.googleapis.com/fcm/send/abc",
          keys: { p256dh: "key1", auth: "key2" },
        },
      },
    });
    const res = mockRes();
    await subscribeHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { subscribed: true }, 201);
  });

  it("rejects missing subscription", async () => {
    const req = mockReq({ body: {} });
    const res = mockRes();
    await subscribeHandler(req as any, res as any);
    expect(mockBadRequest).toHaveBeenCalledWith(
      res,
      "Missing subscription endpoint or keys",
    );
  });

  it("rejects missing endpoint", async () => {
    const req = mockReq({
      body: {
        subscription: {
          keys: { p256dh: "key1", auth: "key2" },
        },
      },
    });
    const res = mockRes();
    await subscribeHandler(req as any, res as any);
    expect(mockBadRequest).toHaveBeenCalledWith(
      res,
      "Missing subscription endpoint or keys",
    );
  });

  it("rejects missing keys.p256dh", async () => {
    const req = mockReq({
      body: {
        subscription: {
          endpoint: "https://example.com",
          keys: { auth: "key2" },
        },
      },
    });
    const res = mockRes();
    await subscribeHandler(req as any, res as any);
    expect(mockBadRequest).toHaveBeenCalledWith(
      res,
      "Missing subscription endpoint or keys",
    );
  });

  it("rejects missing keys.auth", async () => {
    const req = mockReq({
      body: {
        subscription: {
          endpoint: "https://example.com",
          keys: { p256dh: "key1" },
        },
      },
    });
    const res = mockRes();
    await subscribeHandler(req as any, res as any);
    expect(mockBadRequest).toHaveBeenCalledWith(
      res,
      "Missing subscription endpoint or keys",
    );
  });

  it("returns 500 on DB upsert error", async () => {
    setupPushMock({ upsertError: { message: "db error" } });
    const req = mockReq({
      body: {
        subscription: {
          endpoint: "https://example.com",
          keys: { p256dh: "k1", auth: "k2" },
        },
      },
    });
    const res = mockRes();
    await subscribeHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 500, "Failed to save subscription");
  });

  it("rate limits subscribe requests", async () => {
    mockCheckRateLimit.mockResolvedValue({ allowed: false });
    const req = mockReq({
      body: {
        subscription: {
          endpoint: "https://example.com",
          keys: { p256dh: "k1", auth: "k2" },
        },
      },
    });
    const res = mockRes();
    await subscribeHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 429, expect.any(String));
  });

  // ── DELETE: unsubscribe ───────────────────────────────────────────────────

  it("unsubscribes with valid endpoint", async () => {
    const req = mockReq({
      method: "DELETE",
      body: { endpoint: "https://fcm.googleapis.com/fcm/send/abc" },
    });
    const res = mockRes();
    await subscribeHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { unsubscribed: true });
  });

  it("rejects DELETE without endpoint", async () => {
    const req = mockReq({ method: "DELETE", body: {} });
    const res = mockRes();
    await subscribeHandler(req as any, res as any);
    expect(mockBadRequest).toHaveBeenCalledWith(res, "Missing endpoint");
  });
});
