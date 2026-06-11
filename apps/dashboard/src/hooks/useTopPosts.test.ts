import { describe, expect, it } from "vitest";
import { firstPositive } from "@/hooks/useTopPosts";

describe("useTopPosts metric helpers", () => {
	it("uses later synced distribution metrics when IG reach is zero", () => {
		expect(firstPositive(0, 142, 98)).toBe(142);
		expect(firstPositive(null, 0, 98)).toBe(98);
		expect(firstPositive(undefined, null, 0)).toBe(0);
	});
});
