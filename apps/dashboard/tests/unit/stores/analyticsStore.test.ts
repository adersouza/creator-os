import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useAnalyticsStore, getDateRangeFromTimeframe, formatTimeframeRange, timeframeLabels } from "@/src/stores/analyticsStore";
import { useAnalyticsAICacheStore } from "@/src/stores/analyticsAICacheStore";
import type { Timeframe } from "@/src/stores/analyticsStore";

describe("analyticsStore", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: new Date("2026-04-02T12:00:00Z") });
    useAnalyticsStore.setState({
      timeframe: "30D",
      refreshKey: 0,
    });
    useAnalyticsAICacheStore.setState({
      diagnosisCache: {},
      viralAnalysisCache: {},
      postAnalysisCache: {},
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("timeframe", () => {
    it("defaults to 30D", () => {
      expect(useAnalyticsStore.getState().timeframe).toBe("30D");
    });

    it("setTimeframe updates timeframe", () => {
      useAnalyticsStore.getState().setTimeframe("7D");
      expect(useAnalyticsStore.getState().timeframe).toBe("7D");
    });

    it("setTimeframe updates refreshKey", () => {
      const before = useAnalyticsStore.getState().refreshKey;
      useAnalyticsStore.getState().setTimeframe("90D");
      expect(useAnalyticsStore.getState().refreshKey).not.toBe(before);
    });

    it("setTimeframe accepts all valid timeframes", () => {
      const timeframes: Timeframe[] = ["7D", "30D", "90D", "YTD"];
      for (const tf of timeframes) {
        useAnalyticsStore.getState().setTimeframe(tf);
        expect(useAnalyticsStore.getState().timeframe).toBe(tf);
      }
    });
  });

  describe("forceRefresh", () => {
    it("updates refreshKey", () => {
      const before = useAnalyticsStore.getState().refreshKey;
      useAnalyticsStore.getState().forceRefresh();
      expect(useAnalyticsStore.getState().refreshKey).not.toBe(before);
    });

    it("clears all AI caches", () => {
      useAnalyticsAICacheStore.getState().setCachedDiagnosis("acc1", { result: "test" });
      useAnalyticsAICacheStore.getState().setCachedViralAnalysis("post1", "viral analysis");
      useAnalyticsAICacheStore.getState().setCachedPostAnalysis("post2", "post analysis");

      useAnalyticsStore.getState().forceRefresh();

      expect(useAnalyticsAICacheStore.getState().diagnosisCache).toEqual({});
      expect(useAnalyticsAICacheStore.getState().viralAnalysisCache).toEqual({});
      expect(useAnalyticsAICacheStore.getState().postAnalysisCache).toEqual({});
    });
  });
});

describe("analyticsAICacheStore", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: new Date("2026-04-02T12:00:00Z") });
    useAnalyticsAICacheStore.setState({
      diagnosisCache: {},
      viralAnalysisCache: {},
      postAnalysisCache: {},
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("diagnosisCache", () => {
    it("setCachedDiagnosis stores a diagnosis", () => {
      const diagnosis = { summary: "healthy" };
      useAnalyticsAICacheStore.getState().setCachedDiagnosis("acc1", diagnosis);
      const cached = useAnalyticsAICacheStore.getState().getCachedDiagnosis("acc1");
      expect(cached).not.toBeNull();
      expect(cached!.diagnosis).toEqual(diagnosis);
      expect(cached!.accountId).toBe("acc1");
    });

    it("getCachedDiagnosis returns null for unknown accountId", () => {
      expect(useAnalyticsAICacheStore.getState().getCachedDiagnosis("unknown")).toBeNull();
    });

    it("getCachedDiagnosis returns null for expired entries", () => {
      useAnalyticsAICacheStore.getState().setCachedDiagnosis("acc1", { summary: "old" });
      const state = useAnalyticsAICacheStore.getState();
      const cache = { ...state.diagnosisCache };
      cache["acc1"] = { ...cache["acc1"], generatedAt: Date.now() - 25 * 60 * 60 * 1000 };
      useAnalyticsAICacheStore.setState({ diagnosisCache: cache });

      expect(useAnalyticsAICacheStore.getState().getCachedDiagnosis("acc1")).toBeNull();
    });

    it("getCachedDiagnosis returns valid fresh entries", () => {
      useAnalyticsAICacheStore.getState().setCachedDiagnosis("acc1", { summary: "fresh" });
      expect(useAnalyticsAICacheStore.getState().getCachedDiagnosis("acc1")).not.toBeNull();
    });
  });

  describe("viralAnalysisCache", () => {
    it("setCachedViralAnalysis stores analysis", () => {
      useAnalyticsAICacheStore.getState().setCachedViralAnalysis("post1", "This post went viral because...");
      expect(useAnalyticsAICacheStore.getState().getCachedViralAnalysis("post1")).toBe("This post went viral because...");
    });

    it("getCachedViralAnalysis returns null for unknown postId", () => {
      expect(useAnalyticsAICacheStore.getState().getCachedViralAnalysis("unknown")).toBeNull();
    });

    it("getCachedViralAnalysis returns null for expired entries", () => {
      useAnalyticsAICacheStore.getState().setCachedViralAnalysis("post1", "old analysis");
      const state = useAnalyticsAICacheStore.getState();
      const cache = { ...state.viralAnalysisCache };
      cache["post1"] = { ...cache["post1"], generatedAt: Date.now() - 25 * 60 * 60 * 1000 };
      useAnalyticsAICacheStore.setState({ viralAnalysisCache: cache });

      expect(useAnalyticsAICacheStore.getState().getCachedViralAnalysis("post1")).toBeNull();
    });
  });

  describe("postAnalysisCache", () => {
    it("setCachedPostAnalysis stores analysis", () => {
      useAnalyticsAICacheStore.getState().setCachedPostAnalysis("post1", "Great engagement");
      expect(useAnalyticsAICacheStore.getState().getCachedPostAnalysis("post1")).toBe("Great engagement");
    });

    it("getCachedPostAnalysis returns null for unknown postId", () => {
      expect(useAnalyticsAICacheStore.getState().getCachedPostAnalysis("unknown")).toBeNull();
    });

    it("getCachedPostAnalysis returns null for expired entries", () => {
      useAnalyticsAICacheStore.getState().setCachedPostAnalysis("post1", "old");
      const state = useAnalyticsAICacheStore.getState();
      const cache = { ...state.postAnalysisCache };
      cache["post1"] = { ...cache["post1"], generatedAt: Date.now() - 25 * 60 * 60 * 1000 };
      useAnalyticsAICacheStore.setState({ postAnalysisCache: cache });

      expect(useAnalyticsAICacheStore.getState().getCachedPostAnalysis("post1")).toBeNull();
    });
  });

  describe("clearAICache", () => {
    it("clears all caches", () => {
      useAnalyticsAICacheStore.getState().setCachedDiagnosis("acc1", { test: true });
      useAnalyticsAICacheStore.getState().setCachedViralAnalysis("post1", "test");
      useAnalyticsAICacheStore.getState().setCachedPostAnalysis("post2", "test");

      useAnalyticsAICacheStore.getState().clearAICache();

      expect(useAnalyticsAICacheStore.getState().diagnosisCache).toEqual({});
      expect(useAnalyticsAICacheStore.getState().viralAnalysisCache).toEqual({});
      expect(useAnalyticsAICacheStore.getState().postAnalysisCache).toEqual({});
    });
  });
});

describe("getDateRangeFromTimeframe", () => {
  it("returns 7-day range for 7D", () => {
    const { start, end } = getDateRangeFromTimeframe("7D");
    const diffDays = Math.round((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24));
    expect(diffDays).toBeGreaterThanOrEqual(7);
    expect(diffDays).toBeLessThanOrEqual(8);
  });

  it("returns 30-day range for 30D", () => {
    const { start, end } = getDateRangeFromTimeframe("30D");
    const diffDays = Math.round((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24));
    expect(diffDays).toBeGreaterThanOrEqual(30);
    expect(diffDays).toBeLessThanOrEqual(31);
  });

  it("returns 90-day range for 90D", () => {
    const { start, end } = getDateRangeFromTimeframe("90D");
    const diffDays = Math.round((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24));
    expect(diffDays).toBeGreaterThanOrEqual(90);
    expect(diffDays).toBeLessThanOrEqual(91);
  });

  it("returns year-to-date range for YTD", () => {
    const { start } = getDateRangeFromTimeframe("YTD");
    expect(start.getMonth()).toBe(0);
    expect(start.getDate()).toBe(1);
  });

  it("sets start hours to midnight", () => {
    const { start } = getDateRangeFromTimeframe("7D");
    expect(start.getHours()).toBe(0);
    expect(start.getMinutes()).toBe(0);
  });

  it("sets end hours to end of day", () => {
    const { end } = getDateRangeFromTimeframe("7D");
    expect(end.getHours()).toBe(23);
    expect(end.getMinutes()).toBe(59);
  });
});

describe("formatTimeframeRange", () => {
  it("returns a string with date range", () => {
    const result = formatTimeframeRange("7D");
    expect(result).toContain(" \u2013 ");
    expect(result).toMatch(/[A-Z][a-z]{2} \d+/);
  });
});

describe("timeframeLabels", () => {
  it("has labels for all timeframes", () => {
    expect(timeframeLabels["7D"]).toBe("last 7 days");
    expect(timeframeLabels["30D"]).toBe("last 30 days");
    expect(timeframeLabels["90D"]).toBe("last 90 days");
    expect(timeframeLabels["YTD"]).toBe("year to date");
  });
});
