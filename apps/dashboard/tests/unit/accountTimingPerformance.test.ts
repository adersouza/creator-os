import { describe, expect, it } from "vitest";
import { buildAccountHourPerformanceBuckets } from "../../api/_lib/handlers/auto-post/accountTimingPerformance";

describe("buildAccountHourPerformanceBuckets", () => {
	it("builds account hour buckets from Threads performance facts", () => {
		const now = new Date("2026-06-06T12:00:00Z");
		const facts = Array.from({ length: 12 }, (_, index) => ({
			workspace_id: "ws-1",
			group_id: "group-1",
			account_id: "acc-1",
			posting_hour: index < 6 ? 11 : 20,
			published_at: new Date(now.getTime() - index * 86_400_000).toISOString(),
			views_24h: index < 6 ? 80 : 20,
			replies_24h: index < 6 ? 3 : 0,
			profile_clicks_proxy: 0,
		}));

		const buckets = buildAccountHourPerformanceBuckets({
			workspaceId: "ws-1",
			groupId: "group-1",
			facts,
			now,
		});

		const hour11 = buckets.find((bucket) => bucket.hour === 11);
		const hour20 = buckets.find((bucket) => bucket.hour === 20);
		expect(hour11).toMatchObject({
			account_id: "acc-1",
			posts_count: 6,
			fallback_source: "account_learned",
		});
		expect(hour11!.weighted_score).toBeGreaterThan(hour20!.weighted_score);
		expect(hour11!.confidence).toBeGreaterThan(0);
	});

	it("smooths one viral post instead of letting it dominate the whole account", () => {
		const now = new Date("2026-06-06T12:00:00Z");
		const facts = [
			{
				workspace_id: "ws-1",
				group_id: "group-1",
				account_id: "acc-1",
				posting_hour: 23,
				published_at: now.toISOString(),
				views_24h: 5000,
				replies_24h: 20,
			},
			...Array.from({ length: 16 }, (_, index) => ({
				workspace_id: "ws-1",
				group_id: "group-1",
				account_id: "acc-1",
				posting_hour: 11,
				published_at: new Date(
					now.getTime() - (index + 1) * 86_400_000,
				).toISOString(),
				views_24h: 60,
				replies_24h: 2,
			})),
		];

		const buckets = buildAccountHourPerformanceBuckets({
			workspaceId: "ws-1",
			groupId: "group-1",
			facts,
			now,
		});
		const viralHour = buckets.find((bucket) => bucket.hour === 23);
		const steadyHour = buckets.find((bucket) => bucket.hour === 11);

		expect(viralHour!.posts_count).toBe(1);
		expect(viralHour!.confidence).toBeLessThan(steadyHour!.confidence);
		expect(viralHour!.fallback_source).toBe("account_sparse");
	});

	it("marks sparse accounts as sparse even when an hour has data", () => {
		const now = new Date("2026-06-06T12:00:00Z");
		const buckets = buildAccountHourPerformanceBuckets({
			workspaceId: "ws-1",
			groupId: "group-1",
			now,
			facts: [
				{
					account_id: "acc-1",
					posting_hour: 11,
					published_at: now.toISOString(),
					views_24h: 100,
				},
				{
					account_id: "acc-1",
					posting_hour: 11,
					published_at: new Date(now.getTime() - 86_400_000).toISOString(),
					views_24h: 80,
				},
			],
		});

		expect(buckets[0]).toMatchObject({
			fallback_source: "account_sparse",
		});
		expect(buckets[0]!.confidence).toBeLessThan(0.2);
	});
});
