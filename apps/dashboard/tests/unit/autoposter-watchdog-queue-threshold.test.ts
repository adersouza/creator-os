import { describe, expect, it } from "vitest";

import {
	calculateDemandAwareQueueThreshold,
	lowQueueWarningWatermark,
} from "../../api/cron/autoposter-watchdog";

describe("autoposter watchdog demand-aware queue threshold", () => {
	it("does not over-alert small warm-up groups with enough ready depth", () => {
		const threshold = calculateDemandAwareQueueThreshold({
			configuredThreshold: 20,
			groupDailyCap: 2,
			accountIds: ["stacey-1", "stacey-2", "stacey-3"],
			stateByAccount: new Map([
				[
					"stacey-1",
					{
						account_id: "stacey-1",
						status: "active",
						restart_warmup_status: "warming",
						restart_warmup_allowed_posts_per_day: 1,
					},
				],
				[
					"stacey-2",
					{
						account_id: "stacey-2",
						status: "active",
						restart_warmup_status: "warming",
						restart_warmup_allowed_posts_per_day: 1,
					},
				],
				[
					"stacey-3",
					{
						account_id: "stacey-3",
						status: "active",
						restart_warmup_status: "warming",
						restart_warmup_allowed_posts_per_day: 1,
					},
				],
			]),
		});

		expect(threshold).toBe(3);
		expect(lowQueueWarningWatermark(threshold)).toBe(2);
		expect(9).toBeGreaterThan(Math.floor(threshold / 2));
	});

	it("uses one-day demand for large groups fully constrained by warm-up", () => {
		const stateByAccount = new Map(
			Array.from({ length: 24 }, (_, index) => [
				`larissa-${index}`,
				{
					account_id: `larissa-${index}`,
					status: "active",
					restart_warmup_status: "warming",
					restart_warmup_allowed_posts_per_day: 1,
				},
			]),
		);

		const threshold = calculateDemandAwareQueueThreshold({
			configuredThreshold: 20,
			groupDailyCap: 2,
			accountIds: Array.from(stateByAccount.keys()),
			stateByAccount,
		});

		expect(threshold).toBe(20);
		expect(lowQueueWarningWatermark(threshold)).toBe(6);
		expect(11).toBeGreaterThan(Math.floor(threshold / 2));
		expect(3).toBeLessThanOrEqual(Math.floor(threshold / 2));
	});

	it("uses next-24h demand when any account is on normal volume", () => {
		const threshold = calculateDemandAwareQueueThreshold({
			configuredThreshold: 20,
			groupDailyCap: 2,
			accountIds: ["warming", "normal"],
			stateByAccount: new Map([
				[
					"warming",
					{
						account_id: "warming",
						status: "active",
						restart_warmup_status: "warming",
						restart_warmup_allowed_posts_per_day: 1,
					},
				],
				[
					"normal",
					{
						account_id: "normal",
						status: "active",
						restart_warmup_status: "none",
						restart_warmup_allowed_posts_per_day: null,
					},
				],
			]),
		});

		expect(threshold).toBe(3);
	});

	it("uses account schedule volume instead of stale group volume when present", () => {
		const threshold = calculateDemandAwareQueueThreshold({
			configuredThreshold: 20,
			groupDailyCap: 4,
			accountIds: ["normal", "warming", "suppressed", "inactive"],
			stateByAccount: new Map([
				[
					"normal",
					{
						account_id: "normal",
						status: "active",
						restart_warmup_status: "none",
						restart_warmup_allowed_posts_per_day: null,
					},
				],
				[
					"warming",
					{
						account_id: "warming",
						status: "active",
						restart_warmup_status: "warming",
						restart_warmup_allowed_posts_per_day: 2,
					},
				],
				[
					"suppressed",
					{
						account_id: "suppressed",
						status: "active",
						restart_warmup_status: "suppressed",
						restart_warmup_allowed_posts_per_day: 0,
					},
				],
				[
					"inactive",
					{
						account_id: "inactive",
						status: "inactive",
						restart_warmup_status: "none",
						restart_warmup_allowed_posts_per_day: null,
					},
				],
			]),
			scheduleByAccount: new Map([
				["normal", { account_id: "normal", posts_per_day: 2 }],
			]),
		});

		expect(threshold).toBe(4);
		expect(lowQueueWarningWatermark(threshold)).toBe(2);
	});

	it("does not count account schedules blocked by cooldown or pause toward demand", () => {
		const threshold = calculateDemandAwareQueueThreshold({
			configuredThreshold: 20,
			groupDailyCap: 4,
			accountIds: ["ready", "cooldown", "paused", "blocked"],
			stateByAccount: new Map([
				[
					"ready",
					{
						account_id: "ready",
						status: "active",
						restart_warmup_status: "none",
						restart_warmup_allowed_posts_per_day: null,
					},
				],
				[
					"cooldown",
					{
						account_id: "cooldown",
						status: "active",
						restart_warmup_status: "none",
						restart_warmup_allowed_posts_per_day: null,
					},
				],
				[
					"paused",
					{
						account_id: "paused",
						status: "active",
						restart_warmup_status: "none",
						restart_warmup_allowed_posts_per_day: null,
					},
				],
				[
					"blocked",
					{
						account_id: "blocked",
						status: "active",
						restart_warmup_status: "none",
						restart_warmup_allowed_posts_per_day: null,
					},
				],
			]),
			scheduleByAccount: new Map([
				["ready", { account_id: "ready", posts_per_day: 2, status: "active" }],
				[
					"cooldown",
					{ account_id: "cooldown", posts_per_day: 10, status: "view_cooldown" },
				],
				[
					"paused",
					{ account_id: "paused", posts_per_day: 10, paused: true },
				],
				[
					"blocked",
					{
						account_id: "blocked",
						posts_per_day: 10,
						status: "active",
						blocked_until: new Date(Date.now() + 60_000).toISOString(),
					},
				],
			]),
		});

		expect(threshold).toBe(3);
		expect(lowQueueWarningWatermark(threshold)).toBe(2);
	});

	it("lets performance suppression override warm-up demand", () => {
		const threshold = calculateDemandAwareQueueThreshold({
			configuredThreshold: 20,
			groupDailyCap: 2,
			accountIds: ["suppressed-warmup", "reduced-warmup", "clone-warmup"],
			stateByAccount: new Map([
				[
					"suppressed-warmup",
					{
						account_id: "suppressed-warmup",
						status: "active",
						restart_warmup_status: "warming",
						restart_warmup_allowed_posts_per_day: 2,
						recommended_strategy_mode: "suppress",
						recommended_posts_per_day: 0,
					},
				],
				[
					"reduced-warmup",
					{
						account_id: "reduced-warmup",
						status: "active",
						restart_warmup_status: "warming",
						restart_warmup_allowed_posts_per_day: 2,
						recommended_strategy_mode: "reduce",
						recommended_posts_per_day: 1,
					},
				],
				[
					"clone-warmup",
					{
						account_id: "clone-warmup",
						status: "active",
						restart_warmup_status: "warming",
						restart_warmup_allowed_posts_per_day: 2,
						recommended_strategy_mode: "clone_winners",
						recommended_posts_per_day: 2,
					},
				],
			]),
		});

		expect(threshold).toBe(3);
		expect(lowQueueWarningWatermark(threshold)).toBe(2);
	});

	it("does not count suppressed accounts toward queue demand", () => {
		const threshold = calculateDemandAwareQueueThreshold({
			configuredThreshold: 20,
			groupDailyCap: 2,
			accountIds: ["active", "suppressed"],
			stateByAccount: new Map([
				[
					"active",
					{
						account_id: "active",
						status: "active",
						restart_warmup_status: "warming",
						restart_warmup_allowed_posts_per_day: 1,
					},
				],
				[
					"suppressed",
					{
						account_id: "suppressed",
						status: "suppressed",
						restart_warmup_status: "suppressed",
						restart_warmup_allowed_posts_per_day: 0,
					},
				],
			]),
		});

		expect(threshold).toBe(3);
	});
});
