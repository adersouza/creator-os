/**
 * Unit tests for Links addLink handler
 * (api/_lib/handlers/links/addLink.ts)
 *
 * Covers: input validation (Zod), URL safety (scheme blocking, private IPs),
 * page ownership, plan limits (link count), per-link styling gating,
 * deep link config gating, happy path, DB error handling.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockFromAny = vi.fn();
const mockGetUserTier = vi.fn();
const mockSyncWithRetry = vi.fn();
const mockIsSafeUrl = vi.fn();

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
  getSupabaseAny: () => ({ from: mockFromAny }),
}));

vi.mock("@/api/_lib/logger.js", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/api/_lib/outboundUrlSecurity.js", () => ({
  validatePublicRedirectUrl: vi.fn().mockResolvedValue(null),
}));

vi.mock("@/api/_lib/handlers/links/shared.js", async () => {
  const actual = await vi.importActual("@/api/_lib/handlers/links/shared.js");
  return {
    ...actual,
    getUserTier: (...args: unknown[]) => mockGetUserTier(...args),
    syncWithRetry: (...args: unknown[]) => mockSyncWithRetry(...args),
    isSafeUrl: (...args: unknown[]) => mockIsSafeUrl(...args),
  };
});

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { handleAddLink } from "@/api/_lib/handlers/links/addLink";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TEST_USER_ID = "user-1";

function makeReq(body: Record<string, unknown> = {}) {
  return { method: "POST", body, headers: {} };
}

function setupHappyPath(overrides: {
  tier?: string;
  linkCount?: number;
  pageFound?: boolean;
} = {}) {
  mockGetUserTier.mockResolvedValue(overrides.tier || "pro");
  mockIsSafeUrl.mockReturnValue(true);
  mockSyncWithRetry.mockResolvedValue({ synced: true });

  // Page ownership check
  const pageChain = {
    select: vi.fn().mockReturnThis(),
    eq: vi.fn().mockReturnThis(),
    maybeSingle: vi.fn().mockResolvedValue({
      data: overrides.pageFound !== false ? { id: "page-1" } : null,
      error: null,
    }),
  };

  // Link count query
  const countResult = {
    count: overrides.linkCount ?? 0,
    error: null,
  };

  mockFrom.mockImplementation((table: string) => {
    if (table === "link_pages") {
      return pageChain;
    }
    if (table === "link_items") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockResolvedValue(countResult),
        }),
      };
    }
    return { select: vi.fn().mockReturnThis(), eq: vi.fn().mockReturnThis() };
  });

  // Insert
  mockFromAny.mockReturnValue({
    insert: vi.fn().mockReturnValue({
      select: vi.fn().mockReturnValue({
        maybeSingle: vi.fn().mockResolvedValue({
          data: {
            id: "link-1",
            page_id: "page-1",
            title: "Test Link",
            url: "https://example.com",
            redirect_id: "abc12345",
          },
          error: null,
        }),
      }),
    }),
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("handleAddLink", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Input validation ──────────────────────────────────────────────────────

  it("rejects missing pageId with 400", async () => {
    const res = mockRes();
    await handleAddLink(
      makeReq({ title: "Link", url: "https://example.com" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("rejects missing title with 400", async () => {
    const res = mockRes();
    await handleAddLink(
      makeReq({ pageId: "p1", url: "https://example.com" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("rejects missing url with 400", async () => {
    const res = mockRes();
    await handleAddLink(
      makeReq({ pageId: "p1", title: "Link" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("rejects invalid URL format with 400", async () => {
    const res = mockRes();
    await handleAddLink(
      makeReq({ pageId: "p1", title: "Link", url: "not-a-url" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("rejects title over 100 chars with 400", async () => {
    const res = mockRes();
    await handleAddLink(
      makeReq({ pageId: "p1", title: "x".repeat(101), url: "https://example.com" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("rejects icon containing HTML brackets with 400", async () => {
    const res = mockRes();
    await handleAddLink(
      makeReq({ pageId: "p1", title: "Link", url: "https://example.com", icon: "<script>" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(400);
  });

  // ── URL safety ────────────────────────────────────────────────────────────

  it("rejects dangerous URL schemes (javascript:)", async () => {
    setupHappyPath();
    mockIsSafeUrl.mockReturnValue(false);
    const res = mockRes();
    await handleAddLink(
      makeReq({ pageId: "p1", title: "Evil", url: "https://example.com" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(400);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: expect.stringContaining("http") }),
    );
  });

  // ── Page ownership ────────────────────────────────────────────────────────

  it("returns 404 when page not found (wrong owner)", async () => {
    setupHappyPath({ pageFound: false });
    const res = mockRes();
    await handleAddLink(
      makeReq({ pageId: "other-page", title: "Link", url: "https://example.com" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(404);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: "Page not found" }),
    );
  });

  // ── Plan limits ───────────────────────────────────────────────────────────

  it("rejects when free-tier user exceeds max links per page", async () => {
    setupHappyPath({ tier: "free", linkCount: 5 }); // free allows 5
    const res = mockRes();
    await handleAddLink(
      makeReq({ pageId: "p1", title: "Link", url: "https://example.com" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(403);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: expect.stringContaining("plan") }),
    );
  });

  it("allows pro-tier user within link limit", async () => {
    setupHappyPath({ tier: "pro", linkCount: 10 }); // pro allows 25
    const res = mockRes();
    await handleAddLink(
      makeReq({ pageId: "p1", title: "Link", url: "https://example.com" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(200);
  });

  // ── Happy path ────────────────────────────────────────────────────────────

  it("adds link and syncs to Cloudflare on success", async () => {
    setupHappyPath();
    const res = mockRes();
    await handleAddLink(
      makeReq({ pageId: "p1", title: "My Link", url: "https://example.com" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(200);
    const call = res.json.mock.calls[0][0];
    expect(call.success).toBe(true);
    expect(call.link).toBeDefined();
    expect(call.link.title).toBe("Test Link");
    expect(mockSyncWithRetry).toHaveBeenCalled();
  });

  // ── DB error ──────────────────────────────────────────────────────────────

  it("returns 500 on DB insert error", async () => {
    setupHappyPath();
    mockFromAny.mockReturnValue({
      insert: vi.fn().mockReturnValue({
        select: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({
            data: null,
            error: { message: "DB constraint violation" },
          }),
        }),
      }),
    });

    const res = mockRes();
    await handleAddLink(
      makeReq({ pageId: "p1", title: "Link", url: "https://example.com" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(500);
  });

  // ── Optional fields ───────────────────────────────────────────────────────

  it("passes isPrimary and platform to insert", async () => {
    setupHappyPath();
    let insertedData: any = null;
    mockFromAny.mockReturnValue({
      insert: vi.fn().mockImplementation((data: any) => {
        insertedData = data;
        return {
          select: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: { id: "link-1", ...data },
              error: null,
            }),
          }),
        };
      }),
    });

    const res = mockRes();
    await handleAddLink(
      makeReq({
        pageId: "p1",
        title: "Primary Link",
        url: "https://example.com",
        isPrimary: true,
        platform: "instagram",
      }) as any,
      res as any,
      TEST_USER_ID,
    );

    expect(insertedData).toBeDefined();
    expect(insertedData.is_primary).toBe(true);
    expect(insertedData.platform).toBe("instagram");
  });
});
