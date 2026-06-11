/**
 * Auth refresh endpoint tests — validates input validation, auth checks,
 * rate limiting, and error paths of the Threads token refresh handler.
 *
 * The handler (api/auth/threads/refresh.ts) calls external APIs (Meta Graph API)
 * and Supabase — we mock all external dependencies and test the behavioral
 * contract: what inputs cause what HTTP responses.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mock setup — must come before handler import
// ---------------------------------------------------------------------------

const mockGetUser = vi.fn();
const mockFrom = vi.fn();
const mockCheckRateLimit = vi.fn();

vi.mock("@/api/_lib/supabase.js", () => ({
  getSupabase: () => ({
    auth: { getUser: mockGetUser },
    from: mockFrom,
  }),
}));

vi.mock("@/api/_lib/encryption.js", () => ({
  decrypt: vi.fn((token: string) => `decrypted_${token}`),
  encrypt: vi.fn((token: string) => `encrypted_${token}`),
}));

vi.mock("@/api/_lib/logger.js", () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("@/api/_lib/rateLimiter.js", () => ({
  checkRateLimit: (...args: unknown[]) => mockCheckRateLimit(...args),
}));

// ---------------------------------------------------------------------------
// Import handler after mocks
// ---------------------------------------------------------------------------

const { default: handler } = await import("@/api/auth/threads/refresh");

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function makeReq(overrides: Record<string, unknown> = {}) {
  return {
    method: "POST",
    body: { accountId: "acc-123" },
    headers: { authorization: "Bearer valid-token" },
    ...overrides,
  } as any;
}

function makeRes() {
  const res: any = {
    statusCode: 200,
    body: null,
    headers: {} as Record<string, string>,
    status(code: number) {
      res.statusCode = code;
      return res;
    },
    json(data: unknown) {
      res.body = data;
      return res;
    },
    setHeader(key: string, value: string) {
      res.headers[key] = value;
      return res;
    },
  };
  return res;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  mockCheckRateLimit.mockResolvedValue({ allowed: true, remaining: 9 });
});

describe("auth/threads/refresh handler", () => {
  // ── Method validation ─────────────────────────────────────────────────────

  it("rejects non-POST methods with 405", async () => {
    const req = makeReq({ method: "GET" });
    const res = makeRes();
    await handler(req, res);
    expect(res.statusCode).toBe(405);
    expect(res.body.error).toContain("Method not allowed");
  });

  it("rejects PUT requests with 405", async () => {
    const req = makeReq({ method: "PUT" });
    const res = makeRes();
    await handler(req, res);
    expect(res.statusCode).toBe(405);
  });

  // ── Missing accountId ─────────────────────────────────────────────────────

  it("returns 400 when accountId is missing", async () => {
    const req = makeReq({ body: {} });
    const res = makeRes();
    await handler(req, res);
    expect(res.statusCode).toBe(400);
    expect(res.body.error).toContain("Account ID");
  });

  it("returns 400 when accountId is empty string", async () => {
    const req = makeReq({ body: { accountId: "" } });
    const res = makeRes();
    await handler(req, res);
    expect(res.statusCode).toBe(400);
  });

  // ── Auth header validation ────────────────────────────────────────────────

  it("returns 401 when authorization header is missing", async () => {
    const req = makeReq({ headers: {} });
    const res = makeRes();
    await handler(req, res);
    expect(res.statusCode).toBe(401);
    expect(res.body.error).toContain("authorization");
  });

  it("returns 401 when authorization header lacks Bearer prefix", async () => {
    const req = makeReq({ headers: { authorization: "Basic token" } });
    const res = makeRes();
    await handler(req, res);
    expect(res.statusCode).toBe(401);
  });

  it("returns 401 when Supabase auth.getUser fails", async () => {
    mockGetUser.mockResolvedValue({
      data: { user: null },
      error: new Error("Invalid token"),
    });
    const req = makeReq();
    const res = makeRes();
    await handler(req, res);
    expect(res.statusCode).toBe(401);
    expect(res.body.error).toContain("expired");
  });

  it("returns 401 when Supabase auth returns no user", async () => {
    mockGetUser.mockResolvedValue({
      data: { user: null },
      error: null,
    });
    const req = makeReq();
    const res = makeRes();
    await handler(req, res);
    expect(res.statusCode).toBe(401);
  });

  // ── Rate limiting ─────────────────────────────────────────────────────────

  it("returns 429 when rate limit is exceeded", async () => {
    mockGetUser.mockResolvedValue({
      data: { user: { id: "user-1" } },
      error: null,
    });
    mockCheckRateLimit
      .mockResolvedValueOnce({ allowed: true, remaining: 4 })
      .mockResolvedValueOnce({
        allowed: false,
        remaining: 0,
        retryAfterSeconds: 3600,
      });

    const req = makeReq();
    const res = makeRes();
    await handler(req, res);
    expect(res.statusCode).toBe(429);
    expect(res.headers["Retry-After"]).toBe("3600");
  });

  it("proceeds normally when rate limit allows", async () => {
    mockGetUser.mockResolvedValue({
      data: { user: { id: "user-1" } },
      error: null,
    });
    mockCheckRateLimit.mockResolvedValue({ allowed: true, remaining: 9 });

    // Account query returns no account
    const mockSelect = vi.fn().mockReturnValue({
      eq: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
        }),
      }),
    });
    mockFrom.mockReturnValue({ select: mockSelect });

    const req = makeReq();
    const res = makeRes();
    await handler(req, res);
    // Should get past rate limit and hit the "account not found" path
    expect(res.statusCode).toBe(404);
  });

  // ── Account not found ─────────────────────────────────────────────────────

  it("returns 404 when account is not found", async () => {
    mockGetUser.mockResolvedValue({
      data: { user: { id: "user-1" } },
      error: null,
    });

    const mockSelect = vi.fn().mockReturnValue({
      eq: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
        }),
      }),
    });
    mockFrom.mockReturnValue({ select: mockSelect });

    const req = makeReq();
    const res = makeRes();
    await handler(req, res);
    expect(res.statusCode).toBe(404);
    expect(res.body.error).toContain("not found");
  });

  // ── Missing token on account ──────────────────────────────────────────────

  it("returns 400 when account has no encrypted token", async () => {
    mockGetUser.mockResolvedValue({
      data: { user: { id: "user-1" } },
      error: null,
    });

    const mockSelect = vi.fn().mockReturnValue({
      eq: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({
            data: { id: "acc-123", threads_access_token_encrypted: null },
            error: null,
          }),
        }),
      }),
    });
    mockFrom.mockReturnValue({ select: mockSelect });

    const req = makeReq();
    const res = makeRes();
    await handler(req, res);
    expect(res.statusCode).toBe(400);
    expect(res.body.error).toContain("No access token");
  });

  // ── Rate limiter failure (fail open) ──────────────────────────────────────

  it("continues when rate limiter throws (fail-open)", async () => {
    mockGetUser.mockResolvedValue({
      data: { user: { id: "user-1" } },
      error: null,
    });
    mockCheckRateLimit
      .mockResolvedValueOnce({ allowed: true, remaining: 4 })
      .mockRejectedValueOnce(new Error("Redis down"));

    const mockSelect = vi.fn().mockReturnValue({
      eq: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
        }),
      }),
    });
    mockFrom.mockReturnValue({ select: mockSelect });

    const req = makeReq();
    const res = makeRes();
    await handler(req, res);
    // Should proceed past the rate limiter (fail open) and hit account-not-found
    expect(res.statusCode).toBe(404);
  });
});
