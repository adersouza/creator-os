import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useErrorStore } from "@/src/stores/useErrorStore";

describe("errorStore", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useErrorStore.setState({ errors: [] });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("initial state", () => {
    it("has empty errors array", () => {
      expect(useErrorStore.getState().errors).toEqual([]);
    });
  });

  describe("addError", () => {
    it("adds a network error", () => {
      useErrorStore.getState().addError({
        type: "network",
        message: "Connection failed",
      });
      const { errors } = useErrorStore.getState();
      expect(errors).toHaveLength(1);
      expect(errors[0].type).toBe("network");
      expect(errors[0].message).toBe("Connection failed");
    });

    it("assigns an id and timestamp", () => {
      useErrorStore.getState().addError({
        type: "server",
        message: "Internal error",
      });
      const { errors } = useErrorStore.getState();
      expect(errors[0].id).toContain("server_");
      expect(errors[0].timestamp).toBeGreaterThan(0);
    });

    it("adds multiple errors", () => {
      useErrorStore.getState().addError({ type: "network", message: "Error 1" });
      useErrorStore.getState().addError({ type: "server", message: "Error 2" });
      expect(useErrorStore.getState().errors).toHaveLength(2);
    });

    it("deduplicates rate_limit errors — does not add a second one", () => {
      useErrorStore.getState().addError({
        type: "rate_limit",
        message: "Rate limited 1",
      });
      useErrorStore.getState().addError({
        type: "rate_limit",
        message: "Rate limited 2",
      });
      expect(useErrorStore.getState().errors).toHaveLength(1);
      expect(useErrorStore.getState().errors[0].message).toBe("Rate limited 1");
    });

    it("auto-dismisses error after retryAfter seconds", () => {
      useErrorStore.getState().addError({
        type: "network",
        message: "Timeout",
        retryAfter: 10,
      });
      expect(useErrorStore.getState().errors).toHaveLength(1);

      vi.advanceTimersByTime(10_000);
      expect(useErrorStore.getState().errors).toHaveLength(0);
    });

    it("auto-dismisses error after 30s when no retryAfter", () => {
      useErrorStore.getState().addError({
        type: "server",
        message: "Server error",
      });
      expect(useErrorStore.getState().errors).toHaveLength(1);

      vi.advanceTimersByTime(29_999);
      expect(useErrorStore.getState().errors).toHaveLength(1);

      vi.advanceTimersByTime(1);
      expect(useErrorStore.getState().errors).toHaveLength(0);
    });
  });

  describe("dismissError", () => {
    it("removes an error by id", () => {
      useErrorStore.getState().addError({ type: "network", message: "Error A" });
      useErrorStore.getState().addError({ type: "server", message: "Error B" });

      const errors = useErrorStore.getState().errors;
      expect(errors).toHaveLength(2);

      useErrorStore.getState().dismissError(errors[0].id);
      expect(useErrorStore.getState().errors).toHaveLength(1);
      expect(useErrorStore.getState().errors[0].message).toBe("Error B");
    });

    it("does nothing when id does not exist", () => {
      useErrorStore.getState().addError({ type: "network", message: "Error" });
      useErrorStore.getState().dismissError("nonexistent_id");
      expect(useErrorStore.getState().errors).toHaveLength(1);
    });

    it("allows new rate_limit error after previous one is dismissed", () => {
      useErrorStore.getState().addError({ type: "rate_limit", message: "Rate 1" });
      const rateError = useErrorStore.getState().errors[0];

      useErrorStore.getState().dismissError(rateError.id);
      expect(useErrorStore.getState().errors).toHaveLength(0);

      // Should allow adding a new rate_limit error now
      useErrorStore.getState().addError({ type: "rate_limit", message: "Rate 2" });
      expect(useErrorStore.getState().errors).toHaveLength(1);
    });
  });

  describe("clearErrors", () => {
    it("removes all errors", () => {
      useErrorStore.getState().addError({ type: "network", message: "E1" });
      useErrorStore.getState().addError({ type: "auth", message: "E2" });
      useErrorStore.getState().addError({ type: "server", message: "E3" });

      useErrorStore.getState().clearErrors();
      expect(useErrorStore.getState().errors).toEqual([]);
    });

    it("is safe to call when already empty", () => {
      useErrorStore.getState().clearErrors();
      expect(useErrorStore.getState().errors).toEqual([]);
    });
  });
});
