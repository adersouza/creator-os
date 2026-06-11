import { describe, expect, it } from "vitest";
import { hasMinimumEngagerRetentionSignal } from "./EngagerRetentionTile.helpers";

describe("hasMinimumEngagerRetentionSignal", () => {
	it("allows three returning engagers across at least seven days", () => {
		expect(
			hasMinimumEngagerRetentionSignal({
				returningCount: 3,
				totalUnique: 3,
				periodDays: 7,
			}),
		).toBe(true);
	});

	it("requires the returning engager window to cover at least seven days", () => {
		expect(
			hasMinimumEngagerRetentionSignal({
				returningCount: 3,
				totalUnique: 49,
				periodDays: 6,
			}),
		).toBe(false);
	});

	it("hides low unique counts without repeat signal", () => {
		expect(
			hasMinimumEngagerRetentionSignal({
				returningCount: 2,
				totalUnique: 49,
				periodDays: 30,
			}),
		).toBe(false);
	});

	it("allows broad samples at fifty unique engagers", () => {
		expect(
			hasMinimumEngagerRetentionSignal({
				returningCount: 0,
				totalUnique: 50,
				periodDays: 1,
			}),
		).toBe(true);
	});
});
