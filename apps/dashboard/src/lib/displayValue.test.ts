import { describe, expect, it } from "vitest";
import { dash, pct } from "./displayValue";

describe("displayValue", () => {
	it("renders a dash for missing or non-finite values", () => {
		expect(dash(null)).toBe("—");
		expect(dash(undefined)).toBe("—");
		expect(dash(Number.NaN)).toBe("—");
		expect(dash(Number.POSITIVE_INFINITY)).toBe("—");
		expect(pct(null)).toBe("—");
		expect(pct(Number.NEGATIVE_INFINITY)).toBe("—");
	});

	it("renders real zero values when the caller has a real sample", () => {
		expect(dash(0)).toBe("0");
		expect(dash(0, (n) => n.toLocaleString())).toBe("0");
		expect(pct(0, 2)).toBe("0.00%");
	});

	it("formats finite values", () => {
		expect(dash(1234, (n) => `${n / 1000}K`)).toBe("1.234K");
		expect(pct(12.345, 1)).toBe("12.3%");
	});
});
