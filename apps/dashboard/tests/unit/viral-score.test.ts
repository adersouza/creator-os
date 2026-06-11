import { describe, it, expect } from "vitest";
import { calculateViralScore } from "../../src/utils/viralScore";
import type { ViralScoreParams } from "../../src/utils/viralScore";

function defaultParams(overrides: Partial<ViralScoreParams> = {}): ViralScoreParams {
  return {
    postTime: new Date("2025-06-15T14:00:00Z"), // Sunday 2 PM UTC
    mediaType: "text",
    captionLength: 150,
    hashtags: [],
    platform: "threads",
    bestTimes: [],
    typePerformance: {},
    hashtagPerformance: {},
    totalPosts: 50,
    ...overrides,
  };
}

describe("calculateViralScore", () => {
  it("returns a score between 1 and 10", () => {
    const result = calculateViralScore(defaultParams());
    expect(result.score).toBeGreaterThanOrEqual(1);
    expect(result.score).toBeLessThanOrEqual(10);
  });

  it("returns a breakdown with all six components", () => {
    const result = calculateViralScore(defaultParams());
    expect(result.breakdown).toHaveProperty("replyPotential");
    expect(result.breakdown).toHaveProperty("completionSignal");
    expect(result.breakdown).toHaveProperty("timing");
    expect(result.breakdown).toHaveProperty("type");
    expect(result.breakdown).toHaveProperty("caption");
    expect(result.breakdown).toHaveProperty("hashtags");
  });

  it("all breakdown values are between 1 and 10", () => {
    const result = calculateViralScore(defaultParams());
    for (const value of Object.values(result.breakdown)) {
      expect(value).toBeGreaterThanOrEqual(1);
      expect(value).toBeLessThanOrEqual(10);
    }
  });

  describe("reply potential", () => {
    it("boosts score for questions", () => {
      const withQuestion = calculateViralScore(
        defaultParams({ captionText: "What do you think about AI?" })
      );
      const withoutQuestion = calculateViralScore(
        defaultParams({ captionText: "AI is interesting." })
      );
      expect(withQuestion.breakdown.replyPotential).toBeGreaterThan(
        withoutQuestion.breakdown.replyPotential
      );
    });

    it("boosts score for engagement prompts", () => {
      const withPrompt = calculateViralScore(
        defaultParams({ captionText: "Hot take: remote work is better. Agree?" })
      );
      const plain = calculateViralScore(
        defaultParams({ captionText: "Remote work is common now." })
      );
      expect(withPrompt.breakdown.replyPotential).toBeGreaterThan(
        plain.breakdown.replyPotential
      );
    });

    it("uses reply velocity when available", () => {
      const withVelocity = calculateViralScore(
        defaultParams({
          captionText: "Just a thought.",
          replyVelocityAvg: 10,
          accountAvgReplies1h: 5,
        })
      );
      const withoutVelocity = calculateViralScore(
        defaultParams({ captionText: "Just a thought." })
      );
      expect(withVelocity.breakdown.replyPotential).toBeGreaterThanOrEqual(
        withoutVelocity.breakdown.replyPotential
      );
    });
  });

  describe("completion signal", () => {
    it("boosts score for high saves rate", () => {
      const highSaves = calculateViralScore(
        defaultParams({ captionText: "Some content.", savesRate: 0.06 })
      );
      const lowSaves = calculateViralScore(
        defaultParams({ captionText: "Some content.", savesRate: 0.001 })
      );
      expect(highSaves.breakdown.completionSignal).toBeGreaterThan(
        lowSaves.breakdown.completionSignal
      );
    });

    it("boosts for hook patterns", () => {
      const withHook = calculateViralScore(
        defaultParams({ captionText: "Here's what nobody tells you about growth.\nLine 2.\nLine 3." })
      );
      const noHook = calculateViralScore(
        defaultParams({ captionText: "Growth thoughts." })
      );
      expect(withHook.breakdown.completionSignal).toBeGreaterThan(
        noHook.breakdown.completionSignal
      );
    });
  });

  describe("caption length", () => {
    it("gives optimal score for caption in sweet spot (threads)", () => {
      const optimal = calculateViralScore(
        defaultParams({ captionLength: 150, platform: "threads" })
      );
      expect(optimal.breakdown.caption).toBe(9);
    });

    it("gives lower score for empty caption", () => {
      const empty = calculateViralScore(defaultParams({ captionLength: 0 }));
      expect(empty.breakdown.caption).toBe(2);
    });

    it("penalizes very long captions", () => {
      const long = calculateViralScore(defaultParams({ captionLength: 1000 }));
      expect(long.breakdown.caption).toBeLessThan(9);
    });

    it("uses different optimal range for instagram", () => {
      // Instagram optimal: 100-500
      const igOptimal = calculateViralScore(
        defaultParams({ captionLength: 300, platform: "instagram" })
      );
      expect(igOptimal.breakdown.caption).toBe(9);

      // 50 chars is below IG optimal but in Threads optimal range
      const igShort = calculateViralScore(
        defaultParams({ captionLength: 50, platform: "instagram" })
      );
      expect(igShort.breakdown.caption).toBeLessThan(9);
    });
  });

  describe("hashtags", () => {
    it("gives neutral-ish score for no hashtags on threads", () => {
      const result = calculateViralScore(
        defaultParams({ hashtags: [], platform: "threads" })
      );
      expect(result.breakdown.hashtags).toBe(6); // threads doesn't rely on hashtags
    });

    it("gives lower score for no hashtags on instagram", () => {
      const result = calculateViralScore(
        defaultParams({ hashtags: [], platform: "instagram" })
      );
      expect(result.breakdown.hashtags).toBe(3);
    });
  });

  describe("confidence levels", () => {
    it("returns low confidence for < 15 posts", () => {
      const result = calculateViralScore(defaultParams({ totalPosts: 5 }));
      expect(result.confidence).toBe("low");
      expect(result.confidenceLabel).toContain("Early data");
    });

    it("caps score at 7 for low confidence", () => {
      // Force high engagement to try to push score above 7
      const result = calculateViralScore(
        defaultParams({
          totalPosts: 5,
          captionText: "What do you think? Thoughts? Share your hot take!",
          savesRate: 0.1,
          captionLength: 150,
        })
      );
      expect(result.score).toBeLessThanOrEqual(7);
    });

    it("returns medium confidence for 15-30 posts", () => {
      const result = calculateViralScore(defaultParams({ totalPosts: 20 }));
      expect(result.confidence).toBe("medium");
    });

    it("caps score at 9 for medium confidence", () => {
      const result = calculateViralScore(
        defaultParams({
          totalPosts: 20,
          captionText: "What do you think? Thoughts? Share your hot take!",
          savesRate: 0.1,
          captionLength: 150,
        })
      );
      expect(result.score).toBeLessThanOrEqual(9);
    });

    it("returns high confidence for > 30 posts", () => {
      const result = calculateViralScore(defaultParams({ totalPosts: 50 }));
      expect(result.confidence).toBe("high");
    });
  });

  describe("calibration adjustment", () => {
    it("applies calibration multiplier", () => {
      const base = calculateViralScore(
        defaultParams({ calibrationAdjustment: 1.0 })
      );
      const boosted = calculateViralScore(
        defaultParams({ calibrationAdjustment: 1.5 })
      );
      expect(boosted.score).toBeGreaterThanOrEqual(base.score);
    });

    it("clamps calibrated score to 1-10 range", () => {
      const result = calculateViralScore(
        defaultParams({ calibrationAdjustment: 100 })
      );
      expect(result.score).toBeLessThanOrEqual(10);

      const lowResult = calculateViralScore(
        defaultParams({ calibrationAdjustment: 0.01 })
      );
      expect(lowResult.score).toBeGreaterThanOrEqual(1);
    });
  });

  describe("timing score", () => {
    it("defaults to neutral when no best times provided", () => {
      const result = calculateViralScore(defaultParams({ bestTimes: [] }));
      expect(result.breakdown.timing).toBe(5);
    });

    it("adjusts based on best times match", () => {
      const sunday2pm = calculateViralScore(
        defaultParams({
          postTime: new Date("2025-06-15T14:00:00Z"), // Sunday
          bestTimes: [{ day: "Sunday", hour: "2:00 PM", score: 0.9 }],
        })
      );
      const mismatch = calculateViralScore(
        defaultParams({
          postTime: new Date("2025-06-16T03:00:00Z"), // Monday 3 AM
          bestTimes: [{ day: "Sunday", hour: "2:00 PM", score: 0.9 }],
        })
      );
      expect(sunday2pm.breakdown.timing).toBeGreaterThanOrEqual(
        mismatch.breakdown.timing
      );
    });
  });

  describe("type score", () => {
    it("defaults to neutral when no type performance data", () => {
      const result = calculateViralScore(defaultParams({ typePerformance: {} }));
      expect(result.breakdown.type).toBe(5);
    });

    it("uses type performance to score", () => {
      const result = calculateViralScore(
        defaultParams({
          mediaType: "image",
          typePerformance: { image: 100, text: 50, video: 80 },
        })
      );
      expect(result.breakdown.type).toBe(10); // image is the best performer
    });
  });
});
