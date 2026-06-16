import { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } from "../../privilegedDb.js";
import { logger } from "../../logger.js";
import { isAutoposterHardDisabled } from "./killSwitch.js";

type DbClient = ReturnType<typeof getPrivilegedSupabaseAny>;

export type AutoposterRuntimeMode =
	| "running"
	| "paused"
	| "fill_disabled"
	| "group_mode_disabled"
	| "hard_disabled"
	| "draining";

export interface AutoposterSwitchState {
	is_enabled: boolean;
	group_mode_enabled: boolean;
	enable_ai_queue_fill: boolean;
	hard_disabled: boolean;
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

export interface AutoposterControlPreview {
	action: "pause" | "resume_warmup" | "drain";
	workspaceId: string;
	apply: boolean;
	reason: string;
	before: AutoposterControlStatus;
	after: Partial<AutoposterSwitchState> | { cancelledReadyRows: number };
	cancelledReadyRows?: number;
}

export interface AutoposterControlOptions {
	db?: DbClient;
	now?: Date;
	hardDisabled?: boolean;
}

interface WorkspaceConfigRow {
	is_enabled?: boolean | null;
	group_mode_enabled?: boolean | null;
	enable_ai_queue_fill?: boolean | null;
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
	return deriveAutoposterRuntimeMode(normalizeSwitches(config, hardDisabled));
}

function normalizeSwitches(
	config: WorkspaceConfigRow | null | undefined,
	hardDisabled: boolean,
): AutoposterSwitchState {
	return {
		is_enabled: Boolean(config?.is_enabled),
		group_mode_enabled: Boolean(config?.group_mode_enabled),
		enable_ai_queue_fill: Boolean(config?.enable_ai_queue_fill),
		hard_disabled: hardDisabled,
	};
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

export async function getAutoposterControlStatus(
	workspaceId: string,
	options: AutoposterControlOptions = {},
): Promise<AutoposterControlStatus> {
	const db = dbFromOptions(options);
	const now = options.now ?? new Date();
	const hardDisabled = options.hardDisabled ?? isAutoposterHardDisabled();

	const { data: config } = await db
		.from("auto_post_config")
		.select("is_enabled, group_mode_enabled, enable_ai_queue_fill")
		.eq("workspace_id", workspaceId)
		.maybeSingle();

	const switches = normalizeSwitches(config as WorkspaceConfigRow | null, hardDisabled);
	const mode = deriveAutoposterRuntimeMode(switches);

	const [
		ready,
		due,
		publishing,
		deadLetter,
		statesResult,
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
	const accountIds = [
		...new Set(
			stateRows
				.map((row) => String(row.account_id ?? ""))
				.filter((accountId) => accountId.length > 0),
		),
	];
	const { data: accountRows } =
		accountIds.length > 0
			? await db
					.from("accounts")
					.select("id, is_active, needs_reauth, status")
					.in("id", accountIds)
			: { data: [] };
	const accounts = (accountRows ?? []) as Array<{
		is_active?: boolean | null;
		needs_reauth?: boolean | null;
		status?: string | null;
	}>;
	let publishable = 0;
	let needsReauth = 0;
	let inactiveOrOther = 0;
	for (const account of accounts) {
		if (account.needs_reauth) {
			needsReauth += 1;
		} else if (account.is_active && (account.status ?? "active") === "active") {
			publishable += 1;
		} else {
			inactiveOrOther += 1;
		}
	}

	const warmup = countBy(
		stateRows,
		"restart_warmup_status",
	);
	const alerts = (alertsResult.data ?? []) as Array<{ severity?: string | null }>;
	const criticalOrError = alerts.filter((alert) =>
		["critical", "error"].includes(String(alert.severity ?? "")),
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
			total: accounts.length,
			publishable,
			needsReauth,
			blocked: Math.max(0, accounts.length - publishable - inactiveOrOther),
			inactiveOrOther,
		},
		warmup,
		alerts: {
			unresolved: alerts.length,
			criticalOrError,
		},
		recentPublishFailures,
		configFound: Boolean(config),
	};
}

async function writeControlEvent(input: {
	db: DbClient;
	workspaceId: string;
	action: string;
	oldState: unknown;
	newState: unknown;
	reason: string;
	actor?: string | null | undefined;
}): Promise<void> {
	const { error } = await input.db.from("autoposter_control_events").insert({
		workspace_id: input.workspaceId,
		action: input.action,
		old_state: input.oldState,
		new_state: input.newState,
		reason: input.reason,
		actor: input.actor ?? "codex",
		dry_run: false,
	} as Record<string, unknown>);
	if (error) {
		logger.warn("autoposter control audit write failed", {
			workspaceId: input.workspaceId,
			action: input.action,
			error: String(error.message ?? error),
		});
	}
}

function assertWriteSucceeded(
	error: { message?: string } | null | undefined,
	action: string,
): void {
	if (error) {
		throw new Error(`Autoposter control ${action} failed: ${error.message ?? error}`);
	}
}

export async function pauseAutoposter(
	workspaceId: string,
	input: {
		reason: string;
		apply?: boolean | undefined;
		actor?: string | null | undefined;
	} & AutoposterControlOptions,
): Promise<AutoposterControlPreview> {
	const db = dbFromOptions(input);
	const before = await getAutoposterControlStatus(workspaceId, { ...input, db });
	const after = {
		is_enabled: false,
		group_mode_enabled: false,
		enable_ai_queue_fill: false,
	};

	if (input.apply) {
		const { error } = await db
			.from("auto_post_config")
			.update({ ...after, updated_at: new Date().toISOString() })
			.eq("workspace_id", workspaceId);
		assertWriteSucceeded(error, "pause");
		await writeControlEvent({
			db,
			workspaceId,
			action: "pause",
			oldState: before,
			newState: after,
			reason: input.reason,
			actor: input.actor,
		});
	}

	return {
		action: "pause",
		workspaceId,
		apply: Boolean(input.apply),
		reason: input.reason,
		before,
		after,
	};
}

export async function resumeAutoposterWarmup(
	workspaceId: string,
	input: {
		reason: string;
		apply?: boolean | undefined;
		actor?: string | null | undefined;
	} & AutoposterControlOptions,
): Promise<AutoposterControlPreview> {
	const db = dbFromOptions(input);
	const before = await getAutoposterControlStatus(workspaceId, { ...input, db });
	const after = {
		is_enabled: true,
		group_mode_enabled: true,
		enable_ai_queue_fill: true,
	};

	if (input.apply) {
		const { error } = await db
			.from("auto_post_config")
			.update({ ...after, updated_at: new Date().toISOString() })
			.eq("workspace_id", workspaceId);
		assertWriteSucceeded(error, "resume_warmup");
		await writeControlEvent({
			db,
			workspaceId,
			action: "resume_warmup",
			oldState: before,
			newState: after,
			reason: input.reason,
			actor: input.actor,
		});
	}

	return {
		action: "resume_warmup",
		workspaceId,
		apply: Boolean(input.apply),
		reason: input.reason,
		before,
		after,
	};
}

export async function drainAutoposterQueue(
	workspaceId: string,
	input: {
		reason: string;
		mode: "cancel-ready";
		apply?: boolean | undefined;
		includeManual?: boolean | undefined;
		actor?: string | null | undefined;
	} & AutoposterControlOptions,
): Promise<AutoposterControlPreview> {
	const db = dbFromOptions(input);
	const before = await getAutoposterControlStatus(workspaceId, { ...input, db });
	const { data: rows } = await db
		.from("auto_post_queue")
		.select("id, source_type")
		.eq("workspace_id", workspaceId)
		.eq("platform", "threads")
		.in("status", CLAIMABLE_STATUSES)
		.limit(2000);
	const ids = ((rows ?? []) as Array<{ id: string; source_type?: string | null }>)
		.filter((row) => input.includeManual || row.source_type !== "manual")
		.map((row) => row.id);

	if (input.apply && ids.length > 0) {
		const { error } = await db
			.from("auto_post_queue")
			.update({
				status: "cancelled",
				last_error: input.reason,
				schedule_nonce: null,
				qstash_message_id: null,
				claim_token: null,
				claim_expires_at: null,
			} as Record<string, unknown>)
			.in("id", ids);
		assertWriteSucceeded(error, "drain");
		await writeControlEvent({
			db,
			workspaceId,
			action: "drain_cancel_ready",
			oldState: before,
			newState: { cancelledReadyRows: ids.length },
			reason: input.reason,
			actor: input.actor,
		});
	}

	return {
		action: "drain",
		workspaceId,
		apply: Boolean(input.apply),
		reason: input.reason,
		before,
		after: { cancelledReadyRows: ids.length },
		cancelledReadyRows: ids.length,
	};
}
