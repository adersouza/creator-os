import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import type { AccountAutoposterStatus } from "./accountState.js";
import { classifyAutoposterHealthScore } from "./accountHealth.js";
import type { RestartWarmupStatus } from "./restartWarmup.js";

// biome-ignore lint/suspicious/noExplicitAny: auto_post tables not in generated types
const db = (): any => getSupabaseAny();

export type DerivedAccountScheduleStatus = "active" | "inactive" | "suppressed";

export interface AccountScheduleSyncState {
	account_id: string;
	group_id: string;
	workspace_id: string;
	status: AccountAutoposterStatus;
	account_health_score?: number | null | undefined;
	restart_warmup_status?: RestartWarmupStatus | null | undefined;
	recommended_strategy_mode?: string | null | undefined;
	status_reason?: string | null | undefined;
}

export interface AccountScheduleSyncAccount {
	id: string;
	username?: string | null | undefined;
	is_active?: boolean | null | undefined;
	is_retired?: boolean | null | undefined;
	needs_reauth?: boolean | null | undefined;
	is_shadowbanned?: boolean | null | undefined;
	status?: string | null | undefined;
}

export interface AccountScheduleSyncRow {
	account_id: string;
	group_id: string;
	status?: string | null | undefined;
	status_reason?: string | null | undefined;
	blocked_until?: string | null | undefined;
	paused?: boolean | null | undefined;
}

export interface AccountScheduleStatusDecision {
	desiredStatus: DerivedAccountScheduleStatus;
	reason: string;
	shouldBlockPlanner: boolean;
}

export interface AccountScheduleDriftRow {
	account_id: string;
	group_id: string;
	username: string | null;
	currentStatus: string | null;
	desiredStatus: DerivedAccountScheduleStatus;
	reason: string;
	manuallyPaused: boolean;
	scheduleBlocksPlanner: boolean;
	wouldRepair: boolean;
}

export interface AccountScheduleSyncReport {
	checked: number;
	mismatches: number;
	repaired: number;
	skippedPaused: number;
	remainingBlocked: number;
	dryRun: boolean;
	rows: AccountScheduleDriftRow[];
}

const BLOCKING_SCHEDULE_STATUSES = new Set([
	"suppressed",
	"inactive",
	"shadowban_throttle",
	"view_cooldown",
	"flop_delay",
	"viral_suppress",
	"warming_limited",
]);

function isAccountInactive(account?: AccountScheduleSyncAccount | null): boolean {
	return (
		!account ||
		account.is_retired === true ||
		account.needs_reauth === true ||
		account.is_active === false ||
		account.status === "suspended"
	);
}

export function deriveAccountScheduleStatus(input: {
	state: AccountScheduleSyncState;
	account?: AccountScheduleSyncAccount | null | undefined;
}): AccountScheduleStatusDecision {
	const { state, account } = input;
	if (isAccountInactive(account) || state.status === "inactive") {
		return {
			desiredStatus: "inactive",
			reason: isAccountInactive(account)
				? "account_inactive_reauth_or_retired"
				: "autoposter_state_inactive",
			shouldBlockPlanner: true,
		};
	}

	const healthTier = classifyAutoposterHealthScore(state.account_health_score);
	if (
		state.status === "suppressed" ||
		state.status === "shadowban_throttle" ||
		state.restart_warmup_status === "suppressed" ||
		state.recommended_strategy_mode === "suppress" ||
		healthTier === "suppressed"
	) {
		return {
			desiredStatus: "suppressed",
			reason:
				state.status === "suppressed"
					? "autoposter_state_suppressed"
					: state.status === "shadowban_throttle"
						? "autoposter_state_shadowban_throttle"
						: state.restart_warmup_status === "suppressed"
							? "restart_warmup_suppressed"
							: state.recommended_strategy_mode === "suppress"
								? "performance_strategy_suppress"
								: `account_health_${healthTier}`,
			shouldBlockPlanner: true,
		};
	}

	return {
		desiredStatus: "active",
		reason: "autoposter_state_allows_planning",
		shouldBlockPlanner: false,
	};
}

export function buildAccountScheduleDriftReport(input: {
	states: AccountScheduleSyncState[];
	accounts: AccountScheduleSyncAccount[];
	schedules: AccountScheduleSyncRow[];
	dryRun?: boolean | undefined;
}): AccountScheduleSyncReport {
	const accountById = new Map(input.accounts.map((account) => [account.id, account]));
	const scheduleByKey = new Map(
		input.schedules.map((schedule) => [
			`${schedule.group_id}:${schedule.account_id}`,
			schedule,
		]),
	);
	const rows: AccountScheduleDriftRow[] = [];
	let skippedPaused = 0;
	let remainingBlocked = 0;

	for (const state of input.states) {
		const schedule = scheduleByKey.get(`${state.group_id}:${state.account_id}`);
		if (!schedule) continue;
		const account = accountById.get(state.account_id);
		const decision = deriveAccountScheduleStatus({ state, account });
		const manuallyPaused = schedule.paused === true;
		const currentStatus = schedule.status ?? null;
		const scheduleBlocksPlanner =
			manuallyPaused ||
			!!(currentStatus && !["active", "enabled"].includes(currentStatus)) ||
			!!(
				schedule.blocked_until &&
				new Date(schedule.blocked_until).getTime() > Date.now()
			);
		const statusMismatch =
			currentStatus !== decision.desiredStatus &&
			!(currentStatus === "enabled" && decision.desiredStatus === "active");
		const staleActiveBlock =
			decision.desiredStatus === "active" &&
			(scheduleBlocksPlanner || BLOCKING_SCHEDULE_STATUSES.has(currentStatus || ""));
		const staleBlockedAllow =
			decision.desiredStatus !== "active" &&
			(!currentStatus || ["active", "enabled"].includes(currentStatus));
		const wouldRepair =
			!manuallyPaused && (statusMismatch || staleActiveBlock || staleBlockedAllow);
		if (manuallyPaused) skippedPaused++;
		if (scheduleBlocksPlanner && !wouldRepair) remainingBlocked++;
		if (wouldRepair || scheduleBlocksPlanner || statusMismatch) {
			rows.push({
				account_id: state.account_id,
				group_id: state.group_id,
				username: account?.username ?? null,
				currentStatus,
				desiredStatus: decision.desiredStatus,
				reason: decision.reason,
				manuallyPaused,
				scheduleBlocksPlanner,
				wouldRepair,
			});
		}
	}

	return {
		checked: input.states.length,
		mismatches: rows.filter((row) => row.wouldRepair).length,
		repaired: 0,
		skippedPaused,
		remainingBlocked,
		dryRun: input.dryRun !== false,
		rows,
	};
}

export async function syncAccountScheduleStatuses(input: {
	workspaceId: string;
	states: AccountScheduleSyncState[];
	dryRun?: boolean | undefined;
}): Promise<AccountScheduleSyncReport> {
	const states = input.states.filter((state) => state.workspace_id === input.workspaceId);
	if (states.length === 0) {
		return {
			checked: 0,
			mismatches: 0,
			repaired: 0,
			skippedPaused: 0,
			remainingBlocked: 0,
			dryRun: input.dryRun !== false,
			rows: [],
		};
	}

	const accountIds = [...new Set(states.map((state) => state.account_id))];
	const groupIds = [...new Set(states.map((state) => state.group_id))];
	const [{ data: accounts }, { data: schedules }] = await Promise.all([
		db()
			.from("accounts")
			.select("id, username, is_active, is_retired, needs_reauth, is_shadowbanned, status")
			.in("id", accountIds),
		db()
			.from("account_schedule")
			.select("account_id, group_id, status, status_reason, blocked_until, paused")
			.eq("workspace_id", input.workspaceId)
			.in("group_id", groupIds)
			.in("account_id", accountIds),
	]);

	const report = buildAccountScheduleDriftReport({
		states,
		accounts: (accounts ?? []) as AccountScheduleSyncAccount[],
		schedules: (schedules ?? []) as AccountScheduleSyncRow[],
		dryRun: input.dryRun,
	});

	if (input.dryRun !== false) return report;

	let repaired = 0;
	for (const row of report.rows.filter((candidate) => candidate.wouldRepair)) {
		const update: Record<string, unknown> = {
			status: row.desiredStatus,
			status_reason:
				row.desiredStatus === "active"
					? null
					: `synced_from_account_autoposter_state:${row.reason}`,
			updated_at: new Date().toISOString(),
		};
		if (row.desiredStatus === "active") {
			update.blocked_until = null;
		}
		const { error } = await db()
			.from("account_schedule")
			.update(update)
			.eq("workspace_id", input.workspaceId)
			.eq("group_id", row.group_id)
			.eq("account_id", row.account_id)
			.or("paused.is.null,paused.eq.false");
		if (error) {
			logger.warn("[accountScheduleStatusSync] Failed to repair schedule status", {
				workspaceId: input.workspaceId,
				groupId: row.group_id,
				accountId: row.account_id,
				error: error.message,
			});
			continue;
		}
		repaired++;
	}

	return {
		...report,
		repaired,
		dryRun: false,
	};
}
