import { describe, expect, it } from "vitest";
import {
	buildAccountScheduleDriftReport,
	deriveAccountScheduleStatus,
} from "../../api/_lib/handlers/auto-post/accountScheduleStatusSync";

const baseState = {
	account_id: "acct-1",
	group_id: "group-1",
	workspace_id: "workspace-1",
	status: "active" as const,
	account_health_score: 100,
	restart_warmup_status: "warming" as const,
	recommended_strategy_mode: "clone_winners",
};

const baseAccount = {
	id: "acct-1",
	username: "creator_1",
	is_active: true,
	is_retired: false,
	needs_reauth: false,
	is_shadowbanned: false,
	status: null,
};

describe("accountScheduleStatusSync", () => {
	it("marks stale legacy schedule states as repairable when current health truth is active", () => {
		const report = buildAccountScheduleDriftReport({
			states: [baseState],
			accounts: [baseAccount],
			schedules: [
				{
					account_id: "acct-1",
					group_id: "group-1",
					status: "flop_delay",
					paused: false,
					blocked_until: null,
				},
			],
			dryRun: true,
		});

		expect(report.mismatches).toBe(1);
		expect(report.rows[0]).toMatchObject({
			currentStatus: "flop_delay",
			desiredStatus: "active",
			wouldRepair: true,
			scheduleBlocksPlanner: true,
		});
	});

	it("preserves manually paused rows even when their schedule status is stale", () => {
		const report = buildAccountScheduleDriftReport({
			states: [baseState],
			accounts: [baseAccount],
			schedules: [
				{
					account_id: "acct-1",
					group_id: "group-1",
					status: "view_cooldown",
					paused: true,
					blocked_until: null,
				},
			],
			dryRun: true,
		});

		expect(report.skippedPaused).toBe(1);
		expect(report.mismatches).toBe(0);
		expect(report.rows[0]).toMatchObject({
			manuallyPaused: true,
			wouldRepair: false,
		});
	});

	it("derives inactive schedule status for reauth or deactivated accounts", () => {
		const decision = deriveAccountScheduleStatus({
			state: baseState,
			account: {
				...baseAccount,
				needs_reauth: true,
				is_active: false,
			},
		});

		expect(decision).toMatchObject({
			desiredStatus: "inactive",
			shouldBlockPlanner: true,
		});
	});

	it("derives suppressed schedule status for performance suppress mode", () => {
		const decision = deriveAccountScheduleStatus({
			state: {
				...baseState,
				recommended_strategy_mode: "suppress",
			},
			account: baseAccount,
		});

		expect(decision).toMatchObject({
			desiredStatus: "suppressed",
			reason: "performance_strategy_suppress",
			shouldBlockPlanner: true,
		});
	});
});
