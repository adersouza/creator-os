// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Instagram Media Proxy — GET /api/instagram/media-proxy?mediaId=<id>
 *
 * Fetches a fresh media URL from the Instagram Graph API for a given media ID.
 * Mirrors the pattern from api/competitor-media.ts for Threads.
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

const db = () => getSupabase();

export default withAuth(async (req, res, user) => {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	const mediaId = req.query.mediaId as string;
	const igAccountId = req.query.igAccountId as string | undefined;
	if (!mediaId) {
		return apiError(res, 400, "mediaId is required");
	}

	// Get user's IG accounts with valid tokens
	const { data: igAccounts } = await db()
		.from("instagram_accounts")
		.select("id, instagram_access_token_encrypted")
		.eq("user_id", user.id)
		.not("instagram_access_token_encrypted", "is", null)
		.order("created_at", { ascending: false });

	if (!igAccounts?.length) {
		return apiError(res, 400, "No connected Instagram account");
	}

	// Use the specified account if provided, otherwise fall back to most recent
	const igAccount = igAccountId
		? igAccounts.find((a) => a.id === igAccountId) || igAccounts[0]
		: igAccounts[0];

	const accessToken = decrypt(igAccount!.instagram_access_token_encrypted ?? "");

	try {
		const response = await fetch(
			`https://graph.instagram.com/v25.0/${mediaId}?fields=media_url,thumbnail_url,media_type`,
			{
				headers: { Authorization: `Bearer ${accessToken}` },
				signal: AbortSignal.timeout(10000),
			},
		);

		if (!response.ok) {
			const errorBody = await response.text();
			logger.error("IG API error for media proxy", {
				mediaId,
				status: response.status,
				body: errorBody,
			});
			return apiError(
				res,
				response.status,
				`Instagram API returned ${response.status}`,
			);
		}

		const data = await response.json();

		// Set cache headers — fresh for 1 hour
		res.setHeader("Cache-Control", "public, max-age=3600, s-maxage=3600");

		return apiSuccess(res, {
			mediaUrl: data.media_url || null,
			mediaType: data.media_type || null,
			thumbnailUrl: data.thumbnail_url || null,
		});
	} catch (error: unknown) {
		logger.error("IG media proxy error", { error: String(error) });
		return apiError(res, 500, "Failed to fetch media");
	}
});
