import { describe, expect, it } from "vitest";
import { parseCalendarCommand } from "./CommandPalette";
import type { Post } from "./shared";

const posts: Post[] = [
	{
		id: "post-1",
		accountId: "ig-1",
		title: "Launch Reel",
		account: "@juno",
		groupId: "group-1",
		groupName: "Launch",
		groupColor: "#111",
		status: "draft",
		platform: "instagram",
		day: 2,
		hour: 10,
		minute: 0,
	},
];

describe("parseCalendarCommand", () => {
	it.each([
		["open first post wizard", "open_first_post_wizard"],
		["open readiness fixes", "open_readiness"],
		["schedule draft", "schedule_draft"],
		["duplicate post", "duplicate_post"],
		["convert to notify me", "convert_to_notify"],
		["move to next best time", "move_next_best_time"],
	])("maps %s to the non-drag calendar action", (input, action) => {
		expect(parseCalendarCommand(input, posts)?.action).toBe(action);
	});

	it("keeps classic weekday reschedule commands working", () => {
		const preview = parseCalendarCommand("push Wednesday posts to Friday", posts);

		expect(preview?.label).toBe("Move 1 to Friday");
		expect(preview?.diffs[0]?.next).toEqual({ day: 4, hour: 10, minute: 0 });
	});
});
