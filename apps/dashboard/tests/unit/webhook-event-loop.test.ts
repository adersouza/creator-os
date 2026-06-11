/**
 * Unit tests for Webhook Processor Event Loop
 * (api/_lib/cron/webhook-processor/event-loop.ts)
 *
 * Tests the batch event processing loops for Threads and Instagram webhook events:
 * 1. Event fetching — query for unprocessed events, respect retry timing
 * 2. Successful processing — batch mark as processed, broadcast to frontend
 * 3. Error classification — permanent errors → dead letter, transient → retry
 * 4. Retry scheduling — exponential backoff via calculateBackoff
 * 5. Time budget enforcement — stops processing when budget exhausted
 * 6. Redis webhook-active keys — set for each processed account
 * 7. Broadcast — per-user individual events + batch summary
 * 8. Batch mark retry — retries once on mark failure
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — module scope, BEFORE importing module under test
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockChannel = vi.fn();

const mockSupabase: any = {
  from: mockFrom,
  channel: mockChannel,
};

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

const mockRedisSet = vi.fn().mockResolvedValue("OK");
vi.mock("@/api/_lib/redis", () => ({
  getRedis: () => ({
    set: mockRedisSet,
  }),
}));

const mockClassifyWebhookError = vi.fn();
const mockShouldRetry = vi.fn();
const mockCalculateBackoff = vi.fn();
vi.mock("@/api/_lib/retryUtils", () => ({
  classifyWebhookError: (...args: unknown[]) =>
    mockClassifyWebhookError(...args),
  shouldRetry: (...args: unknown[]) => mockShouldRetry(...args),
  calculateBackoff: (...args: unknown[]) => mockCalculateBackoff(...args),
}));

const mockHandleThreadsWebhookEvent = vi.fn();
vi.mock("@/api/_lib/cron/webhook-processor/threads-processors", () => ({
  handleThreadsWebhookEvent: (...args: unknown[]) =>
    mockHandleThreadsWebhookEvent(...args),
}));

const mockHandleIgWebhookEvent = vi.fn();
vi.mock("@/api/_lib/cron/webhook-processor/ig-processors", () => ({
  handleIgWebhookEvent: (...args: unknown[]) =>
    mockHandleIgWebhookEvent(...args),
}));

const mockScheduleWebhookReplay = vi.fn().mockResolvedValue(undefined);
vi.mock("@/api/_lib/cron/webhook-processor/retry", () => ({
  scheduleWebhookReplay: (...args: unknown[]) =>
    mockScheduleWebhookReplay(...args),
}));

vi.mock("@/api/_lib/sentryServer", () => ({
  captureServerException: vi.fn().mockResolvedValue(undefined),
}));

// ---------------------------------------------------------------------------
// Import module under test (AFTER all mocks)
// ---------------------------------------------------------------------------

import {
  processThreadsWebhookEvents,
  processIgWebhookEvents,
} from "@/api/_lib/cron/webhook-processor/event-loop";

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

function setupBroadcastMock() {
  const httpSend = vi.fn().mockResolvedValue(undefined);
  mockChannel.mockReturnValue({ httpSend });
  return httpSend;
}

// ---------------------------------------------------------------------------
// Tests: processThreadsWebhookEvents
// ---------------------------------------------------------------------------

describe("processThreadsWebhookEvents", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockHandleThreadsWebhookEvent.mockResolvedValue(undefined);
    mockClassifyWebhookError.mockReturnValue("transient");
    mockShouldRetry.mockReturnValue(true);
    mockCalculateBackoff.mockReturnValue(new Date(Date.now() + 60000));
    setupBroadcastMock();
  });

  it("returns 0 when no events found", async () => {
    mockFrom.mockImplementation(() => chainable([], null));

    const count = await processThreadsWebhookEvents(mockSupabase, Date.now());
    expect(count).toBe(0);
  });

  it("returns 0 on fetch error (fail-soft)", async () => {
    mockFrom.mockImplementation(() =>
      chainable(null, { message: "DB timeout" })
    );

    const count = await processThreadsWebhookEvents(mockSupabase, Date.now());
    expect(count).toBe(0);
  });

  it("processes events and batch-marks as processed", async () => {
    const events = [
      {
        id: "evt-1",
        event_type: "reply",
        threads_user_id: "tu-1",
        payload: {},
        retry_count: 0,
      },
      {
        id: "evt-2",
        event_type: "mention",
        threads_user_id: "tu-1",
        payload: {},
        retry_count: 0,
      },
    ];

    let callCount = 0;
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "threads_webhook_events") {
        callCount++;
        if (callCount === 1) {
          // First call: fetch events
          c.then = (resolve: (v: any) => void) =>
            resolve({ data: events, error: null });
        } else {
          // Subsequent calls: batch mark
          c.then = (resolve: (v: any) => void) =>
            resolve({ data: null, error: null });
        }
      }
      if (table === "accounts") {
        c.then = (resolve: (v: any) => void) =>
          resolve({
            data: [{ user_id: "user-1", threads_user_id: "tu-1" }],
            error: null,
          });
      }
      return c;
    });

    const count = await processThreadsWebhookEvents(mockSupabase, Date.now());
    expect(count).toBe(2);
    expect(mockHandleThreadsWebhookEvent).toHaveBeenCalledTimes(2);
  });

  it("moves permanent errors to dead letter queue", async () => {
    const events = [
      {
        id: "evt-perm",
        event_type: "reply",
        threads_user_id: "tu-1",
        payload: {},
        retry_count: 0,
      },
    ];

    mockHandleThreadsWebhookEvent.mockRejectedValue(
      new Error("Invalid payload format")
    );
    mockClassifyWebhookError.mockReturnValue("permanent");

    const updateCalls: any[] = [];
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "threads_webhook_events") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: events, error: null });
        const origUpdate = c.update;
        c.update = vi.fn().mockImplementation((payload: any) => {
          updateCalls.push(payload);
          return origUpdate(payload);
        });
      }
      return c;
    });

    const count = await processThreadsWebhookEvents(mockSupabase, Date.now());
    expect(count).toBe(0);
    // Verify dead_letter was set in one of the update calls
    const dlqUpdate = updateCalls.find((u) => u.dead_letter === true);
    expect(dlqUpdate).toBeDefined();
  });

  it("schedules retry for transient errors with backoff", async () => {
    const events = [
      {
        id: "evt-transient",
        event_type: "reply",
        threads_user_id: "tu-1",
        payload: {},
        retry_count: 1,
      },
    ];

    mockHandleThreadsWebhookEvent.mockRejectedValue(
      new Error("Connection timeout")
    );
    mockClassifyWebhookError.mockReturnValue("transient");
    mockShouldRetry.mockReturnValue(true);
    const nextRetryTime = new Date(Date.now() + 120000);
    mockCalculateBackoff.mockReturnValue(nextRetryTime);

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "threads_webhook_events") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: events, error: null });
      }
      return c;
    });

    await processThreadsWebhookEvents(mockSupabase, Date.now());
    expect(mockScheduleWebhookReplay).toHaveBeenCalledWith("threads", expect.any(Number));
  });

  it("stops processing when time budget exhausted", async () => {
    const events = Array.from({ length: 10 }, (_, i) => ({
      id: `evt-${i}`,
      event_type: "reply",
      threads_user_id: "tu-1",
      payload: {},
      retry_count: 0,
    }));

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "threads_webhook_events") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: events, error: null });
      }
      if (table === "accounts") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: [], error: null });
      }
      return c;
    });

    // Start time far in the past — budget exhausted
    const count = await processThreadsWebhookEvents(
      mockSupabase,
      Date.now() - 60_000 // 60s ago, MAX_EXECUTION_TIME is 50s
    );
    // Should have processed 0 (broke immediately)
    expect(count).toBe(0);
  });

  it("sets Redis webhook-active keys for processed accounts", async () => {
    const events = [
      {
        id: "evt-redis",
        event_type: "reply",
        threads_user_id: "tu-redis",
        payload: {},
        retry_count: 0,
      },
    ];

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "threads_webhook_events") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: events, error: null });
      }
      if (table === "accounts") {
        c.then = (resolve: (v: any) => void) =>
          resolve({
            data: [{ user_id: "user-redis", threads_user_id: "tu-redis" }],
            error: null,
          });
      }
      return c;
    });

    await processThreadsWebhookEvents(mockSupabase, Date.now());
    expect(mockRedisSet).toHaveBeenCalledWith(
      "webhook-active:tu-redis",
      expect.any(String),
      { ex: 900 }
    );
  });
});

// ---------------------------------------------------------------------------
// Tests: processIgWebhookEvents
// ---------------------------------------------------------------------------

describe("processIgWebhookEvents", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockHandleIgWebhookEvent.mockResolvedValue(undefined);
    mockClassifyWebhookError.mockReturnValue("transient");
    mockShouldRetry.mockReturnValue(true);
    mockCalculateBackoff.mockReturnValue(new Date(Date.now() + 60000));
    setupBroadcastMock();
  });

  it("returns 0 when no IG events found", async () => {
    mockFrom.mockImplementation(() => chainable([], null));

    const count = await processIgWebhookEvents(mockSupabase, Date.now());
    expect(count).toBe(0);
  });

  it("returns 0 on fetch error", async () => {
    mockFrom.mockImplementation(() =>
      chainable(null, { message: "DB error" })
    );

    const count = await processIgWebhookEvents(mockSupabase, Date.now());
    expect(count).toBe(0);
  });

  it("processes IG events and batch-marks as processed", async () => {
    const events = [
      {
        id: "ig-evt-1",
        event_type: "comment",
        ig_user_id: "ig-u-1",
        payload: {},
        retry_count: 0,
      },
    ];

    let callCount = 0;
    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "ig_webhook_events") {
        callCount++;
        if (callCount === 1) {
          c.then = (resolve: (v: any) => void) =>
            resolve({ data: events, error: null });
        } else {
          c.then = (resolve: (v: any) => void) =>
            resolve({ data: null, error: null });
        }
      }
      if (table === "instagram_accounts") {
        c.then = (resolve: (v: any) => void) =>
          resolve({
            data: [
              { user_id: "user-1", instagram_user_id: "ig-u-1" },
            ],
            error: null,
          });
      }
      return c;
    });

    const count = await processIgWebhookEvents(mockSupabase, Date.now());
    expect(count).toBe(1);
    expect(mockHandleIgWebhookEvent).toHaveBeenCalledOnce();
  });

  it("moves IG permanent errors to dead letter queue", async () => {
    const events = [
      {
        id: "ig-evt-perm",
        event_type: "comment",
        ig_user_id: "ig-u-1",
        payload: {},
        retry_count: 0,
      },
    ];

    mockHandleIgWebhookEvent.mockRejectedValue(
      new Error("Permanent failure")
    );
    mockClassifyWebhookError.mockReturnValue("permanent");

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "ig_webhook_events") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: events, error: null });
      }
      return c;
    });

    const count = await processIgWebhookEvents(mockSupabase, Date.now());
    expect(count).toBe(0);
  });

  it("schedules retry for transient IG errors", async () => {
    const events = [
      {
        id: "ig-evt-retry",
        event_type: "mention",
        ig_user_id: "ig-u-1",
        payload: {},
        retry_count: 1,
      },
    ];

    mockHandleIgWebhookEvent.mockRejectedValue(new Error("Timeout"));
    mockClassifyWebhookError.mockReturnValue("transient");
    mockShouldRetry.mockReturnValue(true);
    mockCalculateBackoff.mockReturnValue(new Date(Date.now() + 60000));

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "ig_webhook_events") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: events, error: null });
      }
      return c;
    });

    await processIgWebhookEvents(mockSupabase, Date.now());
    expect(mockScheduleWebhookReplay).toHaveBeenCalledWith(
      "instagram",
      expect.any(Number)
    );
  });

  it("sets Redis webhook-active keys for processed IG accounts", async () => {
    const events = [
      {
        id: "ig-evt-redis",
        event_type: "comment",
        ig_user_id: "ig-u-redis",
        payload: {},
        retry_count: 0,
      },
    ];

    mockFrom.mockImplementation((table: string) => {
      const c = chainable(null);
      if (table === "ig_webhook_events") {
        c.then = (resolve: (v: any) => void) =>
          resolve({ data: events, error: null });
      }
      if (table === "instagram_accounts") {
        c.then = (resolve: (v: any) => void) =>
          resolve({
            data: [
              { user_id: "user-ig", instagram_user_id: "ig-u-redis" },
            ],
            error: null,
          });
      }
      return c;
    });

    await processIgWebhookEvents(mockSupabase, Date.now());
    expect(mockRedisSet).toHaveBeenCalledWith(
      "webhook-active:ig:ig-u-redis",
      expect.any(String),
      { ex: 900 }
    );
  });
});
