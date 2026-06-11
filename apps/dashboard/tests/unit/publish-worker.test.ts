import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Unit tests for the publish-worker cron (4-phase unified publisher).
 *
 * Tests:
 * 1. Cron auth verification — valid cron secret proceeds, invalid returns 401
 * 2. Phase isolation — error in one phase doesn't prevent others from running
 * 3. Scheduled posts processing (Phase 1) — dispatches publish for due posts
 * 4. Queue reconciliation (Phase 3) — identifies stranded items, re-dispatches
 * 5. Queue fill dispatch (Phase 4) — safety-net fill for empty queues
 * 6. Cross-phase error handling — each phase wrapped in try/catch
 * 7. Cron lock — prevents concurrent execution
 */

// ---------------------------------------------------------------------------
// Mocks — set up before module import
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockRpc = vi.fn();

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
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
	serializeError: (err: unknown) =>
		err instanceof Error ? err.message : String(err),
}));

const mockVerifyCronAuth = vi.fn();

vi.mock("../../api/_lib/apiResponse", () => ({
	verifyCronAuth: (...args: any[]) => mockVerifyCronAuth(...args),
	apiSuccess: (res: any, data?: Record<string, unknown>) =>
		res.status(200).json({ success: true, ...data }),
}));

const mockWithCronLock = vi.fn();
const mockTrackCronRun = vi.fn();

vi.mock("../../api/_lib/cronUtils", () => ({
	withCronLock: (...args: unknown[]) => mockWithCronLock(...args),
	trackCronRun: (...args: unknown[]) => mockTrackCronRun(...args),
}));

const mockAlertCronFailure = vi.fn().mockResolvedValue(undefined);

vi.mock("../../api/_lib/alerting", () => ({
	alertCronFailure: (...args: unknown[]) => mockAlertCronFailure(...args),
}));

const mockProcessScheduledPosts = vi.fn();

vi.mock("../../api/_lib/cron/scheduled-posts", () => ({
	processScheduledPosts: (...args: unknown[]) => mockProcessScheduledPosts(...args),
}));

const mockProcessPendingContainers = vi.fn();

vi.mock("../../api/_lib/cron/ig-container-publisher", () => ({
	processPendingContainers: (...args: unknown[]) => mockProcessPendingContainers(...args),
}));

const mockQStashPublishJSON = vi.fn().mockResolvedValue({});
const mockFetch = vi.fn();

vi.mock("../../api/_lib/qstash", () => ({
	getQStashClient: () => ({
		publishJSON: (...args: unknown[]) => mockQStashPublishJSON(...args),
	}),
}));

vi.mock("../../api/_lib/qstashDefaults", () => ({
	RETRIES: { CRITICAL: 3, IMPORTANT: 2, BEST_EFFORT: 1 },
	MAX_BATCH_SIZE: 100,
	getFailureCallbackUrl: () => "https://juno33.com/api/qstash-failure",
	getRequiredAppBaseUrl: () => "https://juno33.com",
}));

const mockDispatchQueueFill = vi.fn().mockResolvedValue(undefined);

vi.mock("../../api/_lib/handlers/auto-post/queue", () => ({
	dispatchQueueFill: (...args: unknown[]) => mockDispatchQueueFill(...args),
}));

const mockDispatchEngagementFetch = vi.fn().mockResolvedValue(undefined);

vi.mock("../../api/_lib/qstashSchedule", () => ({
	dispatchEngagementFetch: (...args: unknown[]) =>
		mockDispatchEngagementFetch(...args),
}));

const mockRecordInfraEvent = vi.fn().mockResolvedValue(undefined);

vi.mock("../../api/_lib/infraTelemetry", () => ({
	recordInfraEvent: (...args: unknown[]) => mockRecordInfraEvent(...args),
}));

vi.mock("../../api/_lib/sentryServer", () => ({
	captureServerException: vi.fn().mockResolvedValue(undefined),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface MockRes {
	status: ReturnType<typeof vi.fn>;
	json: ReturnType<typeof vi.fn>;
}

function mockReq(headers: Record<string, string> = {}) {
	return { headers } as unknown;
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

/**
 * Build a chainable Supabase mock that resolves to the given value.
 * The chain is thenable (has .then) so `await chain` resolves to finalValue,
 * matching Supabase's PostgREST builder behavior.
 */
function chainMock(finalValue: { data: unknown; error: unknown; count?: number }) {
	const chain: Record<string, ReturnType<typeof vi.fn> | Function> = {};
	const methods = [
		"select", "eq", "in", "is", "not", "or", "gte", "lt", "lte",
		"maybeSingle", "single", "limit", "order", "update", "insert",
	];
	for (const m of methods) {
		if (m === "maybeSingle" || m === "single") {
			chain[m] = vi.fn().mockResolvedValue(finalValue);
		} else {
			chain[m] = vi.fn().mockReturnValue(chain);
		}
	}
	// Make chain thenable so `await supabase.from(...).select(...).eq(...)`
	// resolves to finalValue (Supabase PostgREST builders are thenable)
	chain.then = (resolve: (v: unknown) => unknown) => Promise.resolve(finalValue).then(resolve);
	return chain;
}

/**
 * Configure mockWithCronLock to execute its callback (simulating lock acquired).
 */
function setupCronLockAcquired() {
	mockWithCronLock.mockImplementation(
		async (_supabase: unknown, _jobName: unknown, fn: () => Promise<unknown>) => {
			const result = await fn();
			return { skipped: false, result };
		},
	);
}

/**
 * Configure mockWithCronLock to skip (simulating lock NOT acquired).
 */
function setupCronLockSkipped() {
	mockWithCronLock.mockResolvedValue({ skipped: true });
}

/**
 * Configure mockTrackCronRun to execute its callback.
 */
function setupTrackCronRun() {
	mockTrackCronRun.mockImplementation(
		async (_supabase: unknown, _jobName: unknown, fn: () => Promise<unknown>) => {
			return fn();
		},
	);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("publish-worker cron handler", () => {
	let handler: (req: unknown, res: unknown) => Promise<unknown>;
	let originalFetch: typeof global.fetch | undefined;

	beforeEach(async () => {
		vi.clearAllMocks();
		process.env.CRON_SECRET = "test-cron-secret";
		originalFetch = global.fetch;
		global.fetch = mockFetch as unknown as typeof global.fetch;
		mockFetch.mockReset();
		mockFetch.mockResolvedValue({
			ok: true,
			status: 200,
			text: vi.fn().mockResolvedValue(""),
		});

		// Default: cron auth passes
		mockVerifyCronAuth.mockReturnValue(true);

		// Default: lock acquired + tracking works
		setupCronLockAcquired();
		setupTrackCronRun();

		// Default: all phases succeed with 0 items
		mockProcessScheduledPosts.mockResolvedValue(0);
		mockProcessPendingContainers.mockResolvedValue(0);
		mockRpc.mockResolvedValue({ data: null, error: null });

		// Default: no stranded items, no fill needed
		mockFrom.mockReturnValue(
			chainMock({ data: null, error: null }),
		);

		// Re-import fresh handler each test
		const mod = await import("../../api/cron/publish-worker");
		handler = mod.default as any;
	});

	afterEach(() => {
		global.fetch = originalFetch as typeof global.fetch;
		vi.restoreAllMocks();
	});

	// ── 1. Cron Auth Verification ──

	it("returns early when cron auth fails", async () => {
		mockVerifyCronAuth.mockImplementation((_req: unknown, res: any) => {
			res.status(401).json({ error: "Invalid cron secret" });
			return false;
		});

		const res = mockRes();
		await handler(mockReq(), res);

		expect(res.status).toHaveBeenCalledWith(401);
		expect(mockWithCronLock).not.toHaveBeenCalled();
	});

	it("proceeds when cron auth succeeds", async () => {
		const res = mockRes();
		await handler(mockReq({ authorization: "Bearer valid-secret" }), res);

		expect(mockVerifyCronAuth).toHaveBeenCalled();
		expect(mockWithCronLock).toHaveBeenCalled();
	});

	// ── 2. Cron Lock — Prevents Concurrent Execution ──

	it("returns skipped response when cron lock is not acquired", async () => {
		setupCronLockSkipped();

		const res = mockRes();
		await handler(mockReq(), res);

		// Handler returns res.status(200).json({ skipped: true })
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ skipped: true }),
		);
		expect(mockProcessScheduledPosts).not.toHaveBeenCalled();
	});

	it("executes phases when cron lock is acquired", async () => {
		const res = mockRes();
		await handler(mockReq(), res);

		expect(mockWithCronLock).toHaveBeenCalled();
		expect(mockProcessScheduledPosts).toHaveBeenCalled();
	});

	// ── 3. Phase 1: Scheduled Posts Processing ──

	it("dispatches scheduled posts in Phase 1", async () => {
		mockProcessScheduledPosts.mockResolvedValue(3);

		const res = mockRes();
		await handler(mockReq(), res);

		expect(mockProcessScheduledPosts).toHaveBeenCalled();
		// Should complete successfully — returns ok response
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true }),
		);
	});

	// ── 4. Phase Isolation — Error in One Phase Doesn't Prevent Others ──

	it("continues to Phase 2 even when Phase 1 throws", async () => {
		mockProcessScheduledPosts.mockRejectedValue(new Error("Phase 1 DB crash"));

		const res = mockRes();
		await handler(mockReq(), res);

		// Phase 2 should still run
		expect(mockProcessPendingContainers).toHaveBeenCalled();
		// alertCronFailure should be called for Phase 1
		expect(mockAlertCronFailure).toHaveBeenCalledWith(
			"publish-worker",
			expect.stringContaining("Phase 1 DB crash"),
		);
	});

	it("continues to later phases even when Phase 2 throws", async () => {
		mockProcessPendingContainers.mockRejectedValue(new Error("IG container error"));

		const res = mockRes();
		await handler(mockReq(), res);

		// Phase 1 should have run
		expect(mockProcessScheduledPosts).toHaveBeenCalled();
		// alertCronFailure should be called for Phase 2
		expect(mockAlertCronFailure).toHaveBeenCalledWith(
			"publish-worker",
			expect.stringContaining("IG container error"),
		);
	});

	it("runs all 4 phases independently even when multiple fail", async () => {
		mockProcessScheduledPosts.mockRejectedValue(new Error("Phase 1 fail"));
		mockProcessPendingContainers.mockRejectedValue(new Error("Phase 2 fail"));

		const res = mockRes();
		await handler(mockReq(), res);

		// Both failure alerts should fire
		expect(mockAlertCronFailure).toHaveBeenCalledTimes(2);
		// The handler should still complete with 200
		expect(res.status).toHaveBeenCalledWith(200);
	});

	// ── 5. Phase 3: Queue Reconciliation ──

	it("rebuilds locally missing posts after external publish and schedules engagement fetches", async () => {
		let autoPostQueueCallCount = 0;
		mockRpc.mockResolvedValue({
			data: [{ post_id: "post-1", inserted: true }],
			error: null,
		});
		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_config") {
				return chainMock({
					data: [{
						workspace_id: "ws1",
						scheduler_version: 4,
						group_mode_enabled: true,
						enable_ai_queue_fill: false,
					}],
					error: null,
				});
			}
			if (table === "auto_post_queue") {
				autoPostQueueCallCount++;
				if (autoPostQueueCallCount === 1) {
					return chainMock({
						data: [{
							id: "q-finalize",
							workspace_id: "ws1",
							group_id: "g1",
							account_id: "acct1",
							status: "needs_reconciliation",
							threads_post_id: "threads-123",
							external_published_at: "2026-06-04T12:00:00Z",
							finalize_error: "insert failed",
						}],
						error: null,
					});
				}
				return chainMock({ data: [], error: null });
			}
			return chainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(mockReq(), res);

		expect(mockRpc).toHaveBeenCalledWith("reconcile_autoposter_publish", {
			p_queue_item_id: "q-finalize",
		});
		expect(mockDispatchEngagementFetch).toHaveBeenCalledTimes(2);
		expect(mockDispatchEngagementFetch).toHaveBeenCalledWith(
			"post-1",
			"threads-123",
			3600,
		);
		expect(mockDispatchEngagementFetch).toHaveBeenCalledWith(
			"post-1",
			"threads-123",
			86400,
		);
		expect(mockRecordInfraEvent).toHaveBeenCalledWith(
			"autopost-local-finalize-reconciled",
			expect.objectContaining({
				queueItemId: "q-finalize",
				postId: "post-1",
				threadsPostId: "threads-123",
			}),
		);
		expect(res.status).toHaveBeenCalledWith(200);
	});

	it("reconciles stranded queue items via internal publish invoke", async () => {
		const queueUpdates: Array<Record<string, unknown>> = [];
		const queueChains: any[] = [];

		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				const chain = chainMock({
					data: [
						{ id: "q1", workspace_id: "ws1", group_id: "g1", schedule_nonce: "sched-q1" },
						{ id: "q2", workspace_id: "ws1", group_id: "g1", schedule_nonce: "sched-q2" },
					],
					error: null,
				});
				chain.update = vi.fn((payload: Record<string, unknown>) => {
					queueUpdates.push(payload);
					return chain;
				});
				queueChains.push(chain);
				return chain;
			}
			if (table === "account_groups") {
				// group info lookup
				return chainMock({
					data: [{ id: "g1", name: "Test Group", user_id: "u1" }],
					error: null,
				});
			}
			if (table === "auto_post_config") {
				return chainMock({
					data: [{
						workspace_id: "ws1",
						scheduler_version: 4,
						group_mode_enabled: true,
						enable_ai_queue_fill: false,
					}],
					error: null,
				});
			}
			return chainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(mockReq(), res);

		expect(mockFetch).toHaveBeenCalledTimes(2);
		expect(mockFetch).toHaveBeenCalledWith(
			"https://juno33.com/api/auto-post-publish",
			expect.objectContaining({
				method: "POST",
				headers: expect.objectContaining({
					authorization: "Bearer test-cron-secret",
					"content-type": "application/json",
				}),
				body: expect.stringContaining("\"queueItemId\":\"q1\""),
			}),
		);
		expect(queueUpdates).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					qstash_message_id: null,
					last_error:
						"Manual recovery: overdue queued/pending item reset for fresh reconciliation dispatch",
				}),
			]),
		);
		expect(
			queueChains.some((chain) =>
				chain.or.mock.calls.some(([predicate]: [string]) =>
					predicate.includes("next_retry_at.is.null"),
				),
			),
		).toBe(true);
	});

	it("skips reconciliation when no stranded items found", async () => {
		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				return chainMock({ data: [], error: null });
			}
			return chainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(mockReq(), res);

		expect(mockFetch).not.toHaveBeenCalled();
	});

	it("handles individual reconciliation invoke failure gracefully", async () => {
		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				return chainMock({
					data: [{ id: "q1", workspace_id: "ws1", group_id: "g1" }],
					error: null,
				});
			}
			if (table === "account_groups") {
				return chainMock({
					data: [{ id: "g1", name: "Group", user_id: "u1" }],
					error: null,
				});
			}
			return chainMock({ data: null, error: null });
		});

		mockFetch.mockRejectedValue(new Error("invoke down"));

		const res = mockRes();
		await handler(mockReq(), res);

		// Should still complete without crashing — per-item error is caught
		expect(res.status).toHaveBeenCalledWith(200);
	});

	// ── 6. Phase 4: Queue Fill Dispatch ──

	it("dispatches AI fill when group queue is empty", async () => {
		let autoPostQueueCallCount = 0;
		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				autoPostQueueCallCount++;
				if (autoPostQueueCallCount === 1) {
					// Phase 3: stranded items — none
					return chainMock({ data: [], error: null });
				}
				// Phase 4: count for group — EMPTY (safety net fires at 0)
				return chainMock({ data: null, error: null, count: 0 });
			}
			if (table === "auto_post_config") {
				// Phase 4 config: enabled with AI queue fill
				return chainMock({
					data: [{
						workspace_id: "ws1",
						is_enabled: true,
						group_mode_enabled: true,
						enable_ai_queue_fill: true,
					}],
					error: null,
				});
			}
			if (table === "auto_post_group_config") {
				return chainMock({
					data: [{ group_id: "g1", workspace_id: "ws1" }],
					error: null,
				});
			}
			if (table === "account_groups") {
				return chainMock({
					data: [{ id: "g1", name: "Group1", user_id: "u1" }],
					error: null,
				});
			}
			return chainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(mockReq(), res);

		// Should dispatch fill via dispatchQueueFill helper
		expect(mockDispatchQueueFill).toHaveBeenCalledWith("ws1", "u1", "g1", "Group1");
	});

	it("skips fill when queue count is above zero", async () => {
		let autoPostQueueCallCount = 0;
		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				autoPostQueueCallCount++;
				if (autoPostQueueCallCount === 1) {
					return chainMock({ data: [], error: null });
				}
				// Non-empty queue — dawn planner handles this
				return chainMock({ data: null, error: null, count: 3 });
			}
			if (table === "auto_post_config") {
				return chainMock({
					data: [{
						workspace_id: "ws1",
						is_enabled: true,
						group_mode_enabled: true,
						enable_ai_queue_fill: true,
					}],
					error: null,
				});
			}
			if (table === "auto_post_group_config") {
				return chainMock({
					data: [{ group_id: "g1", workspace_id: "ws1" }],
					error: null,
				});
			}
			if (table === "account_groups") {
				return chainMock({
					data: [{ id: "g1", name: "Group1", user_id: "u1" }],
					error: null,
				});
			}
			return chainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(mockReq(), res);

		// No fill dispatch — safety net only fires when queue is empty
		expect(mockDispatchQueueFill).not.toHaveBeenCalled();
	});

	it("skips fill when auto_post_config is disabled", async () => {
		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				return chainMock({ data: [], error: null });
			}
			if (table === "auto_post_config") {
				return chainMock({ data: null, error: null });
			}
			return chainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(mockReq(), res);

		expect(mockQStashPublishJSON).not.toHaveBeenCalled();
	});

	// ── 7. Cross-Phase Error Handling ──

	it("alerts on Phase 1 failure and Phase 4 failure independently", async () => {
		mockProcessScheduledPosts.mockRejectedValue(new Error("P1 fail"));

		// Keep enabled workspace lookup working, then fail during Phase 4 group config fetch.
		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				return chainMock({ data: [], error: null });
			}
			if (table === "auto_post_config") {
				return chainMock({
					data: [{
						workspace_id: "ws1",
						scheduler_version: 4,
						group_mode_enabled: true,
						enable_ai_queue_fill: true,
					}],
					error: null,
				});
			}
			if (table === "auto_post_group_config") {
				throw new Error("P4 fail");
			}
			return chainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(mockReq(), res);

		// Phase 1 fires alertCronFailure
		expect(mockAlertCronFailure).toHaveBeenCalledWith(
			"publish-worker",
			expect.stringContaining("P1 fail"),
		);
		// Phase 4 also fires alertCronFailure
		expect(mockAlertCronFailure).toHaveBeenCalledWith(
			"publish-worker",
			expect.stringContaining("P4 fail"),
		);
		expect(mockAlertCronFailure).toHaveBeenCalledTimes(2);
	});

	// ── 8. Full Happy Path ──

	it("completes all 4 phases successfully", async () => {
		mockProcessScheduledPosts.mockResolvedValue(2);
		mockProcessPendingContainers.mockResolvedValue(1);

		// Phase 3: no stranded items
		// Phase 4: no fill needed
		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				return chainMock({ data: [], error: null });
			}
			return chainMock({ data: null, error: null });
		});

		const res = mockRes();
		await handler(mockReq(), res);

		expect(mockProcessScheduledPosts).toHaveBeenCalled();
		expect(mockProcessPendingContainers).toHaveBeenCalled();
		expect(mockAlertCronFailure).not.toHaveBeenCalled();
		expect(res.status).toHaveBeenCalledWith(200);
		expect(res.json).toHaveBeenCalledWith(
			expect.objectContaining({ ok: true }),
		);
	});

	// ── 9. Config: maxDuration ──

	it("exports maxDuration of 180", async () => {
		const mod = await import("../../api/cron/publish-worker");
		expect(mod.config.maxDuration).toBe(180);
	});
});
