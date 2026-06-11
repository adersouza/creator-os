import { describe, it, expect } from "vitest";
import {
  calculateEngagementRate,
  calculateInstagramEngagementRate,
  getERTier,
  formatEngagementRate,
  isHighPerformer,
} from "../../utils/engagementRate";
import type { PostPerformance } from "../../types/analytics";

function perf(overrides: Partial<PostPerformance> = {}): PostPerformance {
  return { views: 1000, likes: 50, replies: 10, reposts: 5, quotes: 3, shares: 2, ...overrides };
}

describe("calculateEngagementRate", () => {
  it("calculates weighted rate: likes + replies×2 + reposts×1.5 + quotes + shares / views", () => {
    const result = calculateEngagementRate(perf());
    // (50 + 10×2 + 5×1.5 + 3 + 2) / 1000 × 100 = (50+20+7.5+3+2)/1000*100 = 8.25%
    expect(result).toBeCloseTo(8.25);
  });

  it("returns null for zero views", () => {
    expect(calculateEngagementRate(perf({ views: 0 }))).toBeNull();
  });

  it("returns null for undefined performance", () => {
    expect(calculateEngagementRate(undefined)).toBeNull();
  });

  it("returns 0% when all interactions are zero", () => {
    const result = calculateEngagementRate(perf({ likes: 0, replies: 0, reposts: 0, quotes: 0, shares: 0 }));
    expect(result).toBe(0);
  });

  it("handles large numbers correctly", () => {
    const result = calculateEngagementRate(perf({ views: 1_000_000, likes: 50_000, replies: 10_000, reposts: 5_000, quotes: 3_000, shares: 2_000 }));
    // (50000 + 20000 + 7500 + 3000 + 2000) / 1000000 × 100 = 8.25%
    expect(result).toBeCloseTo(8.25);
  });
});

describe("calculateInstagramEngagementRate", () => {
  it("uses weighted formula: likes + comments×2 + saved×3 + shares / reach", () => {
    const result = calculateInstagramEngagementRate({ likes: 100, comments: 20, shares: 10, saved: 5, reach: 1000 });
    // (100 + 20×2 + 5×3 + 10) / 1000 × 100 = (100+40+15+10)/1000*100 = 16.5%
    expect(result).toBeCloseTo(16.5);
  });

  it("falls back to impressions when reach is 0", () => {
    const result = calculateInstagramEngagementRate({ likes: 100, comments: 20, shares: 0, saved: 0, reach: 0, impressions: 2000 });
    // (100 + 20×2 + 0 + 0) / 2000 × 100 = 140/2000*100 = 7.0%
    expect(result).toBeCloseTo(7.0);
  });

  it("returns 0 when no valid divisor", () => {
    expect(calculateInstagramEngagementRate({ likes: 100, reach: 0, impressions: 0 })).toBe(0);
  });
});

describe("getERTier", () => {
  it("returns high for >3%", () => expect(getERTier(5)).toBe("high"));
  it("returns medium for 1.5-3%", () => expect(getERTier(2)).toBe("medium"));
  it("returns low for <1.5%", () => expect(getERTier(0.5)).toBe("low"));
});

describe("formatEngagementRate", () => {
  it("formats null as dash", () => expect(formatEngagementRate(null)).toBe("-"));
  it("shows <0.1% for tiny values", () => expect(formatEngagementRate(0.05)).toBe("<0.1%"));
  it("shows >20% for extreme values", () => expect(formatEngagementRate(25)).toBe(">20%"));
  it("formats normal values with 1 decimal", () => expect(formatEngagementRate(3.456)).toBe("3.5%"));
});

describe("isHighPerformer", () => {
  it("returns true for >3% ER and >=10 views", () => {
    expect(isHighPerformer(perf({ views: 100, likes: 10, replies: 5, reposts: 0, quotes: 0, shares: 0 }))).toBe(true);
  });

  it("returns false for <10 views even with high ER", () => {
    expect(isHighPerformer(perf({ views: 5, likes: 5, replies: 5, reposts: 5, quotes: 0, shares: 5 }))).toBe(false);
  });

  it("returns false for undefined performance", () => {
    expect(isHighPerformer(undefined)).toBe(false);
  });
});
