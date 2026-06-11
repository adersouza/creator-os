/**
 * Unified reply/comment/DM send endpoint for the juno33 operator inbox.
 * Action: "send"
 *
 * Frontend contract: src/services/api/posts.ts::sendReply
 * Body: { platform, accountId, replyToId, conversationId?, content, kind, replyToUsername? }
 * Success: { success: true, replyId }
 * Failure: { error: string } with non-2xx status
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiSuccess,
	apiError,
	badRequest,
	notFound,
	serverError,
} from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { resolveSendAccount } from "../../resolveAccount.js";
import { getSupabase } from "../../supabase.js";
import {
	type ExecutorResult,
	executeIgCommentReply,
	executeIgDm,
	executeThreadsReply,
} from "./executors.js";
import { SendReplySchema } from "./shared.js";

type ReplyRateLimitResult = {
	allowed?: boolean;
	reason?: string | null;
};

type ReplyTargetVerification =
	| { ok: true }
	| { ok: false; status: 400 | 403 | 404 | 409; message: string };

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

export async function handleSendReply(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = SendReplySchema.safeParse(req.body);
	if (!parsed.success) {
		return badRequest(res, `Invalid input: ${parsed.error.issues[0]?.message}`);
	}
	const {
		platform,
		accountId,
		replyToId,
		conversationId,
		context,
		content,
		kind,
		replyToUsername,
	} = parsed.data;

	const sendAccount = await resolveSendAccount(accountId, userId);
	if (!sendAccount.ok) {
		return apiError(res, sendAccount.status, sendAccount.message);
	}
	const resolved = sendAccount.account;

	if (resolved.platform !== platform) {
		return badRequest(
			res,
			`Account is a ${resolved.platform} account but request targeted ${platform}`,
		);
	}

	if (!resolved.encryptedToken || !resolved.platformUserId) {
		return badRequest(
			res,
			`Account is not connected to ${platform === "instagram" ? "Instagram" : "Threads"}`,
		);
	}

	// Validate kind × platform combinations up front — cheaper than failing at
	// Graph call time with a cryptic error.
	if (kind === "dm" && platform !== "instagram") {
		return badRequest(res, "Direct messages are only supported on Instagram");
	}
	if (kind === "reply" && platform !== "threads") {
		return badRequest(res, "Thread replies are only supported on Threads");
	}
	if (kind === "comment" && platform !== "instagram") {
		return badRequest(res, "Comment replies are only supported on Instagram");
	}

	const targetVerification = await verifyReplyTargetContext({
		userId,
		accountId,
		platform,
		kind,
		replyToId,
		conversationId,
		lastSeenAt: context?.lastSeenAt,
	});
	if (!targetVerification.ok) {
		return apiError(
			res,
			targetVerification.status,
			targetVerification.message,
			{
				code:
					targetVerification.status === 409
						? "STALE_INBOX_CONTEXT"
						: "REPLY_TARGET_INVALID",
			},
		);
	}

	// Atomic rate-limit check shared with action=post — protects each account
	// from blowing its daily reply quota even across the two inbox surfaces.
	const { data: rateCheck, error: rateError } = await getSupabase().rpc(
		"check_reply_rate_limit",
		{
			p_account_id: accountId,
			p_hourly_limit: 55,
			p_daily_limit: 480,
		},
	);
	if (rateError) {
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

	let execution: ExecutorResult;
	if (kind === "reply") {
		execution = await executeThreadsReply(resolved, { replyToId, content });
	} else if (kind === "comment") {
		execution = await executeIgCommentReply(resolved, { replyToId, content });
	} else {
		// kind === 'dm' → resolve the recipient IGSID from the cached conversation.
		const dmId = conversationId ?? replyToId;
		const { data: dmRow, error: dmErr } = await getSupabase()
			.from("inbox_dm_cache")
			.select("participant_id")
			.eq("id", dmId)
			.eq("user_id", userId)
			.eq("account_id", accountId)
			.maybeSingle();

		if (dmErr) {
			logger.error("DM conversation lookup failed", {
				error: dmErr.message,
				dmId,
			});
			return serverError(res, "Failed to look up conversation");
		}
		const recipientId = (dmRow as { participant_id?: string | undefined } | null)
			?.participant_id;
		if (!recipientId) {
			return notFound(
				res,
				"Conversation not found or missing recipient. Sync the inbox and try again.",
			);
		}

		execution = await executeIgDm(resolved, { recipientId, content });
	}

	if (execution.ok === false) {
		logger.error("Send executor failed", {
			platform,
			kind,
			accountId,
			error: execution.message,
		});
		return serverError(res, execution.message);
	}

	try {
		await getSupabase()
			.from("sent_replies")
			.insert({
				user_id: userId,
				account_id: accountId,
				threads_reply_id: execution.replyId, // reused for IG comment/DM ids too
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
		const platformLabel = platform === "instagram" ? "Instagram" : "Threads";
		const kindLabel =
			kind === "dm" ? "DM" : kind === "comment" ? "Comment reply" : "Reply";
		await createNotification({
			userId,
			type: "reply_sent",
			title: `${kindLabel} sent on ${platformLabel}`,
			message: replyToUsername
				? `Replied to @${replyToUsername}`
				: `${kindLabel} posted on ${platformLabel}`,
			data: { replyId: execution.replyId, replyToId, accountId, kind },
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

async function verifyReplyTargetContext(args: {
	userId: string;
	accountId: string;
	platform: "threads" | "instagram";
	kind: "dm" | "comment" | "reply";
	replyToId: string;
	conversationId?: string | undefined;
	lastSeenAt?: string | undefined;
}): Promise<ReplyTargetVerification> {
	const db = getSupabase();
	const lastSeenMs = args.lastSeenAt ? Date.parse(args.lastSeenAt) : null;
	const hasFreshnessGuard = lastSeenMs !== null && Number.isFinite(lastSeenMs);
	const lastSeenIso = hasFreshnessGuard
		? new Date(lastSeenMs as number).toISOString()
		: null;

	if (args.kind === "dm") {
		const dmId = args.conversationId ?? args.replyToId;
		const { data, error } = await db
			.from("inbox_dm_cache")
			.select("id, account_id, user_id, last_message_at, updated_at")
			.eq("id", dmId)
			.eq("user_id", args.userId)
			.eq("account_id", args.accountId)
			.maybeSingle();
		if (error) {
			logger.error("DM target verification failed", { error: error.message });
			return { ok: false, status: 400, message: "Could not verify DM target" };
		}
		if (!data) {
			return {
				ok: false,
				status: 404,
				message: "Conversation not found or no longer belongs to this account",
			};
		}
		const latest = Date.parse(data.last_message_at ?? data.updated_at ?? "");
		if (
			hasFreshnessGuard &&
			Number.isFinite(latest) &&
			latest > (lastSeenMs as number) + 5000
		) {
			return {
				ok: false,
				status: 409,
				message: "This DM has newer activity. Refresh the thread before replying.",
			};
		}
		return { ok: true };
	}

	if (args.kind === "comment") {
		const { data, error } = await db
			.from("ig_comments")
			.select("id, account_id, post_id, media_id, created_at, posts!inner(user_id, instagram_account_id)")
			.eq("comment_id", args.replyToId)
			.maybeSingle();
		if (error) {
			logger.error("IG comment target verification failed", {
				error: error.message,
			});
			return {
				ok: false,
				status: 400,
				message: "Could not verify Instagram comment target",
			};
		}
		const row = data as
			| {
					account_id?: string | null | undefined;
					post_id?: string | null | undefined;
					media_id?: string | null | undefined;
					created_at?: string | null | undefined;
					posts?: { user_id?: string | null | undefined; instagram_account_id?: string | null | undefined } | null | undefined;
			  }
			| null;
		const ownerAccountId = row?.account_id ?? row?.posts?.instagram_account_id ?? null;
		if (!row || row.posts?.user_id !== args.userId || ownerAccountId !== args.accountId) {
			return {
				ok: false,
				status: 404,
				message: "Comment not found or no longer belongs to this account",
			};
		}
		if (lastSeenIso && row.post_id) {
			const { count } = await db
				.from("ig_comments")
				.select("id", { count: "exact", head: true })
				.eq("post_id", row.post_id)
				.gt("created_at", lastSeenIso);
			if ((count ?? 0) > 0) {
				return {
					ok: false,
					status: 409,
					message:
						"This comment thread has newer activity. Refresh the thread before replying.",
				};
			}
		}
		return { ok: true };
	}

	// Threads reply targets can be either one of our published posts or an
	// incoming reply on one of those posts. Verify both paths before posting.
	const { data: post } = await db
		.from("posts")
		.select("id, account_id, user_id, published_at")
		.eq("threads_post_id", args.replyToId)
		.eq("account_id", args.accountId)
		.eq("user_id", args.userId)
		.maybeSingle();
	if (post) return { ok: true };

	const { data: reply, error: replyError } = await db
		.from("post_replies")
		.select("id, post_id, created_at, posts!inner(id, account_id, user_id)")
		.eq("threads_reply_id", args.replyToId)
		.maybeSingle();
	if (replyError) {
		logger.error("Threads reply target verification failed", {
			error: replyError.message,
		});
		return {
			ok: false,
			status: 400,
			message: "Could not verify Threads reply target",
		};
	}
	const replyRow = reply as
		| {
				post_id?: string | null | undefined;
				created_at?: string | null | undefined;
				posts?: { id?: string | null | undefined; account_id?: string | null | undefined; user_id?: string | null | undefined } | null | undefined;
		  }
		| null;
	if (!replyRow || replyRow.posts?.account_id !== args.accountId || replyRow.posts?.user_id !== args.userId) {
		return {
			ok: false,
			status: 404,
			message: "Reply target not found or no longer belongs to this account",
		};
	}
	if (lastSeenIso && replyRow.post_id) {
		const { count } = await db
			.from("post_replies")
			.select("id", { count: "exact", head: true })
			.eq("post_id", replyRow.post_id)
			.gt("created_at", lastSeenIso);
		if ((count ?? 0) > 0) {
			return {
				ok: false,
				status: 409,
				message:
					"This Threads reply thread has newer activity. Refresh before replying.",
			};
		}
	}
	return { ok: true };
}
