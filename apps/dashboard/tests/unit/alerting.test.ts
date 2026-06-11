/**
 * Tests for api/_lib/alerting.ts
 *
 * Covers the Discord alerting system: alert levels, throttling, field sanitization,
 * workspace-scoped alerts, specialized helpers, and partial insights tracking.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

// Mock fetch globally
const mockFetch = vi.fn().mockResolvedValue({ ok: true });
vi.stubGlobal("fetch", mockFetch);

// Mock logger
vi.mock("../../api/_lib/logger.js", () => ({
  logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

// Mock Supabase for workspace webhook lookup
const mockSupabase = {
  from: vi.fn().mockReturnValue({
    select: vi.fn().mockReturnValue({
      eq: vi.fn().mockReturnValue({
        maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
      }),
    }),
  }),
};
vi.mock("../../api/_lib/supabase.js", () => ({
  getSupabase: () => mockSupabase,
  getSupabaseAny: () => mockSupabase,
}));

import {
  alert,
  AlertLevel,
  alertWorkspace,
  alertCronFailure,
  alertTokenRefreshFailure,
  alertDeadLetterThreshold,
  trackInsightsResponse,
  flushPartialInsightsAlert,
  _resetAlertingForTests,
} from "@/api/_lib/alerting";

describe("alerting", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    _resetAlertingForTests();
    process.env.DISCORD_ALERT_WEBHOOK_URL = "https://discord.com/api/webhooks/test";
  });

  afterEach(() => {
    delete process.env.DISCORD_ALERT_WEBHOOK_URL;
  });

  // ============================================================
  // Core alert()
  // ============================================================
  describe("alert()", () => {
    it("sends a Discord webhook with correct embed structure", async () => {
      await alert(AlertLevel.ERROR, "Test alert", { key: "value" });

      expect(mockFetch).toHaveBeenCalledTimes(1);
      const [url, opts] = mockFetch.mock.calls[0];
      expect(url).toBe("https://discord.com/api/webhooks/test");
      expect(opts.method).toBe("POST");

      const payload = JSON.parse(opts.body);
      expect(payload.embeds).toHaveLength(1);
      expect(payload.embeds[0].title).toContain("Test alert");
      expect(payload.embeds[0].color).toBe(0xe74c3c); // Red for ERROR
      expect(payload.embeds[0].footer.text).toBe("Juno33 Backend");
    });

    it("skips when DISCORD_ALERT_WEBHOOK_URL is not set", async () => {
      delete process.env.DISCORD_ALERT_WEBHOOK_URL;
      await alert(AlertLevel.INFO, "Should not send");
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("uses correct colors for each level", async () => {
      const levels = [
        { level: AlertLevel.INFO, color: 0x3498db },
        { level: AlertLevel.WARN, color: 0xf39c12 },
        { level: AlertLevel.ERROR, color: 0xe74c3c },
        { level: AlertLevel.CRITICAL, color: 0x9b59b6 },
      ];

      for (const { level, color } of levels) {
        _resetAlertingForTests();
        mockFetch.mockClear();
        await alert(level, `${level} alert`);
        const payload = JSON.parse(mockFetch.mock.calls[0][1].body);
        expect(payload.embeds[0].color).toBe(color);
      }
    });

    it("includes embed fields from options", async () => {
      await alert(AlertLevel.WARN, "With fields", {
        job: "sync",
        duration: "150ms",
      });

      const payload = JSON.parse(mockFetch.mock.calls[0][1].body);
      const fields = payload.embeds[0].fields;
      expect(fields).toHaveLength(2);
      expect(fields[0].name).toBe("job");
      expect(fields[0].value).toBe("sync");
    });

    it("filters out undefined option values", async () => {
      await alert(AlertLevel.INFO, "Partial", {
        present: "yes",
        missing: undefined,
      });

      const payload = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(payload.embeds[0].fields).toHaveLength(1);
    });

    it("never throws even when fetch fails", async () => {
      mockFetch.mockRejectedValueOnce(new Error("Network failure"));
      await expect(
        alert(AlertLevel.ERROR, "Should not throw")
      ).resolves.toBeUndefined();
    });
  });

  // ============================================================
  // Throttling
  // ============================================================
  describe("throttling", () => {
    it("throttles duplicate alerts within 5 minutes", async () => {
      await alert(AlertLevel.WARN, "Duplicate test");
      await alert(AlertLevel.WARN, "Duplicate test");
      await alert(AlertLevel.WARN, "Duplicate test");

      // Only the first call should go through
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it("allows different alert titles through", async () => {
      await alert(AlertLevel.WARN, "Alert A");
      await alert(AlertLevel.WARN, "Alert B");

      expect(mockFetch).toHaveBeenCalledTimes(2);
    });

    it("differentiates by level + title for throttling", async () => {
      await alert(AlertLevel.WARN, "Same title");
      await alert(AlertLevel.ERROR, "Same title");

      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });

  // ============================================================
  // Field Sanitization
  // ============================================================
  describe("field sanitization", () => {
    it("strips stack traces from field values", async () => {
      await alert(AlertLevel.ERROR, "Error", {
        error: "Something failed\n    at Object.run (/app/handler.ts:42:5)\n    at process.next",
      });

      const payload = JSON.parse(mockFetch.mock.calls[0][1].body);
      const errorField = payload.embeds[0].fields.find(
        (f: any) => f.name === "error"
      );
      expect(errorField.value).not.toContain("at Object.run");
      expect(errorField.value).toContain("Something failed");
    });

    it("redacts username fields", async () => {
      await alert(AlertLevel.WARN, "Token issue", {
        username: "secretuser",
      });

      const payload = JSON.parse(mockFetch.mock.calls[0][1].body);
      const userField = payload.embeds[0].fields.find(
        (f: any) => f.name === "username"
      );
      expect(userField.value).toBe("s***r");
    });

    it("redacts email fields", async () => {
      await alert(AlertLevel.WARN, "Email issue", {
        email: "test@example.com",
      });

      const payload = JSON.parse(mockFetch.mock.calls[0][1].body);
      const emailField = payload.embeds[0].fields.find(
        (f: any) => f.name === "email"
      );
      expect(emailField.value).toBe("t***m");
    });

    it("truncates long field values to 1024 chars", async () => {
      const longValue = "x".repeat(2000);
      await alert(AlertLevel.INFO, "Long value", { data: longValue });

      const payload = JSON.parse(mockFetch.mock.calls[0][1].body);
      const field = payload.embeds[0].fields[0];
      expect(field.value.length).toBeLessThanOrEqual(1024);
    });

    it("sets inline=true for short values", async () => {
      await alert(AlertLevel.INFO, "Short", { status: "ok" });

      const payload = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(payload.embeds[0].fields[0].inline).toBe(true);
    });
  });

  // ============================================================
  // Specialized helpers
  // ============================================================
  describe("alertCronFailure()", () => {
    it("sends an ERROR-level alert with job name and duration", async () => {
      await alertCronFailure("sync-orchestrator", "DB timeout", 12500);

      const payload = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(payload.embeds[0].title).toContain("Cron job failed: sync-orchestrator");
      expect(payload.embeds[0].color).toBe(0xe74c3c);
      const fields = payload.embeds[0].fields;
      expect(fields.find((f: any) => f.name === "duration")?.value).toBe("12500ms");
    });
  });

  describe("alertTokenRefreshFailure()", () => {
    it("sends a WARN-level alert with platform and redacted username", async () => {
      await alertTokenRefreshFailure("threads", "myuser", "Token expired");

      const payload = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(payload.embeds[0].title).toContain("Token refresh failed");
      expect(payload.embeds[0].color).toBe(0xf39c12);
    });
  });

  describe("alertDeadLetterThreshold()", () => {
    it("includes table name and action in fields", async () => {
      await alertDeadLetterThreshold(25, "auto_post_queue");

      const payload = JSON.parse(mockFetch.mock.calls[0][1].body);
      const fields = payload.embeds[0].fields;
      expect(fields.find((f: any) => f.name === "table")?.value).toBe("auto_post_queue");
      expect(fields.find((f: any) => f.name === "action")?.value).toContain("/api/admin/dead-letters");
    });
  });

  // ============================================================
  // Workspace-scoped alerts
  // ============================================================
  describe("alertWorkspace()", () => {
    it("falls back to global alert when workspace has no webhook", async () => {
      await alertWorkspace("ws-1", AlertLevel.WARN, "Workspace alert");

      // Should call global webhook
      expect(mockFetch).toHaveBeenCalledTimes(1);
      const payload = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(payload.embeds[0].fields.find((f: any) => f.name === "workspace")?.value).toBe("ws-1");
    });

    it("uses workspace webhook when available", async () => {
      mockSupabase.from.mockReturnValueOnce({
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: { discord_webhook_url: "https://discord.com/api/webhooks/workspace" },
              error: null,
            }),
          }),
        }),
      });

      await alertWorkspace("ws-1", AlertLevel.INFO, "Workspace specific");

      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(mockFetch.mock.calls[0][0]).toBe("https://discord.com/api/webhooks/workspace");
    });

    it("mirrors to global when mirrorToGlobal is true", async () => {
      mockSupabase.from.mockReturnValueOnce({
        select: vi.fn().mockReturnValue({
          eq: vi.fn().mockReturnValue({
            maybeSingle: vi.fn().mockResolvedValue({
              data: { discord_webhook_url: "https://discord.com/api/webhooks/workspace" },
              error: null,
            }),
          }),
        }),
      });

      await alertWorkspace("ws-1", AlertLevel.WARN, "Mirror test", {}, { mirrorToGlobal: true });

      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });

  // ============================================================
  // Partial Insights Tracking
  // ============================================================
  describe("partial insights tracking", () => {
    it("does not alert when no accounts are tracked", async () => {
      await flushPartialInsightsAlert();
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("does not alert when all accounts are healthy", async () => {
      trackInsightsResponse(false);
      trackInsightsResponse(false);
      trackInsightsResponse(false);
      await flushPartialInsightsAlert();
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("does not alert when partial rate is below 50%", async () => {
      trackInsightsResponse(true, ["views"]);
      trackInsightsResponse(false);
      trackInsightsResponse(false);
      trackInsightsResponse(false);
      await flushPartialInsightsAlert();
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("does not alert when only follower_count is missing (expected optional)", async () => {
      trackInsightsResponse(true, ["follower_count"]);
      trackInsightsResponse(true, ["follower_count"]);
      trackInsightsResponse(true, ["follower_count"]);
      await flushPartialInsightsAlert();
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("alerts when >50% have unexpected missing metrics and sample >= 3", async () => {
      trackInsightsResponse(true, ["impressions", "reach"]);
      trackInsightsResponse(true, ["impressions"]);
      trackInsightsResponse(false);
      // 2/3 = 67% > 50%, and unexpected metrics
      await flushPartialInsightsAlert();
      expect(mockFetch).toHaveBeenCalledTimes(1);
      const payload = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(payload.embeds[0].title).toContain("contract change");
    });

    it("does not alert with fewer than 3 total accounts", async () => {
      trackInsightsResponse(true, ["views"]);
      trackInsightsResponse(true, ["views"]);
      // 2/2 = 100% but sample too small
      await flushPartialInsightsAlert();
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it("resets accumulator after flush", async () => {
      trackInsightsResponse(true, ["views"]);
      trackInsightsResponse(true, ["views"]);
      trackInsightsResponse(true, ["views"]);
      await flushPartialInsightsAlert();
      mockFetch.mockClear();

      // Second flush should have no data
      await flushPartialInsightsAlert();
      expect(mockFetch).not.toHaveBeenCalled();
    });
  });
});
