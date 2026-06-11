import { describe, expect, it } from "vitest";
import { getIdeaDraftSummary, getIdeaSignalScore } from "./Ideas";

describe("Ideas display helpers", () => {
	it("scores ideas from source, status, variants, and targeting context", () => {
		const score = getIdeaSignalScore({
			body: "A strong raw note with enough context to shape into a post.",
			source: "voice",
			status: "ready",
			variants: ["variant one", "variant two"],
			linkUrl: "https://example.com",
			imageUrl: null,
			audioUrl: "data:audio/webm;base64,abc",
			transcript: "Voice transcript",
			accountId: "account-1",
			groupId: "group-1",
		});

		expect(score).toBe(96);
	});

	it("summarizes draft buckets without dropping used ideas", () => {
		const summary = getIdeaDraftSummary([
			{ status: "inbox", variants: [] },
			{ status: "shaping", variants: ["one"] },
			{ status: "ready", variants: ["one", "two"] },
			{ status: "used", variants: [] },
		]);

		expect(summary).toEqual({
			inbox: 1,
			shaping: 1,
			ready: 1,
			used: 1,
			variants: 3,
		});
	});
});
