/**
 * Unit tests for Links createPage handler
 * (api/_lib/handlers/links/createPage.ts)
 *
 * Covers: input validation (Zod schema), plan limits (page count),
 * slug uniqueness, slug TOCTOU race (DB constraint), premium feature gating,
 * happy path, Cloudflare sync, DB error handling.
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

vi.mock("@/api/_lib/handlers/links/shared.js", async () => {
  const actual = await vi.importActual("@/api/_lib/handlers/links/shared.js");
  return {
    ...actual,
    getUserTier: (...args: unknown[]) => mockGetUserTier(...args),
    syncWithRetry: (...args: unknown[]) => mockSyncWithRetry(...args),
  };
});

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { handleCreatePage } from "@/api/_lib/handlers/links/createPage";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const TEST_USER_ID = "user-1";

function makeReq(body: Record<string, unknown> = {}) {
  return { method: "POST", body, headers: {} };
}

/** Set up supabase mocks for happy path */
function setupHappyPath(overrides: {
  tier?: string;
  pageCount?: number;
  existingSlug?: boolean;
} = {}) {
  mockGetUserTier.mockResolvedValue(overrides.tier || "pro");

  mockFrom.mockImplementation((table: string) => {
    if (table === "link_pages") {
      return {
        select: vi.fn().mockImplementation((_cols: string, opts?: any) => {
          if (opts?.count === "exact") {
            // Page count query: .select("*", {count:"exact", head:true}).eq("user_id", userId)
            return {
              eq: vi.fn().mockResolvedValue({
                count: overrides.pageCount ?? 0,
                error: null,
              }),
            };
          }
          // Slug check query: .select("id").eq("slug", slug).maybeSingle()
          return {
            eq: vi.fn().mockReturnValue({
              maybeSingle: vi.fn().mockResolvedValue({
                data: overrides.existingSlug ? { id: "existing-page-id" } : null,
                error: null,
              }),
            }),
          };
        }),
      };
    }
    return { select: vi.fn().mockReturnThis(), eq: vi.fn().mockReturnThis() };
  });

  // Insert via getSupabaseAny
  const insertedPage = {
    id: "page-1",
    slug: "my-page",
    title: "My Page",
    user_id: TEST_USER_ID,
  };

  mockFromAny.mockReturnValue({
    insert: vi.fn().mockReturnValue({
      select: vi.fn().mockReturnValue({
        maybeSingle: vi.fn().mockResolvedValue({
          data: insertedPage,
          error: null,
        }),
      }),
    }),
  });

  mockSyncWithRetry.mockResolvedValue({ synced: true });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("handleCreatePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Input validation ──────────────────────────────────────────────────────

  it("rejects missing slug with 400", async () => {
    const res = mockRes();
    await handleCreatePage(makeReq({}) as any, res as any, TEST_USER_ID);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("rejects empty slug with 400", async () => {
    const res = mockRes();
    await handleCreatePage(makeReq({ slug: "" }) as any, res as any, TEST_USER_ID);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("rejects slug with invalid characters with 400", async () => {
    const res = mockRes();
    await handleCreatePage(makeReq({ slug: "my page!" }) as any, res as any, TEST_USER_ID);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("rejects slug over 50 chars with 400", async () => {
    const res = mockRes();
    await handleCreatePage(
      makeReq({ slug: "a".repeat(51) }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("accepts valid slug with hyphens and underscores", async () => {
    setupHappyPath();
    const res = mockRes();
    await handleCreatePage(
      makeReq({ slug: "my-cool_page123" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(200);
  });

  it("rejects invalid hex color for backgroundColor", async () => {
    const res = mockRes();
    await handleCreatePage(
      makeReq({ slug: "test", backgroundColor: "not-a-color" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(400);
  });

  // ── Plan limits ───────────────────────────────────────────────────────────

  it("rejects when free-tier user exceeds max pages", async () => {
    setupHappyPath({ tier: "free", pageCount: 1 });
    const res = mockRes();
    await handleCreatePage(
      makeReq({ slug: "new-page" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(403);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: expect.stringContaining("plan") }),
    );
  });

  it("allows pro-tier user within page limit", async () => {
    setupHappyPath({ tier: "pro", pageCount: 2 }); // pro allows 3
    const res = mockRes();
    await handleCreatePage(
      makeReq({ slug: "new-page" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(200);
  });

  // ── Slug uniqueness ───────────────────────────────────────────────────────

  it("rejects duplicate slug with 409", async () => {
    setupHappyPath({ existingSlug: true });
    const res = mockRes();
    await handleCreatePage(
      makeReq({ slug: "taken-slug" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(409);
    expect(res.json).toHaveBeenCalledWith(
      expect.objectContaining({ error: expect.stringContaining("Slug already taken") }),
    );
  });

  // ── TOCTOU race (DB constraint) ──────────────────────────────────────────

  it("handles DB duplicate key constraint (TOCTOU race) with 409", async () => {
    setupHappyPath();
    // Override the insert to simulate DB constraint violation
    mockFromAny.mockReturnValue({
      insert: vi.fn().mockReturnValue({
        select: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({
            data: null,
            error: { code: "23505", message: "duplicate key" },
          }),
        }),
      }),
    });

    const res = mockRes();
    await handleCreatePage(
      makeReq({ slug: "race-slug" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(409);
  });

  // ── Happy path ────────────────────────────────────────────────────────────

  it("creates page and syncs to Cloudflare on success", async () => {
    setupHappyPath();
    const res = mockRes();
    await handleCreatePage(
      makeReq({ slug: "my-page", title: "My Page" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(200);
    const call = res.json.mock.calls[0][0];
    expect(call.success).toBe(true);
    expect(call.page).toBeDefined();
    expect(call.cfSync).toBe(true);
    expect(mockSyncWithRetry).toHaveBeenCalled();
  });

  // ── DB error ──────────────────────────────────────────────────────────────

  it("returns 500 on generic DB insert error", async () => {
    setupHappyPath();
    mockFromAny.mockReturnValue({
      insert: vi.fn().mockReturnValue({
        select: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({
            data: null,
            error: { code: "42000", message: "some DB error" },
          }),
        }),
      }),
    });

    const res = mockRes();
    await handleCreatePage(
      makeReq({ slug: "test-page" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(500);
  });

  it("returns 500 when insert returns null data without error", async () => {
    setupHappyPath();
    mockFromAny.mockReturnValue({
      insert: vi.fn().mockReturnValue({
        select: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({
            data: null,
            error: null,
          }),
        }),
      }),
    });

    const res = mockRes();
    await handleCreatePage(
      makeReq({ slug: "test-page" }) as any,
      res as any,
      TEST_USER_ID,
    );
    expect(res.status).toHaveBeenCalledWith(500);
  });

  // ── Premium feature gating ────────────────────────────────────────────────

  it("strips deeplink escape for free-tier users", async () => {
    setupHappyPath({ tier: "free" });
    // Override count to allow page creation
    mockFrom.mockImplementation((table: string) => {
      if (table === "link_pages") {
        return {
          select: vi.fn().mockImplementation((_cols: string, opts?: any) => {
            if (opts?.count === "exact") {
              return {
                eq: vi.fn().mockReturnValue({
                  eq: vi.fn().mockResolvedValue({ count: 0, error: null }),
                }),
              };
            }
            return {
              eq: vi.fn().mockReturnValue({
                maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
              }),
            };
          }),
        };
      }
      return { select: vi.fn().mockReturnThis() };
    });

    // Track what gets inserted
    let insertedData: any = null;
    mockFromAny.mockReturnValue({
      insert: vi.fn().mockImplementation((data: any) => {
        insertedData = data;
        return {
          select: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: { id: "page-1", slug: "test", ...data },
              error: null,
            }),
          }),
        };
      }),
    });

    const res = mockRes();
    await handleCreatePage(
      makeReq({ slug: "test", enableDeeplinkEscape: true }) as any,
      res as any,
      TEST_USER_ID,
    );

    expect(insertedData.enable_deeplink_escape).toBe(false);
  });
});
