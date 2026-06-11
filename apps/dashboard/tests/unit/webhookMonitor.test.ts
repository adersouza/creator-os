/**
 * webhookMonitor — incrementAndCheckSigFailures
 *
 * Tests: counter increment, TTL on first entry, alert threshold (WARN / ERROR),
 * non-blocking Redis failure.
 *
 * vi.mock must be at module scope (Vitest hoists it). mockIncr / mockExpire
 * are reassigned per-test via .mockResolvedValue().
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { incrementAndCheckSigFailures } from "../../api/_lib/webhookMonitor";

const mockIncr = vi.fn();
const mockExpire = vi.fn().mockResolvedValue(1);

vi.mock("../../api/_lib/redis.js", () => ({
	getRedis: () => ({ incr: mockIncr, expire: mockExpire }),
}));

describe("webhookMonitor — signature failure counter and alert threshold", () => {
	let mockFetch: ReturnType<typeof vi.fn>;

	beforeEach(() => {
		mockIncr.mockReset();
		mockExpire.mockReset().mockResolvedValue(1);
		mockFetch = vi.fn().mockResolvedValue(new Response(null, { status: 200 }));
		vi.stubGlobal("fetch", mockFetch);
		process.env.DISCORD_ALERT_WEBHOOK_URL = "https://discord.test/webhook";
		process.env.WEBHOOK_SIG_FAILURE_THRESHOLD = "50";
	});

	afterEach(() => {
		vi.unstubAllGlobals();
		delete process.env.DISCORD_ALERT_WEBHOOK_URL;
		delete process.env.WEBHOOK_SIG_FAILURE_THRESHOLD;
	});

	it("increments the Redis counter on each failure", async () => {
		mockIncr.mockResolvedValue(1);
		await incrementAndCheckSigFailures("threads");
		expect(mockIncr).toHaveBeenCalledOnce();
		const key = mockIncr.mock.calls[0][0] as string;
		expect(key).toMatch(/^webhook:sig-fail:threads:/);
	});

	it("sets 2-hour TTL on first increment (count === 1)", async () => {
		mockIncr.mockResolvedValue(1);
		await incrementAndCheckSigFailures("threads");
		expect(mockExpire).toHaveBeenCalledOnce();
		expect(mockExpire.mock.calls[0][1]).toBe(7200);
	});

	it("does NOT set TTL on subsequent increments (count > 1)", async () => {
		mockIncr.mockResolvedValue(5);
		await incrementAndCheckSigFailures("threads");
		expect(mockExpire).not.toHaveBeenCalled();
	});

	it("does NOT fire alert below threshold", async () => {
		mockIncr.mockResolvedValue(10); // 10 < 50
		await incrementAndCheckSigFailures("instagram");
		expect(mockFetch).not.toHaveBeenCalled();
	});

	it("fires WARN alert at threshold (count === threshold)", async () => {
		mockIncr.mockResolvedValue(50);
		await incrementAndCheckSigFailures("threads");
		expect(mockFetch).toHaveBeenCalledOnce();
		const body = JSON.parse(
			(mockFetch.mock.calls[0][1] as RequestInit).body as string,
		);
		expect(body.embeds[0].title).toContain("threads");
		// WARN = orange (0xf39c12)
		expect(body.embeds[0].color).toBe(0xf39c12);
	});

	it("escalates to ERROR alert at 2× threshold (count === 100)", async () => {
		mockIncr.mockResolvedValue(100);
		await incrementAndCheckSigFailures("instagram");
		expect(mockFetch).toHaveBeenCalledOnce();
		const body = JSON.parse(
			(mockFetch.mock.calls[0][1] as RequestInit).body as string,
		);
		// ERROR = red (0xe74c3c)
		expect(body.embeds[0].color).toBe(0xe74c3c);
	});

	it("is non-blocking — Redis error does not throw or reject", async () => {
		mockIncr.mockRejectedValue(new Error("Redis unavailable"));
		await expect(
			incrementAndCheckSigFailures("threads"),
		).resolves.toBeUndefined();
	});
});
