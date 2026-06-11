/**
 * Instagram Messages API Route
 * POST /api/instagram/messages?action=conversations|messages|send
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

// ============================================================================
// Row / API Types
// ============================================================================

interface IgAccountRow {
	instagram_access_token_encrypted: string;
	instagram_user_id: string;
	login_type: string;
	is_active?: boolean | null | undefined;
	needs_reauth?: boolean | null | undefined;
	status?: string | null | undefined;
	token_expires_at?: string | null | undefined;
}

import { apiError, apiSuccess, handleIgAuthError } from "../../apiResponse.js";
import { trackUsage } from "../../auditLog.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { withIdempotency } from "../../idempotency.js";
import { enforceRouteRateLimit } from "../../routeRateLimit.js";
import { sanitizeMessage } from "../../sanitize.js";
import { getSupabase } from "../../supabase.js";
import { getAccountLifecycleBlock } from "../../resolveAccount.js";
import { z } from "../../zodCompat.js";

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
): Promise<void> {
	try {
		const { data } = await getSupabase()
			.from("ig_endpoint_rate_limits")
			.select("requests_this_hour")
			.eq("account_id", accountId)
			.eq("endpoint", endpoint)
			.maybeSingle();

		const hourlyUsed = data?.requests_this_hour || 0;

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
	} catch (err) {
		logger.debug("Failed to set rate-limit headers for IG messages", {
			error: String(err),
		});
		// Non-blocking — don't fail the request if we can't set headers
	}
}

const ConversationsSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	after: z.string().optional(),
});

const MessagesSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	conversationId: z.string().min(1, "conversationId is required"),
	after: z.string().optional(),
});

const SendSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	recipientId: z.string().min(1, "recipientId is required"),
	message: z
		.string()
		.min(1, "message is required")
		.max(1000, "Message cannot exceed 1000 characters")
		.refine(
			(val) => new TextEncoder().encode(val).length <= 1000,
			"Message cannot exceed 1000 bytes (emoji and non-Latin characters use more bytes)",
		),
	tag: z.string().optional(),
});

const SendMediaSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	recipientId: z.string().min(1, "recipientId is required"),
	mediaUrl: z.string().url("mediaUrl must be a valid URL"),
	mediaType: z.string(),
});

const SenderActionSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	recipientId: z.string().min(1, "recipientId is required"),
	action: z.string(),
});

const SendImagesSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	recipientId: z.string().min(1, "recipientId is required"),
	imageUrls: z
		.array(z.string().url())
		.min(1, "At least one image URL is required")
		.max(10, "Maximum 10 images per message"),
});

const SEND_ACTIONS = new Set([
	"send",
	"send-media",
	"sender-action",
	"send-images",
	"quick-replies",
	"generic-template",
	"reaction",
	"share-post",
	"heart-sticker",
	"button-template",
]);

function rejectBlockedIgSendAccount(
	res: VercelResponse,
	account: IgAccountRow,
): VercelResponse | null {
	const blockReason = getAccountLifecycleBlock(account);
	if (!blockReason) return null;
	return apiError(
		res,
		403,
		`${blockReason}. Reconnect or reactivate the Instagram account before sending.`,
	);
}

async function handleConversations(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = ConversationsSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, after } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select(
			"instagram_access_token_encrypted, instagram_user_id, login_type, is_active, needs_reauth, status, token_expires_at",
		)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}

	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}
	const lifecycleBlock = rejectBlockedIgSendAccount(res, account);
	if (lifecycleBlock) return lifecycleBlock;

	const loginType = account.login_type || "instagram";
	logger.info("[IG Messages] Fetching conversations", { accountId, loginType });

	const { getConversations } = await import("../../instagramApi.js");

	const result = await getConversations(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
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

	return apiSuccess(res, {
		conversations: result.conversations,
		paging: result.paging,
	});
}

async function handleMessages(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = MessagesSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, conversationId, after } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}

	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}
	const lifecycleBlock = rejectBlockedIgSendAccount(res, account);
	if (lifecycleBlock) return lifecycleBlock;

	const loginType = account.login_type || "instagram";
	logger.info("[IG Messages] Fetching messages for conversation", {
		conversationId,
		loginType,
	});

	const { getConversationMessages } = await import("../../instagramApi.js");

	const result = await getConversationMessages(
		account.instagram_access_token_encrypted,
		conversationId,
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

	return apiSuccess(res, {
		messages: result.messages,
		paging: result.paging,
	});
}

async function handleSend(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = SendSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, recipientId, message, tag } = parsed.data;

	// Check rate limit: 100 messages/hour
	const { data: rateLimitData } = await getSupabase().rpc(
		"check_ig_endpoint_limit",
		{
			p_account_id: accountId,
			p_endpoint: "messages",
			p_hourly_limit: 100,
			p_daily_limit: 0, // No daily limit for messages
		},
	);
	const rateResult = rateLimitData?.[0];
	if (rateResult && !rateResult.allowed) {
		await setEndpointRateLimitHeaders(res, accountId, "messages", 100);
		return apiError(res, 429, rateResult.reason || "Rate limit exceeded");
	}

	// Set rate limit headers on successful check (so frontend sees remaining quota)
	await setEndpointRateLimitHeaders(res, accountId, "messages", 100);

	// Sanitize user input to prevent XSS
	const sanitizedMessage = sanitizeMessage(message);

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select(
			"instagram_access_token_encrypted, instagram_user_id, login_type, is_active, needs_reauth, status, token_expires_at",
		)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}

	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const loginType = account.login_type || "instagram";
	logger.info("[IG Messages] Sending message", { accountId, loginType });

	const { sendMessage } = await import("../../instagramApi.js");

	const result = await sendMessage(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		recipientId,
		sanitizedMessage,
		loginType,
		tag,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	try {
		const { createNotification } = await import("../../createNotification.js");
		await createNotification({
			userId,
			type: "dm_sent",
			title: "DM sent",
			message: `Sent a direct message on Instagram`,
			data: { messageId: result.messageId, recipientId, accountId },
		});
	} catch (error) {
		logger.warn("[IG Messages] Message sent but notification failed", {
			accountId,
			messageId: result.messageId,
			error: String(error),
		});
	}

	return apiSuccess(res, { messageId: result.messageId });
}

async function handleSendMedia(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = SendMediaSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, recipientId, mediaUrl, mediaType } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select(
			"instagram_access_token_encrypted, instagram_user_id, login_type, is_active, needs_reauth, status, token_expires_at",
		)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

	if (accountError || !account)
		return apiError(res, 404, "Instagram account not found");
	if (!account.instagram_access_token_encrypted)
		return apiError(res, 400, "Account token not available");
	const lifecycleBlock = rejectBlockedIgSendAccount(res, account);
	if (lifecycleBlock) return lifecycleBlock;

	const loginType = account.login_type || "instagram";
	const { sendMediaMessage } = await import("../../instagramApi.js");

	const result = await sendMediaMessage(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		recipientId,
		mediaUrl,
		mediaType as "image" | "video" | "audio" | "file",
		loginType,
	);

	if (!result.success)
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	return apiSuccess(res, { messageId: result.messageId });
}

async function handleSenderAction(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = SenderActionSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, recipientId, action } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select(
			"instagram_access_token_encrypted, instagram_user_id, login_type, is_active, needs_reauth, status, token_expires_at",
		)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

	if (accountError || !account)
		return apiError(res, 404, "Instagram account not found");
	if (!account.instagram_access_token_encrypted)
		return apiError(res, 400, "Account token not available");
	const lifecycleBlock = rejectBlockedIgSendAccount(res, account);
	if (lifecycleBlock) return lifecycleBlock;

	const loginType = account.login_type || "instagram";
	const { sendSenderAction } = await import("../../instagramApi.js");

	const result = await sendSenderAction(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		recipientId,
		action as "typing_on" | "typing_off" | "mark_seen",
		loginType,
	);

	if (!result.success)
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	return apiSuccess(res, { success: true });
}

async function handleSendImages(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = SendImagesSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, recipientId, imageUrls } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

	if (accountError || !account)
		return apiError(res, 404, "Instagram account not found");
	if (!account.instagram_access_token_encrypted)
		return apiError(res, 400, "Account token not available");

	const loginType = account.login_type || "instagram";
	const { sendMultiImageMessage } = await import("../../instagramApi.js");

	const result = await sendMultiImageMessage(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		recipientId,
		imageUrls,
		loginType,
	);

	if (!result.success)
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	return apiSuccess(res, { messageId: result.messageId });
}

// ============================================================================
// Button Template
// ============================================================================

const ButtonTemplateSchema = z.object({
	accountId: z.string().min(1),
	recipientId: z.string().min(1),
	text: z.string().min(1).max(640),
	buttons: z
		.array(
			z.object({
				type: z.string(),
				title: z.string().min(1),
				url: z.string().url().optional(),
				payload: z.string().optional(),
			}),
		)
		.min(1)
		.max(3),
});

async function handleButtonTemplate(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = ButtonTemplateSchema.safeParse(req.body);
	if (!parsed.success)
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	const { accountId, recipientId, text, buttons } = parsed.data;

	const { data: account } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

	if (!account?.instagram_access_token_encrypted)
		return apiError(res, 404, "Account not found or no token");

	const { sendButtonTemplate } = await import("../../instagramApi.js");
	const result = await sendButtonTemplate(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		recipientId,
		text,
		buttons,
		account.login_type || "instagram",
	);
	if (!result.success)
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	return apiSuccess(res, { messageId: result.messageId });
}

// ============================================================================
// User Profile (IGSID-based, requires message consent)
// ============================================================================

const UserProfileSchema = z.object({
	accountId: z.string().min(1),
	igsid: z.string().min(1, "Instagram-scoped user ID is required"),
});

async function handleUserProfile(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = UserProfileSchema.safeParse(req.body);
	if (!parsed.success)
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	const { accountId, igsid } = parsed.data;

	const { data: account } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

	if (!account?.instagram_access_token_encrypted)
		return apiError(res, 404, "Account not found or no token");

	const { getUserProfile } = await import("../../instagramApi.js");
	const result = await getUserProfile(
		account.instagram_access_token_encrypted,
		igsid,
		account.login_type || "instagram",
	);
	if (!result.success)
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	return apiSuccess(res, { profile: result.profile });
}

// ============================================================================
// Quick Replies
// ============================================================================

const QuickRepliesSchema = z.object({
	accountId: z.string().min(1),
	recipientId: z.string().min(1),
	text: z.string().min(1).max(1000),
	quickReplies: z
		.array(
			z.object({
				content_type: z.string(),
				title: z.string().min(1).max(20),
				payload: z.string().min(1),
			}),
		)
		.min(1)
		.max(13),
});

async function handleQuickReplies(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = QuickRepliesSchema.safeParse(req.body);
	if (!parsed.success)
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	const { accountId, recipientId, text, quickReplies } = parsed.data;

	const { data: account } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

	if (!account?.instagram_access_token_encrypted)
		return apiError(res, 404, "Account not found or no token");

	const { sendQuickReplies } = await import("../../instagramApi.js");
	const result = await sendQuickReplies(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		recipientId,
		text,
		quickReplies,
		account.login_type || "instagram",
	);
	if (!result.success)
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	return apiSuccess(res, { messageId: result.messageId });
}

// ============================================================================
// Generic Template
// ============================================================================

const GenericTemplateSchema = z.object({
	accountId: z.string().min(1),
	recipientId: z.string().min(1),
	elements: z
		.array(
			z.object({
				title: z.string().min(1).max(80),
				subtitle: z.string().max(80).optional(),
				image_url: z.string().url().optional(),
				default_action: z
					.object({ type: z.string(), url: z.string().url() })
					.optional(),
				buttons: z
					.array(
						z.object({
							type: z.string(),
							title: z.string().min(1),
							url: z.string().url().optional(),
							payload: z.string().optional(),
						}),
					)
					.max(3)
					.optional(),
			}),
		)
		.min(1)
		.max(10),
});

async function handleGenericTemplate(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = GenericTemplateSchema.safeParse(req.body);
	if (!parsed.success)
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	const { accountId, recipientId, elements } = parsed.data;

	const { data: account } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

	if (!account?.instagram_access_token_encrypted)
		return apiError(res, 404, "Account not found or no token");

	const { sendGenericTemplate } = await import("../../instagramApi.js");
	const result = await sendGenericTemplate(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		recipientId,
		elements,
		account.login_type || "instagram",
	);
	if (!result.success)
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	return apiSuccess(res, { messageId: result.messageId });
}

// ============================================================================
// Message Reaction
// ============================================================================

const ReactionSchema = z.object({
	accountId: z.string().min(1),
	recipientId: z.string().min(1),
	messageId: z.string().min(1),
	reaction: z.string().optional().nullable(),
});

async function handleReaction(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = ReactionSchema.safeParse(req.body);
	if (!parsed.success)
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	const { accountId, recipientId, messageId, reaction } = parsed.data;

	const { data: account } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

	if (!account?.instagram_access_token_encrypted)
		return apiError(res, 404, "Account not found or no token");

	const { sendMessageReaction } = await import("../../instagramApi.js");
	const result = await sendMessageReaction(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		recipientId,
		messageId,
		reaction,
		account.login_type || "instagram",
	);
	if (!result.success)
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	return apiSuccess(res, { success: true });
}

// ============================================================================
// Share Post via DM
// ============================================================================

const SharePostSchema = z.object({
	accountId: z.string().min(1),
	recipientId: z.string().min(1),
	postId: z.string().min(1),
});

async function handleSharePost(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = SharePostSchema.safeParse(req.body);
	if (!parsed.success)
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	const { accountId, recipientId, postId } = parsed.data;

	const { data: account } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

	if (!account?.instagram_access_token_encrypted)
		return apiError(res, 404, "Account not found or no token");

	const { sendPostShare } = await import("../../instagramApi.js");
	const result = await sendPostShare(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		recipientId,
		postId,
		account.login_type || "instagram",
	);
	if (!result.success)
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	return apiSuccess(res, { messageId: result.messageId });
}

// ============================================================================
// Heart Sticker
// ============================================================================

const HeartStickerSchema = z.object({
	accountId: z.string().min(1),
	recipientId: z.string().min(1),
});

async function handleHeartSticker(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = HeartStickerSchema.safeParse(req.body);
	if (!parsed.success)
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	const { accountId, recipientId } = parsed.data;

	const { data: account } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: IgAccountRow | null; error: unknown };

	if (!account?.instagram_access_token_encrypted)
		return apiError(res, 404, "Account not found or no token");

	const { sendHeartSticker } = await import("../../instagramApi.js");
	const result = await sendHeartSticker(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		recipientId,
		account.login_type || "instagram",
	);
	if (!result.success)
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	return apiSuccess(res, { messageId: result.messageId });
}

// ============================================================================
// Sync Inbox — backfill DMs from Meta API into local DB
// ============================================================================

const SyncInboxSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	isBackfill: z.boolean().optional().default(false),
});

async function handleSyncInbox(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = SyncInboxSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(res, 400, "Invalid input");
	}
	const { accountId, isBackfill } = parsed.data;
	const supabase = getSupabase();

	// Verify account ownership
	const { data: account, error: accountError } = (await supabase
		.from("instagram_accounts")
		.select(
			"instagram_access_token_encrypted, instagram_user_id, login_type, id, user_id",
		)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as {
		data: (IgAccountRow & { id: string; user_id: string }) | null;
		error: unknown;
	};

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}
	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const loginType = account.login_type || "instagram";
	const maxPages = isBackfill ? 5 : 1;
	let totalConversations = 0;
	let totalMessages = 0;

	logger.info("[IG Messages] Syncing inbox to local DB", {
		accountId,
		isBackfill,
		maxPages,
	});

	const { getConversations, getConversationMessages } = await import(
		"../../instagramApi.js"
	);

	let cursor: string | undefined;
	for (let page = 0; page < maxPages; page++) {
		const convResult = await getConversations(
			account.instagram_access_token_encrypted,
			account.instagram_user_id,
			cursor,
			loginType,
		);

		if (!convResult.success || !convResult.conversations?.length) break;

		// Upsert conversation summaries into inbox_dm_cache
		// biome-ignore lint/suspicious/noExplicitAny: Meta API conversation shape is untyped
		const cacheRows = convResult.conversations.map((conv: any) => {
			const participants = conv.participants?.data || [];
			const msgs = conv.messages?.data || [];
			const lastMsg = msgs[0];
			return {
				id: conv.id,
				user_id: userId,
				account_id: accountId,
				participant_id: participants[0]?.id || "",
				participant_username: participants[0]?.username || "Unknown",
				last_message_text: lastMsg?.is_unsupported
					? "(Unsupported message type)"
					: lastMsg?.message || "(no messages)",
				last_message_at:
					conv.updated_time ||
					lastMsg?.created_time ||
					new Date().toISOString(),
				conversation_name: conv.name || null,
				updated_at: new Date().toISOString(),
			};
		});

		// biome-ignore lint/suspicious/noExplicitAny: Supabase type depth
		await (supabase as any)
			.from("inbox_dm_cache")
			.upsert(cacheRows, { onConflict: "id" });
		totalConversations += cacheRows.length;

		// Fetch messages for each conversation
		for (const conv of convResult.conversations) {
			const msgResult = await getConversationMessages(
				account.instagram_access_token_encrypted,
				conv.id,
				undefined,
				loginType,
			);

			if (msgResult.success && msgResult.messages?.length) {
				// biome-ignore lint/suspicious/noExplicitAny: Meta API message shape is untyped
				const msgRows = msgResult.messages.map((msg: any) => ({
					id: msg.id,
					conversation_id: conv.id,
					ig_account_id: accountId,
					user_id: userId,
					sender_id: msg.from?.id || null,
					sender_username: msg.from?.username || msg.from?.name || null,
					message_text: msg.message || null,
					is_echo: msg.from?.id === account.instagram_user_id,
					created_at: msg.created_time || new Date().toISOString(),
				}));

				// biome-ignore lint/suspicious/noExplicitAny: Supabase type depth
				await (supabase as any)
					.from("inbox_dm_messages")
					.upsert(msgRows, { onConflict: "id" });
				totalMessages += msgRows.length;
			}
		}

		cursor = convResult.paging?.cursors?.after;
		if (!cursor) break;
	}

	// Update sync cursor + timestamp
	// biome-ignore lint/suspicious/noExplicitAny: Supabase type depth
	await (supabase as any)
		.from("instagram_accounts")
		.update({
			last_dm_sync_cursor: cursor || null,
			last_dm_sync_at: new Date().toISOString(),
		})
		.eq("id", accountId);

	logger.info("[IG Messages] Inbox sync complete", {
		accountId,
		totalConversations,
		totalMessages,
		isBackfill,
	});

	return apiSuccess(res, {
		synced: true,
		conversations: totalConversations,
		messages: totalMessages,
	});
}

export default withAuth(async (req, res, user) => {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const userId = user.id;
	const action = req.query.action as string;

	try {
		if (SEND_ACTIONS.has(action)) {
			const body = (req.body ?? {}) as { accountId?: unknown | undefined };
			const accountKey =
				typeof body.accountId === "string" && body.accountId.trim()
					? body.accountId.trim()
					: `unknown-user-${userId}`;
			const allowed = await enforceRouteRateLimit(res, {
				key: `ig-messages-send:account:${accountKey}:minute`,
				limit: 30,
				windowSeconds: 60,
				failMode: "closed",
				message: "Too many Instagram message sends. Try again shortly.",
			});
			if (!allowed) return;
		}

		switch (action) {
			case "conversations":
				return handleConversations(req, res, userId);
			case "messages":
				return handleMessages(req, res, userId);
			case "send":
				trackUsage(userId, "instagram.messages.send");
				return withIdempotency(
					req,
					res,
					{
						userId,
						route: "/api/instagram/messages",
						action,
						enabled: true,
						requireKey: true,
						failClosed: true,
					},
					() => handleSend(req, res, userId),
				);
			case "send-media":
				return withIdempotency(
					req,
					res,
					{
						userId,
						route: "/api/instagram/messages",
						action,
						enabled: true,
						requireKey: true,
						failClosed: true,
					},
					() => handleSendMedia(req, res, userId),
				);
			case "sender-action":
				return handleSenderAction(req, res, userId);
			case "send-images":
				return withIdempotency(
					req,
					res,
					{
						userId,
						route: "/api/instagram/messages",
						action,
						enabled: true,
						requireKey: true,
						failClosed: true,
					},
					() => handleSendImages(req, res, userId),
				);
			case "user-profile":
				return handleUserProfile(req, res, userId);
			case "quick-replies":
				trackUsage(userId, "instagram.messages.quickReplies");
				return withIdempotency(
					req,
					res,
					{
						userId,
						route: "/api/instagram/messages",
						action,
						enabled: true,
						requireKey: true,
						failClosed: true,
					},
					() => handleQuickReplies(req, res, userId),
				);
			case "generic-template":
				trackUsage(userId, "instagram.messages.genericTemplate");
				return withIdempotency(
					req,
					res,
					{
						userId,
						route: "/api/instagram/messages",
						action,
						enabled: true,
						requireKey: true,
						failClosed: true,
					},
					() => handleGenericTemplate(req, res, userId),
				);
			case "reaction":
				return withIdempotency(
					req,
					res,
					{
						userId,
						route: "/api/instagram/messages",
						action,
						enabled: true,
						requireKey: true,
						failClosed: true,
					},
					() => handleReaction(req, res, userId),
				);
			case "share-post":
				return withIdempotency(
					req,
					res,
					{
						userId,
						route: "/api/instagram/messages",
						action,
						enabled: true,
						requireKey: true,
						failClosed: true,
					},
					() => handleSharePost(req, res, userId),
				);
			case "heart-sticker":
				return withIdempotency(
					req,
					res,
					{
						userId,
						route: "/api/instagram/messages",
						action,
						enabled: true,
						requireKey: true,
						failClosed: true,
					},
					() => handleHeartSticker(req, res, userId),
				);
			case "sync-inbox":
				return handleSyncInbox(req, res, userId);
			case "button-template":
				trackUsage(userId, "instagram.messages.buttonTemplate");
				return withIdempotency(
					req,
					res,
					{
						userId,
						route: "/api/instagram/messages",
						action,
						enabled: true,
						requireKey: true,
						failClosed: true,
					},
					() => handleButtonTemplate(req, res, userId),
				);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Instagram messages API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
