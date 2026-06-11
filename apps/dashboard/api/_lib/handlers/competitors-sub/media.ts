// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Competitor Media API Route
 *
 * GET /api/competitor-media?threadsPostId=<id>
 *
 * Fetches a fresh media URL from the Threads API for a given post.
 * This avoids storing CDN URLs that expire quickly (403 errors).
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { parseQueryOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";

const CompetitorMediaQuerySchema = z.object({
	threadsPostId: z.string().min(1, "threadsPostId is required"),
	accountId: z.string().optional(),
});

const db = () => getSupabase();

// ============================================================================
// Supabase Client
// ============================================================================

// ============================================================================
// Handler
// ============================================================================

export default withAuth(async (req, res, user) => {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	const parsed = parseQueryOrError(res, CompetitorMediaQuerySchema, req.query);
	if (!parsed) return;
	const { threadsPostId, accountId } = parsed;

	// Get user's accounts with valid tokens
	const { data: accounts } = await db()
		.from("accounts")
		.select("id, threads_access_token_encrypted")
		.eq("user_id", user.id)
		.not("threads_access_token_encrypted", "is", null)
		.order("created_at", { ascending: false });

	if (!accounts?.length) {
		return apiError(res, 400, "No connected account");
	}

	// Use the specified account if provided, otherwise fall back to most recent
	const account = accountId
		? accounts.find((a) => a.id === accountId) || accounts[0]
		: accounts[0];

	const accessToken = decrypt(account!.threads_access_token_encrypted ?? "");

	try {
		const response = await fetch(
			`https://graph.threads.net/v1.0/${threadsPostId}?fields=id,media_url,media_type,thumbnail_url`,
			{
				headers: { Authorization: `Bearer ${accessToken}` },
				signal: AbortSignal.timeout(10000),
			},
		);

		if (!response.ok) {
			const errorBody = await response.text();
			logger.error("Threads API error for competitor media", {
				threadsPostId,
				status: response.status,
				body: errorBody,
			});
			return apiError(
				res,
				response.status,
				`Threads API returned ${response.status}`,
			);
		}

		const data = await response.json();

		return apiSuccess(res, {
			mediaUrl: data.media_url || null,
			mediaType: data.media_type || null,
			thumbnailUrl: data.thumbnail_url || null,
		});
	} catch (error: unknown) {
		logger.error("Competitor media error", { error: String(error) });
		return apiError(res, 500, "Failed to fetch media");
	}
});
