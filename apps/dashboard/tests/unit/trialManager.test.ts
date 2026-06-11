import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ============================================================================
// Setup mocks
// ============================================================================

const mockCreateNotification = vi.fn().mockResolvedValue(undefined);
vi.mock("../../api/_lib/createNotification.js", () => ({
  createNotification: (...args: any[]) => mockCreateNotification(...args),
}));

vi.mock("../../api/_lib/logger.js", () => ({
  logger: {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

// We need a more targeted mock for the DB queries in expireTrial
function createTrialDbMock(opts: {
  aiCount?: number;
  postCount?: number;
  updateRows?: any[];
}) {
  const mock: any = {};

  mock.from = vi.fn().mockImplementation((table: string) => {
    if (table === "feature_usage") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            in: vi.fn().mockResolvedValue({ count: opts.aiCount ?? 0 }),
          }),
        }),
      };
    }
    if (table === "posts") {
      return {
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            eq: vi.fn().mockResolvedValue({ count: opts.postCount ?? 0 }),
          }),
        }),
      };
    }
    if (table === "profiles") {
      // This is the update call
      const chain: any = {};
      chain.update = vi.fn().mockReturnValue(chain);
      chain.eq = vi.fn().mockReturnValue(chain);
      chain.select = vi
        .fn()
        .mockResolvedValue({ data: opts.updateRows ?? [{ id: "user-1" }] });
      return chain;
    }
    return mock;
  });

  return mock;
}

let mockDb: any;

vi.mock("../../api/_lib/supabase.js", () => ({
  getSupabase: () => mockDb,
}));

const { isTrialActive, getTrialDaysRemaining, expireTrial, startTrial } =
  await import("../../api/_lib/trialManager.js");

// ============================================================================
// isTrialActive
// ============================================================================

describe("isTrialActive", () => {
  it("returns true when trial_ends_at is in the future and not used", () => {
    const futureDate = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);
    expect(
      isTrialActive({
        trial_ends_at: futureDate.toISOString(),
        trial_used: false,
        has_used_trial: false,
      })
    ).toBe(true);
  });

  it("returns false when trial_ends_at is null", () => {
    expect(isTrialActive({ trial_ends_at: null })).toBe(false);
  });

  it("returns false when trial_ends_at is undefined", () => {
    expect(isTrialActive({})).toBe(false);
  });

  it("returns false when trial_ends_at is in the past", () => {
    const pastDate = new Date(Date.now() - 1000);
    expect(
      isTrialActive({
        trial_ends_at: pastDate.toISOString(),
        trial_used: false,
      })
    ).toBe(false);
  });

  it("returns false when trial_used is true (even if end date is future)", () => {
    const futureDate = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);
    expect(
      isTrialActive({
        trial_ends_at: futureDate.toISOString(),
        trial_used: true,
      })
    ).toBe(false);
  });

  it("returns false when has_used_trial is true (even if end date is future)", () => {
    const futureDate = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);
    expect(
      isTrialActive({
        trial_ends_at: futureDate.toISOString(),
        has_used_trial: true,
      })
    ).toBe(false);
  });

  it("returns true at exactly 1 second before expiry", () => {
    const almostExpired = new Date(Date.now() + 1000);
    expect(
      isTrialActive({
        trial_ends_at: almostExpired.toISOString(),
        trial_used: false,
        has_used_trial: false,
      })
    ).toBe(true);
  });
});

// ============================================================================
// getTrialDaysRemaining
// ============================================================================

describe("getTrialDaysRemaining", () => {
  it("returns 0 when trial_ends_at is null", () => {
    expect(getTrialDaysRemaining({ trial_ends_at: null })).toBe(0);
  });

  it("returns 0 when trial_ends_at is undefined", () => {
    expect(getTrialDaysRemaining({})).toBe(0);
  });

  it("returns 0 when trial has expired", () => {
    const pastDate = new Date(Date.now() - 48 * 60 * 60 * 1000);
    expect(getTrialDaysRemaining({ trial_ends_at: pastDate.toISOString() })).toBe(
      0
    );
  });

  it("returns 14 for a brand new trial", () => {
    const futureDate = new Date(Date.now() + 14 * 24 * 60 * 60 * 1000);
    expect(
      getTrialDaysRemaining({ trial_ends_at: futureDate.toISOString() })
    ).toBe(14);
  });

  it("returns 1 when less than 24h remain (ceil rounds up)", () => {
    const futureDate = new Date(Date.now() + 1 * 60 * 60 * 1000); // 1 hour
    expect(
      getTrialDaysRemaining({ trial_ends_at: futureDate.toISOString() })
    ).toBe(1);
  });

  it("returns 7 at exactly 7 days", () => {
    const futureDate = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);
    expect(
      getTrialDaysRemaining({ trial_ends_at: futureDate.toISOString() })
    ).toBe(7);
  });

  it("never returns negative (clamped to 0)", () => {
    const longPast = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000);
    expect(
      getTrialDaysRemaining({ trial_ends_at: longPast.toISOString() })
    ).toBe(0);
  });
});

// ============================================================================
// expireTrial
// ============================================================================

describe("expireTrial", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("downgrades user to free and marks trial as used", async () => {
    mockDb = createTrialDbMock({
      aiCount: 5,
      postCount: 3,
      updateRows: [{ id: "user-1" }],
    });

    await expireTrial("user-1");

    // Check notification was created
    expect(mockCreateNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        userId: "user-1",
        type: "trial_expired",
        title: "Your Pro trial has ended",
      })
    );

    // Notification message should contain usage summary
    const notifCall = mockCreateNotification.mock.calls[0][0];
    expect(notifCall.message).toContain("AI insights 5 times");
    expect(notifCall.message).toContain("scheduled 3 posts");
  });

  it("sends generic message when user had no usage", async () => {
    mockDb = createTrialDbMock({
      aiCount: 0,
      postCount: 0,
      updateRows: [{ id: "user-2" }],
    });

    await expireTrial("user-2");

    const notifCall = mockCreateNotification.mock.calls[0][0];
    expect(notifCall.message).not.toContain("During your 14-day trial");
    expect(notifCall.message).toContain("Upgrade to Pro");
  });

  it("is idempotent — no-op when trial already expired (atomic guard)", async () => {
    mockDb = createTrialDbMock({
      aiCount: 0,
      postCount: 0,
      updateRows: [], // No rows matched — trial_used was already true
    });

    await expireTrial("user-already-expired");

    // Should NOT create a notification for an already-expired trial
    expect(mockCreateNotification).not.toHaveBeenCalled();
  });

  it("rethrows when DB update throws", async () => {
    mockDb = {
      from: vi.fn().mockImplementation((table: string) => {
        if (table === "feature_usage" || table === "posts") {
          return {
            select: vi.fn().mockReturnValue({
              eq: vi.fn().mockReturnValue({
                in: vi.fn().mockResolvedValue({ count: 0 }),
                eq: vi.fn().mockResolvedValue({ count: 0 }),
              }),
            }),
          };
        }
        // profiles table — throw
        throw new Error("DB connection lost");
      }),
    };

    await expect(expireTrial("user-crash")).rejects.toThrow(
      "DB connection lost"
    );
  });

  it("still expires even if feature_usage query fails", async () => {
    // Feature usage query throws, but expireTrial catches it and continues
    mockDb = {
      from: vi.fn().mockImplementation((table: string) => {
        if (table === "feature_usage") {
          return {
            select: vi.fn().mockReturnValue({
              eq: vi.fn().mockReturnValue({
                in: vi.fn().mockRejectedValue(new Error("table missing")),
              }),
            }),
          };
        }
        if (table === "posts") {
          return {
            select: vi.fn().mockReturnValue({
              eq: vi.fn().mockReturnValue({
                eq: vi.fn().mockResolvedValue({ count: 0 }),
              }),
            }),
          };
        }
        if (table === "profiles") {
          const chain: any = {};
          chain.update = vi.fn().mockReturnValue(chain);
          chain.eq = vi.fn().mockReturnValue(chain);
          chain.select = vi
            .fn()
            .mockResolvedValue({ data: [{ id: "user-1" }] });
          return chain;
        }
      }),
    };

    await expireTrial("user-1");
    expect(mockCreateNotification).toHaveBeenCalled();
  });
});

// ============================================================================
// startTrial
// ============================================================================

describe("startTrial", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("sets trial for 14 days from now", async () => {
    const now = new Date("2026-04-15T12:00:00.000Z");
    vi.setSystemTime(now);

    const updateMock = vi.fn().mockReturnValue({
      eq: vi.fn().mockResolvedValue({ data: null, error: null }),
    });

    mockDb = {
      from: vi.fn().mockReturnValue({
        update: updateMock,
      }),
    };

    await startTrial("user-new");

    expect(updateMock).toHaveBeenCalledWith(
      expect.objectContaining({
        subscription_tier: "pro",
        trial_used: false,
        has_used_trial: true,
      })
    );

    const updateArg = updateMock.mock.calls[0][0];
    const startedAt = new Date(updateArg.trial_started_at);
    const endsAt = new Date(updateArg.trial_ends_at);

    // Verify 14-day duration
    const diffMs = endsAt.getTime() - startedAt.getTime();
    const diffDays = diffMs / (1000 * 60 * 60 * 24);
    expect(diffDays).toBe(14);

    // Verify started at is "now"
    expect(startedAt.toISOString()).toBe("2026-04-15T12:00:00.000Z");
    expect(endsAt.toISOString()).toBe("2026-04-29T12:00:00.000Z");
  });

  it("sets has_used_trial=true immediately (cannot re-trial)", async () => {
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));

    const updateMock = vi.fn().mockReturnValue({
      eq: vi.fn().mockResolvedValue({ data: null, error: null }),
    });

    mockDb = {
      from: vi.fn().mockReturnValue({
        update: updateMock,
      }),
    };

    await startTrial("user-trial");

    const updateArg = updateMock.mock.calls[0][0];
    expect(updateArg.has_used_trial).toBe(true);
    expect(updateArg.trial_used).toBe(false); // Not used yet
  });
});
