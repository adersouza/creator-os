import { describe, it, expect, beforeEach, vi } from "vitest";
import { useShortcutsStore } from "@/src/stores/useShortcutsStore";

describe("shortcutsStore", () => {
  beforeEach(() => {
    useShortcutsStore.setState({
      isCheatSheetOpen: false,
      pendingG: false,
      navigateFn: null,
      createPostFn: null,
    });
  });

  describe("cheat sheet", () => {
    it("defaults to closed", () => {
      expect(useShortcutsStore.getState().isCheatSheetOpen).toBe(false);
    });

    it("openCheatSheet opens it", () => {
      useShortcutsStore.getState().openCheatSheet();
      expect(useShortcutsStore.getState().isCheatSheetOpen).toBe(true);
    });

    it("closeCheatSheet closes it", () => {
      useShortcutsStore.getState().openCheatSheet();
      useShortcutsStore.getState().closeCheatSheet();
      expect(useShortcutsStore.getState().isCheatSheetOpen).toBe(false);
    });

    it("toggleCheatSheet toggles open", () => {
      useShortcutsStore.getState().toggleCheatSheet();
      expect(useShortcutsStore.getState().isCheatSheetOpen).toBe(true);
    });

    it("toggleCheatSheet toggles closed", () => {
      useShortcutsStore.getState().openCheatSheet();
      useShortcutsStore.getState().toggleCheatSheet();
      expect(useShortcutsStore.getState().isCheatSheetOpen).toBe(false);
    });
  });

  describe("pendingG", () => {
    it("defaults to false", () => {
      expect(useShortcutsStore.getState().pendingG).toBe(false);
    });

    it("setPendingG sets to true", () => {
      useShortcutsStore.getState().setPendingG(true);
      expect(useShortcutsStore.getState().pendingG).toBe(true);
    });

    it("setPendingG sets back to false", () => {
      useShortcutsStore.getState().setPendingG(true);
      useShortcutsStore.getState().setPendingG(false);
      expect(useShortcutsStore.getState().pendingG).toBe(false);
    });
  });

  describe("register functions", () => {
    it("registerNavigate stores function", () => {
      const fn = vi.fn();
      useShortcutsStore.getState().registerNavigate(fn);
      expect(useShortcutsStore.getState().navigateFn).toBe(fn);
    });

    it("registerCreatePost stores function", () => {
      const fn = vi.fn();
      useShortcutsStore.getState().registerCreatePost(fn);
      expect(useShortcutsStore.getState().createPostFn).toBe(fn);
    });
  });
});
