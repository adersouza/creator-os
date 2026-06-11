import { describe, it, expect } from "vitest";
import {
	METRIC_REGISTRY,
	ALL_DB_COLUMNS,
	ANALYTICS_SELECT,
	getPostValue,
} from "@/src/lib/metricRegistry";
import type { MetricDef } from "@/src/lib/metricRegistry";

// ---------------------------------------------------------------------------
// 1. Every metric with a dbColumn must have a non-empty column name
// ---------------------------------------------------------------------------
describe("dbColumn validity", () => {
	it("every metric with a dbColumn has a valid, non-empty column name", () => {
		const withColumns = METRIC_REGISTRY.filter((m) => m.dbColumn !== "");
		expect(withColumns.length).toBeGreaterThan(0);

		for (const m of withColumns) {
			expect(m.dbColumn).toBeTruthy();
			// Must be a valid SQL column name (lowercase snake_case)
			expect(m.dbColumn).toMatch(/^[a-z][a-z0-9_]*$/);
		}
	});

	it("no typos in known column names", () => {
		const columns = METRIC_REGISTRY.map((m) => m.dbColumn).filter(Boolean);
		// Verify known correct column names exist
		expect(columns).toContain("total_likes");
		expect(columns).toContain("total_replies");
		expect(columns).toContain("total_views");
		expect(columns).toContain("total_reposts");
		expect(columns).toContain("total_quotes");
		expect(columns).toContain("total_shares");
		expect(columns).toContain("total_clicks");
		expect(columns).toContain("total_reach");
		expect(columns).toContain("total_saves");
		expect(columns).toContain("followers_count");
		expect(columns).toContain("ig_impressions");
		// Catch common typos
		expect(columns).not.toContain("total_share"); // should be total_shares
		expect(columns).not.toContain("total_like"); // should be total_likes
		expect(columns).not.toContain("follower_count"); // should be followers_count
		expect(columns).not.toContain("total_repost"); // should be total_reposts
	});
});

// ---------------------------------------------------------------------------
// 2. No duplicate dbColumn values within the same platform
// ---------------------------------------------------------------------------
describe("no duplicate dbColumn within the same platform", () => {
	it("threads metrics have no duplicate dbColumns", () => {
		const threadsColumns = METRIC_REGISTRY.filter(
			(m) => m.dbColumn && m.platforms.includes("threads"),
		).map((m) => m.dbColumn);

		const seen = new Set<string>();
		const dupes: string[] = [];
		for (const col of threadsColumns) {
			if (seen.has(col)) dupes.push(col);
			seen.add(col);
		}
		expect(dupes).toEqual([]);
	});

	it("instagram metrics have no duplicate dbColumns", () => {
		const igColumns = METRIC_REGISTRY.filter(
			(m) => m.dbColumn && m.platforms.includes("instagram"),
		).map((m) => m.dbColumn);

		const seen = new Set<string>();
		const dupes: string[] = [];
		for (const col of igColumns) {
			if (seen.has(col)) dupes.push(col);
			seen.add(col);
		}
		expect(dupes).toEqual([]);
	});

	it("cross-platform column sharing is allowed (e.g. total_shares)", () => {
		// total_shares is used by both totalIgShares (instagram) and totalShares (threads)
		const sharesMetrics = METRIC_REGISTRY.filter(
			(m) => m.dbColumn === "total_shares",
		);
		expect(sharesMetrics.length).toBe(2);
		// One should be threads, one instagram
		const platforms = sharesMetrics.flatMap((m) => [...m.platforms]);
		expect(platforms).toContain("threads");
		expect(platforms).toContain("instagram");
	});
});

// ---------------------------------------------------------------------------
// 3. Every metric must have an aggregation type
// ---------------------------------------------------------------------------
describe("aggregation type completeness", () => {
	it("every metric with a dbColumn has an explicit aggregation type", () => {
		const withColumns = METRIC_REGISTRY.filter((m) => m.dbColumn !== "");
		for (const m of withColumns) {
			expect(m.aggregation).toBeDefined();
			expect(["sum", "latest", "snapshot"]).toContain(m.aggregation);
		}
	});

	it("no metric accidentally falls through to default sum", () => {
		const dbMetrics = METRIC_REGISTRY.filter((m) => m.dbColumn !== "");
		const withoutAggregation = dbMetrics.filter((m) => !m.aggregation);
		expect(withoutAggregation).toEqual([]);
	});
});

// ---------------------------------------------------------------------------
// 4. Aggregation type correctness
// ---------------------------------------------------------------------------
describe("aggregation type correctness", () => {
	const findMetric = (key: string): MetricDef | undefined =>
		METRIC_REGISTRY.find((m) => m.key === key);

	it("totalFollowers uses 'latest' (not sum — follower counts are point-in-time)", () => {
		expect(findMetric("totalFollowers")?.aggregation).toBe("latest");
	});

	it("totalIgReach uses 'snapshot' (Meta rolling-window metric)", () => {
		expect(findMetric("totalIgReach")?.aggregation).toBe("snapshot");
	});

	it("totalIgImpressions uses 'snapshot' (Meta rolling-window metric)", () => {
		expect(findMetric("totalIgImpressions")?.aggregation).toBe("snapshot");
	});

	it("post-derived engagement metrics use 'latest' (daily snapshots)", () => {
		const engagementKeys = [
			"totalLikes",
			"totalReplies",
			"totalViews",
			"totalReposts",
			"totalQuotes",
			"totalShares",
			"totalClicks",
			"totalIgSaved",
			"totalIgShares",
		];
		for (const key of engagementKeys) {
			const metric = findMetric(key);
			expect(metric).toBeDefined();
			expect(metric?.aggregation).toBe("latest");
		}
	});

	it("scheduledCount has no dbColumn and no aggregation (special case)", () => {
		const scheduled = findMetric("scheduledCount");
		expect(scheduled).toBeDefined();
		expect(scheduled?.dbColumn).toBe("");
		expect(scheduled?.aggregation).toBeUndefined();
	});
});

// ---------------------------------------------------------------------------
// 5. ALL_DB_COLUMNS completeness
// ---------------------------------------------------------------------------
describe("ALL_DB_COLUMNS completeness", () => {
	it("contains every unique non-empty dbColumn from the registry", () => {
		const expectedColumns = [
			...new Set(METRIC_REGISTRY.map((m) => m.dbColumn).filter(Boolean)),
		];
		// Compare sorted copies — do NOT mutate the original arrays
		expect([...ALL_DB_COLUMNS].sort()).toEqual([...expectedColumns].sort());
	});

	it("has no empty strings", () => {
		expect(ALL_DB_COLUMNS).not.toContain("");
	});

	it("has no duplicates", () => {
		const unique = [...new Set(ALL_DB_COLUMNS)];
		expect(ALL_DB_COLUMNS.length).toBe(unique.length);
	});
});

// ---------------------------------------------------------------------------
// 6. ANALYTICS_SELECT builds correct SQL
// ---------------------------------------------------------------------------
describe("ANALYTICS_SELECT correctness", () => {
	it("starts with account_id", () => {
		expect(ANALYTICS_SELECT.startsWith("account_id")).toBe(true);
	});

	it("ends with date", () => {
		expect(ANALYTICS_SELECT.endsWith("date")).toBe(true);
	});

	it("includes all metric columns", () => {
		for (const col of ALL_DB_COLUMNS) {
			expect(ANALYTICS_SELECT).toContain(col);
		}
	});

	it("is a comma-separated string with deterministic order", () => {
		const parts = ANALYTICS_SELECT.split(", ");
		expect(parts[0]).toBe("account_id");
		expect(parts[parts.length - 1]).toBe("date");
		// All db columns should be between account_id and date
		const middleParts = parts.slice(1, -1);
		expect(middleParts.length).toBe(ALL_DB_COLUMNS.length);
	});

	it("column order matches ALL_DB_COLUMNS derivation", () => {
		// ANALYTICS_SELECT is derived from ALL_DB_COLUMNS — verify they stay in sync
		const expected = ["account_id", ...ALL_DB_COLUMNS, "date"].join(", ");
		expect(ANALYTICS_SELECT).toBe(expected);
	});
});

// ---------------------------------------------------------------------------
// 7. getPostValue utility function
// ---------------------------------------------------------------------------
describe("getPostValue", () => {
	it("resolves nested dot-notation path", () => {
		expect(getPostValue({ performance: { likes: 42 } }, "performance.likes")).toBe(42);
	});

	it("returns 0 for empty object", () => {
		expect(getPostValue({}, "performance.likes")).toBe(0);
	});

	it("returns 0 when intermediate value is null", () => {
		expect(getPostValue({ performance: null }, "performance.likes")).toBe(0);
	});

	it("returns 0 when leaf value is undefined", () => {
		expect(getPostValue({ performance: { likes: undefined } }, "performance.likes")).toBe(0);
	});

	it("returns 0 for non-numeric value", () => {
		expect(getPostValue({ performance: { likes: "not a number" } }, "performance.likes")).toBe(0);
	});

	it("resolves single-level path", () => {
		expect(getPostValue({ igReach: 500 }, "igReach")).toBe(500);
	});

	it("handles deeply nested paths", () => {
		expect(getPostValue({ a: { b: { c: 99 } } }, "a.b.c")).toBe(99);
	});

	it("returns 0 for NaN-producing values", () => {
		expect(getPostValue({ performance: { likes: {} } }, "performance.likes")).toBe(0);
	});
});

// ---------------------------------------------------------------------------
// 8. Platform coverage
// ---------------------------------------------------------------------------
describe("platform coverage", () => {
	const metricsForPlatform = (platform: string) =>
		METRIC_REGISTRY.filter((m) => m.platforms.includes(platform as "threads" | "instagram"));

	const keysForPlatform = (platform: string) =>
		metricsForPlatform(platform).map((m) => m.key);

	describe("threads", () => {
		it("has totalLikes, totalReplies, totalFollowers", () => {
			const keys = keysForPlatform("threads");
			expect(keys).toContain("totalLikes");
			expect(keys).toContain("totalReplies");
			expect(keys).toContain("totalFollowers");
		});

		it("has views, reposts, quotes metrics", () => {
			const keys = keysForPlatform("threads");
			expect(keys).toContain("totalViews");
			expect(keys).toContain("totalReposts");
			expect(keys).toContain("totalQuotes");
		});
	});

	describe("instagram", () => {
		it("has totalLikes, totalReplies, totalFollowers", () => {
			const keys = keysForPlatform("instagram");
			expect(keys).toContain("totalLikes");
			expect(keys).toContain("totalReplies");
			expect(keys).toContain("totalFollowers");
		});

		it("has reach, impressions, saved metrics", () => {
			const keys = keysForPlatform("instagram");
			expect(keys).toContain("totalIgReach");
			expect(keys).toContain("totalIgImpressions");
			expect(keys).toContain("totalIgSaved");
		});
	});

	it("every platform string is a recognized value", () => {
		const allPlatforms = new Set(METRIC_REGISTRY.flatMap((m) => [...m.platforms]));
		for (const p of allPlatforms) {
			expect(["threads", "instagram"]).toContain(p);
		}
	});
});

// ---------------------------------------------------------------------------
// 9. Type contract: AnalyticsStats keys match registry keys
// ---------------------------------------------------------------------------
describe("AnalyticsStats ↔ registry contract", () => {
	// We can't introspect TS interfaces at runtime, but we can verify
	// the registry contains all known AnalyticsStats keys.
	const ANALYTICS_STATS_KEYS = [
		"totalFollowers",
		"totalLikes",
		"totalReplies",
		"totalViews",
		"totalReposts",
		"totalQuotes",
		"totalShares",
		"totalClicks",
		"scheduledCount",
		"totalIgImpressions",
		"totalIgReach",
		"totalIgSaved",
		"totalIgShares",
		"igNewFollows",
		"igUnfollows",
		"igAccountsEngaged",
		"igProfileViews",
		"igWebsiteClicks",
		"igTotalInteractions",
		"igNonFollowerReachPct",
	];

	const registryKeys = METRIC_REGISTRY.map((m) => m.key);

	it("every AnalyticsStats key exists in the registry", () => {
		for (const key of ANALYTICS_STATS_KEYS) {
			expect(registryKeys).toContain(key);
		}
	});

	it("every registry key exists in AnalyticsStats", () => {
		for (const key of registryKeys) {
			expect(ANALYTICS_STATS_KEYS).toContain(key);
		}
	});

	it("no extra keys in the registry beyond AnalyticsStats", () => {
		const extraKeys = registryKeys.filter((k) => !ANALYTICS_STATS_KEYS.includes(k));
		expect(extraKeys).toEqual([]);
	});
});

// ---------------------------------------------------------------------------
// 10. DashboardStats includes all registry keys
// ---------------------------------------------------------------------------
describe("DashboardStats ↔ registry contract", () => {
	// Known DashboardStats keys from types.ts (EMPTY_STATS defines all of them)
	const DASHBOARD_STATS_KEYS = [
		"totalFollowers",
		"totalLikes",
		"totalReplies",
		"totalReposts",
		"totalQuotes",
		"totalShares",
		"totalClicks",
		"scheduledCount",
		"totalViews",
		"engagementRate",
		"totalIgImpressions",
		"totalIgReach",
		"totalIgSaved",
		"totalIgShares",
		"igNewFollows",
		"igUnfollows",
		"igAccountsEngaged",
		"igProfileViews",
		"igWebsiteClicks",
		"igTotalInteractions",
		"igNonFollowerReachPct",
	];

	const registryKeys = METRIC_REGISTRY.map((m) => m.key);

	it("every registry metric key is present in DashboardStats", () => {
		for (const key of registryKeys) {
			expect(DASHBOARD_STATS_KEYS).toContain(key);
		}
	});

	it("DashboardStats covers all registry keys (engagementRate is computed, not in registry)", () => {
		const keysNotInRegistry = DASHBOARD_STATS_KEYS.filter(
			(k) => !registryKeys.includes(k),
		);
		// engagementRate is a computed field, not a raw metric — it should be the only one missing
		expect(keysNotInRegistry).toEqual(["engagementRate"]);
	});
});
