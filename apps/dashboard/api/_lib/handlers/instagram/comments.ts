/**
 * Instagram Comments API Route
 * POST /api/instagram/comments?action=list|reply|hide|delete
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

// Row / API Types
interface IgAccountRow {
	instagram_access_token_encrypted: string | null;
	instagram_user_id?: string | null | undefined;
	login_type: string | null;
}

import { apiError, apiSuccess, handleIgAuthError } from "../../apiResponse.js";
import { withIdempotency } from "../../idempotency.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { sanitizeMessage } from "../../sanitize.js";
import { getSupabase } from "../../supabase.js";
import { z } from "../../zodCompat.js";
import { verifyIgAccountOwnership } from "../helpers/verifyOwnership.js";

// ============================================================================
// Rate Limit Header Utility
// ============================================================================

/**
 * Set X-RateLimit-* headers after querying ig_endpoint_rate_limits.
 * The check_ig_endpoint_limit RPC does not return counts, so we query the table directly.
 */
async function setEndpointRateLimitHeaders(
	res: VercelResponse,
	accountId: string,
	endpoint: string,
	hourlyLimit: number,
	dailyLimit: number,
): Promise<void> {
	try {
		const { data } = await getSupabase()
			.from("ig_endpoint_rate_limits")
			.select("requests_this_hour, requests_today")
			.eq("account_id", accountId)
			.eq("endpoint", endpoint)
			.maybeSingle();

		const hourlyUsed = data?.requests_this_hour || 0;
		const dailyUsed = data?.requests_today || 0;

		// Use the stricter of hourly/daily as the primary limit for headers
		if (hourlyLimit > 0) {
			res.setHeader("X-RateLimit-Limit", String(hourlyLimit));
			res.setHeader(
				"X-RateLimit-Remaining",
				String(Math.max(0, hourlyLimit - hourlyUsed)),
			);
			// Reset at next hour boundary
			const now = new Date();
			const nextHour = new Date(
				Date.UTC(
					now.getUTCFullYear(),
					now.getUTCMonth(),
					now.getUTCDate(),
					now.getUTCHours() + 1,
					0,
					0,
				),
			);
			res.setHeader(
				"X-RateLimit-Reset",
				String(Math.floor(nextHour.getTime() / 1000)),
			);
		}
		if (dailyLimit > 0) {
			res.setHeader("X-RateLimit-Daily-Limit", String(dailyLimit));
			res.setHeader(
				"X-RateLimit-Daily-Remaining",
				String(Math.max(0, dailyLimit - dailyUsed)),
			);
		}
	} catch (err) {
		logger.debug("Failed to set rate-limit headers for IG comments", {
			error: String(err),
		});
		// Non-blocking — don't fail the request if we can't set headers
	}
}

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

const ListSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	mediaId: z.string().min(1, "mediaId is required"),
	after: z.string().optional(),
});

const ReplySchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	commentId: z.string().min(1, "commentId is required"),
	message: z.string().min(1, "message is required"),
});

const HideSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	commentId: z.string().min(1, "commentId is required"),
	hide: z.boolean(),
});

const DeleteSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	commentId: z.string().min(1, "commentId is required"),
});

const ToggleCommentsSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	mediaId: z.string().min(1, "mediaId is required"),
	enabled: z.boolean(),
});

const PrivateReplySchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	commentId: z.string().min(1, "commentId is required"),
	message: z.string().min(1, "message is required"),
});

async function handleList(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = ListSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, mediaId, after } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as unknown as {
		data: IgAccountRow | null;
		error: { message: string } | null;
	};

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}

	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const loginType = account.login_type || "instagram";
	logger.info("[IG Comments] Fetching comments for media", {
		mediaId,
		loginType,
	});

	const { getMediaComments } = await import("../../instagramApi.js");

	const result = await getMediaComments(
		account.instagram_access_token_encrypted,
		mediaId,
		after,
		loginType,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	return apiSuccess(res, { comments: result.comments, paging: result.paging });
}

async function handleReply(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = ReplySchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, commentId, message } = parsed.data;

	// Check rate limit: 60 replies/hour, 500/day
	const { data: rateLimitData } = await getSupabase().rpc(
		"check_ig_endpoint_limit",
		{
			p_account_id: accountId,
			p_endpoint: "comments",
			p_hourly_limit: 60,
			p_daily_limit: 500,
		},
	);
	const rateResult = rateLimitData?.[0];
	if (rateResult && !rateResult.allowed) {
		await setEndpointRateLimitHeaders(res, accountId, "comments", 60, 500);
		return apiError(res, 429, rateResult.reason || "Rate limit exceeded");
	}

	// Set rate limit headers on successful check (so frontend sees remaining quota)
	await setEndpointRateLimitHeaders(res, accountId, "comments", 60, 500);

	// Sanitize user input to prevent XSS
	const sanitizedMessage = sanitizeMessage(message);

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as unknown as {
		data: IgAccountRow | null;
		error: { message: string } | null;
	};

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}

	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const loginType = account.login_type || "instagram";
	logger.info("[IG Comments] Replying to comment", { commentId, loginType });

	const { replyToComment } = await import("../../instagramApi.js");

	const result = await replyToComment(
		account.instagram_access_token_encrypted,
		commentId,
		sanitizedMessage,
		loginType,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	// Store sent reply in DB for instant display (local-first)
	try {
		// Look up the parent comment to get its post_id and media_id
		const { data: parentComment } = await getSupabase()
			.from("ig_comments")
			.select("post_id, media_id")
			.eq("comment_id", commentId)
			.maybeSingle();

		if (parentComment) {
			// biome-ignore lint/suspicious/noExplicitAny: ig_comments new columns not in generated types yet
			await (getSupabase() as any).from("ig_comments").upsert(
				{
					comment_id: result.commentId,
					post_id: parentComment.post_id,
					media_id: parentComment.media_id,
					text: sanitizedMessage,
					username: account.instagram_user_id || "",
					ig_user_id: account.instagram_user_id || "",
					parent_comment_id: commentId,
					is_own_reply: true,
					like_count: 0,
					account_id: accountId,
					created_at: new Date().toISOString(),
				},
				{ onConflict: "comment_id" },
			);
		}
	} catch (err) {
		// Non-blocking: reply was already sent successfully
		logger.warn("[IG Comments] Failed to store sent reply in DB", {
			error: String(err),
		});
	}

	try {
		const { createNotification } = await import("../../createNotification.js");
		await createNotification({
			userId,
			type: "comment_replied",
			title: "Comment reply sent",
			message: `Replied to a comment on Instagram`,
			data: { commentId, replyCommentId: result.commentId, accountId },
		});
	} catch (err) {
		logger.warn("[IG Comments] Reply sent but notification failed", {
			commentId,
			replyCommentId: result.commentId,
			error: String(err),
		});
	}

	return apiSuccess(res, { commentId: result.commentId });
}

async function handleHide(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = HideSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, commentId, hide } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as unknown as {
		data: IgAccountRow | null;
		error: { message: string } | null;
	};

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}

	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const loginType = account.login_type || "instagram";
	logger.info("[IG Comments] Hiding comment", { commentId, hide, loginType });

	const { hideComment } = await import("../../instagramApi.js");

	const result = await hideComment(
		account.instagram_access_token_encrypted,
		commentId,
		hide,
		loginType,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	return apiSuccess(res);
}

async function handleDelete(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = DeleteSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, commentId } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as unknown as {
		data: IgAccountRow | null;
		error: { message: string } | null;
	};

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}

	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const loginType = account.login_type || "instagram";
	logger.info("[IG Comments] Deleting comment", { commentId, loginType });

	const { deleteComment } = await import("../../instagramApi.js");

	const result = await deleteComment(
		account.instagram_access_token_encrypted,
		commentId,
		loginType,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	return apiSuccess(res);
}

async function handleToggleComments(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = ToggleCommentsSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, mediaId, enabled } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as unknown as {
		data: IgAccountRow | null;
		error: { message: string } | null;
	};

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}

	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const loginType = account.login_type || "instagram";
	logger.info("[IG Comments] Toggling comments", {
		mediaId,
		enabled,
		loginType,
	});

	const { toggleCommentEnabled } = await import("../../instagramApi.js");

	const result = await toggleCommentEnabled(
		account.instagram_access_token_encrypted,
		mediaId,
		enabled,
		loginType,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	return apiSuccess(res);
}

async function handlePrivateReply(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = PrivateReplySchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, commentId, message } = parsed.data;

	// Sanitize user input
	const sanitizedMessage = sanitizeMessage(message);

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as unknown as {
		data: IgAccountRow | null;
		error: { message: string } | null;
	};

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}

	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const loginType = account.login_type || "instagram";
	logger.info("[IG Comments] Sending private reply", { commentId, loginType });

	const { sendPrivateReply } = await import("../../instagramApi.js");

	const result = await sendPrivateReply(
		account.instagram_access_token_encrypted ?? "",
		account.instagram_user_id ?? "",
		commentId,
		sanitizedMessage,
		loginType,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	return apiSuccess(res);
}

async function handleListLocal(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = ListSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, mediaId } = parsed.data;

	// Verify account ownership before returning comments
	const ownedAccount = await verifyIgAccountOwnership(res, accountId, userId);
	if (!ownedAccount) return;

	// Read comments from ig_comments (local DB) — no Meta API call
	const { data, error: dbError } = await getSupabase()
		.from("ig_comments")
		.select("*")
		.eq("media_id", mediaId)
		.eq("account_id", accountId)
		.order("created_at", { ascending: false })
		.limit(100);

	if (dbError) {
		return apiError(res, 500, "Failed to fetch comments", {
			details: dbError.message,
		});
	}

	// Map to the same shape as the API list response
	const comments = (data || []).map((row: Record<string, unknown>) => ({
		id: row.comment_id || row.id,
		username: row.username || "unknown",
		text: row.text || "",
		timestamp: row.created_at,
		like_count: row.like_count || 0,
		hidden: false,
		parent_id: row.parent_comment_id || undefined,
		from: { id: row.ig_user_id || "", username: row.username || "unknown" },
	}));

	return apiSuccess(res, { comments });
}

export default withAuth(async (req, res, user) => {
	const userId = user.id;

	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const action = req.query.action as string;

	try {
		switch (action) {
			case "list":
				return handleList(req, res, userId);
			case "list-local":
				return handleListLocal(req, res, userId);
			case "reply":
				return withIdempotency(
					req,
					res,
					{
						userId,
						route: "/api/instagram/comments",
						action,
						enabled: true,
						requireKey: true,
						failClosed: true,
					},
					() => handleReply(req, res, userId),
				);
			case "hide":
				return handleHide(req, res, userId);
			case "delete":
				return handleDelete(req, res, userId);
			case "toggle-comments":
				return handleToggleComments(req, res, userId);
			case "private-reply":
				return withIdempotency(
					req,
					res,
					{
						userId,
						route: "/api/instagram/comments",
						action,
						enabled: true,
						requireKey: true,
						failClosed: true,
					},
					() => handlePrivateReply(req, res, userId),
				);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Instagram comments API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
