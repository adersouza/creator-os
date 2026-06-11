/**
 * Tests for the three cron safety fixes:
 *
 * 1. Monotonic metric writes — higher engagement always wins
 * 2. Meta API rate limit backpressure — MetaRateLimitError breaks batch loops
 * 3. Token expiry pre-flight + OAuthException detection in publish path
 */

import { describe, expect, it } from "vitest";

// ============================================================================
// Fix 1: Monotonic metric writes
// ============================================================================

describe("Monotonic metric guard", () => {
	/**
	 * Simulates the SQL logic: UPDATE ... WHERE existing_total <= new_total
	 * This mirrors update_post_metrics_if_newer()
	 */
	function shouldOverwrite(
		existing: { views: number; likes: number; replies: number; reposts: number },
		incoming: { views: number; likes: number; replies: number; reposts: number },
	): boolean {
		const existingTotal =
			existing.views + existing.likes + existing.replies + existing.reposts;
		const incomingTotal =
			incoming.views + incoming.likes + incoming.replies + incoming.reposts;
		return existingTotal <= incomingTotal;
	}

	it("allows overwrite when incoming metrics are higher", () => {
		const existing = { views: 100, likes: 10, replies: 2, reposts: 1 };
		const incoming = { views: 150, likes: 15, replies: 3, reposts: 2 };
		expect(shouldOverwrite(existing, incoming)).toBe(true);
	});

	it("allows overwrite when metrics are equal (idempotent)", () => {
		const existing = { views: 100, likes: 10, replies: 2, reposts: 1 };
		const incoming = { views: 100, likes: 10, replies: 2, reposts: 1 };
		expect(shouldOverwrite(existing, incoming)).toBe(true);
	});

	it("blocks overwrite when incoming metrics are lower (stale data)", () => {
		const existing = { views: 200, likes: 20, replies: 5, reposts: 3 };
		const incoming = { views: 100, likes: 10, replies: 2, reposts: 1 };
		expect(shouldOverwrite(existing, incoming)).toBe(false);
	});

	it("handles zero-initialized rows (first write always wins)", () => {
		const existing = { views: 0, likes: 0, replies: 0, reposts: 0 };
		const incoming = { views: 1, likes: 0, replies: 0, reposts: 0 };
		expect(shouldOverwrite(existing, incoming)).toBe(true);
	});

	it("handles both zero (allows write)", () => {
		const existing = { views: 0, likes: 0, replies: 0, reposts: 0 };
		const incoming = { views: 0, likes: 0, replies: 0, reposts: 0 };
		expect(shouldOverwrite(existing, incoming)).toBe(true);
	});

	it("webhook wins when pipeline has stale snapshot", () => {
		// Webhook fires at 2:00 AM with fresh data
		const webhookData = { views: 500, likes: 50, replies: 10, reposts: 5 };
		// Pipeline runs at 2:00 AM with data fetched 5 min ago
		const pipelineData = { views: 480, likes: 48, replies: 9, reposts: 4 };

		// If webhook wrote first, pipeline should NOT overwrite
		expect(shouldOverwrite(webhookData, pipelineData)).toBe(false);
		// If pipeline wrote first, webhook SHOULD overwrite
		expect(shouldOverwrite(pipelineData, webhookData)).toBe(true);
	});
});

// ============================================================================
// Fix 2: Meta API rate limit backpressure
// ============================================================================

describe("MetaRateLimitError", () => {
	// Mirror the MetaRateLimitError from constants.ts
	class MetaRateLimitError extends Error {
		constructor(
			message: string,
			public maxPct: number,
		) {
			super(message);
			this.name = "MetaRateLimitError";
		}
	}

	/**
	 * Simulates the backpressure logic in fetchWithTimeout:
	 * - >=95% → throw MetaRateLimitError
	 * - >=70% → delay (backpressure)
	 * - <70% → proceed normally
	 */
	function getBackpressureAction(maxPct: number): "abort" | "delay" | "proceed" {
		if (maxPct >= 95) return "abort";
		if (maxPct >= 70) return "delay";
		return "proceed";
	}

	function getDelayMs(maxPct: number): number {
		if (maxPct < 70) return 0;
		return Math.min(1000 * 2 ** (Math.floor(maxPct / 10) - 7), 30000);
	}

	it("proceeds normally at 40% usage", () => {
		expect(getBackpressureAction(40)).toBe("proceed");
	});

	it("proceeds normally at 69% usage", () => {
		expect(getBackpressureAction(69)).toBe("proceed");
	});

	it("applies delay at 70% usage", () => {
		expect(getBackpressureAction(70)).toBe("delay");
		expect(getDelayMs(70)).toBe(1000); // 1s
	});

	it("applies increasing delay at 80% usage", () => {
		expect(getBackpressureAction(80)).toBe("delay");
		expect(getDelayMs(80)).toBe(2000); // 2s
	});

	it("applies higher delay at 90% usage", () => {
		expect(getBackpressureAction(90)).toBe("delay");
		expect(getDelayMs(90)).toBe(4000); // 4s
	});

	it("aborts at 95% usage", () => {
		expect(getBackpressureAction(95)).toBe("abort");
	});

	it("aborts at 100% usage", () => {
		expect(getBackpressureAction(100)).toBe("abort");
	});

	it("delay never exceeds 30s", () => {
		// Even at extreme percentages
		expect(getDelayMs(94)).toBeLessThanOrEqual(30000);
	});

	it("MetaRateLimitError is catchable by instanceof", () => {
		const err = new MetaRateLimitError("test", 95);
		expect(err).toBeInstanceOf(MetaRateLimitError);
		expect(err).toBeInstanceOf(Error);
		expect(err.maxPct).toBe(95);
		expect(err.name).toBe("MetaRateLimitError");
	});

	it("batch loop breaks on MetaRateLimitError", () => {
		let processed = 0;
		const batches = [1, 2, 3, 4, 5];

		for (const batch of batches) {
			try {
				processed++;
				if (batch === 3) {
					throw new MetaRateLimitError("at ceiling", 96);
				}
			} catch (e) {
				if (e instanceof MetaRateLimitError) break;
				throw e;
			}
		}

		// Should process 1, 2, 3 (throws on 3), then break
		expect(processed).toBe(3);
	});
});

// ============================================================================
// Fix 3: Token expiry pre-flight + OAuthException detection
// ============================================================================

describe("Token expiry pre-flight check", () => {
	function shouldSkipDueToExpiry(tokenExpiresAt: string | null): boolean {
		if (!tokenExpiresAt) return false;
		return new Date(tokenExpiresAt) < new Date();
	}

	it("skips when token expired 5 minutes ago", () => {
		const expired = new Date(Date.now() - 5 * 60 * 1000).toISOString();
		expect(shouldSkipDueToExpiry(expired)).toBe(true);
	});

	it("does not skip when token expires in 5 minutes", () => {
		const future = new Date(Date.now() + 5 * 60 * 1000).toISOString();
		expect(shouldSkipDueToExpiry(future)).toBe(false);
	});

	it("does not skip when token_expires_at is null", () => {
		expect(shouldSkipDueToExpiry(null)).toBe(false);
	});

	it("skips when token expired 1 second ago (edge case)", () => {
		const justExpired = new Date(Date.now() - 1000).toISOString();
		expect(shouldSkipDueToExpiry(justExpired)).toBe(true);
	});
});

describe("OAuthException detection", () => {
	function isTokenError(errorMsg: string): boolean {
		return (
			errorMsg.includes("OAuthException") ||
			errorMsg.includes("expired") ||
			errorMsg.includes("session has been invalidated") ||
			errorMsg.includes("Error validating access token") ||
			errorMsg.includes("code 190") ||
			errorMsg.includes("Token verification failed")
		);
	}

	it("detects OAuthException", () => {
		expect(isTokenError("Error: OAuthException — token is invalid")).toBe(true);
	});

	it("detects expired token", () => {
		expect(isTokenError("The access token has expired")).toBe(true);
	});

	it("detects session invalidated", () => {
		expect(
			isTokenError("The session has been invalidated because the user changed their password"),
		).toBe(true);
	});

	it("detects code 190", () => {
		expect(isTokenError("Error code 190: Invalid OAuth 2.0 Access Token")).toBe(
			true,
		);
	});

	it("detects Token verification failed", () => {
		expect(isTokenError("Token verification failed")).toBe(true);
	});

	it("detects Error validating access token", () => {
		expect(
			isTokenError("Error validating access token: Session has expired"),
		).toBe(true);
	});

	it("does NOT match transient errors (429, timeout)", () => {
		expect(isTokenError("429 Too Many Requests")).toBe(false);
		expect(isTokenError("Request timed out after 10000ms")).toBe(false);
		expect(isTokenError("Internal Server Error 500")).toBe(false);
	});

	it("does NOT match generic publish errors", () => {
		expect(isTokenError("Media type not supported")).toBe(false);
		expect(isTokenError("Content too long")).toBe(false);
		expect(isTokenError("User not authorized")).toBe(false);
	});
});

describe("Token error is NOT in transient error patterns", () => {
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

	it("OAuthException is NOT transient (won't waste retries)", () => {
		expect(isTransientError("OAuthException — token expired")).toBe(false);
	});

	it("code 190 is NOT transient", () => {
		expect(isTransientError("Error code 190: invalid token")).toBe(false);
	});

	it("session invalidated is NOT transient", () => {
		expect(
			isTransientError("session has been invalidated"),
		).toBe(false);
	});
});
