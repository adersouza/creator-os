/**
 * Tests that verifyAccountWorkspaceAccess — the function called by API routes
 * that back MCP tools like get_analytics, get_competitor_metrics, etc. —
 * prevents cross-workspace data bleed.
 *
 * Scenario: Claude is operating in Workspace A. It calls a tool with an
 * accountId that belongs to Workspace B (a different agency's account).
 * The backend must return false and the route must return 404.
 *
 * All DB calls are mocked to avoid a live database dependency.
 * Mock structure follows the pattern in postAuthorization.test.ts.
 */

import { describe, it, expect } from "vitest";
import {
	getWorkspaceAccess,
	verifyAccountWorkspaceAccess,
	verifyWorkspaceAccess,
	workspaceAccessHasRole,
} from "../../api/_lib/workspaceAccess.js";

// ---------------------------------------------------------------------------
// Mock Supabase client factory
//
// Three call shapes this function handles:
//
//  call 1 (account lookup):
//    .from("accounts"|"instagram_accounts")
//    .select("workspace_id, user_id")
//    .eq("id", accountId)
//    .maybeSingle()
//
//  call 2 (membership check inside verifyWorkspaceAccess):
//    .from("workspace_members")
//    .select("role")
//    .eq("workspace_id", wsId)
//    .eq("user_id", userId)
//    .maybeSingle()
//
//  call 3 (owner check fallback):
//    .from("workspaces")
//    .select("owner_id")
//    .eq("id", wsId)
//    .maybeSingle()
// ---------------------------------------------------------------------------

type AccountRow = { workspace_id: string | null; user_id: string } | null;
type MemberRow = { role: string } | null;
type OwnerRow = { owner_id: string } | null;

function buildDb(
  accountRow: AccountRow,
  memberRow: MemberRow,
  ownerRow: OwnerRow,
) {
  return {
    from: (table: string) => {
      if (table === "accounts" || table === "instagram_accounts") {
        return {
          select: (_cols: string) => ({
            eq: (_col: string, _val: string) => ({
              maybeSingle: () => Promise.resolve({ data: accountRow }),
            }),
          }),
        };
      }
      if (table === "workspace_members") {
        return {
          select: (_cols: string) => ({
            eq: (_col: string, _val: string) => ({
              eq: (_col2: string, _val2: string) => ({
                maybeSingle: () => Promise.resolve({ data: memberRow }),
              }),
            }),
          }),
        };
      }
      // "workspaces"
      return {
        select: (_cols: string) => ({
          eq: (_col: string, _val: string) => ({
            maybeSingle: () => Promise.resolve({ data: ownerRow }),
          }),
        }),
      };
    },
  };
}

// ---------------------------------------------------------------------------
// verifyAccountWorkspaceAccess — the cross-workspace isolation guarantee
// ---------------------------------------------------------------------------

describe("verifyAccountWorkspaceAccess — cross-workspace bleed prevention", () => {
  it("denies: accountId belongs to workspace-B, requester is only in workspace-A", async () => {
    // The key attack scenario: Claude passes a foreign accountId.
    // Account is in workspace-B, owned by user-B.
    // Requester (user-A) is not a member or owner of workspace-B.
    const db = buildDb(
      { workspace_id: "workspace-B", user_id: "user-B" },
      null,                          // user-A is NOT a member of workspace-B
      { owner_id: "user-B" },        // workspace-B is owned by user-B, not user-A
    );
    const result = await verifyAccountWorkspaceAccess(db as any, "user-A", "account-B");
    expect(result).toBe(false);
  });

  it("allows: requester is a member of the account's workspace", async () => {
    const db = buildDb(
      { workspace_id: "workspace-A", user_id: "user-B" },
      { role: "member" },  // user-A IS a member of workspace-A
      null,
    );
    const result = await verifyAccountWorkspaceAccess(db as any, "user-A", "account-A");
    expect(result).toBe(true);
  });

  it("allows: requester is the owner of the account's workspace", async () => {
    const db = buildDb(
      { workspace_id: "workspace-A", user_id: "user-B" },
      null,                           // not in members table
      { owner_id: "user-A" },         // but IS the workspace owner
    );
    const result = await verifyAccountWorkspaceAccess(db as any, "user-A", "account-A");
    expect(result).toBe(true);
  });

  it("allows: no workspace attached, requester is the direct account owner", async () => {
    const db = buildDb(
      { workspace_id: null, user_id: "user-A" },
      null,
      null,
    );
    const result = await verifyAccountWorkspaceAccess(db as any, "user-A", "account-A");
    expect(result).toBe(true);
  });

  it("denies: no workspace, requester is NOT the account owner (solo-user IDOR)", async () => {
    const db = buildDb(
      { workspace_id: null, user_id: "user-B" },
      null,
      null,
    );
    const result = await verifyAccountWorkspaceAccess(db as any, "user-A", "account-B");
    expect(result).toBe(false);
  });

  it("denies: account does not exist", async () => {
    const db = buildDb(null, null, null);
    const result = await verifyAccountWorkspaceAccess(db as any, "user-A", "nonexistent");
    expect(result).toBe(false);
  });

  it("denies: unknown table name passed — defense-in-depth guard", async () => {
    const db = buildDb({ workspace_id: null, user_id: "user-A" }, null, null);
    // biome-ignore lint/suspicious/noExplicitAny: testing the runtime table name guard
    const result = await verifyAccountWorkspaceAccess(db as any, "user-A", "id", "posts" as any);
    expect(result).toBe(false);
  });

  it("works for instagram_accounts table", async () => {
    const db = buildDb(
      { workspace_id: "workspace-A", user_id: "user-B" },
      { role: "admin" },
      null,
    );
    const result = await verifyAccountWorkspaceAccess(db as any, "user-A", "ig-account-A", "instagram_accounts");
    expect(result).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// verifyWorkspaceAccess — workspace-level membership check
// ---------------------------------------------------------------------------

describe("verifyWorkspaceAccess — workspace membership check", () => {
  function buildWsDb(memberRow: MemberRow, ownerRow: OwnerRow) {
    return {
      from: (table: string) => {
        if (table === "workspace_members") {
          return {
            select: (_c: string) => ({
              eq: (_c1: string, _v1: string) => ({
                eq: (_c2: string, _v2: string) => ({
                  maybeSingle: () => Promise.resolve({ data: memberRow }),
                }),
              }),
            }),
          };
        }
        return {
          select: (_c: string) => ({
            eq: (_c1: string, _v1: string) => ({
              maybeSingle: () => Promise.resolve({ data: ownerRow }),
            }),
          }),
        };
      },
    };
  }

  it("allows a workspace member", async () => {
    const db = buildWsDb({ role: "member" }, null);
    expect(await verifyWorkspaceAccess(db as any, "user-A", "ws-1")).toBe(true);
  });

  it("returns role details for a workspace member", async () => {
    const db = buildWsDb({ role: "admin" }, null);
    await expect(getWorkspaceAccess(db as any, "user-A", "ws-1")).resolves.toEqual({
      hasAccess: true,
      role: "admin",
      isOwner: false,
    });
  });

  it("allows the workspace owner when not in members table", async () => {
    const db = buildWsDb(null, { owner_id: "user-A" });
    expect(await verifyWorkspaceAccess(db as any, "user-A", "ws-1")).toBe(true);
  });

  it("normalizes owner access when the owner is not in members table", async () => {
    const db = buildWsDb(null, { owner_id: "user-A" });
    await expect(getWorkspaceAccess(db as any, "user-A", "ws-1")).resolves.toEqual({
      hasAccess: true,
      role: "owner",
      isOwner: true,
    });
  });

  it("denies a non-member non-owner", async () => {
    const db = buildWsDb(null, { owner_id: "user-B" });
    expect(await verifyWorkspaceAccess(db as any, "user-A", "ws-1")).toBe(false);
  });

  it("denies when workspace does not exist", async () => {
    const db = buildWsDb(null, null);
    expect(await verifyWorkspaceAccess(db as any, "user-A", "nonexistent")).toBe(false);
  });

  it("treats owner and admin as invite-capable roles", async () => {
    expect(
      workspaceAccessHasRole(
        { hasAccess: true, role: "owner", isOwner: true },
        ["owner", "admin"],
      ),
    ).toBe(true);
    expect(
      workspaceAccessHasRole(
        { hasAccess: true, role: "admin", isOwner: false },
        ["owner", "admin"],
      ),
    ).toBe(true);
  });

  it("does not treat a basic member as an admin role", async () => {
    expect(
      workspaceAccessHasRole(
        { hasAccess: true, role: "member", isOwner: false },
        ["owner", "admin"],
      ),
    ).toBe(false);
  });
});
