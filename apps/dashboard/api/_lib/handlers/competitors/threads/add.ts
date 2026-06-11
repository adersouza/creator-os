/**
 * Handler: POST /api/competitors?action=add
 *
 * Add a Threads competitor by looking up their profile.
 */

import { apiError, apiSuccess } from "../../../apiResponse.js";
import { logger } from "../../../logger.js";
import { checkRateLimit } from "../../../rateLimiter.js";
import { withRetry } from "../../../retryUtils.js";
import { CompetitorAddSchema } from "../../../validation.js";
import { withAuthAndBody } from "../../helpers/withAuthAndBody.js";
import {
	db,
	fetchAndStorePosts,
	getAllAccessTokens,
	tryWithFallbackTokens,
} from "../shared.js";

export const handleAdd = withAuthAndBody(
	CompetitorAddSchema,
	async (user, parsed, _req, res) => {
		const { username } = parsed;
		const rl = await checkRateLimit({
			key: `competitor-add:${user.id}`,
			limit: 60,
			windowSeconds: 60 * 60,
			failMode: "closed",
		});
		if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

		const tokens = await getAllAccessTokens(user.id);
		if (!tokens.length) return apiError(res, 400, "No connected account");

		const cleanUsername = username.replace(/^@/, "").trim();
		logger.info("Adding competitor", {
			username: cleanUsername,
			tokensAvailable: tokens.length,
		});

		// Try each token until one works
		let workingToken = "";
		const result = await tryWithFallbackTokens(tokens, async (accessToken) => {
			const profileLookupUrl = `https://graph.threads.net/v1.0/profile_lookup?username=${encodeURIComponent(cleanUsername)}&fields=username,name,profile_picture_url,biography,is_verified,follower_count`;
			const profileResponse = await withRetry(
				() =>
					fetch(profileLookupUrl, {
						headers: { Authorization: `Bearer ${accessToken}` },
						signal: AbortSignal.timeout(10000),
					}),
				{ label: `competitorAddProfile:${cleanUsername}` },
			);
			const profileData = await profileResponse.json();

			if (profileData.error) {
				logger.info("Add attempt failed", { error: profileData.error.message });
				return { data: null, error: profileData.error.message };
			}

			workingToken = accessToken; // Save the working token for later
			return { data: profileData };
		});

		if (!result.data) {
			logger.error("All tokens failed for add", { username: cleanUsername });
			return apiError(
				res,
				404,
				result.error || `User @${cleanUsername} not found`,
			);
		}

		const profileData = result.data;
		logger.info("Add succeeded", { attemptNumber: result.tokenIndex + 1 });

		const metrics = {
			followerCount: profileData.follower_count || 0,
			likesCount7d: profileData.likes_count || 0,
			quotesCount7d: profileData.quotes_count || 0,
			repliesCount7d: profileData.replies_count || 0,
			repostsCount7d: profileData.reposts_count || 0,
			viewsCount7d: profileData.views_count || 0,
		};

		// Insert directly and rely on UNIQUE constraint to prevent duplicates.
		let competitor: { id: string; [key: string]: unknown } | null = null;
		try {
			const { data: insertData, error: insertError } = await db()
				.from("competitors")
				.insert({
					user_id: user.id,
					threads_user_id: profileData.username,
					username: profileData.username,
					display_name: profileData.name || profileData.username,
					avatar_url: profileData.profile_picture_url || "",
					bio: profileData.biography || "",
					follower_count: metrics.followerCount,
					is_verified: profileData.is_verified || false,
					likes_count_7d: metrics.likesCount7d,
					quotes_count_7d: metrics.quotesCount7d,
					replies_count_7d: metrics.repliesCount7d,
					reposts_count_7d: metrics.repostsCount7d,
					views_count_7d: metrics.viewsCount7d,
					added_at: new Date().toISOString(),
					last_synced_at: new Date().toISOString(),
				})
				.select()
				.maybeSingle();

			if (insertError) {
				// PostgreSQL unique violation error code
				if (insertError.code === "23505") {
					return apiError(res, 400, "Competitor already tracked");
				}
				return apiError(res, 500, "Failed to add competitor");
			}

			competitor = insertData;
		} catch (_err: unknown) {
			return apiError(res, 500, "Failed to add competitor");
		}

		// Immediately fetch posts for the new competitor using the working token
		// This runs async but we don't wait for it to complete
		// eslint-disable-next-line @typescript-eslint/no-non-null-assertion
		fetchAndStorePosts(
			competitor?.id ?? "",
			profileData.username,
			workingToken,
		).catch((err) =>
			logger.error("Failed to fetch initial posts", { error: String(err) }),
		);

		return apiSuccess(res, { competitor });
	},
);
