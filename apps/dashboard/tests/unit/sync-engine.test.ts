/**
 * Tests for the multi-account background sync engine.
 *
 * Three bugs identified in audit (2026-03-07):
 *   1. OAuth code 190 (token expired) is misclassified as "suspended" instead of "needs_reauth"
 *   2. A fatal error on one account must not abort remaining accounts in the batch
 *   3. IG fan-out threshold: >20 IG accounts must route to QStash, not inline
 *
 * Each test mirrors the exact decision logic extracted from sync-orchestrator.ts
 * so it runs without any infra (no Redis, no Supabase, no network).
 */

import { describe, expect, it } from "vitest";

// ============================================================================
// Bug 1 — classifyProfileError
// Mirror the error-classification block from syncAccount() (lines 641–667)
// ============================================================================

type ProfileErrorClass =
  | { kind: "needs_reauth" }
  | { kind: "suspended" }
  | { kind: "transient" };

/**
 * CURRENT (broken) implementation — code 190 lumped into isSuspended.
 * Tests against this must FAIL on the 190 assertion to prove the bug.
 */
function classifyProfileError_BROKEN(
  errorCode: number | undefined,
  errorMessage: string,
): ProfileErrorClass {
  const isSuspended =
    errorCode === 100 ||
    errorCode === 190 || // ← bug: OAuthException treated as suspension
    errorCode === 10 ||
    errorMessage.toLowerCase().includes("suspended");

  if (isSuspended) return { kind: "suspended" };
  return { kind: "transient" };
}

/**
 * FIXED implementation — code 190 routed to its own branch.
 */
function classifyProfileError_FIXED(
  errorCode: number | undefined,
  errorMessage: string,
): ProfileErrorClass {
  // OAuthException: token expired / invalidated — user must reconnect
  if (errorCode === 190) return { kind: "needs_reauth" };

  // Genuine account suspension (content policy, platform ban)
  const isSuspended =
    errorCode === 100 ||
    errorCode === 10 ||
    errorMessage.toLowerCase().includes("suspended");

  if (isSuspended) return { kind: "suspended" };
  return { kind: "transient" };
}

describe("classifyProfileError — Bug 1: OAuth 190 misclassification", () => {
  describe("BROKEN implementation (documents the bug)", () => {
    it("incorrectly classifies code 190 as 'suspended' instead of 'needs_reauth'", () => {
      const result = classifyProfileError_BROKEN(190, "Error validating access token");
      // This passes today — proving the bug exists
      expect(result.kind).toBe("suspended");
    });
  });

  describe("FIXED implementation", () => {
    it("classifies code 190 (OAuthException / token expired) as needs_reauth", () => {
      const result = classifyProfileError_FIXED(190, "Error validating access token");
      expect(result.kind).toBe("needs_reauth");
    });

    it("classifies code 190 with any message as needs_reauth, not suspended", () => {
      const result = classifyProfileError_FIXED(190, "The user has changed their password");
      expect(result.kind).toBe("needs_reauth");
    });

    it("classifies code 100 as suspended (unchanged)", () => {
      const result = classifyProfileError_FIXED(100, "Invalid parameter");
      expect(result.kind).toBe("suspended");
    });

    it("classifies code 10 as suspended (unchanged)", () => {
      const result = classifyProfileError_FIXED(10, "Application does not have permission");
      expect(result.kind).toBe("suspended");
    });

    it("classifies message containing 'suspended' as suspended (unchanged)", () => {
      const result = classifyProfileError_FIXED(undefined, "Account has been suspended");
      expect(result.kind).toBe("suspended");
    });

    it("classifies unknown error codes as transient", () => {
      const result = classifyProfileError_FIXED(500, "Internal server error");
      expect(result.kind).toBe("transient");
    });

    it("classifies missing error code with generic message as transient", () => {
      const result = classifyProfileError_FIXED(undefined, "Unknown error");
      expect(result.kind).toBe("transient");
    });

    it("does not conflate 'suspended' message with token errors", () => {
      // A token error should never be classified as suspended
      const result = classifyProfileError_FIXED(190, "session has been invalidated for the user");
      expect(result.kind).toBe("needs_reauth");
      expect(result.kind).not.toBe("suspended");
    });
  });
});

// ============================================================================
// Bug 2 — Partial sync isolation
// Mirror the batch loop result accumulation from processAnalyticsSyncQueue()
// ============================================================================

interface AccountSyncOutcome {
  accountId: string;
  success: boolean;
  error?: string;
}

/**
 * Simulates the batch processor from lines 1080–1116.
 * A single account throwing must not abort the remaining accounts.
 */
async function simulateBatchProcessor(
  accountIds: string[],
  failingIds: Set<string>,
): Promise<{ success: number; failed: number; processed: string[] }> {
  let success = 0;
  let failed = 0;
  const processed: string[] = [];

  const CONCURRENCY_LIMIT = 3;

  for (let batchStart = 0; batchStart < accountIds.length; batchStart += CONCURRENCY_LIMIT) {
    const batch = accountIds.slice(batchStart, batchStart + CONCURRENCY_LIMIT);

    const batchResults = await Promise.all(
      batch.map(async (accountId): Promise<AccountSyncOutcome> => {
        // Simulate a fatal throw from syncAccount()
        if (failingIds.has(accountId)) {
          try {
            throw new Error("Meta API 500: Internal Server Error");
          } catch (error: unknown) {
            // This is the catch block at line 770-776
            return {
              accountId,
              success: false,
              error: error instanceof Error ? error.message : String(error),
            };
          }
        }
        return { accountId, success: true };
      }),
    );

    for (const result of batchResults) {
      processed.push(result.accountId);
      if (result.success) {
        success++;
      } else {
        failed++;
      }
    }
  }

  return { success, failed, processed };
}

describe("Batch processor — Bug 2: Partial sync isolation", () => {
  it("processes all 50 accounts even when account #47 throws a fatal error", async () => {
    const accountIds = Array.from({ length: 50 }, (_, i) => `acc_${i + 1}`);
    const failingIds = new Set(["acc_47"]);

    const result = await simulateBatchProcessor(accountIds, failingIds);

    expect(result.processed).toHaveLength(50);
    expect(result.success).toBe(49);
    expect(result.failed).toBe(1);
  });

  it("accounts 48, 49, and 50 are present in processed list after #47 fails", async () => {
    const accountIds = Array.from({ length: 50 }, (_, i) => `acc_${i + 1}`);
    const failingIds = new Set(["acc_47"]);

    const result = await simulateBatchProcessor(accountIds, failingIds);

    expect(result.processed).toContain("acc_48");
    expect(result.processed).toContain("acc_49");
    expect(result.processed).toContain("acc_50");
  });

  it("multiple failures in a single batch do not abort the batch or subsequent batches", async () => {
    const accountIds = Array.from({ length: 9 }, (_, i) => `acc_${i + 1}`);
    // All 3 accounts in the first batch fail
    const failingIds = new Set(["acc_1", "acc_2", "acc_3"]);

    const result = await simulateBatchProcessor(accountIds, failingIds);

    expect(result.processed).toHaveLength(9);
    expect(result.failed).toBe(3);
    expect(result.success).toBe(6);
    // Batches 2 and 3 still ran
    expect(result.processed).toContain("acc_4");
    expect(result.processed).toContain("acc_7");
  });

  it("a job with zero failing accounts produces success === total", async () => {
    const accountIds = ["a1", "a2", "a3", "a4"];
    const result = await simulateBatchProcessor(accountIds, new Set());
    expect(result.success).toBe(4);
    expect(result.failed).toBe(0);
  });
});

// ============================================================================
// Bug 3 — QStash fan-out threshold
// Mirror the IG_DIRECT_LIMIT check from lines 1137–1176
// ============================================================================

const IG_DIRECT_LIMIT = 20;

type IgSyncRoute = "inline" | "qstash";

function routeIgAccounts(igAccountIds: string[]): IgSyncRoute {
  if (igAccountIds.length > IG_DIRECT_LIMIT) return "qstash";
  return "inline";
}

describe("IG fan-out routing — Bug 3: QStash threshold", () => {
  it("routes 20 IG accounts inline (at the limit)", () => {
    const ids = Array.from({ length: 20 }, (_, i) => `ig_${i}`);
    expect(routeIgAccounts(ids)).toBe("inline");
  });

  it("routes 21 IG accounts to QStash (above the limit)", () => {
    const ids = Array.from({ length: 21 }, (_, i) => `ig_${i}`);
    expect(routeIgAccounts(ids)).toBe("qstash");
  });

  it("routes 200 IG accounts to QStash", () => {
    const ids = Array.from({ length: 200 }, (_, i) => `ig_${i}`);
    expect(routeIgAccounts(ids)).toBe("qstash");
  });

  it("routes 1 IG account inline", () => {
    expect(routeIgAccounts(["ig_0"])).toBe("inline");
  });

  it("routes empty list inline (no-op)", () => {
    expect(routeIgAccounts([])).toBe("inline");
  });
});
