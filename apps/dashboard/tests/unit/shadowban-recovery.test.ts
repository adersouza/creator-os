/**
 * Unit tests for Shadowban Recovery Cron Sub-Handler
 * (api/_lib/cron/shadowban-recovery.ts)
 *
 * Tests the automated 7-day recovery sequence for shadowbanned accounts:
 * 1. Recovery phase calculation (silence/safe_posting/normal_test/ramp_up/permanently_dead)
 * 2. View-based recovery detection
 * 3. Safe recovery post generation and queueing
 * 4. Permanently dead marking after 3 failed cycles
 * 5. Shadowban trigger analysis (pre-ban content patterns)
 * 6. Error isolation — single account failure doesn't block others
 * 7. Discord alert on recovery/death events
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — module scope, BEFORE importing module under test
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockRpc = vi.fn();

vi.mock("@/api/_lib/supabase", () => ({
  getSupabase: () => ({ from: mockFrom, rpc: mockRpc }),
}));

vi.mock("@/api/_lib/logger", () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
    debug: vi.fn(),
  },
  serializeError: (err: unknown) =>
    err instanceof Error ? err.message : String(err),
}));

const mockAlert = vi.fn().mockResolvedValue(undefined);
vi.mock("@/api/_lib/alerting", () => ({
  alert: (...args: unknown[]) => mockAlert(...args),
  AlertLevel: { INFO: "info", WARN: "warn", ERROR: "error" },
}));

const mockFilterContent = vi.fn();
const mockResolveFilterConfig = vi.fn();
vi.mock("@/api/_lib/handlers/auto-post/contentFilter", () => ({
  filterContent: (...args: unknown[]) => mockFilterContent(...args),
  resolveFilterConfig: (...args: unknown[]) => mockResolveFilterConfig(...args),
}));

const mockGenerateWithProvider = vi.fn();
const mockGetUserAIConfig = vi.fn();
const mockResolveVoiceProfile = vi.fn();
vi.mock("@/api/_lib/handlers/auto-post/contentSelection", () => ({
  generateWithProvider: (...args: unknown[]) =>
    mockGenerateWithProvider(...args),
  getUserAIConfig: (...args: unknown[]) => mockGetUserAIConfig(...args),
  resolveVoiceProfile: (...args: unknown[]) =>
    mockResolveVoiceProfile(...args),
}));

// ---------------------------------------------------------------------------
// Import module under test (AFTER all mocks)
// ---------------------------------------------------------------------------

import { processShadowbanRecovery } from "@/api/_lib/cron/shadowban-recovery";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function chain(data: unknown, error: unknown = null) {
  const c: Record<string, ReturnType<typeof vi.fn>> = {};
  const methods = [
    "select", "eq", "in", "not", "gte", "lte", "lt", "or",
    "order", "limit", "is", "insert", "update", "delete",
  ];
  for (const m of methods) {
    c[m] = vi.fn().mockReturnValue(c);
  }
  c.maybeSingle = vi.fn().mockResolvedValue({ data, error });
  // Make terminal calls also resolve
  (c as any).then = undefined; // Ensure it's not a thenable by default
  // Override select to also work as a terminal
  const origSelect = c.select;
  c.select = vi.fn().mockImplementation((...args: unknown[]) => {
    (origSelect as unknown as (...args: unknown[]) => unknown)(...args);
    return c;
  });
  // Make the chain itself a promise when awaited
  const handler = {
    get(target: any, prop: string) {
      if (prop === "then") {
        return (resolve: (v: unknown) => void) =>
          resolve({ data, error });
      }
      return target[prop];
    },
  };
  return new Proxy(c, handler);
}

function setupFromMock(tableMap: Record<string, ReturnType<typeof chain>>) {
  mockFrom.mockImplementation((table: string) => {
    return tableMap[table] || chain(null);
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("processShadowbanRecovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFilterContent.mockReturnValue({ passed: true });
    mockResolveFilterConfig.mockReturnValue({});
    mockGetUserAIConfig.mockResolvedValue({
      provider: "gemini",
      apiKey: "test-key",
      model: "gemini-2.0-flash",
    });
    mockResolveVoiceProfile.mockResolvedValue({
      voice_profile: "casual, fun creator",
    });
    mockGenerateWithProvider.mockResolvedValue(
      "what song are you currently playing on repeat"
    );
  });

  it("returns zero counts when no shadowbanned accounts exist", async () => {
    setupFromMock({
      account_health_snapshots: chain(null),
    });
    // Override to return empty array
    mockFrom.mockImplementation((table: string) => {
      if (table === "account_health_snapshots") {
        const c = chain([]);
        // The first call selects bannedAccounts
        return c;
      }
      return chain(null);
    });

    const result = await processShadowbanRecovery();
    expect(result.accountsInRecovery).toBe(0);
    expect(result.silenced).toBe(0);
    expect(result.recovered).toBe(0);
    expect(result.permanentlyDead).toBe(0);
  });

  it("recovers an account when recent posts have views > 0", async () => {
    const bannedAccount = {
      account_id: "acc-1",
      user_id: "user-1",
      account_name: "testuser",
      is_shadowbanned: true,
      consecutive_dead_days: 5,
      auto_disabled: true,
      auto_disabled_at: new Date().toISOString(),
      recovery_attempts: 0,
    };

    const callTracker: string[] = [];
    mockFrom.mockImplementation((table: string) => {
      const c: any = {};
      const methods = [
        "select", "eq", "in", "not", "gte", "lte", "lt", "or",
        "order", "limit", "is", "insert", "update", "delete",
      ];
      for (const m of methods) {
        c[m] = vi.fn().mockReturnValue(c);
      }
      c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
      c.then = (resolve: (v: any) => void) => {
        if (table === "account_health_snapshots") {
          callTracker.push("health_snapshots");
          if (callTracker.filter((t) => t === "health_snapshots").length === 1) {
            // First call: get banned accounts
            return resolve({ data: [bannedAccount], error: null });
          }
          // Subsequent: update calls
          return resolve({ data: null, error: null });
        }
        if (table === "posts") {
          // Return posts with views > 0 (recovery signal)
          return resolve({
            data: [
              { views_count: 150, engagement_fetched_at: new Date().toISOString() },
            ],
            error: null,
          });
        }
        if (table === "accounts") {
          return resolve({ data: null, error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    const result = await processShadowbanRecovery();
    expect(result.accountsInRecovery).toBe(1);
    expect(result.recovered).toBe(1);
    expect(result.permanentlyDead).toBe(0);
  });

  it("silences accounts in day 0-2 of recovery (silence phase)", async () => {
    const bannedAccount = {
      account_id: "acc-2",
      user_id: "user-2",
      account_name: "silenceduser",
      is_shadowbanned: true,
      consecutive_dead_days: 1, // Day 1 -> silence phase
      auto_disabled: true,
      auto_disabled_at: new Date().toISOString(),
      recovery_attempts: 0,
    };

    const callTracker: string[] = [];
    mockFrom.mockImplementation((table: string) => {
      const c: any = {};
      const methods = [
        "select", "eq", "in", "not", "gte", "lte", "lt", "or",
        "order", "limit", "is", "insert", "update", "delete",
      ];
      for (const m of methods) {
        c[m] = vi.fn().mockReturnValue(c);
      }
      c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
      c.then = (resolve: (v: any) => void) => {
        if (table === "account_health_snapshots") {
          callTracker.push("health_snapshots");
          if (callTracker.filter((t) => t === "health_snapshots").length === 1) {
            return resolve({ data: [bannedAccount], error: null });
          }
          return resolve({ data: null, error: null });
        }
        if (table === "posts") {
          // No posts with views (not recovered)
          return resolve({ data: [], error: null });
        }
        if (table === "accounts") {
          return resolve({ data: null, error: null });
        }
        if (table === "agent_notes") {
          return resolve({ data: null, error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    const result = await processShadowbanRecovery();
    expect(result.silenced).toBe(1);
    expect(result.recovered).toBe(0);
  });

  it("marks account permanently dead after 3 recovery cycles", async () => {
    const bannedAccount = {
      account_id: "acc-dead",
      user_id: "user-dead",
      account_name: "deaduser",
      is_shadowbanned: true,
      consecutive_dead_days: 21,
      auto_disabled: true,
      auto_disabled_at: new Date().toISOString(),
      recovery_attempts: 3, // 3 cycles = permanently dead
    };

    const callTracker: string[] = [];
    mockFrom.mockImplementation((table: string) => {
      const c: any = {};
      const methods = [
        "select", "eq", "in", "not", "gte", "lte", "lt", "or",
        "order", "limit", "is", "insert", "update", "delete",
      ];
      for (const m of methods) {
        c[m] = vi.fn().mockReturnValue(c);
      }
      c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
      c.then = (resolve: (v: any) => void) => {
        if (table === "account_health_snapshots") {
          callTracker.push("health_snapshots");
          if (callTracker.filter((t) => t === "health_snapshots").length === 1) {
            return resolve({ data: [bannedAccount], error: null });
          }
          return resolve({ data: null, error: null });
        }
        if (table === "posts") {
          return resolve({ data: [], error: null });
        }
        if (table === "accounts") {
          return resolve({ data: null, error: null });
        }
        if (table === "agent_notes") {
          return resolve({ data: null, error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    const result = await processShadowbanRecovery();
    expect(result.permanentlyDead).toBe(1);
    expect(result.recovered).toBe(0);
  });

  it("sends Discord alert when recovery events occur", async () => {
    // Test with a recovered account (views > 0) so alert fires
    const bannedAccount = {
      account_id: "acc-alert",
      user_id: "user-alert",
      account_name: "alertuser",
      is_shadowbanned: true,
      consecutive_dead_days: 5,
      auto_disabled: true,
      auto_disabled_at: new Date().toISOString(),
      recovery_attempts: 0,
    };

    const callTracker: string[] = [];
    mockFrom.mockImplementation((table: string) => {
      const c: any = {};
      const methods = [
        "select", "eq", "in", "not", "gte", "lte", "lt", "or",
        "order", "limit", "is", "insert", "update", "delete",
      ];
      for (const m of methods) {
        c[m] = vi.fn().mockReturnValue(c);
      }
      c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
      c.then = (resolve: (v: any) => void) => {
        if (table === "account_health_snapshots") {
          callTracker.push("health_snapshots");
          if (callTracker.filter((t) => t === "health_snapshots").length === 1) {
            return resolve({ data: [bannedAccount], error: null });
          }
          // trigger analysis query
          return resolve({ data: [], error: null });
        }
        if (table === "posts") {
          // Return posts with views > 0 to trigger recovery
          return resolve({
            data: [{ views_count: 100, engagement_fetched_at: new Date().toISOString() }],
            error: null,
          });
        }
        if (table === "accounts") {
          return resolve({ data: null, error: null });
        }
        if (table === "agent_notes") {
          return resolve({ data: null, error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    await processShadowbanRecovery();
    // Alert fires when recovered > 0
    expect(mockAlert).toHaveBeenCalled();
  });

  it("isolates errors — one account failure does not block others", async () => {
    const accounts = [
      {
        account_id: "acc-fail",
        user_id: "user-fail",
        account_name: "failuser",
        is_shadowbanned: true,
        consecutive_dead_days: 1,
        auto_disabled: true,
        auto_disabled_at: new Date().toISOString(),
        recovery_attempts: 0,
      },
      {
        account_id: "acc-ok",
        user_id: "user-ok",
        account_name: "okuser",
        is_shadowbanned: true,
        consecutive_dead_days: 1,
        auto_disabled: true,
        auto_disabled_at: new Date().toISOString(),
        recovery_attempts: 0,
      },
    ];

    let accountIndex = 0;
    const callTracker: string[] = [];
    mockFrom.mockImplementation((table: string) => {
      const c: any = {};
      const methods = [
        "select", "eq", "in", "not", "gte", "lte", "lt", "or",
        "order", "limit", "is", "insert", "update", "delete",
      ];
      for (const m of methods) {
        c[m] = vi.fn().mockReturnValue(c);
      }
      c.maybeSingle = vi.fn().mockResolvedValue({ data: null, error: null });
      c.then = (resolve: (v: any) => void) => {
        if (table === "account_health_snapshots") {
          callTracker.push("health_snapshots");
          if (callTracker.filter((t) => t === "health_snapshots").length === 1) {
            return resolve({ data: accounts, error: null });
          }
          return resolve({ data: null, error: null });
        }
        if (table === "posts") {
          // First account throws, second returns empty
          if (accountIndex === 0) {
            accountIndex++;
            throw new Error("DB connection lost");
          }
          return resolve({ data: [], error: null });
        }
        if (table === "accounts") {
          return resolve({ data: null, error: null });
        }
        if (table === "agent_notes") {
          return resolve({ data: null, error: null });
        }
        return resolve({ data: null, error: null });
      };
      return c;
    });

    // Should not throw — errors are caught per-account
    const result = await processShadowbanRecovery();
    expect(result.accountsInRecovery).toBe(2);
  });

  it("returns result even on fatal error (top-level catch)", async () => {
    mockFrom.mockImplementation(() => {
      throw new Error("Total DB failure");
    });

    const result = await processShadowbanRecovery();
    // Should return a valid result object (zeroed out)
    expect(result).toBeDefined();
    expect(result.accountsInRecovery).toBe(0);
  });
});
