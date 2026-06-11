import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFrom = vi.fn();
const mockVerifyWorkspaceAccess = vi.fn().mockResolvedValue(true);
const mockVerifyGroupBelongsToWorkspace = vi.fn().mockResolvedValue(true);
const mockRequireMinTier = vi.fn().mockResolvedValue(true);
const mockQstashDelete = vi.fn().mockResolvedValue(undefined);

vi.mock("../../api/_lib/handlers/auto-post/route/routeHelpers", () => ({
	db: () => ({ from: mockFrom }),
	resolveWorkspaceId: vi.fn(),
	verifyWorkspaceAccess: (...args: unknown[]) => mockVerifyWorkspaceAccess(...args),
	verifyGroupBelongsToWorkspace: (...args: unknown[]) => mockVerifyGroupBelongsToWorkspace(...args),
}));

vi.mock("../../api/_lib/tierGate", () => ({
	requireMinTier: (...args: unknown[]) => mockRequireMinTier(...args),
}));

vi.mock("../../api/_lib/apiResponse", () => ({
	apiError: (res: any, status: number, error: string) =>
		res.status(status).json({ error }),
	apiSuccess: (res: any, data?: Record<string, unknown>) =>
		res.status(200).json({ success: true, ...data }),
}));

vi.mock("../../api/_lib/qstash", () => ({
	getQStashClient: () => ({
		messages: {
			delete: (...args: unknown[]) => mockQstashDelete(...args),
		},
	}),
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("../../api/_lib/supabase", () => ({
	getSupabase: () => ({ from: mockFrom }),
	getSupabaseAny: () => ({ from: mockFrom }),
}));

function chainMock(finalValue: { data?: unknown; error?: unknown; count?: number }) {
	const chain: Record<string, any> = {};
	const methods = [
		"select", "eq", "in", "not", "or", "gte", "lt", "lte",
		"maybeSingle", "single", "limit", "order", "update", "insert", "delete",
	];
	for (const m of methods) {
		if (m === "maybeSingle" || m === "single") {
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

describe("auto-post queue handlers", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockRequireMinTier.mockResolvedValue(true);
		mockVerifyWorkspaceAccess.mockResolvedValue(true);
		mockVerifyGroupBelongsToWorkspace.mockResolvedValue(true);
		mockQstashDelete.mockResolvedValue(undefined);
	});

	it("retry dead letter restores a schedulable pool item", async () => {
		let updatePayload: Record<string, unknown> | null = null;

		mockFrom.mockImplementation((table: string) => {
			if (table !== "auto_post_queue") return chainMock({});

			const fetchChain = chainMock({
				data: {
					id: "q1",
					workspace_id: "ws1",
					group_id: "g1",
					status: "dead_letter",
					content: "test",
					last_error: "bad media",
					retry_count: 3,
					scheduled_for: null,
					source_type: "ai",
					created_at: "2026-04-08T00:00:00.000Z",
				},
				error: null,
			});
			fetchChain.update = vi.fn((payload: Record<string, unknown>) => {
				updatePayload = payload;
				return fetchChain;
			});
			return fetchChain;
		});

		const { handleRetryDeadLetter } = await import("../../api/_lib/handlers/auto-post/route/queueHandlers");
		const res = mockRes();

		await handleRetryDeadLetter(
			{ body: { queueItemId: "q1", dryRun: false } } as any,
			res,
			"user-1",
		);

		expect(updatePayload).toEqual(expect.objectContaining({
			status: "pending",
			pool_status: "available",
			account_id: null,
			retry_count: 0,
			last_error: null,
			schedule_nonce: null,
			qstash_message_id: null,
		}));
		expect(res.status).toHaveBeenCalledWith(200);
	});

	it("delete queue item cancels an outstanding QStash message for queued items", async () => {
		let call = 0;

		mockFrom.mockImplementation((table: string) => {
			if (table !== "auto_post_queue") return chainMock({});
			call += 1;
			if (call === 1) {
				return chainMock({
					data: {
						id: "q1",
						workspace_id: "ws1",
						group_id: "g1",
						status: "queued",
						content: "queued post",
						qstash_message_id: "msg-123",
					},
					error: null,
				});
			}
			// Second call: hardDeleteQueueItems — .delete().in().select()
			return chainMock({ data: [{ id: "q1" }], error: null });
		});

		const { handleDeleteQueueItem } = await import("../../api/_lib/handlers/auto-post/route/queueHandlers");
		const res = mockRes();

		await handleDeleteQueueItem(
			{ body: { queueItemId: "q1", dryRun: false } } as any,
			res,
			"user-1",
		);

		expect(mockQstashDelete).toHaveBeenCalledWith("msg-123");
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(expect.objectContaining({
			cancelled: true,
			deleted: true,
		}));
	});
});
