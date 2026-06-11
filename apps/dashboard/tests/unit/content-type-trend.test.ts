import { describe, expect, it } from "vitest";
import { shouldUseUnscopedPostFallback } from "@/api/_lib/handlers/analytics-sub/content-type-trend";

describe("content-type-trend fallback scope", () => {
	it("does not fall back to all user posts for an explicitly selected scope", () => {
		expect(shouldUseUnscopedPostFallback(true, 0)).toBe(false);
	});

	it("allows legacy all-user post fallback only for unscoped fleet requests", () => {
		expect(shouldUseUnscopedPostFallback(false, 0)).toBe(true);
		expect(shouldUseUnscopedPostFallback(false, 2)).toBe(false);
	});
});
