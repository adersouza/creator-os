import { describe, expect, it } from "vitest";
import {
	isActiveWindowNow,
	resolvePublishSchedulePolicy,
	satisfiesPlannedAccountConstraints,
} from "../../api/_lib/handlers/auto-post-publish/accountSchedulePolicy";

describe("auto-post publish account schedule policy", () => {
	it("prefers account_schedule over group 0-0 all-day fallback", () => {
		const policy = resolvePublishSchedulePolicy({
			accountSchedule: {
				active_hours_start: 9,
				active_hours_end: 17,
				timezone: "America/New_York",
				min_interval_minutes: 180,
				paused: false,
				status: "active",
				blocked_until: null,
			},
			legacyOverride: null,
			groupConfig: {
				active_hours_start: 0,
				active_hours_end: 0,
				timezone: "America/New_York",
				min_interval_minutes: 25,
			},
		});

		expect(policy.source).toBe("account_schedule");
		expect(policy.activeHoursStart).toBe(9);
		expect(policy.activeHoursEnd).toBe(17);
		expect(policy.minIntervalMinutes).toBe(180);
		expect(isActiveWindowNow(policy, new Date("2026-06-06T22:00:00.000Z"))).toBe(
			false,
		);
	});

	it("falls back to group config when account_schedule is missing", () => {
		const policy = resolvePublishSchedulePolicy({
			accountSchedule: null,
			legacyOverride: null,
			groupConfig: {
				active_hours_start: 0,
				active_hours_end: 0,
				timezone: "America/New_York",
				min_interval_minutes: 25,
			},
		});

		expect(policy.source).toBe("group_config");
		expect(isActiveWindowNow(policy, new Date("2026-06-06T22:00:00.000Z"))).toBe(
			true,
		);
	});

	it("requires alternate pool assignment to satisfy planned account window constraints", () => {
		const planned = {
			accountId: "planned-1",
			accountWindow: { start: 6, end: 13 },
			minIntervalMinutes: 180,
			timezone: "America/New_York",
		};
		const selectedPolicy = resolvePublishSchedulePolicy({
			accountSchedule: {
				active_hours_start: 18,
				active_hours_end: 23,
				timezone: "America/New_York",
				min_interval_minutes: 180,
				paused: false,
				status: "active",
				blocked_until: null,
			},
			legacyOverride: null,
			groupConfig: null,
		});

		expect(
			satisfiesPlannedAccountConstraints({
				selectedAccountId: "alternate-1",
				plannedAccount: planned,
				selectedPolicy,
				now: new Date("2026-06-06T22:00:00.000Z"),
			}),
		).toBe(false);
	});

	it("rejects alternate pool assignment outside the planned candidate account set", () => {
		const selectedPolicy = resolvePublishSchedulePolicy({
			accountSchedule: {
				active_hours_start: 6,
				active_hours_end: 13,
				timezone: "America/New_York",
				min_interval_minutes: 180,
				paused: false,
				status: "active",
				blocked_until: null,
			},
			legacyOverride: null,
			groupConfig: null,
		});

		expect(
			satisfiesPlannedAccountConstraints({
				selectedAccountId: "alternate-1",
				plannedAccount: {
					accountId: "planned-1",
					candidateAccountIds: ["planned-1"],
					accountWindow: { start: 6, end: 13 },
					minIntervalMinutes: 180,
					timezone: "America/New_York",
				},
				selectedPolicy,
				now: new Date("2026-06-06T14:00:00.000Z"),
			}),
		).toBe(false);
	});
});
