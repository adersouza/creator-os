/**
 * Instagram Mentions API Route
 * POST /api/instagram/mentions?action=tagged|mentioned
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

// Row / API Types
interface IgAccountRow {
	instagram_access_token_encrypted: string | null;
	instagram_user_id: string | null;
	login_type: string | null;
}

interface IgMentionRow {
	media_id: string;
	username: string | null;
	caption: string | null;
	permalink: string | null;
	media_type: string | null;
	mentioned_at: string | null;
}

import { apiError, apiSuccess, handleIgAuthError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { sanitizeMessage } from "../../sanitize.js";
import { getSupabase } from "../../supabase.js";
import { z } from "../../zodCompat.js";

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

const AccountIdSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
});

async function handleTagged(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = AccountIdSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId } = parsed.data;

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
	logger.info("[IG Mentions] Fetching tagged media", { accountId, loginType });

	const { getTaggedMedia } = await import("../../instagramApi.js");

	const result = await getTaggedMedia(
		account.instagram_access_token_encrypted,
		account.instagram_user_id || "",
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

	return apiSuccess(res, { media: result.media });
}

const MentionedSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	mediaId: z.string().optional(),
});

async function handleMentioned(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = MentionedSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, mediaId } = parsed.data;

	// When no mediaId, list all mentions from the ig_mentions table
	if (!mediaId) {
		const { data: mentions, error: mentionsError } = (await getSupabase()
			.from("ig_mentions")
			.select(
				"media_id, username, caption, permalink, media_type, mentioned_at",
			)
			.eq("ig_account_id", accountId)
			.eq("user_id", userId)
			.order("mentioned_at", { ascending: false })
			.limit(50)) as unknown as {
			data: IgMentionRow[] | null;
			error: { message: string } | null;
		};

		if (mentionsError) {
			logger.error("[IG Mentions] Failed to list mentions", {
				error: mentionsError.message,
			});
			return apiError(res, 500, "Failed to fetch mentions");
		}

		const media = (mentions || []).map((m: IgMentionRow) => ({
			id: m.media_id,
			username: m.username,
			caption: m.caption,
			permalink: m.permalink,
			media_type: m.media_type,
			timestamp: m.mentioned_at,
		}));

		return apiSuccess(res, { media });
	}

	// When mediaId is provided, fetch specific mention details from IG API
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
	logger.info("[IG Mentions] Fetching mentioned media", {
		accountId,
		loginType,
	});

	const { getMentionedMedia } = await import("../../instagramApi.js");

	const result = await getMentionedMedia(
		account.instagram_access_token_encrypted,
		account.instagram_user_id || "",
		mediaId,
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

	return apiSuccess(res, { media: result.media });
}

// ============================================================================
// Reply to @Mention
// ============================================================================

const ReplyToMentionSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	mediaId: z.string().min(1, "mediaId is required"),
	message: z.string().min(1, "message is required"),
	commentId: z.string().optional(),
});

async function handleReplyToMention(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = ReplyToMentionSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, mediaId, message: replyMessage, commentId } = parsed.data;
	const sanitizedReply = sanitizeMessage(replyMessage);

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
	logger.info("[IG Mentions] Replying to mention", {
		accountId,
		mediaId,
		commentId,
		loginType,
	});

	const { replyToMention } = await import("../../instagramApi.js");

	const result = await replyToMention(
		account.instagram_access_token_encrypted,
		account.instagram_user_id || "",
		mediaId,
		sanitizedReply,
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

	return apiSuccess(res, { commentId: result.commentId });
}

export default withAuth(async (req, res, user) => {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const userId = user.id;
	const action = req.query.action as string;

	try {
		switch (action) {
			case "tagged":
				return handleTagged(req, res, userId);
			case "mentioned":
				return handleMentioned(req, res, userId);
			case "reply":
				return handleReplyToMention(req, res, userId);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Instagram mentions API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
