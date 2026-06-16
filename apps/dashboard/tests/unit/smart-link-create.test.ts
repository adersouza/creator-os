/**
 * Unit tests for Smart Link Create handler
 * (api/_lib/handlers/smart-links/create.ts)
 *
 * Covers: validation, tier limits, code uniqueness, post ownership,
 * duplicate code handling, cloaking warnings, and success path.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockGetUserTier = vi.fn();
const mockGenerateUniqueCode = vi.fn();
const mockGetAlternateRedirectErrors = vi.fn();
const mockGetCloakingWarnings = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock()
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/supabase.js", () => ({
  getSupabase: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/logger.js", () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}));

vi.mock("@/api/_lib/outboundUrlSecurity.js", () => ({
  validatePublicRedirectUrl: vi.fn().mockResolvedValue(null),
}));

vi.mock("@/api/_lib/apiResponse.js", () => ({
  apiError: (res: any, status: number, msg: string) =>
    res.status(status).json({ error: msg }),
  apiSuccess: (res: any, data: unknown, statusCode?: number) =>
    res.status(statusCode ?? 200).json({ data }),
}));

vi.mock("@/api/_lib/tierGate.js", () => ({
  getUserTier: (...args: unknown[]) => mockGetUserTier(...args),
}));

vi.mock("@/api/_lib/handlers/smart-links/shared.js", async () => {
  const { z } = await import("zod");

  return {
    CreateSchema: z.object({
      code: z
        .string()
        .min(2)
        .max(20)
        .regex(/^[a-zA-Z0-9_-]+$/, "Code must be alphanumeric")
        .optional(),
      target_url: z.string().url("Must be a valid URL"),
      title: z.string().max(255).optional(),
      ig_deep_link: z.string().optional(),
      threads_deep_link: z.string().optional(),
      ig_redirect_url: z.string().url().optional().or(z.literal("")),
      threads_redirect_url: z.string().url().optional().or(z.literal("")),
      mobile_redirect_url: z.string().url().optional().or(z.literal("")),
      enable_deep_links: z.boolean().optional(),
      post_id: z.string().optional().nullable(),
      est_conversion_rate: z.number().min(0).max(1).optional().nullable(),
      est_conversion_value: z.number().min(0).optional().nullable(),
    }),
    db: () => ({ from: mockFrom }),
    generateUniqueCode: (...args: unknown[]) => mockGenerateUniqueCode(...args),
    generateWebhookSecret: () => "test-webhook-secret".repeat(4),
    isReservedSmartLinkCode: (code: string) =>
      new Set(["analytics", "api", "convert", "r", "redirect", "track", "www"]).has(
        code.toLowerCase(),
      ),
    getAlternateRedirectErrors: (...args: unknown[]) =>
      mockGetAlternateRedirectErrors(...args),
    getCloakingWarnings: (...args: unknown[]) =>
      mockGetCloakingWarnings(...args),
    SMART_LINK_LIMITS: { free: 0, pro: 10, agency: 50, empire: 999 },
  };
});

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { handleCreate } from "@/api/_lib/handlers/smart-links/create";
const invokeHandleCreate = handleCreate as unknown as (req: any, res: any, userId: string) => Promise<void>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const USER_ID = "user-1";

function makeReq(body: Record<string, unknown> = {}) {
  return {
    method: "POST",
    query: { action: "create" },
    body,
    headers: {},
  } as any;
}

/**
 * Set up the standard mock chain for the smart_links table.
 * Supports: select count, select by code, insert.
 */
function stubSmartLinksDb(overrides: {
  linkCount?: number;
  existingCode?: boolean;
  insertData?: Record<string, unknown> | null;
  insertError?: { code?: string; message?: string } | null;
  ownedPost?: boolean;
} = {}) {
  mockFrom.mockImplementation((table: string) => {
    if (table === "smart_links") {
      return {
        select: vi.fn().mockImplementation((_cols: string, opts?: any) => {
          // Count query (tier limit check)
          if (opts?.count === "exact" && opts?.head === true) {
            return {
              eq: vi.fn().mockResolvedValue({
                count: overrides.linkCount ?? 0,
                error: null,
              }),
            };
          }
          // Code uniqueness check
          return {
            eq: vi.fn().mockImplementation((_field: string, _val: string) => {
              return {
                maybeSingle: vi.fn().mockResolvedValue({
                  data: overrides.existingCode ? { id: "existing-id" } : null,
                  error: null,
                }),
                eq: vi.fn().mockReturnValue({
                  maybeSingle: vi.fn().mockResolvedValue({
                    data: overrides.existingCode ? { id: "existing-id" } : null,
                    error: null,
                  }),
                }),
              };
            }),
          };
        }),
        insert: vi.fn().mockReturnValue({
          select: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: overrides.insertData ?? {
                id: "link-1",
                code: "abc123",
                target_url: "https://example.com",
              },
              error: overrides.insertError ?? null,
            }),
          }),
        }),
      };
    }
    if (table === "posts") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              maybeSingle: vi.fn().mockResolvedValue({
                data: overrides.ownedPost !== false ? { id: "post-1" } : null,
                error: null,
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

beforeEach(() => {
  vi.clearAllMocks();
  mockGetUserTier.mockResolvedValue("pro");
  mockGetAlternateRedirectErrors.mockReturnValue([]);
  mockGetCloakingWarnings.mockReturnValue([]);
  mockGenerateUniqueCode.mockResolvedValue("auto123");
});

describe("Smart Link Create handler", () => {
  // =========================================================================
  // Validation
  // =========================================================================

  it("returns 400 when target_url is missing", async () => {
    const res = mockRes();
    await invokeHandleCreate(makeReq({}), res, USER_ID);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("returns 400 when target_url is not a valid URL", async () => {
    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "not-a-url" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("returns 400 when code is too short", async () => {
    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com", code: "x" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("returns 400 when code has invalid characters", async () => {
    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com", code: "ab cd!" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("returns 400 when alternate redirect URLs are provided", async () => {
    mockGetAlternateRedirectErrors.mockReturnValue([
      "ig_redirect_url is no longer supported.",
    ]);
    stubSmartLinksDb();

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({
        target_url: "https://example.com",
        ig_redirect_url: "https://other.com",
      }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(400);
  });

  // =========================================================================
  // Tier Limits
  // =========================================================================

  it("returns 403 when free tier tries to create", async () => {
    mockGetUserTier.mockResolvedValue("free");
    stubSmartLinksDb({ linkCount: 0 });

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(403);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({
        error: expect.stringContaining("free plan allows 0"),
      }),
    );
  });

  it("returns 403 when pro tier exceeds 10 links", async () => {
    mockGetUserTier.mockResolvedValue("pro");
    stubSmartLinksDb({ linkCount: 10 });

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(403);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({
        error: expect.stringContaining("pro plan allows 10"),
      }),
    );
  });

  it("allows empire tier with many links", async () => {
    mockGetUserTier.mockResolvedValue("empire");
    stubSmartLinksDb({ linkCount: 500 });

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(201);
  });

  // =========================================================================
  // Code Uniqueness
  // =========================================================================

  it("returns 409 when custom code is already taken", async () => {
    stubSmartLinksDb({ existingCode: true });

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com", code: "mycode" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(409);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: "Code already taken" }),
    );
  });

  it("returns 400 when custom code is reserved for /go routes", async () => {
    stubSmartLinksDb({ existingCode: false });

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com", code: "convert" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: "Code is reserved" }),
    );
  });

  it("auto-generates code when none provided", async () => {
    stubSmartLinksDb();

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com" }),
      res,
      USER_ID,
    );
    expect(mockGenerateUniqueCode).toHaveBeenCalled();
    expect(res.status).toHaveBeenCalledWith(201);
  });

  it("uses custom code (lowercased) when provided and available", async () => {
    stubSmartLinksDb({ existingCode: false });

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com", code: "MyCode" }),
      res,
      USER_ID,
    );
    // Should not auto-generate since custom code was provided
    expect(mockGenerateUniqueCode).not.toHaveBeenCalled();
    expect(res.status).toHaveBeenCalledWith(201);
  });

  // =========================================================================
  // Post Ownership
  // =========================================================================

  it("returns 403 when post_id is not owned by user", async () => {
    stubSmartLinksDb({ ownedPost: false });

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com", post_id: "someone-elses-post" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(403);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({
        error: expect.stringContaining("not owned"),
      }),
    );
  });

  it("allows post_id when owned by user", async () => {
    stubSmartLinksDb({ ownedPost: true });

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com", post_id: "post-1" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(201);
  });

  // =========================================================================
  // DB Insert Errors
  // =========================================================================

  it("returns 409 on duplicate key DB error", async () => {
    stubSmartLinksDb({
      insertData: null,
      insertError: { code: "23505", message: "duplicate key value" },
    });

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(409);
  });

  it("returns 500 on generic DB error", async () => {
    stubSmartLinksDb({
      insertData: null,
      insertError: { code: "42000", message: "Some DB error" },
    });

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(500);
  });

  // =========================================================================
  // Cloaking Warnings
  // =========================================================================

  it("includes warnings in response when cloaking detected", async () => {
    mockGetCloakingWarnings.mockReturnValue([
      "ig_redirect_url points to different.com while target_url points to example.com",
    ]);
    stubSmartLinksDb();

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(201);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          warnings: expect.arrayContaining([
            expect.stringContaining("different.com"),
          ]),
        }),
      }),
    );
  });

  it("omits warnings when none detected", async () => {
    mockGetCloakingWarnings.mockReturnValue([]);
    stubSmartLinksDb();

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({ target_url: "https://example.com" }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(201);
    const responseData = res.json.mock.calls[0][0].data;
    expect(responseData).not.toHaveProperty("warnings");
  });

  // =========================================================================
  // Success Path
  // =========================================================================

  it("creates smart link with all optional fields", async () => {
    stubSmartLinksDb({
      insertData: {
        id: "link-1",
        code: "mylink",
        target_url: "https://example.com",
        title: "My Link",
        ig_deep_link: "instagram://user?username=test",
        enable_deep_links: true,
        est_conversion_rate: 0.05,
        est_conversion_value: 25.0,
      },
    });

    const res = mockRes();
    await invokeHandleCreate(
      makeReq({
        target_url: "https://example.com",
        code: "mylink",
        title: "My Link",
        ig_deep_link: "instagram://user?username=test",
        enable_deep_links: true,
        est_conversion_rate: 0.05,
        est_conversion_value: 25.0,
      }),
      res,
      USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(201);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          link: expect.objectContaining({
            id: "link-1",
            code: "mylink",
          }),
        }),
      }),
    );
  });
});
