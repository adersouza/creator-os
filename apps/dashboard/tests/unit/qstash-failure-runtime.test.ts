import { beforeEach, describe, expect, it, vi } from "vitest";

const mockVerifyQStashSignature = vi.fn().mockResolvedValue(true);
const mockAlert = vi.fn().mockResolvedValue(undefined);
const mockRecordInfraEvent = vi.fn().mockResolvedValue(undefined);
const mockCaptureServerException = vi.fn().mockResolvedValue(undefined);
const mockFrom = vi.fn();

vi.mock("../../api/_lib/qstash", () => ({
	verifyQStashSignature: (...args: unknown[]) => mockVerifyQStashSignature(...args),
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
	summarizeUserContent: (value: unknown) => ({ redacted: true, valueType: typeof value }),
}));

vi.mock("../../api/_lib/alerting", () => ({
	alert: (...args: unknown[]) => mockAlert(...args),
	AlertLevel: { ERROR: "error" },
}));

vi.mock("../../api/_lib/infraTelemetry", () => ({
	recordInfraEvent: (...args: unknown[]) => mockRecordInfraEvent(...args),
}));

vi.mock("../../api/_lib/sentryServer", () => ({
	captureServerException: (...args: unknown[]) => mockCaptureServerException(...args),
}));

vi.mock("../../api/_lib/supabase", () => ({
	getSupabaseAny: () => ({ from: mockFrom }),
}));

function chainMock(finalValue: { data?: unknown; error?: unknown }) {
	const chain: Record<string, any> = {};
	const methods = ["select", "eq", "in", "update", "maybeSingle"];
	for (const m of methods) {
		if (m === "maybeSingle") {
			chain[m] = vi.fn().mockResolvedValue(finalValue);
		} else {
			chain[m] = vi.fn().mockReturnValue(chain);
		}
	}
	chain.then = (resolve: (v: unknown) => unknown) => Promise.resolve(finalValue).then(resolve);
	return chain;
}

function mockRes() {
	const res: any = {
		status: vi.fn(),
		json: vi.fn(),
	};
	res.status.mockReturnValue(res);
	res.json.mockReturnValue(res);
	return res;
}

describe("qstash failure runtime handler", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockVerifyQStashSignature.mockResolvedValue(true);
	});

	it("decodes sourceBody and dead-letters the matching queue item", async () => {
		const updates: Array<Record<string, unknown>> = [];

		mockFrom.mockImplementation((table: string) => {
			const chain = chainMock({
				data: table === "auto_post_queue"
					? {
						status: "queued",
						schedule_nonce: "sched-1",
						qstash_message_id: "msg-1",
						workspace_id: "ws1",
						group_id: "g1",
					}
					: null,
				error: null,
			});
			chain.update = vi.fn((payload: Record<string, unknown>) => {
				updates.push({ table, ...payload });
				return chain;
			});
			return chain;
		});

		const handler = (await import("../../api/qstash-failure")).default;
		const res = mockRes();
		const sourceBody = Buffer.from(JSON.stringify({ queueItemId: "q1" }), "utf8").toString("base64");

		await handler({
			method: "POST",
			body: { sourceBody, sourceMessageId: "msg-1" },
			headers: {},
		} as any, res);

		expect(updates).toEqual(expect.arrayContaining([
			expect.objectContaining({
				table: "auto_post_queue",
				status: "dead_letter",
				qstash_message_id: null,
				schedule_nonce: null,
			}),
		]));
		expect(mockRecordInfraEvent).toHaveBeenCalledWith(
			"qstash-dlq-autopost",
			expect.objectContaining({ queueItemId: "q1", sourceMessageId: "msg-1" }),
		);
		expect(res.status).toHaveBeenCalledWith(200);
	});

	it("ignores stale failure callbacks for superseded qstash message ids", async () => {
		const updates: Array<Record<string, unknown>> = [];

		mockFrom.mockImplementation((table: string) => {
			const chain = chainMock({
				data: table === "auto_post_queue"
					? {
						status: "queued",
						schedule_nonce: "sched-new",
						qstash_message_id: "msg-new",
						workspace_id: "ws1",
						group_id: "g1",
					}
					: null,
				error: null,
			});
			chain.update = vi.fn((payload: Record<string, unknown>) => {
				updates.push({ table, ...payload });
				return chain;
			});
			return chain;
		});

		const handler = (await import("../../api/qstash-failure")).default;
		const res = mockRes();
		const sourceBody = Buffer.from(JSON.stringify({ queueItemId: "q1" }), "utf8").toString("base64");

		await handler({
			method: "POST",
			body: { sourceBody, sourceMessageId: "msg-old" },
			headers: {},
		} as any, res);

		expect(updates.find((u) => u.table === "auto_post_queue" && u.status === "dead_letter")).toBeUndefined();
		expect(mockRecordInfraEvent).toHaveBeenCalledWith(
			"qstash-dlq-autopost-stale-callback",
			expect.objectContaining({ queueItemId: "q1", sourceMessageId: "msg-old", currentQstashMessageId: "msg-new" }),
		);
		expect(res.status).toHaveBeenCalledWith(200);
	});

	it("marks the matching scheduled post as failed", async () => {
		const updates: Array<Record<string, unknown>> = [];

		mockFrom.mockImplementation((table: string) => {
			const chain = chainMock({
				data: table === "posts"
					? {
						status: "scheduled",
						metadata: { qstash_message_id: "post-msg-1" },
						user_id: "user-1",
					}
					: null,
				error: null,
			});
			chain.update = vi.fn((payload: Record<string, unknown>) => {
				updates.push({ table, ...payload });
				return chain;
			});
			return chain;
		});

		const handler = (await import("../../api/qstash-failure")).default;
		const res = mockRes();
		const sourceBody = Buffer.from(JSON.stringify({ postId: "post-1" }), "utf8").toString("base64");

		await handler({
			method: "POST",
			body: { sourceBody, sourceMessageId: "post-msg-1" },
			headers: {},
		} as any, res);

		expect(updates).toEqual(expect.arrayContaining([
			expect.objectContaining({
				table: "posts",
				status: "failed",
				error_message: "QStash retries exhausted",
			}),
		]));
		expect(mockRecordInfraEvent).toHaveBeenCalledWith(
			"qstash-dlq-scheduled-post",
			expect.objectContaining({ postId: "post-1", sourceMessageId: "post-msg-1" }),
		);
		expect(res.status).toHaveBeenCalledWith(200);
	});

	it("ignores stale failure callbacks for superseded scheduled post messages", async () => {
		const updates: Array<Record<string, unknown>> = [];

		mockFrom.mockImplementation((table: string) => {
			const chain = chainMock({
				data: table === "posts"
					? {
						status: "scheduled",
						metadata: { qstash_message_id: "post-msg-new" },
						user_id: "user-1",
					}
					: null,
				error: null,
			});
			chain.update = vi.fn((payload: Record<string, unknown>) => {
				updates.push({ table, ...payload });
				return chain;
			});
			return chain;
		});

		const handler = (await import("../../api/qstash-failure")).default;
		const res = mockRes();
		const sourceBody = Buffer.from(JSON.stringify({ postId: "post-1" }), "utf8").toString("base64");

		await handler({
			method: "POST",
			body: { sourceBody, sourceMessageId: "post-msg-old" },
			headers: {},
		} as any, res);

		expect(updates.find((u) => u.table === "posts" && u.status === "failed")).toBeUndefined();
		expect(mockRecordInfraEvent).toHaveBeenCalledWith(
			"qstash-dlq-scheduled-post-stale-callback",
			expect.objectContaining({
				postId: "post-1",
				sourceMessageId: "post-msg-old",
				currentQstashMessageId: "post-msg-new",
			}),
		);
		expect(res.status).toHaveBeenCalledWith(200);
	});
});
