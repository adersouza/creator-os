import { describe, it, expect, beforeEach, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import { useUserTier } from "@/src/hooks/useUserTier";

// Control what the workspace store returns per test
const mockStore = vi.hoisted(() => ({
  currentWorkspace: null as { subscriptionTier: string } | null,
  isLoading: false,
}));

vi.mock("@/src/stores/useWorkspaceStore", () => ({
  useWorkspaceStore: () => mockStore,
}));

describe("useUserTier", () => {
  beforeEach(() => {
    mockStore.currentWorkspace = null;
    mockStore.isLoading = false;
  });

  describe("tier resolution", () => {
    it("defaults to free when no workspace is loaded", () => {
      mockStore.currentWorkspace = null;
      const { result } = renderHook(() => useUserTier());
      expect(result.current.tier).toBe("free");
    });

    it("returns the workspace subscription tier", () => {
      mockStore.currentWorkspace = { subscriptionTier: "pro" };
      const { result } = renderHook(() => useUserTier());
      expect(result.current.tier).toBe("pro");
    });

    it("returns agency tier correctly", () => {
      mockStore.currentWorkspace = { subscriptionTier: "agency" };
      const { result } = renderHook(() => useUserTier());
      expect(result.current.tier).toBe("agency");
    });

    it("returns empire tier correctly", () => {
      mockStore.currentWorkspace = { subscriptionTier: "empire" };
      const { result } = renderHook(() => useUserTier());
      expect(result.current.tier).toBe("empire");
    });
  });

  describe("isLoading passthrough", () => {
    it("reflects store loading state", () => {
      mockStore.isLoading = true;
      const { result } = renderHook(() => useUserTier());
      expect(result.current.isLoading).toBe(true);
    });

    it("reflects store non-loading state", () => {
      mockStore.isLoading = false;
      const { result } = renderHook(() => useUserTier());
      expect(result.current.isLoading).toBe(false);
    });
  });

  describe("isAtLeast", () => {
    it("free user is at least free", () => {
      mockStore.currentWorkspace = null;
      const { result } = renderHook(() => useUserTier());
      expect(result.current.isAtLeast("free")).toBe(true);
    });

    it("free user is NOT at least pro", () => {
      mockStore.currentWorkspace = null;
      const { result } = renderHook(() => useUserTier());
      expect(result.current.isAtLeast("pro")).toBe(false);
    });

    it("free user is NOT at least empire", () => {
      mockStore.currentWorkspace = null;
      const { result } = renderHook(() => useUserTier());
      expect(result.current.isAtLeast("empire")).toBe(false);
    });

    it("pro user is at least free", () => {
      mockStore.currentWorkspace = { subscriptionTier: "pro" };
      const { result } = renderHook(() => useUserTier());
      expect(result.current.isAtLeast("free")).toBe(true);
    });

    it("pro user is at least pro", () => {
      mockStore.currentWorkspace = { subscriptionTier: "pro" };
      const { result } = renderHook(() => useUserTier());
      expect(result.current.isAtLeast("pro")).toBe(true);
    });

    it("pro user is NOT at least agency", () => {
      mockStore.currentWorkspace = { subscriptionTier: "pro" };
      const { result } = renderHook(() => useUserTier());
      expect(result.current.isAtLeast("agency")).toBe(false);
    });

    it("pro user is NOT at least empire", () => {
      mockStore.currentWorkspace = { subscriptionTier: "pro" };
      const { result } = renderHook(() => useUserTier());
      expect(result.current.isAtLeast("empire")).toBe(false);
    });

    it("agency user is at least pro", () => {
      mockStore.currentWorkspace = { subscriptionTier: "agency" };
      const { result } = renderHook(() => useUserTier());
      expect(result.current.isAtLeast("pro")).toBe(true);
    });

    it("agency user is NOT at least empire", () => {
      mockStore.currentWorkspace = { subscriptionTier: "agency" };
      const { result } = renderHook(() => useUserTier());
      expect(result.current.isAtLeast("empire")).toBe(false);
    });

    it("empire user is at least empire", () => {
      mockStore.currentWorkspace = { subscriptionTier: "empire" };
      const { result } = renderHook(() => useUserTier());
      expect(result.current.isAtLeast("empire")).toBe(true);
    });

    it("empire user is at least all lower tiers", () => {
      mockStore.currentWorkspace = { subscriptionTier: "empire" };
      const { result } = renderHook(() => useUserTier());
      expect(result.current.isAtLeast("free")).toBe(true);
      expect(result.current.isAtLeast("pro")).toBe(true);
      expect(result.current.isAtLeast("agency")).toBe(true);
    });
  });
});
