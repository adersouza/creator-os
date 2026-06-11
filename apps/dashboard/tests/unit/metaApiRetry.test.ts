/**
 * Tests for withRetry() and isRetryableMetaError() from retryUtils.ts
 *
 * Validates retry behavior for Meta API error scenarios:
 * - Success on first attempt (no retry)
 * - Transient errors (500, 503) trigger retries
 * - Rate limits (429) with Retry-After header
 * - Non-retryable errors (400, 403) throw immediately
 * - Max retries exhausted
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

// Mock the logger to suppress output during tests
vi.mock("../../api/_lib/logger.js", () => ({
	logger: {
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

import { withRetry, isRetryableMetaError } from "../../api/_lib/retryUtils";

describe("withRetry", () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it("succeeds on first attempt — no retry", async () => {
		const fn = vi.fn().mockResolvedValue("ok");
		const result = await withRetry(fn, { maxRetries: 3 });
		expect(result).toBe("ok");
		expect(fn).toHaveBeenCalledTimes(1);
	});

	it("retries on 500 and succeeds on 2nd attempt", async () => {
		const fn = vi
			.fn()
			.mockRejectedValueOnce({ status: 500, message: "Internal Server Error" })
			.mockResolvedValue("recovered");

		const promise = withRetry(fn, { maxRetries: 3, baseDelayMs: 100 });
		// Advance timers to allow retry delay to pass
		await vi.runAllTimersAsync();
		const result = await promise;

		expect(result).toBe("recovered");
		expect(fn).toHaveBeenCalledTimes(2);
	});

	it("respects Retry-After header on 429", async () => {
		const error429 = {
			status: 429,
			message: "Too Many Requests",
			headers: { "retry-after": "2" },
		};
		const fn = vi
			.fn()
			.mockRejectedValueOnce(error429)
			.mockResolvedValue("ok after wait");

		const promise = withRetry(fn, { maxRetries: 3, baseDelayMs: 100 });
		await vi.runAllTimersAsync();
		const result = await promise;

		expect(result).toBe("ok after wait");
		expect(fn).toHaveBeenCalledTimes(2);
	});

	it("throws after max retries exhausted with 503", async () => {
		const error503 = { status: 503, message: "Service Unavailable" };
		const fn = vi.fn().mockRejectedValue(error503);

		const promise = withRetry(fn, { maxRetries: 3, baseDelayMs: 50 }).catch(
			(e) => e,
		);
		await vi.runAllTimersAsync();

		const result = await promise;
		expect(result).toEqual(error503);
		// 1 initial + 3 retries = 4 calls
		expect(fn).toHaveBeenCalledTimes(4);
	});

	it("throws immediately on non-retryable 400 error", async () => {
		const error400 = { status: 400, message: "Bad Request" };
		const fn = vi.fn().mockRejectedValue(error400);

		await expect(
			withRetry(fn, { maxRetries: 3, baseDelayMs: 50 }),
		).rejects.toEqual(error400);
		// Should not retry — only 1 call
		expect(fn).toHaveBeenCalledTimes(1);
	});
});

describe("isRetryableMetaError", () => {
	it("returns true for 429 (rate limit)", () => {
		expect(isRetryableMetaError(429)).toBe(true);
	});

	it("returns true for 500 (server error)", () => {
		expect(isRetryableMetaError(500)).toBe(true);
	});

	it("returns true for 502 (bad gateway)", () => {
		expect(isRetryableMetaError(502)).toBe(true);
	});

	it("returns false for 400 (bad request)", () => {
		expect(isRetryableMetaError(400)).toBe(false);
	});

	it("returns false for 403 (forbidden)", () => {
		expect(isRetryableMetaError(403)).toBe(false);
	});

	it("returns true for error object with status 500", () => {
		expect(isRetryableMetaError({ status: 500 })).toBe(true);
	});

	it("returns true for Meta transient subcode 2207026", () => {
		expect(
			isRetryableMetaError(200, { error: { error_subcode: 2207026 } }),
		).toBe(true);
	});
});
