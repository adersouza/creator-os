/**
 * Replies API Route — thin router that delegates to handler modules.
 * POST /api/replies?action=post|sync|fetch-mentions|manage|sync-metrics|conversation
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError } from "./_lib/apiResponse.js";
import { logAudit, trackUsage } from "./_lib/auditLog.js";
import {
	handleConversation,
	handleFetchMentions,
	handleManageReply,
	handlePostReply,
	handleSendReply,
	handleSync,
	handleSyncMetrics,
} from "./_lib/handlers/replies/index.js";
import { logger } from "./_lib/logger.js";
import type { DbContext } from "./_lib/dbContext.js";
import { withAuthDb } from "./_lib/middleware.js";
import { checkRateLimit } from "./_lib/rateLimiter.js";
import { withIdempotency } from "./_lib/idempotency.js";

export default withAuthDb(async (req, res, context) => {
	const { user, userDb } = context;
	const userId = user.id;

	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const action = req.query.action as string;

	// Per-action rate limits — destructive actions fail-closed, read/sync fail-open
	// Sync actions use batch endpoints (1 API call per sync-all), so limits are per-user not per-account
	const actionLimits: Record<
		string,
		{ limit: number; windowSeconds: number; failMode: "open" | "closed" }
	> = {
		post: { limit: 15, windowSeconds: 60, failMode: "closed" },
		send: { limit: 15, windowSeconds: 60, failMode: "closed" },
		sync: { limit: 10, windowSeconds: 60, failMode: "open" },
		"fetch-mentions": { limit: 10, windowSeconds: 60, failMode: "open" },
		manage: { limit: 30, windowSeconds: 60, failMode: "closed" },
		"sync-metrics": { limit: 10, windowSeconds: 60, failMode: "open" },
		conversation: { limit: 30, windowSeconds: 60, failMode: "open" },
		"mark-read": { limit: 60, windowSeconds: 60, failMode: "closed" },
		"mark-all-read": { limit: 30, windowSeconds: 60, failMode: "closed" },
	};
	const limits = actionLimits[action] || {
		limit: 30,
		windowSeconds: 60,
		failMode: "closed" as const,
	};
	const rl = await checkRateLimit({
		key: `replies:${action || "unknown"}:${userId}`,
		limit: limits.limit,
		windowSeconds: limits.windowSeconds,
		failMode: limits.failMode,
	});
	if (!rl.allowed) {
		if (rl.retryAfterSeconds) {
			res.setHeader("Retry-After", String(rl.retryAfterSeconds));
		}
		logger.warn("Replies rate limited", {
			action,
			userId,
			remaining: rl.remaining,
			retryAfter: rl.retryAfterSeconds,
			reason: rl.reason,
			userAgent: req.headers["user-agent"]?.slice(0, 80),
		});
		const message =
			rl.reason === "redis_unavailable"
				? "Service temporarily unavailable. Please try again shortly."
				: `Too many ${action || "reply"} requests. Please wait a moment.`;
		return apiError(res, 429, message);
	}

	try {
		switch (action) {
			case "post":
				trackUsage(userId, "replies.post");
				logAudit(userId, "reply.post", { req });
				return withIdempotency(
					req,
					res,
					{
						userId,
						route: "/api/replies",
						action: "post",
						enabled: true,
						requireKey: true,
						failClosed: true,
					},
					() => handlePostReply(req, res, userId),
				);
			case "send":
				trackUsage(userId, "replies.send");
				logAudit(userId, "reply.send", { req });
				return withIdempotency(
					req,
					res,
					{
						userId,
						route: "/api/replies",
						action: "send",
						enabled: true,
						requireKey: true,
						failClosed: true,
					},
					() => handleSendReply(req, res, userId),
				);
			case "sync":
				return handleSync(req, res, userId);
			case "fetch-mentions":
				return handleFetchMentions(req, res, userId);
			case "manage":
				return handleManageReply(req, res, userId);
			case "sync-metrics":
				return handleSyncMetrics(req, res, userId);
			case "conversation":
				return handleConversation(req, res, userId);
			case "mark-read":
				return handleMarkReplyRead(req, res, userId, userDb);
			case "mark-all-read":
				return handleMarkAllRepliesRead(req, res, userId, userDb);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Replies API error", {
			error: error instanceof Error ? error.message : String(error),
		});
		return apiError(res, 500, "Internal server error");
	}
});

async function handleMarkReplyRead(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: DbContext["userDb"],
) {
	const replyId =
		typeof req.body?.replyId === "string" ? req.body.replyId : null;
	if (!replyId) return apiError(res, 400, "replyId is required");

	const { data: reply, error: lookupError } = await userDb
		.from("post_replies")
		.select("id, posts!inner(user_id)")
		.eq("id", replyId)
		.eq("posts.user_id", userId)
		.maybeSingle();

	if (lookupError) {
		logger.error("Failed to authorize reply read update", {
			userId,
			replyId,
			error: lookupError.message,
		});
		return apiError(res, 500, "Failed to mark reply as read");
	}
	if (!reply) return apiError(res, 404, "Reply not found");

	const { error } = await userDb
		.from("post_replies")
		.update({ is_read: true })
		.eq("id", replyId);

	if (error) {
		logger.error("Failed to mark reply as read", {
			userId,
			replyId,
			error: error.message,
		});
		return apiError(res, 500, "Failed to mark reply as read");
	}

	return res.status(200).json({ success: true });
}

async function handleMarkAllRepliesRead(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: DbContext["userDb"],
) {
	const postId =
		typeof req.body?.postId === "string" && req.body.postId.length > 0
			? req.body.postId
			: null;
	let postIdsQuery = userDb.from("posts").select("id").eq("user_id", userId);
	if (postId) {
		postIdsQuery = postIdsQuery.eq("id", postId);
	}

	const { data: posts, error: postsError } = await postIdsQuery;
	if (postsError) {
		logger.error("Failed to resolve posts for mark-all-read", {
			userId,
			postId,
			error: postsError.message,
		});
		return apiError(res, 500, "Failed to mark replies as read");
	}

	const postIds = (posts || []).map((post: { id: string }) => post.id);
	if (postIds.length === 0) {
		return res.status(200).json({ success: true, updatedCount: 0 });
	}

	const { data, error } = await userDb
		.from("post_replies")
		.update({ is_read: true })
		.in("post_id", postIds)
		.eq("is_read", false)
		.select("id");

	if (error) {
		logger.error("Failed to mark replies as read", {
			userId,
			postId,
			error: error.message,
		});
		return apiError(res, 500, "Failed to mark replies as read");
	}

	return res.status(200).json({
		success: true,
		updatedCount: Array.isArray(data) ? data.length : 0,
	});
}
