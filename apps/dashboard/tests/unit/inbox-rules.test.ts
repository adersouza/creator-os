/**
 * Unit tests for Inbox Rules handler
 * (api/_lib/handlers/inbox/rules.ts)
 *
 * Covers: action routing, validation, workspace IDOR protection,
 * CRUD operations (list, create, update, delete, toggle),
 * unknown actions, audit logging
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockRes } from "../helpers/mockFactories";

// ---------------------------------------------------------------------------
// Mock fns
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockApiError = vi.fn();
const mockApiSuccess = vi.fn();
const mockVerifyWorkspaceAccess = vi.fn();
const mockLogAudit = vi.fn();
const mockRequireMinTier = vi.fn();

// ---------------------------------------------------------------------------
// vi.mock()
// ---------------------------------------------------------------------------

vi.mock("@/api/_lib/supabase", () => ({
  getSupabase: () => ({ from: mockFrom }),
  getSupabaseAny: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/logger", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/api/_lib/apiResponse", () => ({
  apiError: (...args: unknown[]) => mockApiError(...args),
  apiSuccess: (...args: unknown[]) => mockApiSuccess(...args),
  badRequest: (res: any, msg: string) => mockApiError(res, 400, msg),
  methodNotAllowed: (res: any) => mockApiError(res, 405, "Method not allowed"),
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
      return handler(req, res, { user, userDb, adminDb: userDb, adminDbAny: userDb });
    };
  },
}));

vi.mock("@/api/_lib/workspaceAccess", () => ({
  verifyWorkspaceAccess: (...args: unknown[]) => mockVerifyWorkspaceAccess(...args),
}));

vi.mock("@/api/_lib/tierGate", () => ({
  requireMinTier: (...args: unknown[]) => mockRequireMinTier(...args),
}));

vi.mock("@/api/_lib/auditLog", () => ({
  logAudit: (...args: unknown[]) => mockLogAudit(...args),
}));

// ---------------------------------------------------------------------------
// Import module under test
// ---------------------------------------------------------------------------

import rulesHandler from "@/api/_lib/handlers/inbox/rules";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockReq(overrides: Record<string, unknown> = {}) {
  return {
    method: "POST",
    query: {},
    body: {},
    headers: {},
    ...overrides,
  };
}

function setupRulesMock(config: {
  rules?: any[];
  rulesError?: any;
  insertedRule?: any;
  insertError?: any;
  existingRule?: any;
  updatedRule?: any;
  updateError?: any;
  deleteError?: any;
}) {
  mockFrom.mockImplementation((table: string) => {
    if (table === "auto_reply_rules") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            order: vi.fn().mockResolvedValue({
              data: config.rules ?? [],
              error: config.rulesError ?? null,
            }),
            maybeSingle: vi.fn().mockResolvedValue({
              data: config.existingRule ?? { workspace_id: "ws-1" },
              error: null,
            }),
          }),
        }),
        insert: vi.fn().mockReturnValue({
          select: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: config.insertedRule ?? { id: "rule-1" },
              error: config.insertError ?? null,
            }),
          }),
        }),
        update: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            select: vi.fn().mockReturnValue({
              maybeSingle: vi.fn().mockResolvedValue({
                data: config.updatedRule ?? { id: "rule-1" },
                error: config.updateError ?? null,
              }),
            }),
          }),
        }),
        delete: vi.fn().mockReturnValue({
          eq: vi.fn().mockResolvedValue({
            error: config.deleteError ?? null,
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

describe("inbox/rules handler", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockVerifyWorkspaceAccess.mockResolvedValue(true);
    mockRequireMinTier.mockResolvedValue(true);
  });

  // ── Method validation ─────────────────────────────────────────────────────

  it("rejects non-POST methods", async () => {
    const req = mockReq({ method: "GET" });
    const res = mockRes();
    await rulesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 405, "Method not allowed");
  });

  // ── action=list ───────────────────────────────────────────────────────────

  it("list: returns rules for workspace", async () => {
    const rules = [{ id: "r1", trigger_type: "keyword" }];
    setupRulesMock({ rules });
    const req = mockReq({
      query: { action: "list" },
      body: { workspace_id: "ws-1" },
    });
    const res = mockRes();
    await rulesHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { rules });
  });

  it("list: rejects missing workspace_id", async () => {
    setupRulesMock({});
    const req = mockReq({
      query: { action: "list" },
      body: {},
    });
    const res = mockRes();
    await rulesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, expect.stringContaining("Invalid input"));
  });

  it("list: rejects non-member workspace", async () => {
    mockVerifyWorkspaceAccess.mockResolvedValue(false);
    setupRulesMock({});
    const req = mockReq({
      query: { action: "list" },
      body: { workspace_id: "ws-other" },
    });
    const res = mockRes();
    await rulesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 403, "Not a member of this workspace");
  });

  // ── action=create ─────────────────────────────────────────────────────────

  it("create: creates rule with valid input", async () => {
    setupRulesMock({ insertedRule: { id: "rule-1" } });
    const req = mockReq({
      query: { action: "create" },
      body: {
        workspace_id: "ws-1",
        trigger_type: "keyword",
        trigger_pattern: "hello",
        reply_text: "Hi there!",
      },
    });
    const res = mockRes();
    await rulesHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, { rule: { id: "rule-1" } }, 201);
    expect(mockLogAudit).toHaveBeenCalledWith(
      "user-1",
      "inbox-rule.create",
      expect.any(Object),
    );
  });

  it("create: rejects missing required fields", async () => {
    setupRulesMock({});
    const req = mockReq({
      query: { action: "create" },
      body: { workspace_id: "ws-1" },
    });
    const res = mockRes();
    await rulesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, expect.any(String));
  });

  // ── action=update (IDOR protection) ───────────────────────────────────────

  it("update: rejects when rule belongs to another workspace", async () => {
    mockVerifyWorkspaceAccess.mockResolvedValue(false);
    setupRulesMock({ existingRule: { workspace_id: "ws-other" } });
    const req = mockReq({
      query: { action: "update" },
      body: { id: "rule-1", reply_text: "Updated" },
    });
    const res = mockRes();
    await rulesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 403, "Not authorized to modify this rule");
  });

  // ── action=delete (IDOR protection) ───────────────────────────────────────

  it("delete: rejects when rule belongs to another workspace", async () => {
    mockVerifyWorkspaceAccess.mockResolvedValue(false);
    setupRulesMock({ existingRule: { workspace_id: "ws-other" } });
    const req = mockReq({
      query: { action: "delete" },
      body: { id: "rule-1" },
    });
    const res = mockRes();
    await rulesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 403, "Not authorized to delete this rule");
  });

  it("delete: logs audit on success", async () => {
    setupRulesMock({});
    const req = mockReq({
      query: { action: "delete" },
      body: { id: "rule-1" },
    });
    const res = mockRes();
    await rulesHandler(req as any, res as any);
    expect(mockLogAudit).toHaveBeenCalledWith(
      "user-1",
      "inbox-rule.delete",
      expect.any(Object),
    );
  });

  // ── action=toggle ─────────────────────────────────────────────────────────

  it("toggle: toggles rule active state", async () => {
    setupRulesMock({ updatedRule: { id: "rule-1", is_active: false } });
    const req = mockReq({
      query: { action: "toggle" },
      body: { id: "rule-1", is_active: false },
    });
    const res = mockRes();
    await rulesHandler(req as any, res as any);
    expect(mockApiSuccess).toHaveBeenCalledWith(res, {
      rule: { id: "rule-1", is_active: false },
    });
  });

  it("toggle: rejects missing is_active", async () => {
    setupRulesMock({});
    const req = mockReq({
      query: { action: "toggle" },
      body: { id: "rule-1" },
    });
    const res = mockRes();
    await rulesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, expect.any(String));
  });

  // ── Unknown action ────────────────────────────────────────────────────────

  it("rejects unknown action", async () => {
    const req = mockReq({
      query: { action: "explode" },
      body: {},
    });
    const res = mockRes();
    await rulesHandler(req as any, res as any);
    expect(mockApiError).toHaveBeenCalledWith(res, 400, "Unknown action: explode");
  });
});
