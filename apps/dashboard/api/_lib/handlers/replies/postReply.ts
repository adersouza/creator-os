/**
 * Handler for posting a reply (Threads or Instagram).
 * Action: "post"
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	badRequest,
	serverError,
} from "../../apiResponse.js";
import { logger } from "../../logger.js";
import {
	enforceOutboundOperatorGuard,
	recordOutboundOperatorResult,
} from "../../outboundOperatorGuard.js";
import { resolveSendAccount } from "../../resolveAccount.js";
import { getSupabase } from "../../supabase.js";
import { executeIgCommentReply, executeThreadsReply } from "./executors.js";
import { PostReplySchema } from "./shared.js";

type ReplyRateLimitResult = {
	allowed?: boolean;
	reason?: string | null;
};

function normalizeReplyRateLimitResult(
	rateCheck: unknown,
): ReplyRateLimitResult | null {
	if (Array.isArray(rateCheck)) {
		return (rateCheck[0] as ReplyRateLimitResult | undefined) ?? null;
	}
	if (rateCheck && typeof rateCheck === "object") {
		return rateCheck as ReplyRateLimitResult;
	}
	return null;
}

export async function handlePostReply(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = PostReplySchema.safeParse(req.body);
	if (!parsed.success) {
		return badRequest(res, `Invalid input: ${parsed.error.issues[0]?.message}`);
	}
	const { accountId, replyToId, content, replyToUsername, media } = parsed.data;
	const threadsMedia =
		media && (media.type === "image" || media.type === "video")
			? { type: media.type, url: media.url }
			: undefined;

	const sendAccount = await resolveSendAccount(accountId, userId);
	if (!sendAccount.ok) {
		return apiError(res, sendAccount.status, sendAccount.message);
	}
	const resolved = sendAccount.account;

	if (!resolved.encryptedToken || !resolved.platformUserId) {
		return badRequest(
			res,
			`Account is not connected to ${resolved.platform === "instagram" ? "Instagram" : "Threads"}`,
		);
	}

	const groupId =
		typeof resolved.raw.group_id === "string" ? resolved.raw.group_id : null;
	const guardPayload = {
		accountId,
		platform: resolved.platform,
		replyToId,
		kind: "reply",
	};
	const outboundGuard = await enforceOutboundOperatorGuard({
		db: getSupabase(),
		req,
		userId,
		actionName: "send_reply",
		riskLevel: "high",
		scope: { groupId, accountId },
		payload: guardPayload,
		idempotencyKey:
			typeof req.headers["x-idempotency-key"] === "string"
				? req.headers["x-idempotency-key"]
				: `send-reply:${accountId}:${replyToId}`,
		metadata: { platform: resolved.platform },
	});
	if (!outboundGuard.allowed) {
		logger.warn("Reply blocked by outbound operator guard", {
			accountId,
			replyToId,
			code: outboundGuard.code,
			reason: outboundGuard.reason,
		});
		return apiError(res, 403, outboundGuard.reason);
	}

	// ---- Rate limit check (atomic via DB function to prevent race conditions) ----
	const { data: rateCheck, error: rateError } = await getSupabase().rpc(
		"check_reply_rate_limit",
		{
			p_account_id: accountId,
			p_hourly_limit: 55,
			p_daily_limit: 480,
		},
	);

	if (rateError) {
		// Fail closed — deny on error
		logger.error("Reply rate limit check failed", { error: rateError.message });
		return badRequest(res, "Rate limit check failed. Please try again.");
	}

	const rateResult = normalizeReplyRateLimitResult(rateCheck);
	if (rateResult?.allowed !== true) {
		return badRequest(
			res,
			rateResult?.reason || "Rate limit exceeded for replies.",
		);
	}

	const execution =
		resolved.platform === "instagram"
			? await executeIgCommentReply(resolved, { replyToId, content })
			: await executeThreadsReply(resolved, {
					replyToId,
					content,
					...(threadsMedia ? { media: threadsMedia } : {}),
				});

	if (execution.ok === false) {
		await recordOutboundOperatorResult({
			db: getSupabase(),
			req,
			userId,
			actionName: "send_reply",
			riskLevel: "high",
			scope: { groupId, accountId },
			payload: guardPayload,
			idempotencyKey:
				typeof req.headers["x-idempotency-key"] === "string"
					? req.headers["x-idempotency-key"]
					: `send-reply:${accountId}:${replyToId}`,
			outcome: "failure",
			message: "reply executor failed",
			error: execution.message,
			metadata: { platform: resolved.platform },
		});
		logger.error("Reply executor failed", {
			platform: resolved.platform,
			accountId,
			error: execution.message,
		});
		return serverError(res, execution.message);
	}
	await recordOutboundOperatorResult({
		db: getSupabase(),
		req,
		userId,
		actionName: "send_reply",
		riskLevel: "high",
		scope: { groupId, accountId },
		payload: guardPayload,
		idempotencyKey:
			typeof req.headers["x-idempotency-key"] === "string"
				? req.headers["x-idempotency-key"]
				: `send-reply:${accountId}:${replyToId}`,
		outcome: "success",
		message: "reply sent",
		metadata: { platform: resolved.platform, replyId: execution.replyId },
	});

	try {
		await getSupabase()
			.from("sent_replies")
			.insert({
				user_id: userId,
				account_id: accountId,
				threads_reply_id: execution.replyId, // reused for IG comment IDs too
				reply_to_id: replyToId,
				reply_to_username: replyToUsername || null,
				content,
				account_handle: resolved.username || "",
				// biome-ignore lint/suspicious/noExplicitAny: Supabase insert type workaround
			} as any);
	} catch (error) {
		logger.warn("Reply was sent but sent_replies insert failed", {
			accountId,
			replyId: execution.replyId,
			error: String(error),
		});
	}

	try {
		const { createNotification } = await import("../../createNotification.js");
		const platformLabel =
			resolved.platform === "instagram" ? "Instagram" : "Threads";
		await createNotification({
			userId,
			type: "reply_sent",
			title: `Reply sent on ${platformLabel}`,
			message: replyToUsername
				? `Replied to @${replyToUsername}`
				: `Reply posted on ${platformLabel}`,
			data: { replyId: execution.replyId, replyToId, accountId },
		});
	} catch (error) {
		logger.warn("Reply was sent but notification failed", {
			accountId,
			replyId: execution.replyId,
			error: String(error),
		});
	}

	return apiSuccess(res, { replyId: execution.replyId });
}
