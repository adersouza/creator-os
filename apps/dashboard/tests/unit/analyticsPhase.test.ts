/**
 * Unit tests for api/_lib/sync/analyticsPhase.ts
 *
 * Tests the analytics sync phase covering:
 *   1. syncAccount() — profile + followers lightweight sync
 *   2. syncIgAccount() — Instagram account sync
 *   3. cleanupStaleAnalyticsJobs() — stale job recovery
 *   4. _processAnalyticsSyncQueue() — legacy queue processing
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Hoisted mock values (vi.mock factories are hoisted to top of file)
// ---------------------------------------------------------------------------

const {
  mockDecrypt,
  mockLogger,
  mockRedisGet,
  mockRedisRpop,
  mockRedisLlen,
  mockRedis,
  mockInvalidateDashboard,
  mockRefreshInstagramAccountAnalytics,
  mockDispatchWebhook,
  mockAlertCronFailure,
  mockPublishJSON,
  // Per-call Supabase tracking
  fromCalls,
} = vi.hoisted(() => {
  const _mockDecrypt = vi.fn((s: string) => `decrypted-${s}`);
  const _mockLogger = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  };

  const _mockRedisGet = vi.fn().mockResolvedValue(null);
  const _mockRedisSet = vi.fn().mockResolvedValue("OK");
  const _mockRedisDel = vi.fn().mockResolvedValue(1);
  const _mockRedisRpop = vi.fn().mockResolvedValue(null);
  const _mockRedisLlen = vi.fn().mockResolvedValue(0);
  const _mockRedis = {
    get: _mockRedisGet,
    set: _mockRedisSet,
    del: _mockRedisDel,
    rpop: _mockRedisRpop,
    llen: _mockRedisLlen,
    lpush: vi.fn().mockResolvedValue(1),
    expire: vi.fn().mockResolvedValue(1),
  };

  const _mockInvalidateDashboard = vi.fn().mockResolvedValue(undefined);
  const _mockRefreshInstagramAccountAnalytics = vi.fn();
  const _mockDispatchWebhook = vi.fn();
  const _mockAlertCronFailure = vi.fn();
  const _mockPublishJSON = vi.fn().mockResolvedValue({ messageId: "msg-1" });

  // Track from() calls so tests can provide per-table-per-call responses
  const _fromCalls: Array<{ table: string; chain: Record<string, any> }> = [];

  return {
    mockDecrypt: _mockDecrypt,
    mockLogger: _mockLogger,
    mockRedisGet: _mockRedisGet,
    mockRedisSet: _mockRedisSet,
    mockRedisDel: _mockRedisDel,
    mockRedisRpop: _mockRedisRpop,
    mockRedisLlen: _mockRedisLlen,
    mockRedis: _mockRedis,
    mockInvalidateDashboard: _mockInvalidateDashboard,
    mockRefreshInstagramAccountAnalytics: _mockRefreshInstagramAccountAnalytics,
    mockDispatchWebhook: _mockDispatchWebhook,
    mockAlertCronFailure: _mockAlertCronFailure,
    mockPublishJSON: _mockPublishJSON,
    fromCalls: _fromCalls,
  };
});

/**
 * Creates a fresh chainable Supabase-style object.
 * Terminal methods (maybeSingle/single) resolve with `finalValue`.
 * Non-terminal methods return the chain for further chaining.
 */
function makeChain(finalValue: unknown = { data: null, error: null }) {
  const chain: Record<string, any> = {};
  for (const m of [
    "select", "eq", "in", "not", "or", "gte", "gt", "lt", "lte",
    "limit", "order", "update", "insert", "upsert",
  ]) {
    chain[m] = vi.fn().mockReturnValue(chain);
  }
  chain.maybeSingle = vi.fn().mockResolvedValue(finalValue);
  chain.single = vi.fn().mockResolvedValue(finalValue);
  // Also make chain thenable (used when `await db.from(...).select(...)...` without terminal)
  chain.then = (resolve: (v: unknown) => unknown) => Promise.resolve(resolve(finalValue));
  return chain;
}

/** Queue of chains to return for each from() call, with per-table fallback. */
let fromQueue: Array<{ table?: string; chain: Record<string, any> }> = [];
let defaultChainFactory: () => Record<string, any>;

function resetFromQueue() {
  fromQueue = [];
  defaultChainFactory = () => makeChain();
}

const mockFrom = vi.hoisted(() => vi.fn());
const mockSupabase = vi.hoisted(() => ({ from: mockFrom }));

// Wire mockFrom to dequeue from fromQueue
mockFrom.mockImplementation((table: string) => {
  // Try to find a queued chain for this specific table
  const idx = fromQueue.findIndex((e) => e.table === table || e.table === undefined);
  if (idx >= 0) {
    const entry = fromQueue.splice(idx, 1)[0];
    fromCalls.push({ table, chain: entry.chain });
    return entry.chain;
  }
  const chain = defaultChainFactory();
  fromCalls.push({ table, chain });
  return chain;
});

vi.mock("@/api/_lib/encryption.js", () => ({
  decrypt: (s: string) => mockDecrypt(s),
}));
vi.mock("@/api/_lib/logger.js", () => ({
  logger: mockLogger,
  serializeError: (e: unknown) => (e instanceof Error ? e.message : String(e)),
}));
vi.mock("@/api/_lib/supabase.js", () => ({
  getSupabase: () => mockSupabase,
}));
vi.mock("@/api/_lib/redis.js", () => ({
  getRedis: () => mockRedis,
}));
vi.mock("@/api/_lib/dashboardCache.js", () => ({
  invalidateDashboard: (...args: unknown[]) => mockInvalidateDashboard(...args),
}));
vi.mock("@/api/_lib/analyticsSync.js", () => ({
  refreshInstagramAccountAnalytics: (...args: unknown[]) =>
    mockRefreshInstagramAccountAnalytics(...args),
}));
vi.mock("@/api/_lib/webhookDispatcher.js", () => ({
  dispatchWebhook: (...args: unknown[]) => mockDispatchWebhook(...args),
}));
vi.mock("@/api/_lib/alerting.js", () => ({
  alertCronFailure: (...args: unknown[]) => mockAlertCronFailure(...args),
}));
vi.mock("@/api/_lib/qstash.js", () => ({
  getQStashClient: () => ({ publishJSON: mockPublishJSON }),
}));
vi.mock("@/api/_lib/qstashDefaults.js", () => ({
  RETRIES: { BEST_EFFORT: 1, IMPORTANT: 2, CRITICAL: 3 },
}));
vi.mock("@/api/_lib/timing.js", () => ({
  TTL_1_HOUR: 3600,
}));
vi.mock("@/api/_lib/retryUtils.js", () => ({
  withRetry: async <T>(fn: () => Promise<T>) => fn(),
}));

// ---------------------------------------------------------------------------
// Import the module under test AFTER all mocks
// ---------------------------------------------------------------------------

import {
  syncAccount,
  syncIgAccount,
  cleanupStaleAnalyticsJobs,
  _processAnalyticsSyncQueue,
} from "@/api/_lib/sync/analyticsPhase";

import {
  setOrchestratorStartTime,
  type AccountData,
} from "@/api/_lib/sync/shared";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeAccountData(overrides: Partial<AccountData> = {}): AccountData {
  return {
    id: "acc-1",
    user_id: "user-1",
    username: "testuser",
    threads_user_id: "tu-1",
    threads_access_token_encrypted: "enc-token-1",
    status: "active",
    is_active: true,
    followers_count: 100,
    last_synced_at: new Date(Date.now() - 7 * 60 * 60 * 1000).toISOString(), // 7h ago
    ...overrides,
  };
}

function mockFetchResponse(
  body: Record<string, unknown>,
  ok = true,
  status = 200,
): Response {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
    headers: new Headers(),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response;
}

/**
 * Set up standard from() queue for a syncAccount happy path:
 *   1. accounts.select → account data
 *   2. accounts.update → success (after profile + insights fetch)
 *   3. account_analytics.select → prior followers (existing row check)
 *   4. account_analytics.upsert or update → success
 */
function setupSyncAccountFromQueue(
  account: AccountData,
  opts: {
    existingAnalyticsRow?: boolean;
    priorFollowersData?: unknown;
  } = {},
) {
  // 1. accounts.select → returns the account
  const accountsSelectChain = makeChain({ data: account, error: null });
  fromQueue.push({ table: "accounts", chain: accountsSelectChain });

  // 2. accounts.update → success (profile update)
  const accountsUpdateChain = makeChain({ data: null, error: null });
  fromQueue.push({ table: "accounts", chain: accountsUpdateChain });

  // 3. account_analytics.select for prior followers
  if (opts.priorFollowersData !== undefined) {
    const priorChain = makeChain({ data: opts.priorFollowersData, error: null });
    fromQueue.push({ table: "account_analytics", chain: priorChain });
  }

  // 4. account_analytics check for existing row
  const existingRowChain = makeChain({
    data: opts.existingAnalyticsRow ? { account_id: account.id } : null,
    error: null,
  });
  fromQueue.push({ table: "account_analytics", chain: existingRowChain });

  // 5. account_analytics upsert/update
  const analyticsWriteChain = makeChain({ data: null, error: null });
  fromQueue.push({ table: "account_analytics", chain: analyticsWriteChain });

  return { accountsSelectChain, accountsUpdateChain, existingRowChain, analyticsWriteChain };
}

// ---------------------------------------------------------------------------
// Setup / Teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  resetFromQueue();
  mockRedisGet.mockResolvedValue(null);
  setOrchestratorStartTime(Date.now());
  delete process.env.PROFILE_FRESHNESS_MINUTES;
  process.env.APP_URL = "https://juno33.com";
  fromCalls.length = 0;
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ============================================================================
// syncAccount()
// ============================================================================

describe("syncAccount", () => {
  describe("happy path", () => {
    it("syncs profile and followers successfully when no cache", async () => {
      const account = makeAccountData();
      setupSyncAccountFromQueue(account);

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({
          id: "tu-1",
          username: "testuser",
          threads_profile_picture_url: "https://pic.url",
          threads_biography: "test bio",
        }),
      );
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({
          data: [{ name: "followers_count", total_value: { value: 150 } }],
        }),
      );

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(true);
      expect(result.accountId).toBe("acc-1");
      expect(result.username).toBe("testuser");
      expect(mockInvalidateDashboard).toHaveBeenCalledWith("acc-1");

      fetchSpy.mockRestore();
    });
  });

  describe("skip conditions", () => {
    it("skips inactive accounts (status=suspended)", async () => {
      const account = makeAccountData({ status: "suspended", is_active: false });
      const chain = makeChain({ data: account, error: null });
      fromQueue.push({ table: "accounts", chain });

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(true);
      expect(result.skipped).toBe(true);
      expect(mockLogger.info).toHaveBeenCalledWith(
        "Skipping inactive Threads account",
        expect.objectContaining({ accountId: "acc-1" }),
      );
    });

    it("skips inactive accounts (is_active=false)", async () => {
      const account = makeAccountData({ is_active: false, status: "active" });
      const chain = makeChain({ data: account, error: null });
      fromQueue.push({ table: "accounts", chain });

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(true);
      expect(result.skipped).toBe(true);
    });

    it("skips freshly synced accounts (within PROFILE_FRESHNESS_MS)", async () => {
      const account = makeAccountData({
        last_synced_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
      });
      const chain = makeChain({ data: account, error: null });
      fromQueue.push({ table: "accounts", chain });

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(true);
      expect(result.skipped).toBe(true);
      expect(mockLogger.info).toHaveBeenCalledWith(
        "Skipping account (fresh)",
        expect.objectContaining({ username: "testuser" }),
      );
    });

    it("respects custom PROFILE_FRESHNESS_MINUTES env var", async () => {
      process.env.PROFILE_FRESHNESS_MINUTES = "10";
      const account = makeAccountData({
        last_synced_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
      });
      const chain = makeChain({ data: account, error: null });
      fromQueue.push({ table: "accounts", chain });

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(true);
      expect(result.skipped).toBe(true);
    });

    it("does NOT skip when account is outside PROFILE_FRESHNESS_MINUTES", async () => {
      process.env.PROFILE_FRESHNESS_MINUTES = "10";
      const account = makeAccountData({
        last_synced_at: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
      });
      setupSyncAccountFromQueue(account);

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ id: "tu-1", username: "testuser" }),
      );
      fetchSpy.mockResolvedValueOnce(mockFetchResponse({ data: [] }));

      const result = await syncAccount("acc-1", "user-1");

      expect(result.skipped).toBeUndefined();
      fetchSpy.mockRestore();
    });

    it("skips webhook-active account recently synced (within 15 min)", async () => {
      // Set a short freshness window so the account passes the freshness check
      // but still falls within the 15 min webhook-active window
      process.env.PROFILE_FRESHNESS_MINUTES = "5";
      const account = makeAccountData({
        last_synced_at: new Date(Date.now() - 10 * 60 * 1000).toISOString(), // 10 min ago
      });
      const chain = makeChain({ data: account, error: null });
      fromQueue.push({ table: "accounts", chain });

      // Redis: first call = cache miss (getCachedAccount), second = webhook-active flag
      mockRedisGet
        .mockResolvedValueOnce(null)
        .mockResolvedValueOnce("1");

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(true);
      expect(result.skipped).toBe(true);
      expect(mockLogger.info).toHaveBeenCalledWith(
        "Skipping account (webhook-active, recently synced)",
        expect.objectContaining({ username: "testuser" }),
      );
    });
  });

  describe("account not found / no credentials", () => {
    it("returns error when account not found in DB", async () => {
      const chain = makeChain({ data: null, error: null });
      fromQueue.push({ table: "accounts", chain });

      const result = await syncAccount("acc-missing", "user-1");

      expect(result.success).toBe(false);
      expect(result.error).toBe("Account not found");
    });

    it("returns error when account DB query fails", async () => {
      const chain = makeChain({ data: null, error: { message: "DB error" } });
      fromQueue.push({ table: "accounts", chain });

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(false);
      expect(result.error).toBe("Account not found");
    });

    it("returns error when cached account has wrong user_id", async () => {
      const cachedAccount = makeAccountData({ user_id: "other-user" });
      mockRedisGet.mockResolvedValueOnce(JSON.stringify(cachedAccount));

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(false);
      expect(result.error).toBe("Account not found");
    });

    it("returns error when no OAuth credentials", async () => {
      const account = makeAccountData({
        threads_access_token_encrypted: undefined,
        threads_user_id: undefined,
      });
      const chain = makeChain({ data: account, error: null });
      fromQueue.push({ table: "accounts", chain });

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(false);
      expect(result.error).toBe("No OAuth credentials");
      expect(result.username).toBe("testuser");
    });
  });

  describe("token decryption failure", () => {
    it("returns error when token cannot be decrypted", async () => {
      const account = makeAccountData();
      const chain = makeChain({ data: account, error: null });
      fromQueue.push({ table: "accounts", chain });

      mockDecrypt.mockImplementationOnce(() => {
        throw new Error("Decryption failed");
      });

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(false);
      expect(result.error).toBe("Token decryption failed");
      expect(mockLogger.warn).toHaveBeenCalledWith(
        "Token decryption failed for sync",
        expect.objectContaining({ accountId: "acc-1" }),
      );
    });
  });

  describe("API error classification", () => {
    it("handles OAuth error code 190 → needs_reauth", async () => {
      const account = makeAccountData();
      const selectChain = makeChain({ data: account, error: null });
      fromQueue.push({ table: "accounts", chain: selectChain });
      // accounts.update for needs_reauth
      const updateChain = makeChain({ data: null, error: null });
      fromQueue.push({ table: "accounts", chain: updateChain });

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse(
          { error: { code: 190, message: "Error validating access token" } },
          false,
          401,
        ),
      );

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(false);
      expect(result.needsReauth).toBe(true);
      expect(result.error).toBe("Error validating access token");
      expect(updateChain.update).toHaveBeenCalledWith(
        expect.objectContaining({
          status: "needs_reauth",
          needs_reauth: true,
          is_active: false,
        }),
      );

      fetchSpy.mockRestore();
    });

    it("handles suspended account (error code 100)", async () => {
      const account = makeAccountData();
      fromQueue.push({ table: "accounts", chain: makeChain({ data: account, error: null }) });
      const updateChain = makeChain({ data: null, error: null });
      fromQueue.push({ table: "accounts", chain: updateChain });

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse(
          { error: { code: 100, message: "Invalid parameter" } },
          false,
          400,
        ),
      );

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(false);
      expect(result.suspended).toBe(true);
      expect(updateChain.update).toHaveBeenCalledWith(
        expect.objectContaining({ status: "suspended", is_active: false }),
      );

      fetchSpy.mockRestore();
    });

    it("handles suspended account (error code 10)", async () => {
      const account = makeAccountData();
      fromQueue.push({ table: "accounts", chain: makeChain({ data: account, error: null }) });
      fromQueue.push({ table: "accounts", chain: makeChain() }); // update

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse(
          { error: { code: 10, message: "Application does not have permission" } },
          false,
          403,
        ),
      );

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(false);
      expect(result.suspended).toBe(true);

      fetchSpy.mockRestore();
    });

    it("handles suspended message in error", async () => {
      const account = makeAccountData();
      fromQueue.push({ table: "accounts", chain: makeChain({ data: account, error: null }) });
      fromQueue.push({ table: "accounts", chain: makeChain() }); // update

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse(
          { error: { message: "Account has been Suspended by platform" } },
          false,
          400,
        ),
      );

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(false);
      expect(result.suspended).toBe(true);

      fetchSpy.mockRestore();
    });

    it("handles generic profile fetch failure", async () => {
      const account = makeAccountData();
      fromQueue.push({ table: "accounts", chain: makeChain({ data: account, error: null }) });

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse(
          { error: { code: 999, message: "Unknown API error" } },
          false,
          500,
        ),
      );

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(false);
      expect(result.error).toContain("Profile fetch failed");
      expect(result.suspended).toBeUndefined();
      expect(result.needsReauth).toBeUndefined();

      fetchSpy.mockRestore();
    });
  });

  describe("follower growth delta", () => {
    it("calculates positive follower growth from pre-fetched count", async () => {
      const account = makeAccountData({ followers_count: 100 });
      const { analyticsWriteChain } = setupSyncAccountFromQueue(account);

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ id: "tu-1", username: "testuser" }),
      );
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({
          data: [{ name: "followers_count", total_value: { value: 150 } }],
        }),
      );

      const result = await syncAccount("acc-1", "user-1", 120);

      expect(result.success).toBe(true);
      // follower_growth = 150 - 120 = 30, written via upsert (no existing row)
      expect(analyticsWriteChain.upsert).toHaveBeenCalledWith(
        expect.objectContaining({
          followers_count: 150,
          follower_growth: 30,
        }),
        expect.any(Object),
      );

      fetchSpy.mockRestore();
    });

    it("updates existing analytics row without clobbering metrics", async () => {
      const account = makeAccountData();
      const { analyticsWriteChain } = setupSyncAccountFromQueue(account, {
        existingAnalyticsRow: true,
      });

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ id: "tu-1", username: "testuser" }),
      );
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({
          data: [{ name: "followers_count", total_value: { value: 200 } }],
        }),
      );

      const result = await syncAccount("acc-1", "user-1", 180);

      expect(result.success).toBe(true);
      // Should call update (not upsert) when existing row found
      expect(analyticsWriteChain.update).toHaveBeenCalledWith(
        expect.objectContaining({
          followers_count: 200,
          follower_growth: 20,
        }),
      );

      fetchSpy.mockRestore();
    });

    it("handles zero follower growth when no prior data (queries DB fallback)", async () => {
      const account = makeAccountData();
      // When priorFollowerCount is null, the code queries DB for prior followers.
      // We need: accounts.select, accounts.update, analytics(prior), analytics(existing), analytics(write)
      fromQueue.push({ table: "accounts", chain: makeChain({ data: account, error: null }) });
      fromQueue.push({ table: "accounts", chain: makeChain() }); // update

      // Prior followers DB query — returns no data (null)
      const priorChain = makeChain({ data: null, error: null });
      fromQueue.push({ table: "account_analytics", chain: priorChain });
      // Existing row check — no existing row
      fromQueue.push({ table: "account_analytics", chain: makeChain({ data: null, error: null }) });
      // Analytics write (upsert)
      const analyticsWriteChain = makeChain({ data: null, error: null });
      fromQueue.push({ table: "account_analytics", chain: analyticsWriteChain });

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ id: "tu-1", username: "testuser" }),
      );
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({
          data: [{ name: "followers_count", total_value: { value: 100 } }],
        }),
      );

      const result = await syncAccount("acc-1", "user-1", null);

      expect(result.success).toBe(true);
      expect(analyticsWriteChain.upsert).toHaveBeenCalledWith(
        expect.objectContaining({ follower_growth: 0 }),
        expect.any(Object),
      );

      fetchSpy.mockRestore();
    });
  });

  describe("follower metrics extraction", () => {
    it("extracts followers_count from total_value", async () => {
      const account = makeAccountData();
      setupSyncAccountFromQueue(account);

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ id: "tu-1", username: "testuser" }),
      );
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({
          data: [{ name: "followers_count", total_value: { value: 500 } }],
        }),
      );

      const result = await syncAccount("acc-1", "user-1");
      expect(result.success).toBe(true);

      fetchSpy.mockRestore();
    });

    it("extracts followers_count from values array when total_value missing", async () => {
      const account = makeAccountData();
      setupSyncAccountFromQueue(account);

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ id: "tu-1", username: "testuser" }),
      );
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({
          data: [
            { name: "followers_count", values: [{ value: 300 }, { value: 350 }] },
          ],
        }),
      );

      const result = await syncAccount("acc-1", "user-1");
      expect(result.success).toBe(true);

      fetchSpy.mockRestore();
    });

    it("handles follower insights fetch failure gracefully", async () => {
      const account = makeAccountData();
      // Only need accounts select + update (no analytics since no followers)
      fromQueue.push({ table: "accounts", chain: makeChain({ data: account, error: null }) });
      fromQueue.push({ table: "accounts", chain: makeChain() }); // update

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ id: "tu-1", username: "testuser" }),
      );
      fetchSpy.mockRejectedValueOnce(new Error("Network error"));

      const result = await syncAccount("acc-1", "user-1");
      expect(result.success).toBe(true);
      expect(mockLogger.warn).toHaveBeenCalledWith(
        "Failed to fetch follower metrics",
        expect.objectContaining({ accountId: "acc-1" }),
      );

      fetchSpy.mockRestore();
    });
  });

  describe("reactivation tracking", () => {
    it("suspended accounts are always skipped (reactivation is unreachable)", async () => {
      // The code at line 90 checks `account.status === "suspended" || account.is_active === false`
      // This means ANY account with status "suspended" is skipped before reaching the
      // wasReactivated check at line 275. The reactivation flag is effectively unreachable
      // for status "suspended" accounts.
      const account = makeAccountData({ status: "suspended", is_active: true });
      fromQueue.push({ table: "accounts", chain: makeChain({ data: account, error: null }) });

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(true);
      expect(result.skipped).toBe(true);
      expect(result.reactivated).toBeUndefined();
    });

    it("active account with prior non-suspended status has reactivated=undefined", async () => {
      // Only accounts with status !== "suspended" and is_active !== false proceed to sync.
      // For those, wasReactivated = (account.status === "suspended") = false,
      // so result.reactivated is set to false (falsy).
      const account = makeAccountData({ status: "active", is_active: true });
      fromQueue.push({ table: "accounts", chain: makeChain({ data: account, error: null }) });
      fromQueue.push({ table: "accounts", chain: makeChain() }); // update

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ id: "tu-1", username: "testuser" }),
      );
      fetchSpy.mockResolvedValueOnce(mockFetchResponse({ data: [] }));

      const result = await syncAccount("acc-1", "user-1");
      expect(result.success).toBe(true);
      expect(result.reactivated).toBe(false);

      fetchSpy.mockRestore();
    });
  });

  describe("dashboard cache invalidation", () => {
    it("invalidates dashboard cache after successful sync", async () => {
      const account = makeAccountData();
      fromQueue.push({ table: "accounts", chain: makeChain({ data: account, error: null }) });
      fromQueue.push({ table: "accounts", chain: makeChain() });

      const fetchSpy = vi.spyOn(globalThis, "fetch");
      fetchSpy.mockResolvedValueOnce(
        mockFetchResponse({ id: "tu-1", username: "testuser" }),
      );
      fetchSpy.mockResolvedValueOnce(mockFetchResponse({ data: [] }));

      await syncAccount("acc-1", "user-1");

      expect(mockInvalidateDashboard).toHaveBeenCalledWith("acc-1");

      fetchSpy.mockRestore();
    });
  });

  describe("error isolation", () => {
    it("catches top-level exceptions and returns error result", async () => {
      // getCachedAccount catches Redis errors internally and returns null,
      // so to trigger the outer catch we need the DB query to throw
      const chain = makeChain();
      chain.maybeSingle.mockRejectedValueOnce(new Error("DB catastrophe"));
      fromQueue.push({ table: "accounts", chain });

      const result = await syncAccount("acc-1", "user-1");

      expect(result.success).toBe(false);
      expect(result.error).toContain("DB catastrophe");
    });
  });
});

// ============================================================================
// syncIgAccount()
// ============================================================================

describe("syncIgAccount", () => {
  const igAccount = {
    id: "ig-1",
    user_id: "user-1",
    username: "iguser",
    instagram_user_id: "ig-uid-1",
    instagram_access_token_encrypted: "enc-ig-token",
    login_type: "basic",
    follower_count: 500,
    last_milestone_celebrated: null,
    last_synced_at: new Date(Date.now() - 3 * 60 * 60 * 1000).toISOString(),
    is_active: true,
  };

  describe("happy path", () => {
    it("delegates to refreshInstagramAccountAnalytics and returns result", async () => {
      fromQueue.push({
        table: "instagram_accounts",
        chain: makeChain({ data: igAccount, error: null }),
      });
      mockRedisGet.mockResolvedValue(null);
      mockRefreshInstagramAccountAnalytics.mockResolvedValueOnce({
        success: true,
        skipped: false,
      });

      const result = await syncIgAccount("ig-1", "user-1");

      expect(result.success).toBe(true);
      expect(result.username).toBe("iguser");
      expect(mockRefreshInstagramAccountAnalytics).toHaveBeenCalledWith(
        expect.objectContaining({ id: "ig-1" }),
        "metrics",
      );
      expect(mockInvalidateDashboard).toHaveBeenCalledWith("ig-1");
    });
  });

  describe("skip conditions", () => {
    it("skips inactive IG accounts (is_active=false)", async () => {
      fromQueue.push({
        table: "instagram_accounts",
        chain: makeChain({ data: { ...igAccount, is_active: false }, error: null }),
      });

      const result = await syncIgAccount("ig-1", "user-1");

      expect(result.success).toBe(true);
      expect(result.skipped).toBe(true);
      expect(mockRefreshInstagramAccountAnalytics).not.toHaveBeenCalled();
    });

    it("skips recently synced IG accounts (within 2 hours)", async () => {
      fromQueue.push({
        table: "instagram_accounts",
        chain: makeChain({
          data: {
            ...igAccount,
            last_synced_at: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
          },
          error: null,
        }),
      });

      const result = await syncIgAccount("ig-1", "user-1");

      expect(result.success).toBe(true);
      expect(result.skipped).toBe(true);
      expect(mockRefreshInstagramAccountAnalytics).not.toHaveBeenCalled();
    });
  });

  describe("account not found / no credentials", () => {
    it("returns error when IG account not found", async () => {
      fromQueue.push({
        table: "instagram_accounts",
        chain: makeChain({ data: null, error: null }),
      });

      const result = await syncIgAccount("ig-missing", "user-1");

      expect(result.success).toBe(false);
      expect(result.error).toBe("Instagram account not found");
    });

    it("returns error when IG account has no OAuth credentials", async () => {
      fromQueue.push({
        table: "instagram_accounts",
        chain: makeChain({
          data: {
            ...igAccount,
            instagram_access_token_encrypted: null,
            instagram_user_id: null,
          },
          error: null,
        }),
      });

      const result = await syncIgAccount("ig-1", "user-1");

      expect(result.success).toBe(false);
      expect(result.error).toBe("No OAuth credentials");
    });
  });

  describe("error handling", () => {
    it("catches exceptions and returns error result", async () => {
      const chain = makeChain();
      chain.maybeSingle.mockRejectedValueOnce(new Error("DB connection lost"));
      fromQueue.push({ table: "instagram_accounts", chain });

      const result = await syncIgAccount("ig-1", "user-1");

      expect(result.success).toBe(false);
      expect(result.error).toContain("DB connection lost");
    });

    it("does not invalidate dashboard when sync is skipped", async () => {
      fromQueue.push({
        table: "instagram_accounts",
        chain: makeChain({ data: igAccount, error: null }),
      });
      mockRedisGet.mockResolvedValue(null);
      mockRefreshInstagramAccountAnalytics.mockResolvedValueOnce({
        success: true,
        skipped: true,
      });

      await syncIgAccount("ig-1", "user-1");

      expect(mockInvalidateDashboard).not.toHaveBeenCalled();
    });

    it("does not invalidate dashboard when sync fails", async () => {
      fromQueue.push({
        table: "instagram_accounts",
        chain: makeChain({ data: igAccount, error: null }),
      });
      mockRedisGet.mockResolvedValue(null);
      mockRefreshInstagramAccountAnalytics.mockResolvedValueOnce({
        success: false,
        error: "API error",
      });

      await syncIgAccount("ig-1", "user-1");

      expect(mockInvalidateDashboard).not.toHaveBeenCalled();
    });
  });
});

// ============================================================================
// cleanupStaleAnalyticsJobs()
// ============================================================================

describe("cleanupStaleAnalyticsJobs", () => {
  it("recovers stale processing jobs (stuck >20 min)", async () => {
    // Processing jobs found
    const processingChain = makeChain();
    processingChain.select.mockResolvedValueOnce({
      data: [{ id: "job-1" }, { id: "job-2" }],
    });
    fromQueue.push({ table: "sync_jobs", chain: processingChain });

    // No stale queued jobs
    const queuedChain = makeChain();
    queuedChain.select.mockResolvedValueOnce({ data: [] });
    fromQueue.push({ table: "sync_jobs", chain: queuedChain });

    await cleanupStaleAnalyticsJobs();

    expect(processingChain.update).toHaveBeenCalledWith(
      expect.objectContaining({
        status: "failed",
        error_message: expect.stringContaining("stuck in processing >20min"),
      }),
    );
    expect(mockLogger.warn).toHaveBeenCalledWith(
      "[orchestrator] Recovered stale processing jobs",
      expect.objectContaining({ count: 2 }),
    );
  });

  it("recovers stale queued jobs (stuck >2 hours)", async () => {
    const processingChain = makeChain();
    processingChain.select.mockResolvedValueOnce({ data: [] });
    fromQueue.push({ table: "sync_jobs", chain: processingChain });

    const queuedChain = makeChain();
    queuedChain.select.mockResolvedValueOnce({ data: [{ id: "job-3" }] });
    fromQueue.push({ table: "sync_jobs", chain: queuedChain });

    await cleanupStaleAnalyticsJobs();

    expect(mockLogger.warn).toHaveBeenCalledWith(
      "[orchestrator] Recovered stale queued jobs",
      expect.objectContaining({ count: 1 }),
    );
  });

  it("handles DB errors gracefully for processing job recovery", async () => {
    const processingChain = makeChain();
    processingChain.select.mockRejectedValueOnce(new Error("DB timeout"));
    fromQueue.push({ table: "sync_jobs", chain: processingChain });

    const queuedChain = makeChain();
    queuedChain.select.mockResolvedValueOnce({ data: [] });
    fromQueue.push({ table: "sync_jobs", chain: queuedChain });

    await cleanupStaleAnalyticsJobs();

    expect(mockLogger.warn).toHaveBeenCalledWith(
      "[orchestrator] Stale job recovery check failed",
      expect.any(Object),
    );
  });

  it("handles DB errors gracefully for queued job recovery", async () => {
    const processingChain = makeChain();
    processingChain.select.mockResolvedValueOnce({ data: [] });
    fromQueue.push({ table: "sync_jobs", chain: processingChain });

    const queuedChain = makeChain();
    queuedChain.select.mockRejectedValueOnce(new Error("DB timeout"));
    fromQueue.push({ table: "sync_jobs", chain: queuedChain });

    await cleanupStaleAnalyticsJobs();

    expect(mockLogger.warn).toHaveBeenCalledWith(
      "[orchestrator] Stale queued job recovery failed",
      expect.any(Object),
    );
  });

  it("does nothing when no stale jobs found", async () => {
    const chain1 = makeChain();
    chain1.select.mockResolvedValueOnce({ data: [] });
    fromQueue.push({ table: "sync_jobs", chain: chain1 });

    const chain2 = makeChain();
    chain2.select.mockResolvedValueOnce({ data: null });
    fromQueue.push({ table: "sync_jobs", chain: chain2 });

    await cleanupStaleAnalyticsJobs();

    expect(mockLogger.warn).not.toHaveBeenCalledWith(
      "[orchestrator] Recovered stale processing jobs",
      expect.any(Object),
    );
  });
});

// ============================================================================
// _processAnalyticsSyncQueue() — legacy queue processing
// ============================================================================

describe("_processAnalyticsSyncQueue", () => {
  beforeEach(() => {
    // Stale job recovery needs two sync_jobs chains (processing + queued)
    const staleChain1 = makeChain();
    staleChain1.select.mockResolvedValueOnce({ data: [] });
    fromQueue.push({ table: "sync_jobs", chain: staleChain1 });
    const staleChain2 = makeChain();
    staleChain2.select.mockResolvedValueOnce({ data: [] });
    fromQueue.push({ table: "sync_jobs", chain: staleChain2 });
  });

  it("returns 0 when queue is empty", async () => {
    mockRedisLlen.mockResolvedValueOnce(0);

    const result = await _processAnalyticsSyncQueue();

    expect(result).toBe(0);
  });

  it("returns 0 when job is popped but not found in Redis", async () => {
    mockRedisLlen.mockResolvedValueOnce(1);
    mockRedisRpop.mockResolvedValueOnce("job-orphan");
    mockRedisGet.mockResolvedValueOnce(null);

    const result = await _processAnalyticsSyncQueue();

    expect(result).toBe(0);
    expect(mockLogger.warn).toHaveBeenCalledWith(
      "[orchestrator] Analytics sync job not found",
      expect.objectContaining({ jobId: "job-orphan" }),
    );
  });
});
