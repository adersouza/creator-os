import { beforeEach, describe, expect, it, vi } from "vitest";
import { withIdempotency } from "../idempotency.js";

const mockFrom = vi.fn();

vi.mock("../supabase.js", () => ({
	getSupabaseAny: () => ({ from: (...args: unknown[]) => mockFrom(...args) }),
}));

vi.mock("../logger.js", () => ({
	logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

// biome-ignore lint/suspicious/noExplicitAny: lightweight Vercel response test double
function mockRes(): any {
	const res: Record<string, unknown> = {};
	res.status = vi.fn().mockReturnValue(res);
	res.json = vi.fn().mockReturnValue(res);
	res.setHeader = vi.fn().mockReturnValue(res);
	return res;
}

function insertResult(error: unknown = null) {
	return {
		insert: vi.fn().mockResolvedValue({ error }),
	};
}

function replayResult(row: unknown) {
	return {
		insert: vi.fn().mockResolvedValue({ error: { code: "23505" } }),
		select: vi.fn().mockReturnValue({
			eq: vi.fn().mockReturnThis(),
			maybeSingle: vi.fn().mockResolvedValue({ data: row, error: null }),
		}),
	};
}

describe("withIdempotency", () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it("bypasses when no Idempotency-Key is present", async () => {
		const res = mockRes();
		const handler = vi.fn().mockResolvedValue(res);

		await withIdempotency(
			{ headers: {}, body: { content: "hello" } } as never,
			res as never,
			{ userId: "user-1", route: "posts", action: "publish", enabled: true },
			handler,
		);

		expect(handler).toHaveBeenCalledOnce();
		expect(mockFrom).not.toHaveBeenCalled();
	});

	it("claims and records completed responses", async () => {
		const update = vi.fn().mockReturnValue({
			eq: vi.fn().mockReturnThis(),
		});
		mockFrom
			.mockReturnValueOnce(insertResult())
			.mockReturnValueOnce({ update });
		const res = mockRes();

		await withIdempotency(
			{
				headers: { "idempotency-key": "publish-1" },
				body: { content: "hello" },
			} as never,
			res as never,
			{ userId: "user-1", route: "posts", action: "publish", enabled: true },
			async () => {
				res.status(201);
				res.json({ success: true, postId: "p1" });
				return res as never;
			},
		);

		expect(update).toHaveBeenCalledWith(
			expect.objectContaining({
				status: "completed",
				response_status: 201,
				response_body: { success: true, postId: "p1" },
			}),
		);
	});

	it("replays completed duplicate requests", async () => {
		const res = mockRes();
		mockFrom.mockReturnValue(
			replayResult({
				status: "completed",
				payload_hash:
					"20b2dda940d741d9780897200aaef2ef356ab32b38c7de0d94306fb5a66b4a8e",
				response_status: 200,
				response_body: { success: true, postId: "p1" },
			}),
		);
		const handler = vi.fn();

		await withIdempotency(
			{
				headers: { "idempotency-key": "publish-1" },
				body: { content: "hello" },
			} as never,
			res as never,
			{ userId: "user-1", route: "posts", action: "publish", enabled: true },
			handler,
		);

		expect(handler).not.toHaveBeenCalled();
		expect(res.setHeader).toHaveBeenCalledWith("x-idempotent-replay", "true");
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith({ success: true, postId: "p1" });
	});

	it("rejects duplicate keys with different payloads", async () => {
		const res = mockRes();
		mockFrom.mockReturnValue(
			replayResult({
				status: "completed",
				payload_hash: "different",
				response_status: 200,
				response_body: { success: true },
			}),
		);

		await withIdempotency(
			{
				headers: { "idempotency-key": "publish-1" },
				body: { content: "hello" },
			} as never,
			res as never,
			{ userId: "user-1", route: "posts", action: "publish", enabled: true },
			vi.fn(),
		);

		expect(res.status).toHaveBeenCalledWith(409);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ code: "IDEMPOTENCY_PAYLOAD_MISMATCH" }),
		);
	});

	it("requires a key when configured for high-risk writes", async () => {
		const res = mockRes();
		const handler = vi.fn();

		await withIdempotency(
			{ headers: {}, body: { content: "hello" } } as never,
			res as never,
			{
				userId: "user-1",
				route: "posts",
				action: "publish",
				enabled: true,
				requireKey: true,
				failClosed: true,
			},
			handler,
		);

		expect(handler).not.toHaveBeenCalled();
		expect(res.status).toHaveBeenCalledWith(428);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ code: "IDEMPOTENCY_KEY_REQUIRED" }),
		);
	});

	it("fails closed when the idempotency store is unavailable", async () => {
		const res = mockRes();
		const handler = vi.fn();
		mockFrom.mockReturnValue(insertResult({ code: "500", message: "redis down" }));

		await withIdempotency(
			{
				headers: { "idempotency-key": "publish-1" },
				body: { content: "hello" },
			} as never,
			res as never,
			{
				userId: "user-1",
				route: "posts",
				action: "publish",
				enabled: true,
				requireKey: true,
				failClosed: true,
			},
			handler,
		);

		expect(handler).not.toHaveBeenCalled();
		expect(res.status).toHaveBeenCalledWith(503);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ code: "IDEMPOTENCY_UNAVAILABLE" }),
		);
	});
});
