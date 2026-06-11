import { describe, expect, it } from "vitest";
import {
	__test__,
	percentile,
	tierFromFollowers,
} from "../../api/_lib/analytics/cohortAggregation.js";

describe("tierFromFollowers", () => {
	it("matches the migration CHECK constraint labels exactly", () => {
		// The capital-K casing is load-bearing — the DB CHECK rejects any
		// other casing, so a silent drift here would cause every UPSERT to
		// throw at write time. Guard the whole ladder.
		expect(tierFromFollowers(0)).toBe("0-1K");
		expect(tierFromFollowers(999)).toBe("0-1K");
		expect(tierFromFollowers(1_000)).toBe("1K-5K");
		expect(tierFromFollowers(4_999)).toBe("1K-5K");
		expect(tierFromFollowers(5_000)).toBe("5K-10K");
		expect(tierFromFollowers(9_999)).toBe("5K-10K");
		expect(tierFromFollowers(10_000)).toBe("10K-50K");
		expect(tierFromFollowers(49_999)).toBe("10K-50K");
		expect(tierFromFollowers(50_000)).toBe("50K+");
		expect(tierFromFollowers(1_000_000)).toBe("50K+");
	});
});

describe("percentile", () => {
	it("returns the single value for a one-element sample", () => {
		expect(percentile([42], 0.5)).toBe(42);
		expect(percentile([42], 0.9)).toBe(42);
	});

	it("interpolates linearly between neighbors", () => {
		// 10 values, p50 lands between index 4 and 5 (values 5 and 6).
		const sorted = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
		expect(percentile(sorted, 0)).toBe(1);
		expect(percentile(sorted, 0.25)).toBeCloseTo(3.25, 5);
		expect(percentile(sorted, 0.5)).toBeCloseTo(5.5, 5);
		expect(percentile(sorted, 0.75)).toBeCloseTo(7.75, 5);
		expect(percentile(sorted, 0.9)).toBeCloseTo(9.1, 5);
		expect(percentile(sorted, 1)).toBe(10);
	});

	it("returns 0 on an empty sample", () => {
		expect(percentile([], 0.5)).toBe(0);
	});
});

describe("k-anonymity thresholds", () => {
	it("enforces two-dimension thresholds matching the privacy spec", () => {
		// These numbers are load-bearing and must NOT be edited casually —
		// any change must go through a privacy review. The spec is:
		//   median:        ≥ 30 accounts AND ≥ 10 users
		//   full dist:     ≥ 50 accounts AND ≥ 15 users
		expect(__test__.MIN_ACCOUNT_COUNT).toBe(30);
		expect(__test__.MIN_USER_COUNT).toBe(10);
		expect(__test__.MIN_ACCOUNT_COUNT_FULL).toBe(50);
		expect(__test__.MIN_USER_COUNT_FULL).toBe(15);
	});
});

describe("metric compute", () => {
	const metricByName = new Map(__test__.METRICS.map((m) => [m.name, m]));

	it("engagement_rate passes the stored value through unchanged", () => {
		const m = metricByName.get("engagement_rate");
		expect(m).toBeDefined();
		expect(
			m?.compute({
				account_id: "a",
				engagement_rate: 3.25,
				follower_growth: null,
				followers_count: null,
				posts_count: null,
				total_views: null,
				total_replies: null,
				total_saves: null,
				total_reach: null,
			}),
		).toBeCloseTo(3.25);
	});

	it("views_per_post returns null when posts_count is 0", () => {
		// Would otherwise divide by zero — the aggregator treats the bucket
		// cell as missing, not as zero.
		const m = metricByName.get("views_per_post");
		expect(
			m?.compute({
				account_id: "a",
				engagement_rate: null,
				follower_growth: null,
				followers_count: null,
				posts_count: 0,
				total_views: 5000,
				total_replies: null,
				total_saves: null,
				total_reach: null,
			}),
		).toBeNull();
	});

	it("reply_rate returns null when total_views is 0", () => {
		const m = metricByName.get("reply_rate");
		expect(
			m?.compute({
				account_id: "a",
				engagement_rate: null,
				follower_growth: null,
				followers_count: null,
				posts_count: null,
				total_views: 0,
				total_replies: 10,
				total_saves: null,
				total_reach: null,
			}),
		).toBeNull();
	});

	it("save_rate is flagged igOnly so threads accounts never contribute", () => {
		const m = metricByName.get("save_rate");
		expect(m?.igOnly).toBe(true);
	});
});

describe("canonical niche coverage", () => {
	it("keeps the canonical niche list in sync with the cohorts module", () => {
		// The aggregator re-exports CANONICAL_NICHES so both aggregator and
		// read handler can validate against a single source. If this breaks,
		// one side is drifting.
		expect(__test__.CANONICAL_NICHES).toContain("ofm");
		expect(__test__.CANONICAL_NICHES).toContain("uncategorized");
		expect(__test__.CANONICAL_NICHES.length).toBe(8);
	});
});
