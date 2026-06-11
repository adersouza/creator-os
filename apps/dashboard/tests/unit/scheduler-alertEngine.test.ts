import { describe, expect, it } from "vitest";

import {
	isActionableSilentOutcome,
	shouldAlertEmptyPool,
} from "../../api/_lib/cron/scheduler/alertEngine";

describe("scheduler alert engine", () => {
	it("treats warm-up and eligibility skip outcomes as expected silence", () => {
		for (const outcome of [
			"skipped_daily_cap",
			"skipped_outside_window",
			"skipped_min_interval",
			"skipped_weekend",
			"skipped_blocked",
			"skipped_no_content",
		]) {
			expect(isActionableSilentOutcome(outcome)).toBe(false);
		}
	});

	it("keeps supply and execution failures actionable", () => {
		for (const outcome of ["error"]) {
			expect(isActionableSilentOutcome(outcome)).toBe(true);
		}
	});

	it("alerts on empty pool only when recent no-content decisions have no ready queue", () => {
		expect(
			shouldAlertEmptyPool(
				["skipped_no_content", "skipped_no_content", "skipped_no_content"],
				0,
			),
		).toBe(true);
		expect(
			shouldAlertEmptyPool(
				["skipped_no_content", "skipped_no_content", "skipped_no_content"],
				2,
			),
		).toBe(false);
		expect(
			shouldAlertEmptyPool(
				["skipped_no_content", "skipped_outside_window", "skipped_no_content"],
				0,
			),
		).toBe(false);
	});
});
