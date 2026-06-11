/**
 * Unit tests for Admin Dead Letters Handler
 * (api/_lib/handlers/admin/dead-letters.ts)
 *
 * Tests the DLQ management API:
 * 1. Method validation — GET (list) and POST (actions) only
 * 2. Rate limiting
 * 3. Subscription tier gating — free tier rejected
 * 4. GET /list — queries 4 DLQ tables, merges, sorts by dead_letter_at
 * 5. POST /retry — resets DLQ item to pending state
 * 6. POST /purge — deletes individual DLQ item
 * 7. POST /purge-all — deletes all DLQ items (optionally scoped by source)
 * 8. Input validation via Zod schema
 * 9. Ownership verification for user-scoped resources
 * 10. Error string sanitization (strips stack traces and tokens)
 * 11. Webhook retry schedules processor replay
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — module scope, BEFORE importing module under test
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();

vi.mock("@/api/_lib/supabase", () => ({
  getSupabase: () => ({ from: mockFrom }),
  getSupabaseAny: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/logger", () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}));

const mockCheckRateLimit = vi.fn();
vi.mock("@/api/_lib/rateLimiter", () => ({
  checkRateLimit: (...args: unknown[]) => mockCheckRateLimit(...args),
}));

const mockScheduleWebhookReplay = vi.fn().mockResolvedValue(undefined);
vi.mock("@/api/_lib/cron/webhook-processor/retry", () => ({
  scheduleWebhookReplay: (...args: unknown[]) => mockScheduleWebhookReplay(...args),
}));

const mockApiError = vi.fn();
const mockApiSuccess = vi.fn();
vi.mock("@/api/_lib/apiResponse", () => ({
  apiError: (...args: unknown[]) => mockApiError(...args),
  apiSuccess: (...args: unknown[]) => mockApiSuccess(...args),
}));

// Passthrough zodCompat
vi.mock("@/api/_lib/zodCompat", () => ({
  z: require("zod").z,
  zEnum: (values: string[]) => {
    const { z } = require("zod");
    return (z as any).enum(values);
  },
}));

// withAdminRole mock — simulates admin check
vi.mock("@/api/_lib/middleware", () => ({
  withAdminRole: (handler: Function) => {
    return async (req: any, res: any) => {
      const user = { id: "admin-user-1", role: "owner" };
      return handler(req, res, user);
    };
  },
}));

// ---------------------------------------------------------------------------
// Import module under test (AFTER all mocks)
// ---------------------------------------------------------------------------

import deadLettersHandler from "@/api/_lib/handlers/admin/dead-letters";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockReq(overrides: Record<string, unknown> = {}) {
  return {
    method: "GET",
    query: {},
    headers: {},
    body: {},
    ...overrides,
  };
}

function mockPostReq(overrides: Record<string, unknown> = {}) {
  const headers = {
    "idempotency-key": `admin-dlq-test-${Math.random().toString(36).slice(2)}`,
    ...((overrides.headers as Record<string, string> | undefined) || {}),
  };
  return mockReq({
    method: "POST",
    ...overrides,
    headers,
  });
}

function mockRes() {
  const res: Record<string, any> = {};
  res.status = vi.fn().mockReturnValue(res);
  res.json = vi.fn().mockReturnValue(res);
  res.setHeader = vi.fn().mockReturnValue(res);
  return res;
}

function chainable(data: unknown, error: unknown = null) {
  const c: any = {};
  const methods = [
    "select", "eq", "in", "not", "gte", "lte", "lt", "or",
    "order", "limit", "insert", "update", "delete", "is",
  ];
  for (const m of methods) {
    c[m] = vi.fn().mockReturnValue(c);
  }
  c.maybeSingle = vi.fn().mockResolvedValue({ data, error });
  c.then = (resolve: (v: any) => void) => resolve({ data, error });
  return c;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("admin/dead-letters handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCheckRateLimit.mockResolvedValue({ allowed: true });
    mockScheduleWebhookReplay.mockResolvedValue(undefined);
  });

  it("rejects rate-limited requests", async () => {
    mockCheckRateLimit.mockResolvedValue({ allowed: false });

    const req = mockReq();
    const res = mockRes();
    await deadLettersHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 429, "Rate limit exceeded");
  });

  it("rejects free tier users", async () => {
    mockFrom.mockImplementation((table: string) => {
      if (table === "profiles") {
        return chainable({ subscription_tier: "free" });
      }
      return chainable(null);
    });

    const req = mockReq();
    const res = mockRes();
    await deadLettersHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(
      res,
      403,
      "Active paid subscription required for DLQ management"
    );
  });

  it("rejects unsupported methods (PUT, DELETE)", async () => {
    mockFrom.mockImplementation((table: string) => {
      if (table === "profiles") {
        return chainable({ subscription_tier: "pro" });
      }
      return chainable(null);
    });

    const req = mockReq({ method: "PUT" });
    const res = mockRes();
    await deadLettersHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 405, "Method not allowed");
  });

  it("GET lists dead letter items from all 4 tables", async () => {
    mockFrom.mockImplementation((table: string) => {
      if (table === "profiles") {
        return chainable({ subscription_tier: "pro" });
      }
      const c = chainable(null);
      if (table === "threads_webhook_events") {
        c.then = (resolve: (v: any) => void) =>
          resolve({
            data: [
              {
                id: "t-1",
                event_type: "reply",
                error: null,
                dead_letter_at: "2026-04-15T00:00:00Z",
                dead_letter_reason: "Exhausted retries",
                retry_count: 5,
                received_at: "2026-04-14T23:00:00Z",
              },
            ],
            error: null,
          });
      }
      if (table === "ig_webhook_events") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      if (table === "auto_post_queue") {
        c.then = (resolve: (v: any) => void) =>
          resolve({
            data: [
              {
                id: "q-1",
                account_id: "acc-1",
                last_error: "AI generation failed\n  at processQueue (/api/queue.ts:42:5)",
                retry_count: 3,
                created_at: "2026-04-14T22:00:00Z",
              },
            ],
            error: null,
          });
      }
      if (table === "ig_pending_containers") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      return c;
    });

    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await deadLettersHandler(req as any, res as any);

    expect(mockApiSuccess).toHaveBeenCalledWith(
      res,
      expect.objectContaining({
        total: 2,
        items: expect.arrayContaining([
          expect.objectContaining({
            source: "threads_webhook",
            id: "t-1",
          }),
          expect.objectContaining({
            source: "auto_post_queue",
            id: "q-1",
          }),
        ]),
      })
    );
  });

  it("GET sanitizes error strings — strips stack traces and tokens", async () => {
    mockFrom.mockImplementation((table: string) => {
      if (table === "profiles") {
        return chainable({ subscription_tier: "pro" });
      }
      const c = chainable(null);
      if (table === "threads_webhook_events") {
        c.then = (resolve: (v: any) => void) =>
          resolve({
            data: [
              {
                id: "t-sanitize",
                event_type: "reply",
                error: "OAuth error: access_token=EAABsbCS123token456&scope=read\n  at handleOAuth (/api/auth.ts:15:3)\n  at processRequest (/api/handler.ts:42:5)",
                dead_letter_at: "2026-04-15T00:00:00Z",
                dead_letter_reason: null,
                retry_count: 3,
                received_at: "2026-04-14T23:00:00Z",
              },
            ],
            error: null,
          });
      }
      if (table === "ig_webhook_events") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      if (table === "auto_post_queue") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      if (table === "ig_pending_containers") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      return c;
    });

    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await deadLettersHandler(req as any, res as any);

    const call = mockApiSuccess.mock.calls[0];
    const items = call[1].items;
    const item = items.find((i: any) => i.id === "t-sanitize");

    // Token should be redacted
    expect(item.reason).toContain("[REDACTED]");
    // Stack trace should be stripped
    expect(item.reason).not.toContain("at handleOAuth");
  });

  it("POST /retry resets DLQ item for threads_webhook", async () => {
    mockFrom.mockImplementation((table: string) => {
      if (table === "profiles") {
        return chainable({ subscription_tier: "pro" });
      }
      if (table === "threads_webhook_events") {
        return chainable({ threads_user_id: "threads-owned" });
      }
      if (table === "accounts") {
        return chainable({ user_id: "admin-user-1" });
      }
      return chainable(null);
    });

    const req = mockPostReq({
      body: {
        action: "retry",
        source: "threads_webhook",
        itemId: "t-retry-1",
      },
    });
    const res = mockRes();
    await deadLettersHandler(req as any, res as any);

    expect(mockApiSuccess).toHaveBeenCalledWith(
      res,
      expect.objectContaining({
        retried: "t-retry-1",
        replayScheduledFor: "threads",
      })
    );
    expect(mockScheduleWebhookReplay).toHaveBeenCalledWith("threads", 5);
  });

  it("POST /retry resets DLQ item for auto_post_queue", async () => {
    // Ownership check: auto_post_queue needs account ownership verification
    mockFrom.mockImplementation((table: string) => {
      if (table === "profiles") {
        return chainable({ subscription_tier: "pro" });
      }
      if (table === "auto_post_queue") {
        const c = chainable(null);
        c.maybeSingle = vi.fn().mockResolvedValue({
          data: { account_id: "acc-owned" },
          error: null,
        });
        return c;
      }
      if (table === "accounts") {
        const c = chainable(null);
        c.maybeSingle = vi.fn().mockResolvedValue({
          data: { user_id: "admin-user-1" }, // matches the mocked admin user
          error: null,
        });
        return c;
      }
      return chainable(null);
    });

    const req = mockPostReq({
      body: {
        action: "retry",
        source: "auto_post_queue",
        itemId: "q-retry-1",
      },
    });
    const res = mockRes();
    await deadLettersHandler(req as any, res as any);

    expect(mockApiSuccess).toHaveBeenCalledWith(
      res,
      expect.objectContaining({ retried: "q-retry-1" })
    );
  });

  it("POST /retry rejects when user doesn't own the resource", async () => {
    mockFrom.mockImplementation((table: string) => {
      if (table === "profiles") {
        return chainable({ subscription_tier: "pro" });
      }
      if (table === "auto_post_queue") {
        const c = chainable(null);
        c.maybeSingle = vi.fn().mockResolvedValue({
          data: { account_id: "acc-someone-else" },
          error: null,
        });
        return c;
      }
      if (table === "accounts") {
        const c = chainable(null);
        c.maybeSingle = vi.fn().mockResolvedValue({
          data: { user_id: "other-user" }, // NOT the admin user
          error: null,
        });
        return c;
      }
      return chainable(null);
    });

    const req = mockPostReq({
      body: {
        action: "retry",
        source: "auto_post_queue",
        itemId: "q-not-owned",
      },
    });
    const res = mockRes();
    await deadLettersHandler(req as any, res as any);

    expect(mockApiError).toHaveBeenCalledWith(
      res,
      403,
      "You do not have access to this resource"
    );
  });

  it("POST /purge deletes individual DLQ item", async () => {
    mockFrom.mockImplementation((table: string) => {
      if (table === "profiles") {
        return chainable({ subscription_tier: "pro" });
      }
      if (table === "ig_webhook_events") {
        return chainable({ ig_user_id: "ig-owned" });
      }
      if (table === "instagram_accounts") {
        return chainable({ user_id: "admin-user-1" });
      }
      return chainable(null);
    });

    const req = mockPostReq({
      body: {
        action: "purge",
        source: "ig_webhook",
        itemId: "ig-purge-1",
      },
    });
    const res = mockRes();
    await deadLettersHandler(req as any, res as any);

    expect(mockApiSuccess).toHaveBeenCalledWith(
      res,
      expect.objectContaining({ purged: "ig-purge-1" })
    );
  });

  it("POST /purge-all deletes all DLQ items from specific source", async () => {
    mockFrom.mockImplementation((table: string) => {
      if (table === "profiles") {
        return chainable({ subscription_tier: "pro" });
      }
      return chainable(null);
    });

    const req = mockPostReq({
      body: {
        action: "purge-all",
        source: "threads_webhook",
      },
    });
    const res = mockRes();
    await deadLettersHandler(req as any, res as any);

    expect(mockApiSuccess).toHaveBeenCalledWith(
      res,
      expect.objectContaining({ purgedSource: "threads_webhook" })
    );
  });

  it("POST /purge-all without source purges all DLQ tables", async () => {
    mockFrom.mockImplementation((table: string) => {
      if (table === "profiles") {
        return chainable({ subscription_tier: "pro" });
      }
      return chainable(null);
    });

    const req = mockPostReq({
      body: { action: "purge-all" },
    });
    const res = mockRes();
    await deadLettersHandler(req as any, res as any);

    expect(mockApiSuccess).toHaveBeenCalledWith(
      res,
      expect.objectContaining({ purgedSource: "all" })
    );
  });

  it("POST rejects invalid action", async () => {
    mockFrom.mockImplementation((table: string) => {
      if (table === "profiles") {
        return chainable({ subscription_tier: "pro" });
      }
      return chainable(null);
    });

    const req = mockReq({
      method: "POST",
      body: { action: "invalid-action" },
    });
    const res = mockRes();
    await deadLettersHandler(req as any, res as any);

    expect(mockApiError).toHaveBeenCalledWith(
      res,
      400,
      expect.stringContaining("Invalid input")
    );
  });

  it("POST /retry requires source and itemId", async () => {
    mockFrom.mockImplementation((table: string) => {
      if (table === "profiles") {
        return chainable({ subscription_tier: "pro" });
      }
      return chainable(null);
    });

    const req = mockPostReq({
      body: { action: "retry" },
    });
    const res = mockRes();
    await deadLettersHandler(req as any, res as any);

    // Should fail because source/itemId are empty
    expect(mockApiError).toHaveBeenCalledWith(
      res,
      400,
      "source and itemId are required"
    );
  });
});
