import { describe, expect, it } from "vitest";
import {
	countUsedPostingCapacityForAccount,
	deriveEffectivePostingCap,
	planStaleWarmupReadyRowCleanup,
} from "../../api/_lib/handlers/auto-post/warmupCapacity";

describe("warmupCapacity", () => {
	it("derives cap zero for suppressed restart warm-up accounts", () => {
		expect(
			deriveEffectivePostingCap({
				restart_warmup_status: "suppressed",
				restart_warmup_allowed_posts_per_day: 2,
				account_health_score: 100,
			}),
		).toMatchObject({ cap: 0, reason: "suppressed_cap_zero" });
	});

	it("allows explicit suppressed-probe accounts to re-enter at one post per day", () => {
		expect(
			deriveEffectivePostingCap({
				status: "suppressed_probe",
				restart_warmup_status: "suppressed",
				restart_warmup_allowed_posts_per_day: 0,
				recommended_strategy_mode: "suppress",
				account_health_score: 0,
			}),
		).toMatchObject({ cap: 1, reason: "suppressed_probe_cap" });
	});

	it("keeps held accounts on their explicit cap", () => {
		expect(
			deriveEffectivePostingCap({
				restart_warmup_status: "held",
				restart_warmup_allowed_posts_per_day: 1,
				account_health_score: 100,
			}),
		).toMatchObject({ cap: 1, reason: "held_cap" });
	});

	it("counts published, publishing, queued, pending, retry, and pool-planned rows for the account local day", () => {
		const now = new Date("2026-06-08T16:00:00.000Z");
		const rows = [
			{
				id: "published",
				account_id: "acc-1",
				status: "published",
				posted_at: "2026-06-08T15:00:00.000Z",
			},
			{
				id: "publishing",
				account_id: "acc-1",
				status: "publishing",
				scheduled_for: "2026-06-08T16:30:00.000Z",
			},
			{
				id: "queued",
				account_id: "acc-1",
				status: "queued",
				scheduled_for: "2026-06-08T17:30:00.000Z",
			},
			{
				id: "retry",
				account_id: "acc-1",
				status: "pending",
				next_retry_at: "2026-06-08T18:30:00.000Z",
			},
			{
				id: "pool-planned",
				account_id: null,
				status: "pending",
				scheduled_for: "2026-06-08T19:30:00.000Z",
				metadata: { planned_account: { accountId: "acc-1" } },
			},
			{
				id: "review",
				account_id: "acc-1",
				status: "needs_review",
				scheduled_for: "2026-06-08T20:30:00.000Z",
			},
			{
				id: "old",
				account_id: "acc-1",
				status: "published",
				posted_at: "2026-06-07T15:00:00.000Z",
			},
		];

		expect(
			countUsedPostingCapacityForAccount({
				accountId: "acc-1",
				timezone: "America/New_York",
				now,
				rows,
			}),
		).toBe(5);
	});

	it("excludes the current queue item when checking publish-time capacity", () => {
		const now = new Date("2026-06-08T16:00:00.000Z");
		const rows = [
			{
				id: "current",
				account_id: "acc-1",
				status: "queued",
				scheduled_for: "2026-06-08T16:00:00.000Z",
			},
		];

		expect(
			countUsedPostingCapacityForAccount({
				accountId: "acc-1",
				timezone: "America/New_York",
				now,
				rows,
				excludeQueueItemId: "current",
			}),
		).toBe(0);
	});

	it("cleans old ready rows when a warming account is now suppressed", () => {
		const now = new Date("2026-06-08T16:00:00.000Z");
		const result = planStaleWarmupReadyRowCleanup({
			now,
			accounts: new Map([
				[
					"acc-1",
					{
						timezone: "America/New_York",
						state: {
							restart_warmup_status: "suppressed",
							restart_warmup_allowed_posts_per_day: 0,
							account_health_score: 35,
						},
					},
				],
			]),
			rows: [
				{
					id: "ready-old",
					account_id: null,
					status: "pending",
					scheduled_for: "2026-06-08T18:00:00.000Z",
					metadata: {
						restart_warmup: { status: "warming", day: 2 },
						planned_account: { accountId: "acc-1" },
					},
				},
			],
		});

		expect(result.toNeedsReview).toHaveLength(1);
		expect(result.toNeedsReview[0]).toMatchObject({
			id: "ready-old",
			reason: "stale_warmup_state_suppressed",
			cap: 0,
			usedCount: 0,
			localDay: "2026-06-08",
			timezone: "America/New_York",
		});
	});

	it("keeps the earliest held-cap row and cleans later excess rows for the local day", () => {
		const now = new Date("2026-06-08T16:00:00.000Z");
		const result = planStaleWarmupReadyRowCleanup({
			now,
			accounts: new Map([
				[
					"acc-1",
					{
						timezone: "America/New_York",
						state: {
							restart_warmup_status: "held",
							restart_warmup_allowed_posts_per_day: 1,
							account_health_score: 80,
						},
					},
				],
			]),
			rows: [
				{
					id: "later",
					account_id: null,
					status: "queued",
					scheduled_for: "2026-06-08T20:00:00.000Z",
					metadata: { planned_account: { accountId: "acc-1" } },
				},
				{
					id: "earlier",
					account_id: null,
					status: "pending",
					scheduled_for: "2026-06-08T18:00:00.000Z",
					metadata: { planned_account: { accountId: "acc-1" } },
				},
			],
		});

		expect(result.keptIds).toEqual(["earlier"]);
		expect(result.toNeedsReview.map((row) => row.id)).toEqual(["later"]);
		expect(result.toNeedsReview[0]).toMatchObject({
			reason: "stale_warmup_cap_exceeded",
			cap: 1,
			usedCount: 1,
			localDay: "2026-06-08",
		});
	});

	it("counts published rows before cleaning excess warming rows", () => {
		const now = new Date("2026-06-08T16:00:00.000Z");
		const result = planStaleWarmupReadyRowCleanup({
			now,
			accounts: new Map([
				[
					"acc-1",
					{
						timezone: "America/New_York",
						state: {
							restart_warmup_status: "warming",
							restart_warmup_allowed_posts_per_day: 2,
							account_health_score: 80,
						},
					},
				],
			]),
			rows: [
				{
					id: "published",
					account_id: "acc-1",
					status: "published",
					posted_at: "2026-06-08T14:00:00.000Z",
				},
				{
					id: "ready-1",
					account_id: "acc-1",
					status: "pending",
					scheduled_for: "2026-06-08T18:00:00.000Z",
				},
				{
					id: "ready-2",
					account_id: "acc-1",
					status: "queued",
					scheduled_for: "2026-06-08T20:00:00.000Z",
				},
			],
		});

		expect(result.keptIds).toEqual(["ready-1"]);
		expect(result.toNeedsReview.map((row) => row.id)).toEqual(["ready-2"]);
	});

	it("does not touch terminal or review rows", () => {
		const now = new Date("2026-06-08T16:00:00.000Z");
		const result = planStaleWarmupReadyRowCleanup({
			now,
			accounts: new Map([
				[
					"acc-1",
					{
						timezone: "America/New_York",
						state: {
							restart_warmup_status: "suppressed",
							restart_warmup_allowed_posts_per_day: 0,
						},
					},
				],
			]),
			rows: [
				{
					id: "review",
					account_id: "acc-1",
					status: "needs_review",
					scheduled_for: "2026-06-08T18:00:00.000Z",
				},
				{
					id: "cancelled",
					account_id: "acc-1",
					status: "cancelled",
					scheduled_for: "2026-06-08T19:00:00.000Z",
				},
			],
		});

		expect(result.toNeedsReview).toHaveLength(0);
		expect(result.keptIds).toHaveLength(0);
	});

	it("cleans later ready rows that violate the account min interval", () => {
		const result = planStaleWarmupReadyRowCleanup({
			accounts: new Map([
				[
					"acc-1",
					{
						timezone: "America/New_York",
						minIntervalMinutes: 180,
						state: {
							restart_warmup_status: "completed",
							account_health_score: 90,
						},
					},
				],
			]),
			rows: [
				{
					id: "first",
					account_id: "acc-1",
					status: "queued",
					scheduled_for: "2026-06-10T06:02:00.000Z",
				},
				{
					id: "too-soon",
					account_id: null,
					status: "pending",
					scheduled_for: "2026-06-10T06:12:00.000Z",
					metadata: { planned_account: { accountId: "acc-1" } },
				},
				{
					id: "safe",
					account_id: "acc-1",
					status: "queued",
					scheduled_for: "2026-06-10T09:20:00.000Z",
				},
			],
		});

		expect(result.toNeedsReview).toHaveLength(1);
		expect(result.toNeedsReview[0]).toMatchObject({
			id: "too-soon",
			reason: "stale_min_interval_conflict",
			minIntervalMinutes: 180,
			previousReadyRowId: "first",
			gapMinutes: 10,
		});
	});

	it("does not let cap-cleaned rows participate in min interval cleanup", () => {
		const result = planStaleWarmupReadyRowCleanup({
			accounts: new Map([
				[
					"acc-1",
					{
						timezone: "America/New_York",
						minIntervalMinutes: 180,
						state: {
							restart_warmup_status: "held",
							restart_warmup_allowed_posts_per_day: 1,
							account_health_score: 90,
						},
					},
				],
			]),
			rows: [
				{
					id: "first",
					account_id: "acc-1",
					status: "queued",
					scheduled_for: "2026-06-10T06:02:00.000Z",
				},
				{
					id: "cap-excess",
					account_id: "acc-1",
					status: "queued",
					scheduled_for: "2026-06-10T06:12:00.000Z",
				},
			],
		});

		expect(result.toNeedsReview).toHaveLength(1);
		expect(result.toNeedsReview[0]).toMatchObject({
			id: "cap-excess",
			reason: "stale_warmup_cap_exceeded",
		});
	});
});
