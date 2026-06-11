/**
 * Graph-API executors for reply/comment/DM send.
 *
 * Pure functions — no req/res. Shared by `action=post` (legacy inbox) and
 * `action=send` (unified operator inbox). Keeping these isolated means the
 * router handlers stay thin and the Graph calls stay testable.
 */

import { decrypt } from "../../encryption.js";
import {
	replyToComment as igReplyToComment,
	sendMessage as igSendMessage,
} from "../../instagramApi.js";
import { logger } from "../../logger.js";
import type { ResolvedAccount } from "../../resolveAccount.js";
import { withRetry } from "../../retryUtils.js";

export type ExecutorResult =
	| { ok: true; replyId: string }
	| { ok: false; status: number; message: string };

export interface ThreadsReplyParams {
	replyToId: string;
	content: string;
	media?: { type: "image" | "video"; url: string } | undefined;
}

export async function executeThreadsReply(
	resolved: ResolvedAccount,
	params: ThreadsReplyParams,
): Promise<ExecutorResult> {
	const token = decrypt(resolved.encryptedToken);

	const containerParams = new URLSearchParams({
		media_type: params.media
			? params.media.type === "image"
				? "IMAGE"
				: "VIDEO"
			: "TEXT",
		text: params.content,
		reply_to_id: params.replyToId,
	});

	if (params.media) {
		const mediaKey = params.media.type === "image" ? "image_url" : "video_url";
		containerParams.append(mediaKey, params.media.url);
	}

	const containerResponse = await withRetry(() =>
		fetch(`https://graph.threads.net/v1.0/${resolved.platformUserId}/threads`, {
			method: "POST",
			body: containerParams,
			headers: { Authorization: `Bearer ${token}` },
			signal: AbortSignal.timeout(15000),
		}),
	);

	const containerData = await containerResponse.json();

	if (!containerResponse.ok || containerData.error) {
		return {
			ok: false,
			status: 502,
			message:
				containerData.error?.message || "Failed to create reply container",
		};
	}

	type PublishResponse = {
		id?: string | undefined;
		error?: { message?: string | undefined; error_subcode?: number | undefined } | undefined;
	};
	let publishData: PublishResponse = {};
	let publishResponse: Response = new Response();
	for (let attempt = 0; attempt < 5; attempt++) {
		await new Promise((resolve) =>
			setTimeout(resolve, attempt === 0 ? 2000 : 3000),
		);
		const publishParams = new URLSearchParams({
			creation_id: containerData.id,
		});
		publishResponse = await withRetry(() =>
			fetch(
				`https://graph.threads.net/v1.0/${resolved.platformUserId}/threads_publish`,
				{
					method: "POST",
					body: publishParams,
					headers: { Authorization: `Bearer ${token}` },
					signal: AbortSignal.timeout(15000),
				},
			),
		);
		publishData = (await publishResponse.json()) as PublishResponse;
		if (publishResponse.ok && !publishData.error) break;
		const subcode = publishData?.error?.error_subcode;
		// 2207026/2207051 = media not ready — retry. Any other error is terminal.
		if (subcode !== 2207026 && subcode !== 2207051) break;
		logger.info("Reply container not ready, retrying", { attempt, subcode });
	}

	if (!publishResponse.ok || publishData.error || !publishData.id) {
		return {
			ok: false,
			status: 502,
			message: publishData.error?.message || "Failed to publish reply",
		};
	}

	return { ok: true, replyId: publishData.id };
}

export interface IgCommentReplyParams {
	replyToId: string;
	content: string;
}

export async function executeIgCommentReply(
	resolved: ResolvedAccount,
	params: IgCommentReplyParams,
): Promise<ExecutorResult> {
	const result = await igReplyToComment(
		resolved.encryptedToken,
		params.replyToId,
		params.content,
		resolved.loginType,
	);
	if (!result.success || !result.commentId) {
		return {
			ok: false,
			status: 502,
			message: result.error || "Failed to reply to Instagram comment",
		};
	}
	return { ok: true, replyId: result.commentId };
}

export interface IgDmParams {
	recipientId: string;
	content: string;
}

export async function executeIgDm(
	resolved: ResolvedAccount,
	params: IgDmParams,
): Promise<ExecutorResult> {
	const result = await igSendMessage(
		resolved.encryptedToken,
		resolved.platformUserId,
		params.recipientId,
		params.content,
		resolved.loginType,
	);
	if (!result.success || !result.messageId) {
		return {
			ok: false,
			status: 502,
			message: result.error || "Failed to send Instagram DM",
		};
	}
	return { ok: true, replyId: result.messageId };
}
