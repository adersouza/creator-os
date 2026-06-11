import { describe, expect, it } from "vitest";
import type { TopPostRow } from "@/hooks/useTopPosts";
import {
	buildContentOperations,
	discoveryScore,
	engagementTotal,
	formatCompact,
} from "@/lib/contentOperations";

function post(overrides: Partial<TopPostRow>): TopPostRow {
	return {
		id: "post-1",
		platform: "threads",
		caption: "A post",
		mediaUrl: null,
		accountId: "acct-1",
		accountHandle: "juno",
		groupId: "group-1",
		groupName: "Group",
		groupColor: "#000000",
		reach: 0,
		sends: 0,
		saves: 0,
		likes: 0,
		comments: 0,
		publishedAt: "2026-06-01T12:00:00.000Z",
		...overrides,
	};
}

describe("contentOperations", () => {
	it("scores platform discovery using the correct interaction mix", () => {
		expect(discoveryScore(post({ platform: "threads", sends: 3, comments: 7, saves: 50 }))).toBe(10);
		expect(discoveryScore(post({ platform: "instagram", sends: 3, comments: 7, saves: 50 }))).toBe(53);
	});

	it("builds operator signals from the loaded content rows", () => {
		const operations = buildContentOperations([
			post({
				id: "low",
				reach: 20,
				likes: 1,
				comments: 1,
				sends: 0,
				publishedAt: "2026-06-03T12:00:00.000Z",
			}),
			post({
				id: "threads-win",
				reach: 1_000,
				likes: 10,
				comments: 30,
				sends: 20,
				publishedAt: "2026-06-02T12:00:00.000Z",
			}),
			post({
				id: "ig-win",
				platform: "instagram",
				reach: 2_000,
				likes: 20,
				comments: 10,
				sends: 40,
				saves: 25,
				publishedAt: "2026-06-01T12:00:00.000Z",
			}),
		]);

		expect(operations.topPost?.id).toBe("ig-win");
		expect(operations.winningPosts.map((item) => item.id)).toEqual(["ig-win", "threads-win", "low"]);
		expect(operations.reviewPosts.map((item) => item.id)).toEqual(["low"]);
		expect(operations.lowReachCount).toBe(1);
		expect(operations.recentPosts.map((item) => item.id)).toEqual(["low", "threads-win", "ig-win"]);
		expect(operations.platformBreakdown).toEqual([
			{ label: "Threads", count: 2 },
			{ label: "Instagram", count: 1 },
		]);
		expect(operations.totalReach).toBe(3_020);
		expect(operations.totalDiscovery).toBe(116);
		expect(operations.totalEngagement).toBe(157);
	});

	it("keeps empty content readable", () => {
		const operations = buildContentOperations([]);

		expect(operations.topPost).toBeNull();
		expect(operations.reviewPosts).toEqual([]);
		expect(operations.reviewThreshold).toBe(100);
		expect(formatCompact(1_250)).toBe("1.3K");
		expect(engagementTotal(post({ likes: 1, comments: 2, sends: 3, saves: 4 }))).toBe(10);
	});
});
