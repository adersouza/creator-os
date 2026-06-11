import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useConfirmDialog } from "@/src/hooks/useConfirmDialog";

describe("useConfirmDialog", () => {
  describe("initial state", () => {
    it("starts closed", () => {
      const { result } = renderHook(() => useConfirmDialog());
      expect(result.current.open).toBe(false);
    });

    it("has empty default options", () => {
      const { result } = renderHook(() => useConfirmDialog());
      expect(result.current.options.title).toBe("");
      expect(result.current.options.description).toBe("");
    });
  });

  describe("confirm", () => {
    it("opens the dialog with provided options", async () => {
      const { result } = renderHook(() => useConfirmDialog());

      act(() => {
        result.current.confirm({
          title: "Delete post?",
          description: "This action cannot be undone.",
        });
      });

      expect(result.current.open).toBe(true);
      expect(result.current.options.title).toBe("Delete post?");
      expect(result.current.options.description).toBe(
        "This action cannot be undone."
      );
    });

    it("returns a promise that resolves true on confirm", async () => {
      const { result } = renderHook(() => useConfirmDialog());

      let confirmPromise: Promise<boolean>;
      act(() => {
        confirmPromise = result.current.confirm({
          title: "Confirm",
          description: "Are you sure?",
        });
      });

      act(() => {
        result.current.onConfirm();
      });

      const confirmed = await confirmPromise!;
      expect(confirmed).toBe(true);
    });

    it("returns a promise that resolves false on cancel", async () => {
      const { result } = renderHook(() => useConfirmDialog());

      let confirmPromise: Promise<boolean>;
      act(() => {
        confirmPromise = result.current.confirm({
          title: "Confirm",
          description: "Are you sure?",
        });
      });

      act(() => {
        result.current.onCancel();
      });

      const confirmed = await confirmPromise!;
      expect(confirmed).toBe(false);
    });
  });

  describe("onConfirm", () => {
    it("closes the dialog", () => {
      const { result } = renderHook(() => useConfirmDialog());

      act(() => {
        result.current.confirm({
          title: "Test",
          description: "Test",
        });
      });
      expect(result.current.open).toBe(true);

      act(() => {
        result.current.onConfirm();
      });
      expect(result.current.open).toBe(false);
    });
  });

  describe("onCancel", () => {
    it("closes the dialog", () => {
      const { result } = renderHook(() => useConfirmDialog());

      act(() => {
        result.current.confirm({
          title: "Test",
          description: "Test",
        });
      });
      expect(result.current.open).toBe(true);

      act(() => {
        result.current.onCancel();
      });
      expect(result.current.open).toBe(false);
    });
  });

  describe("options passthrough", () => {
    it("passes confirmLabel and cancelLabel", () => {
      const { result } = renderHook(() => useConfirmDialog());

      act(() => {
        result.current.confirm({
          title: "Remove member?",
          description: "They will lose access.",
          confirmLabel: "Remove",
          cancelLabel: "Keep",
          variant: "danger",
        });
      });

      expect(result.current.options.confirmLabel).toBe("Remove");
      expect(result.current.options.cancelLabel).toBe("Keep");
      expect(result.current.options.variant).toBe("danger");
    });
  });

  describe("sequential confirms", () => {
    it("can be used multiple times sequentially", async () => {
      const { result } = renderHook(() => useConfirmDialog());

      // First dialog — confirm
      let p1: Promise<boolean>;
      act(() => {
        p1 = result.current.confirm({ title: "First", description: "1" });
      });
      act(() => {
        result.current.onConfirm();
      });
      expect(await p1!).toBe(true);

      // Second dialog — cancel
      let p2: Promise<boolean>;
      act(() => {
        p2 = result.current.confirm({ title: "Second", description: "2" });
      });
      act(() => {
        result.current.onCancel();
      });
      expect(await p2!).toBe(false);
    });
  });
});
