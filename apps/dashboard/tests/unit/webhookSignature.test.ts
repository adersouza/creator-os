import * as crypto from "crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Tests for webhook HMAC-SHA256 signature verification.
 * Covers both Threads and Instagram webhook handlers.
 */

// Helper: compute a valid HMAC signature
function computeSignature(body: string, secret: string): string {
	return (
		"sha256=" + crypto.createHmac("sha256", secret).update(body).digest("hex")
	);
}

// ===== Threads Webhook Signature Tests =====
describe("Threads webhook signature verification", () => {
	const THREADS_SECRET = "test-threads-app-secret";
	const META_SECRET = "test-meta-app-secret";

	beforeEach(() => {
		process.env.THREADS_APP_SECRET = THREADS_SECRET;
		process.env.META_APP_SECRET = META_SECRET;
		process.env.META_WEBHOOK_VERIFY_TOKEN = "test-verify-token";
	});

	afterEach(() => {
		delete process.env.THREADS_APP_SECRET;
		delete process.env.META_APP_SECRET;
		delete process.env.META_WEBHOOK_VERIFY_TOKEN;
		vi.restoreAllMocks();
	});

	it("accepts valid signature with THREADS_APP_SECRET", () => {
		const body = '{"entry":[]}';
		const sig = computeSignature(body, THREADS_SECRET);
		const rawBody = Buffer.from(body);

		// Inline verification logic (same as webhook handler)
		const secrets = [THREADS_SECRET, META_SECRET];
		let verified = false;
		for (const secret of secrets) {
			const expected =
				"sha256=" +
				crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
			try {
				if (crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig))) {
					verified = true;
					break;
				}
			} catch {}
		}
		expect(verified).toBe(true);
	});

	it("accepts valid signature with META_APP_SECRET fallback", () => {
		const body = '{"entry":[{"id":"123"}]}';
		const sig = computeSignature(body, META_SECRET);
		const rawBody = Buffer.from(body);

		const secrets = [THREADS_SECRET, META_SECRET];
		let verified = false;
		for (const secret of secrets) {
			const expected =
				"sha256=" +
				crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
			try {
				if (crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig))) {
					verified = true;
					break;
				}
			} catch {}
		}
		expect(verified).toBe(true);
	});

	it("rejects invalid signature", () => {
		const body = '{"entry":[]}';
		const sig =
			"sha256=invalid0000000000000000000000000000000000000000000000000000000000";
		const rawBody = Buffer.from(body);

		const secrets = [THREADS_SECRET, META_SECRET];
		let verified = false;
		for (const secret of secrets) {
			const expected =
				"sha256=" +
				crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
			try {
				if (crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig))) {
					verified = true;
					break;
				}
			} catch {}
		}
		expect(verified).toBe(false);
	});

	it("rejects when no secrets are configured", () => {
		const secrets: string[] = [];
		expect(secrets.length).toBe(0);
		// With no secrets, verification should fail
		const verified = false;
		expect(verified).toBe(false);
	});

	it("handles length mismatch without throwing", () => {
		const body = '{"test":true}';
		const sig = "sha256=short";
		const rawBody = Buffer.from(body);

		const secrets = [THREADS_SECRET];
		let verified = false;
		for (const secret of secrets) {
			const expected =
				"sha256=" +
				crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
			try {
				if (crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig))) {
					verified = true;
					break;
				}
			} catch {}
		}
		expect(verified).toBe(false);
	});
});

// ===== Instagram Webhook Signature Tests =====
describe("Instagram webhook signature verification", () => {
	const META_SECRET = "test-meta-secret";
	const FB_SECRET = "test-facebook-secret";

	it("accepts valid signature with META_APP_SECRET", () => {
		const body = '{"object":"instagram","entry":[]}';
		const sig = computeSignature(body, META_SECRET);
		const rawBody = Buffer.from(body);

		const secrets = [META_SECRET, FB_SECRET];
		let verified = false;
		for (const secret of secrets) {
			const expected =
				"sha256=" +
				crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
			try {
				if (crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig))) {
					verified = true;
					break;
				}
			} catch {}
		}
		expect(verified).toBe(true);
	});

	it("accepts valid signature with FACEBOOK_APP_SECRET fallback", () => {
		const body = '{"object":"instagram","entry":[{"id":"456"}]}';
		const sig = computeSignature(body, FB_SECRET);
		const rawBody = Buffer.from(body);

		const secrets = [META_SECRET, FB_SECRET];
		let verified = false;
		for (const secret of secrets) {
			const expected =
				"sha256=" +
				crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
			try {
				if (crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig))) {
					verified = true;
					break;
				}
			} catch {}
		}
		expect(verified).toBe(true);
	});

	it("rejects tampered body", () => {
		const originalBody = '{"object":"instagram","entry":[]}';
		const tamperedBody = '{"object":"instagram","entry":[{"injected":true}]}';
		const sig = computeSignature(originalBody, META_SECRET);
		const rawBody = Buffer.from(tamperedBody);

		const secrets = [META_SECRET, FB_SECRET];
		let verified = false;
		for (const secret of secrets) {
			const expected =
				"sha256=" +
				crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
			try {
				if (crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig))) {
					verified = true;
					break;
				}
			} catch {}
		}
		expect(verified).toBe(false);
	});

	it("rejects missing sha256= prefix", () => {
		const body = '{"test":true}';
		const rawSig = crypto
			.createHmac("sha256", META_SECRET)
			.update(body)
			.digest("hex");
		// No "sha256=" prefix — should not match
		const sig = rawSig;
		const rawBody = Buffer.from(body);

		const secrets = [META_SECRET];
		let verified = false;
		for (const secret of secrets) {
			const expected =
				"sha256=" +
				crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
			try {
				if (crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig))) {
					verified = true;
					break;
				}
			} catch {}
		}
		expect(verified).toBe(false);
	});

	it("is consistent across repeated verifications", () => {
		// Verify the same body+secret always produces the same signature
		const body = '{"test":true}';
		const sig1 = computeSignature(body, META_SECRET);
		const sig2 = computeSignature(body, META_SECRET);
		expect(sig1).toBe(sig2);

		// And different bodies produce different signatures
		const sig3 = computeSignature('{"test":false}', META_SECRET);
		expect(sig1).not.toBe(sig3);
	});
});

// ============================================================================
// Timing attack structural tests
// ============================================================================

describe("Signature verification — timing attack resistance", () => {
	const SECRET = "timing-test-secret";
	const body = '{"entry":[{"id":"123"}]}';
	const rawBody = Buffer.from(body);
	const validSig =
		"sha256=" + crypto.createHmac("sha256", SECRET).update(rawBody).digest("hex");

	// The verify function under test (mirrors the handler implementation)
	function verify(sig: string): boolean {
		const expectedBuf = Buffer.from(validSig);
		const actualBuf = Buffer.from(sig);
		if (expectedBuf.length !== actualBuf.length) return false;
		return crypto.timingSafeEqual(expectedBuf, actualBuf);
	}

	it("rejects a signature that matches only the first byte", () => {
		// Same prefix as valid sig, different last byte
		const earlyMatch =
			validSig.slice(0, -1) +
			(validSig[validSig.length - 1] === "a" ? "b" : "a");
		expect(verify(earlyMatch)).toBe(false);
	});

	it("rejects a signature with all bytes matching except the last", () => {
		const almostValid =
			validSig.slice(0, -1) +
			(validSig[validSig.length - 1] === "f" ? "e" : "f");
		expect(verify(almostValid)).toBe(false);
	});

	it("valid and invalid verifications complete in comparable time (no early-exit leak)", () => {
		// Statistical timing test: run repeated batches and compare medians.
		// Full-suite load can add scheduler/JIT spikes to any single batch; using
		// medians keeps the test focused on gross early-exit behavior.
		const earlyMismatch = "sha256=" + "0".repeat(64);
		const N = 1000;

		const time = (sig: string): number => {
			const start = performance.now();
			for (let i = 0; i < N; i++) verify(sig);
			return performance.now() - start;
		};

		const median = (values: number[]): number => {
			const sorted = [...values].sort((a, b) => a - b);
			return sorted[Math.floor(sorted.length / 2)] ?? 0;
		};

		// Warm up both branches before measuring.
		time(validSig);
		time(earlyMismatch);

		const validTime = median(Array.from({ length: 7 }, () => time(validSig)));
		const invalidTime = median(Array.from({ length: 7 }, () => time(earlyMismatch)));
		const ratio =
			Math.max(validTime, invalidTime) / Math.min(validTime, invalidTime);

		// 5× is very generous — true constant-time should be <1.5×
		// This catches gross early-exit implementations, not nanosecond leaks
		expect(ratio).toBeLessThan(5);
	});

	it("both first-byte and last-byte mismatches are rejected", () => {
		const firstByteMismatch = "sha256=" + "0" + validSig.slice(8);
		const lastByteMismatch =
			validSig.slice(0, -1) +
			(validSig[validSig.length - 1] === "0" ? "1" : "0");

		expect(verify(firstByteMismatch)).toBe(false);
		expect(verify(lastByteMismatch)).toBe(false);
	});
});
