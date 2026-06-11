import { describe, expect, it } from "vitest";
import {
	aggregateRowsForSpec,
	buildSystemPrompt,
	coerceSpec,
	METRIC_REGISTRY,
} from "@/api/_lib/handlers/ai/nl-query";
import {
	COPILOT_GROUNDING_RULES,
	detectIntent,
} from "@/api/_lib/handlers/ai/copilot";

const metricKeys = new Set(METRIC_REGISTRY.map((metric) => metric.key));

const nlQueryGoldens = [
	{ q: "Which accounts got the most views this month?", raw: { metric: "totalViews", timeframeDays: 30, platform: "all", groupBy: "account", limit: 10, orderBy: "desc" }, expect: { metric: "totalViews", platform: "all", groupBy: "account" } },
	{ q: "Show IG saves by account for the last 14 days", raw: { metric: "totalIgSaved", timeframeDays: 14, platform: "instagram", groupBy: "account", limit: 20, orderBy: "desc" }, expect: { metric: "totalIgSaved", platform: "instagram", groupBy: "account" } },
	{ q: "What are my Threads repost leaders?", raw: { metric: "totalReposts", timeframeDays: 30, platform: "threads", groupBy: "account", limit: 10, orderBy: "desc" }, expect: { metric: "totalReposts", platform: "threads", groupBy: "account" } },
	{ q: "Daily follower trend across the fleet", raw: { metric: "totalFollowers", timeframeDays: 60, platform: "all", groupBy: "day", limit: 50, orderBy: "desc" }, expect: { metric: "totalFollowers", platform: "all", groupBy: "day" } },
	{ q: "Which accounts have the lowest profile clicks?", raw: { metric: "totalClicks", timeframeDays: 30, platform: "threads", groupBy: "account", limit: 10, orderBy: "asc" }, expect: { metric: "totalClicks", platform: "threads", groupBy: "account", orderBy: "asc" } },
	{ q: "Total Instagram profile visits", raw: { metric: "igProfileViews", timeframeDays: 30, platform: "instagram", groupBy: "none", limit: 1, orderBy: "desc" }, expect: { metric: "igProfileViews", platform: "instagram", groupBy: "none" } },
	{ q: "Compare IG website clicks by account", raw: { metric: "igWebsiteClicks", timeframeDays: 30, platform: "instagram", groupBy: "account", limit: 15, orderBy: "desc" }, expect: { metric: "igWebsiteClicks", platform: "instagram", groupBy: "account" } },
	{ q: "Where is non-follower reach strongest?", raw: { metric: "igNonFollowerReachPct", timeframeDays: 30, platform: "instagram", groupBy: "account", limit: 10, orderBy: "desc" }, expect: { metric: "igNonFollowerReachPct", platform: "instagram", groupBy: "account" } },
	{ q: "Show new follows over time", raw: { metric: "igNewFollows", timeframeDays: 30, platform: "instagram", groupBy: "day", limit: 30, orderBy: "desc" }, expect: { metric: "igNewFollows", platform: "instagram", groupBy: "day" } },
	{ q: "Which accounts are losing followers?", raw: { metric: "igUnfollows", timeframeDays: 30, platform: "instagram", groupBy: "account", limit: 10, orderBy: "desc" }, expect: { metric: "igUnfollows", platform: "instagram", groupBy: "account" } },
	{ q: "Accounts engaged on IG by day", raw: { metric: "igAccountsEngaged", timeframeDays: 30, platform: "instagram", groupBy: "day", limit: 30, orderBy: "desc" }, expect: { metric: "igAccountsEngaged", platform: "instagram", groupBy: "day" } },
	{ q: "Most replies per account in 7 days", raw: { metric: "totalReplies", timeframeDays: 7, platform: "all", groupBy: "account", limit: 10, orderBy: "desc" }, expect: { metric: "totalReplies", groupBy: "account", timeframeDays: 7 } },
	{ q: "Likes for the last quarter", raw: { metric: "totalLikes", timeframeDays: 90, platform: "all", groupBy: "none", limit: 1, orderBy: "desc" }, expect: { metric: "totalLikes", timeframeDays: 90, groupBy: "none" } },
	{ q: "Quotes on Threads by account", raw: { metric: "totalQuotes", timeframeDays: 30, platform: "threads", groupBy: "account", limit: 10, orderBy: "desc" }, expect: { metric: "totalQuotes", platform: "threads", groupBy: "account" } },
	{ q: "Reach total for Instagram", raw: { metric: "totalIgReach", timeframeDays: 30, platform: "instagram", groupBy: "none", limit: 1, orderBy: "desc" }, expect: { metric: "totalIgReach", platform: "instagram", groupBy: "none" } },
	{ q: "Shares by IG account", raw: { metric: "totalIgShares", timeframeDays: 30, platform: "instagram", groupBy: "account", limit: 10, orderBy: "desc" }, expect: { metric: "totalIgShares", platform: "instagram", groupBy: "account" } },
	{ q: "Give me views over time for 365 days", raw: { metric: "totalViews", timeframeDays: 365, platform: "all", groupBy: "day", limit: 100, orderBy: "desc" }, expect: { metric: "totalViews", timeframeDays: 90, limit: 50 } },
	{ q: "Tiny 2 day sample", raw: { metric: "totalViews", timeframeDays: 2, platform: "all", groupBy: "none", limit: 1, orderBy: "desc" }, expect: { timeframeDays: 7 } },
	{ q: "Unknown metric should not pass through", raw: { metric: "viralMagicScore", timeframeDays: 30, platform: "all", groupBy: "account", limit: 10, orderBy: "desc" }, expect: { metric: "totalViews" } },
	{ q: "Bad platform should normalize", raw: { metric: "totalViews", timeframeDays: 30, platform: "tiktok", groupBy: "account", limit: 10, orderBy: "desc" }, expect: { platform: "all" } },
	{ q: "Bad grouping should normalize", raw: { metric: "totalViews", timeframeDays: 30, platform: "all", groupBy: "cohort", limit: 10, orderBy: "desc" }, expect: { groupBy: "none" } },
	{ q: "Smallest accounts by followers", raw: { metric: "totalFollowers", timeframeDays: 30, platform: "all", groupBy: "account", limit: 10, orderBy: "asc" }, expect: { metric: "totalFollowers", orderBy: "asc" } },
	{ q: "Single aggregate defaults limit to one", raw: { metric: "totalViews", timeframeDays: 30, platform: "all", groupBy: "none", orderBy: "desc" }, expect: { limit: 1 } },
	{ q: "Account breakdown defaults limit", raw: { metric: "totalViews", timeframeDays: 30, platform: "all", groupBy: "account", orderBy: "desc" }, expect: { limit: 10 } },
] as const;

const copilotGoldens = [
	{ q: "Why did reach drop this week?", intents: ["analytics"] },
	{ q: "What should I post tomorrow for my beauty accounts?", intents: ["content_advice", "posts"] },
	{ q: "Compare us against competitors this month", intents: ["competitors", "analytics"] },
	{ q: "Which recent post should I turn into a Reel?", intents: ["posts", "content_advice"] },
	{ q: "Best time to post for the sneaker group?", intents: ["content_advice", "posts"] },
	{ q: "Are followers growing or stalling?", intents: ["analytics"] },
	{ q: "Find my top post and tell me why it worked", intents: ["posts"] },
	{ q: "What content type is dragging performance?", intents: ["analytics", "content_advice"] },
	{ q: "Give me strategy ideas from rival benchmarks", intents: ["competitors", "content_advice"] },
	{ q: "Do I have enough data to judge this account?", intents: ["general"] },
	{ q: "How are views and replies trending?", intents: ["analytics"] },
	{ q: "Recommend a caption angle based on recent posts", intents: ["posts", "content_advice"] },
	{ q: "What competitor is gaining faster?", intents: ["competitors"] },
	{ q: "Which stats should I watch tomorrow?", intents: ["analytics"] },
	{ q: "Suggest a safer posting plan", intents: ["content_advice", "posts"] },
	{ q: "Show me published content patterns", intents: ["posts"] },
	{ q: "Is engagement down versus last week?", intents: ["analytics"] },
	{ q: "What should the next action be?", intents: ["content_advice"] },
	{ q: "Benchmark account performance against rivals", intents: ["analytics", "competitors"] },
	{ q: "Help", intents: ["general"] },
] as const;

describe("AI golden operator evals", () => {
	it("keeps NL query planning inside the metric registry and expected scope", () => {
		for (const testCase of nlQueryGoldens) {
			const spec = coerceSpec(testCase.raw);
			expect(metricKeys.has(spec.metric), testCase.q).toBe(true);
			expect(spec.timeframeDays, testCase.q).toBeGreaterThanOrEqual(7);
			expect(spec.timeframeDays, testCase.q).toBeLessThanOrEqual(90);
			expect(spec.limit, testCase.q).toBeGreaterThanOrEqual(1);
			expect(spec.limit, testCase.q).toBeLessThanOrEqual(50);
			expect(spec, testCase.q).toMatchObject(testCase.expect);
		}
	});

	it("keeps NL query prompts scoped, structured, and non-prose", () => {
		const prompt = buildSystemPrompt("Which accounts got most views this month?");
		expect(prompt).toContain("Return ONLY a valid JSON object");
		expect(prompt).toContain("Available metrics:");
		expect(prompt).toContain("metric MUST be one of the keys above");
		expect(prompt).toContain("Default timeframeDays: 30");
		expect(prompt).toContain("use followerGrowth");
		for (const metric of ["totalViews", "totalIgSaved", "igProfileViews"]) {
			expect(prompt).toContain(metric);
		}
	});

	it("treats followerGrowth as a period metric instead of a lifetime snapshot", () => {
		const metric = METRIC_REGISTRY.find((m) => m.key === "followerGrowth");
		expect(metric).toBeDefined();
		if (!metric) return;

		const result = aggregateRowsForSpec(
			{
				metric: "followerGrowth",
				timeframeDays: 30,
				platform: "all",
				groupBy: "none",
				limit: 1,
				orderBy: "desc",
			},
			metric,
			[
				{ account_id: "a1", date: "2026-05-10", follower_growth: 5 },
				{ account_id: "a1", date: "2026-05-11", follower_growth: -1 },
				{ account_id: "a2", date: "2026-05-11", follower_growth: 8 },
			],
			new Map([
				["a1", "one"],
				["a2", "two"],
			]),
		);

		expect(result).toEqual({
			rows: [{ label: "Total", value: 12 }],
			aggregate: 12,
		});
	});

	it("sums latest metric values per account for single aggregate scopes", () => {
		const metric = METRIC_REGISTRY.find((m) => m.key === "totalFollowers");
		expect(metric).toBeDefined();
		if (!metric) return;

		const result = aggregateRowsForSpec(
			{
				metric: "totalFollowers",
				timeframeDays: 30,
				platform: "all",
				groupBy: "none",
				limit: 1,
				orderBy: "desc",
			},
			metric,
			[
				{ account_id: "a1", date: "2026-05-10", followers_count: 100 },
				{ account_id: "a2", date: "2026-05-10", followers_count: 300 },
				{ account_id: "a1", date: "2026-05-12", followers_count: 150 },
			],
			new Map([
				["a1", "one"],
				["a2", "two"],
			]),
		);

		expect(result).toEqual({
			rows: [{ label: "Total", value: 450 }],
			aggregate: 450,
		});
	});

	it("keeps account rows trimmed without trimming the aggregate", () => {
		const metric = METRIC_REGISTRY.find((m) => m.key === "totalFollowers");
		expect(metric).toBeDefined();
		if (!metric) return;

		const result = aggregateRowsForSpec(
			{
				metric: "totalFollowers",
				timeframeDays: 30,
				platform: "all",
				groupBy: "account",
				limit: 1,
				orderBy: "desc",
			},
			metric,
			[
				{ account_id: "a1", date: "2026-05-12", followers_count: 100 },
				{ account_id: "a2", date: "2026-05-12", followers_count: 300 },
			],
			new Map([
				["a1", "one"],
				["a2", "two"],
			]),
		);

		expect(result.rows).toEqual([{ label: "two", value: 300 }]);
		expect(result.aggregate).toBe(400);
	});

	it("maps real operator questions to the right copilot data fetch intents", () => {
		for (const testCase of copilotGoldens) {
			const actual = detectIntent(testCase.q);
			for (const expectedIntent of testCase.intents) {
				expect(actual, testCase.q).toContain(expectedIntent);
			}
		}
	});

	it("locks copilot guidance against AI slop and invented numbers", () => {
		const rules = COPILOT_GROUNDING_RULES.join("\n");
		expect(rules).toContain("real data");
		expect(rules).toContain("If you don't have enough data, say so");
		expect(rules).toContain("be specific");
		expect(rules).toContain("Never turn qualitative buckets");
		expect(rules).toContain("Do not invent specific numbers or percentages");
	});
});
