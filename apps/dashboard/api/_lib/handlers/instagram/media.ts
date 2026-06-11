/**
 * Instagram Media API Route
 * POST /api/instagram/media?action=delete
 * POST /api/instagram/media?action=collaborative-list
 * POST /api/instagram/media?action=collaborative-search
 * POST /api/instagram/media?action=like
 * POST /api/instagram/media?action=unlike
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, handleIgAuthError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { z } from "../../zodCompat.js";

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

const DeleteSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	mediaId: z.string().min(1, "mediaId is required"),
	postId: z.string().optional(),
});

const CollaborativeListSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	limit: z.number().int().min(1).max(100).optional(),
});

const CollaborativeSearchSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	mediaId: z.string().min(1, "mediaId is required"),
});

const LikeSchema = z
	.object({
		accountId: z.string().min(1, "accountId is required"),
		mediaId: z.string().optional(),
		commentId: z.string().optional(),
	})
	.refine((data) => Boolean(data.mediaId || data.commentId), {
		message: "mediaId or commentId is required",
	});

type InstagramMediaAccount = {
	instagram_user_id: string;
	instagram_access_token_encrypted: string;
	login_type: string | null;
};

async function verifyLikeTargetOwnership(args: {
	userId: string;
	accountId: string;
	mediaId?: string | undefined;
	commentId?: string | undefined;
}): Promise<{ ok: true } | { ok: false; message: string }> {
	const db = getSupabase();
	if (args.commentId) {
		const { data } = await db
			.from("ig_comments")
			.select("id, account_id, posts!inner(user_id, instagram_account_id)")
			.eq("comment_id", args.commentId)
			.maybeSingle();
		const row = data as
			| {
					account_id?: string | null | undefined;
					posts?: { user_id?: string | null | undefined; instagram_account_id?: string | null | undefined } | null | undefined;
			  }
			| null;
		const ownerAccountId = row?.account_id ?? row?.posts?.instagram_account_id ?? null;
		if (!row || row.posts?.user_id !== args.userId || ownerAccountId !== args.accountId) {
			return {
				ok: false,
				message: "Comment not found or no longer belongs to this account",
			};
		}
		return { ok: true };
	}

	if (args.mediaId) {
		const { data } = await db
			.from("posts")
			.select("id")
			.eq("instagram_post_id", args.mediaId)
			.eq("instagram_account_id", args.accountId)
			.eq("user_id", args.userId)
			.maybeSingle();
		if (!data) {
			return {
				ok: false,
				message: "Media not found or no longer belongs to this account",
			};
		}
	}
	return { ok: true };
}

async function getMediaAccount(accountId: string, userId: string) {
	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_user_id, instagram_access_token_encrypted, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as {
		data: InstagramMediaAccount | null;
		error: { message: string } | null;
	};

	return { account, accountError };
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
	const { accountId, mediaId, postId } = parsed.data;

	const { account, accountError } = await getMediaAccount(accountId, userId);

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}

	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const loginType = account.login_type || "facebook";
	logger.info("[IG Media] Deleting media", { mediaId, loginType });

	if (loginType !== "facebook") {
		return apiError(
			res,
			400,
			"Delete unsupported on Instagram Login accounts.",
			{ code: "media_deletion_unsupported_on_ig_login" },
		);
	}

	const { deleteInstagramMedia } = await import("../../instagramApi.js");

	const result = await deleteInstagramMedia(
		account.instagram_access_token_encrypted,
		mediaId,
		loginType,
	);

	if (!result.success) {
		if (result.code === "media_deletion_unsupported_on_ig_login") {
			return apiError(
				res,
				400,
				result.error || "Delete unsupported on Instagram Login accounts.",
				{ code: result.code },
			);
		}
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	// Also update our database record if postId provided
	if (postId) {
		await getSupabase()
			.from("posts")
			.update({ status: "deleted" })
			.eq("id", postId)
			.eq("user_id", userId);
	}

	return apiSuccess(res);
}

async function handleCollaborativeList(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = CollaborativeListSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, limit } = parsed.data;
	const { account, accountError } = await getMediaAccount(accountId, userId);

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}
	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const { getCollaborativeMedia } = await import("../../instagramApi.js");
	const result = await getCollaborativeMedia(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		account.login_type || "facebook",
		limit,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	return apiSuccess(res, { media: result.media || [] });
}

async function handleCollaborativeSearch(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = CollaborativeSearchSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, mediaId } = parsed.data;
	const { account, accountError } = await getMediaAccount(accountId, userId);

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}
	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const { searchCollaborativeMedia } = await import("../../instagramApi.js");
	const result = await searchCollaborativeMedia(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		mediaId,
		account.login_type || "facebook",
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	return apiSuccess(res, { media: result.media || null });
}

async function handleLike(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	liked: boolean,
) {
	const parsed = LikeSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, mediaId, commentId } = parsed.data;
	const { account, accountError } = await getMediaAccount(accountId, userId);

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}
	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const target = await verifyLikeTargetOwnership({
		userId,
		accountId,
		mediaId,
		commentId,
	});
	if (!target.ok) {
		return apiError(res, 404, target.message, {
			code: "LIKE_TARGET_INVALID",
		});
	}

	const { setInstagramLike } = await import("../../instagramApi.js");
	const result = await setInstagramLike(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		{ mediaId, commentId },
		liked,
		account.login_type || "facebook",
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

export default withAuth(async (req, res, user) => {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const userId = user.id;
	const action = req.query.action as string;

	try {
		switch (action) {
			case "delete":
				return handleDelete(req, res, userId);
			case "collaborative-list":
				return handleCollaborativeList(req, res, userId);
			case "collaborative-search":
				return handleCollaborativeSearch(req, res, userId);
			case "like":
				return handleLike(req, res, userId, true);
			case "unlike":
				return handleLike(req, res, userId, false);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Instagram media API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
