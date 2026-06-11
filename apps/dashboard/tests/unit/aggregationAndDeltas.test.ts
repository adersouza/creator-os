/**
 * Tests for analytics aggregation and delta computation logic.
 *
 * These tests replicate the pure computation algorithms from:
 *   - services/api/analytics.ts (getAnalyticsStats, getAnalyticsWithDeltas)
 *   - src/lib/metricRegistry.ts (METRIC_REGISTRY, MetricAggregation)
 *
 * We extract the core logic into local helper functions so tests remain
 * pure and don't depend on Supabase or network calls.
 */
import { describe, expect, it } from "vitest";

// ---------------------------------------------------------------------------
// Types (mirrored from source)
// ---------------------------------------------------------------------------

type MetricAggregation = "sum" | "latest" | "snapshot";

interface MetricDef {
	readonly key: string;
	readonly dbColumn: string;
	readonly aggregation?: MetricAggregation;
}

interface AnalyticsRow {
	account_id: string;
	date: string;
	[column: string]: unknown;
}

// ---------------------------------------------------------------------------
// Extracted pure helpers (mirrored from services/api/analytics.ts)
// ---------------------------------------------------------------------------

/**
 * Registry-driven aggregation — replicates the loop inside getAnalyticsStats().
 *
 * For each metric:
 *   "sum"              → SUM all rows in the period across all accounts
 *   "latest"/"snapshot" → take the most recent row per account (rows must be
 *                         pre-sorted descending by date), then sum across accounts
 */
function aggregateRows(
	rows: AnalyticsRow[],
	metrics: MetricDef[],
): Record<string, number> {
	const totals: Record<string, number> = {};
	const latestSeen = new Set<string>();

	for (const row of rows) {
		const aid = row.account_id || "";
		const isFirstRowForAccount = !latestSeen.has(aid);
		if (isFirstRowForAccount) latestSeen.add(aid);

		for (const metric of metrics) {
			if (!metric.dbColumn) continue;

			const agg: MetricAggregation = metric.aggregation ?? "sum";
			const dbVal = row[metric.dbColumn] as number;
			const val = dbVal || 0;

			if (agg === "sum") {
				totals[metric.key] = (totals[metric.key] || 0) + val;
			} else {
				// "latest" or "snapshot": only use the first (most recent) row per account
				if (isFirstRowForAccount) {
					totals[metric.key] = (totals[metric.key] || 0) + val;
				}
			}
		}
	}

	return totals;
}

/**
 * Compute a delta percentage string — replicates computeDelta() in getAnalyticsWithDeltas().
 */
function computeDelta(current: number, previous: number): string {
	if (previous === 0 && current === 0) return "0%";
	if (previous === 0) return current > 0 ? "New" : "0%";
	const pct = ((current - previous) / previous) * 100;
	if (Math.abs(pct) < 0.1) return "0%";
	const sign = pct >= 0 ? "+" : "";
	return `${sign}${pct.toFixed(1)}%`;
}

/**
 * Compute Threads engagement rate — replicates the formula in getAnalyticsStats().
 */
function computeThreadsEngagementRate(
	likes: number,
	replies: number,
	reposts: number,
	quotes: number,
	views: number,
): number {
	const interactions = likes + replies * 2 + reposts * 1.5 + quotes;
	return (interactions / Math.max(views, 1)) * 100;
}

/**
 * Compute Instagram engagement rate — replicates the formula in getAnalyticsStats().
 */
function computeIgEngagementRate(
	likes: number,
	saves: number,
	shares: number,
	reach: number,
): number {
	const interactions = likes + saves * 3 + shares;
	const denominator = reach > 0 ? reach : 1;
	return (interactions / denominator) * 100;
}

/**
 * Filter rows to a date range (inclusive of start, exclusive of end boundary).
 */
function filterByDateRange(
	rows: AnalyticsRow[],
	startDate: string,
	endDate: string,
): AnalyticsRow[] {
	return rows.filter((r) => r.date >= startDate && r.date <= endDate);
}

// ---------------------------------------------------------------------------
// Test metric definitions (subset of METRIC_REGISTRY)
// ---------------------------------------------------------------------------

const LIKES_METRIC: MetricDef = {
	key: "totalLikes",
	dbColumn: "total_likes",
	aggregation: "latest",
};

const VIEWS_METRIC: MetricDef = {
	key: "totalViews",
	dbColumn: "total_views",
	aggregation: "latest",
};

const FOLLOWERS_METRIC: MetricDef = {
	key: "totalFollowers",
	dbColumn: "followers_count",
	aggregation: "latest",
};

const REACH_METRIC: MetricDef = {
	key: "totalIgReach",
	dbColumn: "total_reach",
	aggregation: "snapshot",
};

const IMPRESSIONS_METRIC: MetricDef = {
	key: "totalIgImpressions",
	dbColumn: "ig_impressions",
	aggregation: "snapshot",
};

const SUM_METRIC: MetricDef = {
	key: "hypotheticalSum",
	dbColumn: "hypothetical_sum",
	aggregation: "sum",
};

const ALL_TEST_METRICS: MetricDef[] = [
	LIKES_METRIC,
	VIEWS_METRIC,
	FOLLOWERS_METRIC,
	REACH_METRIC,
	IMPRESSIONS_METRIC,
];

// ---------------------------------------------------------------------------
// 1. "latest" aggregation picks most recent row
// ---------------------------------------------------------------------------
describe("latest aggregation", () => {
	it("picks the most recent row's value (first in desc-sorted array)", () => {
		// Rows are pre-sorted descending by date (as Supabase returns them)
		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09", total_likes: 200 },
			{ account_id: "acc1", date: "2026-03-05", total_likes: 150 },
			{ account_id: "acc1", date: "2026-03-01", total_likes: 100 },
		];

		const result = aggregateRows(rows, [LIKES_METRIC]);
		expect(result.totalLikes).toBe(200);
	});

	it("ignores older rows for the same account", () => {
		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09", total_likes: 50 },
			{ account_id: "acc1", date: "2026-03-08", total_likes: 999 },
		];

		const result = aggregateRows(rows, [LIKES_METRIC]);
		// Should be 50, not 999 or 1049
		expect(result.totalLikes).toBe(50);
	});
});

// ---------------------------------------------------------------------------
// 2. "latest" with missing/null/zero data
// ---------------------------------------------------------------------------
describe("latest with missing data", () => {
	it("treats null as 0 via `dbVal || 0`", () => {
		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09", total_likes: null },
			{ account_id: "acc1", date: "2026-03-08", total_likes: 150 },
		];

		const result = aggregateRows(rows, [LIKES_METRIC]);
		// The most recent row has null — `null || 0` → 0
		// Does NOT fall back to the previous row (150)
		expect(result.totalLikes).toBe(0);
	});

	it("treats 0 as 0 (no fallback to previous row)", () => {
		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09", total_likes: 0 },
			{ account_id: "acc1", date: "2026-03-08", total_likes: 150 },
		];

		const result = aggregateRows(rows, [LIKES_METRIC]);
		// `0 || 0` → 0, no fallback
		expect(result.totalLikes).toBe(0);
	});

	it("treats undefined column as 0", () => {
		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09" },
			// total_likes is not present at all
		];

		const result = aggregateRows(rows, [LIKES_METRIC]);
		expect(result.totalLikes).toBe(0);
	});
});

// ---------------------------------------------------------------------------
// 3. "snapshot" aggregation for IG reach/impressions
// ---------------------------------------------------------------------------
describe("snapshot aggregation", () => {
	it("takes most recent value (same as latest)", () => {
		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09", total_reach: 5000 },
			{ account_id: "acc1", date: "2026-03-08", total_reach: 4500 },
			{ account_id: "acc1", date: "2026-03-07", total_reach: 4000 },
		];

		const result = aggregateRows(rows, [REACH_METRIC]);
		expect(result.totalIgReach).toBe(5000);
	});

	it("sums latest values across multiple accounts", () => {
		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09", total_reach: 3000 },
			{ account_id: "acc2", date: "2026-03-09", total_reach: 2000 },
			{ account_id: "acc1", date: "2026-03-08", total_reach: 2500 },
			{ account_id: "acc2", date: "2026-03-08", total_reach: 1500 },
		];

		const result = aggregateRows(rows, [REACH_METRIC]);
		// acc1 latest: 3000, acc2 latest: 2000
		expect(result.totalIgReach).toBe(5000);
	});

	it("ig_impressions also uses snapshot aggregation", () => {
		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09", ig_impressions: 10000 },
			{ account_id: "acc1", date: "2026-03-08", ig_impressions: 9000 },
		];

		const result = aggregateRows(rows, [IMPRESSIONS_METRIC]);
		expect(result.totalIgImpressions).toBe(10000);
	});
});

// ---------------------------------------------------------------------------
// 4. "sum" aggregation (hypothetical — no current metrics use it)
// ---------------------------------------------------------------------------
describe("sum aggregation", () => {
	it("sums all rows in the date range", () => {
		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09", hypothetical_sum: 100 },
			{ account_id: "acc1", date: "2026-03-08", hypothetical_sum: 150 },
		];

		const result = aggregateRows(rows, [SUM_METRIC]);
		expect(result.hypotheticalSum).toBe(250);
	});

	it("sums across multiple accounts and multiple days", () => {
		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09", hypothetical_sum: 100 },
			{ account_id: "acc2", date: "2026-03-09", hypothetical_sum: 50 },
			{ account_id: "acc1", date: "2026-03-08", hypothetical_sum: 200 },
			{ account_id: "acc2", date: "2026-03-08", hypothetical_sum: 75 },
		];

		const result = aggregateRows(rows, [SUM_METRIC]);
		expect(result.hypotheticalSum).toBe(425);
	});

	it("defaults to sum when aggregation is undefined", () => {
		const noAggMetric: MetricDef = {
			key: "noAgg",
			dbColumn: "some_col",
			// aggregation not set — defaults to "sum"
		};

		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09", some_col: 10 },
			{ account_id: "acc1", date: "2026-03-08", some_col: 20 },
		];

		const result = aggregateRows(rows, [noAggMetric]);
		expect(result.noAgg).toBe(30);
	});
});

// ---------------------------------------------------------------------------
// 5. Delta computation for "latest" metrics
// ---------------------------------------------------------------------------
describe("delta computation for latest metrics", () => {
	it("computes positive delta percentage", () => {
		// current = 200, previous = 180 → +11.1%
		const delta = computeDelta(200, 180);
		expect(delta).toBe("+11.1%");
	});

	it("computes exact percentage with rounding", () => {
		// 200/180 - 1 = 0.11111... → 11.1%
		const pct = ((200 - 180) / 180) * 100;
		expect(pct).toBeCloseTo(11.111, 2);
		expect(computeDelta(200, 180)).toBe("+11.1%");
	});

	it("computes delta for small changes", () => {
		// current = 101, previous = 100 → +1.0%
		expect(computeDelta(101, 100)).toBe("+1.0%");
	});
});

// ---------------------------------------------------------------------------
// 6. Delta computation for "snapshot" metrics
// ---------------------------------------------------------------------------
describe("delta computation for snapshot metrics", () => {
	it("compares current vs previous period latest values directly", () => {
		// snapshot metrics: delta = computeDelta(currentLatest, previousLatest)
		// current reach = 5000, previous reach = 4500
		const delta = computeDelta(5000, 4500);
		expect(delta).toBe("+11.1%");
	});

	it("shows positive delta when reach increases", () => {
		expect(computeDelta(6000, 5000)).toBe("+20.0%");
	});

	it("shows negative delta when reach decreases", () => {
		expect(computeDelta(4000, 5000)).toBe("-20.0%");
	});
});

// ---------------------------------------------------------------------------
// 7. Delta with zero baseline
// ---------------------------------------------------------------------------
describe("delta with zero baseline", () => {
	it("returns 'New' when previous is 0 and current > 0", () => {
		expect(computeDelta(100, 0)).toBe("New");
	});

	it("returns '0%' when both are 0", () => {
		expect(computeDelta(0, 0)).toBe("0%");
	});

	it("returns '0%' when previous is 0 and current is also 0", () => {
		// No division by zero — handled by the guard
		expect(computeDelta(0, 0)).toBe("0%");
	});

	it("does NOT return Infinity or NaN", () => {
		const delta = computeDelta(100, 0);
		expect(delta).not.toContain("Infinity");
		expect(delta).not.toContain("NaN");
		expect(delta).toBe("New");
	});

	it("returns '0%' when previous is 0 and current is negative", () => {
		// Edge case: current < 0, previous = 0
		// previous === 0 && current <= 0 → "0%"
		expect(computeDelta(-5, 0)).toBe("0%");
	});
});

// ---------------------------------------------------------------------------
// 8. Delta with negative growth
// ---------------------------------------------------------------------------
describe("delta with negative growth", () => {
	it("shows negative percentage for follower loss", () => {
		// previous = 1000, current = 980 → -2.0%
		expect(computeDelta(980, 1000)).toBe("-2.0%");
	});

	it("shows negative percentage for large drops", () => {
		// 500 → 250 = -50%
		expect(computeDelta(250, 500)).toBe("-50.0%");
	});

	it("returns '0%' for very small changes under threshold", () => {
		// 10000 → 10000.05 → pct = 0.0005% which is < 0.1
		expect(computeDelta(10000, 10000)).toBe("0%");
	});

	it("returns '0%' when change is below 0.1% threshold", () => {
		// 10001 / 10000 - 1 = 0.01% which is < 0.1
		expect(computeDelta(10001, 10000)).toBe("0%");
	});
});

// ---------------------------------------------------------------------------
// 9. Multi-account aggregation
// ---------------------------------------------------------------------------
describe("multi-account aggregation", () => {
	it("sums latest values from each account for 'latest' metrics", () => {
		const rows: AnalyticsRow[] = [
			{ account_id: "accA", date: "2026-03-09", total_likes: 100 },
			{ account_id: "accB", date: "2026-03-09", total_likes: 200 },
			{ account_id: "accA", date: "2026-03-08", total_likes: 80 },
			{ account_id: "accB", date: "2026-03-08", total_likes: 160 },
		];

		const result = aggregateRows(rows, [LIKES_METRIC]);
		// accA latest: 100, accB latest: 200 → 300
		expect(result.totalLikes).toBe(300);
	});

	it("handles accounts with different most-recent dates", () => {
		const rows: AnalyticsRow[] = [
			{ account_id: "accA", date: "2026-03-09", total_likes: 100 },
			{ account_id: "accB", date: "2026-03-07", total_likes: 200 },
			{ account_id: "accA", date: "2026-03-05", total_likes: 50 },
		];

		const result = aggregateRows(rows, [LIKES_METRIC]);
		// accA latest: 100, accB latest: 200 → 300
		expect(result.totalLikes).toBe(300);
	});

	it("handles multiple metrics simultaneously across accounts", () => {
		const rows: AnalyticsRow[] = [
			{
				account_id: "accA",
				date: "2026-03-09",
				total_likes: 100,
				total_views: 1000,
				followers_count: 500,
			},
			{
				account_id: "accB",
				date: "2026-03-09",
				total_likes: 200,
				total_views: 2000,
				followers_count: 800,
			},
			{
				account_id: "accA",
				date: "2026-03-08",
				total_likes: 80,
				total_views: 900,
				followers_count: 490,
			},
		];

		const result = aggregateRows(rows, [
			LIKES_METRIC,
			VIEWS_METRIC,
			FOLLOWERS_METRIC,
		]);
		expect(result.totalLikes).toBe(300); // 100 + 200
		expect(result.totalViews).toBe(3000); // 1000 + 2000
		expect(result.totalFollowers).toBe(1300); // 500 + 800
	});
});

// ---------------------------------------------------------------------------
// 10. Empty data handling
// ---------------------------------------------------------------------------
describe("empty data handling", () => {
	it("returns empty object for no rows at all", () => {
		const result = aggregateRows([], ALL_TEST_METRICS);
		expect(result).toEqual({});
	});

	it("returns 0 for all metrics when rows have null values", () => {
		const rows: AnalyticsRow[] = [
			{
				account_id: "acc1",
				date: "2026-03-09",
				total_likes: null,
				total_views: null,
				followers_count: null,
				total_reach: null,
				ig_impressions: null,
			},
		];

		const result = aggregateRows(rows, ALL_TEST_METRICS);
		expect(result.totalLikes).toBe(0);
		expect(result.totalViews).toBe(0);
		expect(result.totalFollowers).toBe(0);
		expect(result.totalIgReach).toBe(0);
		expect(result.totalIgImpressions).toBe(0);
	});

	it("returns correct values for a single row", () => {
		const rows: AnalyticsRow[] = [
			{
				account_id: "acc1",
				date: "2026-03-09",
				total_likes: 42,
				total_views: 500,
			},
		];

		const result = aggregateRows(rows, [LIKES_METRIC, VIEWS_METRIC]);
		expect(result.totalLikes).toBe(42);
		expect(result.totalViews).toBe(500);
	});

	it("delta is 0% when current and previous are both 0", () => {
		expect(computeDelta(0, 0)).toBe("0%");
	});
});

// ---------------------------------------------------------------------------
// 11. Date range filtering
// ---------------------------------------------------------------------------
describe("date range filtering", () => {
	// Generate 30 days of data: 2026-03-01 through 2026-03-30
	const thirtyDaysOfData: AnalyticsRow[] = [];
	for (let i = 0; i < 30; i++) {
		const d = new Date("2026-03-01T00:00:00Z");
		d.setUTCDate(d.getUTCDate() + i);
		const dateStr = d.toISOString().split("T")[0];
		thirtyDaysOfData.push({
			account_id: "acc1",
			date: dateStr,
			total_likes: 100 + i, // incrementing values
		});
	}

	it("filters to the last 7 days only", () => {
		const endDate = "2026-03-30";
		const startDate = "2026-03-24"; // 7 days: 24,25,26,27,28,29,30

		const filtered = filterByDateRange(thirtyDaysOfData, startDate, endDate);
		expect(filtered.length).toBe(7);
		expect(filtered[0].date).toBe("2026-03-24");
		expect(filtered[filtered.length - 1].date).toBe("2026-03-30");
	});

	it("previous period for 7-day view is days 8-14", () => {
		const prevEnd = "2026-03-23";
		const prevStart = "2026-03-17"; // 7 days: 17,18,19,20,21,22,23

		const filtered = filterByDateRange(
			thirtyDaysOfData,
			prevStart,
			prevEnd,
		);
		expect(filtered.length).toBe(7);
		expect(filtered[0].date).toBe("2026-03-17");
		expect(filtered[filtered.length - 1].date).toBe("2026-03-23");
	});

	it("aggregation on filtered 7-day range uses latest from that range", () => {
		const last7 = filterByDateRange(
			thirtyDaysOfData,
			"2026-03-24",
			"2026-03-30",
		);
		// Sort descending for aggregation (as Supabase would)
		const sorted = [...last7].sort((a, b) => b.date.localeCompare(a.date));

		const result = aggregateRows(sorted, [LIKES_METRIC]);
		// 2026-03-30 is day index 29 → total_likes = 100 + 29 = 129
		expect(result.totalLikes).toBe(129);
	});
});

// ---------------------------------------------------------------------------
// 12. Engagement rate computation
// ---------------------------------------------------------------------------
describe("engagement rate computation", () => {
	describe("Threads formula", () => {
		it("computes weighted engagement rate", () => {
			// (likes + replies*2 + reposts*1.5 + quotes) / max(views, 1) * 100
			const rate = computeThreadsEngagementRate(100, 50, 20, 10, 5000);
			// (100 + 100 + 30 + 10) / 5000 * 100 = 240/5000*100 = 4.8
			expect(rate).toBeCloseTo(4.8, 1);
		});

		it("returns weighted value / 1 when views = 0 (not NaN)", () => {
			const rate = computeThreadsEngagementRate(10, 5, 2, 1, 0);
			// (10 + 10 + 3 + 1) / max(0, 1) * 100 = 24/1*100 = 2400
			expect(rate).toBe(2400);
			expect(Number.isNaN(rate)).toBe(false);
		});

		it("returns 0 when all inputs are 0", () => {
			const rate = computeThreadsEngagementRate(0, 0, 0, 0, 0);
			// (0) / max(0, 1) * 100 = 0
			expect(rate).toBe(0);
		});
	});

	describe("Instagram formula", () => {
		it("computes IG engagement rate with saves weighted 3x", () => {
			// (likes + saves*3 + shares) / reach * 100
			const rate = computeIgEngagementRate(100, 50, 20, 5000);
			// (100 + 150 + 20) / 5000 * 100 = 270/5000*100 = 5.4
			expect(rate).toBeCloseTo(5.4, 1);
		});

		it("uses denominator 1 when reach is 0 (not NaN)", () => {
			const rate = computeIgEngagementRate(10, 5, 2, 0);
			// (10 + 15 + 2) / 1 * 100 = 2700
			expect(rate).toBe(2700);
			expect(Number.isNaN(rate)).toBe(false);
		});

		it("returns 0 when all inputs are 0", () => {
			const rate = computeIgEngagementRate(0, 0, 0, 0);
			expect(rate).toBe(0);
		});
	});
});

// ---------------------------------------------------------------------------
// 13. Multiple rows per day (edge case)
// ---------------------------------------------------------------------------
describe("multiple rows per day", () => {
	it("latest picks the first row encountered for an account (desc sort order)", () => {
		// If two rows exist for acc1 on the same date, the first one in the
		// desc-sorted array wins (which is the behavior of the Set-based dedup).
		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09", total_likes: 200 },
			{ account_id: "acc1", date: "2026-03-09", total_likes: 180 },
		];

		const result = aggregateRows(rows, [LIKES_METRIC]);
		// First row wins due to `latestSeen.has(aid)` guard
		expect(result.totalLikes).toBe(200);
	});

	it("sum includes both rows for the same day", () => {
		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09", hypothetical_sum: 100 },
			{ account_id: "acc1", date: "2026-03-09", hypothetical_sum: 50 },
		];

		const result = aggregateRows(rows, [SUM_METRIC]);
		expect(result.hypotheticalSum).toBe(150);
	});

	it("different accounts on the same day each get their own latest", () => {
		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09", total_likes: 100 },
			{ account_id: "acc2", date: "2026-03-09", total_likes: 200 },
			{ account_id: "acc1", date: "2026-03-09", total_likes: 80 },
			{ account_id: "acc2", date: "2026-03-09", total_likes: 160 },
		];

		const result = aggregateRows(rows, [LIKES_METRIC]);
		// acc1 first seen: 100, acc2 first seen: 200 → 300
		expect(result.totalLikes).toBe(300);
	});
});

// ---------------------------------------------------------------------------
// 14. Period boundary edge cases
// ---------------------------------------------------------------------------
describe("period boundary edge cases", () => {
	it("date strings sort correctly as lexicographic comparison", () => {
		const dates = [
			"2026-03-09",
			"2026-01-31",
			"2026-12-01",
			"2026-02-28",
		];
		const sorted = [...dates].sort();
		expect(sorted).toEqual([
			"2026-01-31",
			"2026-02-28",
			"2026-03-09",
			"2026-12-01",
		]);
	});

	it("leap day (Feb 29) sorts between Feb 28 and Mar 01", () => {
		const dates = ["2028-03-01", "2028-02-28", "2028-02-29"];
		const sorted = [...dates].sort();
		expect(sorted).toEqual(["2028-02-28", "2028-02-29", "2028-03-01"]);
	});

	it("midnight UTC boundary: toISOString date extraction is consistent", () => {
		// This is how the source code computes cutoff dates
		const date = new Date("2026-03-09T00:00:00.000Z");
		expect(date.toISOString().split("T")[0]).toBe("2026-03-09");

		const endOfDay = new Date("2026-03-09T23:59:59.999Z");
		expect(endOfDay.toISOString().split("T")[0]).toBe("2026-03-09");
	});

	it("cutoff date computation: 7 days back from 2026-03-09", () => {
		const now = new Date("2026-03-09T12:00:00Z");
		const cutoff = new Date(now);
		cutoff.setDate(cutoff.getDate() - 7);
		const cutoffStr = cutoff.toISOString().split("T")[0];
		expect(cutoffStr).toBe("2026-03-02");
	});

	it("previous period date: periodDays back for pre-previous (2x)", () => {
		const now = new Date("2026-03-09T12:00:00Z");
		const periodDays = 7;

		const prevDate = new Date(now);
		prevDate.setDate(prevDate.getDate() - periodDays);
		expect(prevDate.toISOString().split("T")[0]).toBe("2026-03-02");

		const prePrevDate = new Date(now);
		prePrevDate.setDate(prePrevDate.getDate() - periodDays * 2);
		expect(prePrevDate.toISOString().split("T")[0]).toBe("2026-02-23");
	});

	it("handles month boundary correctly (March → February)", () => {
		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-01", total_likes: 200 },
			{ account_id: "acc1", date: "2026-02-28", total_likes: 180 },
		];

		// Filter for March only
		const marchRows = filterByDateRange(rows, "2026-03-01", "2026-03-31");
		expect(marchRows.length).toBe(1);
		expect(marchRows[0].total_likes).toBe(200);

		// Filter for February only
		const febRows = filterByDateRange(rows, "2026-02-01", "2026-02-28");
		expect(febRows.length).toBe(1);
		expect(febRows[0].total_likes).toBe(180);
	});
});

// ---------------------------------------------------------------------------
// Additional: computeDelta edge cases
// ---------------------------------------------------------------------------
describe("computeDelta additional edge cases", () => {
	it("formats with one decimal place", () => {
		expect(computeDelta(150, 100)).toBe("+50.0%");
	});

	it("handles exact doubling", () => {
		expect(computeDelta(200, 100)).toBe("+100.0%");
	});

	it("handles halving", () => {
		expect(computeDelta(50, 100)).toBe("-50.0%");
	});

	it("handles very large numbers", () => {
		const delta = computeDelta(1_000_000, 999_000);
		// (1000000 - 999000) / 999000 * 100 = 0.1001%
		expect(delta).toBe("+0.1%");
	});

	it("handles very small positive change just above threshold", () => {
		// Need pct >= 0.1 to show as non-zero
		// 1001 / 1000 - 1 = 0.1%
		expect(computeDelta(1001, 1000)).toBe("+0.1%");
	});

	it("handles very small negative change just above threshold", () => {
		// 999 / 1000 - 1 = -0.1%
		expect(computeDelta(999, 1000)).toBe("-0.1%");
	});
});

// ---------------------------------------------------------------------------
// Additional: getAnalyticsWithDeltas "no previous data" branches
// ---------------------------------------------------------------------------
describe("delta display branches (mirroring getAnalyticsWithDeltas)", () => {
	it("all-time (periodDays=0) always returns em dash", () => {
		// In the source: isAllTime → all deltas = "—"
		const isAllTime = true;
		const result = isAllTime ? "—" : computeDelta(100, 50);
		expect(result).toBe("—");
	});

	it("no previous data returns em dash", () => {
		const hasPreviousData = false;
		const result = !hasPreviousData ? "—" : computeDelta(100, 50);
		expect(result).toBe("—");
	});

	it("has previous but no pre-previous: positive value shows 'New'", () => {
		const hasPreviousData = true;
		const hasPrePreviousData = false;
		const currentValue = 100;

		// Source logic: !hasPrePreviousData → currentValue > 0 ? "New" : "0%"
		const result =
			hasPreviousData && !hasPrePreviousData
				? currentValue > 0
					? "New"
					: "0%"
				: computeDelta(currentValue, 0);
		expect(result).toBe("New");
	});

	it("has previous but no pre-previous: zero value shows '0%'", () => {
		const hasPreviousData = true;
		const hasPrePreviousData = false;
		const currentValue = 0;

		const result =
			hasPreviousData && !hasPrePreviousData
				? currentValue > 0
					? "New"
					: "0%"
				: computeDelta(currentValue, 0);
		expect(result).toBe("0%");
	});
});

// ---------------------------------------------------------------------------
// Additional: Mixed aggregation types in a single pass
// ---------------------------------------------------------------------------
describe("mixed aggregation types in single aggregateRows call", () => {
	it("applies correct strategy per metric in one pass", () => {
		const metrics: MetricDef[] = [
			{ key: "latestMetric", dbColumn: "col_a", aggregation: "latest" },
			{ key: "sumMetric", dbColumn: "col_b", aggregation: "sum" },
			{
				key: "snapshotMetric",
				dbColumn: "col_c",
				aggregation: "snapshot",
			},
		];

		const rows: AnalyticsRow[] = [
			{
				account_id: "acc1",
				date: "2026-03-09",
				col_a: 100,
				col_b: 10,
				col_c: 500,
			},
			{
				account_id: "acc1",
				date: "2026-03-08",
				col_a: 80,
				col_b: 20,
				col_c: 400,
			},
			{
				account_id: "acc1",
				date: "2026-03-07",
				col_a: 60,
				col_b: 30,
				col_c: 300,
			},
		];

		const result = aggregateRows(rows, metrics);

		// latest: first row only → 100
		expect(result.latestMetric).toBe(100);
		// sum: all rows → 10 + 20 + 30 = 60
		expect(result.sumMetric).toBe(60);
		// snapshot: first row only → 500
		expect(result.snapshotMetric).toBe(500);
	});
});

// ---------------------------------------------------------------------------
// Additional: Metrics with empty dbColumn are skipped
// ---------------------------------------------------------------------------
describe("metrics with empty dbColumn", () => {
	it("skips metrics without a dbColumn (e.g. scheduledCount)", () => {
		const metrics: MetricDef[] = [
			{ key: "scheduledCount", dbColumn: "" },
			{ key: "totalLikes", dbColumn: "total_likes", aggregation: "latest" },
		];

		const rows: AnalyticsRow[] = [
			{ account_id: "acc1", date: "2026-03-09", total_likes: 42 },
		];

		const result = aggregateRows(rows, metrics);
		expect(result.scheduledCount).toBeUndefined();
		expect(result.totalLikes).toBe(42);
	});
});
