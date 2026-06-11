/**
 * Handler: POST /api/competitors?action=search
 *
 * Search for a Threads profile using the profile_lookup endpoint.
 */

import { apiError, apiSuccess } from "../../../apiResponse.js";
import { logger } from "../../../logger.js";
import { checkRateLimit } from "../../../rateLimiter.js";
import { withRetry } from "../../../retryUtils.js";
import { CompetitorSearchSchema } from "../../../validation.js";
import { withAuthAndBody } from "../../helpers/withAuthAndBody.js";
import { getAllAccessTokens, tryWithFallbackTokens } from "../shared.js";

export const handleSearch = withAuthAndBody(
	CompetitorSearchSchema,
	async (user, parsed, _req, res) => {
		const { query } = parsed;
		const rl = await checkRateLimit({
			key: `competitor-search:${user.id}`,
			limit: 120,
			windowSeconds: 60 * 60,
			failMode: "closed",
		});
		if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

		const tokens = await getAllAccessTokens(user.id);
		if (!tokens.length) return apiError(res, 400, "No connected account");

		const cleanQuery = query.replace(/^@/, "").trim();
		logger.info("Searching for user", {
			username: cleanQuery,
			tokensAvailable: tokens.length,
		});

		// Try each token until one works
		const result = await tryWithFallbackTokens(tokens, async (accessToken) => {
			const profileLookupUrl = `https://graph.threads.net/v1.0/profile_lookup?username=${encodeURIComponent(cleanQuery)}`;
			logger.info("Trying profile_lookup", { username: cleanQuery });

			const profileResponse = await withRetry(
				() =>
					fetch(profileLookupUrl, {
						headers: { Authorization: `Bearer ${accessToken}` },
						signal: AbortSignal.timeout(10000),
					}),
				{ label: `competitorSearchProfile:${cleanQuery}` },
			);
			const profileData = await profileResponse.json();

			logger.info("Profile lookup response", {
				status: profileResponse.status,
				data: profileData,
			});

			if (profileData.error) {
				logger.info("Token failed", {
					code: profileData.error.code,
					type: profileData.error.type,
					message: profileData.error.message,
				});
				return { data: null, error: profileData.error.message };
			}

			return { data: profileData };
		});

		if (!result.data) {
			logger.error("All tokens failed for search", { username: cleanQuery });
			return apiError(
				res,
				404,
				result.error || `User @${cleanQuery} not found`,
			);
		}

		const profileData = result.data;
		logger.info("Search succeeded", {
			attemptNumber: result.tokenIndex + 1,
		});

		return apiSuccess(res, {
			profile: {
				id: profileData.id || cleanQuery,
				username: profileData.username,
				displayName: profileData.name || profileData.username,
				avatarUrl: profileData.profile_picture_url || "",
				bio: profileData.biography || "",
				isVerified: profileData.is_verified || false,
				followerCount: profileData.follower_count || 0,
			},
		});
	},
);
