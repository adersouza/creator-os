import { describe, expect, it, vi } from "vitest";
import {
	deriveAutoposterRuntimeMode,
	drainAutoposterQueue,
	getAutoposterControlStatus,
	pauseAutoposter,
	resumeAutoposterWarmup,
} from "../../api/_lib/handlers/auto-post/controlPlane";

vi.mock("../../api/_lib/privilegedDb", () => ({
	PRIVILEGED_DB_REASONS: {
		operatorControlPlane: "operator_control_plane",
	},
	getPrivilegedSupabaseAny: vi.fn(),
}));

vi.mock("../../api/_lib/handlers/auto-post/killSwitch", () => ({
	isAutoposterHardDisabled: () => false,
}));

type Row = Record<string, any>;

class QueryMock {
	private selectedCount = false;
	private head = false;
	private filters: Array<(row: Row) => boolean> = [];
	private pendingUpdate: Row | null = null;
	private pendingInsert: Row | null = null;
	private limitCount: number | null = null;

	constructor(
		private readonly db: DbMock,
		private readonly table: string,
	) {}

	select(_columns?: string, options?: { count?: string; head?: boolean }) {
		this.selectedCount = options?.count === "exact";
		this.head = options?.head === true;
		return this;
	}

	eq(field: string, value: unknown) {
		this.filters.push((row) => row[field] === value);
		return this;
	}

	in(field: string, values: unknown[]) {
		this.filters.push((row) => values.includes(row[field]));
		return this;
	}

	lte(field: string, value: string) {
		this.filters.push((row) => String(row[field] ?? "") <= value);
		return this;
	}

	gte(field: string, value: string) {
		this.filters.push((row) => String(row[field] ?? "") >= value);
		return this;
	}

	is(field: string, value: unknown) {
		this.filters.push((row) => row[field] === value);
		return this;
	}

	limit(count: number) {
		this.limitCount = count;
		return this;
	}

	update(values: Row) {
		this.pendingUpdate = values;
		return this;
	}

	insert(values: Row) {
		this.pendingInsert = values;
		this.db.inserts.push({ table: this.table, values });
		return this;
	}

	maybeSingle() {
		const data = this.matchRows()[0] ?? null;
		return Promise.resolve({ data, error: null });
	}

	then(resolve: (value: unknown) => unknown) {
		if (this.pendingUpdate) {
			const matched = this.matchRows();
			for (const row of matched) Object.assign(row, this.pendingUpdate);
			this.db.updates.push({
				table: this.table,
				values: this.pendingUpdate,
				count: matched.length,
			});
			return Promise.resolve({ data: matched, error: null }).then(resolve);
		}
		if (this.pendingInsert) {
			this.db.rows[this.table] ??= [];
			this.db.rows[this.table].push(this.pendingInsert);
			return Promise.resolve({ data: this.pendingInsert, error: null }).then(
				resolve,
			);
		}
		const rows = this.matchRows();
		if (this.selectedCount || this.head) {
			return Promise.resolve({ data: this.head ? null : rows, count: rows.length, error: null }).then(resolve);
		}
		return Promise.resolve({ data: rows, error: null }).then(resolve);
	}

	private matchRows() {
		let rows = [...(this.db.rows[this.table] ?? [])];
		for (const filter of this.filters) rows = rows.filter(filter);
		if (this.limitCount !== null) rows = rows.slice(0, this.limitCount);
		return rows;
	}
}

class DbMock {
	rows: Record<string, Row[]>;
	updates: Array<{ table: string; values: Row; count: number }> = [];
	inserts: Array<{ table: string; values: Row }> = [];

	constructor(rows: Record<string, Row[]>) {
		this.rows = rows;
	}

	from(table: string) {
		return new QueryMock(this, table);
	}
}

function dbFixture() {
	return new DbMock({
		auto_post_config: [
			{
				workspace_id: "ws1",
				is_enabled: true,
				group_mode_enabled: true,
				enable_ai_queue_fill: true,
			},
		],
		auto_post_queue: [
			{
				id: "q1",
				workspace_id: "ws1",
				platform: "threads",
				status: "queued",
				source_type: "ai",
				scheduled_for: "2026-06-15T10:00:00.000Z",
			},
			{
				id: "q2",
				workspace_id: "ws1",
				platform: "threads",
				status: "pending",
				source_type: "manual",
				scheduled_for: "2026-06-15T10:00:00.000Z",
			},
			{
				id: "q3",
				workspace_id: "ws1",
				platform: "threads",
				status: "publishing",
				source_type: "ai",
				scheduled_for: "2026-06-15T10:00:00.000Z",
			},
		],
		accounts: [
			{
				id: "a1",
				workspace_id: "ws1",
				is_active: true,
				needs_reauth: false,
				status: "active",
			},
			{
				id: "a2",
				workspace_id: "ws1",
				is_active: true,
				needs_reauth: true,
				status: "active",
			},
		],
		account_autoposter_state: [
			{
				workspace_id: "ws1",
				account_id: "a1",
				restart_warmup_status: "warming",
				status: "active",
			},
			{
				workspace_id: "ws1",
				account_id: "a2",
				restart_warmup_status: "held",
				status: "active",
			},
		],
		watchdog_alerts: [
			{
				workspace_id: "ws1",
				severity: "warn",
				resolved_at: null,
			},
		],
		publish_attempts: [],
		autoposter_control_events: [],
	});
}

describe("autoposter control plane", () => {
	it("derives runtime modes from switches", () => {
		expect(
			deriveAutoposterRuntimeMode({
				is_enabled: true,
				group_mode_enabled: true,
				enable_ai_queue_fill: true,
				hard_disabled: false,
			}),
		).toBe("running");
		expect(
			deriveAutoposterRuntimeMode({
				is_enabled: false,
				group_mode_enabled: true,
				enable_ai_queue_fill: true,
				hard_disabled: false,
			}),
		).toBe("paused");
		expect(
			deriveAutoposterRuntimeMode({
				is_enabled: true,
				group_mode_enabled: true,
				enable_ai_queue_fill: false,
				hard_disabled: false,
			}),
		).toBe("fill_disabled");
	});

	it("reports status without writing", async () => {
		const db = dbFixture();
		const status = await getAutoposterControlStatus("ws1", {
			db: db as any,
			now: new Date("2026-06-15T11:00:00.000Z"),
		});

		expect(status.mode).toBe("running");
		expect(status.queue.ready).toBe(2);
		expect(status.queue.due).toBe(2);
		expect(status.queue.publishing).toBe(1);
		expect(status.accounts.publishable).toBe(1);
		expect(status.accounts.needsReauth).toBe(1);
		expect(status.warmup).toEqual({ warming: 1, held: 1 });
		expect(db.updates).toEqual([]);
		expect(db.inserts).toEqual([]);
	});

	it("pause is a dry run unless apply is true", async () => {
		const db = dbFixture();
		const dryRun = await pauseAutoposter("ws1", {
			db: db as any,
			reason: "operator requested stop",
		});

		expect(dryRun.apply).toBe(false);
		expect(db.updates).toEqual([]);
		expect(db.inserts).toEqual([]);

		await pauseAutoposter("ws1", {
			db: db as any,
			reason: "operator requested stop",
			apply: true,
			actor: "test",
		});

		expect(db.rows.auto_post_config[0]).toEqual(
			expect.objectContaining({
				is_enabled: false,
				group_mode_enabled: false,
				enable_ai_queue_fill: false,
			}),
		);
		expect(db.inserts).toContainEqual(
			expect.objectContaining({
				table: "autoposter_control_events",
			}),
		);
	});

	it("resume-warmup restores the safe runtime switches", async () => {
		const db = dbFixture();
		Object.assign(db.rows.auto_post_config[0], {
			is_enabled: false,
			group_mode_enabled: false,
			enable_ai_queue_fill: false,
		});

		await resumeAutoposterWarmup("ws1", {
			db: db as any,
			reason: "resume monitored warm-up",
			apply: true,
		});

		expect(db.rows.auto_post_config[0]).toEqual(
			expect.objectContaining({
				is_enabled: true,
				group_mode_enabled: true,
				enable_ai_queue_fill: true,
			}),
		);
	});

	it("drain cancels ready non-manual rows only when applied", async () => {
		const db = dbFixture();

		const dryRun = await drainAutoposterQueue("ws1", {
			db: db as any,
			reason: "clear generated queue",
			mode: "cancel-ready",
		});
		expect(dryRun.cancelledReadyRows).toBe(1);
		expect(db.rows.auto_post_queue.find((row) => row.id === "q1")?.status).toBe(
			"queued",
		);

		await drainAutoposterQueue("ws1", {
			db: db as any,
			reason: "clear generated queue",
			mode: "cancel-ready",
			apply: true,
		});

		expect(db.rows.auto_post_queue.find((row) => row.id === "q1")?.status).toBe(
			"cancelled",
		);
		expect(db.rows.auto_post_queue.find((row) => row.id === "q2")?.status).toBe(
			"pending",
		);
	});
});
