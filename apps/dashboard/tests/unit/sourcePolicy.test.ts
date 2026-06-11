import { describe, expect, it } from "vitest";

import {
	DIRECT_COMPETITOR_SHARE,
	getRequiredCompetitorSlots,
	isCompetitorSourced,
} from "../../api/_lib/handlers/auto-post/sourcePolicy";

describe("sourcePolicy", () => {
	it("treats competitor direct and copy as competitor-sourced", () => {
		expect(isCompetitorSourced("competitor_direct_microcopy")).toBe(true);
		expect(isCompetitorSourced("competitor_direct")).toBe(true);
		expect(isCompetitorSourced("competitor_copy")).toBe(true);
		expect(isCompetitorSourced("ai")).toBe(false);
		expect(isCompetitorSourced("trending")).toBe(false);
	});

	it("requires enough competitor slots to keep the projected queue at target share", () => {
		expect(
			getRequiredCompetitorSlots({
				currentQueueSize: 35,
				currentCompetitorCount: 19,
				slotsAvailable: 10,
			}),
		).toBe(0);
	});

	it("never asks for more competitor slots than remain available", () => {
		expect(
			getRequiredCompetitorSlots({
				currentQueueSize: 20,
				currentCompetitorCount: 0,
				slotsAvailable: 4,
			}),
		).toBe(3);
	});

	it("calculates the incremental competitor slots needed when already close to target", () => {
		expect(
			getRequiredCompetitorSlots({
				currentQueueSize: 10,
				currentCompetitorCount: 9,
				slotsAvailable: 4,
			}),
		).toBe(
			Math.max(0, Math.ceil((10 + 4) * DIRECT_COMPETITOR_SHARE) - 9),
		);
	});
});
