import { describe, expect, it } from "vitest";
import { hasMinimumEngagerRetentionSignal } from "./EngagerRetentionTile.helpers";

describe("hasMinimumEngagerRetentionSignal", () => {
	it("requires three retained engagers across at least seven days", () => {
		expect(
			hasMinimumEngagerRetentionSignal({
				returningCount: 3,
				totalUnique: 4,
				periodDays: 7,
			}),
		).toBe(true);
		expect(
			hasMinimumEngagerRetentionSignal({
				returningCount: 3,
				totalUnique: 4,
				periodDays: 6,
			}),
		).toBe(false);
		expect(
			hasMinimumEngagerRetentionSignal({
				returningCount: 2,
				totalUnique: 49,
				periodDays: 30,
			}),
		).toBe(false);
	});

	it("allows broad unique-commenter samples", () => {
		expect(
			hasMinimumEngagerRetentionSignal({
				returningCount: 0,
				totalUnique: 50,
				periodDays: 1,
			}),
		).toBe(true);
	});
});
