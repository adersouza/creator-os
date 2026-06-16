import { describe, expect, it } from "vitest";
import { NotificationType, type Notification } from "@/types/index";
import { applyNotificationLocalState } from "./notificationState";

const notification = (
	id: string,
	overrides: Partial<Notification> = {},
): Notification => ({
	id,
	type: NotificationType.POST_PUBLISHED,
	title: `Notification ${id}`,
	message: "A notification message",
	read: false,
	priority: "medium",
	createdAt: new Date("2026-06-16T12:00:00Z"),
	...overrides,
});

describe("notification local state", () => {
	it("keeps optimistically read notifications read when a stale server snapshot arrives", () => {
		const staleSnapshot = [
			notification("one", { read: false }),
			notification("two", { read: false }),
		];

		const next = applyNotificationLocalState(staleSnapshot, {
			readIds: new Set(["one"]),
			deletedIds: new Set(),
		});

		expect(next).toHaveLength(2);
		expect(next.find((item) => item.id === "one")?.read).toBe(true);
		expect(next.find((item) => item.id === "two")?.read).toBe(false);
	});

	it("keeps optimistically deleted notifications hidden when a stale server snapshot arrives", () => {
		const staleSnapshot = [
			notification("one"),
			notification("two"),
			notification("three"),
		];

		const next = applyNotificationLocalState(staleSnapshot, {
			readIds: new Set(),
			deletedIds: new Set(["two"]),
		});

		expect(next.map((item) => item.id)).toEqual(["one", "three"]);
	});

	it("applies deletes before read overrides", () => {
		const staleSnapshot = [notification("one"), notification("two")];

		const next = applyNotificationLocalState(staleSnapshot, {
			readIds: new Set(["one", "two"]),
			deletedIds: new Set(["two"]),
		});

		expect(next).toHaveLength(1);
		expect(next[0]?.id).toBe("one");
		expect(next[0]?.read).toBe(true);
	});
});
