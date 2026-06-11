/**
 * Unit tests for Admin Token Health Handler
 * (api/_lib/handlers/admin/token-health.ts)
 *
 * Tests the token health check endpoint that verifies token validity
 * for all Threads accounts:
 * 1. Method validation — GET and POST only
 * 2. Account fetching with group names
 * 3. Token decryption and validation via Meta API
 * 4. Token status classification (valid, expired, suspended, no_token, decrypt_error)
 * 5. Concurrency-limited batch processing (5 at a time)
 * 6. 7-day view aggregation per account
 * 7. Discord report sending
 * 8. Flagging accounts for reauth (expired/suspended)
 * 9. Summary generation
 * 10. Error isolation — individual account errors don't crash the batch
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — module scope, BEFORE importing module under test
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockRpc = vi.fn();

vi.mock("@/api/_lib/supabase", () => ({
  getSupabase: () => ({ from: mockFrom, rpc: mockRpc }),
}));

vi.mock("@/api/_lib/logger", () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}));

const mockApiError = vi.fn();
const mockApiSuccess = vi.fn();
const mockServerError = vi.fn();
vi.mock("@/api/_lib/apiResponse", () => ({
  apiError: (...args: unknown[]) => mockApiError(...args),
  apiSuccess: (...args: unknown[]) => mockApiSuccess(...args),
  serverError: (...args: unknown[]) => mockServerError(...args),
}));

const mockDecrypt = vi.fn();
vi.mock("@/api/_lib/encryption", () => ({
  decrypt: (...args: unknown[]) => mockDecrypt(...args),
}));

// withAdminRole mock
vi.mock("@/api/_lib/middleware", () => ({
  withAdminRole: (handler: Function) => {
    return async (req: any, res: any) => {
      const user = { id: "admin-user-1", role: "owner" };
      return handler(req, res, user);
    };
  },
}));

// Mock global fetch for Meta API calls and Discord webhook
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// ---------------------------------------------------------------------------
// Import module under test (AFTER all mocks)
// ---------------------------------------------------------------------------

import tokenHealthHandler from "@/api/_lib/handlers/admin/token-health";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockReq(overrides: Record<string, unknown> = {}) {
  return {
    method: "GET",
    query: {},
    headers: {},
    ...overrides,
  };
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

function makeAccount(overrides: Record<string, unknown> = {}) {
  return {
    id: "acc-1",
    user_id: "user-1",
    username: "testuser",
    threads_user_id: "tu-1",
    threads_access_token_encrypted: "enc-token-1",
    group_id: "group-1",
    needs_reauth: false,
    status: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("admin/token-health handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    delete process.env.DISCORD_ALERT_WEBHOOK_URL;
    mockDecrypt.mockReturnValue("decrypted-test-token");
    mockFetch.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({ id: "tu-1", username: "testuser" }),
    });
  });

  it("rejects unsupported methods (PUT, DELETE)", async () => {
    const req = mockReq({ method: "PUT" });
    const res = mockRes();
    await tokenHealthHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 405, "Method not allowed");
  });

  it("returns empty results when no accounts found", async () => {
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "accounts") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      return c;
    });
    // RPC call for flags
    mockRpc.mockResolvedValue({ data: [], error: null });

    const req = mockReq();
    const res = mockRes();
    await tokenHealthHandler(req as any, res as any);

    expect(mockApiSuccess).toHaveBeenCalledWith(
      res,
      expect.objectContaining({
        results: [],
        summary: "No accounts found",
      })
    );
  });

  it("classifies valid tokens as valid", async () => {
    const account = makeAccount();

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "accounts") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [account], error: null });
      }
      if (table === "account_groups") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [{ id: "group-1", name: "Main Group" }], error: null });
      }
      if (table === "account_analytics") {
        c.then = (resolve: (v: any) => void) =>
          resolve({
            data: [{ account_id: "acc-1", total_views: 500 }],
            error: null,
          });
      }
      return c;
    });
    mockRpc.mockResolvedValue({ data: [], error: null });

    // Meta API returns valid
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ id: "tu-1", username: "testuser" }),
    });

    const req = mockReq({ query: { discord: "false" } });
    const res = mockRes();
    await tokenHealthHandler(req as any, res as any);

    const call = mockApiSuccess.mock.calls[0];
    const results = call[1].results;
    expect(results).toHaveLength(1);
    expect(results[0].token_status).toBe("valid");
    expect(results[0].total_views_7d).toBe(500);
  });

  it("classifies expired tokens (Meta API code 190)", async () => {
    const account = makeAccount();

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "accounts") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [account], error: null });
      }
      if (table === "account_groups") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [{ id: "group-1", name: "Group" }], error: null });
      }
      if (table === "account_analytics") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      return c;
    });
    mockRpc.mockResolvedValue({ data: [], error: null });

    mockFetch.mockResolvedValue({
      ok: false,
      json: () =>
        Promise.resolve({
          error: { code: 190, message: "Invalid access token" },
        }),
    });

    const req = mockReq({ query: { discord: "false" } });
    const res = mockRes();
    await tokenHealthHandler(req as any, res as any);

    const results = mockApiSuccess.mock.calls[0][1].results;
    expect(results[0].token_status).toBe("expired");
  });

  it("classifies suspended accounts (Meta API code 100)", async () => {
    const account = makeAccount();

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "accounts") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [account], error: null });
      }
      if (table === "account_groups") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      if (table === "account_analytics") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      return c;
    });
    mockRpc.mockResolvedValue({ data: [], error: null });

    mockFetch.mockResolvedValue({
      ok: false,
      json: () =>
        Promise.resolve({
          error: { code: 100, message: "User not found" },
        }),
    });

    const req = mockReq({ query: { discord: "false" } });
    const res = mockRes();
    await tokenHealthHandler(req as any, res as any);

    const results = mockApiSuccess.mock.calls[0][1].results;
    expect(results[0].token_status).toBe("suspended");
  });

  it("handles accounts with no token", async () => {
    const noTokenAccount = makeAccount({
      threads_access_token_encrypted: null,
      threads_user_id: null,
    });

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "accounts") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [noTokenAccount], error: null });
      }
      if (table === "account_groups") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      if (table === "account_analytics") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      return c;
    });
    mockRpc.mockResolvedValue({ data: [], error: null });

    const req = mockReq({ query: { discord: "false" } });
    const res = mockRes();
    await tokenHealthHandler(req as any, res as any);

    const results = mockApiSuccess.mock.calls[0][1].results;
    expect(results[0].token_status).toBe("no_token");
  });

  it("handles decryption errors gracefully", async () => {
    const account = makeAccount();

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "accounts") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [account], error: null });
      }
      if (table === "account_groups") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      if (table === "account_analytics") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      return c;
    });
    mockRpc.mockResolvedValue({ data: [], error: null });

    mockDecrypt.mockImplementation(() => {
      throw new Error("Invalid key length");
    });

    const req = mockReq({ query: { discord: "false" } });
    const res = mockRes();
    await tokenHealthHandler(req as any, res as any);

    const results = mockApiSuccess.mock.calls[0][1].results;
    expect(results[0].token_status).toBe("decrypt_error");
    expect(results[0].error_detail).toContain("Invalid key length");
  });

  it("flags expired accounts for reauth", async () => {
    const account = makeAccount({ needs_reauth: false });

    const updateCalls: any[] = [];
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "accounts") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [account], error: null });
        const origUpdate = c.update;
        c.update = vi.fn().mockImplementation((payload: any) => {
          updateCalls.push({ table, payload });
          return origUpdate(payload);
        });
      }
      if (table === "account_groups") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      if (table === "account_analytics") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      return c;
    });
    mockRpc.mockResolvedValue({ data: [], error: null });

    // Meta API returns expired
    mockFetch.mockResolvedValue({
      ok: false,
      json: () =>
        Promise.resolve({
          error: { code: 190, message: "Token expired" },
        }),
    });

    const req = mockReq({ query: { discord: "false" } });
    const res = mockRes();
    await tokenHealthHandler(req as any, res as any);

    // Verify accounts.update was called with needs_reauth: true
    const reauthUpdate = updateCalls.find(
      (u) => u.table === "accounts" && u.payload?.needs_reauth === true
    );
    expect(reauthUpdate).toBeDefined();
  });

  it("generates correct summary counts", async () => {
    const accounts = [
      makeAccount({ id: "acc-valid", username: "valid", threads_user_id: "tu-v" }),
      makeAccount({
        id: "acc-expired",
        username: "expired",
        threads_user_id: "tu-e",
      }),
      makeAccount({
        id: "acc-notoken",
        username: "notoken",
        threads_access_token_encrypted: null,
        threads_user_id: null,
      }),
    ];

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "accounts") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: accounts, error: null });
      }
      if (table === "account_groups") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      if (table === "account_analytics") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      return c;
    });
    mockRpc.mockResolvedValue({ data: [], error: null });

    let fetchCallCount = 0;
    mockFetch.mockImplementation((url: string) => {
      fetchCallCount++;
      // First call (valid account)
      if (url.includes("tu-v")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ id: "tu-v", username: "valid" }),
        });
      }
      // Second call (expired account)
      if (url.includes("tu-e")) {
        return Promise.resolve({
          ok: false,
          json: () =>
            Promise.resolve({
              error: { code: 190, message: "Token expired" },
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({}),
      });
    });

    const req = mockReq({ query: { discord: "false" } });
    const res = mockRes();
    await tokenHealthHandler(req as any, res as any);

    const call = mockApiSuccess.mock.calls[0];
    const summary = call[1].summary;
    expect(summary.total).toBe(3);
    expect(summary.valid).toBe(1);
    expect(summary.expired).toBe(1);
    expect(summary.noToken).toBe(1);
  });

  it("sends Discord webhook when discord query param is not false", async () => {
    process.env.DISCORD_ALERT_WEBHOOK_URL = "https://discord.com/api/webhooks/test";

    const account = makeAccount();

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "accounts") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [account], error: null });
      }
      if (table === "account_groups") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      if (table === "account_analytics") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      return c;
    });
    mockRpc.mockResolvedValue({ data: [], error: null });

    // Meta API and Discord webhook responses
    mockFetch.mockImplementation((url: string) => {
      if (url.includes("discord.com")) {
        return Promise.resolve({ ok: true });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ id: "tu-1", username: "testuser" }),
      });
    });

    const req = mockReq({ query: {} }); // discord not set to "false"
    const res = mockRes();
    await tokenHealthHandler(req as any, res as any);

    // Verify Discord was called
    const discordCalls = mockFetch.mock.calls.filter(
      (call: any[]) => typeof call[0] === "string" && call[0].includes("discord.com")
    );
    expect(discordCalls.length).toBeGreaterThan(0);
  });

  it("handles DB errors gracefully with serverError", async () => {
    mockFrom.mockImplementation((table: string) => {
      if (table === "accounts") {
        const c = chainable(null);
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: null, error: { message: "Connection refused" } });
        return c;
      }
      return chainable(null);
    });

    const req = mockReq({ query: { discord: "false" } });
    const res = mockRes();
    await tokenHealthHandler(req as any, res as any);

    expect(mockServerError).toHaveBeenCalledWith(res, "Connection refused");
  });
});
