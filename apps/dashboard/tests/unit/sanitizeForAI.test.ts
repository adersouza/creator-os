/**
 * Tests for api/_lib/sanitizeForAI.ts
 *
 * Validates that exact metric values are NEVER sent to third-party AI services.
 * All functions convert numbers to relative descriptors per Meta Platform Terms.
 */

import { describe, it, expect } from "vitest";

import {
  sanitizeMetrics,
  describeValue,
  describeRelativePerformance,
  describeAnalyticsTrend,
  describeEngagementRate,
} from "@/api/_lib/sanitizeForAI";

describe("sanitizeForAI", () => {
  // ============================================================
  // describeValue
  // ============================================================
  describe("describeValue()", () => {
    it("returns 'none' for 0", () => {
      expect(describeValue(0)).toBe("none");
    });

    it("returns 'very low' for values < 10", () => {
      expect(describeValue(5)).toBe("very low");
      expect(describeValue(9)).toBe("very low");
    });

    it("returns 'low' for values 10-49", () => {
      expect(describeValue(10)).toBe("low");
      expect(describeValue(49)).toBe("low");
    });

    it("returns 'moderate' for values 50-99", () => {
      expect(describeValue(50)).toBe("moderate");
      expect(describeValue(99)).toBe("moderate");
    });

    it("returns 'good' for values 100-499", () => {
      expect(describeValue(100)).toBe("good");
      expect(describeValue(499)).toBe("good");
    });

    it("returns 'strong' for values 500-999", () => {
      expect(describeValue(500)).toBe("strong");
      expect(describeValue(999)).toBe("strong");
    });

    it("returns 'high' for values 1000-4999", () => {
      expect(describeValue(1000)).toBe("high");
      expect(describeValue(4999)).toBe("high");
    });

    it("returns 'very high' for values >= 5000", () => {
      expect(describeValue(5000)).toBe("very high");
      expect(describeValue(1000000)).toBe("very high");
    });
  });

  // ============================================================
  // sanitizeMetrics
  // ============================================================
  describe("sanitizeMetrics()", () => {
    it("converts all metric values to descriptors", () => {
      const result = sanitizeMetrics({
        views: 1500,
        likes: 45,
        replies: 3,
      });

      expect(result).toContain("views: high");
      expect(result).toContain("likes: low");
      expect(result).toContain("replies: very low");
    });

    it("does not include exact numbers", () => {
      const result = sanitizeMetrics({ views: 12345 });
      expect(result).not.toContain("12345");
    });

    it("skips null and NaN values", () => {
      const result = sanitizeMetrics({
        views: 100,
        likes: NaN,
      } as any);

      expect(result).toContain("views: good");
      expect(result).not.toContain("likes");
    });

    it("handles empty metrics", () => {
      const result = sanitizeMetrics({});
      expect(result).toBe("");
    });
  });

  // ============================================================
  // describeRelativePerformance
  // ============================================================
  describe("describeRelativePerformance()", () => {
    it("returns 'no baseline' when average is 0", () => {
      const result = describeRelativePerformance(100, 0, "views");
      expect(result).toBe("views: no baseline");
    });

    it("returns 'far below average' for ratio < 0.25", () => {
      const result = describeRelativePerformance(10, 100, "views");
      expect(result).toBe("views: far below average");
    });

    it("returns 'well below average' for ratio 0.25-0.5", () => {
      const result = describeRelativePerformance(30, 100, "views");
      expect(result).toBe("views: well below average");
    });

    it("returns 'below average' for ratio 0.5-0.75", () => {
      const result = describeRelativePerformance(60, 100, "views");
      expect(result).toBe("views: below average");
    });

    it("returns 'around average' for ratio 0.75-1.25", () => {
      const result = describeRelativePerformance(100, 100, "views");
      expect(result).toBe("views: around average");
    });

    it("returns 'above average' for ratio 1.25-2", () => {
      const result = describeRelativePerformance(150, 100, "views");
      expect(result).toBe("views: above average");
    });

    it("returns 'well above average' for ratio 2-4", () => {
      const result = describeRelativePerformance(300, 100, "views");
      expect(result).toBe("views: well above average");
    });

    it("returns 'far above average' for ratio >= 4", () => {
      const result = describeRelativePerformance(500, 100, "views");
      expect(result).toBe("views: far above average");
    });

    it("does not leak exact numbers", () => {
      const result = describeRelativePerformance(12345, 6789, "views");
      expect(result).not.toContain("12345");
      expect(result).not.toContain("6789");
    });
  });

  // ============================================================
  // describeAnalyticsTrend
  // ============================================================
  describe("describeAnalyticsTrend()", () => {
    it("returns 'no data' for empty rows", () => {
      expect(describeAnalyticsTrend([], "views")).toBe("no data");
    });

    it("returns descriptor for single row", () => {
      const result = describeAnalyticsTrend(
        [{ date: "2026-04-15", views: 150 }],
        "views"
      );
      expect(result).toBe("good"); // 150 = "good"
    });

    it("identifies upward trend", () => {
      const rows = [
        { date: "2026-04-13", views: 100 },
        { date: "2026-04-14", views: 150 },
        { date: "2026-04-15", views: 200 },
      ];

      const result = describeAnalyticsTrend(rows, "views");
      expect(result).toContain("trending up");
    });

    it("identifies downward trend", () => {
      const rows = [
        { date: "2026-04-13", views: 200 },
        { date: "2026-04-14", views: 150 },
        { date: "2026-04-15", views: 100 },
      ];

      const result = describeAnalyticsTrend(rows, "views");
      expect(result).toContain("trending down");
    });

    it("identifies stable trend", () => {
      const rows = [
        { date: "2026-04-13", views: 100 },
        { date: "2026-04-14", views: 105 },
        { date: "2026-04-15", views: 103 },
      ];

      const result = describeAnalyticsTrend(rows, "views");
      expect(result).toContain("stable");
    });

    it("includes day count in description", () => {
      const rows = [
        { date: "2026-04-13", views: 100 },
        { date: "2026-04-14", views: 150 },
        { date: "2026-04-15", views: 200 },
      ];

      const result = describeAnalyticsTrend(rows, "views");
      expect(result).toContain("3 days");
    });

    it("does not include exact metric values", () => {
      const rows = [
        { date: "2026-04-13", views: 12345 },
        { date: "2026-04-14", views: 67890 },
      ];

      const result = describeAnalyticsTrend(rows, "views");
      expect(result).not.toContain("12345");
      expect(result).not.toContain("67890");
    });

    it("handles missing metric key with 0", () => {
      const rows = [
        { date: "2026-04-13" },
        { date: "2026-04-14" },
      ];

      const result = describeAnalyticsTrend(rows, "views");
      // All zeros = "none (stable over 2 days)"
      expect(result).toContain("none");
    });
  });

  // ============================================================
  // describeEngagementRate
  // ============================================================
  describe("describeEngagementRate()", () => {
    it("returns 'no engagement' for 0", () => {
      expect(describeEngagementRate(0)).toBe("no engagement");
    });

    it("returns 'no engagement' for negative values", () => {
      expect(describeEngagementRate(-1)).toBe("no engagement");
    });

    it("returns 'low engagement' for rate < 1%", () => {
      expect(describeEngagementRate(0.5)).toBe("low engagement");
    });

    it("returns 'moderate engagement' for rate 1-3%", () => {
      expect(describeEngagementRate(2)).toBe("moderate engagement");
    });

    it("returns 'good engagement' for rate 3-5%", () => {
      expect(describeEngagementRate(4)).toBe("good engagement");
    });

    it("returns 'strong engagement' for rate 5-10%", () => {
      expect(describeEngagementRate(7)).toBe("strong engagement");
    });

    it("returns 'exceptional engagement' for rate >= 10%", () => {
      expect(describeEngagementRate(15)).toBe("exceptional engagement");
    });
  });
});
