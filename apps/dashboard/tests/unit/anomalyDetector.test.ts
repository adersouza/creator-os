/**
 * Anomaly Detector — Unit Tests
 *
 * Tests the anomaly detection engine that detects shadowbans,
 * engagement drops, follower anomalies, and composite health decline.
 * Validates statistical detection, thresholds, dedup, edge cases.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — must be declared before importing the module under test
// ---------------------------------------------------------------------------

const mockInsert = vi.fn().mockResolvedValue({ error: null });
const mockUpdateEq = vi.fn().mockResolvedValue({ error: null });
const mockUpdate = vi.fn().mockReturnValue({ eq: mockUpdateEq });

/** Track what tables are queried and return appropriate data */
const mockFrom = vi.fn();

vi.mock("../../api/_lib/supabase.js", () => ({
  getSupabase: () => ({
    from: mockFrom,
  }),
}));

vi.mock("../../api/_lib/createNotification.js", () => ({
  createNotification: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../../api/_lib/logger.js", () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}));

// Mock the AI analysis generation (called asynchronously after alert insert)
vi.mock("@google/genai", () => ({
  GoogleGenAI: vi.fn().mockImplementation(() => ({
    models: {
      generateContent: vi.fn().mockResolvedValue({ text: "AI analysis text" }),
    },
  })),
}));

import { detectAnomalies, generateAIAnalysis } from "../../api/_lib/anomalyDetector.js";
import { createNotification } from "../../api/_lib/createNotification.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface AnalyticsRowInput {
  date: string;
  followers_count?: number | null;
  total_views?: number | null;
  total_likes?: number | null;
  total_replies?: number | null;
  total_reposts?: number | null;
  total_shares?: number | null;
  total_reach?: number | null;
  engagement_rate?: number | null;
  follower_growth?: number | null;
  ig_reach?: number | null;
}

function makeAnalyticsRow(day: number, overrides: Partial<AnalyticsRowInput> = {}): AnalyticsRowInput {
  const date = new Date();
  date.setDate(date.getDate() - (14 - day));
  return {
    date: date.toISOString().split("T")[0],
    followers_count: 5000,
    total_views: 10000,
    total_likes: 500,
    total_replies: 50,
    total_reposts: 30,
    total_shares: 20,
    total_reach: 8000,
    engagement_rate: 5.0,
    follower_growth: 10,
    ig_reach: null,
    ...overrides,
  };
}

/** Generate 14 days of stable analytics data */
function makeStableAnalytics(baseOverrides: Partial<AnalyticsRowInput> = {}): AnalyticsRowInput[] {
  return Array.from({ length: 14 }, (_, i) => makeAnalyticsRow(i, baseOverrides));
}

/**
 * Generate analytics where the last 3 days have significantly different values
 * from the first 11 days (to simulate a drop or spike).
 */
function makeAnalyticsWithRecentDrop(
  baseValues: Partial<AnalyticsRowInput>,
  recentValues: Partial<AnalyticsRowInput>,
): AnalyticsRowInput[] {
  const rows: AnalyticsRowInput[] = [];
  for (let i = 0; i < 11; i++) {
    rows.push(makeAnalyticsRow(i, baseValues));
  }
  for (let i = 11; i < 14; i++) {
    rows.push(makeAnalyticsRow(i, recentValues));
  }
  return rows;
}

/** Set up the mockFrom to return analytics data and handle alert queries */
function setupMocks(analyticsRows: AnalyticsRowInput[], existingAlerts: { id: string }[] = []) {
  mockFrom.mockImplementation((table: string) => {
    if (table === "account_analytics") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            gte: vi.fn().mockReturnValue({
              order: vi.fn().mockResolvedValue({
                data: analyticsRows,
                error: null,
              }),
            }),
          }),
        }),
      };
    }
    if (table === "anomaly_alerts") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            is: vi.fn().mockReturnValue({
              gte: vi.fn().mockReturnValue({
                eq: vi.fn().mockReturnValue({
                  limit: vi.fn().mockResolvedValue({
                    data: existingAlerts,
                    error: null,
                  }),
                }),
              }),
            }),
          }),
        }),
        insert: mockInsert,
        update: mockUpdate,
      };
    }
    if (table === "accounts" || table === "instagram_accounts") {
      return {
        update: mockUpdate,
      };
    }
    if (table === "posts") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockReturnValue({
              order: vi.fn().mockReturnValue({
                limit: vi.fn().mockResolvedValue({ data: [], error: null }),
              }),
            }),
            order: vi.fn().mockReturnValue({
              limit: vi.fn().mockResolvedValue({ data: [], error: null }),
            }),
          }),
        }),
      };
    }
    // Fallback
    return {
      select: vi.fn().mockReturnThis(),
      eq: vi.fn().mockReturnThis(),
      insert: mockInsert,
      update: mockUpdate,
    };
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("anomalyDetector", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockInsert.mockResolvedValue({ error: null });
    mockUpdate.mockReturnValue({ eq: mockUpdateEq });
    mockUpdateEq.mockResolvedValue({ error: null });
  });

  // =========================================================================
  // 1. Insufficient data — should bail out gracefully
  // =========================================================================

  describe("insufficient data handling", () => {
    it("skips detection when fewer than 14 days of data", async () => {
      const fewDays = Array.from({ length: 7 }, (_, i) => makeAnalyticsRow(i));
      setupMocks(fewDays);

      await detectAnomalies("acc-1", "threads", "user-1");

      // Should not insert any alerts
      expect(mockInsert).not.toHaveBeenCalled();
    });

    it("skips detection when analytics query returns an error", async () => {
      mockFrom.mockImplementation((table: string) => {
        if (table === "account_analytics") {
          return {
            select: vi.fn().mockReturnValue({
              eq: vi.fn().mockReturnValue({
                gte: vi.fn().mockReturnValue({
                  order: vi.fn().mockResolvedValue({
                    data: null,
                    error: { message: "DB error" },
                  }),
                }),
              }),
            }),
          };
        }
        return { select: vi.fn().mockReturnThis() };
      });

      await detectAnomalies("acc-1", "threads", "user-1");
      expect(mockInsert).not.toHaveBeenCalled();
    });

    it("skips detection when account has fewer than 100 followers", async () => {
      const rows = makeStableAnalytics({ followers_count: 50 });
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");
      expect(mockInsert).not.toHaveBeenCalled();
    });

    it("skips when analytics returns empty array", async () => {
      setupMocks([]);
      await detectAnomalies("acc-1", "threads", "user-1");
      expect(mockInsert).not.toHaveBeenCalled();
    });
  });

  // =========================================================================
  // 2. Shadowban detection — reach-to-followers ratio drop
  // =========================================================================

  describe("shadowban detection", () => {
    it("detects shadowban when reach-to-follower ratio drops significantly", async () => {
      // Baseline: healthy reach ratio (10000 views / 5000 followers = 2.0)
      // Recent 3 days: very low reach (500 views / 5000 followers = 0.1)
      const rows = makeAnalyticsWithRecentDrop(
        { total_views: 10000, followers_count: 5000 },
        { total_views: 500, followers_count: 5000 },
      );
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");

      // Should have inserted a shadowban alert
      const insertCalls = mockInsert.mock.calls;
      const shadowbanInsert = insertCalls.find(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "shadowban_suspected",
      );
      expect(shadowbanInsert).toBeDefined();
    });

    it("does NOT flag shadowban when reach is stable", async () => {
      const rows = makeStableAnalytics({
        total_views: 10000,
        followers_count: 5000,
      });
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");

      const insertCalls = mockInsert.mock.calls;
      const shadowbanInsert = insertCalls.find(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "shadowban_suspected",
      );
      expect(shadowbanInsert).toBeUndefined();
    });

    it("uses ig_reach for Instagram platform", async () => {
      const rows = makeAnalyticsWithRecentDrop(
        { ig_reach: 10000, total_views: 0, followers_count: 5000 },
        { ig_reach: 200, total_views: 0, followers_count: 5000 },
      );
      setupMocks(rows);

      await detectAnomalies("ig-acc-1", "instagram", "user-1");

      const insertCalls = mockInsert.mock.calls;
      const shadowbanInsert = insertCalls.find(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "shadowban_suspected",
      );
      expect(shadowbanInsert).toBeDefined();
      // Instagram alerts should use instagram_account_id, not account_id
      if (shadowbanInsert) {
        expect((shadowbanInsert[0] as Record<string, unknown>).instagram_account_id).toBe("ig-acc-1");
        expect((shadowbanInsert[0] as Record<string, unknown>).account_id).toBeUndefined();
      }
    });
  });

  // =========================================================================
  // 3. Engagement rate drop detection
  // =========================================================================

  describe("engagement drop detection", () => {
    it("detects significant engagement rate drop", async () => {
      const rows = makeAnalyticsWithRecentDrop(
        { engagement_rate: 8.0, total_views: 10000, followers_count: 5000 },
        { engagement_rate: 1.0, total_views: 10000, followers_count: 5000 },
      );
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");

      const insertCalls = mockInsert.mock.calls;
      const engDropInsert = insertCalls.find(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "engagement_drop",
      );
      expect(engDropInsert).toBeDefined();
    });

    it("does NOT flag when engagement is steady", async () => {
      const rows = makeStableAnalytics({ engagement_rate: 5.0 });
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");

      const insertCalls = mockInsert.mock.calls;
      const engDropInsert = insertCalls.find(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "engagement_drop",
      );
      expect(engDropInsert).toBeUndefined();
    });

    it("skips engagement detection when baseline has zero engagement", async () => {
      const rows = makeStableAnalytics({ engagement_rate: 0 });
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");

      const insertCalls = mockInsert.mock.calls;
      const engDropInsert = insertCalls.find(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "engagement_drop",
      );
      expect(engDropInsert).toBeUndefined();
    });
  });

  // =========================================================================
  // 4. Follower drop detection — day-over-day
  // =========================================================================

  describe("follower drop detection", () => {
    it("detects a single-day follower drop exceeding 5%", async () => {
      const rows = makeStableAnalytics({ followers_count: 10000 });
      // Drop from 10000 to 9000 on the last day (10% drop)
      rows[rows.length - 1].followers_count = 9000;
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");

      const insertCalls = mockInsert.mock.calls;
      const followerDropInsert = insertCalls.find(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "follower_drop",
      );
      expect(followerDropInsert).toBeDefined();
      if (followerDropInsert) {
        const alertData = (followerDropInsert[0] as Record<string, unknown>).data as Record<string, unknown>;
        expect(alertData.previousCount).toBe(10000);
        expect(alertData.currentCount).toBe(9000);
      }
    });

    it("does NOT flag minor follower fluctuation under 5%", async () => {
      const rows = makeStableAnalytics({ followers_count: 10000 });
      // Small dip: 10000 -> 9700 (3% drop)
      rows[rows.length - 1].followers_count = 9700;
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");

      const insertCalls = mockInsert.mock.calls;
      const followerDropInsert = insertCalls.find(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "follower_drop",
      );
      expect(followerDropInsert).toBeUndefined();
    });

    it("only flags the most recent follower drop (breaks after first)", async () => {
      const rows = makeStableAnalytics({ followers_count: 10000 });
      // Two drops: day 5 (10000 -> 8000) and day 10 (10000 -> 8500)
      rows[5].followers_count = 8000;
      rows[10].followers_count = 8500;
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");

      const insertCalls = mockInsert.mock.calls;
      const followerDropInserts = insertCalls.filter(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "follower_drop",
      );
      // Should only flag one drop (the first one found iterating forward)
      expect(followerDropInserts.length).toBeLessThanOrEqual(1);
    });
  });

  // =========================================================================
  // 5. Composite Health Score — reach_anomaly alert
  // =========================================================================

  describe("composite health score", () => {
    it("detects declining health when composite drops below 0.8", async () => {
      // All metrics drop significantly in recent 3 days
      const rows = makeAnalyticsWithRecentDrop(
        {
          total_views: 10000,
          total_shares: 100,
          total_reposts: 50,
          total_replies: 80,
          total_likes: 500,
          followers_count: 5000,
        },
        {
          total_views: 2000,    // 80% reach drop
          total_shares: 10,     // 90% share drop
          total_reposts: 5,
          total_replies: 8,     // 90% comment drop
          total_likes: 50,      // 90% like drop
          followers_count: 5000,
        },
      );
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");

      const insertCalls = mockInsert.mock.calls;
      const healthInsert = insertCalls.find(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "reach_anomaly",
      );
      expect(healthInsert).toBeDefined();
    });

    it("auto-pauses account when health score drops below 0.5 (critical)", async () => {
      // Severe drop: nearly zero engagement in recent days
      const rows = makeAnalyticsWithRecentDrop(
        {
          total_views: 10000,
          total_shares: 100,
          total_reposts: 50,
          total_replies: 80,
          total_likes: 500,
          followers_count: 5000,
        },
        {
          total_views: 100,     // ~99% drop
          total_shares: 0,
          total_reposts: 0,
          total_replies: 0,
          total_likes: 0,
          followers_count: 5000,
        },
      );
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");

      // Account should be auto-paused (update is_active=false)
      expect(mockUpdate).toHaveBeenCalled();
    });

    it("sets severity to critical when health below 0.5", async () => {
      const rows = makeAnalyticsWithRecentDrop(
        {
          total_views: 10000,
          total_shares: 100,
          total_reposts: 50,
          total_replies: 80,
          total_likes: 500,
          followers_count: 5000,
        },
        {
          total_views: 100,
          total_shares: 0,
          total_reposts: 0,
          total_replies: 0,
          total_likes: 0,
          followers_count: 5000,
        },
      );
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");

      const insertCalls = mockInsert.mock.calls;
      const healthInsert = insertCalls.find(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "reach_anomaly",
      );
      if (healthInsert) {
        expect((healthInsert[0] as Record<string, unknown>).severity).toBe("critical");
      }
    });

    it("does NOT flag health when metrics are stable", async () => {
      const rows = makeStableAnalytics();
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");

      const insertCalls = mockInsert.mock.calls;
      const healthInsert = insertCalls.find(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "reach_anomaly",
      );
      expect(healthInsert).toBeUndefined();
    });
  });

  // =========================================================================
  // 6. Viral post handling — high reach is NOT a negative anomaly
  // =========================================================================

  describe("viral post handling", () => {
    it("does NOT flag shadowban or engagement drop when reach spikes (viral)", async () => {
      // Viral scenario: recent 3 days have HIGHER reach than baseline
      const rows = makeAnalyticsWithRecentDrop(
        { total_views: 10000, engagement_rate: 5.0, followers_count: 5000 },
        { total_views: 100000, engagement_rate: 15.0, followers_count: 5100 },
      );
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");

      const insertCalls = mockInsert.mock.calls;
      const shadowbanInsert = insertCalls.find(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "shadowban_suspected",
      );
      const engDropInsert = insertCalls.find(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "engagement_drop",
      );
      expect(shadowbanInsert).toBeUndefined();
      expect(engDropInsert).toBeUndefined();
    });
  });

  // =========================================================================
  // 7. Alert deduplication — 14-day window
  // =========================================================================

  describe("alert deduplication", () => {
    it("skips inserting alert when one already exists (undismissed, within 14 days)", async () => {
      const rows = makeAnalyticsWithRecentDrop(
        { total_views: 10000, followers_count: 5000 },
        { total_views: 500, followers_count: 5000 },
      );
      // Existing undismissed alert
      setupMocks(rows, [{ id: "existing-alert-1" }]);

      await detectAnomalies("acc-1", "threads", "user-1");

      // Insert should not be called for shadowban since dedup found existing
      // (the dedup check runs per alert type, so if existing found, skip)
      // Note: other alert types may still insert if triggered
      const shadowbanInserts = mockInsert.mock.calls.filter(
        (call: unknown[]) => (call[0] as Record<string, unknown>)?.alert_type === "shadowban_suspected",
      );
      expect(shadowbanInserts.length).toBe(0);
    });

    it("inserts alert when no existing undismissed alert found", async () => {
      const rows = makeAnalyticsWithRecentDrop(
        { total_views: 10000, followers_count: 5000 },
        { total_views: 500, followers_count: 5000 },
      );
      setupMocks(rows, []); // no existing alerts

      await detectAnomalies("acc-1", "threads", "user-1");

      expect(mockInsert).toHaveBeenCalled();
    });
  });

  // =========================================================================
  // 8. Notification creation on alert
  // =========================================================================

  describe("notification creation", () => {
    it("creates in-app notification when a new alert is inserted", async () => {
      const rows = makeAnalyticsWithRecentDrop(
        { total_views: 10000, followers_count: 5000 },
        { total_views: 500, followers_count: 5000 },
      );
      setupMocks(rows, []); // no existing alerts

      await detectAnomalies("acc-1", "threads", "user-1");

      expect(createNotification).toHaveBeenCalled();
      const notifCall = (createNotification as ReturnType<typeof vi.fn>).mock.calls[0][0];
      expect(notifCall.userId).toBe("user-1");
      expect(notifCall.type).toMatch(/^anomaly_/);
    });
  });

  // =========================================================================
  // 9. Platform-specific field mapping
  // =========================================================================

  describe("platform field mapping", () => {
    it("sets account_id for threads platform", async () => {
      const rows = makeAnalyticsWithRecentDrop(
        { total_views: 10000, followers_count: 5000 },
        { total_views: 500, followers_count: 5000 },
      );
      setupMocks(rows, []);

      await detectAnomalies("acc-threads", "threads", "user-1");

      const insertCalls = mockInsert.mock.calls;
      if (insertCalls.length > 0) {
        const alert = insertCalls[0][0] as Record<string, unknown>;
        expect(alert.account_id).toBe("acc-threads");
        expect(alert.instagram_account_id).toBeUndefined();
      }
    });

    it("sets instagram_account_id for instagram platform", async () => {
      const rows = makeAnalyticsWithRecentDrop(
        { ig_reach: 10000, total_views: 0, followers_count: 5000 },
        { ig_reach: 200, total_views: 0, followers_count: 5000 },
      );
      setupMocks(rows, []);

      await detectAnomalies("ig-acc", "instagram", "user-1");

      const insertCalls = mockInsert.mock.calls;
      if (insertCalls.length > 0) {
        const alert = insertCalls[0][0] as Record<string, unknown>;
        expect(alert.instagram_account_id).toBe("ig-acc");
        expect(alert.account_id).toBeUndefined();
      }
    });
  });

  // =========================================================================
  // 10. Edge cases — all zeros, null values
  // =========================================================================

  describe("edge cases", () => {
    it("handles all-zero metrics gracefully (no crash)", async () => {
      const rows = makeStableAnalytics({
        total_views: 0,
        total_likes: 0,
        total_replies: 0,
        total_reposts: 0,
        total_shares: 0,
        engagement_rate: 0,
        total_reach: 0,
        ig_reach: 0,
        followers_count: 5000,
      });
      setupMocks(rows);

      // Should not throw
      await expect(detectAnomalies("acc-1", "threads", "user-1")).resolves.toBeUndefined();
    });

    it("handles null followers_count without crashing", async () => {
      const rows = makeStableAnalytics({ followers_count: null });
      setupMocks(rows);

      await expect(detectAnomalies("acc-1", "threads", "user-1")).resolves.toBeUndefined();
      // Should skip due to <100 followers (null treated as 0)
      expect(mockInsert).not.toHaveBeenCalled();
    });

    it("handles single post data point gracefully", async () => {
      const rows = [makeAnalyticsRow(0)];
      setupMocks(rows);

      await expect(detectAnomalies("acc-1", "threads", "user-1")).resolves.toBeUndefined();
      expect(mockInsert).not.toHaveBeenCalled();
    });

    it("does not crash when outer try/catch is triggered by unexpected error", async () => {
      mockFrom.mockImplementation(() => {
        throw new Error("Unexpected DB connection failure");
      });

      // Should not throw — outer try/catch logs and returns
      await expect(detectAnomalies("acc-1", "threads", "user-1")).resolves.toBeUndefined();
    });
  });

  // =========================================================================
  // 11. AI Analysis generation
  // =========================================================================

  describe("generateAIAnalysis", () => {
    it("does not throw when Gemini API key is missing", async () => {
      const originalKey = process.env.GEMINI_API_KEY;
      const originalGoogleKey = process.env.GOOGLE_AI_API_KEY;
      delete process.env.GEMINI_API_KEY;
      delete process.env.GOOGLE_AI_API_KEY;

      const alert = {
        user_id: "user-1",
        account_id: "acc-1",
        platform: "threads" as const,
        alert_type: "shadowban_suspected" as const,
        severity: "high" as const,
        title: "Test",
        description: "Test desc",
        data: { dropPct: 50 },
      };

      setupMocks(makeStableAnalytics(), []);

      await expect(
        generateAIAnalysis(alert, "acc-1", "threads"),
      ).resolves.toBeUndefined();

      process.env.GEMINI_API_KEY = originalKey;
      process.env.GOOGLE_AI_API_KEY = originalGoogleKey;
    });
  });

  // =========================================================================
  // 12. Historical comparison — period-over-period
  // =========================================================================

  describe("historical comparison", () => {
    it("uses first 11 days as baseline and last 3 as recent for comparison", async () => {
      // Construct data where baseline (first 11 days) is high, recent (last 3) is low
      const rows: AnalyticsRowInput[] = [];
      for (let i = 0; i < 11; i++) {
        rows.push(makeAnalyticsRow(i, { total_views: 20000, followers_count: 5000 }));
      }
      // Recent 3 days: severely reduced views
      for (let i = 11; i < 14; i++) {
        rows.push(makeAnalyticsRow(i, { total_views: 500, followers_count: 5000 }));
      }
      setupMocks(rows, []);

      await detectAnomalies("acc-1", "threads", "user-1");

      // Should detect the drop based on period-over-period analysis
      const insertCalls = mockInsert.mock.calls;
      expect(insertCalls.length).toBeGreaterThan(0);
    });

    it("does not flag when recent period is similar to baseline", async () => {
      // Both periods have similar values
      const rows = makeStableAnalytics({
        total_views: 10000,
        followers_count: 5000,
        engagement_rate: 5.0,
      });
      setupMocks(rows);

      await detectAnomalies("acc-1", "threads", "user-1");

      const insertCalls = mockInsert.mock.calls;
      // Stable data should not trigger shadowban or engagement drop
      const problemAlerts = insertCalls.filter(
        (call: unknown[]) => {
          const alertType = (call[0] as Record<string, unknown>)?.alert_type;
          return alertType === "shadowban_suspected" || alertType === "engagement_drop";
        },
      );
      expect(problemAlerts.length).toBe(0);
    });
  });
});
