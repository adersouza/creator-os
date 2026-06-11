/**
 * Tests for time-series gap filling:
 * When a user has data for days 1 and 5, the chart array must include days 2-4 with zero values.
 */
import { describe, it, expect } from "vitest";
import { fillDateGaps } from "../../utils/fillDateGaps";

/** Helper: create a local midnight date (matches how rawDate is created in analytics) */
function localDate(y: number, m: number, d: number): Date {
  return new Date(y, m - 1, d);
}

describe("fillDateGaps", () => {
  it("fills missing dates with zero-value objects", () => {
    const data = [
      { date: "Mar 1", rawDate: localDate(2026, 3, 1), followers: 100, views: 50 },
      { date: "Mar 4", rawDate: localDate(2026, 3, 4), followers: 110, views: 80 },
    ];
    const start = localDate(2026, 3, 1);
    const end = localDate(2026, 3, 4);

    const result = fillDateGaps(data, start, end);

    expect(result).toHaveLength(4); // Mar 1, 2, 3, 4
    // Original data preserved
    expect(result[0].followers).toBe(100);
    expect(result[3].followers).toBe(110);
    // Gap days filled with last known followers, zero engagement
    expect(result[1].rawDate.getDate()).toBe(2);
    expect(result[1].views).toBe(0);
    expect(result[2].rawDate.getDate()).toBe(3);
    expect(result[2].views).toBe(0);
  });

  it("returns original data unchanged when no gaps exist", () => {
    const data = [
      { date: "Mar 1", rawDate: localDate(2026, 3, 1), followers: 100, views: 10 },
      { date: "Mar 2", rawDate: localDate(2026, 3, 2), followers: 101, views: 20 },
      { date: "Mar 3", rawDate: localDate(2026, 3, 3), followers: 102, views: 30 },
    ];
    const result = fillDateGaps(data, localDate(2026, 3, 1), localDate(2026, 3, 3));
    expect(result).toHaveLength(3);
    expect(result[0].views).toBe(10);
    expect(result[2].views).toBe(30);
  });

  it("handles empty input — returns zero-filled range", () => {
    const result = fillDateGaps([] as { date: string; rawDate: Date; [key: string]: unknown }[], localDate(2026, 3, 1), localDate(2026, 3, 3));
    expect(result).toHaveLength(3);
    expect(result[0].followers).toBe(0);
    expect(result[0].views).toBe(0);
  });

  it("handles single data point", () => {
    const data = [
      { date: "Mar 2", rawDate: localDate(2026, 3, 2), followers: 50, views: 10 },
    ];
    const result = fillDateGaps(data, localDate(2026, 3, 1), localDate(2026, 3, 3));
    expect(result).toHaveLength(3);
    expect(result[0].views).toBe(0);  // Mar 1 — gap before data
    expect(result[1].views).toBe(10); // Mar 2 — real data
    expect(result[2].views).toBe(0);  // Mar 3 — gap after data
  });
});
