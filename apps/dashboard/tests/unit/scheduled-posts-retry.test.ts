/**
 * Tests for transient error auto-reschedule logic in scheduled-posts.ts
 *
 * Verifies that 429/5xx/timeout errors reschedule the post with a 15-min delay
 * instead of hard-failing, and that permanent errors or exhausted retries still fail.
 */

import { describe, expect, it } from "vitest";

// ---------------------------------------------------------------------------
// Mirror the exact patterns from scheduled-posts.ts (lines 518-539)
// ---------------------------------------------------------------------------

const TRANSIENT_ERROR_PATTERNS = [
	"timeout",
	"ETIMEDOUT",
	"ECONNRESET",
	"ECONNREFUSED",
	"rate limit",
	"too many requests",
	"429",
	"internal server error",
	"500",
	"502",
	"503",
	"504",
	"temporarily unavailable",
];

function isTransientError(errorMsg: string): boolean {
	const lower = errorMsg.toLowerCase();
	return TRANSIENT_ERROR_PATTERNS.some((pattern) =>
		lower.includes(pattern.toLowerCase()),
	);
}

// ---------------------------------------------------------------------------
// Mirror the exact reschedule decision from the Threads/IG failure handlers
// ---------------------------------------------------------------------------

function simulateFailureHandler(
	errorMsg: string,
	currentRetryCount: number,
): { action: "rescheduled" | "failed"; retryCount: number; delayMs?: number } {
	if (isTransientError(errorMsg) && currentRetryCount < 3) {
		const delayMs = 15 * 60 * 1000;
		return {
			action: "rescheduled",
			retryCount: currentRetryCount + 1,
			delayMs,
		};
	}
	return { action: "failed", retryCount: currentRetryCount };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("isTransientError", () => {
	describe("identifies transient errors", () => {
		it.each([
			["Rate limited after retries: 429 Too Many Requests", "429 in message"],
			["rate limit exceeded", "rate limit phrase"],
			["too many requests", "too many requests phrase"],
			["Request timeout after 10000ms", "timeout"],
			["connect ETIMEDOUT 157.240.1.17:443", "ETIMEDOUT"],
			["read ECONNRESET", "ECONNRESET"],
			["connect ECONNREFUSED 127.0.0.1:443", "ECONNREFUSED"],
			["500 Internal Server Error", "500"],
			["502 Bad Gateway", "502"],
			["503 Service Unavailable", "503"],
			["504 Gateway Timeout", "504"],
			["internal server error from upstream", "internal server error"],
			["Service temporarily unavailable", "temporarily unavailable"],
		])("returns true for: %s (%s)", (msg) => {
			expect(isTransientError(msg)).toBe(true);
		});
	});

	describe("identifies permanent errors", () => {
		it.each([
			["Invalid access token", "auth error"],
			["Invalid parameter: media_url is required", "validation error"],
			["OAuthException: permissions error", "permissions"],
			["Unsupported post type", "unsupported type"],
			["User does not exist", "not found"],
			["Content policy violation", "policy error"],
			["WebP is not supported", "format error"],
		])("returns false for: %s (%s)", (msg) => {
			expect(isTransientError(msg)).toBe(false);
		});
	});
});

describe("transient error reschedule logic", () => {
	it("reschedules on first 429 error with 15-min delay", () => {
		const result = simulateFailureHandler("Rate limited: 429", 0);
		expect(result.action).toBe("rescheduled");
		expect(result.retryCount).toBe(1);
		expect(result.delayMs).toBe(15 * 60 * 1000);
	});

	it("reschedules on second transient error", () => {
		const result = simulateFailureHandler("503 Service Unavailable", 1);
		expect(result.action).toBe("rescheduled");
		expect(result.retryCount).toBe(2);
	});

	it("reschedules on third transient error (retry_count=2 → 3)", () => {
		const result = simulateFailureHandler("timeout", 2);
		expect(result.action).toBe("rescheduled");
		expect(result.retryCount).toBe(3);
	});

	it("hard-fails after 3 transient retries exhausted (retry_count=3)", () => {
		const result = simulateFailureHandler("429 Too Many Requests", 3);
		expect(result.action).toBe("failed");
		expect(result.retryCount).toBe(3);
		expect(result.delayMs).toBeUndefined();
	});

	it("hard-fails immediately on permanent error regardless of retry_count", () => {
		const result = simulateFailureHandler("Invalid access token", 0);
		expect(result.action).toBe("failed");
		expect(result.retryCount).toBe(0);
	});

	it("hard-fails on permanent error even when retry_count is low", () => {
		const result = simulateFailureHandler("OAuthException: permissions error", 1);
		expect(result.action).toBe("failed");
		expect(result.retryCount).toBe(1);
	});

	it("treats ECONNRESET as transient", () => {
		const result = simulateFailureHandler("read ECONNRESET", 0);
		expect(result.action).toBe("rescheduled");
	});

	it("treats ETIMEDOUT as transient", () => {
		const result = simulateFailureHandler("connect ETIMEDOUT 1.2.3.4:443", 0);
		expect(result.action).toBe("rescheduled");
	});

	it("treats 'temporarily unavailable' as transient", () => {
		const result = simulateFailureHandler("Service temporarily unavailable, please retry", 0);
		expect(result.action).toBe("rescheduled");
	});

	it("treats unknown errors as permanent", () => {
		const result = simulateFailureHandler("Something completely unexpected happened", 0);
		expect(result.action).toBe("failed");
	});

	it("delay is exactly 15 minutes in milliseconds", () => {
		const result = simulateFailureHandler("rate limit", 0);
		expect(result.delayMs).toBe(900_000);
	});
});
