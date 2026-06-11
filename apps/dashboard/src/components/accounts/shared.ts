import type { AccountHealth, AccountPlatform } from "@/hooks/useFleetAccounts";
import type { HealthState } from "@/components/ui/HealthDot";

export type ViewMode = "list" | "map";
export type GroupFilter = "all" | string;
export type PlatformFilter = "all" | AccountPlatform;
export type StatusFilter =
	| "all"
	| "active"
	| "drifting"
	| "flagged"
	| "inactive";
export type SortKey = "followers" | "health" | "posts24h" | "recent";
export type AccountUiStatus = Exclude<StatusFilter, "all">;

export type AccountSignalType =
	| "engagement_spike"
	| "reach_anomaly"
	| "shadowban_risk"
	| "token_expiring"
	| "rate_limit"
	| "capability_error";

export type AccountSignalSeverity = "good" | "warn" | "critical";

export interface AccountHealthSignal {
	id: string;
	account_id: string;
	signal_type: AccountSignalType;
	severity: AccountSignalSeverity;
	metadata: Record<string, unknown> | null;
	detected_at: string;
	resolved_at: string | null;
}

export const UNASSIGNED_COLOR = "var(--color-health-idle)";
export const PAGE_SIZE = 10;

export function uiStatusFromHealth(h: AccountHealth): AccountUiStatus {
	if (h === "good") return "active";
	if (h === "critical") return "flagged";
	if (h === "offline") return "inactive";
	return "drifting";
}

export const STATUS_STRIPE: Record<AccountUiStatus, string> = {
	active: "transparent",
	drifting: "var(--color-warning)",
	flagged: "var(--color-critical)",
	inactive: "color-mix(in_srgb,var(--color-foreground)_12%,transparent)",
};

export const STATUS_ROW_TINT: Record<AccountUiStatus, string> = {
	active: "transparent",
	drifting: "transparent",
	flagged: "transparent",
	inactive: "transparent",
};

export const STATUS_LABEL: Record<AccountUiStatus, string> = {
	active: "Active",
	drifting: "Drifting",
	flagged: "Flagged",
	inactive: "Inactive",
};

export const UI_TO_HEALTH_STATE: Record<AccountUiStatus, HealthState> = {
	active: "good",
	drifting: "warning",
	flagged: "critical",
	inactive: "idle",
};

export function formatFollowers(n: number): string {
	if (n >= 1_000_000)
		return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
	if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
	return n.toString();
}

export function formatLastPost(hoursAgo: number | null): string {
	if (hoursAgo === null) return "-";
	if (hoursAgo < 1) return "now";
	if (hoursAgo < 24) return `${hoursAgo}h`;
	const days = Math.floor(hoursAgo / 24);
	return `${days}d`;
}

export function signalLabel(type: AccountSignalType): string {
	if (type === "capability_error") {
		return "Reply farming disabled - Advanced Threads API access required";
	}
	return type.replace(/_/g, " ");
}

export function signalSeverityColor(severity: AccountSignalSeverity): string {
	if (severity === "critical") return "var(--color-critical)";
	if (severity === "warn") return "var(--color-warning)";
	return "var(--color-health-good)";
}

export function accountSignalStatus(
	accountHealth: AccountHealth,
	signals: AccountHealthSignal[] | undefined,
): AccountUiStatus {
	const active = (signals ?? []).filter((signal) => !signal.resolved_at);
	if (active.some((signal) => signal.severity === "critical")) return "flagged";
	if (active.some((signal) => signal.severity === "warn")) return "drifting";
	return uiStatusFromHealth(accountHealth);
}

export function hasTokenExpiringSignal(
	signals: AccountHealthSignal[] | undefined,
): boolean {
	return (signals ?? []).some(
		(signal) => signal.signal_type === "token_expiring" && !signal.resolved_at,
	);
}

export function hasReplyFarmingAdvancedAccessSignal(
	signals: AccountHealthSignal[] | undefined,
): boolean {
	return (signals ?? []).some(
		(signal) =>
			signal.signal_type === "capability_error" &&
			signal.metadata?.capability === "reply_farming" &&
			signal.metadata?.error_code === "needs_advanced_access" &&
			!signal.resolved_at,
	);
}
