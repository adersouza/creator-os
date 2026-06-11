/**
 * Instagram Saved Media API Route
 * POST /api/instagram/saved-media
 *
 * Returns saved posts for the authenticated user's IG account.
 * Requires `instagram_manage_saved_media` permission.
 */

import { apiError, apiSuccess, handleIgAuthError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { z } from "../../zodCompat.js";

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

const SavedMediaSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	limit: z.number().min(1).max(100).optional(),
});

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

export default withAuth(async (req, res, user) => {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	// #678: Rate limit IG data endpoints
	const { checkRateLimit } = await import("../../rateLimiter.js");
	const rl = await checkRateLimit({
		key: `ig-saved-media:${user.id}`,
		limit: 20,
		windowSeconds: 60,
		failMode: "open",
	});
	if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

	const userId = user.id;
	const parsed = SavedMediaSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message || "Bad request"}`,
		);
	}

	const { accountId, limit } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as {
		data: {
			instagram_access_token_encrypted: string;
			instagram_user_id: string;
			login_type: string;
		} | null;
		error: { message: string } | null;
	};

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}

	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const loginType = account.login_type || "instagram";
	logger.info("[IG SavedMedia] Fetching saved media", {
		accountId,
		loginType,
	});

	const { getSavedMedia } = await import("../../instagramApi.js");

	const result = await getSavedMedia(
		account.instagram_access_token_encrypted,
		account.instagram_user_id,
		loginType,
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

	return apiSuccess(res, { media: result.media });
});
