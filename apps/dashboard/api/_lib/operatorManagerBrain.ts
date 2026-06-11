import type { getSupabaseAny } from "./supabase.js";

type Db = ReturnType<typeof getSupabaseAny>;
type Row = Record<string, unknown>;

export type ManagerBrainSnapshot = {
	activeGoals: Row[];
	activeCycles: Row[];
	activePlans: Array<Row & { items: Row[] }>;
	recentDecisions: Row[];
	staleEvidenceWarnings: Array<{
		key: string;
		cycleId: string;
		objective: string;
		severity: "medium" | "high";
		message: string;
		evidenceAt: string | null;
	}>;
	recommendedNextActions: Array<{
		key: string;
		label: string;
		priority: "low" | "medium" | "high";
		type: string;
		linkedEntityType?: string | undefined;
		linkedEntityId?: string | undefined;
	}>;
};

const ACTIVE_GOAL_STATUSES = ["active", "paused"];
const ACTIVE_CYCLE_STATUSES = ["open", "running", "blocked"];
const ACTIVE_PLAN_STATUSES = ["draft", "pending_approval", "approved", "running"];
const ACTIVE_PLAN_ITEM_STATUSES = ["pending", "blocked", "approved", "running", "failed"];
const STALE_EVIDENCE_MS = 6 * 60 * 60 * 1000;
const MISSING_EVIDENCE_MS = 4 * 60 * 60 * 1000;

export async function loadOperatorManagerBrain(
	db: Db,
	userId: string,
	now = new Date(),
): Promise<ManagerBrainSnapshot> {
	const [goals, cycles, plans, decisions] = await Promise.all([
		db
			.from("manager_goals")
			.select("id, workspace_id, group_id, account_id, metric, baseline, target, deadline, priority, constraints, status, created_at, updated_at")
			.eq("user_id", userId)
			.in("status", ACTIVE_GOAL_STATUSES)
			.order("updated_at", { ascending: false })
			.limit(25),
		db
			.from("manager_cycles")
			.select("id, objective, status, started_at, completed_at, evidence_snapshot, created_at")
			.eq("user_id", userId)
			.in("status", ACTIVE_CYCLE_STATUSES)
			.order("started_at", { ascending: false })
			.limit(15),
		db
			.from("manager_plans")
			.select("id, cycle_id, goal_id, title, status, confidence, risk_level, expected_outcome, created_at, updated_at")
			.eq("user_id", userId)
			.in("status", ACTIVE_PLAN_STATUSES)
			.order("updated_at", { ascending: false })
			.limit(25),
		db
			.from("manager_decisions")
			.select("id, plan_item_id, scope, decision_type, options_json, selected_option, evidence_refs, confidence, risk_level, approval_id, action_hash, expected_outcome, actual_outcome, review_status, created_at")
			.eq("user_id", userId)
			.order("created_at", { ascending: false })
			.limit(25),
	]);

	const planRows = rows(plans.data);
	const planIds = planRows.map((plan) => stringValue(plan.id)).filter(Boolean);
	const planItems = planIds.length
		? await db
			.from("manager_plan_items")
			.select("id, plan_id, title, status, selected_action, alternatives, confidence, risk_level, approval_id, intent_id, expected_outcome, actual_outcome, created_at, updated_at")
			.eq("user_id", userId)
			.in("plan_id", planIds)
			.in("status", ACTIVE_PLAN_ITEM_STATUSES)
			.order("updated_at", { ascending: false })
			.limit(100)
		: { data: [] };

	return buildOperatorManagerBrainSnapshot({
		goals: rows(goals.data),
		cycles: rows(cycles.data),
		plans: planRows,
		planItems: rows(planItems.data),
		decisions: rows(decisions.data),
		now,
	});
}

export function buildOperatorManagerBrainSnapshot(input: {
	goals: Row[];
	cycles: Row[];
	plans: Row[];
	planItems: Row[];
	decisions: Row[];
	now?: Date;
}): ManagerBrainSnapshot {
	const now = input.now ?? new Date();
	const itemsByPlan = new Map<string, Row[]>();
	for (const item of input.planItems) {
		const planId = stringValue(item.plan_id);
		if (!planId) continue;
		const bucket = itemsByPlan.get(planId) ?? [];
		bucket.push(item);
		itemsByPlan.set(planId, bucket);
	}

	const activePlans = input.plans.map((plan) => ({
		...plan,
		items: itemsByPlan.get(stringValue(plan.id) ?? "") ?? [],
	}));
	const staleEvidenceWarnings = input.cycles
		.map((cycle) => staleEvidenceWarning(cycle, now))
		.filter((warning): warning is NonNullable<typeof warning> => Boolean(warning));

	return {
		activeGoals: input.goals,
		activeCycles: input.cycles,
		activePlans,
		recentDecisions: input.decisions,
		staleEvidenceWarnings,
		recommendedNextActions: buildManagerBrainRecommendations({
			goals: input.goals,
			cycles: input.cycles,
			plans: activePlans,
			planItems: input.planItems,
			decisions: input.decisions,
			staleEvidenceWarnings,
		}),
	};
}

function staleEvidenceWarning(cycle: Row, now: Date): ManagerBrainSnapshot["staleEvidenceWarnings"][number] | null {
	const cycleId = stringValue(cycle.id);
	if (!cycleId) return null;
	const objective = stringValue(cycle.objective) ?? "Manager cycle";
	const evidence = recordValue(cycle.evidence_snapshot);
	const evidenceAt = evidenceTimestamp(evidence);
	const startedAt = parseDate(stringValue(cycle.started_at) ?? stringValue(cycle.created_at));
	const ageMs = evidenceAt ? now.getTime() - evidenceAt.getTime() : null;
	const missingAgeMs = startedAt ? now.getTime() - startedAt.getTime() : null;

	if (evidenceAt && ageMs !== null && ageMs > STALE_EVIDENCE_MS) {
		return {
			key: `stale_evidence:${cycleId}`,
			cycleId,
			objective,
			severity: ageMs > 24 * 60 * 60 * 1000 ? "high" : "medium",
			message: `Evidence for "${objective}" is stale; refresh the operator snapshot before making new decisions.`,
			evidenceAt: evidenceAt.toISOString(),
		};
	}

	if (!evidenceAt && missingAgeMs !== null && missingAgeMs > MISSING_EVIDENCE_MS) {
		return {
			key: `missing_evidence:${cycleId}`,
			cycleId,
			objective,
			severity: "high",
			message: `Cycle "${objective}" has no timestamped evidence snapshot.`,
			evidenceAt: null,
		};
	}

	return null;
}

function buildManagerBrainRecommendations(input: {
	goals: Row[];
	cycles: Row[];
	plans: Array<Row & { items: Row[] }>;
	planItems: Row[];
	decisions: Row[];
	staleEvidenceWarnings: ManagerBrainSnapshot["staleEvidenceWarnings"];
}): ManagerBrainSnapshot["recommendedNextActions"] {
	const actions: ManagerBrainSnapshot["recommendedNextActions"] = [];
	const pendingApprovalPlan = input.plans.find((plan) => plan.status === "pending_approval");
	const blockedItem = input.planItems.find((item) => item.status === "blocked");
	const failedItem = input.planItems.find((item) => item.status === "failed");
	const lowConfidenceDecision = input.decisions.find((decision) => {
		const confidence = numberValue(decision.confidence);
		return confidence !== null && confidence < 0.6 && decision.review_status !== "accepted";
	});

	if (!input.goals.length) {
		actions.push({
			key: "define_manager_goal",
			label: "Define the manager's current growth or operations goal",
			priority: "medium",
			type: "create_manager_goal",
		});
	}
	if (input.staleEvidenceWarnings.length > 0) {
		actions.push({
			key: "refresh_stale_manager_evidence",
			label: "Refresh stale manager evidence before approving new actions",
			priority: "high",
			type: "refresh_operator_snapshot",
			linkedEntityType: "manager_cycle",
			linkedEntityId: input.staleEvidenceWarnings[0]?.cycleId,
		});
	}
	if (pendingApprovalPlan) {
		actions.push({
			key: `review_manager_plan:${pendingApprovalPlan.id}`,
			label: `Review manager plan: ${pendingApprovalPlan.title || "Untitled plan"}`,
			priority: riskPriority(pendingApprovalPlan.risk_level),
			type: "review_manager_plan",
			linkedEntityType: "manager_plan",
			linkedEntityId: stringValue(pendingApprovalPlan.id) ?? undefined,
		});
	}
	if (blockedItem) {
		actions.push({
			key: `unblock_plan_item:${blockedItem.id}`,
			label: `Unblock manager step: ${blockedItem.title || "Plan item"}`,
			priority: "high",
			type: "unblock_manager_plan_item",
			linkedEntityType: "manager_plan_item",
			linkedEntityId: stringValue(blockedItem.id) ?? undefined,
		});
	}
	if (failedItem) {
		actions.push({
			key: `inspect_failed_plan_item:${failedItem.id}`,
			label: `Inspect failed manager step: ${failedItem.title || "Plan item"}`,
			priority: "high",
			type: "inspect_failed_manager_plan_item",
			linkedEntityType: "manager_plan_item",
			linkedEntityId: stringValue(failedItem.id) ?? undefined,
		});
	}
	if (lowConfidenceDecision) {
		actions.push({
			key: `review_low_confidence_decision:${lowConfidenceDecision.id}`,
			label: `Review low-confidence ${lowConfidenceDecision.decision_type || "manager"} decision`,
			priority: "medium",
			type: "review_manager_decision",
			linkedEntityType: "manager_decision",
			linkedEntityId: stringValue(lowConfidenceDecision.id) ?? undefined,
		});
	}
	if (input.goals.length > 0 && input.plans.length === 0) {
		actions.push({
			key: "create_plan_from_active_goal",
			label: "Create a plan for the active manager goal",
			priority: "medium",
			type: "create_manager_plan",
			linkedEntityType: "manager_goal",
			linkedEntityId: stringValue(input.goals[0]?.id) ?? undefined,
		});
	}
	if (!actions.length) {
		actions.push({
			key: "manager_brain_clear",
			label: "Manager brain has no blocked plans or stale evidence",
			priority: "low",
			type: "monitor_manager_state",
		});
	}
	return actions;
}

function evidenceTimestamp(evidence: Row | null): Date | null {
	if (!evidence) return null;
	const keys = [
		"generatedAt",
		"generated_at",
		"capturedAt",
		"captured_at",
		"collectedAt",
		"collected_at",
		"asOf",
		"as_of",
		"snapshotAt",
		"snapshot_at",
	];
	for (const key of keys) {
		const parsed = parseDate(stringValue(evidence[key]));
		if (parsed) return parsed;
	}
	return null;
}

function riskPriority(value: unknown): "low" | "medium" | "high" {
	return value === "high" || value === "critical" ? "high" : "medium";
}

function rows(value: unknown): Row[] {
	return Array.isArray(value)
		? value.filter((row): row is Row => Boolean(row) && typeof row === "object" && !Array.isArray(row))
		: [];
}

function recordValue(value: unknown): Row | null {
	return value && typeof value === "object" && !Array.isArray(value) ? value as Row : null;
}

function stringValue(value: unknown): string | null {
	return typeof value === "string" && value.length > 0 ? value : null;
}

function numberValue(value: unknown): number | null {
	return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function parseDate(value: string | null): Date | null {
	if (!value) return null;
	const date = new Date(value);
	return Number.isFinite(date.getTime()) ? date : null;
}
