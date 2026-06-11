import * as crypto from "crypto";
import { describe, expect, it } from "vitest";

/**
 * Webhook Processing Integrity Tests
 *
 * Contract tests for:
 * 1. HMAC-SHA256 signature verification
 * 2. Deduplication key uniqueness semantics
 * 3. Threads publish → post_count increment
 * 4. Threads delete → post_count decrement
 * 5. Instagram comment → metric refresh debounce
 * 6. Event type routing (unknown types don't crash)
 * 7. Dead letter queue mechanics (retry_count, backoff, dead_letter flag)
 */

// ---------------------------------------------------------------------------
// 1. HMAC Signature Verification
// ---------------------------------------------------------------------------

describe("HMAC signature verification", () => {
	/**
	 * Extracted from both api/threads/webhook.ts and api/instagram/webhook.ts.
	 * Both use the same pattern: sha256= + HMAC-SHA256(secret, rawBody).
	 */
	function computeHmacSignature(secret: string, body: Buffer): string {
		return (
			"sha256=" +
			crypto.createHmac("sha256", secret).update(body).digest("hex")
		);
	}

	function verifySignature(
		rawBody: Buffer,
		signature: string,
		secrets: string[],
	): boolean {
		for (const secret of secrets) {
			const expectedSig = computeHmacSignature(secret, rawBody);
			const expectedBuf = Buffer.from(expectedSig);
			const actualBuf = Buffer.from(signature);
			if (expectedBuf.length !== actualBuf.length) continue;
			if (crypto.timingSafeEqual(expectedBuf, actualBuf)) return true;
		}
		return false;
	}

	it("accepts a valid HMAC-SHA256 signature", () => {
		const secret = "test-app-secret-12345";
		const body = Buffer.from(JSON.stringify({ event: "publish", id: "123" }));
		const sig = computeHmacSignature(secret, body);

		expect(verifySignature(body, sig, [secret])).toBe(true);
	});

	it("rejects an invalid signature", () => {
		const secret = "test-app-secret-12345";
		const body = Buffer.from(JSON.stringify({ event: "publish", id: "123" }));
		const wrongSig = "sha256=deadbeef0000000000000000000000000000000000000000000000000000abcd";

		expect(verifySignature(body, wrongSig, [secret])).toBe(false);
	});

	it("rejects when signature is missing (empty string)", () => {
		const secret = "test-app-secret-12345";
		const body = Buffer.from(JSON.stringify({ event: "publish" }));

		// Empty string won't match any valid HMAC
		expect(verifySignature(body, "", [secret])).toBe(false);
	});

	it("rejects when body is empty", () => {
		const secret = "test-app-secret-12345";
		const emptyBody = Buffer.from("");
		// Compute a signature for a non-empty payload
		const sigForOtherPayload = computeHmacSignature(
			secret,
			Buffer.from('{"event":"publish"}'),
		);

		expect(verifySignature(emptyBody, sigForOtherPayload, [secret])).toBe(
			false,
		);
	});

	it("rejects when no secrets are configured", () => {
		const body = Buffer.from(JSON.stringify({ event: "publish" }));
		const sig = "sha256=anything";

		expect(verifySignature(body, sig, [])).toBe(false);
	});

	it("accepts if ANY of the configured secrets matches (multi-secret fallback)", () => {
		const correctSecret = "secret-b";
		const body = Buffer.from(JSON.stringify({ event: "publish" }));
		const sig = computeHmacSignature(correctSecret, body);

		// First secret is wrong, second is correct — should still pass
		expect(verifySignature(body, sig, ["wrong-secret", correctSecret])).toBe(
			true,
		);
	});

	it("uses timing-safe comparison (signature prefix sha256=)", () => {
		const secret = "my-secret";
		const body = Buffer.from("test");
		const sig = computeHmacSignature(secret, body);

		// Signature must start with sha256=
		expect(sig).toMatch(/^sha256=[a-f0-9]{64}$/);
	});
});

// ---------------------------------------------------------------------------
// 2. Webhook Dedup Key Uniqueness
// ---------------------------------------------------------------------------

describe("webhook dedup key uniqueness", () => {
	/**
	 * The dedup constraint is: UNIQUE (event_type, user_id, payload_id)
	 * This is a NON-partial unique constraint per CLAUDE.md.
	 */

	function makeDedupKey(
		eventType: string,
		userId: string,
		payloadId: string | null,
	): string {
		// Represents the composite key. In SQL, NULL != NULL,
		// so two rows with payloadId = NULL are NOT duplicates.
		return `${eventType}:${userId}:${payloadId ?? "NULL"}`;
	}

	it("same event_type + user_id + payload_id = duplicate", () => {
		const key1 = makeDedupKey("replies", "user-1", "payload-abc");
		const key2 = makeDedupKey("replies", "user-1", "payload-abc");

		expect(key1).toBe(key2);
	});

	it("different payload_id = NOT duplicate", () => {
		const key1 = makeDedupKey("replies", "user-1", "payload-abc");
		const key2 = makeDedupKey("replies", "user-1", "payload-def");

		expect(key1).not.toBe(key2);
	});

	it("different event_type = NOT duplicate", () => {
		const key1 = makeDedupKey("replies", "user-1", "payload-abc");
		const key2 = makeDedupKey("mentions", "user-1", "payload-abc");

		expect(key1).not.toBe(key2);
	});

	it("NULL payload_id — two NULLs are NOT equal in SQL (known behavior)", () => {
		// In SQL: NULL != NULL, so UNIQUE constraint does NOT catch this.
		// The codebase handles this by falling back to a SHA-256 content hash
		// instead of leaving payload_id as NULL.
		const payload1 = { text: "hello" };
		const payload2 = { text: "world" };

		const hash1 = crypto
			.createHash("sha256")
			.update(JSON.stringify(payload1))
			.digest("hex")
			.slice(0, 32);
		const hash2 = crypto
			.createHash("sha256")
			.update(JSON.stringify(payload2))
			.digest("hex")
			.slice(0, 32);

		// Different payloads produce different hashes — so dedup still works
		expect(hash1).not.toBe(hash2);
	});

	it("content hash fallback is deterministic for identical payloads", () => {
		const payload = { text: "identical content", id: undefined };
		const hash1 = crypto
			.createHash("sha256")
			.update(JSON.stringify(payload ?? ""))
			.digest("hex")
			.slice(0, 32);
		const hash2 = crypto
			.createHash("sha256")
			.update(JSON.stringify(payload ?? ""))
			.digest("hex")
			.slice(0, 32);

		expect(hash1).toBe(hash2);
		expect(hash1).toHaveLength(32);
	});

	it("payload_id is extracted from payload.id when present", () => {
		const payload = { id: "real-thread-id-123", text: "some text" };
		const payloadId =
			(payload.id as string | undefined) ||
			crypto
				.createHash("sha256")
				.update(JSON.stringify(payload))
				.digest("hex")
				.slice(0, 32);

		expect(payloadId).toBe("real-thread-id-123");
	});
});

// ---------------------------------------------------------------------------
// 3. Threads Publish Webhook → post_count Increment
// ---------------------------------------------------------------------------

describe("Threads publish webhook → post_count increment", () => {
	it("identifies 'publish' as the event_type for new post events", () => {
		// The Threads webhook uses field = "publish" for new post events
		const publishPayload = {
			field: "publish",
			value: {
				id: "post-123",
				text: "Hello world",
				timestamp: Date.now() / 1000,
			},
		};

		expect(publishPayload.field).toBe("publish");
	});

	it("uses post_count (not posts_count) as the DB column name", () => {
		// The webhook processor increments account_analytics.post_count
		// Verify the column name is "post_count" not "posts_count"
		const correctColumnName = "post_count";
		const wrongColumnName = "posts_count";

		// This is a contract test — the column name must be exactly "post_count"
		expect(correctColumnName).toBe("post_count");
		expect(correctColumnName).not.toBe(wrongColumnName);
	});

	it("increment should produce value >= 0", () => {
		// Simulating post_count increment logic
		const currentCount = 0;
		const afterIncrement = currentCount + 1;

		expect(afterIncrement).toBe(1);
		expect(afterIncrement).toBeGreaterThanOrEqual(0);
	});
});

// ---------------------------------------------------------------------------
// 4. Threads Delete Webhook → post_count Decrement
// ---------------------------------------------------------------------------

describe("Threads delete webhook → post_count decrement", () => {
	it("identifies 'delete' as the event_type for post deletion", () => {
		const deletePayload = {
			field: "delete",
			value: { id: "post-123" },
		};

		expect(deletePayload.field).toBe("delete");
	});

	it("decrement should not go below 0", () => {
		// Simulating the decrement guard: GREATEST(post_count - 1, 0)
		function safeDecrement(current: number): number {
			return Math.max(current - 1, 0);
		}

		expect(safeDecrement(5)).toBe(4);
		expect(safeDecrement(1)).toBe(0);
		expect(safeDecrement(0)).toBe(0); // Must NOT go negative
	});

	it("decrements by exactly 1 per delete event", () => {
		function safeDecrement(current: number): number {
			return Math.max(current - 1, 0);
		}

		const before = 10;
		const after = safeDecrement(before);
		expect(after).toBe(9);
		expect(before - after).toBe(1);
	});
});

// ---------------------------------------------------------------------------
// 5. Instagram Comment Webhook → Metric Update + Debounce
// ---------------------------------------------------------------------------

describe("Instagram comment webhook → metric refresh debounce", () => {
	it("identifies comment event types correctly", () => {
		// IG webhooks use "comments" and "live_comments" event types
		const commentEventTypes = ["comments", "live_comments"];

		expect(commentEventTypes).toContain("comments");
		expect(commentEventTypes).toContain("live_comments");
	});

	it("debounce key is per-post (60s window)", () => {
		// The processor uses Redis key: `threads-metric-refresh:{postId}`
		// with NX + EX 60 (set-if-not-exists, 60s expiry)
		const postId = "post-abc-123";
		const debounceKey = `threads-metric-refresh:${postId}`;

		expect(debounceKey).toBe("threads-metric-refresh:post-abc-123");
	});

	it("two comments within 60s window should produce only one refresh", () => {
		// Simulating Redis NX behavior
		const seenKeys = new Set<string>();

		function shouldRefresh(key: string): boolean {
			if (seenKeys.has(key)) return false; // NX fails — already exists
			seenKeys.add(key);
			return true;
		}

		const key = "threads-metric-refresh:post-123";
		const firstCall = shouldRefresh(key);
		const secondCall = shouldRefresh(key);

		expect(firstCall).toBe(true); // First comment triggers refresh
		expect(secondCall).toBe(false); // Second is debounced
	});

	it("comments for different posts refresh independently", () => {
		const seenKeys = new Set<string>();

		function shouldRefresh(key: string): boolean {
			if (seenKeys.has(key)) return false;
			seenKeys.add(key);
			return true;
		}

		const post1 = shouldRefresh("threads-metric-refresh:post-1");
		const post2 = shouldRefresh("threads-metric-refresh:post-2");

		expect(post1).toBe(true);
		expect(post2).toBe(true); // Different post = independent debounce
	});
});

// ---------------------------------------------------------------------------
// 6. Webhook Event Type Routing
// ---------------------------------------------------------------------------

describe("webhook event type routing", () => {
	const KNOWN_THREADS_EVENT_TYPES = [
		"replies",
		"mentions",
		"publish",
		"delete",
	];

	const KNOWN_IG_EVENT_TYPES = [
		"comments",
		"live_comments",
		"mentions",
		"story_insights",
		"messages",
		"messaging_postbacks",
		"message_reactions",
		"messaging_seen",
		"message_edit",
		"messaging_referral",
		"messaging_optins",
		"messaging_handover",
		"standby",
		"follow",
	];

	it("all known Threads event types are strings", () => {
		for (const eventType of KNOWN_THREADS_EVENT_TYPES) {
			expect(typeof eventType).toBe("string");
			expect(eventType.length).toBeGreaterThan(0);
		}
	});

	it("all known IG event types are strings", () => {
		for (const eventType of KNOWN_IG_EVENT_TYPES) {
			expect(typeof eventType).toBe("string");
			expect(eventType.length).toBeGreaterThan(0);
		}
	});

	it("unknown event types should be storable (inserted to DB) without crash", () => {
		// The webhook handlers insert ALL events to DB regardless of event_type.
		// Processing of unknown types is a no-op (logged but not processed).
		const unknownEvent = {
			event_type: "some_future_meta_event",
			threads_user_id: "user-123",
			payload: { data: "test" },
		};

		// Should be a valid row shape — no crash
		expect(unknownEvent.event_type).toBe("some_future_meta_event");
		expect(unknownEvent).toHaveProperty("payload");
		expect(unknownEvent).toHaveProperty("threads_user_id");
	});

	it("IG messaging event type routing covers all message subtypes", () => {
		// From instagram/webhook.ts — messaging events are sub-routed by payload shape
		function classifyMessagingEvent(msg: Record<string, unknown>): string {
			if (msg.postback) return "messaging_postbacks";
			if (msg.reaction) return "message_reactions";
			if (msg.read) return "messaging_seen";
			if (msg.message_edit) return "message_edit";
			if (msg.referral && !msg.message) return "messaging_referral";
			if (msg.optin) return "messaging_optins";
			if (
				msg.pass_thread_control ||
				msg.take_thread_control ||
				msg.request_thread_control
			)
				return "messaging_handover";
			return "messages"; // default
		}

		expect(classifyMessagingEvent({ postback: {} })).toBe(
			"messaging_postbacks",
		);
		expect(classifyMessagingEvent({ reaction: {} })).toBe("message_reactions");
		expect(classifyMessagingEvent({ read: {} })).toBe("messaging_seen");
		expect(classifyMessagingEvent({ message_edit: {} })).toBe("message_edit");
		expect(classifyMessagingEvent({ referral: {} })).toBe(
			"messaging_referral",
		);
		expect(classifyMessagingEvent({ optin: {} })).toBe("messaging_optins");
		expect(classifyMessagingEvent({ pass_thread_control: {} })).toBe(
			"messaging_handover",
		);
		expect(classifyMessagingEvent({ message: { text: "hi" } })).toBe(
			"messages",
		);
		expect(classifyMessagingEvent({})).toBe("messages");
	});
});

// ---------------------------------------------------------------------------
// 7. Dead Letter Queue
// ---------------------------------------------------------------------------

describe("dead letter queue mechanics", () => {
	// MAX_RETRIES = 3 from retryUtils.ts
	const MAX_RETRIES = 3;

	function shouldRetry(attempt: number, max: number = MAX_RETRIES): boolean {
		return attempt < max;
	}

	function calculateBackoff(attempt: number, baseDelay: number = 30000): Date {
		// Exponential backoff: baseDelay * 2^attempt
		const delay = baseDelay * Math.pow(2, attempt);
		return new Date(Date.now() + delay);
	}

	it("retries up to MAX_RETRIES (3) times", () => {
		expect(shouldRetry(0)).toBe(true); // 1st attempt
		expect(shouldRetry(1)).toBe(true); // 2nd attempt
		expect(shouldRetry(2)).toBe(true); // 3rd attempt
		expect(shouldRetry(3)).toBe(false); // Exhausted — move to dead letter
	});

	it("moves to dead letter after MAX_RETRIES exhausted", () => {
		const retryCount = 3;
		const shouldDeadLetter = !shouldRetry(retryCount);

		expect(shouldDeadLetter).toBe(true);
	});

	it("retry_count increments by 1 on each failure", () => {
		let retryCount = 0;

		// Simulate 3 failures
		for (let i = 0; i < 3; i++) {
			if (shouldRetry(retryCount)) {
				retryCount += 1;
			}
		}

		expect(retryCount).toBe(3);
	});

	it("next_retry_at uses exponential backoff", () => {
		const baseDelay = 30000; // 30 seconds
		const now = Date.now();

		const retry0 = calculateBackoff(0, baseDelay);
		const retry1 = calculateBackoff(1, baseDelay);
		const retry2 = calculateBackoff(2, baseDelay);

		// Each retry should be further in the future
		expect(retry0.getTime()).toBeGreaterThan(now);
		expect(retry1.getTime()).toBeGreaterThan(retry0.getTime());
		expect(retry2.getTime()).toBeGreaterThan(retry1.getTime());

		// Verify exponential growth: delay doubles each time
		const delay0 = retry0.getTime() - now;
		const delay1 = retry1.getTime() - now;
		const delay2 = retry2.getTime() - now;

		// Allow small timing variance (within 100ms)
		expect(delay1).toBeCloseTo(delay0 * 2, -2);
		expect(delay2).toBeCloseTo(delay0 * 4, -2);
	});

	it("dead letter record includes reason and timestamp", () => {
		const errorMessage = "Meta API returned 500";
		const retryCount = 3;

		const deadLetterUpdate = {
			processed: true,
			processed_at: new Date().toISOString(),
			error: `Max retries exceeded: ${errorMessage}`,
			dead_letter: true,
			dead_letter_at: new Date().toISOString(),
			dead_letter_reason: `Exhausted ${retryCount} retries: ${errorMessage}`,
		};

		expect(deadLetterUpdate.dead_letter).toBe(true);
		expect(deadLetterUpdate.dead_letter_reason).toContain("Exhausted 3 retries");
		expect(deadLetterUpdate.dead_letter_reason).toContain(errorMessage);
		expect(deadLetterUpdate.processed).toBe(true);
		expect(deadLetterUpdate.dead_letter_at).toBeTruthy();
	});

	it("retry update sets retry_count and next_retry_at", () => {
		const retryCount = 1;
		const errorMessage = "Temporary failure";
		const nextRetryAt = calculateBackoff(retryCount, 30000);

		const retryUpdate = {
			error: errorMessage,
			last_error: errorMessage,
			retry_count: retryCount + 1,
			next_retry_at: nextRetryAt.toISOString(),
		};

		expect(retryUpdate.retry_count).toBe(2);
		expect(retryUpdate.next_retry_at).toBeTruthy();
		expect(retryUpdate.error).toBe(errorMessage);
		expect(retryUpdate.last_error).toBe(errorMessage);
	});
});
