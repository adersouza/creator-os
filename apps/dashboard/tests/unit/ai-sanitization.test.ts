import { describe, it, expect } from "vitest";
import {
  sanitizeMetrics,
  describeRelativePerformance,
  describeAnalyticsTrend,
  describeEngagementRate,
} from "../../api/_lib/sanitizeForAI";

describe("sanitizeMetrics", () => {
  it("converts exact numbers to descriptive buckets", () => {
    const result = sanitizeMetrics({ views: 1500, likes: 75, replies: 8 });
    expect(result).not.toContain("1500");
    expect(result).not.toContain("75");
    expect(result).not.toContain("8");
    expect(result).toContain("views:");
    expect(result).toContain("likes:");
    expect(result).toContain("replies:");
  });

  it("returns 'none' for zero values", () => {
    const result = sanitizeMetrics({ likes: 0 });
    expect(result).toContain("none");
  });

  it("preserves metric keys as labels", () => {
    const result = sanitizeMetrics({ followers: 500, engagement: 200 });
    expect(result).toContain("followers:");
    expect(result).toContain("engagement:");
  });

  it("handles empty object", () => {
    expect(sanitizeMetrics({})).toBe("");
  });

  it("skips null and NaN values", () => {
    const result = sanitizeMetrics({ valid: 100, bad: NaN } as any);
    expect(result).toContain("valid:");
    expect(result).not.toContain("bad:");
  });
});

describe("describeRelativePerformance", () => {
  it("describes above average when actual > average", () => {
    const result = describeRelativePerformance(150, 100, "views");
    expect(result).toContain("above average");
  });

  it("describes below average when actual < average", () => {
    const result = describeRelativePerformance(30, 100, "views");
    expect(result).toContain("below average");
  });

  it("returns 'no baseline' when average is 0", () => {
    expect(describeRelativePerformance(100, 0, "likes")).toContain("no baseline");
  });

  it("describes around average when close to 1x", () => {
    const result = describeRelativePerformance(110, 100, "views");
    expect(result).toContain("around average");
  });
});

describe("describeAnalyticsTrend", () => {
  it("returns 'no data' for empty rows", () => {
    expect(describeAnalyticsTrend([], "views")).toBe("no data");
  });

  it("returns single value description for one row", () => {
    const result = describeAnalyticsTrend([{ date: "2025-01-01", views: 500 }], "views");
    expect(result).toBeTruthy();
    expect(result).not.toBe("no data");
  });

  it("detects upward trend", () => {
    const rows = [
      { date: "2025-01-01", views: 100 },
      { date: "2025-01-02", views: 200 },
      { date: "2025-01-03", views: 300 },
    ];
    const result = describeAnalyticsTrend(rows, "views");
    expect(result).toContain("trending up");
  });

  it("detects downward trend", () => {
    const rows = [
      { date: "2025-01-01", views: 300 },
      { date: "2025-01-02", views: 200 },
      { date: "2025-01-03", views: 100 },
    ];
    const result = describeAnalyticsTrend(rows, "views");
    expect(result).toContain("trending down");
  });

  it("handles null/undefined metric values", () => {
    const rows = [
      { date: "2025-01-01", views: undefined },
      { date: "2025-01-02", views: null },
    ];
    const result = describeAnalyticsTrend(rows as any, "views");
    expect(result).toBeTruthy();
  });
});

describe("describeEngagementRate", () => {
  it("returns 'no engagement' for 0", () => {
    expect(describeEngagementRate(0)).toBe("no engagement");
  });

  it("returns 'low engagement' for <1%", () => {
    expect(describeEngagementRate(0.5)).toBe("low engagement");
  });

  it("returns 'good engagement' for 3-5%", () => {
    expect(describeEngagementRate(4)).toBe("good engagement");
  });

  it("returns 'exceptional engagement' for >=10%", () => {
    expect(describeEngagementRate(15)).toBe("exceptional engagement");
  });
});
