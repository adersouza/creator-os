/**
 * Create in-app notification helper
 *
 * Inserts into the notifications table (in-app display) and
 * fans out to push + email delivery based on user preferences.
 */

import { logger } from "./logger.js";
import { getSupabase } from "./supabase.js";

interface NotificationParams {
	userId: string;
	type: string;
	title: string;
	message: string;
	data?: Record<string, unknown> | undefined;
}

export async function createNotification({
	userId,
	type,
	title,
	message,
	data,
}: NotificationParams): Promise<void> {
	try {
		const insertPayload = {
			user_id: userId,
			type,
			title,
			message,
			read: false,
			...(data ? { data } : {}),
		};
		const { error } = await getSupabase()
			.from("notifications")
			// biome-ignore lint/suspicious/noExplicitAny: notifications.data column not in generated types
			.insert(insertPayload as any);
		if (error) {
			logger.warn("Failed to create notification", {
				type,
				error: error.message,
			});
		}

		// Fire-and-forget: deliver via push + email
		import("./deliverNotification.js")
			.then(({ deliverNotification }) =>
				deliverNotification({ userId, type, title, message, data }),
			)
			.catch((err) =>
				logger.warn("Notification delivery side-channel failed", {
					type,
					error: String(err),
				}),
			);
	} catch (err) {
		logger.warn("Notification creation error", { type, error: String(err) });
	}
}
