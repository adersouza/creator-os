import { beforeEach, describe, expect, it, vi } from "vitest";

const mockVerifyCronAuth = vi.fn().mockReturnValue(true);
const mockPublishJSON = vi.fn().mockResolvedValue({ messageId: "msg-1" });
const mockRecordInfraEvent = vi.fn().mockResolvedValue(undefined);
const mockFrom = vi.fn();

vi.mock("../../api/_lib/apiResponse", () => ({
	verifyCronAuth: (...args: unknown[]) => mockVerifyCronAuth(...args),
	apiError: (res: any, status: number, error: string) => res.status(status).json({ error }),
	apiSuccess: (res: any, data?: Record<string, unknown>) => res.status(200).json({ success: true, ...data }),
}));

vi.mock("../../api/_lib/qstash", () => ({
	getQStashClient: () => ({
		publishJSON: (...args: unknown[]) => mockPublishJSON(...args),
	}),
}));

vi.mock("../../api/_lib/qstashDefaults", () => ({
	RETRIES: { CRITICAL: 3 },
	getRequiredAppBaseUrl: () => "https://juno33.com",
	getFailureCallbackUrl: () => "https://juno33.com/api/qstash-failure",
}));

vi.mock("../../api/_lib/infraTelemetry", () => ({
	recordInfraEvent: (...args: unknown[]) => mockRecordInfraEvent(...args),
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

vi.mock("../../api/_lib/supabase", () => ({
	getSupabase: () => ({ from: mockFrom }),
}));

function chainMock(finalValue: { data?: unknown; error?: unknown }) {
	const chain: Record<string, any> = {};
	const methods = ["select", "eq", "is", "order", "limit", "in", "update", "maybeSingle"];
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

describe("dispatch-manual-queue", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockVerifyCronAuth.mockReturnValue(true);
		mockPublishJSON.mockResolvedValue({ messageId: "msg-1" });
	});

	it("dispatches each item with its group's owner and reuses schedule_nonce as dedup key", async () => {
		const updates: Array<Record<string, unknown>> = [];
		let queueReads = 0;

		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				queueReads += 1;
				if (queueReads === 1) {
					return chainMock({
						data: [
							{ id: "q1", workspace_id: "ws1", group_id: "g1", scheduled_for: "2026-04-08T12:00:00.000Z", schedule_nonce: "sched-q1" },
							{ id: "q2", workspace_id: "ws2", group_id: "g2", scheduled_for: "2026-04-08T13:00:00.000Z", schedule_nonce: "sched-q2" },
						],
						error: null,
					});
				}
				const chain = chainMock({ data: null, error: null });
				chain.update = vi.fn((payload: Record<string, unknown>) => {
					updates.push(payload);
					return chain;
				});
				return chain;
			}
			if (table === "account_groups") {
				return chainMock({
					data: [
						{ id: "g1", name: "Group 1", user_id: "owner-1" },
						{ id: "g2", name: "Group 2", user_id: "owner-2" },
					],
					error: null,
				});
			}
			return chainMock({ data: null, error: null });
		});

		const handler = (await import("../../api/dispatch-manual-queue")).default;
		const res = mockRes();
		await handler({ method: "POST", headers: {}, body: {} } as any, res);

		expect(mockPublishJSON).toHaveBeenNthCalledWith(1, expect.objectContaining({
			body: expect.objectContaining({ queueItemId: "q1", ownerId: "owner-1", groupId: "g1", groupName: "Group 1" }),
			deduplicationId: "sched-q1",
			failureCallback: "https://juno33.com/api/qstash-failure",
			retries: 3,
		}));
		expect(mockPublishJSON).toHaveBeenNthCalledWith(2, expect.objectContaining({
			body: expect.objectContaining({ queueItemId: "q2", ownerId: "owner-2", groupId: "g2", groupName: "Group 2" }),
			deduplicationId: "sched-q2",
			failureCallback: "https://juno33.com/api/qstash-failure",
			retries: 3,
		}));
		expect(updates).toEqual(expect.arrayContaining([
			expect.objectContaining({ qstash_message_id: "msg-1", schedule_nonce: "sched-q1" }),
			expect.objectContaining({ qstash_message_id: "msg-1", schedule_nonce: "sched-q2" }),
		]));
		expect(res.status).toHaveBeenCalledWith(200);
	});
});
