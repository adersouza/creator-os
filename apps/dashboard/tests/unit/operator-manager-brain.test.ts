import { describe, expect, it } from "vitest";
import { buildOperatorManagerBrainSnapshot } from "../../api/_lib/operatorManagerBrain.js";

describe("operator manager brain snapshot", () => {
	const now = new Date("2026-05-22T16:00:00.000Z");

	it("groups active plan items under their plans and returns recent decisions", () => {
		const snapshot = buildOperatorManagerBrainSnapshot({
			now,
			goals: [
				{
					id: "goal-1",
					metric: "publish_success_rate",
					status: "active",
					priority: "high",
				},
			],
			cycles: [],
			plans: [
				{
					id: "plan-1",
					title: "Recover posting reliability",
					status: "running",
					risk_level: "medium",
				},
			],
			planItems: [
				{
					id: "item-1",
					plan_id: "plan-1",
					title: "Review failed publishes",
					status: "running",
				},
			],
			decisions: [
				{
					id: "decision-1",
					decision_type: "prioritize_failed_publish",
					confidence: 0.82,
					review_status: "accepted",
				},
			],
		});

		expect(snapshot.activeGoals).toHaveLength(1);
		expect(snapshot.activePlans).toHaveLength(1);
		expect(snapshot.activePlans[0]?.items).toHaveLength(1);
		expect(snapshot.activePlans[0]?.items[0]?.title).toBe("Review failed publishes");
		expect(snapshot.recentDecisions[0]?.decision_type).toBe("prioritize_failed_publish");
	});

	it("warns and recommends a refresh when cycle evidence is stale", () => {
		const snapshot = buildOperatorManagerBrainSnapshot({
			now,
			goals: [{ id: "goal-1", metric: "growth", status: "active" }],
			cycles: [
				{
					id: "cycle-1",
					objective: "Plan tomorrow's queue",
					status: "running",
					started_at: "2026-05-22T08:00:00.000Z",
					evidence_snapshot: {
						generatedAt: "2026-05-22T06:00:00.000Z",
					},
				},
			],
			plans: [],
			planItems: [],
			decisions: [],
		});

		expect(snapshot.staleEvidenceWarnings).toHaveLength(1);
		expect(snapshot.staleEvidenceWarnings[0]?.key).toBe("stale_evidence:cycle-1");
		expect(snapshot.recommendedNextActions).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					key: "refresh_stale_manager_evidence",
					type: "refresh_operator_snapshot",
					priority: "high",
				}),
			]),
		);
	});

	it("surfaces blocked steps, pending approvals, low-confidence decisions, and missing plans", () => {
		const snapshot = buildOperatorManagerBrainSnapshot({
			now,
			goals: [{ id: "goal-1", metric: "engagement", status: "active" }],
			cycles: [
				{
					id: "cycle-2",
					objective: "Fix engagement drop",
					status: "running",
					started_at: "2026-05-22T08:00:00.000Z",
					evidence_snapshot: {},
				},
			],
			plans: [
				{
					id: "plan-2",
					title: "Repair engagement workflow",
					status: "pending_approval",
					risk_level: "high",
				},
			],
			planItems: [
				{
					id: "item-2",
					plan_id: "plan-2",
					title: "Confirm reply policy",
					status: "blocked",
				},
				{
					id: "item-3",
					plan_id: "plan-2",
					title: "Replay failed task",
					status: "failed",
				},
			],
			decisions: [
				{
					id: "decision-2",
					decision_type: "draft_reply",
					confidence: 0.42,
					review_status: "unreviewed",
				},
			],
		});

		const keys = snapshot.recommendedNextActions.map((action) => action.key);

		expect(keys).toContain("refresh_stale_manager_evidence");
		expect(keys).toContain("review_manager_plan:plan-2");
		expect(keys).toContain("unblock_plan_item:item-2");
		expect(keys).toContain("inspect_failed_plan_item:item-3");
		expect(keys).toContain("review_low_confidence_decision:decision-2");
	});

	it("recommends defining goals or creating a plan when state is incomplete", () => {
		const empty = buildOperatorManagerBrainSnapshot({
			now,
			goals: [],
			cycles: [],
			plans: [],
			planItems: [],
			decisions: [],
		});
		const goalOnly = buildOperatorManagerBrainSnapshot({
			now,
			goals: [{ id: "goal-1", metric: "queue_coverage", status: "active" }],
			cycles: [],
			plans: [],
			planItems: [],
			decisions: [],
		});

		expect(empty.recommendedNextActions).toEqual(
			expect.arrayContaining([
				expect.objectContaining({ key: "define_manager_goal" }),
			]),
		);
		expect(goalOnly.recommendedNextActions).toEqual(
			expect.arrayContaining([
				expect.objectContaining({ key: "create_plan_from_active_goal" }),
			]),
		);
	});
});
