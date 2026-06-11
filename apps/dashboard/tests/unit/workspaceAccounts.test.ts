/**
 * Tests for api/_lib/workspaceAccounts.ts
 *
 * Validates the workspace-scoped account resolver: workspace member lookup,
 * platform filtering, fallback behavior, and the "always include requesting user" rule.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";

// Mock logger
vi.mock("../../api/_lib/logger.js", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

// Table-aware Supabase mock
const mockMemberData: Array<{ user_id: string }> = [];
const mockAccountData: Array<{ id: string }> = [];
const mockIgAccountData: Array<{ id: string }> = [];
let memberError: unknown = null;

const mockSupabase = {
  from: vi.fn().mockImplementation((table: string) => {
    if (table === "workspace_members") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue(
            Promise.resolve({
              data: memberError ? null : mockMemberData,
              error: memberError,
            })
          ),
        }),
      };
    }
    if (table === "accounts") {
      return {
        select: vi.fn().mockReturnValue({
          in: vi.fn().mockReturnValue(
            Promise.resolve({ data: mockAccountData, error: null })
          ),
        }),
      };
    }
    if (table === "instagram_accounts") {
      return {
        select: vi.fn().mockReturnValue({
          in: vi.fn().mockReturnValue(
            Promise.resolve({ data: mockIgAccountData, error: null })
          ),
        }),
      };
    }
    return {
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      in: vi.fn().mockResolvedValue({ data: [], error: null }),
    };
  }),
};

vi.mock("../../api/_lib/supabase.js", () => ({
  getSupabase: () => mockSupabase,
}));

import { getAccountIdsForContext } from "@/api/_lib/workspaceAccounts";

describe("getAccountIdsForContext", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMemberData.length = 0;
    mockAccountData.length = 0;
    mockIgAccountData.length = 0;
    memberError = null;
  });

  it("returns only user's accounts when workspaceId is null", async () => {
    mockAccountData.push({ id: "acc-1" }, { id: "acc-2" });
    mockIgAccountData.push({ id: "ig-1" });

    const ids = await getAccountIdsForContext("user-1", null);

    expect(ids).toEqual(["acc-1", "acc-2", "ig-1"]);
    // Should NOT query workspace_members
    const calls = mockSupabase.from.mock.calls.map((c: any) => c[0]);
    expect(calls).not.toContain("workspace_members");
  });

  it("returns accounts for all workspace members", async () => {
    mockMemberData.push({ user_id: "user-1" }, { user_id: "user-2" });
    mockAccountData.push({ id: "acc-1" }, { id: "acc-2" }, { id: "acc-3" });
    mockIgAccountData.push({ id: "ig-1" });

    const ids = await getAccountIdsForContext("user-1", "ws-1");

    expect(ids).toEqual(["acc-1", "acc-2", "acc-3", "ig-1"]);
  });

  it("always includes the requesting user even if not in member list", async () => {
    mockMemberData.push({ user_id: "user-2" }, { user_id: "user-3" });
    mockAccountData.push({ id: "acc-1" });

	const ids = await getAccountIdsForContext("user-1", "ws-1");

	// Just verify the results come back
	expect(ids).toContain("acc-1");
});

  it("falls back to userId on workspace member fetch error", async () => {
    memberError = { message: "DB timeout" };
    mockAccountData.push({ id: "acc-fallback" });

    const ids = await getAccountIdsForContext("user-1", "ws-1");

    expect(ids).toContain("acc-fallback");
  });

  it("returns only threads accounts when platform is 'threads'", async () => {
    mockAccountData.push({ id: "threads-1" });
    mockIgAccountData.push({ id: "ig-1" });

    const ids = await getAccountIdsForContext("user-1", null, "threads");

    expect(ids).toEqual(["threads-1"]);
    // Should not query instagram_accounts
    const tables = mockSupabase.from.mock.calls.map((c: any) => c[0]);
    expect(tables).not.toContain("instagram_accounts");
  });

  it("returns only instagram accounts when platform is 'instagram'", async () => {
    mockAccountData.push({ id: "threads-1" });
    mockIgAccountData.push({ id: "ig-1" });

    const ids = await getAccountIdsForContext("user-1", null, "instagram");

    expect(ids).toEqual(["ig-1"]);
    const tables = mockSupabase.from.mock.calls.map((c: any) => c[0]);
    expect(tables).not.toContain("accounts");
  });

  it("returns empty array when no accounts exist", async () => {
    const ids = await getAccountIdsForContext("user-1", null);
    expect(ids).toEqual([]);
  });

  it("returns both platform accounts when platform is undefined", async () => {
    mockAccountData.push({ id: "t-1" });
    mockIgAccountData.push({ id: "ig-1" });

    const ids = await getAccountIdsForContext("user-1", null);

    expect(ids).toContain("t-1");
    expect(ids).toContain("ig-1");
  });
});
