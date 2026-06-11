import { describe, expect, it } from "vitest";
import { containsTriggerKeyword } from "@/api/_lib/commentToDm";

describe("comment-to-DM keyword matching", () => {
	it("matches keywords on word boundaries", () => {
		expect(containsTriggerKeyword("send me the snap?")).toEqual({
			matched: true,
			keyword: "snap",
		});
	});

	it("does not match short keywords inside unrelated words", () => {
		expect(containsTriggerKeyword("this is a scam")).toEqual({
			matched: false,
		});
	});
});
