import { describe, it, expect } from "vitest";
import { computeDelta, EMPTY_DELTAS } from "../../src/utils/deltas";

describe("computeDelta", () => {
  it("computes positive change percentage", () => {
    const result = computeDelta(150, 100);
    expect(result.value).toBe("+50.0%");
    expect(result.trend).toBe("up");
  });

  it("computes negative change percentage", () => {
    const result = computeDelta(50, 100);
    expect(result.value).toBe("-50.0%");
    expect(result.trend).toBe("down");
  });

  it("returns neutral for equal values", () => {
    const result = computeDelta(100, 100);
    expect(result.value).toBe("0%");
    expect(result.trend).toBe("neutral");
  });

  it("returns neutral for both zero", () => {
    const result = computeDelta(0, 0);
    expect(result.value).toBe("0%");
    expect(result.trend).toBe("neutral");
  });

  it("returns +infinity when previous is zero and current is positive", () => {
    const result = computeDelta(100, 0);
    expect(result.value).toBe("+∞");
    expect(result.trend).toBe("up");
  });

  it("returns 0% when both previous and current are zero", () => {
    const result = computeDelta(0, 0);
    expect(result.value).toBe("0%");
    expect(result.trend).toBe("neutral");
  });

  it("handles negative previous (guard) — treats as zero baseline", () => {
    // previous <= 0 branch: current > 0 → +∞
    const result = computeDelta(50, -10);
    expect(result.value).toBe("+∞");
    expect(result.trend).toBe("up");
  });

  it("handles negative previous with zero current", () => {
    const result = computeDelta(0, -10);
    expect(result.value).toBe("0%");
    expect(result.trend).toBe("neutral");
  });

  it("treats very small change as neutral", () => {
    // 0.05% change is below 0.1 threshold
    const result = computeDelta(100.05, 100);
    expect(result.value).toBe("0%");
    expect(result.trend).toBe("neutral");
  });

  it("handles large numbers without overflow", () => {
    const result = computeDelta(2_000_000, 1_000_000);
    expect(result.value).toBe("+100.0%");
    expect(result.trend).toBe("up");
  });

  it("handles fractional values", () => {
    const result = computeDelta(1.5, 1.0);
    expect(result.value).toBe("+50.0%");
    expect(result.trend).toBe("up");
  });

  it("formats with 1 decimal place", () => {
    const result = computeDelta(133, 100);
    expect(result.value).toBe("+33.0%");
  });

  it("does not include + sign for negative values", () => {
    const result = computeDelta(75, 100);
    expect(result.value).toMatch(/^-/);
    expect(result.value).not.toMatch(/^\+-/);
  });
});

describe("EMPTY_DELTAS", () => {
  it("has all required keys with dash values", () => {
    const keys = ["followers", "likes", "replies", "reposts", "views", "clicks", "reach", "saves", "shares", "engagement"];
    for (const key of keys) {
      expect(EMPTY_DELTAS).toHaveProperty(key, "—");
    }
  });
});
