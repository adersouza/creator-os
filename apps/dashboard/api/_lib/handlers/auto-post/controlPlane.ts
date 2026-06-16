import { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } from "../../privilegedDb.js";
import { isAutoposterHardDisabled } from "./killSwitch.js";

type DbClient = ReturnType<typeof getPrivilegedSupabaseAny>;

export type AutoposterRuntimeMode =
	| "running"
	| "paused"
	| "fill_disabled"
	| "group_mode_disabled"
	| "hard_disabled";

export interface AutoposterSwitchState {
	is_enabled: boolean;
	group_mode_enabled: boolean;
	enable_ai_queue_fill: boolean;
	hard_disabled: boolean;
}

interface WorkspaceConfigRow {
	workspace_id?: string | null;
	is_enabled?: boolean | null;
	group_mode_enabled?: boolean | null;
	enable_ai_queue_fill?: boolean | null;
}

export interface AutoposterControlStatus {
	workspaceId: string;
	mode: AutoposterRuntimeMode;
	switches: AutoposterSwitchState;
	queue: {
		ready: number;
		due: number;
		publishing: number;
		deadLetter: number;
		wouldPublishNonManual: boolean;
		wouldCancelNonManualAtPublish: boolean;
	};
	accounts: {
		total: number;
		publishable: number;
		needsReauth: number;
		blocked: number;
		inactiveOrOther: number;
	};
	warmup: Record<string, number>;
	alerts: {
		unresolved: number;
		criticalOrError: number;
	};
	recentPublishFailures: number;
	configFound: boolean;
}

export interface AutoposterControlOptions {
	db?: DbClient;
	now?: Date;
	hardDisabled?: boolean;
}

export interface AutoposterControlMutationOptions extends AutoposterControlOptions {
	reason: string;
	apply?: boolean;
	actor?: string;
}

export interface AutoposterDrainOptions extends AutoposterControlMutationOptions {
	mode: "cancel-ready";
	includeManual?: boolean;
}

const CLAIMABLE_STATUSES = ["pending", "queued"];

function dbFromOptions(options: AutoposterControlOptions = {}): DbClient {
	return (
		options.db ??
		getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.operatorControlPlane)
	);
}

export function deriveAutoposterRuntimeMode(
	switches: AutoposterSwitchState,
): AutoposterRuntimeMode {
	if (switches.hard_disabled) return "hard_disabled";
	if (!switches.is_enabled) return "paused";
	if (!switches.group_mode_enabled) return "group_mode_disabled";
	if (!switches.enable_ai_queue_fill) return "fill_disabled";
	return "running";
}

export function deriveAutoposterRuntimeModeFromConfig(
	config: WorkspaceConfigRow | null | undefined,
	hardDisabled: boolean,
): AutoposterRuntimeMode {
	return deriveAutoposterRuntimeMode({
		is_enabled: Boolean(config?.is_enabled),
		group_mode_enabled: Boolean(config?.group_mode_enabled),
		enable_ai_queue_fill: Boolean(config?.enable_ai_queue_fill),
		hard_disabled: hardDisabled,
	});
}

async function countQuery(query: PromiseLike<{ count: number | null }>): Promise<number> {
	try {
		const result = await query;
		return result.count ?? 0;
	} catch {
		return 0;
	}
}

function countBy<T extends Record<string, unknown>>(
	rows: T[] | null | undefined,
	field: keyof T,
): Record<string, number> {
	const result: Record<string, number> = {};
	for (const row of rows ?? []) {
		const key = String(row[field] ?? "unknown");
		result[key] = (result[key] ?? 0) + 1;
	}
	return result;
}

async function insertControlEvent(
	db: DbClient,
	workspaceId: string,
	action: string,
	options: AutoposterControlMutationOptions,
	oldState: unknown,
	newState: unknown,
): Promise<void> {
	await db.from("autoposter_control_events").insert({
		workspace_id: workspaceId,
		action,
		old_state: oldState,
		new_state: newState,
		reason: options.reason,
		actor: options.actor ?? "codex",
		dry_run: options.apply !== true,
		created_at: new Date().toISOString(),
	});
}

export async function getAutoposterControlStatus(
	workspaceId: string,
	options: AutoposterControlOptions = {},
): Promise<AutoposterControlStatus> {
	const db = dbFromOptions(options);
	const now = options.now ?? new Date();
	const hardDisabled = options.hardDisabled ?? isAutoposterHardDisabled();

	const { data: config } = await db
		.from("auto_post_config")
		.select("workspace_id, is_enabled, group_mode_enabled, enable_ai_queue_fill")
		.eq("workspace_id", workspaceId)
		.maybeSingle();

	const switches: AutoposterSwitchState = {
		is_enabled: Boolean((config as WorkspaceConfigRow | null)?.is_enabled),
		group_mode_enabled: Boolean((config as WorkspaceConfigRow | null)?.group_mode_enabled),
		enable_ai_queue_fill: Boolean((config as WorkspaceConfigRow | null)?.enable_ai_queue_fill),
		hard_disabled: hardDisabled,
	};
	const mode = deriveAutoposterRuntimeMode(switches);

	const [
		ready,
		due,
		publishing,
		deadLetter,
		statesResult,
		accountsResult,
		alertsResult,
		recentPublishFailures,
	] = await Promise.all([
		countQuery(
			db
				.from("auto_post_queue")
				.select("id", { count: "exact", head: true })
				.eq("workspace_id", workspaceId)
				.eq("platform", "threads")
				.in("status", CLAIMABLE_STATUSES),
		),
		countQuery(
			db
				.from("auto_post_queue")
				.select("id", { count: "exact", head: true })
				.eq("workspace_id", workspaceId)
				.eq("platform", "threads")
				.in("status", CLAIMABLE_STATUSES)
				.lte("scheduled_for", now.toISOString()),
		),
		countQuery(
			db
				.from("auto_post_queue")
				.select("id", { count: "exact", head: true })
				.eq("workspace_id", workspaceId)
				.eq("platform", "threads")
				.eq("status", "publishing"),
		),
		countQuery(
			db
				.from("auto_post_queue")
				.select("id", { count: "exact", head: true })
				.eq("workspace_id", workspaceId)
				.eq("platform", "threads")
				.eq("status", "dead_letter"),
		),
		db
			.from("account_autoposter_state")
			.select("account_id, restart_warmup_status, status")
			.eq("workspace_id", workspaceId),
		db
			.from("accounts")
			.select("id, is_active, needs_reauth, status")
			.eq("workspace_id", workspaceId),
		db
			.from("watchdog_alerts")
			.select("severity")
			.eq("workspace_id", workspaceId)
			.is("resolved_at", null),
		countQuery(
			db
				.from("publish_attempts")
				.select("id", { count: "exact", head: true })
				.eq("workspace_id", workspaceId)
				.gte("started_at", new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString())
				.in("result", [
					"claim_failed",
					"dead_letter",
					"failed",
					"error",
					"reconcile_failed",
				]),
		),
	]);

	const stateRows = (statesResult.data ?? []) as Array<Record<string, unknown>>;
	const accountRows = (accountsResult.data ?? []) as Array<Record<string, unknown>>;
	const alertRows = (alertsResult.data ?? []) as Array<Record<string, unknown>>;
	const publishableAccounts = accountRows.filter(
		(row) =>
			row.is_active === true &&
			row.needs_reauth !== true &&
			String(row.status ?? "active") === "active",
	).length;

	return {
		workspaceId,
		mode,
		switches,
		queue: {
			ready,
			due,
			publishing,
			deadLetter,
			wouldPublishNonManual: mode === "running" || mode === "fill_disabled",
			wouldCancelNonManualAtPublish: mode !== "running" && mode !== "fill_disabled",
		},
		accounts: {
			total: accountRows.length,
			publishable: publishableAccounts,
			needsReauth: accountRows.filter((row) => row.needs_reauth === true).length,
			blocked: accountRows.filter((row) => String(row.status ?? "") === "blocked").length,
			inactiveOrOther: accountRows.filter(
				(row) =>
					row.is_active !== true &&
					row.needs_reauth !== true &&
					String(row.status ?? "active") !== "blocked",
			).length,
		},
		warmup: countBy(stateRows, "restart_warmup_status"),
		alerts: {
			unresolved: alertRows.length,
			criticalOrError: alertRows.filter((row) =>
				["critical", "error"].includes(String(row.severity ?? "").toLowerCase()),
			).length,
		},
		recentPublishFailures,
		configFound: Boolean(config),
	};
}

export async function pauseAutoposter(
	workspaceId: string,
	options: AutoposterControlMutationOptions,
) {
	const db = dbFromOptions(options);
	const before = await getAutoposterControlStatus(workspaceId, options);
	const after = {
		is_enabled: false,
		group_mode_enabled: false,
		enable_ai_queue_fill: false,
	};
	if (options.apply === true) {
		await db.from("auto_post_config").update(after).eq("workspace_id", workspaceId);
		await insertControlEvent(db, workspaceId, "pause", options, before.switches, after);
	}
	return {
		action: "pause" as const,
		workspaceId,
		apply: options.apply === true,
		reason: options.reason,
		before,
		after,
	};
}

export async function resumeAutoposterWarmup(
	workspaceId: string,
	options: AutoposterControlMutationOptions,
) {
	const db = dbFromOptions(options);
	const before = await getAutoposterControlStatus(workspaceId, options);
	const after = {
		is_enabled: true,
		group_mode_enabled: true,
		enable_ai_queue_fill: true,
	};
	if (options.apply === true) {
		await db.from("auto_post_config").update(after).eq("workspace_id", workspaceId);
		await insertControlEvent(
			db,
			workspaceId,
			"resume_warmup",
			options,
			before.switches,
			after,
		);
	}
	return {
		action: "resume_warmup" as const,
		workspaceId,
		apply: options.apply === true,
		reason: options.reason,
		before,
		after,
	};
}

export async function drainAutoposterQueue(
	workspaceId: string,
	options: AutoposterDrainOptions,
) {
	const db = dbFromOptions(options);
	const before = await getAutoposterControlStatus(workspaceId, options);
	const filter = db
		.from("auto_post_queue")
		.select("id, source_type")
		.eq("workspace_id", workspaceId)
		.eq("platform", "threads")
		.in("status", CLAIMABLE_STATUSES);
	const rowsResult = await filter;
	const rows = ((rowsResult.data ?? []) as Array<Record<string, unknown>>).filter(
		(row) => options.includeManual === true || row.source_type !== "manual",
	);
	const cancelledReadyRows = rows.length;
	if (options.apply === true && cancelledReadyRows > 0) {
		for (const row of rows) {
			await db
				.from("auto_post_queue")
				.update({
					status: "cancelled",
					updated_at: new Date().toISOString(),
					metadata: {
						control_reason: options.reason,
						cancelled_by: options.actor ?? "codex",
					},
				})
				.eq("id", row.id)
				.eq("workspace_id", workspaceId);
		}
		await insertControlEvent(
			db,
			workspaceId,
			"drain",
			options,
			before.queue,
			{ cancelledReadyRows },
		);
	}
	return {
		action: "drain" as const,
		workspaceId,
		apply: options.apply === true,
		reason: options.reason,
		before,
		after: { cancelledReadyRows },
		cancelledReadyRows,
	};
}
