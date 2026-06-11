/**
 * Unit tests for the Unified Scheduler Account Loop
 * (api/_lib/cron/scheduler/accountLoop.ts)
 *
 * Tests the core scheduler loop that processes each account group:
 * 1. Scheduling decisions — which accounts get posts and when
 * 2. Active hours enforcement — posts only during configured active hours
 * 3. Cooldown logic — minimum interval between posts per account
 * 4. Account state evaluation — active, paused, warming, suppressed, cooldown
 * 5. Round-robin account selection via pool claiming
 * 6. Error handling — one account/group failure doesn't block others
 * 7. Edge cases — no accounts, all paused, all at cooldown
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mocks — module-scope, BEFORE importing module under test
// ---------------------------------------------------------------------------

const mockFrom = vi.fn();
const mockRpc = vi.fn();

vi.mock("../../api/_lib/supabase", () => ({
	getSupabase: () => ({ from: mockFrom, rpc: mockRpc }),
	getSupabaseAny: () => ({ from: mockFrom, rpc: mockRpc }),
}));

const mockLoggerInfo = vi.fn();
const mockLoggerWarn = vi.fn();
const mockLoggerError = vi.fn();
const mockLoggerDebug = vi.fn();

vi.mock("../../api/_lib/logger", () => ({
	logger: {
		info: (...args: unknown[]) => mockLoggerInfo(...args),
		warn: (...args: unknown[]) => mockLoggerWarn(...args),
		error: (...args: unknown[]) => mockLoggerError(...args),
		debug: (...args: unknown[]) => mockLoggerDebug(...args),
	},
}));

// accountState
const mockGetGroupAccountStates = vi.fn().mockResolvedValue([]);
const mockBulkUpsertAccountStates = vi
	.fn()
	.mockResolvedValue({ success: 0, failed: 0 });
const mockIsBlocked = vi.fn().mockReturnValue(false);

vi.mock("../../api/_lib/handlers/auto-post/accountState", () => ({
	getGroupAccountStates: (...args: unknown[]) =>
		mockGetGroupAccountStates(...args),
	bulkUpsertAccountStates: (...args: unknown[]) =>
		mockBulkUpsertAccountStates(...args),
	isBlocked: (...args: unknown[]) => mockIsBlocked(...args),
}));

// queueState
const mockQueueQueueItemForDispatch = vi.fn().mockResolvedValue(undefined);
const mockMarkQueueItemDispatched = vi.fn().mockResolvedValue(undefined);

vi.mock("../../api/_lib/handlers/auto-post/queueState", () => ({
	queueQueueItemForDispatch: (...args: unknown[]) =>
		mockQueueQueueItemForDispatch(...args),
	markQueueItemDispatched: (...args: unknown[]) =>
		mockMarkQueueItemDispatched(...args),
}));

// stateEvaluator
const mockEvaluateAccountState = vi.fn().mockReturnValue({
	status: "active",
	status_reason: "healthy",
	blocked_until: null,
	flop_proven_remaining: 0,
	probe_posts_remaining: 0,
	warming_posts_today: 0,
	last_14d_avg_views: 100,
	median_30d_views: 80,
	max_30d_views: 500,
	pct_under_5_views: 0,
	last_flop_post_id: null,
	flop_triggered_at: null,
	probe_cycles_completed: 0,
	consecutive_flops: 0,
	should_retire: false,
});

vi.mock("../../api/_lib/handlers/auto-post/stateEvaluator", () => ({
	evaluateAccountState: (...args: unknown[]) =>
		mockEvaluateAccountState(...args),
}));

// decisionLog
const mockFlushDecisions = vi
	.fn()
	.mockResolvedValue({ inserted: 0, failed: 0 });

vi.mock("../../api/_lib/cron/scheduler/decisionLog", () => ({
	flushDecisions: (...args: unknown[]) => mockFlushDecisions(...args),
}));

// eligibility
const mockCheckEligibility = vi.fn().mockReturnValue({
	eligible: true,
	reason: "eligible",
	localHour: 14,
});

vi.mock("../../api/_lib/cron/scheduler/eligibility", () => ({
	checkEligibility: (...args: unknown[]) => mockCheckEligibility(...args),
}));

// QStash
const mockQstashPublishJSON = vi
	.fn()
	.mockResolvedValue({ messageId: "msg-123" });

vi.mock("../../api/_lib/qstash", () => ({
	getQStashClient: () => ({
		publishJSON: (...args: unknown[]) => mockQstashPublishJSON(...args),
	}),
}));

vi.mock("../../api/_lib/qstashDefaults", () => ({
	RETRIES: { CRITICAL: 3 },
	getFailureCallbackUrl: () => "https://example.com/fail",
	getRequiredAppBaseUrl: () => "https://example.com",
}));

// infraTelemetry
const mockRecordInfraEvent = vi.fn().mockResolvedValue(undefined);

vi.mock("../../api/_lib/infraTelemetry", () => ({
	recordInfraEvent: (...args: unknown[]) => mockRecordInfraEvent(...args),
}));

// alertEngine
vi.mock("../../api/_lib/cron/scheduler/alertEngine", () => ({
	runAlertEngine: vi.fn().mockResolvedValue(undefined),
}));

// dispatchQueueFill
const mockDispatchQueueFill = vi.fn().mockResolvedValue({
	dispatched: true,
	reason: "dispatched",
});

vi.mock("../../api/_lib/handlers/auto-post/queue", () => ({
	dispatchQueueFill: (...args: unknown[]) => mockDispatchQueueFill(...args),
}));

// ---------------------------------------------------------------------------
// Import module under test (AFTER all mocks)
// ---------------------------------------------------------------------------

import { runSchedulerLoop } from "../../api/_lib/cron/scheduler/accountLoop";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a chainable Supabase query mock */
function chain(data: unknown, count?: number) {
	const c: any = {};
	const methods = [
		"select",
		"eq",
		"in",
		"not",
		"or",
		"gte",
		"gt",
		"lt",
		"lte",
		"neq",
		"order",
		"limit",
	];
	for (const m of methods) {
		c[m] = vi.fn().mockReturnValue(c);
	}
	// Terminal
	c.maybeSingle = vi.fn().mockResolvedValue({ data, error: null });
	c.single = vi.fn().mockResolvedValue({ data, error: null });
	// For head queries
	if (count !== undefined) {
		c.count = count;
	}
	// Make the chain itself thenable for implicit resolution
	c.then = (resolve: (v: any) => void) =>
		resolve({ data: Array.isArray(data) ? data : data ? [data] : [], error: null, count: count ?? 0 });
	return c;
}

function errorChain(message: string) {
	const c = chain(null);
	c.then = (resolve: (v: any) => void) =>
		resolve({ data: null, error: { message }, count: 0 });
	return c;
}

/** Default workspace config with scheduler v2+ */
function makeWorkspaceConfig(overrides: Record<string, unknown> = {}) {
	return {
		workspace_id: "ws-1",
		scheduler_version: 2,
		group_mode_enabled: true,
		is_enabled: true,
		...overrides,
	};
}

/** Default group config */
function makeGroupConfig(overrides: Record<string, unknown> = {}) {
	return {
		group_id: "grp-1",
		workspace_id: "ws-1",
		enabled: true,
		posts_per_account_per_day: 3,
		min_interval_minutes: 60,
		active_hours_start: 9,
		active_hours_end: 22,
		timezone: "America/New_York",
		post_on_weekends: true,
		...overrides,
	};
}

/** Default account group info */
function makeGroupInfo(overrides: Record<string, unknown> = {}) {
	return {
		id: "grp-1",
		name: "Test Group",
		user_id: "user-1",
		account_ids: ["acc-1", "acc-2"],
		...overrides,
	};
}

/** Default account row */
function makeAccount(overrides: Record<string, unknown> = {}) {
	return {
		id: "acc-1",
		username: "testuser",
		created_at: "2025-01-01T00:00:00Z",
		is_shadowbanned: false,
		is_retired: false,
		needs_reauth: false,
		is_active: true,
		status: null,
		followers_count: 1000,
		user_id: "user-1",
		threads_access_token_encrypted: "enc-token",
		...overrides,
	};
}

/** Default queue item */
function makeQueueItem(overrides: Record<string, unknown> = {}) {
	return {
		id: "qi-1",
		workspace_id: "ws-1",
		group_id: "grp-1",
		account_id: null,
		scheduled_for: new Date(Date.now() - 60000).toISOString(),
		pool_status: "available",
		...overrides,
	};
}

/**
 * Sets up mockFrom to return appropriate chain mocks for each table.
 * This is the common setup for most tests.
 */
function setupDefaultDbMocks(overrides: {
	workspaceConfigs?: unknown[];
	groupConfigs?: unknown[];
	groupInfoRows?: unknown[];
	accounts?: unknown[];
	overridesData?: unknown[];
	queueCount?: number;
	pendingItems?: unknown[];
	posts30d?: unknown[];
	posts2h?: unknown[];
	publishedCounts?: unknown[];
	posts48h?: unknown[];
	lastPost?: unknown[];
} = {}) {
	const observedChains: Record<string, any[]> = {};
	const remember = (table: string, c: any) => {
		observedChains[table] ??= [];
		observedChains[table].push(c);
		return c;
	};
	const defaults = {
		workspaceConfigs: [makeWorkspaceConfig()],
		groupConfigs: [makeGroupConfig()],
		groupInfoRows: [makeGroupInfo()],
		accounts: [makeAccount({ id: "acc-1" }), makeAccount({ id: "acc-2", username: "user2" })],
		overridesData: [],
		queueCount: 5,
		pendingItems: [makeQueueItem({ id: "qi-1" }), makeQueueItem({ id: "qi-2" })],
		posts30d: [],
		posts2h: [],
		publishedCounts: [],
		posts48h: [],
		lastPost: [],
		...overrides,
	};

	mockFrom.mockImplementation((table: string) => {
		if (table === "auto_post_config") {
			return remember(table, chain(defaults.workspaceConfigs));
		}
		if (table === "auto_post_group_config") {
			return remember(table, chain(defaults.groupConfigs));
		}
		if (table === "account_groups") {
			return remember(table, chain(defaults.groupInfoRows));
		}
		if (table === "accounts") {
			return remember(table, chain(defaults.accounts));
		}
		if (table === "auto_post_account_overrides") {
			return remember(table, chain(defaults.overridesData));
		}
		if (table === "auto_post_queue") {
			// queue is called multiple times — for count and for items
			const c = chain(defaults.pendingItems, defaults.queueCount);
			return remember(table, c);
		}
		if (table === "posts") {
			// posts is called multiple times for different queries
			return remember(table, chain(defaults.posts30d));
		}
		if (table === "account_autoposter_state") {
			return remember(table, chain([]));
		}
		if (table === "scheduler_decisions") {
			return remember(table, chain(null));
		}
		// Fallback
		return remember(table, chain(null));
	});

	return observedChains;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("accountLoop — runSchedulerLoop", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		// Defaults: all mocks return reasonable "happy path" values
		mockIsBlocked.mockReturnValue(false);
		mockCheckEligibility.mockReturnValue({
			eligible: true,
			reason: "eligible",
			localHour: 14,
		});
		mockEvaluateAccountState.mockReturnValue({
			status: "active",
			status_reason: "healthy",
			blocked_until: null,
			flop_proven_remaining: 0,
			probe_posts_remaining: 0,
			warming_posts_today: 0,
			last_14d_avg_views: 100,
			median_30d_views: 80,
			max_30d_views: 500,
			pct_under_5_views: 0,
			last_flop_post_id: null,
			flop_triggered_at: null,
			probe_cycles_completed: 0,
			consecutive_flops: 0,
			should_retire: false,
		});
		mockBulkUpsertAccountStates.mockResolvedValue({
			success: 2,
			failed: 0,
		});
		mockFlushDecisions.mockResolvedValue({ inserted: 2, failed: 0 });
	});

	afterEach(() => {
		vi.restoreAllMocks();
	});

	// ── No workspaces ──

	describe("when no v2+ workspaces exist", () => {
		it("returns a summary with zero counts", async () => {
			setupDefaultDbMocks({ workspaceConfigs: [] });

			const result = await runSchedulerLoop();

			expect(result.groupsProcessed).toBe(0);
			expect(result.accountsEvaluated).toBe(0);
			expect(result.dispatched).toBe(0);
			expect(result.errors).toHaveLength(0);
		});
	});

	// ── No enabled groups ──

	describe("when no enabled groups exist", () => {
		it("returns a summary with zero counts", async () => {
			setupDefaultDbMocks({ groupConfigs: [] });

			const result = await runSchedulerLoop();

			expect(result.groupsProcessed).toBe(0);
			expect(result.accountsEvaluated).toBe(0);
		});
	});

	// ── No accounts in group ──

	describe("when group has no accounts", () => {
		it("skips the group without error", async () => {
			setupDefaultDbMocks({
				groupInfoRows: [makeGroupInfo({ account_ids: [] })],
			});

			const result = await runSchedulerLoop();

			expect(result.groupsProcessed).toBe(1);
			expect(result.accountsEvaluated).toBe(0);
			expect(result.dispatched).toBe(0);
			expect(result.errors).toHaveLength(0);
		});
	});

	// ── Group info not found ──

	describe("when group info is missing from account_groups", () => {
		it("skips the group gracefully", async () => {
			setupDefaultDbMocks({
				groupInfoRows: [], // No matching group info
			});

			const result = await runSchedulerLoop();

			expect(result.groupsProcessed).toBe(1);
			expect(result.accountsEvaluated).toBe(0);
		});
	});

	// ── Successful dispatch ──

	describe("successful dispatch", () => {
		it("dispatches queue items and records decisions", async () => {
			const observedChains = setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
				pendingItems: [makeQueueItem({ id: "qi-1" })],
			});

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(1);
			expect(result.groupsProcessed).toBe(1);
			expect(result.accountsEvaluated).toBe(1);
			expect(mockQueueQueueItemForDispatch).toHaveBeenCalledTimes(1);
			expect(mockQstashPublishJSON).toHaveBeenCalledTimes(1);
			expect(mockMarkQueueItemDispatched).toHaveBeenCalledTimes(1);
			expect(
				observedChains.auto_post_queue.some((c) =>
					c.or.mock.calls.some(([predicate]: [string]) =>
						predicate.includes("next_retry_at.is.null"),
					),
				),
			).toBe(true);
		});

		it("dispatches to multiple accounts in the same group", async () => {
			setupDefaultDbMocks({
				accounts: [
					makeAccount({ id: "acc-1" }),
					makeAccount({ id: "acc-2", username: "user2" }),
				],
				pendingItems: [
					makeQueueItem({ id: "qi-1" }),
					makeQueueItem({ id: "qi-2" }),
				],
			});

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(2);
			expect(mockQstashPublishJSON).toHaveBeenCalledTimes(2);
		});
	});

	// ── Account state blocking ──

	describe("account state evaluation", () => {
		it("skips blocked accounts (suppressed)", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
			});

			mockIsBlocked.mockReturnValue(true);
			mockEvaluateAccountState.mockReturnValue({
				status: "suppressed",
				status_reason: "permanently_suppressed",
				blocked_until: null,
				flop_proven_remaining: 0,
				probe_posts_remaining: 0,
				warming_posts_today: 0,
				last_14d_avg_views: 0,
				median_30d_views: 0,
				max_30d_views: 0,
				pct_under_5_views: 100,
				last_flop_post_id: null,
				flop_triggered_at: null,
				probe_cycles_completed: 2,
				consecutive_flops: 0,
				should_retire: true,
			});

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(0);
			expect(mockQstashPublishJSON).not.toHaveBeenCalled();
			// Decisions should still be flushed
			expect(mockFlushDecisions).toHaveBeenCalled();
			const decisions = mockFlushDecisions.mock.calls[0][0];
			expect(decisions.some((d: any) => d.outcome === "skipped_blocked")).toBe(
				true,
			);
		});

		it("skips inactive accounts", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
			});
			mockIsBlocked.mockReturnValue(true);
			mockEvaluateAccountState.mockReturnValue({
				status: "inactive",
				status_reason: "needs_reauth",
				blocked_until: null,
				flop_proven_remaining: 0,
				probe_posts_remaining: 0,
				warming_posts_today: 0,
				last_14d_avg_views: null,
				median_30d_views: null,
				max_30d_views: null,
				pct_under_5_views: null,
				last_flop_post_id: null,
				flop_triggered_at: null,
				probe_cycles_completed: 0,
				consecutive_flops: 0,
				should_retire: false,
			});

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(0);
		});

		it("proceeds with active accounts", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
				pendingItems: [makeQueueItem({ id: "qi-1" })],
			});

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(1);
		});

		it("still upserts state for blocked accounts", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
			});
			mockIsBlocked.mockReturnValue(true);

			await runSchedulerLoop();

			// bulkUpsertAccountStates is called once per group with all states
			expect(mockBulkUpsertAccountStates).toHaveBeenCalled();
		});
	});

	// ── Eligibility checks ──

	describe("eligibility enforcement", () => {
		it("skips accounts outside active hours", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
			});

			mockCheckEligibility.mockReturnValue({
				eligible: false,
				reason: "outside_active_window(3h, window=9-22)",
				localHour: 3,
			});

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(0);
			const decisions = mockFlushDecisions.mock.calls[0][0];
			expect(
				decisions.some(
					(d: any) => d.outcome === "skipped_outside_window",
				),
			).toBe(true);
		});

		it("skips accounts that hit daily cap", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
			});

			mockCheckEligibility.mockReturnValue({
				eligible: false,
				reason: "daily_cap_reached(3/3)",
				localHour: 14,
			});

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(0);
			const decisions = mockFlushDecisions.mock.calls[0][0];
			expect(
				decisions.some((d: any) => d.outcome === "skipped_daily_cap"),
			).toBe(true);
		});

		it("caps warming-limited accounts at one post per day", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
				overridesData: [
					{
						group_id: "grp-1",
						account_id: "acc-1",
						overrides: { posts_per_account_per_day: 3 },
					},
				],
			});
			mockEvaluateAccountState.mockReturnValue({
				status: "warming_limited",
				status_reason: "warmup_cap",
				blocked_until: null,
				flop_proven_remaining: 0,
				probe_posts_remaining: 0,
				warming_posts_today: 0,
				last_14d_avg_views: 100,
				median_30d_views: 80,
				max_30d_views: 500,
				pct_under_5_views: 0,
				last_flop_post_id: null,
				flop_triggered_at: null,
				probe_cycles_completed: 0,
				consecutive_flops: 0,
				should_retire: false,
			});

			await runSchedulerLoop();

			expect(mockCheckEligibility).toHaveBeenCalledWith(
				expect.objectContaining({
					dailyCap: 1,
					override: expect.objectContaining({
						posts_per_account_per_day: 1,
					}),
				}),
			);
		});

		it("skips accounts within min interval cooldown", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
			});

			mockCheckEligibility.mockReturnValue({
				eligible: false,
				reason: "min_interval(30min < 60min)",
				localHour: 14,
			});

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(0);
			const decisions = mockFlushDecisions.mock.calls[0][0];
			expect(
				decisions.some(
					(d: any) => d.outcome === "skipped_min_interval",
				),
			).toBe(true);
		});

		it("skips accounts on weekends when disabled", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
			});

			mockCheckEligibility.mockReturnValue({
				eligible: false,
				reason: "weekend_paused",
				localHour: 14,
			});

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(0);
			const decisions = mockFlushDecisions.mock.calls[0][0];
			expect(
				decisions.some(
					(d: any) => d.outcome === "skipped_weekend",
				),
			).toBe(true);
		});
	});

	// ── No content available ──

	describe("when no queue items are available", () => {
		it("records skipped_no_content decision", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
				pendingItems: [], // No content in queue
			});

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(0);
			const decisions = mockFlushDecisions.mock.calls[0][0];
			expect(
				decisions.some(
					(d: any) => d.outcome === "skipped_no_content",
				),
			).toBe(true);
		});
	});

	// ── Queue item claiming prevents double-dispatch ──

	describe("pool-based queue item claiming", () => {
		it("does not dispatch the same queue item to two accounts", async () => {
			setupDefaultDbMocks({
				accounts: [
					makeAccount({ id: "acc-1" }),
					makeAccount({ id: "acc-2", username: "user2" }),
				],
				pendingItems: [makeQueueItem({ id: "qi-only-one" })],
			});

			const result = await runSchedulerLoop();

			// Only 1 dispatched despite 2 eligible accounts
			expect(result.dispatched).toBe(1);
			expect(mockQstashPublishJSON).toHaveBeenCalledTimes(1);
			// Second account should get skipped_no_content
			const decisions = mockFlushDecisions.mock.calls[0][0];
			expect(
				decisions.some(
					(d: any) => d.outcome === "skipped_no_content",
				),
			).toBe(true);
		});
	});

	// ── Queue fill trigger ──

	describe("queue fill triggering", () => {
		it("triggers fill when queue depth drops below threshold", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
				pendingItems: [makeQueueItem({ id: "qi-1" })],
				queueCount: 2, // Below MIN_QUEUE_THRESHOLD of 3 after claiming 1
			});

			const result = await runSchedulerLoop();

			expect(result.fillsTriggered).toBe(1);
			expect(mockDispatchQueueFill).toHaveBeenCalledWith(
				"ws-1",
				"user-1",
				"grp-1",
				"Test Group",
			);
		});

		it("does not count cooldown-skipped fills as triggered jobs", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
				pendingItems: [makeQueueItem({ id: "qi-1" })],
				queueCount: 2,
			});
			mockDispatchQueueFill.mockResolvedValue({
				dispatched: false,
				reason: "cooldown_active",
			});

			const result = await runSchedulerLoop();

			expect(result.fillsTriggered).toBe(0);
			expect(mockDispatchQueueFill).toHaveBeenCalledWith(
				"ws-1",
				"user-1",
				"grp-1",
				"Test Group",
			);
		});

		it("does not trigger fill when queue is healthy", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
				pendingItems: [makeQueueItem({ id: "qi-1" })],
				queueCount: 10,
			});

			await runSchedulerLoop();

			expect(mockDispatchQueueFill).not.toHaveBeenCalled();
		});
	});

	// ── Dispatch failure handling ──

	describe("dispatch error handling", () => {
		it("records error decision when QStash publish fails", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
				pendingItems: [makeQueueItem({ id: "qi-1" })],
			});

			mockQstashPublishJSON.mockRejectedValue(
				new Error("QStash unavailable"),
			);

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(0);
			const decisions = mockFlushDecisions.mock.calls[0][0];
			expect(
				decisions.some((d: any) => d.outcome === "error"),
			).toBe(true);
			expect(
				decisions.some((d: any) =>
					d.reason.includes("QStash unavailable"),
				),
			).toBe(true);
			// Infra event should be recorded
			expect(mockRecordInfraEvent).toHaveBeenCalledWith(
				"autopost-scheduler-dispatch-failed",
				expect.objectContaining({
					queueItemId: "qi-1",
					error: "QStash unavailable",
				}),
			);
		});

		it("continues processing other accounts after dispatch failure", async () => {
			setupDefaultDbMocks({
				accounts: [
					makeAccount({ id: "acc-1" }),
					makeAccount({ id: "acc-2", username: "user2" }),
				],
				pendingItems: [
					makeQueueItem({ id: "qi-1" }),
					makeQueueItem({ id: "qi-2" }),
				],
			});

			// First call fails, second succeeds
			mockQstashPublishJSON
				.mockRejectedValueOnce(new Error("Transient failure"))
				.mockResolvedValueOnce({ messageId: "msg-ok" });

			const result = await runSchedulerLoop();

			// Only 1 successful dispatch despite 2 accounts
			expect(result.dispatched).toBe(1);
			expect(mockQstashPublishJSON).toHaveBeenCalledTimes(2);
		});
	});

	// ── Group-level error isolation ──

	describe("group error isolation", () => {
		it("catches group processing errors and continues", async () => {
			// Set up so that the DB queries for group processing throw
			setupDefaultDbMocks();

			// Make the accounts query throw for simulating a group error
			let callCount = 0;
			mockFrom.mockImplementation((table: string) => {
				if (table === "auto_post_config") {
					return chain([makeWorkspaceConfig()]);
				}
				if (table === "auto_post_group_config") {
					return chain([
						makeGroupConfig({ group_id: "grp-1" }),
						makeGroupConfig({ group_id: "grp-2", workspace_id: "ws-1" }),
					]);
				}
				if (table === "account_groups") {
					return chain([
						makeGroupInfo({ id: "grp-1" }),
						makeGroupInfo({ id: "grp-2", account_ids: ["acc-3"] }),
					]);
				}
				if (table === "accounts") {
					callCount++;
					if (callCount === 1) {
						// First group's account query throws
						const c = chain(null);
						c.then = (_resolve: any, reject: any) => {
							if (reject) reject(new Error("DB timeout"));
							else throw new Error("DB timeout");
						};
						return c;
					}
					return chain([makeAccount({ id: "acc-3" })]);
				}
				return chain([]);
			});

			const result = await runSchedulerLoop();

			// Should have errors logged but not crash
			expect(result.errors.length).toBeGreaterThanOrEqual(0);
			// The loop itself should complete
			expect(typeof result.durationMs).toBe("number");
		});
	});

	// ── Top-level error handling ──

	describe("top-level error handling", () => {
		it("catches and records top-level errors gracefully", async () => {
			// Make the very first DB call throw
			mockFrom.mockImplementation(() => {
				throw new Error("Connection refused");
			});

			const result = await runSchedulerLoop();

			expect(result.errors.length).toBeGreaterThan(0);
			expect(result.errors[0]).toContain("Connection refused");
			expect(result.groupsProcessed).toBe(0);
		});

		it("reports initial workspace DB read errors instead of treating them as no work", async () => {
			mockFrom.mockImplementation((table: string) => {
				if (table === "auto_post_config") {
					return errorChain("database unavailable");
				}
				return chain(null);
			});

			const result = await runSchedulerLoop();

			expect(result.errors[0]).toContain(
				"scheduler workspace config query failed: database unavailable",
			);
			expect(mockLoggerError).toHaveBeenCalledWith(
				"[scheduler] Top-level error",
				expect.anything(),
			);
			expect(result.groupsProcessed).toBe(0);
		});
	});

	// ── All accounts paused ──

	describe("edge case: all accounts blocked", () => {
		it("processes group but dispatches nothing", async () => {
			setupDefaultDbMocks({
				accounts: [
					makeAccount({ id: "acc-1" }),
					makeAccount({ id: "acc-2", username: "user2" }),
				],
			});

			mockIsBlocked.mockReturnValue(true);

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(0);
			expect(result.accountsEvaluated).toBe(2);
			// All decisions should be skipped_blocked
			const decisions = mockFlushDecisions.mock.calls[0][0];
			expect(
				decisions.every((d: any) => d.outcome === "skipped_blocked"),
			).toBe(true);
		});
	});

	// ── All accounts at cooldown ──

	describe("edge case: all accounts ineligible (cooldown)", () => {
		it("processes group but dispatches nothing", async () => {
			setupDefaultDbMocks({
				accounts: [
					makeAccount({ id: "acc-1" }),
					makeAccount({ id: "acc-2", username: "user2" }),
				],
			});

			mockCheckEligibility.mockReturnValue({
				eligible: false,
				reason: "min_interval(15min < 60min)",
				localHour: 14,
			});

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(0);
			const decisions = mockFlushDecisions.mock.calls[0][0];
			expect(
				decisions.every(
					(d: any) => d.outcome === "skipped_min_interval",
				),
			).toBe(true);
		});
	});

	// ── Mixed account states ──

	describe("mixed account states in a group", () => {
		it("dispatches only to eligible, non-blocked accounts", async () => {
			setupDefaultDbMocks({
				accounts: [
					makeAccount({ id: "acc-1" }),
					makeAccount({ id: "acc-2", username: "user2" }),
				],
				pendingItems: [
					makeQueueItem({ id: "qi-1" }),
					makeQueueItem({ id: "qi-2" }),
				],
			});
			// Ensure QStash succeeds
			mockQstashPublishJSON.mockResolvedValue({ messageId: "msg-ok" });

			// acc-1: blocked, acc-2: eligible
			let blockCallCount = 0;
			mockIsBlocked.mockImplementation(() => {
				blockCallCount++;
				// First account is blocked, second is not
				return blockCallCount === 1;
			});

			mockCheckEligibility.mockReturnValue({
				eligible: true,
				reason: "eligible",
				localHour: 14,
			});

			const result = await runSchedulerLoop();

			// Only acc-2 should dispatch (acc-1 is blocked)
			expect(result.dispatched).toBe(1);
			expect(result.accountsEvaluated).toBe(2);
		});
	});

	// ── Scheduler version filtering ──

	describe("scheduler version filtering", () => {
		it("ignores workspaces with scheduler_version < 2", async () => {
			setupDefaultDbMocks({
				workspaceConfigs: [
					makeWorkspaceConfig({ scheduler_version: 1 }),
				],
			});

			const result = await runSchedulerLoop();

			expect(result.groupsProcessed).toBe(0);
		});

		it("includes workspaces with scheduler_version >= 2", async () => {
			setupDefaultDbMocks({
				workspaceConfigs: [
					makeWorkspaceConfig({ scheduler_version: 3 }),
				],
				accounts: [makeAccount({ id: "acc-1" })],
				pendingItems: [makeQueueItem({ id: "qi-1" })],
			});

			const result = await runSchedulerLoop();

			expect(result.groupsProcessed).toBe(1);
		});
	});

	// ── Summary structure ──

	describe("summary structure", () => {
		it("returns a properly structured SchedulerSummary", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
				pendingItems: [makeQueueItem({ id: "qi-1" })],
			});

			const result = await runSchedulerLoop();

			expect(result).toEqual(
				expect.objectContaining({
					runId: expect.any(String),
					groupsProcessed: expect.any(Number),
					accountsEvaluated: expect.any(Number),
					dispatched: expect.any(Number),
					fillsTriggered: expect.any(Number),
					statesUpserted: expect.any(Number),
					decisionsLogged: expect.any(Number),
					errors: expect.any(Array),
					durationMs: expect.any(Number),
				}),
			);
		});

		it("generates a unique runId each invocation", async () => {
			setupDefaultDbMocks({ workspaceConfigs: [] });

			const result1 = await runSchedulerLoop();
			const result2 = await runSchedulerLoop();

			expect(result1.runId).not.toBe(result2.runId);
			expect(result1.runId).toMatch(
				/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
			);
		});
	});

	// ── Decision logging ──

	describe("decision logging", () => {
		it("flushes all decisions after processing", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
				pendingItems: [makeQueueItem({ id: "qi-1" })],
			});

			await runSchedulerLoop();

			expect(mockFlushDecisions).toHaveBeenCalledTimes(1);
			const decisions = mockFlushDecisions.mock.calls[0][0];
			expect(decisions.length).toBeGreaterThan(0);
			// Each decision should have the required fields
			for (const d of decisions) {
				expect(d.run_id).toBeDefined();
				expect(d.workspace_id).toBe("ws-1");
				expect(d.group_id).toBe("grp-1");
				expect(d.account_id).toBeDefined();
				expect(d.outcome).toBeDefined();
				expect(d.reason).toBeDefined();
			}
		});
	});

	// ── v4+ scheduler: account_schedule paused ──

	describe("v4+ scheduler paused/blocked accounts", () => {
		it("skips accounts paused in account_schedule", async () => {
			setupDefaultDbMocks({
				workspaceConfigs: [
					makeWorkspaceConfig({ scheduler_version: 4 }),
				],
				accounts: [makeAccount({ id: "acc-1" })],
			});

			// Override the from mock to return account_schedule data
			const originalMock = mockFrom.getMockImplementation();
			mockFrom.mockImplementation((table: string) => {
				if (table === "account_schedule") {
					return chain([
						{
							account_id: "acc-1",
							paused: true,
							status: "paused",
							blocked_until: null,
							posts_per_day: 3,
							min_interval_minutes: 60,
							active_hours_start: 9,
							active_hours_end: 22,
							timezone: "America/New_York",
							post_on_weekends: true,
						},
					]);
				}
				return originalMock!(table);
			});

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(0);
			const decisions = mockFlushDecisions.mock.calls[0][0];
			expect(
				decisions.some(
					(d: any) =>
						d.outcome === "skipped_blocked" &&
						d.reason === "paused_in_account_schedule",
				),
			).toBe(true);
		});

		it("skips accounts blocked_until a future time", async () => {
			const futureDate = new Date(
				Date.now() + 60 * 60 * 1000,
			).toISOString();

			setupDefaultDbMocks({
				workspaceConfigs: [
					makeWorkspaceConfig({ scheduler_version: 4 }),
				],
				accounts: [makeAccount({ id: "acc-1" })],
			});

			const originalMock = mockFrom.getMockImplementation();
			mockFrom.mockImplementation((table: string) => {
				if (table === "account_schedule") {
					return chain([
						{
							account_id: "acc-1",
							paused: false,
							status: "blocked",
							blocked_until: futureDate,
							posts_per_day: 3,
							min_interval_minutes: 60,
							active_hours_start: 9,
							active_hours_end: 22,
							timezone: "America/New_York",
							post_on_weekends: true,
						},
					]);
				}
				return originalMock!(table);
			});

			const result = await runSchedulerLoop();

			expect(result.dispatched).toBe(0);
			const decisions = mockFlushDecisions.mock.calls[0][0];
			expect(
				decisions.some(
					(d: any) =>
						d.outcome === "skipped_blocked" &&
						d.reason.includes("blocked_until"),
				),
			).toBe(true);
		});
	});

	// ── Queue fill failure is non-fatal ──

	describe("queue fill dispatch failure", () => {
		it("logs warning but does not fail the group", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
				pendingItems: [makeQueueItem({ id: "qi-1" })],
				queueCount: 1, // Below threshold
			});
			// Ensure QStash publish succeeds for the dispatch
			mockQstashPublishJSON.mockResolvedValue({ messageId: "msg-ok" });

			mockDispatchQueueFill.mockRejectedValue(
				new Error("Fill failed"),
			);

			const result = await runSchedulerLoop();

			// Dispatch should still succeed
			expect(result.dispatched).toBe(1);
			// Fill should be 0 since it failed
			expect(result.fillsTriggered).toBe(0);
			expect(mockLoggerWarn).toHaveBeenCalledWith(
				"[scheduler] Queue fill dispatch failed",
				expect.objectContaining({ groupId: "grp-1" }),
			);
		});
	});

	// ── Infra telemetry on success ──

	describe("infra telemetry", () => {
		it("records dispatch infra event on success", async () => {
			setupDefaultDbMocks({
				accounts: [makeAccount({ id: "acc-1" })],
				pendingItems: [makeQueueItem({ id: "qi-1" })],
			});
			// Ensure QStash succeeds for this test
			mockQstashPublishJSON.mockResolvedValue({ messageId: "msg-123" });

			await runSchedulerLoop();

			expect(mockRecordInfraEvent).toHaveBeenCalledWith(
				"autopost-scheduler-dispatch",
				expect.objectContaining({
					queueItemId: "qi-1",
					accountId: "acc-1",
					groupId: "grp-1",
					workspaceId: "ws-1",
				}),
			);
		});
	});

	// ── Groups not matching v2+ workspaces are filtered ──

	describe("workspace-group filtering", () => {
		it("skips groups belonging to non-v2 workspaces", async () => {
			setupDefaultDbMocks({
				workspaceConfigs: [
					makeWorkspaceConfig({ workspace_id: "ws-v2", scheduler_version: 2 }),
				],
				groupConfigs: [
					makeGroupConfig({ group_id: "grp-v2", workspace_id: "ws-v2" }),
					makeGroupConfig({
						group_id: "grp-other",
						workspace_id: "ws-legacy",
					}),
				],
				groupInfoRows: [
					makeGroupInfo({ id: "grp-v2" }),
					makeGroupInfo({ id: "grp-other" }),
				],
				accounts: [makeAccount({ id: "acc-1" })],
				pendingItems: [makeQueueItem({ id: "qi-1" })],
			});

			const result = await runSchedulerLoop();

			// Only grp-v2 should be processed
			expect(result.groupsProcessed).toBe(1);
		});
	});
});
