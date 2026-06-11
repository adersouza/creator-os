/**
 * Unit tests for Agent Notes handler
 * (api/_lib/handlers/agent/notes.ts)
 *
 * Covers: GET list, POST upsert/delete, validation, ownership verification
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockApiError = vi.fn();
const mockApiSuccess = vi.fn();

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

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import notesHandler from "@/api/_lib/handlers/agent/notes";

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

/** Build a Supabase chain mock for the agent_notes and account_groups tables */
function setupFromMock(config: {
  groupOwned?: boolean;
  notes?: any[];
  notesError?: any;
  existingNote?: any;
  updateError?: any;
  insertError?: any;
  deleteResult?: { data: any; error: any };
}) {
  mockFrom.mockImplementation((table: string) => {
    if (table === "account_groups") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              maybeSingle: vi.fn().mockResolvedValue({
                data: config.groupOwned !== false ? { id: "group-1" } : null,
              }),
            }),
          }),
        }),
      };
    }

    if (table === "agent_notes") {
      const chain: any = {};
      // select
      chain.select = vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            is: vi.fn().mockReturnValue({
              maybeSingle: vi.fn().mockResolvedValue({
                data: config.existingNote ?? null,
              }),
            }),
            maybeSingle: vi.fn().mockResolvedValue({
              data: config.existingNote ?? null,
            }),
          }),
          order: vi.fn().mockResolvedValue({
            data: config.notes ?? [],
            error: config.notesError ?? null,
          }),
        }),
        eq2: vi.fn(),
      });
      // For GET: select > eq > order
      const orderResult = {
        data: config.notes ?? [],
        error: config.notesError ?? null,
      };
      const eqChainForGet: any = {
        order: vi.fn().mockResolvedValue(orderResult),
        eq: vi.fn().mockReturnThis(),
      };
      eqChainForGet.eq = vi.fn().mockReturnValue(eqChainForGet);

      // For POST find existing: select > eq > eq > is/eq > maybeSingle
      const maybeSingleFn = vi.fn().mockResolvedValue({ data: config.existingNote ?? null });
      const isNullChain = { maybeSingle: maybeSingleFn };
      const innerEqChain: any = {
        eq: vi.fn().mockReturnValue({ maybeSingle: maybeSingleFn }),
        is: vi.fn().mockReturnValue(isNullChain),
        maybeSingle: maybeSingleFn,
      };
      const outerEqChain: any = {
        eq: vi.fn().mockReturnValue(innerEqChain),
        order: vi.fn().mockResolvedValue(orderResult),
      };

      chain.select = vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue(outerEqChain),
      });

      // update
      chain.update = vi.fn().mockReturnValue({
        eq: vi.fn().mockResolvedValue({ error: config.updateError ?? null }),
      });

      // insert
      chain.insert = vi.fn().mockResolvedValue({ error: config.insertError ?? null });

      // delete
      const deleteSelectChain: any = {
        eq: vi.fn().mockReturnThis(),
        is: vi.fn().mockReturnThis(),
        maybeSingle: vi.fn().mockResolvedValue(config.deleteResult ?? { data: null, error: null }),
      };
      chain.delete = vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            select: vi.fn().mockReturnValue(deleteSelectChain),
          }),
        }),
      });

      return chain;
    }

    // Fallback
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

describe("agent/notes handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── Method validation ─────────────────────────────────────────────────────

  it("rejects unsupported HTTP methods", async () => {
    const req = mockReq({ method: "DELETE" });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 405, "Method not allowed");
  });

  it("rejects PUT method", async () => {
    const req = mockReq({ method: "PUT" });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 405, "Method not allowed");
  });

  // ── GET: list notes ───────────────────────────────────────────────────────

  it("GET returns notes list", async () => {
    const notes = [
      { id: "n1", key: "k1", value: "v1" },
      { id: "n2", key: "k2", value: "v2" },
    ];
    setupFromMock({ notes });
    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { notes });
  });

  it("GET returns empty array when no notes", async () => {
    setupFromMock({ notes: [] });
    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { notes: [] });
  });

  it("GET with unowned accountGroupId returns 404", async () => {
    setupFromMock({ groupOwned: false });
    const req = mockReq({
      method: "GET",
      query: { accountGroupId: "group-999" },
    });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 404, "Account group not found");
  });

  it("GET returns 500 on DB error", async () => {
    setupFromMock({ notesError: { message: "db failure" } });
    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(
      res, 500, "Failed to fetch notes",
      expect.objectContaining({ details: "db failure" }),
    );
  });

  // ── POST: validation ──────────────────────────────────────────────────────

  it("POST rejects missing action", async () => {
    setupFromMock({});
    const req = mockReq({ method: "POST", body: { key: "test" } });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "action must be 'upsert' or 'delete'");
  });

  it("POST rejects invalid action value", async () => {
    setupFromMock({});
    const req = mockReq({ method: "POST", body: { action: "update", key: "test" } });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "action must be 'upsert' or 'delete'");
  });

  it("POST rejects missing key", async () => {
    setupFromMock({});
    const req = mockReq({ method: "POST", body: { action: "upsert" } });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "key is required");
  });

  it("POST rejects key over 200 characters", async () => {
    setupFromMock({});
    const req = mockReq({
      method: "POST",
      body: { action: "upsert", key: "a".repeat(201), value: "x" },
    });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "key must be at most 200 characters");
  });

  it("POST upsert rejects missing value", async () => {
    setupFromMock({});
    const req = mockReq({
      method: "POST",
      body: { action: "upsert", key: "test-key" },
    });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "value is required for upsert");
  });

  it("POST upsert rejects value over 5000 characters", async () => {
    setupFromMock({});
    const req = mockReq({
      method: "POST",
      body: { action: "upsert", key: "test-key", value: "x".repeat(5001) },
    });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "value must be at most 5000 characters");
  });

  // ── POST: upsert (create) ─────────────────────────────────────────────────

  it("POST upsert creates new note when none exists", async () => {
    setupFromMock({ existingNote: null, insertError: null });
    const req = mockReq({
      method: "POST",
      body: { action: "upsert", key: "new-key", value: "new-value" },
    });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { action: "created", key: "new-key" });
  });

  // ── POST: upsert (update) ─────────────────────────────────────────────────

  it("POST upsert updates existing note", async () => {
    setupFromMock({ existingNote: { id: "n1" }, updateError: null });
    const req = mockReq({
      method: "POST",
      body: { action: "upsert", key: "existing-key", value: "updated-value" },
    });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { action: "updated", key: "existing-key" });
  });

  // ── POST: delete ──────────────────────────────────────────────────────────

  it("POST delete returns 404 when note not found", async () => {
    setupFromMock({ deleteResult: { data: null, error: null } });
    const req = mockReq({
      method: "POST",
      body: { action: "delete", key: "missing-key" },
    });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 404, "Note not found");
  });

  // ── POST: accountGroupId ownership ────────────────────────────────────────

  it("POST rejects unowned accountGroupId", async () => {
    setupFromMock({ groupOwned: false });
    const req = mockReq({
      method: "POST",
      body: { action: "upsert", key: "test", value: "val", accountGroupId: "group-999" },
    });
    const res = mockRes();
    await notesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 404, "Account group not found");
  });
});
