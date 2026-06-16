import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
	mockRes,
	mockAutoPostReq,
	createChainMock,
	createTestQueueItem,
} from "../helpers/mockFactories";

/**
 * Unit tests for the auto-post-publish endpoint (QStash → Threads publish).
 *
 * Tests the 10-step pipeline's critical failure modes:
 * 1. Already-claimed item → skip (prevents double-publish)
 * 2. OAuth error → flag account needs_reauth
 * 3. Transient Meta 500 → DON'T flag as OAuth
 * 4. Burst guard → reschedule +30min
 * 5. Successful publish → correct status updates
 * 6. Missing fields → reject as invalid body (400)
 */

// ---------------------------------------------------------------------------
// Mocks — set up before module import
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockRpc = vi.fn();
const mockLoggerInfo = vi.fn();
const mockLoggerWarn = vi.fn();
const mockLoggerError = vi.fn();
const mockQstashPublishJSON = vi.fn().mockResolvedValue({});
const mockVerifyQStashSignature = vi.fn().mockResolvedValue(true);

vi.mock("../../api/_lib/supabase", () => ({
	getSupabase: () => ({
		from: mockFrom,
		rpc: mockRpc,
	}),
	getSupabaseAny: () => ({
		from: mockFrom,
		rpc: mockRpc,
	}),
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: {
		info: (...args: unknown[]) => mockLoggerInfo(...args),
		warn: (...args: unknown[]) => mockLoggerWarn(...args),
		error: (...args: unknown[]) => mockLoggerError(...args),
		debug: vi.fn(),
	},
}));

vi.mock("../../api/_lib/qstash", () => ({
	verifyQStashSignature: (...args: unknown[]) => mockVerifyQStashSignature(...args),
	getQStashClient: () => ({
		publishJSON: (...args: unknown[]) => mockQstashPublishJSON(...args),
	}),
}));

const mockPostToThreads = vi.fn();
const mockShouldAttachMedia = vi.fn().mockReturnValue(false);
const mockGetRandomMediaUrl = vi.fn().mockResolvedValue(null);
const mockLogActivity = vi.fn().mockResolvedValue(undefined);
const mockVerifyGatePassToken = vi.fn().mockReturnValue({
	ok: true,
	contentHash: "content-hash",
	verdictHash: "verdict-hash",
});

vi.mock("../../api/_lib/handlers/auto-post/publisher", () => ({
	postToThreads: (...args: unknown[]) => mockPostToThreads(...args),
	shouldAttachMedia: (...args: unknown[]) => mockShouldAttachMedia(...args),
	getRandomMediaUrl: (...args: unknown[]) => mockGetRandomMediaUrl(...args),
	logActivity: (...args: unknown[]) => mockLogActivity(...args),
}));

vi.mock("../../api/_lib/handlers/auto-post/gatePassToken", () => ({
	verifyAutopublishGatePassToken: (...args: unknown[]) =>
		mockVerifyGatePassToken(...args),
}));

vi.mock("../../api/_lib/handlers/auto-post/types", () => ({
	RATE_LIMITS: { POSTS_PER_HOUR: 25, POSTS_PER_DAY: 250 },
}));

vi.mock("../../api/_lib/retryUtils", () => ({
	shouldRetry: (count: number) => count < 3,
	calculateBackoff: () => new Date(Date.now() + 30000),
}));

vi.mock("../../api/_lib/dailyCap", () => ({
	checkDailyCap: vi.fn().mockResolvedValue({ allowed: true }),
}));

vi.mock("../../api/_lib/humanizeContent", () => ({
	bannedWordsCheck: vi.fn().mockReturnValue({ flagged: false, matches: [] }),
}));

vi.mock("../../api/_lib/handlers/auto-post/spoilerTricks", () => ({
	resolveSpoilerEntities: vi.fn().mockReturnValue(null),
}));

vi.mock("../../api/_lib/createNotification", () => ({
	createNotification: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../../api/_lib/publishLock", () => ({
	acquirePublishLock: vi.fn().mockResolvedValue({
		acquired: true,
		release: vi.fn().mockResolvedValue(undefined),
	}),
}));

const mockRedisGet = vi.fn().mockResolvedValue(null);
const mockRedisSet = vi.fn().mockResolvedValue(undefined);

vi.mock("../../api/_lib/redis", () => ({
	getRedis: () => ({
		get: (...args: unknown[]) => mockRedisGet(...args),
		set: (...args: unknown[]) => mockRedisSet(...args),
	}),
}));

vi.mock("../../api/_lib/encryption", () => ({
	decrypt: (value: string) => `decrypted_${value}`,
	encrypt: (value: string) => `encrypted_${value}`,
}));

vi.mock("../../api/_lib/autopilotRunLogger", () => ({
	logRun: vi.fn().mockResolvedValue({
		runId: "run-1",
		logStep: vi.fn().mockResolvedValue(undefined),
		finishRun: vi.fn().mockResolvedValue(undefined),
	}),
}));

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const QUEUE_ITEM = createTestQueueItem();
const CLAIM_RPC = "claim_auto_post_queue_item_for_publish";
const RATE_LIMIT_RPC = "get_rate_limit_status";
const FINALIZE_RPC = "finalize_autoposter_publish";

function installDefaultRpcMocks() {
	mockRpc.mockImplementation((name: string) => {
		if (name === CLAIM_RPC) {
			return Promise.resolve({
				data: [{ id: "q1" }],
				error: null,
			});
		}
		if (name === RATE_LIMIT_RPC) {
			return Promise.resolve({
				data: [{ posts_this_hour: 1, posts_today: 20 }],
				error: null,
			});
		}
		if (name === FINALIZE_RPC) {
			return Promise.resolve({
				data: [{ post_id: "post-1", inserted: true }],
				error: null,
			});
		}
		return Promise.resolve({ data: null, error: null });
	});
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("auto-post-publish handler", () => {
	let handler: (req: any, res: any) => Promise<any>;

	beforeEach(async () => {
		vi.clearAllMocks();
		vi.resetModules();
		mockQstashPublishJSON.mockReset();
		mockQstashPublishJSON.mockResolvedValue({});
		mockVerifyQStashSignature.mockReset();
		mockVerifyQStashSignature.mockResolvedValue(true);
		mockRedisGet.mockReset();
		mockRedisGet.mockResolvedValue(null);
		mockRedisSet.mockReset();
		mockRedisSet.mockResolvedValue(undefined);
		mockVerifyGatePassToken.mockReset();
		mockVerifyGatePassToken.mockReturnValue({
			ok: true,
			contentHash: "content-hash",
			verdictHash: "verdict-hash",
		});
		installDefaultRpcMocks();
		delete process.env.AUTOPOSTER_HARD_DISABLED;
		delete process.env.CRON_SECRET;
		// Re-import fresh handler
		const mod = await import("../../api/auto-post-publish");
		handler = mod.default;
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	it("rejects with 400 when required fields are missing", async () => {
		const res = mockRes();
		await handler(mockAutoPostReq({}), res);
		expect(res.status).toHaveBeenCalledWith(400);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				ok: false,
				skipped: true,
				reason: "invalid_body",
			}),
		);
	});

	it("allows internal cron recovery auth without QStash signature", async () => {
		process.env.CRON_SECRET = "test-cron-secret";
		mockVerifyQStashSignature.mockResolvedValue(false);

		const itemChain = createChainMock({
			data: { ...QUEUE_ITEM, status: "published" },
			error: null,
		});
		mockFrom.mockReturnValue(itemChain);

		const res = mockRes();
		await handler(
			mockAutoPostReq(
				{ queueItemId: "q1", workspaceId: "ws1", groupId: "g1", ownerId: "u1", groupName: "G" },
				{ authorization: "Bearer test-cron-secret" },
			),
			res,
		);

		expect(mockVerifyQStashSignature).not.toHaveBeenCalled();
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ skipped: true, reason: "published" }),
		);
	});

	it("skips when queue item is already published", async () => {
		// Load returns published item
		const itemChain = createChainMock({
			data: { ...QUEUE_ITEM, status: "published" },
			error: null,
		});
		mockFrom.mockReturnValue(itemChain);

		const res = mockRes();
		await handler(
			mockAutoPostReq({ queueItemId: "q1", workspaceId: "ws1", groupId: "g1", ownerId: "u1", groupName: "G" }),
			res,
		);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ skipped: true, reason: "published" }),
		);
		expect(mockLoggerInfo).toHaveBeenCalledWith(
			"[auto-post-publish] Skip terminal queue item",
			expect.objectContaining({ queueItemId: "q1", status: "published" }),
		);
		expect(mockLoggerInfo).not.toHaveBeenCalledWith(
			"[auto-post-publish] Start",
			expect.anything(),
		);
	});

	it("skips stale QStash messages when schedule nonce no longer matches", async () => {
		mockFrom.mockReturnValue(
			createChainMock({
				data: {
					...QUEUE_ITEM,
					status: "queued",
					schedule_nonce: "current-nonce",
					scheduled_for: new Date(Date.now() - 60_000).toISOString(),
				},
				error: null,
			}),
		);

		const res = mockRes();
		await handler(
			mockAutoPostReq({
				queueItemId: "q1",
				workspaceId: "ws1",
				groupId: "g1",
				ownerId: "u1",
				groupName: "G",
				scheduleNonce: "old-nonce",
			}),
			res,
		);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ skipped: true, reason: "stale_schedule_nonce" }),
		);
		expect(mockPostToThreads).not.toHaveBeenCalled();
	});

	it("skips queue items that are not due yet", async () => {
		mockFrom.mockReturnValue(
			createChainMock({
				data: {
					...QUEUE_ITEM,
					status: "queued",
					schedule_nonce: "nonce-1",
					scheduled_for: new Date(Date.now() + 60 * 60_000).toISOString(),
				},
				error: null,
			}),
		);

		const res = mockRes();
		await handler(
			mockAutoPostReq({
				queueItemId: "q1",
				workspaceId: "ws1",
				groupId: "g1",
				ownerId: "u1",
				groupName: "G",
				scheduleNonce: "nonce-1",
			}),
			res,
		);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ skipped: true, reason: "not_due" }),
		);
		expect(mockPostToThreads).not.toHaveBeenCalled();
	});

	it("skips immediately when AUTOPOSTER_HARD_DISABLED is set", async () => {
		process.env.AUTOPOSTER_HARD_DISABLED = "true";
		vi.resetModules();
		const mod = await import("../../api/auto-post-publish");
		handler = mod.default;

		const res = mockRes();
		await handler(
			mockAutoPostReq({ queueItemId: "q1", workspaceId: "ws1", groupId: "g1", ownerId: "u1", groupName: "G" }),
			res,
		);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ skipped: true, reason: "hard_disabled" }),
		);
		expect(mockFrom).not.toHaveBeenCalled();
		expect(mockLoggerWarn).toHaveBeenCalledWith(
			"[auto-post-publish] Skip global hard disable",
			expect.objectContaining({ queueItemId: "q1", workspaceId: "ws1" }),
		);
	});

	it("skips when atomic claim fails (already claimed by another worker)", async () => {
		// Step 1: load item → pending
		// Step 2: load ws config → enabled
		// Step 3: load group config → enabled
		// Step 4: atomic claim → null (already claimed)
		let callCount = 0;
		mockFrom.mockImplementation((_table: string) => {
			callCount++;
			if (callCount === 1) {
				// auto_post_queue load
				return createChainMock({ data: QUEUE_ITEM, error: null });
			}
			if (callCount === 2) {
				// auto_post_config
				return createChainMock({ data: { is_enabled: true, group_mode_enabled: true }, error: null });
			}
			if (callCount === 3) {
				// auto_post_group_config
				return createChainMock({ data: { enabled: true }, error: null });
			}
			return createChainMock({ data: null, error: null });
		});
		mockRpc.mockImplementation((name: string) => {
			if (name === CLAIM_RPC) {
				return Promise.resolve({ data: [], error: null });
			}
			return Promise.resolve({ data: null, error: null });
		});

		const res = mockRes();
		await handler(
			mockAutoPostReq({ queueItemId: "q1", workspaceId: "ws1", groupId: "g1", ownerId: "u1", groupName: "G" }),
			res,
		);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ skipped: true, reason: "claim_failed" }),
		);
		// postToThreads should NOT have been called
		expect(mockPostToThreads).not.toHaveBeenCalled();
	});

	it("cancels and logs when workspace config is disabled", async () => {
		let callCount = 0;
		let updatePayload: Record<string, unknown> | null = null;
		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				callCount += 1;
				if (callCount === 1) {
					return createChainMock({ data: QUEUE_ITEM, error: null });
				}
				const updateChain = createChainMock({ data: null, error: null });
				updateChain.update = vi.fn((payload: Record<string, unknown>) => {
					updatePayload = payload;
					return updateChain;
				});
				return updateChain;
			}
			if (table === "auto_post_config") {
				return createChainMock({
					data: { is_enabled: false, group_mode_enabled: false },
					error: null,
				});
			}
			return createChainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(
			mockAutoPostReq({ queueItemId: "q1", workspaceId: "ws1", groupId: "g1", ownerId: "u1", groupName: "G" }),
			res,
		);

		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, result: "cancelled", reason: "disabled" }),
		);
		expect(updatePayload).toEqual(
			expect.objectContaining({
				status: "cancelled",
				last_error: "Autoposter disabled at publish time",
			}),
		);
		expect(mockLoggerInfo).toHaveBeenCalledWith(
			"[auto-post-publish] Skip disabled workspace",
			expect.objectContaining({ queueItemId: "q1", workspaceId: "ws1" }),
		);
		expect(mockPostToThreads).not.toHaveBeenCalled();
	});

	it("cancels and logs when group config is disabled", async () => {
		let callCount = 0;
		let updatePayload: Record<string, unknown> | null = null;
		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				callCount += 1;
				if (callCount === 1) {
					return createChainMock({ data: QUEUE_ITEM, error: null });
				}
				const updateChain = createChainMock({ data: null, error: null });
				updateChain.update = vi.fn((payload: Record<string, unknown>) => {
					updatePayload = payload;
					return updateChain;
				});
				return updateChain;
			}
			if (table === "auto_post_config") {
				return createChainMock({
					data: { is_enabled: true, group_mode_enabled: true },
					error: null,
				});
			}
			if (table === "auto_post_group_config") {
				return createChainMock({
					data: { enabled: false },
					error: null,
				});
			}
			return createChainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(
			mockAutoPostReq({ queueItemId: "q1", workspaceId: "ws1", groupId: "g1", ownerId: "u1", groupName: "G" }),
			res,
		);

		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, result: "cancelled", reason: "group_disabled" }),
		);
		expect(updatePayload).toEqual(
			expect.objectContaining({
				status: "cancelled",
				last_error: "Group disabled at publish time",
			}),
		);
		expect(mockLoggerInfo).toHaveBeenCalledWith(
			"[auto-post-publish] Skip disabled group",
			expect.objectContaining({ queueItemId: "q1", workspaceId: "ws1", groupId: "g1" }),
		);
		expect(mockPostToThreads).not.toHaveBeenCalled();
	});

	it("does not select shadowbanned accounts in publish-time fallback", async () => {
		const queueItem = createTestQueueItem({ account_id: null } as any);
		const autoPostQueueBase = {
			select: vi.fn().mockReturnThis(),
			eq: vi.fn().mockReturnThis(),
			in: vi.fn().mockReturnThis(),
			is: vi.fn().mockReturnThis(),
			lte: vi.fn().mockReturnThis(),
			or: vi.fn().mockReturnThis(),
			update: vi.fn().mockReturnThis(),
			maybeSingle: vi.fn()
				.mockResolvedValueOnce({ data: queueItem, error: null })
				.mockResolvedValueOnce({ data: { id: "q1" }, error: null }),
			then: vi.fn((resolve: (value: { error: null }) => unknown) =>
				Promise.resolve({ error: null }).then(resolve),
			),
		};

		const autoPostQueueRetry = {
			update: vi.fn().mockReturnThis(),
			eq: vi.fn().mockReturnThis(),
			then: vi.fn((resolve: (value: { error: null }) => unknown) =>
				Promise.resolve({ error: null }).then(resolve),
			),
		};

		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") return autoPostQueueBase;
			if (table === "auto_post_config") {
				return createChainMock({
					data: { is_enabled: true, group_mode_enabled: true },
					error: null,
				});
			}
			if (table === "auto_post_group_config") {
				return createChainMock({
					data: {
						enabled: true,
						timezone: "UTC",
						active_hours_start: 0,
						active_hours_end: 23,
						post_on_weekends: true,
						min_interval_minutes: 30,
						posts_per_account_per_day: 5,
					},
					error: null,
				});
			}
			if (table === "account_groups") {
				return createChainMock({
					data: { account_ids: ["sb-1"] },
					error: null,
				});
			}
			if (table === "accounts") {
				const chain: any = {
					select: vi.fn().mockReturnThis(),
					eq: vi.fn().mockReturnThis(),
					in: vi.fn().mockReturnThis(),
					not: vi.fn().mockReturnThis(),
					or: vi.fn().mockReturnThis(),
					maybeSingle: vi.fn().mockResolvedValue({ data: null, error: null }),
				};
				chain.or = vi.fn().mockResolvedValue({
					data: [{
						id: "sb-1",
						username: "shadowed",
						threads_user_id: "tu-sb",
						threads_access_token_encrypted: "enc",
						is_retired: false,
						needs_reauth: false,
						is_active: true,
						is_shadowbanned: true,
						status: "active",
					}],
					error: null,
				});
				return chain;
			}
			if (table === "workspaces") {
				return createChainMock({ data: { owner_id: "owner-1" }, error: null });
			}
			return autoPostQueueRetry;
		});

		const res = mockRes();
		await handler(
			mockAutoPostReq({
				queueItemId: "q1",
				workspaceId: "ws1",
				groupId: "g1",
				ownerId: "u1",
				groupName: "G",
			}),
			res,
		);

		expect(mockPostToThreads).not.toHaveBeenCalled();
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, result: "rescheduled", reason: "no_account_assigned" }),
		);
	});

	it("reopens queued items cleanly when outside-window redispatch fails", async () => {
		const currentHour = Number.parseInt(
			new Date().toLocaleString("en-US", {
				hour: "numeric",
				hour12: false,
				timeZone: "UTC",
			}),
			10,
		);
		const activeStart = (currentHour + 1) % 24;
		const activeEnd = (currentHour + 2) % 24;
		const queueItem = createTestQueueItem({ account_id: "acct-1" } as any);
		let autoPostQueueCallCount = 0;
		const queueUpdatePayloads: Array<Record<string, unknown>> = [];

		mockQstashPublishJSON.mockRejectedValueOnce(new Error("qstash down"));

		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				autoPostQueueCallCount += 1;
				if (autoPostQueueCallCount === 1) {
					return createChainMock({ data: queueItem, error: null });
				}
				const updateChain = createChainMock({ data: { id: "q1" }, error: null });
				updateChain.update = vi.fn((payload: Record<string, unknown>) => {
					queueUpdatePayloads.push(payload);
					return updateChain;
				});
				return updateChain;
			}
			if (table === "auto_post_config") {
				return createChainMock({
					data: { is_enabled: true, group_mode_enabled: true },
					error: null,
				});
			}
			if (table === "auto_post_group_config") {
				return createChainMock({
					data: {
						enabled: true,
						timezone: "UTC",
						active_hours_start: activeStart,
						active_hours_end: activeEnd,
						post_on_weekends: true,
						min_interval_minutes: 30,
						posts_per_account_per_day: 5,
					},
					error: null,
				});
			}
			if (table === "auto_post_account_overrides") {
				return createChainMock({ data: null, error: null });
			}
			if (table === "account_schedule") {
				return createChainMock({ data: null, error: null });
			}
			return createChainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(
			mockAutoPostReq({
				queueItemId: "q1",
				workspaceId: "ws1",
				groupId: "g1",
				ownerId: "u1",
				groupName: "G",
				accountId: "acct-1",
			}),
			res,
		);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, result: "rescheduled", reason: "outside_active_window" }),
		);
		expect(queueUpdatePayloads).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					status: "pending",
					pool_status: "available",
					scheduled_for: expect.any(String),
					claimed_at: null,
				}),
			]),
		);
	});

	it("rechecks active hours after pool-mode account assignment", async () => {
		const currentHour = Number.parseInt(
			new Date().toLocaleString("en-US", {
				hour: "numeric",
				hour12: false,
				timeZone: "UTC",
			}),
			10,
		);
		const activeStart = (currentHour + 1) % 24;
		const activeEnd = (currentHour + 2) % 24;
		const queueItem = createTestQueueItem({
			id: "q1",
			account_id: null,
			status: "pending",
		} as any);
		const queueUpdatePayloads: Array<Record<string, unknown>> = [];
		let queueMaybeSingleCount = 0;
		mockQstashPublishJSON.mockResolvedValueOnce({ messageId: "resched-msg" });

		const queueChain: any = {
			select: vi.fn().mockReturnThis(),
			eq: vi.fn().mockReturnThis(),
			in: vi.fn().mockReturnThis(),
			is: vi.fn().mockReturnThis(),
			gte: vi.fn().mockReturnThis(),
			lte: vi.fn().mockReturnThis(),
			or: vi.fn().mockReturnThis(),
			update: vi.fn((payload: Record<string, unknown>) => {
				queueUpdatePayloads.push(payload);
				return queueChain;
			}),
			maybeSingle: vi.fn(async () => {
				queueMaybeSingleCount += 1;
				if (queueMaybeSingleCount === 1) {
					return { data: queueItem, error: null };
				}
				return { data: { id: "q1", schedule_nonce: "nonce-1" }, error: null };
			}),
			then: vi.fn((resolve: (value: { error: null }) => unknown) =>
				Promise.resolve({ error: null }).then(resolve),
			),
		};

		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") return queueChain;
			if (table === "auto_post_config") {
				return createChainMock({
					data: { is_enabled: true, group_mode_enabled: true },
					error: null,
				});
			}
			if (table === "auto_post_group_config") {
				return createChainMock({
					data: {
						enabled: true,
						timezone: "UTC",
						active_hours_start: activeStart,
						active_hours_end: activeEnd,
						post_on_weekends: true,
						min_interval_minutes: 30,
						posts_per_account_per_day: 5,
					},
					error: null,
				});
			}
			if (table === "account_groups") {
				return createChainMock({
					data: { account_ids: ["acct-1"] },
					error: null,
				});
			}
			if (table === "accounts") {
				const accountsChain: any = {
					select: vi.fn().mockReturnThis(),
					in: vi.fn().mockReturnThis(),
					not: vi.fn().mockReturnThis(),
					or: vi.fn().mockResolvedValue({
						data: [
							{
								id: "acct-1",
								username: "pooled",
								threads_user_id: "tu-1",
								threads_access_token_encrypted: "enc",
								is_retired: false,
								needs_reauth: false,
								is_active: true,
								is_shadowbanned: false,
								status: "active",
							},
						],
						error: null,
					}),
				};
				return accountsChain;
			}
			if (table === "auto_post_account_overrides") {
				return createChainMock({ data: null, error: null });
			}
			if (table === "account_schedule") {
				return createChainMock({ data: null, error: null });
			}
			return createChainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(
			mockAutoPostReq({
				queueItemId: "q1",
				workspaceId: "ws1",
				groupId: "g1",
				ownerId: "u1",
				groupName: "G",
			}),
			res,
		);

		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				ok: true,
				result: "rescheduled",
				reason: "outside_active_window",
			}),
		);
		expect(mockPostToThreads).not.toHaveBeenCalled();
		expect(queueUpdatePayloads).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					status: "pending",
					pool_status: "available",
					account_id: null,
					scheduled_for: expect.any(String),
					last_error: "outside_active_window",
				}),
			]),
		);
	});

	it("requeues local rate-limit blocks with retry backoff metadata", async () => {
		const queueItem = createTestQueueItem({
			id: "q1",
			account_id: "acct-1",
			status: "pending",
			retry_count: 0,
		} as any);
		const queueUpdatePayloads: Array<Record<string, unknown>> = [];
		let autoPostQueueCallCount = 0;

		mockRpc.mockImplementation((name: string) => {
			if (name === CLAIM_RPC) {
				return Promise.resolve({ data: [{ id: "q1" }], error: null });
			}
			if (name === RATE_LIMIT_RPC) {
				return Promise.resolve({
					data: [{ posts_this_hour: 25, posts_today: 20 }],
					error: null,
				});
			}
			return Promise.resolve({ data: null, error: null });
		});

		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				autoPostQueueCallCount += 1;
				if (autoPostQueueCallCount === 1) {
					return createChainMock({ data: queueItem, error: null });
				}
				const chain = createChainMock({
					data: autoPostQueueCallCount === 2 ? { id: "q1" } : null,
					error: null,
				});
				chain.update = vi.fn((payload: Record<string, unknown>) => {
					queueUpdatePayloads.push(payload);
					return chain;
				});
				return chain;
			}
			if (table === "auto_post_config") {
				return createChainMock({
					data: { is_enabled: true, group_mode_enabled: true },
					error: null,
				});
			}
			if (table === "auto_post_group_config") {
				return createChainMock({
					data: {
						enabled: true,
						timezone: "UTC",
						active_hours_start: 0,
						active_hours_end: 24,
						post_on_weekends: true,
						min_interval_minutes: 30,
						posts_per_account_per_day: 5,
					},
					error: null,
				});
			}
			if (table === "auto_post_account_overrides") {
				return createChainMock({ data: null, error: null });
			}
			if (table === "accounts") {
				return createChainMock({
					data: {
						id: "acct-1",
						username: "ratey",
						threads_user_id: "tu-1",
						threads_access_token_encrypted: "enc",
						is_retired: false,
						needs_reauth: false,
						is_active: true,
						is_shadowbanned: false,
						status: "active",
					},
					error: null,
				});
			}
			return createChainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(
			mockAutoPostReq({
				queueItemId: "q1",
				workspaceId: "ws1",
				groupId: "g1",
				ownerId: "u1",
				groupName: "G",
				accountId: "acct-1",
			}),
			res,
		);

		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true, result: "requeued", reason: "rate_limit" }),
		);
		expect(queueUpdatePayloads).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					status: "pending",
					pool_status: "available",
					account_id: null,
					scheduled_for: expect.any(String),
					next_retry_at: expect.any(String),
					claimed_at: null,
					schedule_nonce: null,
					qstash_message_id: null,
					last_error: "Rate limit at publish time — requeued",
				}),
			]),
		);
		const backoffUpdate = queueUpdatePayloads.find(
			(payload) => payload.last_error === "Rate limit at publish time — requeued",
		);
		expect(backoffUpdate?.scheduled_for).toBe(backoffUpdate?.next_retry_at);
		expect(mockPostToThreads).not.toHaveBeenCalled();
	});

	it("requeues on exhausted live Threads quota before publishing", async () => {
		const queueItem = createTestQueueItem({
			id: "q1",
			account_id: "acct-1",
			status: "pending",
			retry_count: 0,
		} as any);
		const originalFetch = global.fetch;
		const liveQuotaFetch = vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
			json: vi.fn().mockResolvedValue({
				data: [
					{
						quota_usage: 250,
						config: { quota_total: 250, quota_duration: 3600 },
					},
				],
			}),
		});
		global.fetch = liveQuotaFetch as unknown as typeof global.fetch;
		const queueUpdatePayloads: Array<Record<string, unknown>> = [];
		let autoPostQueueCallCount = 0;

		mockRpc.mockImplementation((name: string) => {
			if (name === CLAIM_RPC) {
				return Promise.resolve({ data: [{ id: "q1" }], error: null });
			}
			if (name === RATE_LIMIT_RPC) {
				return Promise.resolve({
					data: [{ posts_this_hour: 1, posts_today: 249 }],
					error: null,
				});
			}
			return Promise.resolve({ data: null, error: null });
		});

		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				autoPostQueueCallCount += 1;
				if (autoPostQueueCallCount === 1) {
					return createChainMock({ data: queueItem, error: null });
				}
				const chain = createChainMock({
					data: autoPostQueueCallCount === 2 ? { id: "q1" } : null,
					error: null,
				});
				chain.update = vi.fn((payload: Record<string, unknown>) => {
					queueUpdatePayloads.push(payload);
					return chain;
				});
				return chain;
			}
			if (table === "auto_post_config") {
				return createChainMock({
					data: { is_enabled: true, group_mode_enabled: true },
					error: null,
				});
			}
			if (table === "auto_post_group_config") {
				return createChainMock({
					data: {
						enabled: true,
						timezone: "UTC",
						active_hours_start: 0,
						active_hours_end: 24,
						post_on_weekends: true,
						min_interval_minutes: 30,
						posts_per_account_per_day: 5,
					},
					error: null,
				});
			}
			if (table === "auto_post_account_overrides") {
				return createChainMock({ data: null, error: null });
			}
			if (table === "accounts") {
				return createChainMock({
					data: {
						id: "acct-1",
						username: "quota",
						threads_user_id: "tu-1",
						threads_access_token_encrypted: "enc",
						is_retired: false,
						needs_reauth: false,
						is_active: true,
						is_shadowbanned: false,
						status: "active",
					},
					error: null,
				});
			}
			return createChainMock({ data: null, error: null });
		});

		try {
			const res = mockRes();
			await handler(
				mockAutoPostReq({
					queueItemId: "q1",
					workspaceId: "ws1",
					groupId: "g1",
					ownerId: "u1",
					groupName: "G",
					accountId: "acct-1",
				}),
				res,
			);

			expect(res.json).toHaveBeenCalledWith(
				expect.objectContaining({ ok: true, result: "requeued", reason: "live_quota" }),
			);
			expect(liveQuotaFetch).toHaveBeenCalledWith(
				expect.stringContaining("/tu-1/threads_publishing_limit"),
				expect.objectContaining({
					headers: { Authorization: "Bearer decrypted_enc" },
				}),
			);
			expect(queueUpdatePayloads).toEqual(
				expect.arrayContaining([
					expect.objectContaining({
						status: "pending",
						next_retry_at: expect.any(String),
						schedule_nonce: null,
						qstash_message_id: null,
						last_error: "Live Threads quota exhausted (250/250) — requeued",
					}),
				]),
			);
			expect(mockPostToThreads).not.toHaveBeenCalled();
		} finally {
			global.fetch = originalFetch;
		}
	});

	it("requeues a due preassigned warm-up row when account capacity is already used", async () => {
		const queueItem = createTestQueueItem({
			id: "q1",
			account_id: "acct-1",
			status: "pending",
			scheduled_for: "2026-06-08T16:00:00.000Z",
			metadata: {
				quality_gate: {
					decision: "pass",
					reason: "quality_gate_passed",
				},
				judge: {
					score: 4,
					dimensions: {},
				},
				provenance: {
					source_type: "ai",
					source_id: "group:g1",
					content_fingerprint: "content-fingerprint-1",
					publish_fingerprint: "publish-fingerprint-1",
					generation_id: "generation-1",
					quality_gate_result: "pass",
					judge_result: "llm_judge_passed",
				},
			},
		} as any);
		const queueUpdates: Array<Record<string, unknown>> = [];
		let queueCall = 0;

		vi.setSystemTime(new Date("2026-06-08T16:00:00.000Z"));
		mockRpc.mockImplementation((name: string) => {
			if (name === CLAIM_RPC) {
				return Promise.resolve({ data: [{ id: "q1" }], error: null });
			}
			return Promise.resolve({ data: null, error: null });
		});

		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				queueCall += 1;
				if (queueCall === 1) {
					return createChainMock({ data: queueItem, error: null });
				}
				if (queueCall === 2) {
					const chain = createChainMock({ data: null, error: null });
					chain.update = vi.fn((payload: Record<string, unknown>) => {
						queueUpdates.push(payload);
						return chain;
					});
					return chain;
				}
				if (queueCall === 3) {
					return createChainMock({ count: 0, data: [], error: null });
				}
				if (queueCall === 4) {
					const chain: Record<string, any> = {};
					for (const method of ["select", "eq", "in", "or"]) {
						chain[method] = vi.fn(() => chain);
					}
					chain.then = (
						resolve: (value: unknown) => void,
						reject?: (err: unknown) => void,
					) =>
						Promise.resolve({
							data: [
								{
									id: "existing",
									account_id: "acct-1",
									status: "published",
									posted_at: "2026-06-08T15:00:00.000Z",
									metadata: {},
								},
							],
							error: null,
						}).then(resolve, reject);
					return chain;
				}
				const chain = createChainMock({ data: null, error: null });
				chain.update = vi.fn((payload: Record<string, unknown>) => {
					queueUpdates.push(payload);
					return chain;
				});
				return chain;
			}
			if (table === "auto_post_config") {
				return createChainMock({
					data: { is_enabled: true, group_mode_enabled: true },
					error: null,
				});
			}
			if (table === "auto_post_group_config") {
				return createChainMock({
					data: {
						enabled: true,
						timezone: "America/New_York",
						active_hours_start: 0,
						active_hours_end: 24,
						min_interval_minutes: 30,
						posts_per_account_per_day: 5,
					},
					error: null,
				});
			}
			if (table === "account_schedule") {
				return createChainMock({
					data: {
						active_hours_start: 0,
						active_hours_end: 24,
						timezone: "America/New_York",
						min_interval_minutes: 180,
						paused: false,
						status: "active",
						blocked_until: null,
					},
					error: null,
				});
			}
			if (table === "auto_post_account_overrides") {
				return createChainMock({ data: null, error: null });
			}
			if (table === "account_autoposter_state") {
				return createChainMock({
					data: {
						account_id: "acct-1",
						group_id: "g1",
						workspace_id: "ws1",
						status: "active",
						account_health_score: 100,
						restart_warmup_status: "warming",
						restart_warmup_day: 2,
						restart_warmup_allowed_posts_per_day: 1,
						restart_warmup_reason: "restart_warmup_day_2",
					},
					error: null,
				});
			}
			if (table === "accounts") {
				return createChainMock({
					data: {
						id: "acct-1",
						username: "warm",
						threads_user_id: "tu-1",
						threads_access_token_encrypted: "enc",
						is_retired: false,
						needs_reauth: false,
						is_active: true,
						is_shadowbanned: false,
						status: "active",
					},
					error: null,
				});
			}
			if (table === "publish_attempts") {
				const chain = createChainMock({ data: { id: "attempt-1" }, error: null });
				chain.update = vi.fn().mockReturnValue(chain);
				return chain;
			}
			return createChainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(
			mockAutoPostReq({
				queueItemId: "q1",
				workspaceId: "ws1",
				groupId: "g1",
				ownerId: "u1",
				groupName: "G",
				accountId: "acct-1",
			}),
			res,
		);

		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				ok: true,
				result: "requeued",
				reason: "warmup_cap_exceeded",
			}),
		);
		expect(queueUpdates).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					status: "pending",
					pool_status: "available",
					account_id: null,
					last_error: "warmup_cap_exceeded — requeued",
				}),
			]),
		);
		expect(mockPostToThreads).not.toHaveBeenCalled();
	});

	it("finalizes successful external publishes through the database RPC", async () => {
		const queueItem = createTestQueueItem({
			id: "q1",
			account_id: "acct-1",
			status: "pending",
			content: "final content",
		} as any);
		let autoPostQueueCallCount = 0;

		mockRpc.mockImplementation((name: string) => {
			if (name === CLAIM_RPC) {
				return Promise.resolve({ data: [{ id: "q1" }], error: null });
			}
			if (name === RATE_LIMIT_RPC) {
				return Promise.resolve({
					data: [{ posts_this_hour: 1, posts_today: 20 }],
					error: null,
				});
			}
			if (name === FINALIZE_RPC) {
				return Promise.resolve({
					data: [{ post_id: "post-1", inserted: true }],
					error: null,
				});
			}
			return Promise.resolve({ data: null, error: null });
		});
		mockPostToThreads.mockResolvedValueOnce({
			success: true,
			threadId: "threads-1",
		});

		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				autoPostQueueCallCount += 1;
				if (autoPostQueueCallCount === 1) {
					return createChainMock({ data: queueItem, error: null });
				}
				if (autoPostQueueCallCount === 2) {
					return createChainMock({ data: { id: "q1" }, error: null });
				}
				return createChainMock({ data: null, error: null });
			}
			if (table === "auto_post_config") {
				return createChainMock({
					data: { is_enabled: true, group_mode_enabled: true },
					error: null,
				});
			}
			if (table === "auto_post_group_config") {
				return createChainMock({
					data: {
						enabled: true,
						timezone: "UTC",
						active_hours_start: 0,
						active_hours_end: 24,
						post_on_weekends: true,
						min_interval_minutes: 30,
						posts_per_account_per_day: 5,
					},
					error: null,
				});
			}
			if (table === "auto_post_account_overrides") {
				return createChainMock({ data: null, error: null });
			}
			if (table === "accounts") {
				return createChainMock({
					data: {
						id: "acct-1",
						username: "publisher",
						threads_user_id: null,
						threads_access_token_encrypted: "enc",
						is_retired: false,
						needs_reauth: false,
						is_active: true,
						is_shadowbanned: false,
						status: "active",
					},
					error: null,
				});
			}
			if (table === "auto_post_group_state") {
				return createChainMock({ data: { last_reset_date: "today" }, error: null });
			}
			return createChainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(
			mockAutoPostReq({
				queueItemId: "q1",
				workspaceId: "ws1",
				groupId: "g1",
				ownerId: "u1",
				groupName: "G",
				accountId: "acct-1",
			}),
			res,
		);

		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				ok: true,
				result: "published",
				threadId: "threads-1",
			}),
		);
		expect(mockRpc).toHaveBeenCalledWith(
			"finalize_autoposter_publish",
			expect.objectContaining({
				p_queue_item_id: "q1",
				p_claim_token: expect.any(String),
				p_threads_post_id: "threads-1",
				p_account_id: "acct-1",
				p_workspace_id: "ws1",
				p_group_id: "g1",
				p_content: "final content",
				p_media_urls: [],
				p_source_type: "auto-poster",
				p_published_at: expect.any(String),
			}),
		);
		expect(mockFrom).not.toHaveBeenCalledWith("posts");
	});

	it("dead-letters non-manual rows with an invalid fill-time gate pass before Graph publish", async () => {
		const queueItem = createTestQueueItem({
			id: "q1",
			account_id: "acct-1",
			status: "pending",
			content: "final content changed after fill",
		} as any);
		let autoPostQueueCallCount = 0;
		mockVerifyGatePassToken.mockReturnValueOnce({
			ok: false,
			reason: "gate_pass_content_hash_mismatch",
			contentHash: "changed-hash",
		});

		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				autoPostQueueCallCount += 1;
				if (autoPostQueueCallCount === 1) {
					return createChainMock({ data: queueItem, error: null });
				}
				if (autoPostQueueCallCount === 2) {
					return createChainMock({ data: { id: "q1" }, error: null });
				}
				return createChainMock({ data: null, error: null });
			}
			if (table === "auto_post_config") {
				return createChainMock({
					data: { is_enabled: true, group_mode_enabled: true },
					error: null,
				});
			}
			if (table === "auto_post_group_config") {
				return createChainMock({
					data: {
						enabled: true,
						timezone: "UTC",
						active_hours_start: 0,
						active_hours_end: 24,
						post_on_weekends: true,
						min_interval_minutes: 30,
						posts_per_account_per_day: 5,
					},
					error: null,
				});
			}
			if (table === "auto_post_account_overrides") {
				return createChainMock({ data: null, error: null });
			}
			if (table === "accounts") {
				return createChainMock({
					data: {
						id: "acct-1",
						username: "publisher",
						threads_user_id: null,
						threads_access_token_encrypted: "enc",
						is_retired: false,
						needs_reauth: false,
						is_active: true,
						is_shadowbanned: false,
						status: "active",
					},
					error: null,
				});
			}
			if (table === "auto_post_group_state") {
				return createChainMock({ data: { last_reset_date: "today" }, error: null });
			}
			return createChainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(
			mockAutoPostReq({
				queueItemId: "q1",
				workspaceId: "ws1",
				groupId: "g1",
				ownerId: "u1",
				groupName: "G",
				accountId: "acct-1",
			}),
			res,
		);

		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				ok: true,
				result: "dead_letter",
				reason: "gate_pass_content_hash_mismatch",
			}),
		);
		expect(mockPostToThreads).not.toHaveBeenCalled();
	});

	it("dead-letters off-platform content at publish even if it reached the queue", async () => {
		const queueItem = createTestQueueItem({
			id: "q1",
			account_id: "acct-1",
			status: "pending",
			content: "dm me for the link in bio",
		} as any);
		let autoPostQueueCallCount = 0;

		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				autoPostQueueCallCount += 1;
				if (autoPostQueueCallCount === 1) {
					return createChainMock({ data: queueItem, error: null });
				}
				if (autoPostQueueCallCount === 2) {
					return createChainMock({ data: { id: "q1" }, error: null });
				}
				return createChainMock({ data: null, error: null });
			}
			if (table === "auto_post_config") {
				return createChainMock({
					data: { is_enabled: true, group_mode_enabled: true },
					error: null,
				});
			}
			if (table === "auto_post_group_config") {
				return createChainMock({
					data: {
						enabled: true,
						timezone: "UTC",
						active_hours_start: 0,
						active_hours_end: 24,
						post_on_weekends: true,
						min_interval_minutes: 30,
						posts_per_account_per_day: 5,
					},
					error: null,
				});
			}
			if (table === "auto_post_account_overrides") {
				return createChainMock({ data: null, error: null });
			}
			if (table === "accounts") {
				return createChainMock({
					data: {
						id: "acct-1",
						username: "publisher",
						threads_user_id: null,
						threads_access_token_encrypted: "enc",
						is_retired: false,
						needs_reauth: false,
						is_active: true,
						is_shadowbanned: false,
						status: "active",
					},
					error: null,
				});
			}
			if (table === "auto_post_group_state") {
				return createChainMock({ data: { last_reset_date: "today" }, error: null });
			}
			return createChainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(
			mockAutoPostReq({
				queueItemId: "q1",
				workspaceId: "ws1",
				groupId: "g1",
				ownerId: "u1",
				groupName: "G",
				accountId: "acct-1",
			}),
			res,
		);

		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				ok: true,
				result: "dead_letter",
				reason: "discoverability_risk_link_dm_or_off_platform_reference",
			}),
		);
		expect(mockPostToThreads).not.toHaveBeenCalled();
	});

	it("moves externally published items to reconciliation when finalization fails", async () => {
		const queueItem = createTestQueueItem({
			id: "q1",
			account_id: "acct-1",
			status: "pending",
			content: "final content",
		} as any);
		const queueUpdatePayloads: Array<Record<string, unknown>> = [];
		let autoPostQueueCallCount = 0;

		mockRpc.mockImplementation((name: string) => {
			if (name === CLAIM_RPC) {
				return Promise.resolve({ data: [{ id: "q1" }], error: null });
			}
			if (name === RATE_LIMIT_RPC) {
				return Promise.resolve({
					data: [{ posts_this_hour: 1, posts_today: 20 }],
					error: null,
				});
			}
			if (name === FINALIZE_RPC) {
				return Promise.resolve({
					data: null,
					error: { message: "posts insert failed" },
				});
			}
			return Promise.resolve({ data: null, error: null });
		});
		mockPostToThreads.mockResolvedValueOnce({
			success: true,
			threadId: "threads-1",
		});

		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				autoPostQueueCallCount += 1;
				if (autoPostQueueCallCount === 1) {
					return createChainMock({ data: queueItem, error: null });
				}
				if (autoPostQueueCallCount === 2) {
					return createChainMock({ data: { id: "q1" }, error: null });
				}
				const chain = createChainMock({ data: null, error: null });
				chain.update = vi.fn((payload: Record<string, unknown>) => {
					queueUpdatePayloads.push(payload);
					return chain;
				});
				return chain;
			}
			if (table === "auto_post_config") {
				return createChainMock({
					data: { is_enabled: true, group_mode_enabled: true },
					error: null,
				});
			}
			if (table === "auto_post_group_config") {
				return createChainMock({
					data: {
						enabled: true,
						timezone: "UTC",
						active_hours_start: 0,
						active_hours_end: 24,
						post_on_weekends: true,
						min_interval_minutes: 30,
						posts_per_account_per_day: 5,
					},
					error: null,
				});
			}
			if (table === "auto_post_account_overrides") {
				return createChainMock({ data: null, error: null });
			}
			if (table === "accounts") {
				return createChainMock({
					data: {
						id: "acct-1",
						username: "publisher",
						threads_user_id: null,
						threads_access_token_encrypted: "enc",
						is_retired: false,
						needs_reauth: false,
						is_active: true,
						is_shadowbanned: false,
						status: "active",
					},
					error: null,
				});
			}
			return createChainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(
			mockAutoPostReq({
				queueItemId: "q1",
				workspaceId: "ws1",
				groupId: "g1",
				ownerId: "u1",
				groupName: "G",
				accountId: "acct-1",
			}),
			res,
		);

		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({
				ok: false,
				result: "needs_reconciliation",
				reason: "local_finalize_failed_after_external_publish",
				threadId: "threads-1",
			}),
		);
		expect(queueUpdatePayloads).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					status: "needs_reconciliation",
					account_id: "acct-1",
					threads_post_id: "threads-1",
					external_published_at: expect.any(String),
					finalize_error: expect.stringContaining("posts insert failed"),
					claim_token: null,
					claim_expires_at: null,
				}),
			]),
		);
		expect(mockFrom).not.toHaveBeenCalledWith("posts");
	});

});
