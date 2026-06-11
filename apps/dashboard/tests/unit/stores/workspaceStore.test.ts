import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useWorkspaceStore } from "@/src/stores/useWorkspaceStore";
import { PERMISSIONS } from "@/types/team";

// Mock external dependencies
vi.mock("@/services/supabase", () => ({
  supabase: {
    auth: {
      getSession: vi.fn().mockResolvedValue({ data: { session: null } }),
      onAuthStateChange: vi.fn().mockReturnValue({
        data: { subscription: { unsubscribe: vi.fn() } },
      }),
    },
  },
}));

vi.mock("@/utils/logger", () => ({
  logger: { error: vi.fn(), log: vi.fn(), warn: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

vi.mock("@/services/teamService", () => ({
  teamService: {
    getUserWorkspaces: vi.fn().mockResolvedValue([]),
    getWorkspace: vi.fn().mockResolvedValue(null),
    getMemberRole: vi.fn().mockResolvedValue(null),
    getWorkspaceMembers: vi.fn().mockResolvedValue([]),
    createWorkspace: vi.fn().mockResolvedValue({ id: "ws-new", name: "Test" }),
  },
}));

vi.mock("@/services/subscriptionService", () => ({
  subscriptionService: {
    getUsageStats: vi.fn().mockResolvedValue({ accountCount: 0, accountLimit: 1 }),
    canAddAccount: vi.fn().mockResolvedValue({ allowed: true }),
    canInviteMember: vi.fn().mockResolvedValue({ allowed: true }),
  },
}));

describe("workspaceStore", () => {
  beforeEach(() => {
    localStorage.clear();
    useWorkspaceStore.getState().reset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("initial state", () => {
    it("has null currentWorkspace", () => {
      expect(useWorkspaceStore.getState().currentWorkspace).toBeNull();
    });

    it("has null currentRole", () => {
      expect(useWorkspaceStore.getState().currentRole).toBeNull();
    });

    it("has empty members array", () => {
      expect(useWorkspaceStore.getState().members).toEqual([]);
    });

    it("has empty workspaces array", () => {
      expect(useWorkspaceStore.getState().workspaces).toEqual([]);
    });

    it("has null subscription", () => {
      expect(useWorkspaceStore.getState().subscription).toBeNull();
    });

    it("is not trialing by default", () => {
      expect(useWorkspaceStore.getState().isTrialing).toBe(false);
    });

    it("has 0 trial days remaining", () => {
      expect(useWorkspaceStore.getState().trialDaysRemaining).toBe(0);
    });

    it("is not in grace period", () => {
      expect(useWorkspaceStore.getState().isInGrace).toBe(false);
    });
  });

  describe("setSelectedGroupId", () => {
    it("sets groupId", () => {
      useWorkspaceStore.getState().setSelectedGroupId("group1");
      expect(useWorkspaceStore.getState().selectedGroupId).toBe("group1");
    });

    it("persists to localStorage", () => {
      useWorkspaceStore.getState().setSelectedGroupId("group1");
      expect(localStorage.getItem("juno33-selected-group")).toBe("group1");
    });

    it("clears from localStorage when null", () => {
      useWorkspaceStore.getState().setSelectedGroupId("group1");
      useWorkspaceStore.getState().setSelectedGroupId(null);
      expect(localStorage.getItem("juno33-selected-group")).toBeNull();
    });

    it("sets null groupId", () => {
      useWorkspaceStore.getState().setSelectedGroupId("group1");
      useWorkspaceStore.getState().setSelectedGroupId(null);
      expect(useWorkspaceStore.getState().selectedGroupId).toBeNull();
    });
  });

  describe("can (permission check)", () => {
    it("returns false when no role", () => {
      expect(useWorkspaceStore.getState().can(PERMISSIONS.VIEW_DASHBOARD)).toBe(false);
    });

    it("returns true for owner on any permission", () => {
      useWorkspaceStore.setState({ currentRole: "owner" });
      expect(useWorkspaceStore.getState().can(PERMISSIONS.DELETE_WORKSPACE)).toBe(true);
      expect(useWorkspaceStore.getState().can(PERMISSIONS.VIEW_DASHBOARD)).toBe(true);
      expect(useWorkspaceStore.getState().can(PERMISSIONS.ACCESS_BILLING)).toBe(true);
    });

    it("returns true for admin on allowed permissions", () => {
      useWorkspaceStore.setState({ currentRole: "admin" });
      expect(useWorkspaceStore.getState().can(PERMISSIONS.VIEW_DASHBOARD)).toBe(true);
      expect(useWorkspaceStore.getState().can(PERMISSIONS.CREATE_POST)).toBe(true);
      expect(useWorkspaceStore.getState().can(PERMISSIONS.INVITE_MEMBER)).toBe(true);
    });

    it("returns false for admin on owner-only permissions", () => {
      useWorkspaceStore.setState({ currentRole: "admin" });
      expect(useWorkspaceStore.getState().can(PERMISSIONS.ACCESS_BILLING)).toBe(false);
      expect(useWorkspaceStore.getState().can(PERMISSIONS.DELETE_WORKSPACE)).toBe(false);
      expect(useWorkspaceStore.getState().can(PERMISSIONS.TRANSFER_OWNERSHIP)).toBe(false);
    });

    it("returns true for editor on basic permissions", () => {
      useWorkspaceStore.setState({ currentRole: "editor" });
      expect(useWorkspaceStore.getState().can(PERMISSIONS.VIEW_DASHBOARD)).toBe(true);
      expect(useWorkspaceStore.getState().can(PERMISSIONS.CREATE_POST)).toBe(true);
    });

    it("returns false for editor on team management", () => {
      useWorkspaceStore.setState({ currentRole: "editor" });
      expect(useWorkspaceStore.getState().can(PERMISSIONS.INVITE_MEMBER)).toBe(false);
      expect(useWorkspaceStore.getState().can(PERMISSIONS.REMOVE_MEMBER)).toBe(false);
    });
  });

  describe("canManageUser", () => {
    it("returns false when no role", () => {
      expect(useWorkspaceStore.getState().canManageUser("editor")).toBe(false);
    });

    it("owner can manage admin", () => {
      useWorkspaceStore.setState({ currentRole: "owner" });
      expect(useWorkspaceStore.getState().canManageUser("admin")).toBe(true);
    });

    it("owner can manage editor", () => {
      useWorkspaceStore.setState({ currentRole: "owner" });
      expect(useWorkspaceStore.getState().canManageUser("editor")).toBe(true);
    });

    it("admin can manage editor", () => {
      useWorkspaceStore.setState({ currentRole: "admin" });
      expect(useWorkspaceStore.getState().canManageUser("editor")).toBe(true);
    });

    it("admin cannot manage owner", () => {
      useWorkspaceStore.setState({ currentRole: "admin" });
      expect(useWorkspaceStore.getState().canManageUser("owner")).toBe(false);
    });

    it("editor cannot manage anyone", () => {
      useWorkspaceStore.setState({ currentRole: "editor" });
      expect(useWorkspaceStore.getState().canManageUser("editor")).toBe(false);
      expect(useWorkspaceStore.getState().canManageUser("admin")).toBe(false);
    });
  });

  describe("getEffectiveLimit", () => {
    it("returns 1 for free tier accounts", () => {
      useWorkspaceStore.setState({
        currentWorkspace: { id: "ws1", name: "test", ownerId: "u1", createdAt: new Date(), subscriptionTier: "free" },
        subscription: null,
      });
      expect(useWorkspaceStore.getState().getEffectiveLimit("accounts")).toBe(1);
    });

    it("returns 10 for pro tier accounts with no add-ons", () => {
      useWorkspaceStore.setState({
        currentWorkspace: { id: "ws1", name: "test", ownerId: "u1", createdAt: new Date(), subscriptionTier: "pro" },
        subscription: { tier: "pro", status: "active", addOnsCount: 0 },
      });
      expect(useWorkspaceStore.getState().getEffectiveLimit("accounts")).toBe(10);
    });

    it("returns 13 for pro tier with 3 add-ons", () => {
      useWorkspaceStore.setState({
        currentWorkspace: { id: "ws1", name: "test", ownerId: "u1", createdAt: new Date(), subscriptionTier: "pro" },
        subscription: { tier: "pro", status: "active", addOnsCount: 3 },
      });
      expect(useWorkspaceStore.getState().getEffectiveLimit("accounts")).toBe(13);
    });

    it("returns Infinity for agency tier accounts", () => {
      useWorkspaceStore.setState({
        currentWorkspace: { id: "ws1", name: "test", ownerId: "u1", createdAt: new Date(), subscriptionTier: "agency" },
        subscription: { tier: "agency", status: "active", addOnsCount: 0 },
      });
      expect(useWorkspaceStore.getState().getEffectiveLimit("accounts")).toBe(Infinity);
    });

    it("returns correct member limits by tier", () => {
      useWorkspaceStore.setState({
        currentWorkspace: { id: "ws1", name: "test", ownerId: "u1", createdAt: new Date(), subscriptionTier: "free" },
        subscription: null,
      });
      expect(useWorkspaceStore.getState().getEffectiveLimit("members")).toBe(1);

      useWorkspaceStore.setState({
        currentWorkspace: { id: "ws1", name: "test", ownerId: "u1", createdAt: new Date(), subscriptionTier: "pro" },
      });
      expect(useWorkspaceStore.getState().getEffectiveLimit("members")).toBe(4);
    });
  });

  describe("reset", () => {
    it("resets to initial values", () => {
      useWorkspaceStore.setState({
        currentWorkspace: { id: "ws1", name: "test", ownerId: "u1", createdAt: new Date(), subscriptionTier: "pro" },
        currentRole: "owner",
        members: [{ userId: "u1", role: "owner", joinedAt: new Date(), invitedBy: "system" }],
        isTrialing: true,
      });

      useWorkspaceStore.getState().reset();

      const state = useWorkspaceStore.getState();
      expect(state.currentWorkspace).toBeNull();
      expect(state.currentRole).toBeNull();
      expect(state.members).toEqual([]);
      expect(state.isTrialing).toBe(false);
      expect(state.isInitialized).toBe(true);
    });
  });

  describe("canAddAccount", () => {
    it("returns not allowed when no workspace", async () => {
      useWorkspaceStore.setState({ currentWorkspace: null });
      const result = await useWorkspaceStore.getState().canAddAccount();
      expect(result.allowed).toBe(false);
      expect(result.reason).toBe("No workspace selected");
    });
  });

  describe("canInviteMember", () => {
    it("returns not allowed when no workspace", async () => {
      useWorkspaceStore.setState({ currentWorkspace: null });
      const result = await useWorkspaceStore.getState().canInviteMember();
      expect(result.allowed).toBe(false);
      expect(result.reason).toBe("No workspace selected");
    });
  });
});
