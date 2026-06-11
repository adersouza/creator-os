import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPublishJob, getPublishJobStatus } from "../publishJobs.js";

const mockFrom = vi.fn();
const mockPublishJSON = vi.fn();

vi.mock("../supabase.js", () => ({
	getSupabaseAny: () => ({ from: (...args: unknown[]) => mockFrom(...args) }),
}));

vi.mock("../qstash.js", () => ({
	getQStashClient: () => ({ publishJSON: (...args: unknown[]) => mockPublishJSON(...args) }),
}));

vi.mock("../qstashDefaults.js", () => ({
	getRequiredAppBaseUrl: () => "https://juno33.com",
	getFailureCallbackUrl: () => "https://juno33.com/api/qstash-failure",
	RETRIES: { CRITICAL: 3 },
}));

vi.mock("../requestId.js", () => ({
	getOrCreateRequestId: () => "00000000-0000-4000-8000-000000000001",
}));

vi.mock("../logger.js", () => ({
	logger: { warn: vi.fn(), error: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

function mockRes() {
	const res: Record<string, unknown> = { statusCode: 200 };
	res.setHeader = vi.fn().mockReturnValue(res);
	res.status = vi.fn((status: number) => {
		res.statusCode = status;
		return res;
	});
	res.json = vi.fn().mockReturnValue(res);
	return res;
}

function selectSingle(data: unknown, error: unknown = null) {
	const chain: Record<string, unknown> = {};
	chain.select = vi.fn(() => chain);
	chain.eq = vi.fn(() => chain);
	chain.maybeSingle = vi.fn().mockResolvedValue({ data, error });
	return chain;
}

describe("publishJobs", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockPublishJSON.mockResolvedValue({ messageId: "msg-1" });
	});

	it("creates a queued publish job and dispatches the worker", async () => {
		const insertChain: Record<string, unknown> = {};
		insertChain.insert = vi.fn(() => insertChain);
		insertChain.select = vi.fn(() => insertChain);
		insertChain.maybeSingle = vi.fn().mockResolvedValue({
			data: { id: "job-1", status: "queued", stage: "queued", request_id: "req-1" },
			error: null,
		});
		const updateChain = { update: vi.fn(() => ({ eq: vi.fn() })) };
		mockFrom
			.mockReturnValueOnce(selectSingle(null))
			.mockReturnValueOnce(insertChain)
			.mockReturnValueOnce(updateChain);

		const res = mockRes();
		await createPublishJob(
			{
				headers: { "idempotency-key": "key-1" },
				body: { platform: "threads", accountId: "acct-1", content: "hello" },
			} as never,
			res as never,
			"user-1",
		);

		expect(insertChain.insert).toHaveBeenCalledWith(expect.objectContaining({
			user_id: "user-1",
			platform: "threads",
			account_id: "acct-1",
			status: "queued",
			stage: "queued",
			idempotency_key: "key-1",
		}));
		expect(mockPublishJSON).toHaveBeenCalledWith(expect.objectContaining({
			url: "https://juno33.com/api/jobs?action=publish-worker",
			body: { jobId: "job-1" },
			retries: 3,
		}));
		expect(res.status).toHaveBeenCalledWith(202);
		expect(res.json).toHaveBeenCalledWith(expect.objectContaining({ jobId: "job-1" }));
	});

	it("returns only the authenticated user's publish job status", async () => {
		const statusChain: Record<string, unknown> = {};
		statusChain.select = vi.fn(() => statusChain);
		statusChain.eq = vi.fn(() => statusChain);
		statusChain.maybeSingle = vi.fn().mockResolvedValue({
			data: { id: "job-1", status: "published", stage: "published", result: { postId: "p1" } },
			error: null,
		});
		mockFrom.mockReturnValueOnce(statusChain);
		const res = mockRes();

		await getPublishJobStatus(
			{ query: { id: "job-1" } } as never,
			res as never,
			"user-1",
		);

		expect(statusChain.eq).toHaveBeenCalledWith("id", "job-1");
		expect(statusChain.eq).toHaveBeenCalledWith("user_id", "user-1");
		expect(res.json).toHaveBeenCalledWith(expect.objectContaining({
			jobId: "job-1",
			status: "published",
			result: { postId: "p1" },
		}));
	});
});
