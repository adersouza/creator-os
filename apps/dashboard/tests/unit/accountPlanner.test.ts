import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockFrom = vi.fn();
const mockGetGroupAccountStates = vi.fn();

vi.mock("../../api/_lib/supabase.js", () => ({
	getSupabaseAny: () => ({ from: mockFrom }),
}));

vi.mock("../../api/_lib/logger.js", () => ({
	logger: {
		info: vi.fn(),
		warn: vi.fn(),
		error: vi.fn(),
		debug: vi.fn(),
	},
}));

vi.mock("../../api/_lib/handlers/auto-post/accountState.js", () => ({
	getGroupAccountStates: () => mockGetGroupAccountStates(),
	isBlocked: vi.fn(() => false),
}));

import { planAccountSlots } from "../../api/_lib/handlers/auto-post/accountPlanner";

function chainMock(finalValue: unknown = { data: null, error: null }) {
	const chain: Record<string, any> = {};
	for (const method of [
		"select",
		"eq",
		"in",
		"not",
		"or",
		"gte",
		"order",
		"limit",
	]) {
		chain[method] = vi.fn(() => chain);
	}
	chain.maybeSingle = vi.fn().mockResolvedValue(finalValue);
	chain.upsert = vi.fn().mockResolvedValue(finalValue);
	chain.then = (resolve: (value: unknown) => void, reject?: (err: unknown) => void) =>
		Promise.resolve(finalValue).then(resolve, reject);
	return chain;
}

function resolvedConfig(overrides: Record<string, unknown> = {}) {
	return {
		groupTimingConfig: {
			enabled: true,
			timezone: "America/Los_Angeles",
			active_hours_start: 8,
			active_hours_end: 22,
			post_on_weekends: true,
			min_interval_minutes: 30,
			posts_per_account_per_day: 4,
			min_posts_per_account_per_day: 1,
			rest_days_per_week: 0,
		},
		groupAccountIds: ["acc-1"],
		accountOverrides: new Map(),
		...overrides,
	} as any;
}

function makeAccount(overrides: Record<string, unknown> = {}) {
	return {
		id: "acc-1",
		username: "one",
		created_at: "2026-01-01T00:00:00Z",
		is_shadowbanned: false,
		is_retired: false,
		needs_reauth: false,
		is_active: true,
		status: null,
		followers_count: 500,
		sync_cohort: null,
		...overrides,
	};
}

function mockPlannerReads(
	publishedToday: Array<Record<string, unknown>> = [],
	accounts: Array<Record<string, unknown>> = [makeAccount()],
	accountSchedules: Array<Record<string, unknown>> = [],
) {
	const accountsQuery = chainMock({
		data: accounts,
		error: null,
	});
	const accountSchedulesQuery = chainMock({
		data: accountSchedules,
		error: null,
	});
	const queueReads = [
		chainMock({ data: [], error: null }),
		chainMock({ data: publishedToday, error: null }),
	];
	const groupStateRead = chainMock({
		data: { current_account_index: 0 },
		error: null,
	});
	const groupStateWrite = chainMock({ data: null, error: null });

	mockFrom.mockImplementation((table: string) => {
		if (table === "accounts") return accountsQuery;
		if (table === "account_schedule") return accountSchedulesQuery;
		if (table === "auto_post_queue") return queueReads.shift();
		if (table === "auto_post_group_state") {
			return groupStateRead.select.mock.calls.length === 0
				? groupStateRead
				: groupStateWrite;
		}
		throw new Error(`unexpected table ${table}`);
	});
}

describe("accountPlanner", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		vi.useFakeTimers();
		mockGetGroupAccountStates.mockResolvedValue([]);
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.restoreAllMocks();
	});

	it("honors resolved max_posts_per_day overrides as per-account daily caps", async () => {
		vi.setSystemTime(new Date("2026-05-13T16:00:00Z"));
		mockPlannerReads();

		const result = await planAccountSlots(
			"group-1",
			"workspace-1",
			"owner-1",
			2,
			resolvedConfig({
				accountOverrides: new Map([
					[
						"group-1:acc-1",
						{
							account_id: "acc-1",
							group_id: "group-1",
							max_posts_per_day: 1,
						},
					],
				]),
			}),
		);

		expect(result.slots).toHaveLength(1);
		expect(result.slots[0]?.accountId).toBe("acc-1");
	});

	it("counts published-today posts in the account timezone, not server midnight", async () => {
		vi.setSystemTime(new Date("2026-05-13T08:30:00Z"));
		mockPlannerReads([
			{
				account_id: "acc-1",
				posted_at: "2026-05-13T06:30:00Z",
			},
		]);

		const result = await planAccountSlots(
			"group-1",
			"workspace-1",
			"owner-1",
			1,
			resolvedConfig({
				groupTimingConfig: {
					...resolvedConfig().groupTimingConfig,
					posts_per_account_per_day: 1,
				},
			}),
		);

		expect(result.slots).toHaveLength(1);
		expect(result.slots[0]?.accountId).toBe("acc-1");
	});

	it("prefers the highest health score among eligible accounts", async () => {
		vi.setSystemTime(new Date("2026-05-13T16:00:00Z"));
		mockPlannerReads([], [
			makeAccount({ id: "acc-low", username: "low" }),
			makeAccount({ id: "acc-high", username: "high" }),
		]);
		mockGetGroupAccountStates.mockResolvedValue([
			{
				account_id: "acc-low",
				group_id: "group-1",
				workspace_id: "workspace-1",
				status: "active",
				account_health_score: 62,
			},
			{
				account_id: "acc-high",
				group_id: "group-1",
				workspace_id: "workspace-1",
				status: "active",
				account_health_score: 91,
			},
		]);

		const result = await planAccountSlots(
			"group-1",
			"workspace-1",
			"owner-1",
			1,
			resolvedConfig({ groupAccountIds: ["acc-low", "acc-high"] }),
		);

		expect(result.slots[0]?.accountId).toBe("acc-high");
	});

	it("uses account_schedule windows for planned slot timing metadata", async () => {
		vi.setSystemTime(new Date("2026-05-13T16:00:00Z"));
		mockPlannerReads(
			[],
			[makeAccount({ id: "acc-1", username: "one" })],
			[
				{
					account_id: "acc-1",
					active_hours_start: 2,
					active_hours_end: 8,
					timezone: "America/New_York",
					min_interval_minutes: 180,
					paused: false,
					status: "active",
				},
			],
		);

		const result = await planAccountSlots(
			"group-1",
			"workspace-1",
			"owner-1",
			1,
			resolvedConfig(),
		);

		expect(result.slots[0]).toMatchObject({
			accountId: "acc-1",
			activeHoursStart: 2,
			activeHoursEnd: 8,
			timezone: "America/New_York",
			minIntervalMinutes: 180,
		});
	});

	it("blocks a day 2 warm-up account after existing queued rows use its cap", async () => {
		vi.setSystemTime(new Date("2026-06-08T16:00:00Z"));
		mockPlannerReads([
			{
				account_id: "acc-1",
				status: "queued",
				scheduled_for: "2026-06-08T17:00:00Z",
			},
		]);
		mockGetGroupAccountStates.mockResolvedValue([
			{
				account_id: "acc-1",
				group_id: "group-1",
				workspace_id: "workspace-1",
				status: "active",
				account_health_score: 100,
				restart_warmup_status: "warming",
				restart_warmup_day: 2,
				restart_warmup_allowed_posts_per_day: 1,
				restart_warmup_reason: "restart_warmup_day_2",
			},
		]);

		const result = await planAccountSlots(
			"group-1",
			"workspace-1",
			"owner-1",
			1,
			resolvedConfig(),
		);

		expect(result.slots).toHaveLength(0);
	});

	it("blocks suppressed restart warm-up accounts even when account health is stale-high", async () => {
		vi.setSystemTime(new Date("2026-06-08T16:00:00Z"));
		mockPlannerReads();
		mockGetGroupAccountStates.mockResolvedValue([
			{
				account_id: "acc-1",
				group_id: "group-1",
				workspace_id: "workspace-1",
				status: "active",
				account_health_score: 100,
				restart_warmup_status: "suppressed",
				restart_warmup_day: 2,
				restart_warmup_allowed_posts_per_day: 0,
				restart_warmup_reason: "health_suppressed:26",
			},
		]);

		const result = await planAccountSlots(
			"group-1",
			"workspace-1",
			"owner-1",
			1,
			resolvedConfig(),
		);

		expect(result.slots).toHaveLength(0);
		expect(result.skipped[0]?.reason).toBe("restart_warmup_suppressed");
	});

	it("allows a suppressed_probe account to receive one spaced probe slot despite suppress mode", async () => {
		vi.setSystemTime(new Date("2026-05-13T16:00:00Z"));
		mockPlannerReads(
			[],
			[makeAccount({ id: "acc-probe", username: "probe" })],
			[
				{
					account_id: "acc-probe",
					active_hours_start: 8,
					active_hours_end: 22,
					timezone: "America/Los_Angeles",
					min_interval_minutes: 180,
					paused: false,
					status: "active",
				},
			],
		);
		mockGetGroupAccountStates.mockResolvedValue([
			{
				account_id: "acc-probe",
				group_id: "group-1",
				workspace_id: "workspace-1",
				status: "suppressed_probe",
				account_health_score: 55,
				recommended_strategy_mode: "suppress",
				recommended_posts_per_day: 0,
				probe_posts_remaining: 3,
			},
		]);

		const result = await planAccountSlots(
			"group-1",
			"workspace-1",
			"owner-1",
			2,
			resolvedConfig({ groupAccountIds: ["acc-probe"] }),
		);

		expect(result.slots).toHaveLength(1);
		expect(result.slots[0]).toMatchObject({
			accountId: "acc-probe",
			isProbe: true,
			minIntervalMinutes: 1440,
		});
	});
});
