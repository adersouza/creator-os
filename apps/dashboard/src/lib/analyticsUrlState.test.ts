import { describe, expect, it } from "vitest";
import {
	DEFAULT_STATE,
	parseState,
	serializeState,
	type AnalyticsState,
} from "@/lib/analyticsUrlState";

describe("analyticsUrlState", () => {
	it("defaults to the overview tab and omits it from clean URLs", () => {
		const state = parseState(new URLSearchParams());

		expect(state.tab).toBe("overview");
		expect(serializeState(state).has("tab")).toBe(false);
	});

	it("parses and serializes non-default tabs", () => {
		const state = parseState(new URLSearchParams("tab=posts&p=threads"));

		expect(state.tab).toBe("posts");
		expect(state.platform).toBe("threads");
		expect(serializeState(state).get("tab")).toBe("posts");
	});

	it("falls back to overview for unknown tab values", () => {
		const state = parseState(new URLSearchParams("tab=ops-health"));

		expect(state.tab).toBe("overview");
	});

	it("keeps existing filter serialization stable with a tab present", () => {
		const state: AnalyticsState = {
			...DEFAULT_STATE,
			tab: "accounts",
			platform: "ig",
			compare: "off",
		};
		const serialized = serializeState(state);

		expect(serialized.get("tab")).toBe("accounts");
		expect(serialized.get("p")).toBe("ig");
		expect(serialized.get("c")).toBe("off");
	});
});
