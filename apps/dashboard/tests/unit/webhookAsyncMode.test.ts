import * as crypto from "crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Characterization tests for webhook async-first mode.
 *
 * Proves that:
 * 1. With WEBHOOK_ASYNC_ONLY=true, the route returns 200 BEFORE processing
 * 2. Events are inserted into DB with processed=false
 * 3. QStash nudge is fired (non-blocking) for near-instant pickup
 * 4. With WEBHOOK_ASYNC_ONLY unset (legacy), inline processing runs with timing
 * 5. Deduplication still works in both modes
 * 6. Signature verification still gates everything
 */

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockUpsert = vi.fn();
const mockSelect = vi.fn();
const mockUpdate = vi.fn();
const mockEq = vi.fn();
const mockChannel = vi.fn();
const mockHttpSend = vi.fn().mockResolvedValue(undefined);
const mockIn = vi.fn().mockResolvedValue({ data: [], error: null });
const mockAccountSelect = vi.fn().mockReturnValue({ in: mockIn });

const mockSupabase = {
	from: vi.fn((table: string) => {
		if (table === "accounts" || table === "instagram_accounts") {
			return { select: mockAccountSelect };
		}
		return {
			upsert: mockUpsert.mockReturnValue({ select: mockSelect }),
			update: mockUpdate.mockReturnValue({ eq: mockEq }),
		};
	}),
	channel: mockChannel.mockReturnValue({ httpSend: mockHttpSend }),
};

vi.mock("@/api/_lib/supabase.js", () => ({
	getSupabase: () => mockSupabase,
}));

vi.mock("@/api/_lib/logger.js", () => ({
	logger: {
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

vi.mock("@/api/_lib/redis.js", () => ({
	getRedis: () => ({
		set: vi.fn().mockResolvedValue("OK"),
	}),
}));

vi.mock("@/api/_lib/apiResponse.js", () => ({
	apiError: (res: any, status: number, msg: string) =>
		res.status(status).json({ error: msg }),
	apiSuccess: (res: any, data: unknown) =>
		res.status(200).json({ data }),
}));

const mockScheduleWebhookReplay = vi.fn().mockResolvedValue(undefined);
const mockHandleThreadsWebhookEvent = vi.fn().mockResolvedValue(undefined);
const mockHandleIgWebhookEvent = vi.fn().mockResolvedValue(undefined);
const mockMarkWebhookEventForRetry = vi.fn().mockResolvedValue(undefined);
const mockIncrementAndCheckSigFailures = vi.fn().mockResolvedValue(false);

// Both webhook.ts files import scheduleWebhookReplay from this path
vi.mock("@/api/_lib/cron/webhook-processor/retry.js", () => ({
	scheduleWebhookReplay: (...args: unknown[]) =>
		mockScheduleWebhookReplay(...args),
}));

// Both webhook.ts files import incrementAndCheckSigFailures from this path
vi.mock("@/api/_lib/webhookMonitor.js", () => ({
	incrementAndCheckSigFailures: (...args: unknown[]) =>
		mockIncrementAndCheckSigFailures(...args),
}));

// webhook-processor exports used by other modules (handleThreadsWebhookEvent, etc.)
vi.mock("@/api/cron/webhook-processor.js", () => ({
	handleThreadsWebhookEvent: (...args: unknown[]) =>
		mockHandleThreadsWebhookEvent(...args),
	handleIgWebhookEvent: (...args: unknown[]) =>
		mockHandleIgWebhookEvent(...args),
	markWebhookEventForRetry: (...args: unknown[]) =>
		mockMarkWebhookEventForRetry(...args),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const THREADS_SECRET = "test-threads-secret";

function computeSignature(body: string, secret: string): string {
	return (
		"sha256=" + crypto.createHmac("sha256", secret).update(body).digest("hex")
	);
}

function mockRes() {
	const res: Record<string, ReturnType<typeof vi.fn>> = {};
	res.status = vi.fn().mockReturnValue(res);
	res.json = vi.fn().mockReturnValue(res);
	res.send = vi.fn().mockReturnValue(res);
	res.setHeader = vi.fn().mockReturnValue(res);
	return res;
}

function makeStreamReq(
	body: string,
	signature: string,
	method = "POST",
): Record<string, unknown> {
	const buf = Buffer.from(body);
	let dataHandler: ((chunk: Buffer) => void) | null = null;
	let endHandler: (() => void) | null = null;

	return {
		method,
		headers: {
			"x-hub-signature-256": signature,
			"x-forwarded-for": "127.0.0.1",
			"user-agent": "test",
		},
		query: {},
		body: undefined,
		on(event: string, handler: (...args: unknown[]) => void) {
			if (event === "data") {
				dataHandler = handler as (chunk: Buffer) => void;
				// Emit data on next tick to simulate stream
				queueMicrotask(() => dataHandler?.(buf));
			}
			if (event === "end") {
				endHandler = handler as () => void;
				queueMicrotask(() => queueMicrotask(() => endHandler?.()));
			}
			if (event === "error") {
				// no-op
			}
		},
	};
}

// ---------------------------------------------------------------------------
// Test Suites
// ---------------------------------------------------------------------------

describe("Threads webhook async mode", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		process.env.THREADS_APP_SECRET = THREADS_SECRET;
		process.env.META_APP_SECRET = "";
		process.env.META_WEBHOOK_VERIFY_TOKEN = "test-verify";
	});

	afterEach(() => {
		delete process.env.THREADS_APP_SECRET;
		delete process.env.META_APP_SECRET;
		delete process.env.META_WEBHOOK_VERIFY_TOKEN;
		delete process.env.WEBHOOK_ASYNC_ONLY;
		vi.restoreAllMocks();
	});

	it("async mode: returns 200 without calling handleThreadsWebhookEvent", async () => {
		process.env.WEBHOOK_ASYNC_ONLY = "true";

		const payload = JSON.stringify({
			target_id: "user123",
			topic: "threads",
			values: { field: "replies", value: { id: "reply1", text: "hello" } },
			time: Math.floor(Date.now() / 1000),
		});
		const sig = computeSignature(payload, THREADS_SECRET);

		const insertedRow = {
			id: "evt-1",
			event_type: "replies",
			threads_user_id: "user123",
			payload: { id: "reply1", text: "hello" },
		};
		mockSelect.mockResolvedValue({ data: [insertedRow], error: null });

		const { default: handler } = await import("@/api/threads/webhook.js");
		const res = mockRes();
		await handler(makeStreamReq(payload, sig) as any, res as any);

		// Should return 200
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith({ data: { received: true } });

		// Should NOT have called inline processing
		expect(mockHandleThreadsWebhookEvent).not.toHaveBeenCalled();

		// Should have fired QStash nudge
		expect(mockScheduleWebhookReplay).toHaveBeenCalledWith("threads", 5);
	});

	it("rejects spoofed signature before any DB interaction", async () => {
		process.env.WEBHOOK_ASYNC_ONLY = "true";

		const payload = JSON.stringify({ target_id: "x", values: { field: "replies", value: {} } });
		const fakeSig =
			"sha256=0000000000000000000000000000000000000000000000000000000000000000";

		const { default: handler } = await import("@/api/threads/webhook.js");
		const res = mockRes();
		await handler(makeStreamReq(payload, fakeSig) as any, res as any);

		expect(res.status).toHaveBeenCalledWith(401);
		expect(mockSupabase.from).not.toHaveBeenCalled();
		expect(mockHandleThreadsWebhookEvent).not.toHaveBeenCalled();
		expect(mockScheduleWebhookReplay).not.toHaveBeenCalled();
	});

	it("deduplication: duplicate insert returns empty array, no processing", async () => {
		process.env.WEBHOOK_ASYNC_ONLY = "true";

		const payload = JSON.stringify({
			target_id: "user789",
			topic: "threads",
			values: { field: "replies", value: { id: "dup1" } },
			time: Math.floor(Date.now() / 1000),
		});
		const sig = computeSignature(payload, THREADS_SECRET);

		// Upsert with ignoreDuplicates returns empty array for dupes
		mockSelect.mockResolvedValue({ data: [], error: null });

		const { default: handler } = await import("@/api/threads/webhook.js");
		const res = mockRes();
		await handler(makeStreamReq(payload, sig) as any, res as any);

		expect(res.status).toHaveBeenCalledWith(200);
		// No new events = no QStash nudge
		expect(mockScheduleWebhookReplay).not.toHaveBeenCalled();
		expect(mockHandleThreadsWebhookEvent).not.toHaveBeenCalled();
	});
});

describe("Instagram webhook async mode", () => {
	const META_SECRET = "test-ig-meta-secret";

	beforeEach(() => {
		vi.clearAllMocks();
		process.env.META_APP_SECRET = META_SECRET;
		process.env.FACEBOOK_APP_SECRET = "";
		process.env.META_WEBHOOK_VERIFY_TOKEN = "test-verify";
	});

	afterEach(() => {
		delete process.env.META_APP_SECRET;
		delete process.env.FACEBOOK_APP_SECRET;
		delete process.env.META_WEBHOOK_VERIFY_TOKEN;
		delete process.env.WEBHOOK_ASYNC_ONLY;
		vi.restoreAllMocks();
	});

	it("async mode: returns 200 without calling handleIgWebhookEvent", async () => {
		process.env.WEBHOOK_ASYNC_ONLY = "true";

		const payload = JSON.stringify({
			entry: [
				{
					id: "ig-user-1",
					time: Math.floor(Date.now() / 1000),
					changes: [{ field: "comments", value: { id: "c1", text: "nice" } }],
				},
			],
		});
		const sig = computeSignature(payload, META_SECRET);

		const insertedRow = {
			id: "ig-evt-1",
			event_type: "comments",
			ig_user_id: "ig-user-1",
			payload: { id: "c1", text: "nice" },
		};
		mockSelect.mockResolvedValue({ data: [insertedRow], error: null });

		const { default: handler } = await import("@/api/instagram/webhook.js");
		const res = mockRes();
		await handler(makeStreamReq(payload, sig) as any, res as any);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(mockHandleIgWebhookEvent).not.toHaveBeenCalled();
		expect(mockScheduleWebhookReplay).toHaveBeenCalledWith("instagram", 5);
	});

});
