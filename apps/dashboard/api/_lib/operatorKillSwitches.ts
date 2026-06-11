import { logger } from "./logger.js";

export const OPERATOR_KILL_SWITCH_TABLE = "operator_kill_switches";

export type OperatorKillSwitchScopeType =
	| "global"
	| "workspace"
	| "group"
	| "account"
	| "session"
	| "api_key";

export type OperatorRiskLevel = "low" | "medium" | "high" | "critical";

export type OperatorKillSwitchContext = {
	userId: string;
	workspaceId?: string | null | undefined;
	groupId?: string | null | undefined;
	accountId?: string | null | undefined;
	sessionId?: string | null | undefined;
	apiKeyId?: string | null | undefined;
	actionName?: string | null | undefined;
	riskLevel?: OperatorRiskLevel | string | null | undefined;
};

export type OperatorKillSwitchBlock = {
	blocked: true;
	reason: string;
	scopeType: OperatorKillSwitchScopeType;
	scopeId: string | null;
	switchId: string | null;
	actionName: string | null;
};

export type OperatorKillSwitchAllowed = {
	blocked: false;
};

export type OperatorKillSwitchResult =
	| OperatorKillSwitchBlock
	| OperatorKillSwitchAllowed;

type SupabaseLike = {
	from: (table: string) => unknown;
};

type KillSwitchRow = {
	id?: string | null;
	user_id?: string | null;
	scope_type?: string | null;
	scope_id?: string | null;
	action_name?: string | null;
	min_risk_level?: string | null;
	reason?: string | null;
	is_active?: boolean | null;
	expires_at?: string | null;
	created_at?: string | null;
};

const SCOPE_RANK: Record<OperatorKillSwitchScopeType, number> = {
	global: 0,
	workspace: 1,
	group: 2,
	account: 3,
	session: 4,
	api_key: 5,
};

const RISK_RANK: Record<OperatorRiskLevel, number> = {
	low: 0,
	medium: 1,
	high: 2,
	critical: 3,
};

/**
 * Checks active operator kill switches from broadest to narrowest scope.
 * A single matching row blocks the outbound/high-risk action and returns a
 * reason safe to expose to the operator UI/API caller.
 */
export async function checkOperatorKillSwitch(
	db: SupabaseLike,
	context: OperatorKillSwitchContext,
): Promise<OperatorKillSwitchResult> {
	const nowIso = new Date().toISOString();

	try {
		const [legacyProfilePaused, switches] = await Promise.all([
			readLegacyAgentPaused(db, context.userId),
			readKillSwitchRows(db, context.userId),
		]);

		if (legacyProfilePaused) {
			return {
				blocked: true,
				reason: "Operator action blocked: global agent pause is enabled.",
				scopeType: "global",
				scopeId: null,
				switchId: null,
				actionName: context.actionName ?? null,
			};
		}

		const candidates = buildScopeCandidates(context);
		const matching = switches
			.filter((row) => rowMatchesContext(row, candidates, context, nowIso))
			.sort(compareKillSwitches)[0];

		if (!matching) return { blocked: false };

		const scopeType = normalizeScopeType(matching.scope_type) ?? "global";
		const scopeId = matching.scope_id ?? null;
		const switchReason = matching.reason?.trim() || "No reason provided";
		const action = context.actionName ?? matching.action_name ?? "operator action";

		return {
			blocked: true,
			reason: `Operator action blocked by ${formatScope(scopeType, scopeId)} kill switch: ${switchReason}`,
			scopeType,
			scopeId,
			switchId: matching.id ?? null,
			actionName: action,
		};
	} catch (error) {
		logger.warn("[operatorKillSwitches] Check failed — failing open", {
			userId: context.userId,
			actionName: context.actionName,
			error: String(error),
		});
		return { blocked: false };
	}
}

function buildScopeCandidates(context: OperatorKillSwitchContext) {
	const candidates = new Map<OperatorKillSwitchScopeType, Set<string | null>>();
	addCandidate(candidates, "global", null);
	addCandidate(candidates, "workspace", context.workspaceId);
	addCandidate(candidates, "group", context.groupId);
	addCandidate(candidates, "account", context.accountId);
	addCandidate(candidates, "session", context.sessionId);
	addCandidate(candidates, "api_key", context.apiKeyId);
	return candidates;
}

function addCandidate(
	candidates: Map<OperatorKillSwitchScopeType, Set<string | null>>,
	scopeType: OperatorKillSwitchScopeType,
	scopeId: string | null | undefined,
) {
	if (scopeId === undefined || scopeId === "") return;
	const values = candidates.get(scopeType) ?? new Set<string | null>();
	values.add(scopeId);
	candidates.set(scopeType, values);
}

function rowMatchesContext(
	row: KillSwitchRow,
	candidates: Map<OperatorKillSwitchScopeType, Set<string | null>>,
	context: OperatorKillSwitchContext,
	nowIso: string,
) {
	if (row.is_active === false) return false;
	if (row.expires_at && row.expires_at <= nowIso) return false;

	const scopeType = normalizeScopeType(row.scope_type);
	if (!scopeType) return false;

	const scopeValues = candidates.get(scopeType);
	if (!scopeValues?.has(row.scope_id ?? null)) return false;

	if (row.action_name && row.action_name !== context.actionName) return false;

	if (row.min_risk_level) {
		const rowRisk = normalizeRisk(row.min_risk_level);
		const contextRisk = normalizeRisk(context.riskLevel) ?? "medium";
		if (!rowRisk || RISK_RANK[contextRisk] < RISK_RANK[rowRisk]) return false;
	}

	return true;
}

function compareKillSwitches(a: KillSwitchRow, b: KillSwitchRow) {
	const aScope = normalizeScopeType(a.scope_type) ?? "api_key";
	const bScope = normalizeScopeType(b.scope_type) ?? "api_key";
	const byScope = SCOPE_RANK[aScope] - SCOPE_RANK[bScope];
	if (byScope !== 0) return byScope;

	const aCreated = a.created_at ? Date.parse(a.created_at) : 0;
	const bCreated = b.created_at ? Date.parse(b.created_at) : 0;
	return bCreated - aCreated;
}

function normalizeScopeType(value: string | null | undefined) {
	if (
		value === "global" ||
		value === "workspace" ||
		value === "group" ||
		value === "account" ||
		value === "session" ||
		value === "api_key"
	) {
		return value;
	}
	return null;
}

function normalizeRisk(value: string | null | undefined) {
	if (
		value === "low" ||
		value === "medium" ||
		value === "high" ||
		value === "critical"
	) {
		return value;
	}
	return null;
}

function formatScope(scopeType: OperatorKillSwitchScopeType, scopeId: string | null) {
	if (scopeType === "global") return "global";
	return `${scopeType} ${scopeId ?? "(unknown)"}`;
}

async function readLegacyAgentPaused(db: SupabaseLike, userId: string) {
	const query = db.from("profiles") as {
		select: (columns: string) => {
			eq: (column: string, value: string) => {
				maybeSingle: () => Promise<{ data?: { agent_paused?: boolean | null } | null }>;
			};
		};
	};

	const { data } = await query
		.select("agent_paused")
		.eq("id", userId)
		.maybeSingle();

	return data?.agent_paused === true;
}

async function readKillSwitchRows(db: SupabaseLike, userId: string) {
	const query = db.from(OPERATOR_KILL_SWITCH_TABLE) as {
		select: (columns: string) => {
			eq: (
				column: string,
				value: string | boolean,
			) => {
				eq: (
					column: string,
					value: string | boolean,
				) => {
					order: (
						column: string,
						options: { ascending: boolean },
					) => {
						limit: (
							count: number,
						) => Promise<{ data?: KillSwitchRow[] | null }>;
					};
				};
			};
		};
	};

	const { data } = await query
		.select(
			"id, user_id, scope_type, scope_id, action_name, min_risk_level, reason, is_active, expires_at, created_at",
		)
		.eq("user_id", userId)
		.eq("is_active", true)
		.order("created_at", { ascending: false })
		.limit(100);

	return data ?? [];
}
