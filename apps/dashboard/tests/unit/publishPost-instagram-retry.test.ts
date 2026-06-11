import { describe, expect, it } from "vitest";
import { shouldRescheduleInstagramFailure } from "@/api/_lib/publishPost.js";

describe("shouldRescheduleInstagramFailure", () => {
	it("reschedules retryable sanitized Instagram errors from Meta", () => {
		const result = shouldRescheduleInstagramFailure(
			{
				error: "An unexpected Instagram error occurred. Please try again.",
				retryable: true,
			},
			0,
			() => false,
		);

		expect(result).toBe(true);
	});

	it("does not reschedule explicitly non-retryable Instagram errors", () => {
		const result = shouldRescheduleInstagramFailure(
			{
				error: "Invalid content. Check your post meets Instagram's guidelines.",
				retryable: false,
			},
			0,
			() => true,
		);

		expect(result).toBe(false);
	});

	it("does not reschedule after the retry budget is exhausted", () => {
		const result = shouldRescheduleInstagramFailure(
			{
				error: "An unexpected Instagram error occurred. Please try again.",
				retryable: true,
			},
			3,
			() => false,
		);

		expect(result).toBe(false);
	});
});
