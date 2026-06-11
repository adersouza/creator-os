import { describe, expect, it } from "vitest";
import {
	evaluateRestartWarmup,
	restartWarmupPolicyFromState,
} from "../../api/_lib/handlers/auto-post/restartWarmup";
import { nudgeScheduleToRestartWarmupPrimaryHour } from "../../api/_lib/handlers/auto-post/scheduleAndInsert";

const now = new Date("2026-06-06T16:00:00.000Z");

describe("restart warm-up policy", () => {
	it("enters day 1 warm-up after 48h inactivity with text-only primary-hour policy", () => {
		const result = evaluateRestartWarmup({
			now,
			accountId: "acct-1",
			healthScore: 100,
			lastAutoposterPublishedAt: "2026-06-04T15:59:59.000Z",
			recentWarmupViews: [],
		});

		expect(result.status).toBe("warming");
		expect(result.day).toBe(1);
		expect(result.allowedPostsPerDay).toBe(1);
		expect(result.textOnly).toBe(true);
		expect(result.mediaChanceCap).toBe(0);
		expect(result.primaryHoursOnly).toBe(true);
		expect(result.directMicrocopyAllowed).toBe(false);
		expect(result.genericQuestionCap).toBe(0);
	});

	it("does not enter restart warm-up when recent autoposter activity exists", () => {
		const result = evaluateRestartWarmup({
			now,
			accountId: "acct-1",
			healthScore: 100,
			lastAutoposterPublishedAt: "2026-06-06T10:00:00.000Z",
			recentWarmupViews: [30],
		});

		expect(result.status).toBe("none");
		expect(result.allowedPostsPerDay).toBeNull();
		expect(result.textOnly).toBe(false);
	});

	it("ramps day 3 to two posts when previous warm-up is healthy", () => {
		const result = evaluateRestartWarmup({
			now,
			accountId: "acct-2",
			healthScore: 90,
			previous: {
				restart_warmup_status: "warming",
				restart_warmup_started_at: "2026-06-04T16:00:00.000Z",
			},
			lastAutoposterPublishedAt: "2026-06-06T12:00:00.000Z",
			recentWarmupViews: [55, 21],
		});

		expect(result.status).toBe("warming");
		expect(result.day).toBe(3);
		expect(result.allowedPostsPerDay).toBe(2);
		expect(result.textOnly).toBe(false);
		expect(result.mediaChanceCap).toBe(10);
	});

	it("holds at one post per day after repeated near-zero views", () => {
		const result = evaluateRestartWarmup({
			now,
			accountId: "acct-3",
			healthScore: 95,
			previous: {
				restart_warmup_status: "warming",
				restart_warmup_started_at: "2026-06-02T16:00:00.000Z",
			},
			recentWarmupViews: [2, 4, 3],
		});

		expect(result.status).toBe("held");
		expect(result.allowedPostsPerDay).toBe(1);
		expect(result.reason).toContain("near_zero_views_avg");
		expect(result.textOnly).toBe(true);
	});

	it("suppresses/skips warm-up when health drops below 40", () => {
		const result = evaluateRestartWarmup({
			now,
			accountId: "acct-4",
			healthScore: 35,
			previous: {
				restart_warmup_status: "warming",
				restart_warmup_started_at: "2026-06-05T16:00:00.000Z",
			},
			recentWarmupViews: [80],
		});

		expect(result.status).toBe("suppressed");
		expect(result.allowedPostsPerDay).toBe(0);
		expect(result.shouldSkipToday).toBe(true);
	});

	it("keeps suppressed-probe accounts in a one-post warm-up lane despite low health", () => {
		const result = evaluateRestartWarmup({
			now,
			accountId: "acct-probe",
			healthScore: 0,
			isProbeMode: true,
			previous: {
				restart_warmup_status: "suppressed",
				restart_warmup_started_at: "2026-06-05T16:00:00.000Z",
			},
			recentWarmupViews: [1, 2, 3],
		});

		expect(result.status).toBe("warming");
		expect(result.allowedPostsPerDay).toBe(1);
		expect(result.reason).toBe("suppressed_probe_active");
		expect(result.shouldSkipToday).toBe(false);
	});

	it("completes after day 7 when recent views are decent", () => {
		const result = evaluateRestartWarmup({
			now,
			accountId: "acct-5",
			healthScore: 100,
			previous: {
				restart_warmup_status: "warming",
				restart_warmup_started_at: "2026-05-29T16:00:00.000Z",
			},
			recentWarmupViews: [45, 30, 20],
		});

		expect(result.status).toBe("completed");
		expect(result.allowedPostsPerDay).toBeNull();
		expect(result.reason).toBe("completed_after_decent_views");
	});

	it("hydrates planner policy from persisted state", () => {
		const policy = restartWarmupPolicyFromState({
			restart_warmup_status: "warming",
			restart_warmup_day: 2,
			restart_warmup_allowed_posts_per_day: 1,
			restart_warmup_reason: "restart_warmup_day_2",
			restart_warmup_last_post_views: 42,
		});

		expect(policy?.allowedPostsPerDay).toBe(1);
		expect(policy?.directMicrocopyAllowed).toBe(true);
		expect(policy?.directMicrocopyCapPercent).toBe(5);
		expect(policy?.genericQuestionCap).toBe(0);
	});

	it("nudges restart warm-up times toward primary performance hours", () => {
		const nudged = nudgeScheduleToRestartWarmupPrimaryHour(
			"2026-06-06T18:00:00.000Z",
			"UTC",
			"acct-6",
		);
		const hour = new Date(nudged).getUTCHours();
		expect([6, 7, 11, 12, 13]).toContain(hour);
	});
});
