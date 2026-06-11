/**
 * Instagram Stories API
 * Fetches user's active stories and story insights
 */

import { apiError, apiSuccess, handleIgAuthError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

const db = () => getSupabase();

export default withAuth(async (req, res, user) => {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	// #678: Rate limit IG data endpoints
	const { checkRateLimit } = await import("../../rateLimiter.js");
	const rl = await checkRateLimit({
		key: `ig-stories:${user.id}`,
		limit: 30,
		windowSeconds: 60,
		failMode: "open",
	});
	if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

	const { accountId, action } = req.query;

	if (!accountId || typeof accountId !== "string") {
		return apiError(res, 400, "Missing accountId");
	}

	try {
		const supabase = db();

		// Get account credentials — verify user ownership
		const { data: account, error: accountError } = await supabase
			.from("instagram_accounts")
			.select("instagram_access_token_encrypted, instagram_user_id, login_type")
			.eq("id", accountId)
			.eq("user_id", user.id)
			.maybeSingle();

		if (accountError || !account) {
			return apiError(res, 404, "Account not found");
		}

		if (!account.instagram_access_token_encrypted) {
			return apiError(res, 400, "Account has no access token");
		}

		const { getInstagramStories, getInstagramStoryMetrics } = await import(
			"../../instagramApi.js"
		);
		const loginType = account.login_type || "facebook";

		if (action === "insights") {
			// Get story insights for a specific story
			const { mediaId } = req.query;
			if (!mediaId || typeof mediaId !== "string") {
				return apiError(res, 400, "Missing mediaId for insights");
			}

			// #676: Validate mediaId format to prevent IDOR
			if (mediaId.length > 100 || !/^[\w.-]+$/.test(mediaId)) {
				return apiError(res, 400, "Invalid mediaId format");
			}

			const result = await getInstagramStoryMetrics(
				account.instagram_access_token_encrypted ?? "",
				mediaId,
				loginType,
			);

			if (!result.success) {
				return await handleIgAuthError(
					res,
					accountId as string,
					user.id,
					result.error || "Unknown error",
				);
			}

			return apiSuccess(res, { metrics: result.metrics });
		}

		// Default: Get user's active stories
		const result = await getInstagramStories(
			account.instagram_access_token_encrypted ?? "",
			account.instagram_user_id,
			loginType,
		);

		if (!result.success) {
			return await handleIgAuthError(
				res,
				accountId as string,
				user.id,
				result.error || "Unknown error",
			);
		}

		return apiSuccess(res, { stories: result.stories });
	} catch (error: unknown) {
		logger.error("[Instagram Stories API] Error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
