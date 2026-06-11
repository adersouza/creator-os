import { describe, expect, it, vi } from "vitest";
import {
	API_MAX_RETRIES,
	calculateBackoff,
	isRetryableMetaError,
	MAX_RETRIES,
	shouldRetry,
	withRetry,
} from "../retryUtils.js";

// Silence logger output during tests
vi.mock("../logger.js", () => ({
	logger: {
		debug: vi.fn(),
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
	},
}));

describe("calculateBackoff", () => {
	it("returns exponentially increasing delays", () => {
		const t0 = calculateBackoff(0).getTime() - Date.now();
		const t1 = calculateBackoff(1).getTime() - Date.now();
		const t2 = calculateBackoff(2).getTime() - Date.now();
		// Base delays: 1000, 2000, 4000 (plus up to 25% jitter)
		expect(t0).toBeGreaterThanOrEqual(999);
		expect(t1).toBeGreaterThan(t0 * 0.9);
		expect(t2).toBeGreaterThan(t1 * 0.9);
	});

	it("returns a Date object", () => {
		expect(calculateBackoff(0)).toBeInstanceOf(Date);
	});

	it("computes correct delay for retryCount 0 with default base (1000ms)", () => {
		const delay = calculateBackoff(0).getTime() - Date.now();
		// 1000 * 2^0 = 1000ms base + up to 25% jitter (0-250)
		expect(delay).toBeGreaterThanOrEqual(999);
		expect(delay).toBeLessThanOrEqual(1300);
	});

	it("computes correct delay for retryCount 1 (2000ms base)", () => {
		const delay = calculateBackoff(1).getTime() - Date.now();
		// 1000 * 2^1 = 2000ms + up to 25% jitter (0-500)
		expect(delay).toBeGreaterThanOrEqual(1999);
		expect(delay).toBeLessThanOrEqual(2600);
	});

	it("computes correct delay for retryCount 2 (4000ms base)", () => {
		const delay = calculateBackoff(2).getTime() - Date.now();
		// 1000 * 2^2 = 4000ms + up to 25% jitter (0-1000)
		expect(delay).toBeGreaterThanOrEqual(3999);
		expect(delay).toBeLessThanOrEqual(5100);
	});

	it("caps base at 30000ms", () => {
		const delay = calculateBackoff(20).getTime() - Date.now();
		// min(1000 * 2^20, 30000) = 30000 + up to 25% jitter (0-7500)
		expect(delay).toBeGreaterThanOrEqual(29999);
		expect(delay).toBeLessThanOrEqual(37600);
	});

	it("caps high retryCount at same level as moderate retryCount", () => {
		// Both should cap at 30000 base
		const d10 = calculateBackoff(10).getTime() - Date.now();
		const d100 = calculateBackoff(100).getTime() - Date.now();
		// Both capped at 30000 base with up to 25% jitter
		expect(d10).toBeGreaterThanOrEqual(29999);
		expect(d100).toBeGreaterThanOrEqual(29999);
		expect(d10).toBeLessThanOrEqual(37600);
		expect(d100).toBeLessThanOrEqual(37600);
	});

	it("uses custom base delay", () => {
		const delay = calculateBackoff(0, 5000).getTime() - Date.now();
		// 5000 * 2^0 = 5000 + up to 25% jitter (0-1250)
		expect(delay).toBeGreaterThanOrEqual(4999);
		expect(delay).toBeLessThanOrEqual(6300);
	});

	it("custom base delay also grows exponentially", () => {
		const d0 = calculateBackoff(0, 1000).getTime() - Date.now();
		const d1 = calculateBackoff(1, 1000).getTime() - Date.now();
		const d2 = calculateBackoff(2, 1000).getTime() - Date.now();
		// 1000, 2000, 4000 + up to 25% jitter
		expect(d0).toBeGreaterThanOrEqual(999);
		expect(d0).toBeLessThan(1300);
		expect(d1).toBeGreaterThanOrEqual(1999);
		expect(d1).toBeLessThan(2600);
		expect(d2).toBeGreaterThanOrEqual(3999);
		expect(d2).toBeLessThan(5100);
	});
});

describe("shouldRetry", () => {
	it("returns true when retryCount is 0", () => {
		expect(shouldRetry(0)).toBe(true);
	});

	it("returns true for all counts below MAX_RETRIES", () => {
		for (let i = 0; i < MAX_RETRIES; i++) {
			expect(shouldRetry(i)).toBe(true);
		}
	});

	it("returns false at MAX_RETRIES", () => {
		expect(shouldRetry(MAX_RETRIES)).toBe(false);
	});

	it("returns false above MAX_RETRIES", () => {
		expect(shouldRetry(MAX_RETRIES + 1)).toBe(false);
		expect(shouldRetry(100)).toBe(false);
	});

	it("exports MAX_RETRIES as 3", () => {
		expect(MAX_RETRIES).toBe(3);
	});

	it("exports API_MAX_RETRIES as 5", () => {
		expect(API_MAX_RETRIES).toBe(5);
	});
});

describe("isRetryableMetaError", () => {
	describe("retryable HTTP status codes", () => {
		it.each([
			429, 500, 502, 503, 504,
		])("returns true for status %d", (status) => {
			expect(isRetryableMetaError(status)).toBe(true);
		});
	});

	describe("non-retryable HTTP status codes", () => {
		it.each([
			200, 201, 301, 400, 401, 403, 404, 405, 422,
		])("returns false for status %d with no body", (status) => {
			expect(isRetryableMetaError(status)).toBe(false);
		});
	});

	describe("retryable Meta subcodes", () => {
		it.each([2207026, 2207051])("returns true for subcode %d", (subcode) => {
			expect(
				isRetryableMetaError(400, {
					error: { error_subcode: subcode },
				}),
			).toBe(true);
		});
	});

	describe("retryable error codes", () => {
		it("returns true for code 429", () => {
			expect(isRetryableMetaError(400, { error: { code: 429 } })).toBe(true);
		});

		it("returns true for code >= 500", () => {
			expect(isRetryableMetaError(400, { error: { code: 500 } })).toBe(true);
			expect(isRetryableMetaError(400, { error: { code: 503 } })).toBe(true);
		});
	});

	describe("non-retryable Meta error codes", () => {
		it.each([
			[190, "invalid access token"],
			[100, "invalid parameter"],
			[10, "permission error"],
			[200, "permissions error"],
		])("returns false for code %d (%s)", (code) => {
			expect(isRetryableMetaError(400, { error: { code } })).toBe(false);
		});
	});

	describe("edge cases", () => {
		it("returns false when body is undefined", () => {
			expect(isRetryableMetaError(400)).toBe(false);
		});

		it("returns false when body has no error field", () => {
			expect(isRetryableMetaError(400, {})).toBe(false);
		});

		it("returns false when error has no code and no retryable subcode", () => {
			expect(isRetryableMetaError(400, { error: {} })).toBe(false);
		});

		it("retryable HTTP status trumps non-retryable body code", () => {
			expect(isRetryableMetaError(429, { error: { code: 190 } })).toBe(true);
		});
	});
});

describe("withRetry", () => {
	it("returns on first success without retrying", async () => {
		const fn = vi.fn().mockResolvedValue("ok");
		const res = await withRetry(fn, { maxRetries: 3, baseDelayMs: 1 });
		expect(res).toBe("ok");
		expect(fn).toHaveBeenCalledTimes(1);
	});

	it("retries on thrown error then succeeds", async () => {
		const fn = vi
			.fn()
			.mockRejectedValueOnce(new Error("ECONNRESET"))
			.mockResolvedValue("ok");
		const res = await withRetry(fn, { maxRetries: 3, baseDelayMs: 1 });
		expect(res).toBe("ok");
		expect(fn).toHaveBeenCalledTimes(2);
	});

	it("throws after exhausting retries on errors", async () => {
		const fn = vi.fn().mockRejectedValue(new Error("timeout"));
		await expect(
			withRetry(fn, { maxRetries: 2, baseDelayMs: 1 }),
		).rejects.toThrow("timeout");
		expect(fn).toHaveBeenCalledTimes(3); // initial + 2 retries
	});

	it("uses default maxRetries (3) when not specified", async () => {
		const fn = vi.fn().mockRejectedValue(new Error("network fail"));
		await expect(withRetry(fn, { baseDelayMs: 1 })).rejects.toThrow(
			"network fail",
		);
		// Default maxRetries=3 → 1 initial + 3 retries = 4 calls
		expect(fn).toHaveBeenCalledTimes(4);
	});

	it("does not retry non-retryable errors (status < 500 and != 429)", async () => {
		const err = Object.assign(new Error("bad request"), { status: 400 });
		const fn = vi.fn().mockRejectedValue(err);
		await expect(
			withRetry(fn, { maxRetries: 3, baseDelayMs: 1 }),
		).rejects.toThrow("bad request");
		expect(fn).toHaveBeenCalledTimes(1);
	});

	it("retries on error with status 429", async () => {
		const err429 = Object.assign(new Error("rate limited"), { status: 429 });
		const fn = vi.fn().mockRejectedValueOnce(err429).mockResolvedValue("ok");
		const res = await withRetry(fn, { maxRetries: 3, baseDelayMs: 1 });
		expect(res).toBe("ok");
		expect(fn).toHaveBeenCalledTimes(2);
	});

	it("retries on error with status >= 500", async () => {
		const err503 = Object.assign(new Error("service unavailable"), {
			status: 503,
		});
		const fn = vi.fn().mockRejectedValueOnce(err503).mockResolvedValue("ok");
		const res = await withRetry(fn, { maxRetries: 3, baseDelayMs: 1 });
		expect(res).toBe("ok");
		expect(fn).toHaveBeenCalledTimes(2);
	});

	it("returns resolved value as-is without inspecting response status", async () => {
		// withRetry only retries on thrown errors, not on resolved values
		const badResponse = { ok: false, status: 503 };
		const fn = vi.fn().mockResolvedValue(badResponse);
		const res = await withRetry(fn, { maxRetries: 3, baseDelayMs: 1 });
		expect(res).toEqual(badResponse);
		expect(fn).toHaveBeenCalledTimes(1);
	});

	it("wraps non-Error thrown values", async () => {
		const fn = vi.fn().mockRejectedValue("string error");
		await expect(withRetry(fn, { maxRetries: 0, baseDelayMs: 1 })).rejects.toBe(
			"string error",
		);
	});
});
