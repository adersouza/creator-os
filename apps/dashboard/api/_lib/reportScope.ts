import { logger } from "./logger.js";
import { getSupabaseAny } from "./supabase.js";

export type ReportPlatformScope = "threads" | "instagram";

export interface SavedReportScopeInput {
	id: string;
	user_id: string;
	name?: string | null | undefined;
	network?: string | null | undefined;
	config?: Record<string, unknown> | null | undefined;
}

export type ResolvedReportScope =
	| {
			ok: true;
			platform: ReportPlatformScope;
			accountIds: string[];
			accountCount: number;
			scopeLabel: string;
			warnings: string[];
	  }
	| {
			ok: false;
			status: number;
			error: string;
			scopeLabel: string;
			warnings: string[];
	  };

interface AccountCandidate {
	id: string;
	groupId: string | null;
	platform: ReportPlatformScope;
	active: boolean;
	retired: boolean;
}

export async function resolveReportScope(
	report: SavedReportScopeInput,
): Promise<ResolvedReportScope> {
	const db = getSupabaseAny();
	const config = isRecord(report.config) ? report.config : {};
	const configuredAccountIds = readStringArray(config.accountIds);
	const configuredGroupIds = readStringArray(config.groupIds);
	const groupIds =
		configuredGroupIds.length > 0
			? configuredGroupIds
			: typeof report.network === "string" && report.network.length > 0
				? [report.network]
				: [];
	const groupSet = new Set(groupIds);
	const configuredAccountSet = new Set(configuredAccountIds);
	const requestedPlatform = readPlatform(config.platform);
	const warnings: string[] = [];

	const [threadsResult, instagramResult] = await Promise.all([
		db
			.from("accounts")
			.select("id, group_id, is_active, is_retired")
			.eq("user_id", report.user_id)
			.limit(1000),
		db
			.from("instagram_accounts")
			.select("id, group_id, is_active")
			.eq("user_id", report.user_id)
			.limit(1000),
	]);

	if (threadsResult.error) {
		logger.error("[reports] Threads account scope lookup failed", {
			reportId: report.id,
			error: threadsResult.error.message,
		});
		return {
			ok: false,
			status: 500,
			error: "Could not resolve Threads report accounts",
			scopeLabel: "Unresolved report scope",
			warnings,
		};
	}
	if (instagramResult.error) {
		logger.error("[reports] Instagram account scope lookup failed", {
			reportId: report.id,
			error: instagramResult.error.message,
		});
		return {
			ok: false,
			status: 500,
			error: "Could not resolve Instagram report accounts",
			scopeLabel: "Unresolved report scope",
			warnings,
		};
	}

	const candidates = [
		...(threadsResult.data ?? []).map((row: Record<string, unknown>) =>
			toCandidate(row, "threads"),
		),
		...(instagramResult.data ?? []).map((row: Record<string, unknown>) =>
			toCandidate(row, "instagram"),
		),
	]
		.filter((row) => row.id.length > 0)
		.filter((row) => row.active && !row.retired)
		.filter((row) => groupSet.size === 0 || groupSet.has(row.groupId ?? ""))
		.filter(
			(row) =>
				configuredAccountSet.size === 0 || configuredAccountSet.has(row.id),
		);

	const threadsIds = candidates
		.filter((row) => row.platform === "threads")
		.map((row) => row.id);
	const instagramIds = candidates
		.filter((row) => row.platform === "instagram")
		.map((row) => row.id);

	const platform = choosePlatform({
		requestedPlatform,
		threadsCount: threadsIds.length,
		instagramCount: instagramIds.length,
		hasExplicitAccounts: configuredAccountIds.length > 0,
	});

	if (platform === "mixed") {
		return {
			ok: false,
			status: 400,
			error:
				"Mixed-platform PDF reports are not supported yet. Choose Threads or Instagram in report settings.",
			scopeLabel: "Mixed platform report",
			warnings,
		};
	}

	if (!requestedPlatform && instagramIds.length > 0 && platform === "threads") {
		warnings.push(
			"Report platform defaulted to Threads. Set platform to Instagram for Instagram-only reports.",
		);
	}

	const accountIds = platform === "instagram" ? instagramIds : threadsIds;
	const platformLabel = platform === "instagram" ? "Instagram" : "Threads";
	const scopeLabel = scopeName(platformLabel, accountIds.length, groupIds.length);

	if (accountIds.length === 0) {
		return {
			ok: false,
			status: 400,
			error: `No active ${platformLabel} accounts matched this report scope.`,
			scopeLabel,
			warnings,
		};
	}

	return {
		ok: true,
		platform,
		accountIds: Array.from(new Set(accountIds)),
		accountCount: accountIds.length,
		scopeLabel,
		warnings,
	};
}

function readStringArray(value: unknown): string[] {
	if (!Array.isArray(value)) return [];
	return Array.from(
		new Set(
			value
				.map((item) => (typeof item === "string" ? item.trim() : ""))
				.filter(Boolean),
		),
	);
}

function readPlatform(value: unknown): ReportPlatformScope | "all" | null {
	if (value === "threads" || value === "instagram" || value === "all") {
		return value;
	}
	return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return !!value && typeof value === "object" && !Array.isArray(value);
}

function toCandidate(
	row: Record<string, unknown>,
	platform: ReportPlatformScope,
): AccountCandidate {
	return {
		id: typeof row.id === "string" ? row.id : String(row.id ?? ""),
		groupId:
			typeof row.group_id === "string" && row.group_id.length > 0
				? row.group_id
				: null,
		platform,
		active: row.is_active !== false,
		retired: row.is_retired === true,
	};
}

function choosePlatform({
	requestedPlatform,
	threadsCount,
	instagramCount,
	hasExplicitAccounts,
}: {
	requestedPlatform: ReportPlatformScope | "all" | null;
	threadsCount: number;
	instagramCount: number;
	hasExplicitAccounts: boolean;
}): ReportPlatformScope | "mixed" {
	if (requestedPlatform === "threads" || requestedPlatform === "instagram") {
		return requestedPlatform;
	}
	if (requestedPlatform === "all") {
		if (threadsCount > 0 && instagramCount > 0) return "mixed";
		return instagramCount > 0 ? "instagram" : "threads";
	}
	if (hasExplicitAccounts && threadsCount === 0 && instagramCount > 0) {
		return "instagram";
	}
	return "threads";
}

function scopeName(
	platformLabel: string,
	accountCount: number,
	groupCount: number,
): string {
	const accountLabel =
		accountCount === 1 ? "1 account" : `${accountCount} accounts`;
	if (groupCount > 0) {
		const groupLabel = groupCount === 1 ? "1 group" : `${groupCount} groups`;
		return `${platformLabel} - ${groupLabel} - ${accountLabel}`;
	}
	return `${platformLabel} - all groups - ${accountLabel}`;
}
