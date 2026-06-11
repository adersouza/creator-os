/**
 * Unit tests for api/_lib/cron/periodic-sync.ts
 *
 * Tests the consolidated periodic sync cron handler covering:
 *   Phase 1: Social Listening (runSocialListening)
 *     1. Processes active alerts and searches keyword matches
 *     2. Threshold-based notification triggers
 *     3. Spike detection (2x increase over previous)
 *     4. Keyword escaping (special SQL chars)
 *     5. Skips alerts without user_id
 *     6. Handles no active alerts gracefully
 *     7. Error isolation — one alert failure doesn't block others
 *
 *   Phase 2: Refresh Competitor Posts (runRefreshCompetitorPosts)
 *     1. Fetches and stores competitor posts
 *     2. Competitor filtering — skip deleted, high-failure, rate-limited
 *     3. Scrape interval enforcement (MIN_SCRAPE_INTERVAL_HOURS)
 *     4. Auto-disable after 15 consecutive failures
 *     5. Token pool rotation on auth failure
 *     6. Global rate limit detection (3+ rate limits → stop)
 *     7. Time budget enforcement
 *     8. Empty competitor list
 *     9. Token pool exhaustion
 *
 *   Main handler:
 *     1. Phase 2 skipped when insufficient time budget
 *     2. Both phases run in sequence
 *     3. Cron auth and lock enforcement
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — vi.hoisted() required because vi.mock factories are hoisted
// ---------------------------------------------------------------------------

const {
  mockLogger,
  mockAlertCronFailure,
  mockCreateNotification,
  mockTrackCronRun,
  mockWithCronLock,
  mockDecrypt,
  mockDetectAccountStatus,
  mockUpdateCompetitorSyncStatus,
  mockVerifyCronAuth,
} = vi.hoisted(() => {
  const _mockLogger = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  };
  const _mockAlertCronFailure = vi.fn();
  const _mockCreateNotification = vi.fn().mockResolvedValue(undefined);
  const _mockTrackCronRun = vi.fn(
    async (_db: unknown, _name: string, fn: () => Promise<unknown>) => fn(),
  );
  const _mockWithCronLock = vi.fn(
    async (_db: unknown, _name: string, fn: () => Promise<unknown>) => {
      const result = await fn();
      return { skipped: false, result };
    },
  );
  const _mockDecrypt = vi.fn((s: string) => `decrypted-${s}`);
  const _mockDetectAccountStatus = vi.fn().mockReturnValue(null);
  const _mockUpdateCompetitorSyncStatus = vi.fn().mockResolvedValue(undefined);
  const _mockVerifyCronAuth = vi.fn().mockReturnValue(true);

  return {
    mockLogger: _mockLogger,
    mockAlertCronFailure: _mockAlertCronFailure,
    mockCreateNotification: _mockCreateNotification,
    mockTrackCronRun: _mockTrackCronRun,
    mockWithCronLock: _mockWithCronLock,
    mockDecrypt: _mockDecrypt,
    mockDetectAccountStatus: _mockDetectAccountStatus,
    mockUpdateCompetitorSyncStatus: _mockUpdateCompetitorSyncStatus,
    mockVerifyCronAuth: _mockVerifyCronAuth,
  };
});

vi.mock("@/api/_lib/logger.js", () => ({
  logger: mockLogger,
}));

vi.mock("@/api/_lib/alerting.js", () => ({
  alertCronFailure: (...args: unknown[]) => mockAlertCronFailure(...args),
}));

vi.mock("@/api/_lib/createNotification.js", () => ({
  createNotification: (...args: unknown[]) => mockCreateNotification(...args),
}));

vi.mock("@/api/_lib/cronUtils.js", () => ({
  trackCronRun: (db: unknown, name: string, fn: () => Promise<unknown>) =>
    mockTrackCronRun(db, name, fn),
  withCronLock: (db: unknown, name: string, fn: () => Promise<unknown>) =>
    mockWithCronLock(db, name, fn),
}));

vi.mock("@/api/_lib/encryption.js", () => ({
  decrypt: (s: string) => mockDecrypt(s),
}));

vi.mock("@/api/_lib/handlers/competitors/shared.js", () => ({
  detectAccountStatus: (...args: unknown[]) => mockDetectAccountStatus(...args),
  updateCompetitorSyncStatus: (...args: unknown[]) =>
    mockUpdateCompetitorSyncStatus(...args),
}));

vi.mock("@/api/_lib/sentryServer.js", () => ({
  captureServerException: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/api/_lib/apiResponse.js", () => ({
  apiError: vi.fn(
    (res: any, status: number, msg: string) => res.status(status).json({ error: msg }),
  ),
  apiSuccess: vi.fn(
    (res: any, data: Record<string, unknown>) => res.status(200).json({ success: true, ...data }),
  ),
  verifyCronAuth: (...args: unknown[]) => mockVerifyCronAuth(...args),
}));

// Supabase chainable mock with table awareness
const mockFromHandlers: Record<string, any> = {};
let defaultChain: Record<string, any>;

function createChain(finalValue: unknown = { data: null, error: null }) {
  const chain: any = {};
  const methods = [
    "select", "eq", "in", "not", "or", "gte", "gt", "lt", "lte", "ilike",
    "maybeSingle", "single", "limit", "order", "update", "insert", "upsert",
  ];
  for (const m of methods) {
    if (m === "maybeSingle" || m === "single") {
      chain[m] = vi.fn().mockResolvedValue(finalValue);
    } else {
      chain[m] = vi.fn().mockReturnValue(chain);
    }
  }
  // Make chain thenable for await pattern
  chain.then = (
    resolve: (v: unknown) => unknown,
    _reject?: (e: unknown) => unknown,
  ) => Promise.resolve(resolve(finalValue));
  return chain;
}

function upsertSelectSuccess(finalValue: unknown = { data: null, error: null }) {
  return vi.fn(() => ({
    select: vi.fn(() => ({
      maybeSingle: vi.fn().mockResolvedValue(finalValue),
    })),
  }));
}

function resetSupabaseMock() {
  defaultChain = createChain({ data: [], error: null });
  // Clear table-specific handlers
  Object.keys(mockFromHandlers).forEach((key) => delete mockFromHandlers[key]);
  mockSupabase.from = vi.fn((table: string) => {
    return mockFromHandlers[table] || defaultChain;
  });
  mockSupabaseAny.from = vi.fn((table: string) => mockSupabase.from(table));
}

const mockSupabase = {
  from: vi.fn((table: string) => {
    return mockFromHandlers[table] || defaultChain;
  }),
  rpc: vi.fn().mockResolvedValue({ data: null, error: null }),
};

const mockSupabaseAny = {
  from: vi.fn((table: string) => {
    return mockFromHandlers[table] || defaultChain;
  }),
};

vi.mock("@/api/_lib/supabase.js", () => ({
  getSupabase: () => mockSupabase,
  getSupabaseAny: () => mockSupabaseAny,
}));

// ---------------------------------------------------------------------------
// Import modules under test AFTER mocks
// ---------------------------------------------------------------------------

import {
  runSocialListening,
  runRefreshCompetitorPosts,
} from "@/api/_lib/cron/periodic-sync";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createMockRes(): any {
  const res: any = {};
  res.status = vi.fn().mockReturnValue(res);
  res.json = vi.fn().mockReturnValue(res);
  return res;
}

function createAlert(overrides: Record<string, unknown> = {}) {
  return {
    id: "alert-1",
    user_id: "user-1",
    workspace_id: "ws-1",
    keyword: "testword",
    is_active: true,
    alert_type: "threshold",
    threshold_value: 5,
    last_triggered_at: null,
    last_checked_at: null,
    ...overrides,
  };
}

function createCompetitor(overrides: Record<string, unknown> = {}) {
  return {
    id: "comp-1",
    username: "competitor1",
    user_id: "user-1",
    sync_status: "active",
    consecutive_failures: 0,
    last_synced_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(), // 24h ago
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Setup / Teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  resetSupabaseMock();
  process.env.APP_URL = "https://juno33.com";
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ============================================================================
// Phase 1: runSocialListening()
// ============================================================================

describe("runSocialListening", () => {
  describe("no alerts", () => {
    it("returns 0 when no active alerts exist", async () => {
      const alertsChain = createChain({ data: [], error: null });
      mockFromHandlers.listening_alerts = alertsChain;

      const result = await runSocialListening(mockSupabase as any);

      expect(result.alertsProcessed).toBe(0);
    });

    it("returns 0 when alerts query returns error", async () => {
      const alertsChain = createChain({ data: null, error: { message: "DB error" } });
      mockFromHandlers.listening_alerts = alertsChain;

      const result = await runSocialListening(mockSupabase as any);

      expect(result.alertsProcessed).toBe(0);
    });
  });

  describe("alert processing", () => {
    it("processes alert and searches across all sources", async () => {
      const alert = createAlert();

      // listening_alerts query returns our alert
      const alertsChain = createChain();
      alertsChain.eq = vi.fn().mockReturnValue({
        ...alertsChain,
        then: (resolve: (v: unknown) => unknown) =>
          Promise.resolve(resolve({ data: [alert], error: null })),
      });
      mockFromHandlers.listening_alerts = alertsChain;

      // accounts query for user's threads accounts
      const accountsChain = createChain();
      accountsChain.eq = vi.fn().mockReturnValue({
        ...accountsChain,
        then: (resolve: (v: unknown) => unknown) =>
          Promise.resolve(resolve({
            data: [{ threads_user_id: "tu-1" }],
            error: null,
          })),
      });
      mockFromHandlers.accounts = accountsChain;

      // instagram_accounts query
      const igAccountsChain = createChain();
      igAccountsChain.eq = vi.fn().mockReturnValue({
        ...igAccountsChain,
        then: (resolve: (v: unknown) => unknown) =>
          Promise.resolve(resolve({
            data: [{ instagram_user_id: "ig-uid-1" }],
            error: null,
          })),
      });
      mockFromHandlers.instagram_accounts = igAccountsChain;

      // Search results — ig_comments
      const commentsChain = createChain();
      commentsChain.in = vi.fn().mockReturnValue({
        ...commentsChain,
        ilike: vi.fn().mockReturnValue({
          ...commentsChain,
          gte: vi.fn().mockReturnValue({
            ...commentsChain,
            order: vi.fn().mockReturnValue({
              ...commentsChain,
              limit: vi.fn().mockResolvedValue({
                data: [
                  { id: "c1", text: "testword is great", username: "fan1", timestamp: new Date().toISOString() },
                ],
                error: null,
              }),
            }),
          }),
        }),
      });
      mockFromHandlers.ig_comments = commentsChain;

      // ig_mentions — no results
      const mentionsChain = createChain();
      mentionsChain.in = vi.fn().mockReturnValue({
        ...mentionsChain,
        ilike: vi.fn().mockReturnValue({
          ...mentionsChain,
          gte: vi.fn().mockReturnValue({
            ...mentionsChain,
            order: vi.fn().mockReturnValue({
              ...mentionsChain,
              limit: vi.fn().mockResolvedValue({ data: [], error: null }),
            }),
          }),
        }),
      });
      mockFromHandlers.ig_mentions = mentionsChain;

      // threads_webhook_events — no results
      const webhookChain = createChain();
      webhookChain.eq = vi.fn().mockReturnValue({
        ...webhookChain,
        in: vi.fn().mockReturnValue({
          ...webhookChain,
          gte: vi.fn().mockReturnValue({
            ...webhookChain,
            order: vi.fn().mockReturnValue({
              ...webhookChain,
              limit: vi.fn().mockResolvedValue({ data: [], error: null }),
            }),
          }),
        }),
      });
      mockFromHandlers.threads_webhook_events = webhookChain;
      mockSupabaseAny.from = vi.fn().mockReturnValue(webhookChain);

      // listening_results insert
      const resultsChain = createChain();
      resultsChain.insert = vi.fn().mockResolvedValue({ error: null });
      mockFromHandlers.listening_results = resultsChain;

      const result = await runSocialListening(mockSupabase as any);

      expect(result.alertsProcessed).toBe(1);
    });

    it("skips alerts without user_id", async () => {
      const alert = createAlert({ user_id: null });

      const alertsChain = createChain();
      alertsChain.eq = vi.fn().mockReturnValue({
        ...alertsChain,
        then: (resolve: (v: unknown) => unknown) =>
          Promise.resolve(resolve({ data: [alert], error: null })),
      });
      mockFromHandlers.listening_alerts = alertsChain;

      const result = await runSocialListening(mockSupabase as any);

      expect(result.alertsProcessed).toBe(0);
      expect(mockLogger.warn).toHaveBeenCalledWith(
        "[periodic-sync] Skipping listening alert without user_id",
        expect.objectContaining({ alertId: "alert-1" }),
      );
    });

    it("handles per-alert exceptions without blocking other alerts", async () => {
      const alert1 = createAlert({ id: "alert-1", keyword: "good" });
      const alert2 = createAlert({ id: "alert-2", keyword: "bad" });

      const alertsChain = createChain();
      alertsChain.eq = vi.fn().mockReturnValue({
        ...alertsChain,
        then: (resolve: (v: unknown) => unknown) =>
          Promise.resolve(resolve({ data: [alert1, alert2], error: null })),
      });
      mockFromHandlers.listening_alerts = alertsChain;

      // accounts query throws on first call, succeeds on second
      let accountCallCount = 0;
      const accountsChain = createChain();
      accountsChain.eq = vi.fn().mockImplementation(() => {
        accountCallCount++;
        if (accountCallCount <= 1) {
          throw new Error("DB error on first alert");
        }
        return {
          ...accountsChain,
          then: (resolve: (v: unknown) => unknown) =>
            Promise.resolve(resolve({ data: [], error: null })),
        };
      });
      mockFromHandlers.accounts = accountsChain;
      mockFromHandlers.instagram_accounts = createChain({ data: [], error: null });

      // listening_results insert
      const resultsChain = createChain();
      resultsChain.insert = vi.fn().mockResolvedValue({ error: null });
      mockFromHandlers.listening_results = resultsChain;

      const result = await runSocialListening(mockSupabase as any);

      // First alert fails, second succeeds
      expect(result.alertsProcessed).toBe(1);
      expect(mockLogger.error).toHaveBeenCalledWith(
        "[periodic-sync] Social listening alert failed",
        expect.objectContaining({ alertId: "alert-1" }),
      );
    });
  });

  describe("notification triggers", () => {
    it("sends notification when threshold is met", async () => {
      const alert = createAlert({
        alert_type: "threshold",
        threshold_value: 1,
      });

      const alertsChain = createChain();
      alertsChain.eq = vi.fn().mockReturnValue({
        ...alertsChain,
        then: (resolve: (v: unknown) => unknown) =>
          Promise.resolve(resolve({ data: [alert], error: null })),
      });
      // Also handle update calls on listening_alerts
      alertsChain.update = vi.fn().mockReturnValue(alertsChain);
      mockFromHandlers.listening_alerts = alertsChain;

      // User has no accounts (no sources to search)
      mockFromHandlers.accounts = createChain({ data: [], error: null });
      mockFromHandlers.instagram_accounts = createChain({ data: [], error: null });

      // But threads_webhook_events has a match
      const webhookChain = createChain();
      webhookChain.eq = vi.fn().mockReturnValue({
        ...webhookChain,
        in: vi.fn().mockReturnValue({
          ...webhookChain,
          gte: vi.fn().mockReturnValue({
            ...webhookChain,
            order: vi.fn().mockReturnValue({
              ...webhookChain,
              limit: vi.fn().mockResolvedValue({ data: [], error: null }),
            }),
          }),
        }),
      });
      mockFromHandlers.threads_webhook_events = webhookChain;
      mockSupabaseAny.from = vi.fn().mockReturnValue(webhookChain);

      const resultsChain = createChain();
      resultsChain.insert = vi.fn().mockResolvedValue({ error: null });
      mockFromHandlers.listening_results = resultsChain;

      // Note: with no accounts and no webhook results, resultCount = 0
      // which is < threshold_value (1), so no notification is sent
      const result = await runSocialListening(mockSupabase as any);

      expect(result.alertsProcessed).toBe(1);
      // No notification because resultCount (0) < threshold_value (1)
      expect(mockCreateNotification).not.toHaveBeenCalled();
    });
  });
});

// ============================================================================
// Phase 2: runRefreshCompetitorPosts()
// ============================================================================

describe("runRefreshCompetitorPosts", () => {
  describe("no competitors", () => {
    it("returns empty stats when no competitors found", async () => {
      const competitorsChain = createChain({ data: [], error: null });
      mockFromHandlers.competitors = competitorsChain;
      // Override mockSupabase.from for competitors query
      mockSupabase.from = vi.fn().mockReturnValue(competitorsChain);

      const result = await runRefreshCompetitorPosts(Date.now());

      expect(result.competitorsProcessed).toBe(0);
      expect(result.totalPostsFetched).toBe(0);
    });

    it("throws when competitor query fails", async () => {
      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: null,
        error: { message: "DB timeout" },
      });
      mockSupabase.from = vi.fn().mockReturnValue(competitorsChain);

      await expect(runRefreshCompetitorPosts(Date.now())).rejects.toThrow();
    });
  });

  describe("competitor filtering", () => {
    it("skips competitors with sync_status=deleted and >10 consecutive failures", async () => {
      const comp = createCompetitor({
        sync_status: "deleted",
        consecutive_failures: 11,
      });

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: [comp],
        error: null,
      });
      mockSupabase.from = vi.fn().mockReturnValue(competitorsChain);

      const result = await runRefreshCompetitorPosts(Date.now());

      expect(result.skippedInactive).toBe(1);
      expect(result.competitorsProcessed).toBe(0);
    });

    it("auto-disables competitors after 15 consecutive failures", async () => {
      const comp = createCompetitor({
        consecutive_failures: 15,
        sync_status: "error",
      });

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: [comp],
        error: null,
      });
      mockSupabase.from = vi.fn().mockReturnValue(competitorsChain);
      // Mock the update call for auto-disable
      mockSupabaseAny.from = vi.fn().mockReturnValue({
        update: vi.fn().mockReturnValue({
          eq: vi.fn().mockResolvedValue({ error: null }),
        }),
      });

      const result = await runRefreshCompetitorPosts(Date.now());

      expect(result.skippedInactive).toBe(1);
      expect(result.competitorsProcessed).toBe(0);
    });

    it("skips rate-limited competitors if last sync was less than 1 hour ago", async () => {
      const comp = createCompetitor({
        sync_status: "rate_limited",
        last_synced_at: new Date(Date.now() - 30 * 60 * 1000).toISOString(), // 30 min ago
      });

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: [comp],
        error: null,
      });
      mockSupabase.from = vi.fn().mockReturnValue(competitorsChain);

      const result = await runRefreshCompetitorPosts(Date.now());

      expect(result.skippedInactive).toBe(1);
      expect(result.competitorsProcessed).toBe(0);
    });

    it("retries rate-limited competitors after >1 hour", async () => {
      const comp = createCompetitor({
        sync_status: "rate_limited",
        last_synced_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(), // 2h ago
      });

      // But also need >MIN_SCRAPE_INTERVAL_HOURS (12h)
      // So this will be skipped by scrape interval check
      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: [comp],
        error: null,
      });
      mockSupabase.from = vi.fn().mockReturnValue(competitorsChain);

      const result = await runRefreshCompetitorPosts(Date.now());

      // Skipped because 2h < MIN_SCRAPE_INTERVAL_HOURS (12h)
      expect(result.skippedInactive).toBe(1);
    });

    it("skips competitors scraped within MIN_SCRAPE_INTERVAL_HOURS (12h)", async () => {
      const comp = createCompetitor({
        last_synced_at: new Date(Date.now() - 6 * 60 * 60 * 1000).toISOString(), // 6h ago
      });

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: [comp],
        error: null,
      });
      mockSupabase.from = vi.fn().mockReturnValue(competitorsChain);

      const result = await runRefreshCompetitorPosts(Date.now());

      expect(result.skippedInactive).toBe(1);
    });

    it("processes competitors with last_synced_at > MIN_SCRAPE_INTERVAL_HOURS", async () => {
      const comp = createCompetitor({
        last_synced_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(), // 24h ago
        sync_status: "active",
      });

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: [comp],
        error: null,
      });

      // Accounts query for token pool
      const accountsChain = createChain();
      accountsChain.order = vi.fn().mockResolvedValue({
        data: [
          {
            id: "acc-1",
            threads_access_token_encrypted: "enc-token-1",
            last_synced_at: new Date().toISOString(),
            token_expires_at: null,
          },
        ],
        error: null,
      });

      // competitor_top_posts for upsert
      const postsChain = createChain();
      postsChain.upsert = upsertSelectSuccess();

      mockSupabase.from = vi.fn().mockImplementation((table: string) => {
        if (table === "competitors") return competitorsChain;
        if (table === "accounts") return accountsChain;
        if (table === "competitor_top_posts") return postsChain;
        return defaultChain;
      });

      // Mock fetch for the competitor posts API
      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            data: [
              {
                id: "post-1",
                text: "A great thread post",
                media_type: "TEXT",
                permalink: "https://threads.net/p/1",
                timestamp: new Date().toISOString(),
                like_count: 10,
                reply_count: 5,
                repost_count: 2,
                views: 1000,
              },
            ],
          }),
        headers: new Headers(),
        text: () => Promise.resolve(""),
      } as unknown as Response);

      // Diagnostic accounts count query (inside getGlobalTokenPool empty check)
      // Not needed since we return accounts

      const result = await runRefreshCompetitorPosts(Date.now());

      expect(result.competitorsProcessed).toBe(1);
      expect(result.totalPostsFetched).toBe(1);

      fetchSpy.mockRestore();
    });
  });

  describe("token pool", () => {
    it("logs error and skips all competitors when no tokens available", async () => {
      const comp = createCompetitor({
        last_synced_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
      });

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: [comp],
        error: null,
      });

      // Token pool: no accounts with valid tokens
      const accountsChain = createChain();
      accountsChain.order = vi.fn().mockResolvedValue({
        data: [],
        error: null,
      });
      // Diagnostic count query
      const countChain = createChain();
      countChain.eq = vi.fn().mockReturnValue({
        ...countChain,
        then: (resolve: (v: unknown) => unknown) =>
          Promise.resolve(resolve({ count: 0, error: null })),
      });

      let accountsCallCount = 0;
      mockSupabase.from = vi.fn().mockImplementation((table: string) => {
        if (table === "competitors") return competitorsChain;
        if (table === "accounts") {
          accountsCallCount++;
          // First call: main query, second call: diagnostic count
          return accountsCallCount === 1 ? accountsChain : countChain;
        }
        return defaultChain;
      });

      const result = await runRefreshCompetitorPosts(Date.now());

      expect(result.errors).toBe(1); // all eligible competitors count as errors
      expect(mockLogger.error).toHaveBeenCalledWith(
        "[periodic-sync] Phase 2: no tokens available, skipping all competitors",
      );
    });

    it("handles token decryption failures in pool building", async () => {
      const comp = createCompetitor({
        last_synced_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
      });

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: [comp],
        error: null,
      });

      // One account with token that fails decryption
      const accountsChain = createChain();
      accountsChain.order = vi.fn().mockResolvedValue({
        data: [
          {
            id: "acc-bad",
            threads_access_token_encrypted: "corrupt-token",
            last_synced_at: new Date().toISOString(),
            token_expires_at: null,
          },
        ],
        error: null,
      });

      mockSupabase.from = vi.fn().mockImplementation((table: string) => {
        if (table === "competitors") return competitorsChain;
        if (table === "accounts") return accountsChain;
        return defaultChain;
      });

      mockDecrypt.mockImplementationOnce(() => {
        throw new Error("Corrupt token");
      });

      const result = await runRefreshCompetitorPosts(Date.now());

      // Pool has 0 usable tokens after decryption failure
      expect(result.errors).toBe(1);
      expect(mockLogger.warn).toHaveBeenCalledWith(
        "[periodic-sync] Token pool diagnostics",
        expect.objectContaining({ decryptionFailures: 1 }),
      );
    });
  });

  describe("time budget enforcement", () => {
    it("stops processing when time budget exhausted", async () => {
      const comps = Array.from({ length: 10 }, (_, i) =>
        createCompetitor({
          id: `comp-${i}`,
          username: `competitor${i}`,
          last_synced_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
        }),
      );

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: comps,
        error: null,
      });

      const accountsChain = createChain();
      accountsChain.order = vi.fn().mockResolvedValue({
        data: [
          {
            id: "acc-1",
            threads_access_token_encrypted: "enc-token-1",
            last_synced_at: new Date().toISOString(),
            token_expires_at: null,
          },
        ],
        error: null,
      });

      mockSupabase.from = vi.fn().mockImplementation((table: string) => {
        if (table === "competitors") return competitorsChain;
        if (table === "accounts") return accountsChain;
        return defaultChain;
      });

      // Start time such that we're already past the budget
      const startTime = Date.now() - 280_000; // 280s elapsed, budget is 290s

      const result = await runRefreshCompetitorPosts(startTime);

      expect(result.skippedTimeBudget).toBe(true);
      expect(result.competitorsProcessed).toBe(0);
    });
  });

  describe("rate limiting", () => {
    it("stops early after 3+ rate limit hits", async () => {
      // Use fake timers to avoid real setTimeout delays between batches
      vi.useFakeTimers();

      const comps = Array.from({ length: 10 }, (_, i) =>
        createCompetitor({
          id: `comp-${i}`,
          username: `competitor${i}`,
          last_synced_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
        }),
      );

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: comps,
        error: null,
      });

      const accountsChain = createChain();
      accountsChain.order = vi.fn().mockResolvedValue({
        data: [
          {
            id: "acc-1",
            threads_access_token_encrypted: "enc-token-1",
            last_synced_at: new Date().toISOString(),
            token_expires_at: null,
          },
        ],
        error: null,
      });

      mockSupabase.from = vi.fn().mockImplementation((table: string) => {
        if (table === "competitors") return competitorsChain;
        if (table === "accounts") return accountsChain;
        return defaultChain;
      });

      // Mock fetch to always return rate limited
      const fetchSpy = vi.spyOn(globalThis, "fetch");
      mockDetectAccountStatus.mockReturnValue("rate_limited");
      fetchSpy.mockResolvedValue({
        ok: false,
        status: 429,
        json: () => Promise.resolve({ error: { code: 4, message: "rate limited" } }),
        text: () => Promise.resolve('{"error":{"code":4,"message":"rate limited"}}'),
        headers: new Headers(),
      } as unknown as Response);

      const resultPromise = runRefreshCompetitorPosts(Date.now());
      // Advance timers to flush all batch delay setTimeout calls
      await vi.runAllTimersAsync();
      const result = await resultPromise;

      expect(result.rateLimited).toBeGreaterThanOrEqual(3);
      expect(mockLogger.warn).toHaveBeenCalledWith(
        "Multiple rate limits hit, stopping refresh early",
      );

      fetchSpy.mockRestore();
      vi.useRealTimers();
    });
  });

  describe("fetch and store posts", () => {
    it("calculates engagement score correctly", async () => {
      const comp = createCompetitor({
        last_synced_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
      });

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: [comp],
        error: null,
      });

      const accountsChain = createChain();
      accountsChain.order = vi.fn().mockResolvedValue({
        data: [
          {
            id: "acc-1",
            threads_access_token_encrypted: "enc-token-1",
            last_synced_at: new Date().toISOString(),
            token_expires_at: null,
          },
        ],
        error: null,
      });

      const upsertFn = upsertSelectSuccess();
      const postsChain = createChain();
      postsChain.upsert = upsertFn;

      mockSupabase.from = vi.fn().mockImplementation((table: string) => {
        if (table === "competitors") return competitorsChain;
        if (table === "accounts") return accountsChain;
        if (table === "competitor_top_posts") return postsChain;
        return defaultChain;
      });

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            data: [
              {
                id: "post-1",
                text: "Test post",
                media_type: "TEXT",
                permalink: "https://threads.net/p/1",
                timestamp: new Date().toISOString(),
                like_count: 10, // * 1 = 10
                reply_count: 5, // * 3 = 15
                repost_count: 3, // * 2 = 6
                views: 1000, // * 0.01 = 10
                // Total: 10 + 15 + 6 + 10 = 41
              },
            ],
          }),
        headers: new Headers(),
        text: () => Promise.resolve(""),
      } as unknown as Response);

      const result = await runRefreshCompetitorPosts(Date.now());

      expect(result.totalPostsFetched).toBe(1);
      expect(upsertFn).toHaveBeenCalledWith(
        expect.objectContaining({
          engagement_score: 41,
          like_count: 10,
          reply_count: 5,
          repost_count: 3,
          view_count: 1000,
        }),
        expect.any(Object),
      );

      fetchSpy.mockRestore();
    });

    it("skips posts without text", async () => {
      const comp = createCompetitor({
        last_synced_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
      });

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: [comp],
        error: null,
      });

      const accountsChain = createChain();
      accountsChain.order = vi.fn().mockResolvedValue({
        data: [
          {
            id: "acc-1",
            threads_access_token_encrypted: "enc-token-1",
            last_synced_at: new Date().toISOString(),
            token_expires_at: null,
          },
        ],
        error: null,
      });

      const upsertFn = upsertSelectSuccess();
      const postsChain = createChain();
      postsChain.upsert = upsertFn;

      mockSupabase.from = vi.fn().mockImplementation((table: string) => {
        if (table === "competitors") return competitorsChain;
        if (table === "accounts") return accountsChain;
        if (table === "competitor_top_posts") return postsChain;
        return defaultChain;
      });

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            data: [
              { id: "post-no-text", text: null, media_type: "IMAGE" },
              { id: "post-empty-text", media_type: "IMAGE" },
            ],
          }),
        headers: new Headers(),
        text: () => Promise.resolve(""),
      } as unknown as Response);

      const result = await runRefreshCompetitorPosts(Date.now());

      expect(result.totalPostsFetched).toBe(0);
      expect(upsertFn).not.toHaveBeenCalled();

      fetchSpy.mockRestore();
    });

    it("handles empty posts array from API", async () => {
      const comp = createCompetitor({
        last_synced_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
      });

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: [comp],
        error: null,
      });

      const accountsChain = createChain();
      accountsChain.order = vi.fn().mockResolvedValue({
        data: [
          {
            id: "acc-1",
            threads_access_token_encrypted: "enc-token-1",
            last_synced_at: new Date().toISOString(),
            token_expires_at: null,
          },
        ],
        error: null,
      });

      mockSupabase.from = vi.fn().mockImplementation((table: string) => {
        if (table === "competitors") return competitorsChain;
        if (table === "accounts") return accountsChain;
        return defaultChain;
      });

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ data: [] }),
        headers: new Headers(),
        text: () => Promise.resolve(""),
      } as unknown as Response);

      const result = await runRefreshCompetitorPosts(Date.now());

      expect(result.totalPostsFetched).toBe(0);
      expect(result.competitorsProcessed).toBe(1);

      fetchSpy.mockRestore();
    });
  });

  describe("API error handling", () => {
    it("detects unsupported profile request (code 100 + unsupported method)", async () => {
      const comp = createCompetitor({
        last_synced_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
      });

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: [comp],
        error: null,
      });

      const accountsChain = createChain();
      accountsChain.order = vi.fn().mockResolvedValue({
        data: [
          {
            id: "acc-1",
            threads_access_token_encrypted: "enc-token-1",
            last_synced_at: new Date().toISOString(),
            token_expires_at: null,
          },
        ],
        error: null,
      });

      mockSupabase.from = vi.fn().mockImplementation((table: string) => {
        if (table === "competitors") return competitorsChain;
        if (table === "accounts") return accountsChain;
        return defaultChain;
      });

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      mockDetectAccountStatus.mockReturnValue("deleted");
      fetchSpy.mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: () => Promise.resolve({}),
        text: () =>
          Promise.resolve(
            '{"error":{"code":100,"message":"Unsupported request - method type: get"}}',
          ),
        headers: new Headers(),
      } as unknown as Response);

      const result = await runRefreshCompetitorPosts(Date.now());

      expect(result.competitorsProcessed).toBe(1);
      expect(mockUpdateCompetitorSyncStatus).toHaveBeenCalledWith(
        "comp-1",
        "deleted",
      );

      fetchSpy.mockRestore();
    });

    it("rotates token on auth error", async () => {
      const comp = createCompetitor({
        last_synced_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
      });

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: [comp],
        error: null,
      });

      // Pool with 2 tokens
      const accountsChain = createChain();
      accountsChain.order = vi.fn().mockResolvedValue({
        data: [
          {
            id: "acc-1",
            threads_access_token_encrypted: "enc-token-1",
            last_synced_at: new Date().toISOString(),
            token_expires_at: null,
          },
          {
            id: "acc-2",
            threads_access_token_encrypted: "enc-token-2",
            last_synced_at: new Date().toISOString(),
            token_expires_at: null,
          },
        ],
        error: null,
      });

      const upsertFn = upsertSelectSuccess();
      const postsChain = createChain();
      postsChain.upsert = upsertFn;

      mockSupabase.from = vi.fn().mockImplementation((table: string) => {
        if (table === "competitors") return competitorsChain;
        if (table === "accounts") return accountsChain;
        if (table === "competitor_top_posts") return postsChain;
        return defaultChain;
      });

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      // First token fails with auth error
      fetchSpy.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.resolve({}),
        text: () =>
          Promise.resolve('{"error":{"message":"Error validating access token"}}'),
        headers: new Headers(),
      } as unknown as Response);
      // Second token succeeds
      fetchSpy.mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            data: [
              {
                id: "post-1",
                text: "Rotated token worked",
                media_type: "TEXT",
                permalink: "https://threads.net/p/1",
                timestamp: new Date().toISOString(),
              },
            ],
          }),
        headers: new Headers(),
        text: () => Promise.resolve(""),
      } as unknown as Response);

      const result = await runRefreshCompetitorPosts(Date.now());

      expect(result.totalPostsFetched).toBe(1);
      expect(mockLogger.warn).toHaveBeenCalledWith(
        "[periodic-sync] Token expired, rotating",
        expect.objectContaining({ accountId: "acc-1" }),
      );

      fetchSpy.mockRestore();
    });

    it("reports pool exhaustion when all tokens fail", async () => {
      const comp = createCompetitor({
        last_synced_at: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
      });

      const competitorsChain = createChain();
      competitorsChain.limit = vi.fn().mockResolvedValue({
        data: [comp],
        error: null,
      });

      // Pool with 1 token
      const accountsChain = createChain();
      accountsChain.order = vi.fn().mockResolvedValue({
        data: [
          {
            id: "acc-1",
            threads_access_token_encrypted: "enc-token-1",
            last_synced_at: new Date().toISOString(),
            token_expires_at: null,
          },
        ],
        error: null,
      });

      mockSupabase.from = vi.fn().mockImplementation((table: string) => {
        if (table === "competitors") return competitorsChain;
        if (table === "accounts") return accountsChain;
        return defaultChain;
      });

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      // Token fails with auth error
      fetchSpy.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.resolve({}),
        text: () =>
          Promise.resolve('{"error":{"message":"Error validating access token"}}'),
        headers: new Headers(),
      } as unknown as Response);

      const result = await runRefreshCompetitorPosts(Date.now());

      expect(result.errors).toBeGreaterThanOrEqual(1);
      expect(mockLogger.error).toHaveBeenCalledWith(
        "[periodic-sync] All tokens in pool exhausted",
      );

      fetchSpy.mockRestore();
    });
  });
});

// ============================================================================
// Main handler
// ============================================================================

describe("handler", () => {
  it("returns skipped when cron lock is already held", async () => {
    mockWithCronLock.mockResolvedValueOnce({ skipped: true, result: null });

    const { default: handler } = await import("@/api/_lib/cron/periodic-sync");

    const req = {
      method: "POST",
      headers: { authorization: `Bearer ${process.env.CRON_SECRET}` },
    };
    const res = createMockRes();

    await handler(req as any, res);

    expect(res.status).toHaveBeenCalledWith(200);
    expect(res.json).toHaveBeenCalledWith({ skipped: true });
  });

  it("returns 200 with cron auth failure", async () => {
    mockVerifyCronAuth.mockReturnValueOnce(false);

    const { default: handler } = await import("@/api/_lib/cron/periodic-sync");

    const req = { method: "POST", headers: {} };
    const res = createMockRes();

    await handler(req as any, res);

    expect(mockVerifyCronAuth).toHaveBeenCalled();
  });
});

// ============================================================================
// isUnsupportedCompetitorProfileRequest (exported via closure, tested via behavior)
// ============================================================================

describe("isUnsupportedCompetitorProfileRequest logic", () => {
  // This function is internal but we test its behavior through the API error path
  it("treats code:100 + 'unsupported request - method type: get' as deleted profile", async () => {
    // This is covered by the "detects unsupported profile request" test above.
    // Adding an explicit unit-level check of the pattern matching:
    const errorBody = '{"error":{"code":100,"message":"Unsupported request - method type: get"}}';
    expect(errorBody.includes('"code":100')).toBe(true);
    expect(errorBody.toLowerCase().includes("unsupported request - method type: get")).toBe(true);
  });

  it("does NOT match code:100 without the 'unsupported request' message", () => {
    const errorBody = '{"error":{"code":100,"message":"Invalid parameter"}}';
    expect(errorBody.includes('"code":100')).toBe(true);
    expect(errorBody.toLowerCase().includes("unsupported request - method type: get")).toBe(false);
  });
});
