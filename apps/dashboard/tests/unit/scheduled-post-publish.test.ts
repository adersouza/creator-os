import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Unit tests for the scheduled-post-publish endpoint (QStash -> publish pipeline).
 *
 * Tests the critical paths:
 * 1. QStash signature verification — valid proceeds, invalid returns 401
 * 2. Body validation — missing/invalid postId returns 400
 * 3. Method not allowed — non-POST returns 405
 * 4. Post not found — returns 200 with reason "not_found" (non-retryable)
 * 5. Status validation — only "scheduled" posts get published
 * 6. Happy path — post published, returns 200
 * 7. Non-retryable error classification — certain errors return 200
 * 8. Retryable failures — returns 500 so QStash retries
 * 9. Unhandled exception — returns 500 with error message
 * 10. Exhaustive non-retryable error set coverage
 */

// ---------------------------------------------------------------------------
// Mocks — set up before module import
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();

vi.mock("../../api/_lib/supabase", () => ({
	getSupabase: () => ({
		from: mockFrom,
	}),
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

const mockVerifyQStashSignature = vi.fn();
vi.mock("../../api/_lib/qstash", () => ({
	verifyQStashSignature: (...args: unknown[]) => mockVerifyQStashSignature(...args),
}));

const mockPublishSinglePost = vi.fn();
vi.mock("../../api/_lib/publishPost", () => ({
	publishSinglePost: (...args: unknown[]) => mockPublishSinglePost(...args),
}));

interface MockRes {
	status: ReturnType<typeof vi.fn>;
	json: ReturnType<typeof vi.fn>;
}

vi.mock("../../api/_lib/apiResponse", () => ({
	apiError: (res: any, status: number, message: string) =>
		res.status(status).json({ error: message }),
}));

vi.mock("../../api/_lib/sentryServer", () => ({
	captureServerException: vi.fn().mockResolvedValue(undefined),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mockReq(body: Record<string, unknown>, method = "POST") {
	return { method, body } as unknown;
}

function mockRes(): MockRes {
	const res: MockRes = {
		status: vi.fn(),
		json: vi.fn(),
	};
	res.status.mockReturnValue(res);
	res.json.mockReturnValue(res);
	return res;
}

/** Build a chainable Supabase mock that resolves to the given value. */
function chainMock(finalValue: { data: unknown; error: unknown }) {
	const chain: Record<string, ReturnType<typeof vi.fn>> = {};
	const methods = [
		"select", "eq", "in", "not", "or", "gte", "lt", "lte",
		"maybeSingle", "single", "limit", "order", "update", "insert",
	];
	for (const m of methods) {
		if (m === "maybeSingle" || m === "single") {
			chain[m] = vi.fn().mockResolvedValue(finalValue);
		} else {
			chain[m] = vi.fn().mockReturnValue(chain);
		}
	}
	return chain;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("scheduled-post-publish handler", () => {
	let handler: (req: unknown, res: unknown) => Promise<unknown>;

	beforeEach(async () => {
		vi.clearAllMocks();
		// Default: QStash signature is valid
		mockVerifyQStashSignature.mockResolvedValue(true);
		// Re-import fresh handler each test
		const mod = await import("../../api/scheduled-post-publish");
		handler = mod.default as any;
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	// ── 1. QStash Signature Verification ──

	it("returns 401 when QStash signature is invalid", async () => {
		mockVerifyQStashSignature.mockImplementation(
			(_req: unknown, res: any) => {
				res.status(401).json({ error: "Invalid signature" });
				return Promise.resolve(false);
			},
		);

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(401);
		expect(mockPublishSinglePost).not.toHaveBeenCalled();
	});

	it("proceeds when QStash signature is valid", async () => {
		mockVerifyQStashSignature.mockResolvedValue(true);
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "scheduled" }, error: null }),
		);
		mockPublishSinglePost.mockResolvedValue({ result: "published" });

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(mockPublishSinglePost).toHaveBeenCalledWith("p1");
	});

	// ── 2. Body Validation ──

	it("returns 400 when postId is missing", async () => {
		const res = mockRes();
		await handler(mockReq({}), res);

		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				ok: false,
				skipped: true,
				reason: "invalid_body",
			}),
		);
		expect(mockPublishSinglePost).not.toHaveBeenCalled();
	});

	it("returns 400 when postId is empty string", async () => {
		const res = mockRes();
		await handler(mockReq({ postId: "" }), res);

		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				ok: false,
				skipped: true,
				reason: "invalid_body",
			}),
		);
	});

	// ── 3. Method Not Allowed ──

	it("returns 405 for non-POST requests", async () => {
		const res = mockRes();
		await handler(mockReq({ postId: "p1" }, "GET"), res);

		expect(res.status).toHaveBeenCalledWith(405);
	});

	// ── 4. Post Not Found — Returns 200 (Non-Retryable) ──

	it("returns 200 with reason not_found when post does not exist", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: null, error: null }),
		);

		const res = mockRes();
		await handler(mockReq({ postId: "nonexistent" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, skipped: true, reason: "not_found" }),
		);
		expect(mockPublishSinglePost).not.toHaveBeenCalled();
	});

	// ── 5. Status Validation — Only "scheduled" Posts Get Published ──

	it("skips with 200 when post status is published", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "published" }, error: null }),
		);

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, skipped: true, reason: "published" }),
		);
		expect(mockPublishSinglePost).not.toHaveBeenCalled();
	});

	it("skips with 200 when post status is draft", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "draft" }, error: null }),
		);

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, skipped: true, reason: "draft" }),
		);
		expect(mockPublishSinglePost).not.toHaveBeenCalled();
	});

	it("skips with 200 when post status is failed", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "failed" }, error: null }),
		);

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, skipped: true, reason: "failed" }),
		);
		expect(mockPublishSinglePost).not.toHaveBeenCalled();
	});

	it("skips stale exact-time messages when the post was rescheduled later", async () => {
		const later = new Date(Date.now() + 10 * 60 * 1000).toISOString();
		mockFrom.mockReturnValue(
			chainMock({
				data: { id: "p1", status: "scheduled", scheduled_for: later },
				error: null,
			}),
		);

		const res = mockRes();
		await handler(mockReq({ postId: "p1", traceId: "trace-old" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, skipped: true, reason: "not_due" }),
		);
		expect(mockPublishSinglePost).not.toHaveBeenCalled();
	});

	// ── 6. Happy Path — Scheduled Post Published ──

	it("publishes a scheduled post and returns 200", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "scheduled" }, error: null }),
		);
		mockPublishSinglePost.mockResolvedValue({
			result: "published",
			threadId: "t123",
		});

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(mockPublishSinglePost).toHaveBeenCalledWith("p1");
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, result: "published", threadId: "t123" }),
		);
	});

	// ── 7. Non-Retryable Results — Return 200 So QStash Stops ──

	it("returns 200 for container_pending result (non-retryable)", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "scheduled" }, error: null }),
		);
		mockPublishSinglePost.mockResolvedValue({ result: "container_pending" });

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, result: "container_pending" }),
		);
	});

	it("returns 200 for rescheduled result", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "scheduled" }, error: null }),
		);
		mockPublishSinglePost.mockResolvedValue({ result: "rescheduled" });

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, result: "rescheduled" }),
		);
	});

	it("returns 200 for skipped with non-retryable error (not_found from publisher)", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "scheduled" }, error: null }),
		);
		mockPublishSinglePost.mockResolvedValue({
			result: "skipped",
			error: "not_found",
		});

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, result: "skipped", error: "not_found" }),
		);
	});

	it("returns 200 for skipped with claim_failed (non-retryable)", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "scheduled" }, error: null }),
		);
		mockPublishSinglePost.mockResolvedValue({
			result: "skipped",
			error: "claim_failed",
		});

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, result: "skipped", error: "claim_failed" }),
		);
	});

	it("returns 200 for skipped with account_not_configured (non-retryable)", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "scheduled" }, error: null }),
		);
		mockPublishSinglePost.mockResolvedValue({
			result: "skipped",
			error: "account_not_configured",
		});

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
	});

	it("returns 200 for skipped with empty_content (non-retryable)", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "scheduled" }, error: null }),
		);
		mockPublishSinglePost.mockResolvedValue({
			result: "skipped",
			error: "empty_content",
		});

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
	});

	// ── 8. Retryable Failures — Return 500 So QStash Retries ──

	it("returns 500 for failed result (retryable)", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "scheduled" }, error: null }),
		);
		mockPublishSinglePost.mockResolvedValue({
			result: "failed",
			error: "meta_api_timeout",
		});

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(500);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: false, result: "failed" }),
		);
	});

	it("returns 500 for skipped with retryable error", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "scheduled" }, error: null }),
		);
		mockPublishSinglePost.mockResolvedValue({
			result: "skipped",
			error: "some_transient_error",
		});

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(500);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: false, result: "skipped" }),
		);
	});

	// ── 9. Unhandled Exception ──

	it("returns 500 on unhandled exception", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "scheduled" }, error: null }),
		);
		mockPublishSinglePost.mockRejectedValue(new Error("Unexpected DB crash"));

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(500);
		// Error message is sanitized to "publish_failed" — raw exception text is
		// only logged server-side (avoid leaking internals to the response).
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: false, result: "error", error: "publish_failed" }),
		);
	});

	it("returns 500 with stringified non-Error exception", async () => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "scheduled" }, error: null }),
		);
		mockPublishSinglePost.mockRejectedValue("string error");

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(500);
		// Error message is sanitized to "publish_failed" regardless of input shape.
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: false, result: "error", error: "publish_failed" }),
		);
	});

	// ── 10. Non-Retryable Error Set Completeness ──

	it.each([
		"not_found",
		"not_found_or_not_scheduled",
		"claim_failed",
		"status_changed_before_publish",
		"status_changed_before_chain_publish",
		"account_not_configured",
		"empty_content",
		"content_too_long",
		"caption_too_long",
		"story_no_media",
		"media_inaccessible",
		"chain_post_too_long",
	])("returns 200 for non-retryable skip error: %s", async (errorCode) => {
		mockFrom.mockReturnValue(
			chainMock({ data: { id: "p1", status: "scheduled" }, error: null }),
		);
		mockPublishSinglePost.mockResolvedValue({
			result: "skipped",
			error: errorCode,
		});

		const res = mockRes();
		await handler(mockReq({ postId: "p1" }), res);

		expect(res.status).toHaveBeenCalledWith(200);
	});
});
