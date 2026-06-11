export interface AccountScheduleRow {
	active_hours_start?: number | null;
	active_hours_end?: number | null;
	timezone?: string | null;
	min_interval_minutes?: number | null;
	paused?: boolean | null;
	status?: string | null;
	blocked_until?: string | null;
}

export interface LegacyAccountOverride {
	active_hours_start?: number | null;
	active_hours_end?: number | null;
	timezone?: string | null;
	min_interval_minutes?: number | null;
}

export interface GroupScheduleConfig {
	active_hours_start?: number | null;
	active_hours_end?: number | null;
	timezone?: string | null;
	min_interval_minutes?: number | null;
}

export interface PublishSchedulePolicy {
	activeHoursStart: number;
	activeHoursEnd: number;
	timezone: string;
	minIntervalMinutes: number;
	paused: boolean;
	status: string | null;
	blockedUntil: string | null;
	source: "account_schedule" | "legacy_override" | "group_config" | "default";
}

export interface PlannedAccountConstraints {
	accountId?: string | null;
	candidateAccountIds?: string[] | null;
	accountWindow?: { start?: number | null; end?: number | null } | null;
	minIntervalMinutes?: number | null;
	timezone?: string | null;
}

function numberOrDefault(value: unknown, fallback: number): number {
	const numeric = Number(value);
	return Number.isFinite(numeric) ? numeric : fallback;
}

export function isHourInWindow(hour: number, start: number, end: number): boolean {
	if (start === end) return true;
	return start < end ? hour >= start && hour < end : hour >= start || hour < end;
}

export function localHourForDate(date: Date, timezone: string): number {
	try {
		const hour = Number(
			date.toLocaleString("en-US", {
				hour: "numeric",
				hour12: false,
				timeZone: timezone,
			}),
		);
		return Number.isFinite(hour) ? hour : date.getUTCHours();
	} catch {
		return date.getUTCHours();
	}
}

export function resolvePublishSchedulePolicy(input: {
	accountSchedule?: AccountScheduleRow | null;
	legacyOverride?: LegacyAccountOverride | null;
	groupConfig?: GroupScheduleConfig | null;
}): PublishSchedulePolicy {
	if (input.accountSchedule) {
		return {
			activeHoursStart: numberOrDefault(input.accountSchedule.active_hours_start, 8),
			activeHoursEnd: numberOrDefault(input.accountSchedule.active_hours_end, 23),
			timezone: input.accountSchedule.timezone || input.groupConfig?.timezone || "UTC",
			minIntervalMinutes: numberOrDefault(
				input.accountSchedule.min_interval_minutes,
				60,
			),
			paused: input.accountSchedule.paused === true,
			status: input.accountSchedule.status ?? null,
			blockedUntil: input.accountSchedule.blocked_until ?? null,
			source: "account_schedule",
		};
	}
	if (input.legacyOverride) {
		return {
			activeHoursStart: numberOrDefault(input.legacyOverride.active_hours_start, 8),
			activeHoursEnd: numberOrDefault(input.legacyOverride.active_hours_end, 23),
			timezone: input.legacyOverride.timezone || input.groupConfig?.timezone || "UTC",
			minIntervalMinutes: numberOrDefault(
				input.legacyOverride.min_interval_minutes,
				60,
			),
			paused: false,
			status: null,
			blockedUntil: null,
			source: "legacy_override",
		};
	}
	if (input.groupConfig) {
		return {
			activeHoursStart: numberOrDefault(input.groupConfig.active_hours_start, 8),
			activeHoursEnd: numberOrDefault(input.groupConfig.active_hours_end, 23),
			timezone: input.groupConfig.timezone || "UTC",
			minIntervalMinutes: numberOrDefault(input.groupConfig.min_interval_minutes, 60),
			paused: false,
			status: null,
			blockedUntil: null,
			source: "group_config",
		};
	}
	return {
		activeHoursStart: 8,
		activeHoursEnd: 23,
		timezone: "UTC",
		minIntervalMinutes: 60,
		paused: false,
		status: null,
		blockedUntil: null,
		source: "default",
	};
}

export function isActiveWindowNow(
	policy: PublishSchedulePolicy,
	now: Date,
): boolean {
	return isHourInWindow(
		localHourForDate(now, policy.timezone),
		policy.activeHoursStart,
		policy.activeHoursEnd,
	);
}

export function isPolicyTemporarilyBlocked(
	policy: PublishSchedulePolicy,
	now: Date,
): boolean {
	if (policy.paused) return true;
	if (policy.blockedUntil) {
		const blockedUntil = new Date(policy.blockedUntil);
		if (!Number.isNaN(blockedUntil.getTime()) && blockedUntil > now) return true;
	}
	return false;
}

export function satisfiesPlannedAccountConstraints(input: {
	selectedAccountId: string;
	plannedAccount?: PlannedAccountConstraints | null;
	selectedPolicy: PublishSchedulePolicy;
	now: Date;
}): boolean {
	const planned = input.plannedAccount;
	if (!planned) return true;
	if (
		planned.candidateAccountIds?.length &&
		!planned.candidateAccountIds.includes(input.selectedAccountId)
	) {
		return false;
	}
	if (planned.accountId && planned.accountId === input.selectedAccountId) return true;
	const window = planned.accountWindow;
	if (window?.start != null || window?.end != null) {
		const start = numberOrDefault(window.start, input.selectedPolicy.activeHoursStart);
		const end = numberOrDefault(window.end, input.selectedPolicy.activeHoursEnd);
		const hour = localHourForDate(input.now, planned.timezone || input.selectedPolicy.timezone);
		if (!isHourInWindow(hour, start, end)) return false;
	}
	if (
		planned.minIntervalMinutes != null &&
		input.selectedPolicy.minIntervalMinutes < planned.minIntervalMinutes
	) {
		return false;
	}
	return true;
}
