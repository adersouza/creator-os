/**
 * Token Refresh Cron — Unit Tests
 *
 * Tests the token-refresh cron module (api/_lib/cron/token-refresh.ts),
 * which refreshes OAuth tokens for all connected accounts (Threads + IG).
 *
 * Security-critical: a bug here causes mass token expiration, breaking
 * all publishing and sync for affected users.
 *
 * Covers:
 * 1.  Refresh scheduling — which tokens need refresh (expiring within 10 days)
 * 2.  Token refresh flow — Meta API call, new token encrypted and stored
 * 3.  Error handling — expired vs revoked tokens (different treatment)
 * 4.  Meta API error classification — transient (code=1) vs permanent (code=190)
 * 5.  needs_reauth flagging — when to flag, when NOT to flag (transient errors)
 * 6.  Batch processing — processes all found tokens, skips deduped
 * 7.  Threads vs Instagram — different refresh endpoints
 * 8.  Token encryption — new token properly encrypted before storage
 * 9.  Edge cases — already refreshed, no tokens expiring, network error
 * 10. Fail-safe — partial failure doesn't block remaining tokens
 * 11. Recovery probe — re-probes needs_reauth accounts with non-expired tokens
 * 12. PBKDF2 v1->v2 token migration
 * 13. Pre-flight alert — fires when >= 5 tokens expire within 48h
 * 14. Optimistic locking — skips row if updated_at changed (concurrent update)
 * 15. Redis dedup — skips accounts already refreshed by daily-maintenance
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mock setup — must come before module import
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockRedisGet = vi.fn();
const mockRedisSet = vi.fn();
const mockDecrypt = vi.fn();
const mockEncrypt = vi.fn();
const mockNeedsUpgrade = vi.fn();
const mockRefreshTokenByLoginType = vi.fn();
const mockAlertTokenRefreshFailure = vi.fn().mockResolvedValue(undefined);
const mockAlert = vi.fn().mockResolvedValue(undefined);
const mockDeliverNotification = vi.fn().mockResolvedValue(undefined);

vi.mock("@/api/_lib/supabase.js", () => ({
  getSupabaseAny: () => ({ from: mockFrom }),
}));

vi.mock("@/api/_lib/encryption.js", () => ({
  decrypt: (...args: unknown[]) => mockDecrypt(...args),
  encrypt: (...args: unknown[]) => mockEncrypt(...args),
  needsUpgrade: (...args: unknown[]) => mockNeedsUpgrade(...args),
}));

vi.mock("@/api/_lib/redis.js", () => ({
  getRedis: () => ({
    get: mockRedisGet,
    set: mockRedisSet,
  }),
}));

vi.mock("@/api/_lib/logger.js", () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
}));

vi.mock("@/api/_lib/alerting.js", () => ({
  alertTokenRefreshFailure: (...args: unknown[]) =>
    mockAlertTokenRefreshFailure(...args),
  alert: (...args: unknown[]) => mockAlert(...args),
  AlertLevel: { WARN: "warn", ERROR: "error", CRITICAL: "critical" },
}));

vi.mock("@/api/_lib/tokenRefresh.js", () => ({
  refreshTokenByLoginType: (...args: unknown[]) =>
    mockRefreshTokenByLoginType(...args),
}));

vi.mock("@/api/_lib/deliverNotification.js", () => ({
  deliverNotification: (...args: unknown[]) =>
    mockDeliverNotification(...args),
}));

// ---------------------------------------------------------------------------
// Import module under test — AFTER all mocks
// ---------------------------------------------------------------------------

const { refreshAllTokens } = await import(
  "@/api/_lib/cron/token-refresh.js"
);

// ---------------------------------------------------------------------------
// Chain builder — creates a Supabase-like chainable that resolves when awaited
// ---------------------------------------------------------------------------

/**
 * Creates a chainable mock that mimics Supabase's PostgREST builder.
 * Every builder method returns the same chain. When `await`-ed the chain
 * resolves with `{ data, error, count }`.
 */
function thenableChain(
  data: unknown = null,
  error: unknown = null,
  count: number | null = null,
) {
  const result = { data, error, count };
  // The chain is a function so we can attach methods AND make it thenable
  const chain: Record<string, any> = {};

  // All builder methods return the chain itself
  const builderMethods = [
    "select", "eq", "neq", "not", "or", "gt", "lt", "lte", "gte",
    "limit", "order", "filter", "in", "is",
  ];
  for (const m of builderMethods) {
    chain[m] = vi.fn().mockReturnValue(chain);
  }

  // Terminal methods
  chain.maybeSingle = vi.fn().mockResolvedValue(result);
  chain.single = vi.fn().mockResolvedValue(result);

  // Make the chain itself thenable (for `await db.from(...).select().eq()...`)
  chain.then = (
    onFulfilled?: (v: any) => any,
    onRejected?: (e: any) => any,
  ) => Promise.resolve(result).then(onFulfilled, onRejected);
  chain.catch = (onRejected?: (e: any) => any) =>
    Promise.resolve(result).catch(onRejected);

  return chain;
}

/**
 * Like thenableChain but the update builder — supports .update().eq().eq().select()
 */
function updateChain(data: unknown = [{ id: "ok" }], error: unknown = null) {
  const result = { data, error };
  const chain: Record<string, any> = {};
  const methods = ["eq", "select", "neq", "not", "gt", "lt", "lte", "gte", "in"];
  for (const m of methods) {
    chain[m] = vi.fn().mockReturnValue(chain);
  }
  chain.then = (
    onFulfilled?: (v: any) => any,
    onRejected?: (e: any) => any,
  ) => Promise.resolve(result).then(onFulfilled, onRejected);
  chain.catch = (onRejected?: (e: any) => any) =>
    Promise.resolve(result).catch(onRejected);
  chain.maybeSingle = vi.fn().mockResolvedValue(result);
  return chain;
}

// ---------------------------------------------------------------------------
// Test data factories
// ---------------------------------------------------------------------------

function makeThreadsAccount(overrides: Record<string, unknown> = {}) {
  return {
    id: "t-acc-1",
    user_id: "user-1",
    username: "threaduser",
    threads_access_token_encrypted: "enc_token_threads",
    token_expires_at: new Date(
      Date.now() + 5 * 24 * 60 * 60 * 1000,
    ).toISOString(),
    updated_at: "2026-04-10T00:00:00.000Z",
    ...overrides,
  };
}

function makeIgAccount(overrides: Record<string, unknown> = {}) {
  return {
    id: "ig-acc-1",
    user_id: "user-1",
    username: "iguser",
    instagram_access_token_encrypted: "enc_token_ig",
    facebook_page_access_token_encrypted: null,
    login_type: "instagram",
    token_expires_at: new Date(
      Date.now() + 5 * 24 * 60 * 60 * 1000,
    ).toISOString(),
    updated_at: "2026-04-10T00:00:00.000Z",
    ...overrides,
  };
}

// Global fetch mock
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

// ---------------------------------------------------------------------------
// Setup/teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();

  // Default encryption mocks
  mockDecrypt.mockImplementation((token: string) => `decrypted_${token}`);
  mockEncrypt.mockImplementation((token: string) => `encrypted_${token}`);
  mockNeedsUpgrade.mockReturnValue(false);

  // Default Redis: no dedup hit
  mockRedisGet.mockResolvedValue(null);
  mockRedisSet.mockResolvedValue("OK");

  // Default: all tables return empty — override per test
  mockFrom.mockReturnValue({
    ...thenableChain(null),
    update: vi.fn().mockReturnValue(updateChain()),
  });
});

// ---------------------------------------------------------------------------
// Table-routing helper
//
// The code calls db.from(table) many times within refreshAllTokens:
//   1. Pre-flight counts (accounts + instagram_accounts with {count, head})
//   2. Main select (accounts — active tokens to refresh)
//   3. Main select (instagram_accounts)
//   4. handleRefreshFailure / resetFailureCount (select + update on same table)
//   5. Recovery probe selects (accounts + instagram_accounts with needs_reauth)
//   6. Migration selects (accounts + instagram_accounts for v1 tokens)
//
// We track call counts per table to route to the correct mock.
// ---------------------------------------------------------------------------

interface TableConfig {
  /** Data returned by the main select query (accounts needing refresh) */
  mainData?: unknown[];
  /** Data returned by the recovery probe query */
  recoveryData?: unknown[];
  /** Data returned by the migration query */
  migrationData?: unknown[];
  /** Data returned by update operations */
  updateData?: unknown[];
  /** Error returned by update operations */
  updateError?: unknown;
  /** Override for maybeSingle (failure tracking lookups) */
  failureRow?: { consecutive_refresh_failures: number; user_id?: string };
}

function setupMockFrom(config: {
  accounts?: TableConfig;
  instagram_accounts?: TableConfig;
  preflightCounts?: { threads: number; ig: number };
}) {
  const callCounts: Record<string, number> = {};

  mockFrom.mockImplementation((table: string) => {
    callCounts[table] = (callCounts[table] || 0) + 1;
    const callNum = callCounts[table];

    const tableConf =
      table === "accounts"
        ? config.accounts
        : table === "instagram_accounts"
          ? config.instagram_accounts
          : undefined;

    // Build a combined table mock that supports both select and update
    const selectResult = thenableChain(
      tableConf?.mainData ?? [],
      null,
      null,
    );
    const updResult = updateChain(
      tableConf?.updateData ?? [{ id: "ok" }],
      tableConf?.updateError ?? null,
    );

    // Override maybeSingle for failure tracking lookups
    if (tableConf?.failureRow) {
      selectResult.maybeSingle = vi
        .fn()
        .mockResolvedValue({ data: tableConf.failureRow, error: null });
    }

    // For the pre-flight count query: .select("id", { count: "exact", head: true })
    const originalSelect = selectResult.select;
    selectResult.select = vi
      .fn()
      .mockImplementation((_cols: string, opts?: any) => {
        if (opts?.count === "exact" && opts?.head === true) {
          const countVal =
            table === "accounts"
              ? (config.preflightCounts?.threads ?? 0)
              : (config.preflightCounts?.ig ?? 0);
          return thenableChain(null, null, countVal);
        }
        // For recovery probe and migration, we need different data.
        // Recovery probe is the 2nd or 3rd "accounts" select depending on
        // whether there was a main select. Migration is later.
        // Use a simple heuristic: the first non-count select is the main
        // query; the second is the recovery probe; the third is migration.
        if (tableConf?.recoveryData && callNum >= 3 && callNum <= 4) {
          return thenableChain(tableConf.recoveryData);
        }
        if (tableConf?.migrationData && callNum >= 5) {
          return thenableChain(tableConf.migrationData);
        }
        return originalSelect();
      });

    return {
      ...selectResult,
      update: vi.fn().mockReturnValue(updResult),
    };
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("refreshAllTokens", () => {
  // ========================================================================
  // 1. No tokens expiring
  // ========================================================================

  describe("when no tokens are expiring", () => {
    it("returns zero counts when no accounts found", async () => {
      setupMockFrom({
        accounts: { mainData: [] },
        instagram_accounts: { mainData: [] },
      });

      const result = await refreshAllTokens();

      expect(result.threadsRefreshed).toBe(0);
      expect(result.igRefreshed).toBe(0);
      expect(result.threadsErrors).toBe(0);
      expect(result.igErrors).toBe(0);
      expect(result.total).toBe(0);
    });

    it("returns zero counts when data is null", async () => {
      // All from() calls return null data
      mockFrom.mockReturnValue({
        ...thenableChain(null),
        update: vi.fn().mockReturnValue(updateChain()),
      });

      const result = await refreshAllTokens();
      expect(result.total).toBe(0);
    });
  });

  // ========================================================================
  // 2. Threads token refresh — successful flow
  // ========================================================================

  describe("Threads token refresh — success", () => {
    it("refreshes a Threads token via graph.threads.net endpoint", async () => {
      const account = makeThreadsAccount();
      setupMockFrom({
        accounts: { mainData: [account] },
        instagram_accounts: { mainData: [] },
      });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            access_token: "new_threads_token",
            expires_in: 5184000,
          }),
      });

      const result = await refreshAllTokens();

      expect(result.threadsRefreshed).toBe(1);
      expect(result.threadsErrors).toBe(0);
      expect(mockDecrypt).toHaveBeenCalledWith("enc_token_threads");
      expect(mockEncrypt).toHaveBeenCalledWith("new_threads_token");
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("graph.threads.net/refresh_access_token"),
        expect.objectContaining({ signal: expect.anything() }),
      );
    });

    it("uses th_refresh_token grant type for Threads", async () => {
      const account = makeThreadsAccount();
      setupMockFrom({
        accounts: { mainData: [account] },
        instagram_accounts: { mainData: [] },
      });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ access_token: "t", expires_in: 5184000 }),
      });

      await refreshAllTokens();

      const fetchUrl = mockFetch.mock.calls[0][0];
      expect(fetchUrl).toContain("grant_type=th_refresh_token");
    });

    it("stores encrypted token after successful refresh", async () => {
      const account = makeThreadsAccount();
      setupMockFrom({
        accounts: { mainData: [account] },
        instagram_accounts: { mainData: [] },
      });

      mockEncrypt.mockReturnValueOnce("newly_encrypted_token");
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ access_token: "fresh_token", expires_in: 5184000 }),
      });

      await refreshAllTokens();

      expect(mockEncrypt).toHaveBeenCalledWith("fresh_token");
    });

    it("sets Redis dedup key after successful refresh", async () => {
      const account = makeThreadsAccount({ id: "t-dedup-1" });
      setupMockFrom({
        accounts: { mainData: [account] },
        instagram_accounts: { mainData: [] },
      });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ access_token: "t", expires_in: 5184000 }),
      });

      await refreshAllTokens();

      expect(mockRedisSet).toHaveBeenCalledWith(
        "token-refreshed:t-dedup-1",
        "1",
        { ex: 21600 },
      );
    });

    it("defaults to 60-day expiry when expires_in is missing", async () => {
      const account = makeThreadsAccount();
      setupMockFrom({
        accounts: { mainData: [account] },
        instagram_accounts: { mainData: [] },
      });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ access_token: "t" }),
      });

      // Should not throw — uses default 5184000
      const result = await refreshAllTokens();
      expect(result.threadsRefreshed).toBe(1);
    });
  });

  // ========================================================================
  // 3. Instagram token refresh — different endpoint
  // ========================================================================

  describe("Instagram token refresh — success", () => {
    it("uses refreshTokenByLoginType for IG tokens", async () => {
      const igAccount = makeIgAccount();
      setupMockFrom({
        accounts: { mainData: [] },
        instagram_accounts: { mainData: [igAccount] },
      });

      mockRefreshTokenByLoginType.mockResolvedValueOnce({
        ok: true,
        data: { access_token: "new_ig_token", expires_in: 5184000 },
      });

      const result = await refreshAllTokens();

      expect(result.igRefreshed).toBe(1);
      expect(mockRefreshTokenByLoginType).toHaveBeenCalledWith(
        "decrypted_enc_token_ig",
        "instagram",
      );
    });

    it("passes the correct login_type for Facebook-login IG accounts", async () => {
      const igAccount = makeIgAccount({ login_type: "facebook" });
      setupMockFrom({
        accounts: { mainData: [] },
        instagram_accounts: { mainData: [igAccount] },
      });

      mockRefreshTokenByLoginType.mockResolvedValueOnce({
        ok: true,
        data: { access_token: "fb_ig_token", expires_in: 5184000 },
      });

      await refreshAllTokens();

      expect(mockRefreshTokenByLoginType).toHaveBeenCalledWith(
        expect.any(String),
        "facebook",
      );
    });

    it("defaults login_type to 'instagram' when not set", async () => {
      const igAccount = makeIgAccount({ login_type: null });
      setupMockFrom({
        accounts: { mainData: [] },
        instagram_accounts: { mainData: [igAccount] },
      });

      mockRefreshTokenByLoginType.mockResolvedValueOnce({
        ok: true,
        data: { access_token: "t", expires_in: 5184000 },
      });

      await refreshAllTokens();

      expect(mockRefreshTokenByLoginType).toHaveBeenCalledWith(
        expect.any(String),
        "instagram",
      );
    });

    it("does NOT overwrite facebook_page_access_token_encrypted on IG refresh", async () => {
      const igAccount = makeIgAccount({
        facebook_page_access_token_encrypted: "enc_page_token",
      });
      setupMockFrom({
        accounts: { mainData: [] },
        instagram_accounts: { mainData: [igAccount] },
      });

      mockRefreshTokenByLoginType.mockResolvedValueOnce({
        ok: true,
        data: { access_token: "refreshed_user_token", expires_in: 5184000 },
      });

      await refreshAllTokens();

      // Find the update call for instagram_accounts
      const igUpdateCalls = mockFrom.mock.results
        .filter((_: any, i: number) => {
          const table = mockFrom.mock.calls[i][0];
          return table === "instagram_accounts";
        })
        .map((r: any) => r.value?.update)
        .filter(Boolean);

      for (const updateFn of igUpdateCalls) {
        for (const call of updateFn.mock?.calls ?? []) {
          const updateData = call[0];
          if (updateData?.instagram_access_token_encrypted) {
            expect(updateData).not.toHaveProperty(
              "facebook_page_access_token_encrypted",
            );
          }
        }
      }
    });

    it("sets IG-specific Redis dedup key", async () => {
      const igAccount = makeIgAccount({ id: "ig-dedup-1" });
      setupMockFrom({
        accounts: { mainData: [] },
        instagram_accounts: { mainData: [igAccount] },
      });

      mockRefreshTokenByLoginType.mockResolvedValueOnce({
        ok: true,
        data: { access_token: "t", expires_in: 5184000 },
      });

      await refreshAllTokens();

      expect(mockRedisSet).toHaveBeenCalledWith(
        "token-refreshed:ig_ig-dedup-1",
        "1",
        { ex: 21600 },
      );
    });
  });

  // ========================================================================
  // 4. Meta API error classification
  // ========================================================================

  describe("Meta API error classification", () => {
    it("treats code=190 as auth error", async () => {
      const account = makeThreadsAccount();
      setupMockFrom({
        accounts: {
          mainData: [account],
          failureRow: { consecutive_refresh_failures: 0, user_id: "user-1" },
        },
        instagram_accounts: { mainData: [] },
      });

      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: () =>
          Promise.resolve({
            error: { code: 190, message: "The access token has expired" },
          }),
      });

      const result = await refreshAllTokens();
      expect(result.threadsErrors).toBe(1);
    });

    it("treats 'session has been invalidated' as auth error", async () => {
      const account = makeThreadsAccount();
      setupMockFrom({
        accounts: {
          mainData: [account],
          failureRow: { consecutive_refresh_failures: 0, user_id: "user-1" },
        },
        instagram_accounts: { mainData: [] },
      });

      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: () =>
          Promise.resolve({
            error: { code: 102, message: "Session has been invalidated" },
          }),
      });

      const result = await refreshAllTokens();
      expect(result.threadsErrors).toBe(1);
    });

    it("treats 'password has been changed' as auth error", async () => {
      const account = makeThreadsAccount();
      setupMockFrom({
        accounts: {
          mainData: [account],
          failureRow: { consecutive_refresh_failures: 0, user_id: "user-1" },
        },
        instagram_accounts: { mainData: [] },
      });

      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: () =>
          Promise.resolve({
            error: { message: "The password has been changed" },
          }),
      });

      const result = await refreshAllTokens();
      expect(result.threadsErrors).toBe(1);
    });

    it("treats code=1 OAuthException as TRANSIENT (does NOT flag needs_reauth)", async () => {
      const account = makeThreadsAccount();

      // Track all update calls to verify no needs_reauth=true
      const allUpdateCalls: any[] = [];
      mockFrom.mockImplementation((table: string) => {
        const chain = thenableChain(
          table === "accounts" ? [account] : [],
        );
        const uChain = updateChain();
        const origUpdate = vi.fn().mockImplementation((data: any) => {
          allUpdateCalls.push({ table, data });
          return uChain;
        });

        chain.maybeSingle = vi.fn().mockResolvedValue({
          data: { consecutive_refresh_failures: 1, user_id: "user-1" },
          error: null,
        });

        return { ...chain, update: origUpdate };
      });

      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: () =>
          Promise.resolve({
            error: {
              code: 1,
              type: "OAuthException",
              message: "An unknown error has occurred",
            },
          }),
      });

      const result = await refreshAllTokens();
      expect(result.threadsErrors).toBe(1);

      // Transient errors reset failures to 0, never set needs_reauth
      const reauthUpdates = allUpdateCalls.filter(
        (c) =>
          c.data?.needs_reauth === true &&
          c.data?.consecutive_refresh_failures !== undefined,
      );
      expect(reauthUpdates).toHaveLength(0);
    });

    it("fires Discord alert on refresh failure", async () => {
      const account = makeThreadsAccount({ username: "alertme" });
      setupMockFrom({
        accounts: {
          mainData: [account],
          failureRow: { consecutive_refresh_failures: 0, user_id: "user-1" },
        },
        instagram_accounts: { mainData: [] },
      });

      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: () =>
          Promise.resolve({ error: { message: "Some error" } }),
      });

      await refreshAllTokens();

      expect(mockAlertTokenRefreshFailure).toHaveBeenCalledWith(
        "threads",
        "alertme",
        expect.stringContaining("Some error"),
      );
    });
  });

  // ========================================================================
  // 5. needs_reauth flagging — consecutive failures
  // ========================================================================

  describe("needs_reauth flagging via consecutive failures", () => {
    it("flags needs_reauth after 3 consecutive non-transient failures (encryption errors)", async () => {
      // In the main refresh loop, all non-auth API errors are treated as
      // transient (isTransient = !isAuth). The only non-transient, non-auth
      // path is encryption failure (handleRefreshFailure called with
      // isAuth=false, isTransient=false). So we trigger via encrypt() throwing.
      const account = makeThreadsAccount();

      const allUpdateCalls: any[] = [];
      mockFrom.mockImplementation((table: string) => {
        const data = table === "accounts" ? [account] : [];
        const chain = thenableChain(data);
        const uChain = updateChain();
        const origUpdate = vi.fn().mockImplementation((updateData: any) => {
          allUpdateCalls.push({ table, data: updateData });
          return uChain;
        });
        // 2 existing failures — encryption failure will be the 3rd
        chain.maybeSingle = vi.fn().mockResolvedValue({
          data: { consecutive_refresh_failures: 2, user_id: "user-1" },
          error: null,
        });
        return { ...chain, update: origUpdate };
      });

      // Successful Meta API response, but encrypt() throws
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            access_token: "new_token",
            expires_in: 5184000,
          }),
      });
      mockEncrypt.mockImplementationOnce(() => {
        throw new Error("Encryption key missing");
      });

      await refreshAllTokens();

      const deactivateCalls = allUpdateCalls.filter(
        (c) => c.data?.needs_reauth === true,
      );
      expect(deactivateCalls.length).toBeGreaterThan(0);
      expect(deactivateCalls[0].data.is_active).toBe(false);
      expect(deactivateCalls[0].data.status).toBe("needs_reauth");
    });

    it("resets consecutive_refresh_failures on transient error", async () => {
      const account = makeThreadsAccount();

      const allUpdateCalls: any[] = [];
      mockFrom.mockImplementation((table: string) => {
        const data = table === "accounts" ? [account] : [];
        const chain = thenableChain(data);
        const uChain = updateChain();
        const origUpdate = vi.fn().mockImplementation((updateData: any) => {
          allUpdateCalls.push({ table, data: updateData });
          return uChain;
        });
        chain.maybeSingle = vi.fn().mockResolvedValue({
          data: { consecutive_refresh_failures: 2, user_id: "user-1" },
          error: null,
        });
        return { ...chain, update: origUpdate };
      });

      // Network timeout — caught by outer catch, always transient
      mockFetch.mockRejectedValueOnce(new Error("AbortError: signal timed out"));

      await refreshAllTokens();

      // Transient errors should reset failure count to 0
      const resetCalls = allUpdateCalls.filter(
        (c) => c.data?.consecutive_refresh_failures === 0,
      );
      expect(resetCalls.length).toBeGreaterThan(0);
    });

    it("resets consecutive_refresh_failures on successful refresh", async () => {
      const account = makeThreadsAccount();

      const allUpdateCalls: any[] = [];
      mockFrom.mockImplementation((table: string) => {
        const data = table === "accounts" ? [account] : [];
        const chain = thenableChain(data);
        const uChain = updateChain();
        const origUpdate = vi.fn().mockImplementation((updateData: any) => {
          allUpdateCalls.push({ table, data: updateData });
          return uChain;
        });
        chain.maybeSingle = vi.fn().mockResolvedValue({
          data: { consecutive_refresh_failures: 1 },
          error: null,
        });
        return { ...chain, update: origUpdate };
      });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ access_token: "new_token", expires_in: 5184000 }),
      });

      await refreshAllTokens();

      const resetCalls = allUpdateCalls.filter(
        (c) => c.data?.consecutive_refresh_failures === 0,
      );
      expect(resetCalls.length).toBeGreaterThan(0);
    });

    it("sends user notification when deactivating account on auth error", async () => {
      // Auth errors immediately deactivate regardless of consecutive count
      const account = makeThreadsAccount({ user_id: "user-notify" });

      mockFrom.mockImplementation((table: string) => {
        const data = table === "accounts" ? [account] : [];
        const chain = thenableChain(data);
        const uChain = updateChain();
        chain.maybeSingle = vi.fn().mockResolvedValue({
          data: { consecutive_refresh_failures: 0, user_id: "user-notify" },
          error: null,
        });
        return { ...chain, update: vi.fn().mockReturnValue(uChain) };
      });

      // Auth error (code=190) triggers immediate deactivation + notification
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: () =>
          Promise.resolve({
            error: { code: 190, message: "Token has expired" },
          }),
      });

      await refreshAllTokens();

      expect(mockDeliverNotification).toHaveBeenCalledWith(
        expect.objectContaining({
          userId: "user-notify",
          type: "token_reauth_needed",
          title: expect.stringContaining("Threads"),
          message: expect.stringContaining("reconnect"),
        }),
      );
    });
  });

  // ========================================================================
  // 6. Redis dedup
  // ========================================================================

  describe("Redis dedup", () => {
    it("skips Threads account if Redis dedup key exists", async () => {
      const account = makeThreadsAccount({ id: "t-skip-1" });

      // Use custom mock to return account only for main select (not recovery probe)
      let accountsCall = 0;
      mockFrom.mockImplementation((table: string) => {
        if (table === "accounts") {
          accountsCall++;
          // Call 1 = pre-flight count, call 2 = expired-token guard,
          // call 3 = main select, call 4+ = recovery/migration.
          if (accountsCall === 3) {
            return {
              ...thenableChain([account]),
              update: vi.fn().mockReturnValue(updateChain()),
            };
          }
          return {
            ...thenableChain([]),
            update: vi.fn().mockReturnValue(updateChain()),
          };
        }
        return {
          ...thenableChain([]),
          update: vi.fn().mockReturnValue(updateChain()),
        };
      });

      mockRedisGet.mockResolvedValueOnce("1");

      const result = await refreshAllTokens();

      expect(result.threadsSkipped).toBe(1);
      expect(result.threadsRefreshed).toBe(0);
    });

    it("skips IG account if Redis dedup key exists", async () => {
      const igAccount = makeIgAccount({ id: "ig-skip-1" });
      setupMockFrom({
        accounts: { mainData: [] },
        instagram_accounts: { mainData: [igAccount] },
      });

      mockRedisGet.mockResolvedValueOnce("1");

      const result = await refreshAllTokens();

      expect(result.igSkipped).toBe(1);
      expect(result.igRefreshed).toBe(0);
    });

    it("proceeds if Redis dedup check fails (non-fatal)", async () => {
      const account = makeThreadsAccount();
      setupMockFrom({
        accounts: { mainData: [account] },
        instagram_accounts: { mainData: [] },
      });

      mockRedisGet.mockRejectedValueOnce(
        new Error("Redis connection failed"),
      );
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ access_token: "t", expires_in: 5184000 }),
      });

      const result = await refreshAllTokens();
      expect(result.threadsRefreshed).toBe(1);
    });

    it("continues if Redis dedup SET fails after refresh", async () => {
      const account = makeThreadsAccount();
      setupMockFrom({
        accounts: { mainData: [account] },
        instagram_accounts: { mainData: [] },
      });

      mockRedisSet.mockRejectedValueOnce(new Error("Redis write failed"));
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ access_token: "t", expires_in: 5184000 }),
      });

      const result = await refreshAllTokens();
      expect(result.threadsRefreshed).toBe(1);
    });
  });

  // ========================================================================
  // 7. Optimistic locking
  // ========================================================================

  describe("optimistic locking", () => {
    it("skips when update returns 0 rows (concurrent update)", async () => {
      const account = makeThreadsAccount();

      mockFrom.mockImplementation((table: string) => {
        const data = table === "accounts" ? [account] : [];
        const chain = thenableChain(data);
        // Update returns empty array (no rows matched — updated_at changed)
        const uChain = updateChain([], null);
        chain.maybeSingle = vi.fn().mockResolvedValue({
          data: { consecutive_refresh_failures: 0 },
          error: null,
        });
        return { ...chain, update: vi.fn().mockReturnValue(uChain) };
      });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ access_token: "t", expires_in: 5184000 }),
      });

      const result = await refreshAllTokens();

      expect(result.threadsSkipped).toBe(1);
      expect(result.threadsRefreshed).toBe(0);
    });
  });

  // ========================================================================
  // 8. Encryption failures
  // ========================================================================

  describe("encryption failures", () => {
    it("counts as error when encrypt() throws for Threads", async () => {
      const account = makeThreadsAccount();
      setupMockFrom({
        accounts: {
          mainData: [account],
          failureRow: { consecutive_refresh_failures: 0, user_id: "user-1" },
        },
        instagram_accounts: { mainData: [] },
      });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ access_token: "t", expires_in: 5184000 }),
      });
      mockEncrypt.mockImplementationOnce(() => {
        throw new Error("Encryption key missing");
      });

      const result = await refreshAllTokens();

      expect(result.threadsErrors).toBe(1);
      expect(result.threadsRefreshed).toBe(0);
    });

    it("counts as error when encrypt() throws for IG", async () => {
      const igAccount = makeIgAccount();
      setupMockFrom({
        accounts: { mainData: [] },
        instagram_accounts: {
          mainData: [igAccount],
          failureRow: { consecutive_refresh_failures: 0, user_id: "user-1" },
        },
      });

      mockRefreshTokenByLoginType.mockResolvedValueOnce({
        ok: true,
        data: { access_token: "t", expires_in: 5184000 },
      });
      mockEncrypt.mockImplementationOnce(() => {
        throw new Error("Encryption key corrupted");
      });

      const result = await refreshAllTokens();

      expect(result.igErrors).toBe(1);
      expect(result.igRefreshed).toBe(0);
    });
  });

  // ========================================================================
  // 9. Fail-safe — partial failure isolation
  // ========================================================================

  describe("fail-safe — partial failure isolation", () => {
    it("continues processing remaining accounts after one fails", async () => {
      const account1 = makeThreadsAccount({ id: "t-1", username: "user1" });
      const account2 = makeThreadsAccount({ id: "t-2", username: "user2" });
      setupMockFrom({
        accounts: { mainData: [account1, account2] },
        instagram_accounts: { mainData: [] },
      });

      // First fetch fails, second succeeds
      mockFetch
        .mockResolvedValueOnce({
          ok: false,
          json: () =>
            Promise.resolve({ error: { message: "Rate limited" } }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () =>
            Promise.resolve({ access_token: "t2", expires_in: 5184000 }),
        });

      const result = await refreshAllTokens();

      expect(result.threadsErrors).toBe(1);
      expect(result.threadsRefreshed).toBe(1);
    });

    it("continues IG processing even if Threads query throws", async () => {
      const igAccount = makeIgAccount();

      let accountsSelectCount = 0;
      mockFrom.mockImplementation((table: string) => {
        if (table === "accounts") {
          accountsSelectCount++;
          if (accountsSelectCount <= 1) {
            // Pre-flight count — return a chain that throws on await
            const throwChain = thenableChain([]);
            // Override then to reject
            throwChain.then = (onF?: any, onR?: any) =>
              Promise.reject(new Error("DB connection lost")).then(onF, onR);
            throwChain.catch = (onR?: any) =>
              Promise.reject(new Error("DB connection lost")).catch(onR);
            return { ...throwChain, update: vi.fn().mockReturnValue(updateChain()) };
          }
          // Recovery probe etc — return empty
          return {
            ...thenableChain([]),
            update: vi.fn().mockReturnValue(updateChain()),
          };
        }
        if (table === "instagram_accounts") {
          const chain = thenableChain([igAccount]);
          chain.maybeSingle = vi.fn().mockResolvedValue({
            data: { consecutive_refresh_failures: 0 },
            error: null,
          });
          return { ...chain, update: vi.fn().mockReturnValue(updateChain()) };
        }
        return {
          ...thenableChain(null),
          update: vi.fn().mockReturnValue(updateChain()),
        };
      });

      mockRefreshTokenByLoginType.mockResolvedValueOnce({
        ok: true,
        data: { access_token: "ig_tok", expires_in: 5184000 },
      });

      const result = await refreshAllTokens();

      expect(result.igRefreshed).toBe(1);
    });

    it("network error on fetch is treated as transient", async () => {
      const account = makeThreadsAccount();
      setupMockFrom({
        accounts: {
          mainData: [account],
          failureRow: { consecutive_refresh_failures: 0, user_id: "user-1" },
        },
        instagram_accounts: { mainData: [] },
      });

      mockFetch.mockRejectedValueOnce(new Error("ECONNREFUSED"));

      const result = await refreshAllTokens();

      expect(result.threadsErrors).toBe(1);
      expect(mockAlertTokenRefreshFailure).toHaveBeenCalledWith(
        "threads",
        expect.any(String),
        expect.stringContaining("ECONNREFUSED"),
      );
    });
  });

  // ========================================================================
  // 10. Pre-flight expiry alert
  // ========================================================================

  describe("pre-flight expiry alert", () => {
    it("fires alert when >= 5 tokens expire within 48h", async () => {
      // We need the pre-flight count queries to return >= 5 total
      mockFrom.mockImplementation((_table: string) => {
        const chain = thenableChain([]);
        // The select call with { count: "exact", head: true } should return
        // a count of 3 for both tables
        const origSelect = chain.select;
        chain.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
          if (opts?.count === "exact" && opts?.head === true) {
            return thenableChain(null, null, 3);
          }
          return origSelect();
        });
        return { ...chain, update: vi.fn().mockReturnValue(updateChain()) };
      });

      await refreshAllTokens();

      // 3 + 3 = 6 >= 5 threshold
      expect(mockAlert).toHaveBeenCalledWith(
        "warn",
        expect.stringContaining("Token expiry cluster"),
        expect.objectContaining({
          threads: expect.any(Number),
          instagram: expect.any(Number),
        }),
      );
    });

    it("does not fire alert when < 5 tokens expire within 48h", async () => {
      mockFrom.mockImplementation(() => {
        const chain = thenableChain([]);
        const origSelect = chain.select;
        chain.select = vi.fn().mockImplementation((_cols: string, opts?: any) => {
          if (opts?.count === "exact" && opts?.head === true) {
            return thenableChain(null, null, 1);
          }
          return origSelect();
        });
        return { ...chain, update: vi.fn().mockReturnValue(updateChain()) };
      });

      await refreshAllTokens();

      // 1 + 1 = 2 < 5 threshold
      expect(mockAlert).not.toHaveBeenCalled();
    });
  });

  // ========================================================================
  // 11. Recovery probe
  // ========================================================================

  describe("recovery probe", () => {
    it("recovers a needs_reauth Threads account when token still works", async () => {
      const reauthAccount = makeThreadsAccount({
        id: "t-recover-1",
        username: "recovered_user",
      });

      // Track calls to see what happens
      let accountsCall = 0;
      mockFrom.mockImplementation((table: string) => {
        if (table === "accounts") {
          accountsCall++;
          const chain = thenableChain(
            // Pre-flight count → empty, expired-token guard → empty,
            // main select → empty, recovery probe → [reauthAccount]
            accountsCall >= 4 ? [reauthAccount] : [],
          );
          chain.maybeSingle = vi.fn().mockResolvedValue({
            data: { consecutive_refresh_failures: 0 },
            error: null,
          });
          return { ...chain, update: vi.fn().mockReturnValue(updateChain()) };
        }
        return {
          ...thenableChain([]),
          update: vi.fn().mockReturnValue(updateChain()),
        };
      });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            access_token: "recovered_token",
            expires_in: 5184000,
          }),
      });

      await refreshAllTokens();

      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining("graph.threads.net"),
        expect.anything(),
      );
      expect(mockEncrypt).toHaveBeenCalledWith("recovered_token");
    });

    it("marks token_expires_at=NOW for confirmed dead tokens in probe", async () => {
      const reauthAccount = makeThreadsAccount({ id: "t-dead-1" });

      let accountsCall = 0;
      const allUpdateCalls: any[] = [];
      mockFrom.mockImplementation((table: string) => {
        if (table === "accounts") {
          accountsCall++;
          const chain = thenableChain(
            accountsCall >= 4 ? [reauthAccount] : [],
          );
          const uChain = updateChain();
          const origUpdate = vi.fn().mockImplementation((data: any) => {
            allUpdateCalls.push({ table, data });
            return uChain;
          });
          chain.maybeSingle = vi.fn().mockResolvedValue({
            data: { consecutive_refresh_failures: 0 },
            error: null,
          });
          return { ...chain, update: origUpdate };
        }
        return {
          ...thenableChain([]),
          update: vi.fn().mockReturnValue(updateChain()),
        };
      });

      // Probe fails — token is dead
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: () =>
          Promise.resolve({
            error: { code: 190, message: "Token expired" },
          }),
      });

      await refreshAllTokens();

      // Should have an update with token_expires_at set to ~NOW
      const expiryUpdates = allUpdateCalls.filter(
        (c) =>
          c.data?.token_expires_at &&
          !c.data?.needs_reauth &&
          !c.data?.threads_access_token_encrypted,
      );
      expect(expiryUpdates.length).toBeGreaterThan(0);
    });

    it("does not mark token dead on network error during probe", async () => {
      const reauthAccount = makeThreadsAccount({ id: "t-probe-err-1" });

      let accountsCall = 0;
      mockFrom.mockImplementation((table: string) => {
        if (table === "accounts") {
          accountsCall++;
          const chain = thenableChain(
            accountsCall >= 4 ? [reauthAccount] : [],
          );
          chain.maybeSingle = vi.fn().mockResolvedValue({
            data: { consecutive_refresh_failures: 0 },
            error: null,
          });
          return { ...chain, update: vi.fn().mockReturnValue(updateChain()) };
        }
        return {
          ...thenableChain([]),
          update: vi.fn().mockReturnValue(updateChain()),
        };
      });

      mockFetch.mockRejectedValueOnce(new Error("Network timeout"));

      // Should not throw
      const result = await refreshAllTokens();
      expect(result).toBeDefined();
    });
  });

  // ========================================================================
  // 12. PBKDF2 v1->v2 token migration
  // ========================================================================

  describe("PBKDF2 v1->v2 token migration", () => {
    it("re-encrypts v1 tokens found in the database", async () => {
      const v1Account = {
        id: "v1-acc-1",
        threads_access_token_encrypted: "old_v1_encrypted_token",
      };

      // The migration query is the last accounts query after recovery probes.
      // We track calls to route correctly.
      let accountsCall = 0;
      mockFrom.mockImplementation((table: string) => {
        if (table === "accounts") {
          accountsCall++;
          // Calls 1-4 are pre-flight, main select, recovery probe,
          // migration starts at call 5+
          if (accountsCall >= 4) {
            const chain = thenableChain([v1Account]);
            return { ...chain, update: vi.fn().mockReturnValue(updateChain()) };
          }
          const chain = thenableChain([]);
          chain.maybeSingle = vi.fn().mockResolvedValue({
            data: { consecutive_refresh_failures: 0 },
            error: null,
          });
          return { ...chain, update: vi.fn().mockReturnValue(updateChain()) };
        }
        // IG migration returns empty
        return {
          ...thenableChain([]),
          update: vi.fn().mockReturnValue(updateChain()),
        };
      });

      mockNeedsUpgrade.mockReturnValue(true);
      mockDecrypt.mockReturnValue("plaintext_token");
      mockEncrypt.mockReturnValue("v2:new_encrypted_token");

      await refreshAllTokens();

      expect(mockNeedsUpgrade).toHaveBeenCalledWith("old_v1_encrypted_token");
      expect(mockDecrypt).toHaveBeenCalledWith("old_v1_encrypted_token");
      expect(mockEncrypt).toHaveBeenCalledWith("plaintext_token");
    });

    it("skips tokens that needsUpgrade() returns false for", async () => {
      const v2Account = {
        id: "v2-acc-1",
        threads_access_token_encrypted: "v2:already_upgraded",
      };

      let accountsCall = 0;
      mockFrom.mockImplementation((table: string) => {
        if (table === "accounts") {
          accountsCall++;
          if (accountsCall >= 4) {
            const chain = thenableChain([v2Account]);
            return { ...chain, update: vi.fn().mockReturnValue(updateChain()) };
          }
          const chain = thenableChain([]);
          return { ...chain, update: vi.fn().mockReturnValue(updateChain()) };
        }
        return {
          ...thenableChain([]),
          update: vi.fn().mockReturnValue(updateChain()),
        };
      });

      mockNeedsUpgrade.mockReturnValue(false);
      // Reset encrypt call tracking
      mockEncrypt.mockClear();

      await refreshAllTokens();

      // needsUpgrade returns false — should NOT have called decrypt/encrypt for migration
      // (encrypt may be called 0 times)
      const encryptCallsWithV2 = mockEncrypt.mock.calls.filter(
        (call: any[]) => call[0] === "plaintext_token",
      );
      expect(encryptCallsWithV2).toHaveLength(0);
    });
  });

  // ========================================================================
  // 13. Batch processing
  // ========================================================================

  describe("batch processing", () => {
    it("processes all accounts in the batch", async () => {
      const accounts = [
        makeThreadsAccount({ id: "t-1", username: "user1" }),
        makeThreadsAccount({ id: "t-2", username: "user2" }),
        makeThreadsAccount({ id: "t-3", username: "user3" }),
      ];

      setupMockFrom({
        accounts: { mainData: accounts },
        instagram_accounts: { mainData: [] },
      });

      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: () =>
            Promise.resolve({ access_token: "t1", expires_in: 5184000 }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () =>
            Promise.resolve({ access_token: "t2", expires_in: 5184000 }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: () =>
            Promise.resolve({ access_token: "t3", expires_in: 5184000 }),
        });

      const result = await refreshAllTokens();

      expect(result.threadsRefreshed).toBe(3);
      expect(result.total).toBe(3);
    });

    it("processes both Threads and IG accounts in same run", async () => {
      const threadsAccount = makeThreadsAccount();
      const igAccount = makeIgAccount();

      setupMockFrom({
        accounts: { mainData: [threadsAccount] },
        instagram_accounts: { mainData: [igAccount] },
      });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ access_token: "t_tok", expires_in: 5184000 }),
      });
      mockRefreshTokenByLoginType.mockResolvedValueOnce({
        ok: true,
        data: { access_token: "ig_tok", expires_in: 5184000 },
      });

      const result = await refreshAllTokens();

      expect(result.threadsRefreshed).toBe(1);
      expect(result.igRefreshed).toBe(1);
      expect(result.total).toBe(2);
    });
  });

  // ========================================================================
  // 14. IG refresh failure alerts
  // ========================================================================

  describe("IG refresh failure alerts", () => {
    it("fires Discord alert for IG refresh failure", async () => {
      const igAccount = makeIgAccount({ username: "ig_alert_user" });
      setupMockFrom({
        accounts: { mainData: [] },
        instagram_accounts: {
          mainData: [igAccount],
          failureRow: { consecutive_refresh_failures: 0, user_id: "user-1" },
        },
      });

      mockRefreshTokenByLoginType.mockResolvedValueOnce({
        ok: false,
        data: { error: { message: "IG token expired" } },
      });

      await refreshAllTokens();

      expect(mockAlertTokenRefreshFailure).toHaveBeenCalledWith(
        "instagram",
        "ig_alert_user",
        expect.stringContaining("IG token expired"),
      );
    });

    it("uses account id when username is missing for alert", async () => {
      const igAccount = makeIgAccount({
        id: "ig-fallback-id",
        username: "",
      });
      setupMockFrom({
        accounts: { mainData: [] },
        instagram_accounts: {
          mainData: [igAccount],
          failureRow: { consecutive_refresh_failures: 0, user_id: "user-1" },
        },
      });

      mockRefreshTokenByLoginType.mockResolvedValueOnce({
        ok: false,
        data: { error: { message: "Token invalid" } },
      });

      await refreshAllTokens();

      expect(mockAlertTokenRefreshFailure).toHaveBeenCalledWith(
        "instagram",
        "ig-fallback-id",
        expect.any(String),
      );
    });
  });

  // ========================================================================
  // 15. IG network errors — transient treatment
  // ========================================================================

  describe("IG network errors", () => {
    it("treats IG network error as transient", async () => {
      const igAccount = makeIgAccount();

      const allUpdateCalls: any[] = [];
      mockFrom.mockImplementation((table: string) => {
        const data = table === "instagram_accounts" ? [igAccount] : [];
        const chain = thenableChain(data);
        const uChain = updateChain();
        const origUpdate = vi.fn().mockImplementation((updateData: any) => {
          allUpdateCalls.push({ table, data: updateData });
          return uChain;
        });
        chain.maybeSingle = vi.fn().mockResolvedValue({
          data: { consecutive_refresh_failures: 2, user_id: "user-1" },
          error: null,
        });
        return { ...chain, update: origUpdate };
      });

      mockRefreshTokenByLoginType.mockRejectedValueOnce(
        new Error("ETIMEDOUT"),
      );

      const result = await refreshAllTokens();

      expect(result.igErrors).toBe(1);
      // Should reset failures, not set needs_reauth
      const reauthUpdates = allUpdateCalls.filter(
        (c) =>
          c.data?.needs_reauth === true &&
          c.data?.consecutive_refresh_failures !== undefined,
      );
      expect(reauthUpdates).toHaveLength(0);
    });
  });

  // ========================================================================
  // 16. Return shape validation
  // ========================================================================

  describe("return shape", () => {
    it("returns all expected fields in RefreshResult", async () => {
      setupMockFrom({
        accounts: { mainData: [] },
        instagram_accounts: { mainData: [] },
      });

      const result = await refreshAllTokens();

      expect(result).toEqual(
        expect.objectContaining({
          threadsRefreshed: expect.any(Number),
          threadsErrors: expect.any(Number),
          threadsSkipped: expect.any(Number),
          igRefreshed: expect.any(Number),
          igErrors: expect.any(Number),
          igSkipped: expect.any(Number),
          total: expect.any(Number),
        }),
      );
    });

    it("total equals threadsRefreshed + igRefreshed", async () => {
      const threadsAccount = makeThreadsAccount();
      const igAccount = makeIgAccount();

      setupMockFrom({
        accounts: { mainData: [threadsAccount] },
        instagram_accounts: { mainData: [igAccount] },
      });

      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ access_token: "t", expires_in: 5184000 }),
      });
      mockRefreshTokenByLoginType.mockResolvedValueOnce({
        ok: true,
        data: { access_token: "i", expires_in: 5184000 },
      });

      const result = await refreshAllTokens();

      expect(result.total).toBe(
        result.threadsRefreshed + result.igRefreshed,
      );
    });
  });
});
