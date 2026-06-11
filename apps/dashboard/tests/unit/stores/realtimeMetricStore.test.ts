/**
 * realtimeMetricStore — unit tests for the optimistic metric bumps store.
 *
 * Tests cover: bumpAccountMetric, clearAccountBumps, clearAllBumps,
 * incremental accumulation, custom deltas, and multi-account isolation.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useRealtimeMetricStore } from "@/src/stores/realtimeMetricStore";

describe("realtimeMetricStore", () => {
  beforeEach(() => {
    useRealtimeMetricStore.setState({ accountBumps: {} });
  });

  it("starts with empty accountBumps", () => {
    expect(useRealtimeMetricStore.getState().accountBumps).toEqual({});
  });

  describe("bumpAccountMetric", () => {
    it("adds a bump for a new account and metric", () => {
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "likes");

      const bumps = useRealtimeMetricStore.getState().accountBumps;
      expect(bumps["acc-1"]).toEqual({ likes: 1 });
    });

    it("increments an existing metric", () => {
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "replies");
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "replies");
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "replies");

      const bumps = useRealtimeMetricStore.getState().accountBumps;
      expect(bumps["acc-1"].replies).toBe(3);
    });

    it("supports custom delta values", () => {
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "views", 50);

      const bumps = useRealtimeMetricStore.getState().accountBumps;
      expect(bumps["acc-1"].views).toBe(50);
    });

    it("accumulates custom deltas", () => {
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "views", 10);
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "views", 20);

      const bumps = useRealtimeMetricStore.getState().accountBumps;
      expect(bumps["acc-1"].views).toBe(30);
    });

    it("tracks multiple metrics per account independently", () => {
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "likes");
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "replies");
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "views", 5);

      const bumps = useRealtimeMetricStore.getState().accountBumps;
      expect(bumps["acc-1"]).toEqual({ likes: 1, replies: 1, views: 5 });
    });

    it("isolates bumps across different accounts", () => {
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "likes", 3);
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-2", "likes", 7);

      const bumps = useRealtimeMetricStore.getState().accountBumps;
      expect(bumps["acc-1"].likes).toBe(3);
      expect(bumps["acc-2"].likes).toBe(7);
    });
  });

  describe("clearAccountBumps", () => {
    it("removes all bumps for a specific account", () => {
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "likes", 5);
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "replies", 2);
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-2", "views", 10);

      useRealtimeMetricStore.getState().clearAccountBumps("acc-1");

      const bumps = useRealtimeMetricStore.getState().accountBumps;
      expect(bumps["acc-1"]).toBeUndefined();
      expect(bumps["acc-2"]).toEqual({ views: 10 });
    });

    it("is a safe no-op for non-existent account", () => {
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "likes");

      useRealtimeMetricStore.getState().clearAccountBumps("nonexistent");

      const bumps = useRealtimeMetricStore.getState().accountBumps;
      expect(bumps["acc-1"]).toEqual({ likes: 1 });
    });
  });

  describe("clearAllBumps", () => {
    it("removes all bumps for all accounts", () => {
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-1", "likes", 5);
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-2", "replies", 3);
      useRealtimeMetricStore.getState().bumpAccountMetric("acc-3", "views", 100);

      useRealtimeMetricStore.getState().clearAllBumps();

      expect(useRealtimeMetricStore.getState().accountBumps).toEqual({});
    });

    it("is a safe no-op on already empty state", () => {
      useRealtimeMetricStore.getState().clearAllBumps();
      expect(useRealtimeMetricStore.getState().accountBumps).toEqual({});
    });
  });
});
