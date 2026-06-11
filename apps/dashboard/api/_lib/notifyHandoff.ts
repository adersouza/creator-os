import { logger } from "./logger.js";
import { getSupabaseAny } from "./supabase.js";
import { sendWebPushToUser } from "./webPushDelivery.js";

const db = () => getSupabaseAny();
const MAX_REMINDERS = 2;
const REMINDER_INTERVAL_MS = 15 * 60 * 1000;

type NotifyPostRow = {
	id: string;
	user_id: string;
	content: string | null;
	status: string | null;
	platform: string | null;
	publish_mode: string | null;
	handoff_status: string | null;
	notification_sent_at: string | null;
	reminder_count: number | null;
	instagram_accounts?: { username?: string | null } | null;
};

export type NotifyHandoffResult =
	| { result: "notified"; pushSent: boolean }
	| { result: "skipped"; error: string };

function canSendReminder(post: NotifyPostRow, nowMs: number): boolean {
	if (!post.notification_sent_at) return true;
	if ((post.reminder_count ?? 0) >= MAX_REMINDERS) return false;
	const lastSent = Date.parse(post.notification_sent_at);
	if (!Number.isFinite(lastSent)) return true;
	return nowMs - lastSent >= REMINDER_INTERVAL_MS;
}

export async function notifyInstagramHandoff(
	postId: string,
	source = "scheduled",
): Promise<NotifyHandoffResult> {
	const { data: post, error } = (await db()
		.from("posts")
		.select(
			`
			id,
			user_id,
			content,
			status,
			platform,
			publish_mode,
			handoff_status,
			notification_sent_at,
			reminder_count,
			instagram_accounts(username)
		`,
		)
		.eq("id", postId)
		.maybeSingle()) as {
		data: NotifyPostRow | null;
		error: { message?: string | undefined } | null;
	};

	if (error || !post) return { result: "skipped", error: "not_found" };
	if (post.status !== "scheduled") {
		return { result: "skipped", error: post.status || "status_changed" };
	}
	if (post.platform !== "instagram" || post.publish_mode !== "notify") {
		return { result: "skipped", error: "not_notify_mode" };
	}
	if (post.handoff_status === "completed") {
		return { result: "skipped", error: "completed" };
	}
	if (!canSendReminder(post, Date.now())) {
		return { result: "skipped", error: "reminder_window" };
	}

	const now = new Date().toISOString();
	const nextReminderCount = post.notification_sent_at
		? (post.reminder_count ?? 0) + 1
		: (post.reminder_count ?? 0);
	const handle = post.instagram_accounts?.username
		? `@${post.instagram_accounts.username}`
		: "Instagram";

	await db().from("notifications").insert({
		user_id: post.user_id,
		type: "publish_reminder",
		title: "Time to publish",
		message: `Your scheduled ${handle} post is ready for manual publishing.`,
		read: false,
		data: { postId: post.id, platform: "instagram", source },
	});

	const push = await sendWebPushToUser(post.user_id, {
		title: "Time to publish",
		body: "Your Instagram post is ready.",
		tag: `handoff-${post.id}`,
		requireInteraction: true,
		data: { url: `/handoff/${post.id}`, postId: post.id, platform: "instagram" },
	});
	const handoffStatus = push.sent > 0 ? "notified" : "notification_unavailable";

	await db()
		.from("posts")
		.update({
			handoff_status: handoffStatus,
			notification_sent_at: now,
			reminder_count: nextReminderCount,
			updated_at: now,
		})
		.eq("id", post.id)
		.eq("status", "scheduled")
		.eq("publish_mode", "notify");

	logger.info("[notify-handoff] Reminder sent", {
		postId,
		userId: post.user_id,
		source,
		push,
		handoffStatus,
		reminderCount: nextReminderCount,
	});

	return { result: "notified", pushSent: push.sent > 0 };
}
