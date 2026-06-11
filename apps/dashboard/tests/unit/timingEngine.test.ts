import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
	calculateAccountAwareNaturalPostTimes,
	calculateNaturalPostTimes,
} from "../../api/_lib/handlers/auto-post/timingEngine";
import type { AutoPostConfig } from "../../api/_lib/handlers/auto-post/types";

vi.mock("../../api/_lib/supabase", () => ({
	getSupabaseAny: () => ({ from: vi.fn() }),
}));

vi.mock("../../api/_lib/logger", () => ({
	logger: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
}));

const config = {
	workspace_id: "ws-1",
	is_enabled: true,
	platform: "threads",
	posting_times: { media_chance: 0.3, timezone: "America/Los_Angeles" },
	pause_on_low_performance: false,
	performance_threshold: 0.5,
} satisfies AutoPostConfig;

function localHour(iso: string, timezone: string): number {
	return Number(
		new Intl.DateTimeFormat("en-US", {
			timeZone: timezone,
			hour: "2-digit",
			hourCycle: "h23",
		}).format(new Date(iso)),
	);
}

describe("calculateNaturalPostTimes", () => {
	beforeEach(() => {
		vi.useFakeTimers();
		vi.setSystemTime(new Date("2026-05-13T12:00:00.000Z"));
		vi.spyOn(Math, "random").mockReturnValue(0.5);
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.restoreAllMocks();
	});

	it("schedules learned hours in the configured timezone", () => {
		const times = calculateNaturalPostTimes(
			1,
			config,
			undefined,
			1,
			{
				bestPostingHours: [9],
				timezone: "America/Los_Angeles",
				activeHoursStart: 8,
				activeHoursEnd: 17,
			},
			"threads",
		);

		expect(times).toHaveLength(1);
		expect(localHour(times[0]!, "America/Los_Angeles")).toBe(9);
	});

	it("keeps fallback random scheduling inside the active window", () => {
		const times = calculateNaturalPostTimes(
			3,
			config,
			undefined,
			1,
			{
				timezone: "America/Los_Angeles",
				activeHoursStart: 9,
				activeHoursEnd: 10,
			},
			"threads",
		);

		expect(times).toHaveLength(3);
		for (const time of times) {
			expect(localHour(time, "America/Los_Angeles")).toBe(9);
		}
	});

	it("returns exactly the requested number of times on Tuesdays", () => {
		vi.setSystemTime(new Date("2026-05-12T12:00:00.000Z"));

		const times = calculateNaturalPostTimes(
			2,
			config,
			undefined,
			1,
			{
				bestPostingHours: [9],
				timezone: "America/Los_Angeles",
				activeHoursStart: 8,
				activeHoursEnd: 17,
			},
			"threads",
		);

		expect(times).toHaveLength(2);
	});
});

describe("calculateAccountAwareNaturalPostTimes", () => {
	beforeEach(() => {
		vi.useFakeTimers();
		vi.setSystemTime(new Date("2026-05-13T12:00:00.000Z"));
		vi.spyOn(Math, "random").mockReturnValue(0.2);
	});

	afterEach(() => {
		vi.useRealTimers();
		vi.restoreAllMocks();
	});

	it("uses account proven hours when the profile has enough samples", () => {
		const times = calculateAccountAwareNaturalPostTimes({
			plannedSlots: [
				{
					accountId: "acc-1",
					timezone: "America/Los_Angeles",
					activeHoursStart: 8,
					activeHoursEnd: 22,
					minIntervalMinutes: 180,
				},
			],
			config,
			insights: {
				timezone: "America/Los_Angeles",
				activeHoursStart: 8,
				activeHoursEnd: 22,
			},
			platform: "threads",
			accountProfiles: new Map([
				[
					"acc-1",
					{
						accountId: "acc-1",
						provenHours: [
							{
								hour: 20,
								postsCount: 5,
								effectiveSampleSize: 4,
								avgViews24h: 120,
								medianViews24h: 80,
								above100Rate: 0.4,
								avgReplies24h: 2,
								profileClicksProxy: 0,
								weightedScore: 99,
								confidence: 0.8,
								fallbackSource: "account_learned",
								lastSeenAt: null,
							},
						],
						explorationHours: [],
						allHours: [],
						confidence: 0.8,
						sampleSize: 18,
						fallbackSource: "account_learned",
					},
				],
			]),
		});

		expect(times[0]!.timing.timingReason).toBe("account_proven_hour");
		expect(localHour(times[0]!.scheduledFor, "America/Los_Angeles")).toBe(20);
	});

	it("falls back to global hours for sparse account data", () => {
		const times = calculateAccountAwareNaturalPostTimes({
			plannedSlots: [
				{
					accountId: "acc-1",
					timezone: "America/New_York",
					activeHoursStart: 6,
					activeHoursEnd: 14,
				},
			],
			config,
			insights: {
				timezone: "America/New_York",
				activeHoursStart: 6,
				activeHoursEnd: 14,
			},
			platform: "threads",
			accountProfiles: new Map([
				[
					"acc-1",
					{
						accountId: "acc-1",
						provenHours: [],
						explorationHours: [],
						allHours: [],
						confidence: 0.1,
						sampleSize: 2,
						fallbackSource: "account_sparse",
					},
				],
			]),
		});

		expect(times[0]!.timing.timingReason).toBe("global_fallback_hour");
		expect([6, 7, 11, 12, 13]).toContain(
			localHour(times[0]!.scheduledFor, "America/New_York"),
		);
	});

	it("keeps warm-up day one on primary hours even with learned data", () => {
		const times = calculateAccountAwareNaturalPostTimes({
			plannedSlots: [
				{
					accountId: "acc-1",
					timezone: "America/New_York",
					activeHoursStart: 0,
					activeHoursEnd: 24,
					warmupPolicy: { primaryHoursOnly: true, day: 1, status: "warming" },
				},
			],
			config,
			insights: { timezone: "America/New_York", activeHoursStart: 0, activeHoursEnd: 24 },
			platform: "threads",
			accountProfiles: new Map([
				[
					"acc-1",
					{
						accountId: "acc-1",
						provenHours: [
							{
								hour: 23,
								postsCount: 8,
								effectiveSampleSize: 8,
								avgViews24h: 200,
								medianViews24h: 120,
								above100Rate: 0.8,
								avgReplies24h: 5,
								profileClicksProxy: 0,
								weightedScore: 200,
								confidence: 0.9,
								fallbackSource: "account_learned",
								lastSeenAt: null,
							},
						],
						explorationHours: [],
						allHours: [],
						confidence: 0.9,
						sampleSize: 30,
						fallbackSource: "account_learned",
					},
				],
			]),
		});

		expect(times[0]!.timing.timingReason).toBe("warmup_primary_hour");
		expect([6, 7, 11, 12, 13]).toContain(
			localHour(times[0]!.scheduledFor, "America/New_York"),
		);
	});

	it("respects account active windows even when learned hours are outside", () => {
		const times = calculateAccountAwareNaturalPostTimes({
			plannedSlots: [
				{
					accountId: "acc-1",
					timezone: "America/New_York",
					activeHoursStart: 9,
					activeHoursEnd: 10,
				},
			],
			config,
			insights: { timezone: "America/New_York", activeHoursStart: 9, activeHoursEnd: 10 },
			platform: "threads",
			accountProfiles: new Map([
				[
					"acc-1",
					{
						accountId: "acc-1",
						provenHours: [
							{
								hour: 20,
								postsCount: 5,
								effectiveSampleSize: 5,
								avgViews24h: 100,
								medianViews24h: 100,
								above100Rate: 0.5,
								avgReplies24h: 2,
								profileClicksProxy: 0,
								weightedScore: 100,
								confidence: 0.8,
								fallbackSource: "account_learned",
								lastSeenAt: null,
							},
						],
						explorationHours: [],
						allHours: [],
						confidence: 0.8,
						sampleSize: 20,
						fallbackSource: "account_learned",
					},
				],
			]),
		});

		expect(localHour(times[0]!.scheduledFor, "America/New_York")).toBe(9);
	});

	it("applies min interval and jitter for repeated account slots", () => {
		const times = calculateAccountAwareNaturalPostTimes({
			plannedSlots: [
				{
					accountId: "acc-1",
					timezone: "America/New_York",
					activeHoursStart: 0,
					activeHoursEnd: 24,
					minIntervalMinutes: 180,
				},
				{
					accountId: "acc-1",
					timezone: "America/New_York",
					activeHoursStart: 0,
					activeHoursEnd: 24,
					minIntervalMinutes: 180,
				},
			],
			config,
			insights: { timezone: "America/New_York", activeHoursStart: 0, activeHoursEnd: 24 },
			platform: "threads",
		});

		const gap =
			new Date(times[1]!.scheduledFor).getTime() -
			new Date(times[0]!.scheduledFor).getTime();
		expect(gap).toBeGreaterThanOrEqual(180 * 60_000);
		expect(times[0]!.scheduledFor).not.toEqual(times[1]!.scheduledFor);
	});
});
