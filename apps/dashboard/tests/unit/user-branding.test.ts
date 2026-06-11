/**
 * Unit tests for Agency Branding handler
 * (api/_lib/handlers/user/branding.ts)
 *
 * Covers: tier gating (agency+), GET branding, POST upsert,
 * logo upload validation (format, size), logo removal,
 * method validation, error handling
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
const mockStorageFrom = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock()
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/supabase", () => ({
  getSupabase: () => ({
    from: mockFrom,
    storage: { from: mockStorageFrom },
  }),
}));

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
      const db = {
        from: mockFrom,
        storage: { from: mockStorageFrom },
      };
      return handler(req, res, {
        user,
        userDb: db,
        adminDb: db,
        adminDbAny: db,
      });
    };
  },
}));

vi.mock("@/api/_lib/tierGate", () => ({
  requireMinTier: (...args: unknown[]) => mockRequireMinTier(...args),
}));

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import brandingHandler from "@/api/_lib/handlers/user/branding";

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

function setupBrandingMock(config: {
  branding?: any;
  selectError?: any;
  upsertResult?: any;
  upsertError?: any;
}) {
  mockFrom.mockImplementation((table: string) => {
    if (table === "agency_branding") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: config.branding ?? null,
              error: config.selectError ?? null,
            }),
          }),
        }),
        upsert: vi.fn().mockReturnValue({
          select: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: config.upsertResult ?? { agency_name: "Test Agency" },
              error: config.upsertError ?? null,
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

describe("user/branding handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRequireMinTier.mockResolvedValue(true);
    mockStorageFrom.mockReturnValue({
      upload: vi.fn().mockResolvedValue({ error: null }),
      getPublicUrl: vi.fn().mockReturnValue({
        data: { publicUrl: "https://storage.example.com/logo.png" },
      }),
    });
  });

  // ── Tier gating ───────────────────────────────────────────────────────────

  it("blocks non-agency tier users", async () => {
    mockRequireMinTier.mockResolvedValue(false);
    const req = mockReq();
    const res = mockRes();
    await brandingHandler(req as any, res as any);
    expect(mockRequireMinTier).toHaveBeenCalledWith("user-1", "agency", res);
    expect(mockApiSuccess).not.toHaveBeenCalled();
  });

  // ── Method validation ─────────────────────────────────────────────────────

  it("rejects unsupported methods", async () => {
    const req = mockReq({ method: "DELETE" });
    const res = mockRes();
    await brandingHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 405, "Method not allowed");
  });

  // ── GET ───────────────────────────────────────────────────────────────────

  it("GET returns branding data", async () => {
    const branding = {
      agency_name: "My Agency",
      agency_logo_url: "https://logo.png",
      brand_color: "#ff0000",
      updated_at: "2026-04-15",
    };
    setupBrandingMock({ branding });
    const req = mockReq();
    const res = mockRes();
    await brandingHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { branding });
  });

  it("GET returns null branding when none exists", async () => {
    setupBrandingMock({});
    const req = mockReq();
    const res = mockRes();
    await brandingHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { branding: null });
  });

  it("GET returns 500 on DB error", async () => {
    setupBrandingMock({ selectError: { message: "db fail" } });
    const req = mockReq();
    const res = mockRes();
    await brandingHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 500, "Internal server error");
  });

  // ── POST: update branding ─────────────────────────────────────────────────

  it("POST updates agency name and color", async () => {
    setupBrandingMock({
      upsertResult: {
        agency_name: "New Agency",
        brand_color: "#00ff00",
        agency_logo_url: null,
        updated_at: "2026-04-15",
      },
    });
    const req = mockReq({
      method: "POST",
      body: { agency_name: "New Agency", brand_color: "#00ff00" },
    });
    const res = mockRes();
    await brandingHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, {
      branding: expect.objectContaining({ agency_name: "New Agency" }),
    });
  });

  it("POST rejects invalid input", async () => {
    setupBrandingMock({});
    const req = mockReq({
      method: "POST",
      body: { agency_name: "x".repeat(201) },
    });
    const res = mockRes();
    await brandingHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, expect.stringContaining("Invalid input"));
  });

  it("POST rejects invalid logo base64 format", async () => {
    setupBrandingMock({});
    const req = mockReq({
      method: "POST",
      body: { logo_base64: "not-valid-base64" },
    });
    const res = mockRes();
    await brandingHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "Invalid image format. Use image/* base64.");
  });

  it("POST rejects logo over 500KB", async () => {
    setupBrandingMock({});
    // Create a base64 string that decodes to >500KB
    const largeData = Buffer.alloc(501 * 1024).toString("base64");
    const req = mockReq({
      method: "POST",
      body: { logo_base64: `data:image/png;base64,${largeData}` },
    });
    const res = mockRes();
    await brandingHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "Logo must be under 500KB");
  });

  it("POST handles logo removal", async () => {
    setupBrandingMock({
      upsertResult: {
        agency_name: "Agency",
        agency_logo_url: null,
        brand_color: null,
        updated_at: "2026-04-15",
      },
    });
    const req = mockReq({
      method: "POST",
      body: { remove_logo: true },
    });
    const res = mockRes();
    await brandingHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, {
      branding: expect.objectContaining({ agency_logo_url: null }),
    });
  });

  it("POST returns 500 on upsert error", async () => {
    setupBrandingMock({ upsertError: { message: "db error" } });
    const req = mockReq({
      method: "POST",
      body: { agency_name: "Test" },
    });
    const res = mockRes();
    await brandingHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 500, "Internal server error");
  });
});
