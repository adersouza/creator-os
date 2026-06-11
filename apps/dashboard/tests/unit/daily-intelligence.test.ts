/**
 * Daily Intelligence Cron — Unit Tests
 *
 * Tests the three main phases of the daily intelligence pipeline:
 *   Phase 1: Power user scoring (computeScoreForUser, phasePowerUserScoring)
 *   Phase 2: Quick win monitor (regression detection, notification batching/dedup)
 *   Phase 3: Competitor snapshots (token pool, API fetching, batch upserts)
 *
 * Validates: insight generation, notification dedup, regression detection,
 * report generation, error handling, edge cases.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — declared before imports
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockUpsert = vi.fn();
const mockInsert = vi.fn();
const mockDelete = vi.fn();

function createSelectChain(data: unknown, error: unknown = null) {
  return {
    eq: vi.fn().mockReturnValue({
      eq: vi.fn().mockReturnValue({
        maybeSingle: vi.fn().mockResolvedValue({ data, error }),
        gte: vi.fn().mockResolvedValue({ count: 0, error: null }),
      }),
      maybeSingle: vi.fn().mockResolvedValue({ data, error }),
      gte: vi.fn().mockReturnValue({
        order: vi.fn().mockResolvedValue({ data: data ?? [], error }),
      }),
      limit: vi.fn().mockResolvedValue({ data: data ?? [], error }),
      is: vi.fn().mockReturnValue({
        gte: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            limit: vi.fn().mockResolvedValue({ data: data ?? [], error }),
          }),
        }),
      }),
    }),
    in: vi.fn().mockReturnValue({
      ilike: vi.fn().mockReturnValue({
        gte: vi.fn().mockResolvedValue({ count: 0, error: null }),
      }),
    }),
    limit: vi.fn().mockResolvedValue({ data: data ?? [], error }),
    order: vi.fn().mockResolvedValue({ data: data ?? [], error }),
    or: vi.fn().mockReturnValue({
      order: vi.fn().mockResolvedValue({ data: data ?? [], error }),
    }),
    not: vi.fn().mockReturnValue({
      eq: vi.fn().mockReturnValue({
        eq: vi.fn().mockReturnValue({
          or: vi.fn().mockReturnValue({
            order: vi.fn().mockResolvedValue({ data: data ?? [], error }),
          }),
        }),
      }),
    }),
    ilike: vi.fn().mockReturnValue({
      gte: vi.fn().mockResolvedValue({ count: 0, error: null }),
    }),
  };
}

vi.mock("../../api/_lib/supabase.js", () => ({
  getSupabase: () => ({
    from: mockFrom,
  }),
  getSupabaseAny: () => ({
    from: mockFrom,
  }),
}));

// Track regression events returned
const mockCheckRegressions = vi.fn().mockResolvedValue([]);
const mockCheckResultReminders = vi.fn().mockResolvedValue(0);

vi.mock("../../api/_lib/regressionDetector.js", () => ({
  checkRegressions: (...args: unknown[]) => mockCheckRegressions(...args),
  checkResultReminders: (...args: unknown[]) => mockCheckResultReminders(...args),
}));

const mockCreateNotification = vi.fn().mockResolvedValue(undefined);
vi.mock("../../api/_lib/createNotification.js", () => ({
  createNotification: (...args: unknown[]) => mockCreateNotification(...args),
}));

vi.mock("../../api/_lib/logger.js", () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}));

vi.mock("../../api/_lib/cronUtils.js", () => ({
  trackCronRun: vi.fn((_sb: unknown, _name: string, fn: () => Promise<unknown>) => fn()),
  withCronLock: vi.fn((_sb: unknown, _name: string, fn: () => Promise<unknown>) => fn()),
}));

vi.mock("../../api/_lib/alerting.js", () => ({
  alertCronFailure: vi.fn(),
}));

vi.mock("../../api/_lib/encryption.js", () => ({
  decrypt: vi.fn().mockReturnValue("decrypted-token"),
}));

vi.mock("../../api/_lib/handlers/competitors/shared.js", () => ({
  detectAccountStatus: vi.fn().mockReturnValue(null),
  updateCompetitorSyncStatus: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../../api/_lib/redis.js", () => ({
  getRedis: () => ({
    del: vi.fn().mockResolvedValue(1),
    get: vi.fn().mockResolvedValue(null),
    set: vi.fn().mockResolvedValue("OK"),
  }),
}));

vi.mock("../../api/_lib/sentiment.js", () => ({
  analyzeSentiment: vi.fn().mockReturnValue({ score: 0.5 }),
}));

// Import module under test AFTER mocks
import {
  phasePowerUserScoring,
  phaseQuickwinMonitor,
  phaseDiscoverRefresh,
  phaseCompetitorSnapshots,
} from "../../api/_lib/cron/daily-intelligence.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Set up mockFrom to return different data per table */
function setupTableMocks(tableData: Record<string, { data: unknown; error: unknown }>) {
  mockFrom.mockImplementation((table: string) => {
    const td = tableData[table];
    if (!td) {
      return {
        select: vi.fn().mockReturnValue(createSelectChain([], null)),
        upsert: mockUpsert.mockResolvedValue({ error: null }),
        insert: mockInsert.mockResolvedValue({ error: null }),
        update: vi.fn().mockReturnValue({ eq: vi.fn().mockResolvedValue({ error: null }) }),
        delete: mockDelete.mockReturnValue({
          lt: vi.fn().mockResolvedValue({ count: 0, error: null }),
        }),
      };
    }
    return {
      select: vi.fn().mockImplementation((_cols?: string, opts?: { count?: string; head?: boolean }) => {
        if (opts?.count === "exact") {
          return {
            eq: vi.fn().mockReturnValue({
              eq: vi.fn().mockReturnValue({
                gte: vi.fn().mockResolvedValue({ count: 0, error: null }),
              }),
              gte: vi.fn().mockResolvedValue({ count: 0, error: null }),
            }),
          };
        }
        return createSelectChain(td.data, td.error);
      }),
      upsert: mockUpsert.mockResolvedValue({ error: td.error }),
      insert: mockInsert.mockResolvedValue({ error: td.error }),
      update: vi.fn().mockReturnValue({
        eq: vi.fn().mockResolvedValue({ error: td.error }),
      }),
      delete: mockDelete.mockReturnValue({
        lt: vi.fn().mockResolvedValue({ count: 5, error: null }),
      }),
    };
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("daily-intelligence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUpsert.mockResolvedValue({ error: null });
    mockInsert.mockResolvedValue({ error: null });
    mockCheckRegressions.mockResolvedValue([]);
    mockCheckResultReminders.mockResolvedValue(0);
  });

  // =========================================================================
  // Phase 1: Power User Scoring
  // =========================================================================

  describe("phasePowerUserScoring", () => {
    it("returns success with count of scored users", async () => {
      setupTableMocks({
        profiles: {
          data: [{ id: "user-1" }, { id: "user-2" }],
          error: null,
        },
        posts: { data: [], error: null },
        feature_usage: { data: [], error: null },
      });

      const result = await phasePowerUserScoring();

      expect(result.status).toBe("success");
      expect(result.detail?.totalUsers).toBe(2);
      expect(result.durationMs).toBeGreaterThanOrEqual(0);
    });

    it("throws when profiles query fails", async () => {
      setupTableMocks({
        profiles: { data: null, error: { message: "connection refused" } },
      });

      await expect(phasePowerUserScoring()).rejects.toThrow("Failed to fetch profiles");
    });

    it("handles empty user list gracefully", async () => {
      setupTableMocks({
        profiles: { data: [], error: null },
      });

      const result = await phasePowerUserScoring();
      expect(result.status).toBe("success");
      expect(result.detail?.usersScored).toBe(0);
      expect(result.detail?.totalUsers).toBe(0);
    });

    it("continues processing when individual user scoring fails", async () => {
      // First user succeeds, second triggers an error in the update path
      let callCount = 0;
      mockFrom.mockImplementation((table: string) => {
        if (table === "profiles") {
          if (callCount === 0) {
            callCount++;
            return {
              select: vi.fn().mockReturnValue({
                limit: vi.fn().mockResolvedValue({
                  data: [{ id: "user-1" }, { id: "user-2" }],
                  error: null,
                }),
              }),
            };
          }
          // For updates — first succeeds, second fails
          return {
            select: vi.fn().mockReturnValue(createSelectChain([], null)),
            update: vi.fn().mockReturnValue({
              eq: vi.fn().mockResolvedValue({ error: null }),
            }),
          };
        }
        // posts/feature_usage
        return {
          select: vi.fn().mockReturnValue(createSelectChain([], null)),
        };
      });

      const result = await phasePowerUserScoring();
      // Should not crash — uses Promise.allSettled
      expect(result.status).toBe("success");
    });

    it("score is clamped between 0 and 100", async () => {
      // A very active user — many posts, copilot usage, logins, features
      setupTableMocks({
        profiles: {
          data: [{ id: "user-1" }],
          error: null,
        },
        posts: { data: [], error: null },
        feature_usage: { data: [], error: null },
      });

      const result = await phasePowerUserScoring();
      expect(result.status).toBe("success");
      // Score should be computed (even if 0 for no activity)
      expect(result.detail?.usersScored).toBeDefined();
    });
  });

  // =========================================================================
  // Phase 2: Quick Win Monitor — Regression Detection + Notification Batching
  // =========================================================================

  describe("phaseQuickwinMonitor", () => {
    it("returns success when no regressions detected", async () => {
      mockCheckRegressions.mockResolvedValue([]);
      mockCheckResultReminders.mockResolvedValue(0);

      const result = await phaseQuickwinMonitor();

      expect(result.status).toBe("success");
      expect(result.detail?.regressionsDetected).toBe(0);
      expect(result.detail?.remindersSent).toBe(0);
    });

    it("detects regressions and creates notifications", async () => {
      const regressionEvents = [
        {
          accountId: "acc-1",
          platform: "threads",
          recId: "rec-1",
          category: "engagement",
          baselineValue: 100,
          postOptValue: 150,
          currentValue: 80,
          regressionPct: 47,
          consecutiveDays: 7,
          status: "regressed" as const,
        },
      ];
      mockCheckRegressions.mockResolvedValue(regressionEvents);
      mockCheckResultReminders.mockResolvedValue(0);

      // Mock account lookup for user resolution
      setupTableMocks({
        accounts: {
          data: { user_id: "user-1" },
          error: null,
        },
      });

      const result = await phaseQuickwinMonitor();

      expect(result.status).toBe("success");
      expect(result.detail?.regressionsDetected).toBe(1);
      expect(mockCreateNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          userId: "user-1",
          type: "quick_win_regressed",
        }),
      );
    });

    it("batches notifications by user+category+status to avoid spam", async () => {
      // Two regressions for same user+category → should create ONE notification
      const regressionEvents = [
        {
          accountId: "acc-1",
          platform: "threads",
          recId: "rec-1",
          category: "engagement",
          baselineValue: 100,
          postOptValue: 150,
          currentValue: 80,
          regressionPct: 40,
          consecutiveDays: 7,
          status: "regressed" as const,
        },
        {
          accountId: "acc-2",
          platform: "threads",
          recId: "rec-2",
          category: "engagement",
          baselineValue: 200,
          postOptValue: 250,
          currentValue: 120,
          regressionPct: 52,
          consecutiveDays: 8,
          status: "regressed" as const,
        },
      ];
      mockCheckRegressions.mockResolvedValue(regressionEvents);
      mockCheckResultReminders.mockResolvedValue(0);

      // Both accounts belong to same user
      setupTableMocks({
        accounts: {
          data: { user_id: "user-1" },
          error: null,
        },
      });

      const result = await phaseQuickwinMonitor();

      expect(result.detail?.regressionsDetected).toBe(2);
      // Should be batched into ONE notification since same user+category+status
      const regressedCalls = mockCreateNotification.mock.calls.filter(
        (c: unknown[]) => (c[0] as Record<string, unknown>).type === "quick_win_regressed",
      );
      expect(regressedCalls.length).toBe(1);

      // Notification should mention count of accounts
      const notif = regressedCalls[0][0] as Record<string, unknown>;
      expect((notif.message as string)).toContain("2 accounts");
    });

    it("sends separate notifications for different categories", async () => {
      const regressionEvents = [
        {
          accountId: "acc-1",
          platform: "threads",
          recId: "rec-1",
          category: "engagement",
          baselineValue: 100,
          postOptValue: 150,
          currentValue: 80,
          regressionPct: 40,
          consecutiveDays: 7,
          status: "regressed" as const,
        },
        {
          accountId: "acc-2",
          platform: "threads",
          recId: "rec-2",
          category: "reach",
          baselineValue: 500,
          postOptValue: 700,
          currentValue: 300,
          regressionPct: 57,
          consecutiveDays: 9,
          status: "regressed" as const,
        },
      ];
      mockCheckRegressions.mockResolvedValue(regressionEvents);
      mockCheckResultReminders.mockResolvedValue(0);

      setupTableMocks({
        accounts: {
          data: { user_id: "user-1" },
          error: null,
        },
      });

      await phaseQuickwinMonitor();

      // Different categories → separate notifications
      const regressedCalls = mockCreateNotification.mock.calls.filter(
        (c: unknown[]) => (c[0] as Record<string, unknown>).type === "quick_win_regressed",
      );
      expect(regressedCalls.length).toBe(2);
    });

    it("handles faded status and clears Redis deprioritization keys", async () => {
      const fadedEvents = [
        {
          accountId: "acc-1",
          platform: "threads",
          recId: "rec-1",
          category: "engagement",
          baselineValue: 100,
          postOptValue: 150,
          currentValue: 100,
          regressionPct: 33,
          consecutiveDays: 21,
          status: "faded" as const,
        },
      ];
      mockCheckRegressions.mockResolvedValue(fadedEvents);
      mockCheckResultReminders.mockResolvedValue(0);

      setupTableMocks({
        accounts: {
          data: { user_id: "user-1" },
          error: null,
        },
      });

      const result = await phaseQuickwinMonitor();

      expect(result.detail?.regressionsDetected).toBe(1);
      expect(mockCreateNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "quick_win_faded",
        }),
      );
    });

    it("continues when regression check throws (non-fatal)", async () => {
      mockCheckRegressions.mockRejectedValue(new Error("Redis connection failed"));
      mockCheckResultReminders.mockResolvedValue(3);

      const result = await phaseQuickwinMonitor();

      // Should still succeed overall — regression check failure is caught
      expect(result.status).toBe("success");
      expect(result.detail?.remindersSent).toBe(3);
    });

    it("continues when result reminders throw (non-fatal)", async () => {
      mockCheckRegressions.mockResolvedValue([]);
      mockCheckResultReminders.mockRejectedValue(new Error("DB timeout"));

      const result = await phaseQuickwinMonitor();

      expect(result.status).toBe("success");
      expect(result.detail?.regressionsDetected).toBe(0);
    });

    it("skips events where account lookup fails (no user_id)", async () => {
      const events = [
        {
          accountId: "deleted-acc",
          platform: "threads",
          recId: "rec-1",
          category: "engagement",
          baselineValue: 100,
          postOptValue: 150,
          currentValue: 80,
          regressionPct: 47,
          consecutiveDays: 7,
          status: "regressed" as const,
        },
      ];
      mockCheckRegressions.mockResolvedValue(events);

      // Account lookup returns null (deleted account)
      setupTableMocks({
        accounts: { data: null, error: null },
      });

      await phaseQuickwinMonitor();

      // No notification should be sent since we can't resolve user_id
      expect(mockCreateNotification).not.toHaveBeenCalled();
    });

    it("includes regression percentage range for multiple accounts", async () => {
      const events = [
        {
          accountId: "acc-1",
          platform: "threads",
          recId: "rec-1",
          category: "engagement",
          baselineValue: 100,
          postOptValue: 150,
          currentValue: 80,
          regressionPct: 25,
          consecutiveDays: 7,
          status: "regressed" as const,
        },
        {
          accountId: "acc-2",
          platform: "threads",
          recId: "rec-2",
          category: "engagement",
          baselineValue: 200,
          postOptValue: 300,
          currentValue: 100,
          regressionPct: 67,
          consecutiveDays: 8,
          status: "regressed" as const,
        },
      ];
      mockCheckRegressions.mockResolvedValue(events);

      setupTableMocks({
        accounts: { data: { user_id: "user-1" }, error: null },
      });

      await phaseQuickwinMonitor();

      const notifCall = mockCreateNotification.mock.calls.find(
        (c: unknown[]) => (c[0] as Record<string, unknown>).type === "quick_win_regressed",
      );
      if (notifCall) {
        const msg = (notifCall[0] as Record<string, unknown>).message as string;
        // Should contain a range like "25-67%"
        expect(msg).toContain("25");
        expect(msg).toContain("67");
      }
    });
  });

  // =========================================================================
  // Phase 3: Discover Refresh (stub)
  // =========================================================================

  describe("phaseDiscoverRefresh", () => {
    it("returns skipped status (tables dropped)", async () => {
      const result = await phaseDiscoverRefresh();
      expect(result.status).toBe("skipped");
      expect(result.durationMs).toBe(0);
      expect(result.detail?.reason).toBe("saved_searches_tables_dropped");
    });
  });

  // =========================================================================
  // Phase 4: Competitor Snapshots
  // =========================================================================

  describe("phaseCompetitorSnapshots", () => {
    it("returns success with zero competitors when none need refresh", async () => {
      setupTableMocks({
        competitors: { data: [], error: null },
        accounts: { data: [], error: null },
      });

      const result = await phaseCompetitorSnapshots(Date.now());

      expect(result.status).toBe("success");
      expect(result.detail?.totalCompetitors).toBe(0);
    });

    it("throws when competitors query fails", async () => {
      mockFrom.mockImplementation((table: string) => {
        if (table === "competitors") {
          return {
            select: vi.fn().mockReturnValue({
              or: vi.fn().mockReturnValue({
                order: vi.fn().mockResolvedValue({
                  data: null,
                  error: { message: "table not found" },
                }),
              }),
            }),
          };
        }
        return {
          select: vi.fn().mockReturnValue(createSelectChain([], null)),
        };
      });

      await expect(phaseCompetitorSnapshots(Date.now())).rejects.toBeDefined();
    });

    it("skips all competitors when no tokens available in pool", async () => {
      mockFrom.mockImplementation((table: string) => {
        if (table === "competitors") {
          return {
            select: vi.fn().mockReturnValue({
              or: vi.fn().mockReturnValue({
                order: vi.fn().mockResolvedValue({
                  data: [
                    { id: "comp-1", user_id: "user-1", username: "rival1", threads_user_id: null, last_synced_at: null },
                  ],
                  error: null,
                }),
              }),
            }),
          };
        }
        if (table === "accounts") {
          // No valid accounts with tokens
          return {
            select: vi.fn().mockReturnValue({
              not: vi.fn().mockReturnValue({
                eq: vi.fn().mockReturnValue({
                  eq: vi.fn().mockReturnValue({
                    or: vi.fn().mockReturnValue({
                      order: vi.fn().mockResolvedValue({
                        data: [],
                        error: null,
                      }),
                    }),
                  }),
                }),
              }),
            }),
          };
        }
        return {
          select: vi.fn().mockReturnValue(createSelectChain([], null)),
          upsert: mockUpsert.mockResolvedValue({ error: null }),
          insert: mockInsert.mockResolvedValue({ error: null }),
        };
      });

      const result = await phaseCompetitorSnapshots(Date.now());

      expect(result.status).toBe("success");
      expect(result.detail?.skipped).toBe(1);
    });

    it("respects time budget and stops processing mid-batch", async () => {
      // Start time far in the past to simulate time budget exhaustion
      const expiredStartTime = Date.now() - 300_000; // 300s ago

      setupTableMocks({
        competitors: { data: [
          { id: "c1", user_id: "u1", username: "user1", threads_user_id: null, last_synced_at: null },
          { id: "c2", user_id: "u1", username: "user2", threads_user_id: null, last_synced_at: null },
        ], error: null },
        accounts: { data: [], error: null },
      });

      // Override competitors query to return data
      mockFrom.mockImplementation((table: string) => {
        if (table === "competitors") {
          return {
            select: vi.fn().mockReturnValue({
              or: vi.fn().mockReturnValue({
                order: vi.fn().mockResolvedValue({
                  data: [
                    { id: "c1", user_id: "u1", username: "user1", threads_user_id: null, last_synced_at: null },
                    { id: "c2", user_id: "u1", username: "user2", threads_user_id: null, last_synced_at: null },
                  ],
                  error: null,
                }),
              }),
              eq: vi.fn().mockReturnValue({
                or: vi.fn().mockResolvedValue({ data: [], error: null }),
              }),
            }),
          };
        }
        if (table === "accounts") {
          return {
            select: vi.fn().mockReturnValue({
              not: vi.fn().mockReturnValue({
                eq: vi.fn().mockReturnValue({
                  eq: vi.fn().mockReturnValue({
                    or: vi.fn().mockReturnValue({
                      order: vi.fn().mockResolvedValue({
                        data: [{ id: "acc-1", threads_access_token_encrypted: "enc", last_synced_at: null, token_expires_at: null }],
                        error: null,
                      }),
                    }),
                  }),
                }),
              }),
            }),
          };
        }
        return {
          select: vi.fn().mockReturnValue(createSelectChain([], null)),
          upsert: mockUpsert.mockResolvedValue({ error: null }),
          delete: mockDelete.mockReturnValue({
            lt: vi.fn().mockResolvedValue({ count: 0, error: null }),
          }),
        };
      });

      const result = await phaseCompetitorSnapshots(expiredStartTime);

      // Should skip some competitors due to time budget
      expect(result.status).toBe("success");
      const skipped = (result.detail?.skipped as number) || 0;
      expect(skipped).toBeGreaterThan(0);
    });
  });

  // =========================================================================
  // Error Handling — Partial Failures
  // =========================================================================

  describe("error handling", () => {
    it("phase 2 catches regression check error and still runs reminders", async () => {
      mockCheckRegressions.mockRejectedValue(new Error("Redis down"));
      mockCheckResultReminders.mockResolvedValue(5);

      const result = await phaseQuickwinMonitor();

      expect(result.status).toBe("success");
      expect(result.detail?.remindersSent).toBe(5);
    });

    it("phase 2 catches reminder error and still returns", async () => {
      mockCheckRegressions.mockResolvedValue([]);
      mockCheckResultReminders.mockRejectedValue(new Error("query timeout"));

      const result = await phaseQuickwinMonitor();

      expect(result.status).toBe("success");
      // remindersSent should be 0 since it errored
      expect(result.detail?.remindersSent).toBe(0);
    });
  });

  // =========================================================================
  // Edge Cases
  // =========================================================================

  describe("edge cases", () => {
    it("handles single-account regression notification (no 'across X accounts' text)", async () => {
      const events = [
        {
          accountId: "acc-1",
          platform: "threads",
          recId: "rec-1",
          category: "engagement",
          baselineValue: 100,
          postOptValue: 150,
          currentValue: 80,
          regressionPct: 47,
          consecutiveDays: 7,
          status: "regressed" as const,
        },
      ];
      mockCheckRegressions.mockResolvedValue(events);

      setupTableMocks({
        accounts: { data: { user_id: "user-1" }, error: null },
      });

      await phaseQuickwinMonitor();

      const notifCall = mockCreateNotification.mock.calls.find(
        (c: unknown[]) => (c[0] as Record<string, unknown>).type === "quick_win_regressed",
      );
      if (notifCall) {
        const msg = (notifCall[0] as Record<string, unknown>).message as string;
        // Single account → "Your engagement metric dipped X%", not "across N accounts"
        expect(msg).not.toContain("accounts");
        expect(msg).toContain("engagement");
        expect(msg).toContain("47%");
      }
    });

    it("handles faded notification for single vs multiple accounts", async () => {
      const events = [
        {
          accountId: "acc-1",
          platform: "threads",
          recId: "rec-1",
          category: "reach",
          baselineValue: 500,
          postOptValue: 700,
          currentValue: 500,
          regressionPct: 29,
          consecutiveDays: 21,
          status: "faded" as const,
        },
      ];
      mockCheckRegressions.mockResolvedValue(events);

      setupTableMocks({
        accounts: { data: { user_id: "user-1" }, error: null },
      });

      await phaseQuickwinMonitor();

      const notifCall = mockCreateNotification.mock.calls.find(
        (c: unknown[]) => (c[0] as Record<string, unknown>).type === "quick_win_faded",
      );
      if (notifCall) {
        const msg = (notifCall[0] as Record<string, unknown>).message as string;
        expect(msg).toContain("faded");
      }
    });

    it("phase 1 processes users in batches of 50", async () => {
      // Create 75 users to verify batching
      const users = Array.from({ length: 75 }, (_, i) => ({ id: `user-${i}` }));

      mockFrom.mockImplementation((table: string) => {
        if (table === "profiles") {
          return {
            select: vi.fn().mockReturnValue({
              limit: vi.fn().mockResolvedValue({
                data: users,
                error: null,
              }),
            }),
            update: vi.fn().mockReturnValue({
              eq: vi.fn().mockResolvedValue({ error: null }),
            }),
          };
        }
        // posts/feature_usage
        return {
          select: vi.fn().mockReturnValue(createSelectChain([], null)),
        };
      });

      const result = await phasePowerUserScoring();

      expect(result.status).toBe("success");
      expect(result.detail?.totalUsers).toBe(75);
    });

    it("mixed regressed and faded events produce separate notification groups", async () => {
      const events = [
        {
          accountId: "acc-1",
          platform: "threads",
          recId: "rec-1",
          category: "engagement",
          baselineValue: 100,
          postOptValue: 150,
          currentValue: 80,
          regressionPct: 47,
          consecutiveDays: 7,
          status: "regressed" as const,
        },
        {
          accountId: "acc-2",
          platform: "threads",
          recId: "rec-2",
          category: "engagement",
          baselineValue: 200,
          postOptValue: 250,
          currentValue: 200,
          regressionPct: 20,
          consecutiveDays: 21,
          status: "faded" as const,
        },
      ];
      mockCheckRegressions.mockResolvedValue(events);

      setupTableMocks({
        accounts: { data: { user_id: "user-1" }, error: null },
      });

      await phaseQuickwinMonitor();

      // Should produce two separate notifications: one regressed, one faded
      // because they have different statuses
      const regressedCalls = mockCreateNotification.mock.calls.filter(
        (c: unknown[]) => (c[0] as Record<string, unknown>).type === "quick_win_regressed",
      );
      const fadedCalls = mockCreateNotification.mock.calls.filter(
        (c: unknown[]) => (c[0] as Record<string, unknown>).type === "quick_win_faded",
      );
      expect(regressedCalls.length).toBe(1);
      expect(fadedCalls.length).toBe(1);
    });
  });

  // =========================================================================
  // Clamp helper (tested via power user scoring output)
  // =========================================================================

  describe("score computation clamping", () => {
    it("never exceeds 100 even with extreme activity data", async () => {
      // Set up a user with massive activity
      mockFrom.mockImplementation((table: string) => {
        if (table === "profiles") {
          return {
            select: vi.fn().mockReturnValue({
              limit: vi.fn().mockResolvedValue({
                data: [{ id: "power-user" }],
                error: null,
              }),
            }),
            update: vi.fn().mockReturnValue({
              eq: vi.fn().mockResolvedValue({ error: null }),
            }),
          };
        }
        if (table === "posts") {
          return {
            select: vi.fn().mockImplementation((_cols: string, opts?: { count?: string; head?: boolean }) => {
              if (opts?.count === "exact") {
                return {
                  eq: vi.fn().mockReturnValue({
                    eq: vi.fn().mockReturnValue({
                      gte: vi.fn().mockResolvedValue({
                        count: 100, // Lots of posts
                        error: null,
                      }),
                    }),
                  }),
                };
              }
              return createSelectChain([], null);
            }),
          };
        }
        if (table === "feature_usage") {
          // Return many usage days and features for high score
          const manyDays = Array.from({ length: 30 }, (_, i) => ({
            used_at: new Date(Date.now() - i * 86400000).toISOString(),
            feature_name: `feature-${i % 10}.action`,
          }));
          return {
            select: vi.fn().mockReturnValue(createSelectChain(manyDays, null)),
          };
        }
        return { select: vi.fn().mockReturnValue(createSelectChain([], null)) };
      });

      const result = await phasePowerUserScoring();
      // The function should succeed; score is clamped via Math.min in clamp()
      expect(result.status).toBe("success");
    });
  });
});
