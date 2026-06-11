import { describe, expect, it } from "vitest";
import { accountDetailPath, calendarPostPath } from "./deepLinks";

describe("deepLinks", () => {
	it("builds a calendar post URL without a date", () => {
		expect(calendarPostPath("post-1")).toBe("/calendar?postId=post-1");
	});

	it("adds a stable calendar date when the publish timestamp is valid", () => {
		expect(calendarPostPath("post/1", "2026-05-06T16:00:00Z")).toBe(
			"/calendar?postId=post%2F1&date=2026-05-06",
		);
	});

	it("omits invalid calendar dates", () => {
		expect(calendarPostPath("post-1", "not-a-date")).toBe("/calendar?postId=post-1");
	});

	it("builds an encoded account detail URL", () => {
		expect(accountDetailPath("account/1")).toBe("/accounts?id=account%2F1");
	});
});
