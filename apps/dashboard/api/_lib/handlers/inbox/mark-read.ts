import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";

type UserDb = DbContext["userDb"];

function readSource(messageId: string):
	| "ig_mention"
	| "threads_mention"
	| "threads_reply"
	| "ig_comment"
	| "ig_dm"
	| "fallback" {
	if (messageId.startsWith("ig_mention_")) return "ig_mention";
	if (messageId.startsWith("threads_mention_")) return "threads_mention";
	if (messageId.startsWith("threads_reply_")) return "threads_reply";
	if (messageId.startsWith("ig_comment_")) return "ig_comment";
	if (messageId.startsWith("ig_dm_")) return "ig_dm";
	return "fallback";
}

function stripPrefix(messageId: string, prefix: string): string {
	return messageId.startsWith(prefix) ? messageId.slice(prefix.length) : messageId;
}

async function upsertReadSetting(
	userDb: UserDb,
	userId: string,
	messageId: string,
	read: boolean,
) {
	const settingKey = "inbox_read_message_ids";
	const { data } = await userDb
		.from("user_settings")
		.select("setting_value")
		.eq("user_id", userId)
		.eq("setting_key", settingKey)
		.maybeSingle();

	const settingValue = data?.setting_value;
	const existing = Array.isArray(settingValue) ? settingValue : [];
	const next = read
		? Array.from(new Set([...existing, messageId]))
		: existing.filter((value) => value !== messageId);
	await userDb.from("user_settings").upsert({
		user_id: userId,
		setting_key: settingKey,
		setting_value: next,
	});
}

async function updateOperatorInboxTask(
	userDb: UserDb,
	userId: string,
	source: Exclude<ReturnType<typeof readSource>, "fallback">,
	messageId: string,
	read: boolean,
) {
	const sourceId = `${source}:${stripPrefix(messageId, `${source}_`)}`;
	await userDb
		.from("operator_tasks")
		.update({
			status: read ? "resolved" : "open",
			resolution_reason: read ? "Marked done from Inbox" : null,
			resolved_at: read ? new Date().toISOString() : null,
			snoozed_until: null,
			updated_at: new Date().toISOString(),
		})
		.eq("user_id", userId)
		.eq("source", "inbox_attention")
		.eq("source_id", sourceId);
}

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, context) => {
		const { user, userDb } = context;
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		const messageId = req.body?.messageId;
		if (typeof messageId !== "string" || messageId.trim().length === 0) {
			return apiError(res, 400, "messageId is required");
		}
		const read = req.body?.read !== false;

		try {
			const source = readSource(messageId);

			if (source === "ig_mention") {
				await userDb
					.from("ig_mentions")
					.update({ is_read: read })
					.eq("id", stripPrefix(messageId, "ig_mention_"))
					.eq("user_id", user.id);
			} else if (source === "threads_mention") {
				await userDb
					.from("mentions")
					.update({ is_read: read })
					.eq("id", stripPrefix(messageId, "threads_mention_"))
					.eq("user_id", user.id);
			} else if (source === "threads_reply") {
				const replyId = stripPrefix(messageId, "threads_reply_");
				const { data: reply } = await userDb
					.from("post_replies")
					.select("id, post_id")
					.eq("id", replyId)
					.maybeSingle();

				if (reply?.post_id) {
					const { data: post } = await userDb
						.from("posts")
						.select("id")
						.eq("id", reply.post_id)
						.eq("user_id", user.id)
						.maybeSingle();
					if (post?.id) {
						await userDb
							.from("post_replies")
							.update({ is_read: read })
							.eq("id", replyId);
					}
				}
			} else if (source === "ig_comment") {
				const commentId = stripPrefix(messageId, "ig_comment_");
				const { data: comment } = await userDb
					.from("ig_comments")
					.select("id, post_id")
					.eq("id", commentId)
					.maybeSingle();
				if (comment?.post_id) {
					const { data: post } = await userDb
						.from("posts")
						.select("id")
						.eq("id", comment.post_id)
						.eq("user_id", user.id)
						.maybeSingle();
					if (post?.id) {
						await userDb
							.from("ig_comments")
							.update({ is_read: read })
							.eq("id", commentId);
					}
				}
			} else if (source === "ig_dm") {
				await userDb
					.from("inbox_dm_cache")
					.update({ is_read: read })
					.eq("id", stripPrefix(messageId, "ig_dm_"))
					.eq("user_id", user.id);
			} else {
				await upsertReadSetting(userDb, user.id, messageId, read);
			}
			if (source !== "fallback") {
				await updateOperatorInboxTask(userDb, user.id, source, messageId, read);
			}

			return apiSuccess(res, { success: true });
		} catch (error) {
			logger.warn("[inbox/mark-read] Failed to mark message as read", {
				messageId,
				error: String(error),
			});
			return apiError(res, 500, "Internal server error");
		}
	},
);
