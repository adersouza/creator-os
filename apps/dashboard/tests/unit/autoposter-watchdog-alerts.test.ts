import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockFrom = vi.fn();

vi.mock("../../api/_lib/privilegedDb", () => ({
	PRIVILEGED_DB_REASONS: {
		autoposterWatchdog: "autoposter_watchdog",
	},
	getPrivilegedSupabaseAny: () => ({
		from: mockFrom,
	}),
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: {
		error: vi.fn(),
		warn: vi.fn(),
		info: vi.fn(),
		debug: vi.fn(),
	},
}));

vi.mock("../../api/_lib/alerting", () => ({
	AlertLevel: { WARN: "WARN", ERROR: "ERROR", CRITICAL: "CRITICAL" },
	alert: vi.fn(),
}));

vi.mock("../../api/_lib/cronUtils", () => ({
	trackCronRun: vi.fn(),
	withCronLock: vi.fn(),
}));

vi.mock("../../api/_lib/handlers/auto-post/killSwitch", () => ({
	isAutoposterHardDisabled: vi.fn().mockReturnValue(false),
}));

vi.mock("../../api/_lib/retryUtils", () => ({
	isDefinitiveOAuthError: vi.fn().mockReturnValue(false),
}));

vi.mock("../../api/_lib/tokenRefresh", () => ({
	refreshThreadsToken: vi.fn(),
}));

function makeSelectOpenAlertsChain(rows: Array<Record<string, unknown>>) {
	return {
		select: vi.fn().mockReturnValue({
			is: vi.fn().mockReturnValue({
				range: vi
					.fn()
					.mockImplementation((from: number, to: number) =>
						Promise.resolve({ data: rows.slice(from, to + 1) }),
					),
			}),
		}),
	};
}

describe("autoposter watchdog alert persistence", () => {
	beforeEach(() => {
		vi.resetModules();
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.clearAllMocks();
	});

	it("resolves stale alerts using current evidence, not only deduped notification alerts", async () => {
		const inserted: unknown[] = [];
		const resolvedIds: unknown[] = [];
		const refreshed: Array<{ id: unknown; row: unknown }> = [];
		const openAlerts = [
			{ id: "active-deduped", workspace_id: "ws1", check_name: "low-queue" },
			{ id: "stale", workspace_id: "ws1", check_name: "empty-queue" },
		];

		mockFrom.mockImplementation((table: string) => {
			if (table !== "watchdog_alerts") throw new Error(`unexpected table ${table}`);
			return {
				insert: vi.fn().mockImplementation((row: unknown) => {
					inserted.push(row);
					return Promise.resolve({ error: null });
				}),
				select: makeSelectOpenAlertsChain(openAlerts).select,
				update: vi.fn().mockImplementation((row: unknown) => ({
					in: vi.fn().mockImplementation((_column: string, ids: unknown[]) => {
						resolvedIds.push(...ids);
						return Promise.resolve({ error: null });
					}),
					eq: vi.fn().mockImplementation((_column: string, id: unknown) => {
						refreshed.push({ id, row });
						return Promise.resolve({ error: null });
					}),
				})),
			};
		});

		const { persistAlerts } = await import("../../api/cron/autoposter-watchdog");
		await persistAlerts(
			[],
			[
				{
					workspace_id: "ws1",
					check_name: "low-queue",
					severity: "WARN",
					message: "still active",
					details: {},
				},
			],
		);

		expect(inserted).toEqual([]);
		expect(resolvedIds).toEqual(["stale"]);
		expect(refreshed).toHaveLength(1);
		expect(refreshed[0]).toMatchObject({
			id: "active-deduped",
			row: {
				severity: "WARN",
				message: "still active",
			},
		});
	});

	it("persists alerts with owner, TTL, evidence timestamp, and resolution condition", async () => {
		const inserted: Array<{ details?: Record<string, unknown> }> = [];

		mockFrom.mockImplementation((table: string) => {
			if (table !== "watchdog_alerts") throw new Error(`unexpected table ${table}`);
			return {
				insert: vi.fn().mockImplementation((row: unknown) => {
					inserted.push(row);
					return Promise.resolve({ error: null });
				}),
				select: makeSelectOpenAlertsChain([]).select,
				update: vi.fn().mockImplementation(() => ({
					in: vi.fn().mockResolvedValue({ error: null }),
				})),
			};
		});

		const { persistAlerts } = await import("../../api/cron/autoposter-watchdog");
		await persistAlerts([
			{
				workspace_id: "ws1",
				check_name: "low-queue",
				severity: "WARN",
				message: "low queue",
				details: { pendingQueue: 1 },
			},
		]);

		expect(inserted).toHaveLength(1);
		expect(inserted[0].details).toMatchObject({
			pendingQueue: 1,
			owner: "threads_autoposter_ops",
			severity: "WARN",
			ttlMs: 3 * 60 * 60 * 1000,
			resolutionCondition:
				"ready depth meets demand-aware threshold or no uncovered capacity",
		});
		expect(inserted[0].details.evidenceGeneratedAt).toEqual(
			expect.any(String),
		);
	});

	it("resolves older duplicate open alerts for the same current check", async () => {
		const inserted: unknown[] = [];
		const resolvedIds: unknown[] = [];
		const refreshed: Array<{ id: unknown; row: unknown }> = [];
		const now = Date.now();
		const openAlerts = [
			{
				id: "old-low-queue",
				workspace_id: "ws1",
				check_name: "low-queue",
				created_at: new Date(now - 60 * 60 * 1000).toISOString(),
			},
			{
				id: "new-low-queue",
				workspace_id: "ws1",
				check_name: "low-queue",
				created_at: new Date(now - 5 * 60 * 1000).toISOString(),
			},
		];

		mockFrom.mockImplementation((table: string) => {
			if (table !== "watchdog_alerts") throw new Error(`unexpected table ${table}`);
			return {
				insert: vi.fn().mockImplementation((row: unknown) => {
					inserted.push(row);
					return Promise.resolve({ error: null });
				}),
				select: makeSelectOpenAlertsChain(openAlerts).select,
				update: vi.fn().mockImplementation((row: unknown) => ({
					in: vi.fn().mockImplementation((_column: string, ids: unknown[]) => {
						resolvedIds.push(...ids);
						return Promise.resolve({ error: null });
					}),
					eq: vi.fn().mockImplementation((_column: string, id: unknown) => {
						refreshed.push({ id, row });
						return Promise.resolve({ error: null });
					}),
				})),
			};
		});

		const { persistAlerts } = await import("../../api/cron/autoposter-watchdog");
		await persistAlerts(
			[],
			[
				{
					workspace_id: "ws1",
					check_name: "low-queue",
					severity: "WARN",
					message: "still active",
					details: {},
				},
			],
		);

		expect(inserted).toEqual([]);
		expect(resolvedIds).toEqual(["old-low-queue"]);
		expect(refreshed).toHaveLength(1);
		expect(refreshed[0]).toMatchObject({
			id: "new-low-queue",
			row: {
				severity: "WARN",
				message: "still active",
			},
		});
	});

	it("resolves stale open alerts in bounded batches", async () => {
		const resolvedBatches: unknown[][] = [];
		const openAlerts = Array.from({ length: 1205 }, (_, index) => ({
			id: `stale-${index}`,
			workspace_id: "ws1",
			check_name: "low-queue",
			created_at: new Date(1780900000000 + index).toISOString(),
		}));

		mockFrom.mockImplementation((table: string) => {
			if (table !== "watchdog_alerts") throw new Error(`unexpected table ${table}`);
			return {
				insert: vi.fn().mockResolvedValue({ error: null }),
				select: makeSelectOpenAlertsChain(openAlerts).select,
				update: vi.fn().mockImplementation(() => ({
					in: vi.fn().mockImplementation((_column: string, ids: unknown[]) => {
						resolvedBatches.push(ids);
						return Promise.resolve({ error: null });
					}),
				})),
			};
		});

		const { persistAlerts } = await import("../../api/cron/autoposter-watchdog");
		await persistAlerts([], []);

		expect(resolvedBatches).toHaveLength(13);
		expect(resolvedBatches.map((batch) => batch.length)).toEqual([
			100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 100, 5,
		]);
	});

	it("expires short-lived open alerts even when the same condition still fires", async () => {
		const inserted: unknown[] = [];
		const resolvedIds: unknown[] = [];
		const openAlerts = [
			{
				id: "old-current-low-queue",
				workspace_id: "ws1",
				check_name: "low-queue",
				created_at: "2026-06-08T00:00:00.000Z",
			},
		];

		mockFrom.mockImplementation((table: string) => {
			if (table !== "watchdog_alerts") throw new Error(`unexpected table ${table}`);
			return {
				insert: vi.fn().mockImplementation((row: unknown) => {
					inserted.push(row);
					return Promise.resolve({ error: null });
				}),
				select: makeSelectOpenAlertsChain(openAlerts).select,
				update: vi.fn().mockImplementation(() => ({
					in: vi.fn().mockImplementation((_column: string, ids: unknown[]) => {
						resolvedIds.push(...ids);
						return Promise.resolve({ error: null });
					}),
				})),
			};
		});

		vi.useFakeTimers();
		vi.setSystemTime(new Date("2026-06-08T04:00:01.000Z"));
		const { persistAlerts } = await import("../../api/cron/autoposter-watchdog");
		await persistAlerts(
			[],
			[
				{
					workspace_id: "ws1",
					check_name: "low-queue",
					severity: "WARN",
					message: "still active",
					details: {},
				},
			],
		);
		vi.useRealTimers();

		expect(inserted).toEqual([]);
		expect(resolvedIds).toEqual(["old-current-low-queue"]);
	});
});

describe("autoposter watchdog queue-fill evidence", () => {
	afterEach(() => {
		vi.clearAllMocks();
	});

	it("uses successful queue_fill_log rows to suppress stale filter-rejection alerts", async () => {
		const queriedTables: string[] = [];
		mockFrom.mockImplementation((table: string) => {
			queriedTables.push(table);

			if (table === "auto_post_queue") {
				let statusCount = 0;
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockImplementation(() => ({
							eq: vi.fn().mockImplementation(() => ({
								gte: vi.fn().mockResolvedValue({ count: 0 }),
							})),
							in: vi.fn().mockImplementation(() => {
								statusCount += 1;
								return Promise.resolve({ count: statusCount ? 5 : 0 });
							}),
						})),
					}),
				};
			}

			if (table === "cron_runs") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							gte: vi.fn().mockReturnValue({
								order: vi.fn().mockReturnValue({
									limit: vi.fn().mockResolvedValue({
										data: [{ metadata: { fillsTriggered: 4 } }],
									}),
								}),
							}),
						}),
					}),
				};
			}

			if (table === "queue_fill_log") {
				return {
					select: vi.fn().mockReturnValue({
						gte: vi.fn().mockResolvedValue({
							data: [
								{
									posts_inserted: 4,
									posts_generated: 60,
									early_exit_reason: null,
								},
							],
						}),
					}),
				};
			}

			throw new Error(`unexpected table ${table}`);
		});

		const { checkFilterRejectionRate } = await import(
			"../../api/cron/autoposter-watchdog"
		);
		const alerts: Array<{ check_name: string }> = [];

		await checkFilterRejectionRate(
			[
				{
					workspace_id: "ws1",
					enable_ai_queue_fill: true,
					ai_generations_today: 100,
					ai_queue_min_threshold: 20,
				} as never,
			],
			alerts as never,
		);

		expect(queriedTables).toContain("queue_fill_log");
		expect(queriedTables).not.toContain("autopilot_runs");
		expect(alerts.map((alert) => alert.check_name)).not.toContain(
			"queue-fill-not-executing",
		);
		expect(alerts.map((alert) => alert.check_name)).not.toContain(
			"high-filter-rejection",
		);
	});

	it("does not treat scheduler cooldown/no-op rows as dispatched queue-fill jobs", async () => {
		mockFrom.mockImplementation((table: string) => {
			if (table === "auto_post_queue") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockImplementation(() => ({
							eq: vi.fn().mockImplementation(() => ({
								gte: vi.fn().mockResolvedValue({ count: 0 }),
							})),
							in: vi.fn().mockResolvedValue({ count: 5 }),
						})),
					}),
				};
			}

			if (table === "cron_runs") {
				return {
					select: vi.fn().mockReturnValue({
						eq: vi.fn().mockReturnValue({
							gte: vi.fn().mockReturnValue({
								order: vi.fn().mockReturnValue({
									limit: vi.fn().mockResolvedValue({
										data: [
											{
												metadata: {
													fillsTriggered: 4,
													dispatched: 0,
												},
											},
										],
									}),
								}),
							}),
						}),
					}),
				};
			}

			if (table === "queue_fill_log") {
				return {
					select: vi.fn().mockReturnValue({
						gte: vi.fn().mockResolvedValue({ data: [] }),
					}),
				};
			}

			throw new Error(`unexpected table ${table}`);
		});

		const { checkFilterRejectionRate } = await import(
			"../../api/cron/autoposter-watchdog"
		);
		const alerts: Array<{ check_name: string }> = [];

		await checkFilterRejectionRate(
			[
				{
					workspace_id: "ws1",
					enable_ai_queue_fill: true,
					ai_generations_today: 100,
					ai_queue_min_threshold: 20,
				} as never,
			],
			alerts as never,
		);

		expect(alerts.map((alert) => alert.check_name)).not.toContain(
			"queue-fill-not-executing",
		);
		expect(alerts.map((alert) => alert.check_name)).toContain(
			"high-filter-rejection",
		);
	});
});
