import { describe, it, expect, vi, afterEach } from "vitest";
import {
  calculateHealthScore,
  detectAnomalies,
} from "../../src/utils/healthScoreCalculator";
import type { HealthScoreInput } from "../../src/utils/healthScoreCalculator";

function defaultInput(overrides: Partial<HealthScoreInput> = {}): HealthScoreInput {
  return {
    followerGrowthRate: 5,
    currentFollowers: 5000,
    engagementRate: 0.05, // 5%
    totalPosts: 50,
    avgPostsPerDay: 1.5,
    topPostEngagement: 500,
    avgEngagement: 100,
    ...overrides,
  };
}

describe("calculateHealthScore", () => {
  it("returns a score between 0 and 100", () => {
    const result = calculateHealthScore(defaultInput());
    expect(result.score).toBeGreaterThanOrEqual(0);
    expect(result.score).toBeLessThanOrEqual(100);
  });

  it("returns a valid grade", () => {
    const validGrades = ["A+", "A", "B+", "B", "C+", "C", "D", "F"];
    const result = calculateHealthScore(defaultInput());
    expect(validGrades).toContain(result.grade);
  });

  it("returns a color string", () => {
    const result = calculateHealthScore(defaultInput());
    expect(result.color).toMatch(/^#[0-9a-f]{6}$/i);
  });

  it("breakdown sums to total score", () => {
    const result = calculateHealthScore(defaultInput());
    const breakdown = result.breakdown;
    const sum =
      breakdown.growthMomentum +
      breakdown.engagementQuality +
      breakdown.consistencyScore +
      breakdown.viralPotential +
      breakdown.competitivePosition;
    expect(result.score).toBe(Math.round(sum));
  });

  it("identifies the lowest scoring category", () => {
    const result = calculateHealthScore(defaultInput());
    expect(result.lowestCategory).toHaveProperty("name");
    expect(result.lowestCategory).toHaveProperty("score");
    expect(result.lowestCategory).toHaveProperty("maxScore");
  });

  describe("growth momentum (0-20)", () => {
    it("gives 20 for 20%+ growth", () => {
      const result = calculateHealthScore(defaultInput({ followerGrowthRate: 25 }));
      expect(result.breakdown.growthMomentum).toBe(20);
    });

    it("gives mid-range for 5% growth", () => {
      const result = calculateHealthScore(defaultInput({ followerGrowthRate: 5 }));
      expect(result.breakdown.growthMomentum).toBeGreaterThanOrEqual(10);
      expect(result.breakdown.growthMomentum).toBeLessThanOrEqual(14);
    });

    it("gives 5 for 0% growth", () => {
      const result = calculateHealthScore(defaultInput({ followerGrowthRate: 0 }));
      expect(result.breakdown.growthMomentum).toBe(5);
    });

    it("gives benefit of doubt for new accounts with negative growth", () => {
      const result = calculateHealthScore(
        defaultInput({ followerGrowthRate: -5, currentFollowers: 50 })
      );
      expect(result.breakdown.growthMomentum).toBe(5);
    });

    it("penalizes negative growth for established accounts", () => {
      const result = calculateHealthScore(
        defaultInput({ followerGrowthRate: -10, currentFollowers: 5000 })
      );
      expect(result.breakdown.growthMomentum).toBeLessThan(5);
    });
  });

  describe("engagement quality (0-25)", () => {
    it("gives 25 for 10%+ engagement", () => {
      const result = calculateHealthScore(defaultInput({ engagementRate: 0.10 }));
      expect(result.breakdown.engagementQuality).toBe(25);
    });

    it("gives mid-range for 3% engagement", () => {
      const result = calculateHealthScore(defaultInput({ engagementRate: 0.03 }));
      expect(result.breakdown.engagementQuality).toBeGreaterThanOrEqual(10);
      expect(result.breakdown.engagementQuality).toBeLessThanOrEqual(14);
    });

    it("gives low score for <1% engagement", () => {
      const result = calculateHealthScore(defaultInput({ engagementRate: 0.005 }));
      expect(result.breakdown.engagementQuality).toBeLessThanOrEqual(5);
    });
  });

  describe("consistency score (0-20)", () => {
    it("gives 20 for 1-3 posts per day", () => {
      const result = calculateHealthScore(defaultInput({ avgPostsPerDay: 2 }));
      expect(result.breakdown.consistencyScore).toBe(20);
    });

    it("gives 5 for < 5 total posts (not enough data)", () => {
      const result = calculateHealthScore(
        defaultInput({ totalPosts: 3, avgPostsPerDay: 0.5 })
      );
      expect(result.breakdown.consistencyScore).toBe(5);
    });

    it("penalizes over-posting (>3/day)", () => {
      const result = calculateHealthScore(defaultInput({ avgPostsPerDay: 6 }));
      expect(result.breakdown.consistencyScore).toBeLessThan(20);
    });

    it("gives lower score for very low frequency", () => {
      const result = calculateHealthScore(defaultInput({ avgPostsPerDay: 0.05 }));
      expect(result.breakdown.consistencyScore).toBeLessThan(5);
    });
  });

  describe("viral potential (0-15)", () => {
    it("gives 15 for 10x top/avg ratio", () => {
      const result = calculateHealthScore(
        defaultInput({ topPostEngagement: 1000, avgEngagement: 100 })
      );
      expect(result.breakdown.viralPotential).toBe(15);
    });

    it("gives 5 when both top and avg are zero", () => {
      const result = calculateHealthScore(
        defaultInput({ topPostEngagement: 0, avgEngagement: 0 })
      );
      expect(result.breakdown.viralPotential).toBe(5);
    });

    it("gives moderate score for 3x ratio", () => {
      const result = calculateHealthScore(
        defaultInput({ topPostEngagement: 300, avgEngagement: 100 })
      );
      expect(result.breakdown.viralPotential).toBeGreaterThanOrEqual(9);
      expect(result.breakdown.viralPotential).toBeLessThanOrEqual(11);
    });
  });

  describe("competitive position (0-20)", () => {
    it("gives neutral 10 when no competitor data", () => {
      const result = calculateHealthScore(
        defaultInput({ competitorBenchmarks: null })
      );
      expect(result.breakdown.competitivePosition).toBe(10);
    });

    it("gives high score when outperforming competitors", () => {
      const result = calculateHealthScore(
        defaultInput({
          competitorBenchmarks: {
            avgFollowerCount: 2000,
            avgEngagementRate: 2,
            avgPostFrequency: 1,
          },
        })
      );
      // 5000 followers vs 2000 avg (2.5x), 5% vs 2% engagement, similar posting
      expect(result.breakdown.competitivePosition).toBeGreaterThanOrEqual(15);
    });

    it("gives lower score when underperforming competitors", () => {
      const result = calculateHealthScore(
        defaultInput({
          currentFollowers: 500,
          engagementRate: 0.01,
          competitorBenchmarks: {
            avgFollowerCount: 10000,
            avgEngagementRate: 5,
            avgPostFrequency: 2,
          },
        })
      );
      expect(result.breakdown.competitivePosition).toBeLessThanOrEqual(10);
    });
  });

  describe("grades", () => {
    it("assigns A+ for 95+", () => {
      // Max everything
      const result = calculateHealthScore(
        defaultInput({
          followerGrowthRate: 25,
          engagementRate: 0.15,
          avgPostsPerDay: 2,
          topPostEngagement: 5000,
          avgEngagement: 100,
          competitorBenchmarks: {
            avgFollowerCount: 1000,
            avgEngagementRate: 1,
            avgPostFrequency: 1,
          },
        })
      );
      expect(result.grade).toBe("A+");
    });

    it("assigns F for very low scores", () => {
      const result = calculateHealthScore(
        defaultInput({
          followerGrowthRate: -20,
          currentFollowers: 10000,
          engagementRate: 0.001,
          totalPosts: 50,
          avgPostsPerDay: 0.01,
          topPostEngagement: 1,
          avgEngagement: 1,
          competitorBenchmarks: {
            avgFollowerCount: 100000,
            avgEngagementRate: 10,
            avgPostFrequency: 5,
          },
        })
      );
      expect(result.grade).toBe("F");
    });
  });

  describe("trend", () => {
    it("returns 0 when no previous score", () => {
      const result = calculateHealthScore(defaultInput());
      expect(result.trend).toBe(0);
    });

    it("returns positive diff when current > previous", () => {
      const result = calculateHealthScore(defaultInput({ previousScore: 50 }));
      expect(result.trend).toBeGreaterThan(0);
    });
  });

  describe("audience quality score", () => {
    it("returns 0-100", () => {
      const result = calculateHealthScore(defaultInput());
      expect(result.audienceQualityScore).toBeGreaterThanOrEqual(0);
      expect(result.audienceQualityScore).toBeLessThanOrEqual(100);
    });

    it("penalizes suspicious growth (high growth + low engagement)", () => {
      const suspicious = calculateHealthScore(
        defaultInput({ followerGrowthRate: 25, engagementRate: 0.01 })
      );
      const normal = calculateHealthScore(
        defaultInput({ followerGrowthRate: 5, engagementRate: 0.05 })
      );
      expect(suspicious.audienceQualityScore).toBeLessThan(
        normal.audienceQualityScore
      );
    });

    it("rewards good engagement at scale", () => {
      const scaled = calculateHealthScore(
        defaultInput({ currentFollowers: 50000, engagementRate: 0.03 })
      );
      // 3% at 50k followers gets +10 bonus
      expect(scaled.audienceQualityScore).toBeGreaterThanOrEqual(80);
    });
  });
});

describe("detectAnomalies", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns empty array when no anomalies", () => {
    const rates = Array(14).fill(5);
    // Followers must be growing to avoid follower_stall detection
    const followers = Array.from({ length: 14 }, (_, i) => 1000 + i * 5);
    const alerts = detectAnomalies(rates, 5, followers);
    expect(alerts).toEqual([]);
  });

  it("detects critical engagement drop (< 50% of avg)", () => {
    const rates = [...Array(7).fill(5), ...Array(7).fill(2)]; // recent 7 days = 2 vs avg 5
    const alerts = detectAnomalies(rates, 5, Array(14).fill(1000));
    const drop = alerts.find(
      (a) => a.type === "engagement_drop" && a.severity === "critical"
    );
    expect(drop).toBeDefined();
  });

  it("detects warning engagement drop (50-70% of avg)", () => {
    const rates = [...Array(7).fill(5), ...Array(7).fill(3.2)]; // 3.2/5 = 64%
    const alerts = detectAnomalies(rates, 5, Array(14).fill(1000));
    const drop = alerts.find(
      (a) => a.type === "engagement_drop" && a.severity === "warning"
    );
    expect(drop).toBeDefined();
  });

  it("detects engagement surge (3x+ avg in last 3 days)", () => {
    const rates = [...Array(11).fill(5), 20, 18, 22]; // last 3: avg 20 vs historical 5
    const alerts = detectAnomalies(rates, 5, Array(14).fill(1000));
    const spike = alerts.find((a) => a.type === "sudden_spike");
    expect(spike).toBeDefined();
    expect(spike!.severity).toBe("positive");
  });

  it("detects follower stall (no growth over 14 days)", () => {
    const followers = Array(14).fill(1000);
    const alerts = detectAnomalies(Array(14).fill(5), 5, followers);
    const stall = alerts.find((a) => a.type === "follower_stall");
    expect(stall).toBeDefined();
  });

  it("does not flag follower stall when growing", () => {
    const followers = Array.from({ length: 14 }, (_, i) => 1000 + i * 10);
    const alerts = detectAnomalies(Array(14).fill(5), 5, followers);
    const stall = alerts.find((a) => a.type === "follower_stall");
    expect(stall).toBeUndefined();
  });

  it("detects posting gap (>5 days since last post)", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2025-06-15T12:00:00Z"));

    const postDates = ["2025-06-05T12:00:00Z"]; // 10 days ago
    const alerts = detectAnomalies(
      Array(14).fill(5),
      5,
      Array(14).fill(1000),
      postDates
    );
    const gap = alerts.find((a) => a.type === "posting_gap");
    expect(gap).toBeDefined();
    expect(gap!.description).toContain("10 days");
  });

  it("does not flag posting gap for recent posts", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2025-06-15T12:00:00Z"));

    const postDates = ["2025-06-14T12:00:00Z"]; // 1 day ago
    const alerts = detectAnomalies(
      Array(14).fill(5),
      5,
      Array(14).fill(1000),
      postDates
    );
    const gap = alerts.find((a) => a.type === "posting_gap");
    expect(gap).toBeUndefined();
  });

  it("requires 7+ engagement rates to detect drops", () => {
    const shortRates = [1, 1, 1]; // only 3 rates
    const alerts = detectAnomalies(shortRates, 5, Array(14).fill(1000));
    const drop = alerts.find((a) => a.type === "engagement_drop");
    expect(drop).toBeUndefined();
  });
});
