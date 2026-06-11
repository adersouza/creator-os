/**
 * Surprise scorer — ranks metrics by z-score magnitude relative to trailing
 * baseline so the Auto-Insights Feed can lift the most unexpected values.
 */

import { describe, expect, it } from "vitest";
import {
	rankBySurprise,
	scoreSurprise,
	type MetricSample,
} from "@/lib/surprise";

describe("scoreSurprise", () => {
	it("returns null when history is too short", () => {
		expect(scoreSurprise([], 5)).toBeNull();
		expect(scoreSurprise([1, 2, 3, 4], 10)).toBeNull();
	});

	it("returns null when history is flat and current matches", () => {
		expect(scoreSurprise([7, 7, 7, 7, 7, 7], 7)).toBeNull();
	});

	it("still scores a change against a zero-variance baseline", () => {
		// Flat prior but current differs → should surface with a large magnitude.
		const score = scoreSurprise([10, 10, 10, 10, 10, 10], 20);
		expect(score).not.toBeNull();
		if (!score) return;
		expect(score.direction).toBe("up");
		expect(score.magnitude).toBeGreaterThan(2);
	});

	it("reports 'up' for a current above the baseline", () => {
		const score = scoreSurprise([10, 11, 10, 12, 11, 10], 16);
		expect(score).not.toBeNull();
		if (!score) return;
		expect(score.direction).toBe("up");
		expect(score.zScore).toBeGreaterThan(0);
	});

	it("reports 'down' for a current below the baseline", () => {
		const score = scoreSurprise([100, 102, 98, 101, 99, 100], 60);
		expect(score).not.toBeNull();
		if (!score) return;
		expect(score.direction).toBe("down");
		expect(score.zScore).toBeLessThan(0);
	});

	it("tiers escalate with magnitude", () => {
		// Trailing stdDev ≈ 1.29 over [10,11,9,12,8,10].
		// mild: z ≈ 1.55, notable: z ≈ 2.71, striking: z ≈ 3.87.
		const mild = scoreSurprise([10, 11, 9, 12, 8, 10], 12);
		const notable = scoreSurprise([10, 11, 9, 12, 8, 10], 13.5);
		const striking = scoreSurprise([10, 11, 9, 12, 8, 10], 15);

		expect(mild?.tier).toBe("mild");
		expect(notable?.tier).toBe("notable");
		expect(striking?.tier).toBe("striking");
	});

	it("flags the baseline and stdDev it actually used", () => {
		const score = scoreSurprise([4, 6, 4, 6, 4, 6], 5);
		expect(score?.baseline).toBeCloseTo(5, 6);
		expect(score?.stdDev).toBeCloseTo(1, 6);
	});
});

describe("rankBySurprise", () => {
	const samples: MetricSample[] = [
		{
			key: "reach",
			label: "Reach",
			history: [1000, 1050, 980, 1020, 990, 1010],
			current: 2500,
		},
		{
			key: "eqs",
			label: "EQS",
			history: [55, 56, 54, 57, 55, 56],
			current: 56,
		},
		{
			key: "follows",
			label: "New Follows",
			history: [10, 12, 11, 9, 10, 11],
			current: 4,
		},
		{
			key: "comments",
			label: "Comments",
			history: [50, 48, 52, 49, 51, 50],
			current: 51,
		},
	];

	it("orders by absolute magnitude, descending", () => {
		const ranked = rankBySurprise(samples);
		expect(ranked[0].key).toBe("reach");
		expect(ranked[1].key).toBe("follows");
		// Stable, low-magnitude metrics fall off even before limit.
		expect(ranked.map((r) => r.key)).not.toContain("eqs");
	});

	it("respects the limit parameter", () => {
		const ranked = rankBySurprise(samples, 1);
		expect(ranked).toHaveLength(1);
		expect(ranked[0].key).toBe("reach");
	});

	it("drops metrics with insufficient history", () => {
		const ranked = rankBySurprise([
			...samples,
			{ key: "brand-new", label: "New Metric", history: [1, 2], current: 99 },
		]);
		expect(ranked.map((r) => r.key)).not.toContain("brand-new");
	});
});
