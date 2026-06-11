import { afterEach, describe, expect, it, vi } from "vitest";
import {
	claimQueueItemForPublish,
	explainQueueItemPublishClaim,
	isClaimableQueueStatus,
	isReschedulableQueueStatus,
	isTerminalQueueStatus,
	poolStatusForQueueStatus,
	type AutoPostQueueItem,
} from "../../api/_lib/handlers/auto-post/queueState";

const mockRpc = vi.fn();
const mockFrom = vi.fn();
const mockLoggerError = vi.fn();
const mockLoggerWarn = vi.fn();

vi.mock("../../api/_lib/supabase", () => ({
	getSupabaseAny: () => ({
		from: mockFrom,
		rpc: mockRpc,
	}),
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: {
		error: (...args: unknown[]) => mockLoggerError(...args),
		warn: (...args: unknown[]) => mockLoggerWarn(...args),
		info: vi.fn(),
		debug: vi.fn(),
	},
}));

function queueItem(
	overrides: Partial<AutoPostQueueItem> = {},
): Pick<
	AutoPostQueueItem,
	| "status"
	| "scheduled_for"
	| "next_retry_at"
	| "schedule_nonce"
	| "claim_token"
	| "claim_expires_at"
> {
	return {
		status: "queued",
		scheduled_for: "2026-06-06T10:00:00.000Z",
		next_retry_at: null,
		schedule_nonce: "nonce-1",
		claim_token: null,
		claim_expires_at: null,
		...overrides,
	};
}

describe("auto-post queue publish claim", () => {
	afterEach(() => {
		vi.clearAllMocks();
	});

	it("claims a due queued winner-clone row with matching scheduleNonce", async () => {
		mockRpc.mockResolvedValueOnce({
			data: [{ id: "00000000-0000-0000-0000-000000000001" }],
			error: null,
		});

		const token = await claimQueueItemForPublish(
			"00000000-0000-0000-0000-000000000001",
			{
				scheduleNonce: "nonce-1",
				now: new Date("2026-06-06T11:00:00.000Z"),
			},
		);

		expect(token).toEqual(expect.any(String));
		expect(mockRpc).toHaveBeenCalledWith(
			"claim_auto_post_queue_item_for_publish",
			expect.objectContaining({
				p_queue_item_id: "00000000-0000-0000-0000-000000000001",
				p_schedule_nonce: "nonce-1",
				p_now: "2026-06-06T11:00:00.000Z",
			}),
		);
		expect(mockFrom).not.toHaveBeenCalled();
	});

	it("allows a pool-mode row with account_id null because claim does not require account assignment", () => {
		const reasons = explainQueueItemPublishClaim(
			queueItem({
				schedule_nonce: null,
			}),
			{
				scheduleNonce: null,
				now: new Date("2026-06-06T11:00:00.000Z"),
			},
		);

		expect(reasons).toEqual([]);
	});

	it("rejects stale scheduleNonce", () => {
		const reasons = explainQueueItemPublishClaim(queueItem(), {
			scheduleNonce: "old-nonce",
			now: new Date("2026-06-06T11:00:00.000Z"),
		});

		expect(reasons).toContain("stale_schedule_nonce");
	});

	it("rejects future scheduled_for", () => {
		const reasons = explainQueueItemPublishClaim(
			queueItem({ scheduled_for: "2026-06-06T12:00:00.000Z" }),
			{
				scheduleNonce: "nonce-1",
				now: new Date("2026-06-06T11:00:00.000Z"),
			},
		);

		expect(reasons).toContain("future_scheduled_for");
	});

	it("rejects future next_retry_at", () => {
		const reasons = explainQueueItemPublishClaim(
			queueItem({ next_retry_at: "2026-06-06T11:30:00.000Z" }),
			{
				scheduleNonce: "nonce-1",
				now: new Date("2026-06-06T11:00:00.000Z"),
			},
		);

		expect(reasons).toContain("future_next_retry_at");
	});

	it("rejects an existing unexpired claim", () => {
		const reasons = explainQueueItemPublishClaim(
			queueItem({
				claim_token: "active-claim",
				claim_expires_at: "2026-06-06T11:10:00.000Z",
			}),
			{
				scheduleNonce: "nonce-1",
				now: new Date("2026-06-06T11:00:00.000Z"),
			},
		);

		expect(reasons).toContain("unexpired_claim");
	});

	it("allows an expired claim to be reclaimed", () => {
		const reasons = explainQueueItemPublishClaim(
			queueItem({
				claim_token: "expired-claim",
				claim_expires_at: "2026-06-06T10:59:00.000Z",
			}),
			{
				scheduleNonce: "nonce-1",
				now: new Date("2026-06-06T11:00:00.000Z"),
			},
		);

		expect(reasons).toEqual([]);
	});

	it("rejects wrong status", () => {
		const reasons = explainQueueItemPublishClaim(
			queueItem({ status: "needs_review" }),
			{
				scheduleNonce: "nonce-1",
				now: new Date("2026-06-06T11:00:00.000Z"),
			},
		);

		expect(reasons).toContain("wrong_status");
	});

	it("defines the official queue lifecycle predicates", () => {
		expect(isClaimableQueueStatus("pending")).toBe(true);
		expect(isClaimableQueueStatus("queued")).toBe(true);
		expect(isClaimableQueueStatus("publishing")).toBe(false);
		expect(isClaimableQueueStatus("needs_review")).toBe(false);

		expect(isTerminalQueueStatus("published")).toBe(true);
		expect(isTerminalQueueStatus("rejected")).toBe(true);
		expect(isTerminalQueueStatus("dead_letter")).toBe(true);
		expect(isTerminalQueueStatus("cancelled")).toBe(true);
		expect(isTerminalQueueStatus("publishing")).toBe(false);

		expect(isReschedulableQueueStatus("pending")).toBe(true);
		expect(isReschedulableQueueStatus("queued")).toBe(true);
		expect(isReschedulableQueueStatus("publishing")).toBe(true);
		expect(isReschedulableQueueStatus("published")).toBe(false);
	});

	it("documents pool_status semantics for pool and assigned rows", () => {
		expect(poolStatusForQueueStatus("pending")).toBe("available");
		expect(poolStatusForQueueStatus("queued", false)).toBe("available");
		expect(poolStatusForQueueStatus("queued", true)).toBe("claimed");
		expect(poolStatusForQueueStatus("publishing")).toBe("claimed");
		expect(poolStatusForQueueStatus("published")).toBe("claimed");
		expect(poolStatusForQueueStatus("dead_letter")).toBeNull();
	});
});
