/**
 * Tests for api/_lib/deliverNotification.ts
 *
 * Validates that deliverNotification routes critical notification types
 * to Discord via alerting.ts and silently ignores non-critical types.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";

// Mock the alerting module
const mockAlert = vi.fn().mockResolvedValue(undefined);
vi.mock("../../api/_lib/alerting.js", () => ({
  alert: mockAlert,
  AlertLevel: {
    INFO: "info",
    WARN: "warn",
    ERROR: "error",
    CRITICAL: "critical",
  },
}));

// Mock logger
vi.mock("../../api/_lib/logger.js", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

import { deliverNotification } from "@/api/_lib/deliverNotification";

describe("deliverNotification", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const DISCORD_TYPES = [
    "post_failed",
    "token_expiring",
    "token_reauth_needed",
    "account_disconnected",
    "account_suspended",
    "agent_circuit_breaker",
    "queue_low",
    "post_rate_limited",
  ];

  it.each(DISCORD_TYPES)(
    "sends Discord alert for critical type: %s",
    async (type) => {
      await deliverNotification({
        userId: "user-1",
        type,
        title: "Test alert",
        message: "Something happened",
      });

      expect(mockAlert).toHaveBeenCalledTimes(1);
      expect(mockAlert).toHaveBeenCalledWith(
        "warn",
        "Test alert",
        expect.objectContaining({
          type,
          detail: "Something happened",
        })
      );
    }
  );

  it("does not send Discord alert for non-critical types", async () => {
    const nonCritical = [
      "post_published",
      "follower_milestone",
      "report_ready",
      "engagement_spike",
      "feature_update",
    ];

    for (const type of nonCritical) {
      await deliverNotification({
        userId: "user-1",
        type,
        title: "Not critical",
        message: "Should be ignored by Discord",
      });
    }

    expect(mockAlert).not.toHaveBeenCalled();
  });

  it("truncates message to 500 chars for Discord detail field", async () => {
    const longMessage = "x".repeat(1000);

    await deliverNotification({
      userId: "user-1",
      type: "post_failed",
      title: "Long message",
      message: longMessage,
    });

    const detailArg = mockAlert.mock.calls[0][2]?.detail;
    expect(detailArg.length).toBe(500);
  });

  it("never throws even when alerting fails", async () => {
    mockAlert.mockRejectedValueOnce(new Error("Discord down"));

    await expect(
      deliverNotification({
        userId: "user-1",
        type: "post_failed",
        title: "Fail gracefully",
        message: "Should not throw",
      })
    ).resolves.toBeUndefined();
  });

  it("passes optional data through without error", async () => {
    await deliverNotification({
      userId: "user-1",
      type: "post_failed",
      title: "With data",
      message: "Has extra",
      data: { postId: "p-1", accountId: "a-1" },
    });

    expect(mockAlert).toHaveBeenCalledTimes(1);
    expect(mockAlert).toHaveBeenCalledWith(
      "warn",
      "With data",
      expect.objectContaining({
        postId: "p-1",
        accountId: "a-1",
      })
    );
  });
});
