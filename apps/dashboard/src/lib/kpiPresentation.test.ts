import { describe, expect, it } from "vitest";
import {
	KPI_PRESENTATION,
	deltaDirection,
	formatCompact,
	formatDelta,
	formatPercent,
	kpiDescription,
	kpiLabel,
} from "./kpiPresentation";

describe("kpiPresentation", () => {
	it("keeps follower percentage movement labeled as follower growth", () => {
		expect(kpiLabel("followerGrowth")).toBe("Follower growth");
		expect(KPI_PRESENTATION.followerGrowth.label).not.toMatch(/new|net/i);
		expect(kpiDescription("followerGrowth")).toContain("Follower movement");
	});

	it("formats compact counts consistently", () => {
		expect(formatCompact(0)).toBe("0");
		expect(formatCompact(950)).toBe("950");
		expect(formatCompact(1250)).toBe("1.3K");
		expect(formatCompact(null)).toBe("0");
	});

	it("formats percent values without fake zeroes for unavailable data", () => {
		expect(formatPercent(12.34)).toBe("12.3%");
		expect(formatPercent(null)).toBe("Unavailable");
		expect(formatPercent(Number.NaN)).toBe("Unavailable");
		expect(formatPercent(null, "Pending")).toBe("Pending");
	});

	it("formats deltas and classifies movement", () => {
		expect(formatDelta(null)).toBe("No prior");
		expect(formatDelta(2.24)).toBe("+2.2%");
		expect(formatDelta(-1.26)).toBe("-1.3%");
		expect(formatDelta(4.22, "pp")).toBe("+4.2pp");
		expect(deltaDirection(null)).toBe("flat");
		expect(deltaDirection(0.05)).toBe("flat");
		expect(deltaDirection(0.2)).toBe("up");
		expect(deltaDirection(-0.2)).toBe("down");
	});
});
