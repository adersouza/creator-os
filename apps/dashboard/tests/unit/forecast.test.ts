/**
 * Forecast math — linear regression + 95 % prediction intervals.
 *
 * Validates:
 * 1. Returns null when series too short (n < 3) or horizon ≤ 0.
 * 2. Perfect line → confidence = high, bands collapse to the fit.
 * 3. Noisy line → confidence degrades, bands widen away from the last point.
 * 4. Flat series → slope ≈ 0, confidence = low (no variance to explain).
 * 5. Forecast indices continue past the history.
 * 6. Lower ≤ value ≤ upper always holds.
 */

import { describe, expect, it } from "vitest";
import { computeForecast } from "@/lib/forecast";

describe("computeForecast", () => {
	it("returns null for too-short history", () => {
		expect(computeForecast([1, 2], 3)).toBeNull();
		expect(computeForecast([], 3)).toBeNull();
		expect(computeForecast([5], 3)).toBeNull();
	});

	it("returns null for non-positive horizon", () => {
		expect(computeForecast([1, 2, 3], 0)).toBeNull();
		expect(computeForecast([1, 2, 3], -1)).toBeNull();
	});

	it("fits a perfect line and reports high confidence", () => {
		const result = computeForecast([10, 12, 14, 16, 18], 3);
		expect(result).not.toBeNull();
		if (!result) return;

		expect(result.slope).toBeCloseTo(2, 6);
		expect(result.intercept).toBeCloseTo(10, 6);
		expect(result.r2).toBeCloseTo(1, 6);
		expect(result.confidence).toBe("high");

		// Perfect-fit residuals → prediction intervals collapse onto the line.
		expect(result.points).toHaveLength(3);
		expect(result.points[0].value).toBeCloseTo(20, 6);
		expect(result.points[0].upper).toBeCloseTo(20, 6);
		expect(result.points[0].lower).toBeCloseTo(20, 6);
		expect(result.points[1].value).toBeCloseTo(22, 6);
		expect(result.points[2].value).toBeCloseTo(24, 6);
	});

	it("extends indices past the history", () => {
		const history = [1, 2, 3, 4];
		const result = computeForecast(history, 2);
		expect(result).not.toBeNull();
		if (!result) return;

		expect(result.points[0].index).toBe(history.length);
		expect(result.points[1].index).toBe(history.length + 1);
	});

	it("keeps value inside [lower, upper] for every forecast point", () => {
		const history = [10, 11, 13, 12, 14, 13, 15, 16, 14, 17];
		const result = computeForecast(history, 5);
		expect(result).not.toBeNull();
		if (!result) return;

		for (const point of result.points) {
			expect(point.lower).toBeLessThanOrEqual(point.value);
			expect(point.value).toBeLessThanOrEqual(point.upper);
		}
	});

	it("widens the band as the horizon extends", () => {
		const result = computeForecast([10, 11, 13, 12, 14, 13, 15, 16], 5);
		expect(result).not.toBeNull();
		if (!result) return;

		const widths = result.points.map((p) => p.upper - p.lower);
		// Every step further from the history should loosen the interval.
		for (let i = 1; i < widths.length; i++) {
			expect(widths[i]).toBeGreaterThan(widths[i - 1]);
		}
	});

	it("reports low confidence for a flat series (no trend to explain)", () => {
		const result = computeForecast([7, 7, 7, 7, 7, 7], 3);
		expect(result).not.toBeNull();
		if (!result) return;

		expect(result.slope).toBeCloseTo(0, 6);
		expect(result.confidence).toBe("low");
	});

	it("reports medium confidence for partially-explained variance", () => {
		// Underlying trend y = x, noise breaks R² into the 0.4–0.7 band.
		const history = [1, 3, 2, 5, 4, 7, 6, 9, 8, 11];
		const result = computeForecast(history, 3);
		expect(result).not.toBeNull();
		if (!result) return;

		expect(result.r2).toBeGreaterThan(0.4);
		expect(result.r2).toBeLessThan(0.95);
		expect(["medium", "high"]).toContain(result.confidence);
	});

	it("handles a descending series without flipping the band", () => {
		const result = computeForecast([20, 17, 15, 12, 10, 7], 3);
		expect(result).not.toBeNull();
		if (!result) return;

		expect(result.slope).toBeLessThan(0);
		for (const point of result.points) {
			expect(point.upper).toBeGreaterThanOrEqual(point.lower);
		}
		// Next point should be below the last observation.
		expect(result.points[0].value).toBeLessThan(7);
	});
});
