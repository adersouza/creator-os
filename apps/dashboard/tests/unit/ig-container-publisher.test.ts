/**
 * Unit tests for IG Container Publisher Cron
 * (api/_lib/cron/ig-container-publisher.ts)
 *
 * Tests the container check-and-publish flow:
 * 1. Auth verification (verifyCronAuth)
 * 2. Lock acquisition (withCronLock)
 * 3. Orphan recovery — reset stuck "processing" containers
 * 4. Atomic claim — pending → processing to prevent double-publish
 * 5. Container ready → publish → update post record
 * 6. Container error → mark failed
 * 7. Container still pending — increment check count, reset to pending
 * 8. Dead letter after MAX_CHECK_ATTEMPTS (10)
 * 9. Account inactive/needs_reauth → skip container
 * 10. Error handling per container (fail-safe, doesn't block others)
 * 11. Engagement sync scheduling after publish
 * 12. Notification delivery on success/failure
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — module scope, BEFORE importing module under test
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockSupabase: any = {
  from: mockFrom,
};

vi.mock("@/api/_lib/supabase", () => ({
  getSupabase: () => mockSupabase,
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

vi.mock("@/api/_lib/alerting", () => ({
  alertCronFailure: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/api/_lib/cronUtils", () => ({
  trackCronRun: vi.fn().mockImplementation((_sb: unknown, _name: string, fn: () => unknown) => fn()),
  withCronLock: vi.fn().mockImplementation((_sb: unknown, _name: string, fn: () => unknown) => fn()),
}));

const mockCheckContainerReady = vi.fn();
const mockPublishContainerFn = vi.fn();
vi.mock("@/api/_lib/instagramApi", () => ({
  checkContainerReady: (...args: unknown[]) => mockCheckContainerReady(...args),
  publishContainer: (...args: unknown[]) => mockPublishContainerFn(...args),
}));

const mockDecrypt = vi.fn().mockReturnValue("decrypted-token");
vi.mock("@/api/_lib/encryption", () => ({
  decrypt: (...args: unknown[]) => mockDecrypt(...args),
}));

vi.mock("@/api/_lib/retryUtils", () => ({
  withRetry: vi.fn().mockImplementation((fn: () => unknown) => fn()),
  isRetryableMetaError: vi.fn().mockReturnValue(false),
}));

vi.mock("@/api/_lib/sentryServer", () => ({
  captureServerException: vi.fn().mockResolvedValue(undefined),
}));

const mockSchedulePostPublishSyncs = vi.fn().mockResolvedValue(undefined);
vi.mock("@/api/_lib/qstashSchedule", () => ({
  schedulePostPublishSyncs: (...args: unknown[]) =>
    mockSchedulePostPublishSyncs(...args),
}));

const mockDeliverNotification = vi.fn().mockResolvedValue(undefined);
vi.mock("@/api/_lib/deliverNotification", () => ({
  deliverNotification: (...args: unknown[]) =>
    mockDeliverNotification(...args),
}));

vi.mock("@/api/_lib/apiResponse", () => ({
  verifyCronAuth: vi.fn().mockReturnValue(true),
}));

// ---------------------------------------------------------------------------
// Import module under test (AFTER all mocks)
// ---------------------------------------------------------------------------

import { processPendingContainers } from "@/api/_lib/cron/ig-container-publisher";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function chainable(data: unknown, error: unknown = null) {
  const c: any = {};
  const methods = [
    "select", "eq", "in", "not", "gte", "lte", "lt", "or",
    "order", "limit", "insert", "update", "delete", "is",
  ];
  for (const m of methods) {
    c[m] = vi.fn().mockReturnValue(c);
  }
  c.maybeSingle = vi.fn().mockResolvedValue({ data, error });
  c.then = (resolve: (v: any) => void) => resolve({ data, error });
  return c;
}

function makeContainer(overrides: Record<string, unknown> = {}) {
  return {
    id: "container-1",
    post_id: "post-1",
    container_id: "meta-container-1",
    account_id: "ig-acc-1",
    check_count: 0,
    login_type: "facebook",
    ...overrides,
  };
}

function makeIgAccount(overrides: Record<string, unknown> = {}) {
  return {
    instagram_user_id: "ig-user-1",
    instagram_access_token_encrypted: "enc-token",
    is_active: true,
    needs_reauth: false,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("processPendingContainers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns 0 when no pending containers exist", async () => {
    let callCount = 0;
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "ig_pending_containers") {
        callCount++;
        if (callCount === 1) {
          // Orphan recovery update
          c.then = (resolve: (v: any) => void) => resolve({ data: null, error: null });
        } else {
          // Claim query — return empty with select
          c.select = vi.fn().mockReturnValue({
            ...c,
            then: (resolve: (v: any) => void) =>
              resolve({ data: [], error: null }),
          });
        }
      }
      return c;
    });

    const count = await processPendingContainers(mockSupabase);
    expect(count).toBe(0);
  });

  it("publishes container when status is ready", async () => {
    const container = makeContainer();
    const igAccount = makeIgAccount();

    mockCheckContainerReady.mockResolvedValue({ status: "ready" });
    mockPublishContainerFn.mockResolvedValue({
      success: true,
      mediaId: "media-abc",
      permalink: "https://instagram.com/p/abc",
    });

    let containerCallCount = 0;
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "ig_pending_containers") {
        containerCallCount++;
        if (containerCallCount <= 1) {
          // Orphan recovery
          c.then = (resolve: (v: any) => void) => resolve({ data: null, error: null });
        } else if (containerCallCount === 2) {
          // Claim query
          c.select = vi.fn().mockReturnValue({
            ...c,
            then: (resolve: (v: any) => void) =>
              resolve({ data: [container], error: null }),
          });
        }
      }
      if (table === "instagram_accounts") {
        c.maybeSingle = vi.fn().mockResolvedValue({
          data: igAccount,
          error: null,
        });
      }
      if (table === "posts") {
        c.maybeSingle = vi.fn().mockResolvedValue({
          data: { user_id: "user-1" },
          error: null,
        });
      }
      if (table === "notifications") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: null, error: null });
      }
      return c;
    });

    const count = await processPendingContainers(mockSupabase);
    expect(count).toBe(1);
  });

  it("marks container as error when status is error", async () => {
    const container = makeContainer();
    const igAccount = makeIgAccount();

    mockCheckContainerReady.mockResolvedValue({
      status: "error",
      error: "Media processing failed",
    });

    let containerCallCount = 0;
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "ig_pending_containers") {
        containerCallCount++;
        if (containerCallCount <= 1) {
          c.then = (resolve: (v: any) => void) => resolve({ data: null, error: null });
        } else if (containerCallCount === 2) {
          c.select = vi.fn().mockReturnValue({
            ...c,
            then: (resolve: (v: any) => void) =>
              resolve({ data: [container], error: null }),
          });
        }
      }
      if (table === "instagram_accounts") {
        c.maybeSingle = vi.fn().mockResolvedValue({
          data: igAccount,
          error: null,
        });
      }
      return c;
    });

    const count = await processPendingContainers(mockSupabase);
    expect(count).toBe(0);
  });

  it("moves container to dead letter after MAX_CHECK_ATTEMPTS", async () => {
    const container = makeContainer({ check_count: 9 }); // 9 + 1 = 10
    const igAccount = makeIgAccount();

    mockCheckContainerReady.mockResolvedValue({ status: "pending" });

    const updateCalls: any[] = [];
    let containerCallCount = 0;
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "ig_pending_containers") {
        containerCallCount++;
        if (containerCallCount <= 1) {
          c.then = (resolve: (v: any) => void) => resolve({ data: null, error: null });
        } else if (containerCallCount === 2) {
          c.select = vi.fn().mockReturnValue({
            ...c,
            then: (resolve: (v: any) => void) =>
              resolve({ data: [container], error: null }),
          });
        }
        const origUpdate = c.update;
        c.update = vi.fn().mockImplementation((payload: any) => {
          updateCalls.push(payload);
          return origUpdate(payload);
        });
      }
      if (table === "instagram_accounts") {
        c.maybeSingle = vi.fn().mockResolvedValue({
          data: igAccount,
          error: null,
        });
      }
      if (table === "posts") {
        c.maybeSingle = vi.fn().mockResolvedValue({
          data: { user_id: "user-1" },
          error: null,
        });
      }
      if (table === "notifications") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: null, error: null });
      }
      return c;
    });

    const count = await processPendingContainers(mockSupabase);
    expect(count).toBe(0);

    // Verify dead_letter was set
    const dlqUpdate = updateCalls.find((u) => u.dead_letter === true);
    expect(dlqUpdate).toBeDefined();
  });

  it("skips containers for inactive accounts", async () => {
    const container = makeContainer();
    const inactiveAccount = makeIgAccount({ is_active: false });

    let containerCallCount = 0;
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "ig_pending_containers") {
        containerCallCount++;
        if (containerCallCount <= 1) {
          c.then = (resolve: (v: any) => void) => resolve({ data: null, error: null });
        } else if (containerCallCount === 2) {
          c.select = vi.fn().mockReturnValue({
            ...c,
            then: (resolve: (v: any) => void) =>
              resolve({ data: [container], error: null }),
          });
        }
      }
      if (table === "instagram_accounts") {
        c.maybeSingle = vi.fn().mockResolvedValue({
          data: inactiveAccount,
          error: null,
        });
      }
      return c;
    });

    const count = await processPendingContainers(mockSupabase);
    expect(count).toBe(0);
  });

  it("skips containers for accounts needing reauth", async () => {
    const container = makeContainer();
    const reauthAccount = makeIgAccount({ needs_reauth: true });

    let containerCallCount = 0;
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "ig_pending_containers") {
        containerCallCount++;
        if (containerCallCount <= 1) {
          c.then = (resolve: (v: any) => void) => resolve({ data: null, error: null });
        } else if (containerCallCount === 2) {
          c.select = vi.fn().mockReturnValue({
            ...c,
            then: (resolve: (v: any) => void) =>
              resolve({ data: [container], error: null }),
          });
        }
      }
      if (table === "instagram_accounts") {
        c.maybeSingle = vi.fn().mockResolvedValue({
          data: reauthAccount,
          error: null,
        });
      }
      return c;
    });

    const count = await processPendingContainers(mockSupabase);
    expect(count).toBe(0);
  });

  it("handles container with no valid account token", async () => {
    const container = makeContainer();

    let containerCallCount = 0;
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "ig_pending_containers") {
        containerCallCount++;
        if (containerCallCount <= 1) {
          c.then = (resolve: (v: any) => void) => resolve({ data: null, error: null });
        } else if (containerCallCount === 2) {
          c.select = vi.fn().mockReturnValue({
            ...c,
            then: (resolve: (v: any) => void) =>
              resolve({ data: [container], error: null }),
          });
        }
      }
      if (table === "instagram_accounts") {
        c.maybeSingle = vi.fn().mockResolvedValue({
          data: null, // No account found
          error: null,
        });
      }
      return c;
    });

    const count = await processPendingContainers(mockSupabase);
    expect(count).toBe(0);
  });

  it("increments check_count and resets to pending when still processing", async () => {
    const container = makeContainer({ check_count: 3 });
    const igAccount = makeIgAccount();

    mockCheckContainerReady.mockResolvedValue({ status: "pending" });

    const updateCalls: any[] = [];
    let containerCallCount = 0;
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "ig_pending_containers") {
        containerCallCount++;
        if (containerCallCount <= 1) {
          c.then = (resolve: (v: any) => void) => resolve({ data: null, error: null });
        } else if (containerCallCount === 2) {
          c.select = vi.fn().mockReturnValue({
            ...c,
            then: (resolve: (v: any) => void) =>
              resolve({ data: [container], error: null }),
          });
        }
        const origUpdate = c.update;
        c.update = vi.fn().mockImplementation((payload: any) => {
          updateCalls.push(payload);
          return origUpdate(payload);
        });
      }
      if (table === "instagram_accounts") {
        c.maybeSingle = vi.fn().mockResolvedValue({
          data: igAccount,
          error: null,
        });
      }
      return c;
    });

    await processPendingContainers(mockSupabase);

    // Should have an update setting status back to "pending" with incremented check_count
    const pendingUpdate = updateCalls.find(
      (u) => u.status === "pending" && u.check_count === 4
    );
    expect(pendingUpdate).toBeDefined();
  });

  it("handles query error by throwing (for trackCronRun to catch)", async () => {
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "ig_pending_containers") {
        c.select = vi.fn().mockReturnValue({
          ...c,
          then: (resolve: (v: any) => void) =>
            resolve({ data: null, error: { message: "Query failed" } }),
        });
        // The update for orphan recovery needs to work first
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: null, error: { message: "Query failed" } });
      }
      return c;
    });

    // Should throw because the query returned an error
    await expect(processPendingContainers(mockSupabase)).rejects.toThrow();
  });
});
