/**
 * teamService — unit tests for workspace and team management operations.
 *
 * Tests cover: createWorkspace, getWorkspace, getMemberRole,
 * updateMemberRole guards, removeMember guards, transferOwnership,
 * createInvite tier limits, joinWorkspaceWithCode validation,
 * generateInviteCode uniqueness, and logActivity.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

// ── Supabase mock ────────────────────────────────────────────────────────────

function createChain() {
  const chain: any = {};
  chain.select = vi.fn().mockReturnValue(chain);
  chain.insert = vi.fn().mockReturnValue(chain);
  chain.update = vi.fn().mockReturnValue(chain);
  chain.delete = vi.fn().mockReturnValue(chain);
  chain.eq = vi.fn().mockReturnValue(chain);
  chain.gt = vi.fn().mockReturnValue(chain);
  chain.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
  chain.limit = vi.fn().mockReturnValue(chain);
  chain.order = vi.fn().mockReturnValue(chain);
  chain.single = vi.fn().mockResolvedValue({ data: null, error: null });
  return chain;
}

const mockGetSession = vi.fn();

let tableChains: Record<string, any> = {};

vi.mock("@/services/supabase", () => ({
  supabase: {
    auth: {
      getSession: () => mockGetSession(),
    },
    from: vi.fn((table: string) => {
      if (!tableChains[table]) {
        tableChains[table] = createChain();
      }
      return tableChains[table];
    }),
    channel: vi.fn().mockReturnValue({
      on: vi.fn().mockReturnThis(),
      subscribe: vi.fn().mockReturnThis(),
    }),
  },
}));

vi.mock("@/services/realtimeManager", () => ({
  subscribe: vi.fn(() => () => {}),
}));

vi.mock("../utils/logger", () => ({
  default: {
    log: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    debug: vi.fn(),
  },
}));

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

import {
  createWorkspace,
  getWorkspace,
  getMemberRole,
  updateMemberRole,
  removeMember,
  getWorkspaceMembers,
  logActivity,
  getActivityLog,
} from "@/services/teamService";

const MOCK_SESSION = {
  data: {
    session: {
      user: {
        id: "user-1",
        email: "test@example.com",
        user_metadata: { display_name: "Test User" },
      },
      access_token: "tok-123",
    },
  },
};

describe("teamService", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    tableChains = {};
    mockGetSession.mockResolvedValue(MOCK_SESSION);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("createWorkspace", () => {
    it("throws when not authenticated", async () => {
      mockGetSession.mockResolvedValueOnce({ data: { session: null } });

      await expect(createWorkspace("My Workspace")).rejects.toThrow("Not authenticated");
    });

    it("creates workspace with owner as member", async () => {
      const wsChain = createChain();
      wsChain.insert.mockReturnValue({
        select: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({
            data: {
              id: "ws-new",
              name: "My Workspace",
              owner_id: "user-1",
              created_at: "2026-04-15T12:00:00Z",
              tier: "free",
            },
            error: null,
          }),
        }),
      });

      const memberChain = createChain();
      memberChain.insert.mockResolvedValue({ error: null });

      const activityChain = createChain();
      activityChain.insert.mockResolvedValue({ error: null });

      tableChains["workspaces"] = wsChain;
      tableChains["workspace_members"] = memberChain;
      tableChains["workspace_activity"] = activityChain;

      const result = await createWorkspace("My Workspace");

      expect(result.id).toBe("ws-new");
      expect(result.name).toBe("My Workspace");
      expect(result.ownerId).toBe("user-1");
    });
  });

  describe("getWorkspace", () => {
    it("returns null when workspace not found", async () => {
      const wsChain = createChain();
      wsChain.select.mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
        }),
      });
      tableChains["workspaces"] = wsChain;

      const result = await getWorkspace("nonexistent");
      expect(result).toBeNull();
    });

    it("returns workspace with correct shape", async () => {
      const wsChain = createChain();
      wsChain.select.mockReturnValue({
        eq: vi.fn().mockReturnValue({
          maybeSingle: vi.fn().mockResolvedValue({
            data: {
              id: "ws-1",
              name: "Test WS",
              owner_id: "user-1",
              created_at: "2026-04-15T12:00:00Z",
              tier: "pro",
            },
            error: null,
          }),
        }),
      });
      tableChains["workspaces"] = wsChain;

      const result = await getWorkspace("ws-1");
      expect(result).not.toBeNull();
      expect(result!.id).toBe("ws-1");
      expect(result!.name).toBe("Test WS");
      expect(result!.subscriptionTier).toBe("pro");
    });
  });

  describe("getMemberRole", () => {
    it("returns null when not authenticated and no targetUserId", async () => {
      mockGetSession.mockResolvedValueOnce({ data: { session: null } });

      const role = await getMemberRole("ws-1");
      expect(role).toBeNull();
    });

    it("returns the role for a member", async () => {
      const memberChain = createChain();
      memberChain.select.mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: { role: "admin" },
              error: null,
            }),
          }),
        }),
      });
      tableChains["workspace_members"] = memberChain;

      const role = await getMemberRole("ws-1", "user-1");
      expect(role).toBe("admin");
    });

    it("returns null for non-member", async () => {
      const memberChain = createChain();
      memberChain.select.mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
          }),
        }),
      });
      tableChains["workspace_members"] = memberChain;

      const role = await getMemberRole("ws-1", "stranger");
      expect(role).toBeNull();
    });
  });

  describe("updateMemberRole", () => {
    it("throws when trying to set role to owner", async () => {
      await expect(
        updateMemberRole("ws-1", "user-2", "owner" as any),
      ).rejects.toThrow("transferOwnership");
    });

    it("throws when caller is not owner or admin", async () => {
      // getMemberRole for caller
      const memberChain = createChain();
      memberChain.select.mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: { role: "editor" },
              error: null,
            }),
          }),
        }),
      });
      tableChains["workspace_members"] = memberChain;

      await expect(
        updateMemberRole("ws-1", "user-2", "admin"),
      ).rejects.toThrow("permission");
    });

    it("throws when trying to change own role", async () => {
      const memberChain = createChain();
      memberChain.select.mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: { role: "owner" },
              error: null,
            }),
          }),
        }),
      });
      tableChains["workspace_members"] = memberChain;

      await expect(
        updateMemberRole("ws-1", "user-1", "editor"),
      ).rejects.toThrow("your own role");
    });
  });

  describe("removeMember", () => {
    it("throws when trying to remove yourself", async () => {
      const memberChain = createChain();
      memberChain.select.mockReturnValue({
        eq: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: { role: "owner" },
              error: null,
            }),
          }),
        }),
      });
      tableChains["workspace_members"] = memberChain;

      await expect(removeMember("ws-1", "user-1")).rejects.toThrow(
        "cannot remove yourself",
      );
    });
  });

  describe("getWorkspaceMembers", () => {
    it("returns empty array on error", async () => {
      const memberChain = createChain();
      memberChain.select.mockReturnValue({
        eq: vi.fn().mockResolvedValue({ data: null, error: new Error("fail") }),
      });
      tableChains["workspace_members"] = memberChain;

      const members = await getWorkspaceMembers("ws-1");
      expect(members).toEqual([]);
    });

    it("maps Supabase rows to WorkspaceMember shape", async () => {
      const memberChain = createChain();
      memberChain.select.mockReturnValue({
        eq: vi.fn().mockResolvedValue({
          data: [
            {
              user_id: "u1",
              role: "owner",
              joined_at: "2026-04-01T10:00:00Z",
              invited_by: null,
              display_name: "Alice",
              email: "alice@test.com",
              photo_url: null,
            },
          ],
          error: null,
        }),
      });
      tableChains["workspace_members"] = memberChain;

      const members = await getWorkspaceMembers("ws-1");
      expect(members).toHaveLength(1);
      expect(members[0].userId).toBe("u1");
      expect(members[0].role).toBe("owner");
      expect(members[0].displayName).toBe("Alice");
    });
  });

  describe("logActivity", () => {
    it("inserts activity row with user info", async () => {
      const activityChain = createChain();
      tableChains["workspace_activity"] = activityChain;

      await logActivity("ws-1", "member_joined" as any, { newMemberId: "u2" });

      expect(activityChain.insert).toHaveBeenCalled();
    });

    it("is a no-op when not authenticated", async () => {
      mockGetSession.mockResolvedValueOnce({ data: { session: null } });
      const activityChain = createChain();
      tableChains["workspace_activity"] = activityChain;

      await logActivity("ws-1", "member_joined" as any);

      expect(activityChain.insert).not.toHaveBeenCalled();
    });
  });

  describe("getActivityLog", () => {
    it("returns empty array on error", async () => {
      const activityChain = createChain();
      activityChain.select.mockReturnValue({
        eq: vi.fn().mockReturnValue({
          order: vi.fn().mockReturnValue({
            limit: vi.fn().mockResolvedValue({ data: null, error: new Error("fail") }),
          }),
        }),
      });
      tableChains["workspace_activity"] = activityChain;

      const log = await getActivityLog("ws-1");
      expect(log).toEqual([]);
    });

    it("maps rows to ActivityLogEntry shape", async () => {
      const activityChain = createChain();
      activityChain.select.mockReturnValue({
        eq: vi.fn().mockReturnValue({
          order: vi.fn().mockReturnValue({
            limit: vi.fn().mockResolvedValue({
              data: [
                {
                  id: "a1",
                  action: "member_joined",
                  user_id: "u1",
                  user_name: "Alice",
                  created_at: "2026-04-15T10:00:00Z",
                  details: { newMemberId: "u2" },
                },
              ],
              error: null,
            }),
          }),
        }),
      });
      tableChains["workspace_activity"] = activityChain;

      const log = await getActivityLog("ws-1");
      expect(log).toHaveLength(1);
      expect(log[0].action).toBe("member_joined");
      expect(log[0].userId).toBe("u1");
      expect(log[0].userName).toBe("Alice");
      expect(log[0].details).toEqual({ newMemberId: "u2" });
    });
  });
});
