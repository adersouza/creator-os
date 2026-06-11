import { describe, expect, it } from "vitest";
import { queryKeys } from "./queryKeys";

describe("queryKeys", () => {
	it("keeps account cache prefixes aligned with scoped account reads", () => {
		expect(queryKeys.accounts.connectedAll).toEqual(["connectedAccounts"]);
		expect(queryKeys.accounts.connected("user-1")).toEqual([
			"connectedAccounts",
			"v2",
			"user-1",
		]);
		expect(queryKeys.accounts.groupsAll).toEqual(["accountGroups"]);
		expect(queryKeys.accounts.groups("user-1")).toEqual([
			"accountGroups",
			"user-1",
		]);
	});

	it("keeps calendar prefix invalidation compatible with week-span reads", () => {
		expect(queryKeys.calendar.all).toEqual(["calendarPosts"]);
		expect(queryKeys.calendar.userPosts("user-1")).toEqual([
			"calendarPosts",
			"user-1",
		]);
		expect(queryKeys.calendar.posts("user-1", 1_771_459_200_000, 2)).toEqual([
			"calendarPosts",
			"user-1",
			1_771_459_200_000,
			2,
		]);
	});

	it("keeps listening and operator snapshot prefixes available for mutations", () => {
		expect(queryKeys.listening.snapshotAll).toEqual(["listeningSnapshot"]);
		expect(queryKeys.listening.snapshot("user-1", "workspace-1")).toEqual([
			"listeningSnapshot",
			"user-1",
			"workspace-1",
		]);
		expect(queryKeys.operator.snapshotAll).toEqual(["operatorSnapshot"]);
		expect(queryKeys.operator.snapshot("user-1", "2026-06-08")).toEqual([
			"operatorSnapshot",
			"user-1",
			"2026-06-08",
		]);
	});

	it("keeps simple system and fleet keys centralized", () => {
		expect(queryKeys.fleet.totals("user-1")).toEqual([
			"fleetTotals",
			"user-1",
		]);
		expect(queryKeys.fleet.profileVisits("user-1", 7)).toEqual([
			"fleetProfileVisits",
			"user-1",
			7,
		]);
		expect(queryKeys.system.trialStatus("user-1")).toEqual([
			"trialStatus",
			"user-1",
		]);
		expect(queryKeys.system.reliabilitySummary(24)).toEqual([
			"reliabilitySummary",
			24,
		]);
		expect(queryKeys.system.instagramPublishingLimits("user-1")).toEqual([
			"instagramPublishingLimits",
			"user-1",
		]);
	});

	it("keeps routine analytics singleton keys centralized", () => {
		expect(queryKeys.analytics.bestPostingTimes("user-1", null)).toEqual([
			"bestPostingTimes",
			"user-1",
			null,
		]);
		expect(queryKeys.analytics.competitorPulse("user-1")).toEqual([
			"competitorPulse",
			"user-1",
		]);
		expect(queryKeys.analytics.competitorSurprises("user-1")).toEqual([
			"competitorSurprises",
			"user-1",
		]);
		expect(queryKeys.analytics.crossAccountPatterns("user-1")).toEqual([
			"crossAccountPatterns",
			"user-1",
		]);
		expect(queryKeys.analytics.eqsTrendSubtitle("cache-key")).toEqual([
			"eqsTrendSubtitle",
			"cache-key",
		]);
		expect(queryKeys.analytics.hookPatterns("user-1", "acct-1")).toEqual([
			"hookPatterns",
			"user-1",
			"acct-1",
		]);
		expect(queryKeys.analytics.reelRetention("user-1", 30, null)).toEqual([
			"reelRetention",
			"user-1",
			30,
			null,
		]);
	});
});
