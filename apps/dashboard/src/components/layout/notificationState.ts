import type { Notification as AppNotification } from "@/types/index";

export function applyNotificationLocalState<T extends AppNotification>(
	notifications: readonly T[],
	state: {
		readIds: ReadonlySet<string>;
		deletedIds: ReadonlySet<string>;
	},
): T[] {
	return notifications
		.filter((notification) => !state.deletedIds.has(notification.id))
		.map((notification) => {
			if (!state.readIds.has(notification.id) || notification.read) {
				return notification;
			}
			return { ...notification, read: true };
		});
}
