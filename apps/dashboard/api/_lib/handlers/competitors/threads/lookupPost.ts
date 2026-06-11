// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Handler: POST /api/competitors?action=lookup-post
 *
 * Lookup a Threads post by URL to get its numeric ID for quoting.
 */

import { apiError, apiSuccess } from "../../../apiResponse.js";
import { logger } from "../../../logger.js";
import { withRetry } from "../../../retryUtils.js";
import { CompetitorLookupPostSchema } from "../../../validation.js";
import { withAuthAndBody } from "../../helpers/withAuthAndBody.js";
import { getAccessToken } from "../shared.js";

export const handleLookupPost = withAuthAndBody(
	CompetitorLookupPostSchema,
	async (user, parsed, _req, res) => {
		const { postUrl } = parsed;

		// Validate it's a Threads URL
		if (!postUrl.includes("threads.net") && !postUrl.includes("threads.com")) {
			return apiError(res, 400, "Must be a Threads URL");
		}

		const accessToken = await getAccessToken(user.id);
		if (!accessToken) return apiError(res, 400, "No connected account");

		try {
			// Parse URL to extract username and shortcode
			// Format: https://www.threads.net/@username/post/shortcode
			const urlMatch = postUrl.match(
				/threads\.(net|com)\/@([^/]+)\/post\/([^/?#]+)/i,
			);

			if (!urlMatch) {
				return apiError(
					res,
					400,
					"Invalid Threads post URL. Expected format: https://www.threads.net/@username/post/...",
				);
			}

			const username = urlMatch[2];
			const shortcode = urlMatch[3];

			logger.info("Looking up post", { username, shortcode });

			// Use profile_posts to get the user's posts
			const profilePostsUrl = `https://graph.threads.net/v1.0/profile_posts?username=${encodeURIComponent(username!)}&fields=id,text,timestamp,media_url,media_type,permalink,username&limit=50`;

			const response = await withRetry(
				() =>
					fetch(profilePostsUrl, {
						headers: { Authorization: `Bearer ${accessToken}` },
						signal: AbortSignal.timeout(10000),
					}),
				{ label: `competitorLookupPost:${username}` },
			);
			const responseData = await response.json();

			if (responseData.error) {
				logger.error("Profile posts error", {
					error: String(responseData.error),
				});

				if (
					responseData.error.code === 10 ||
					responseData.error.message?.includes("permission")
				) {
					return apiError(
						res,
						403,
						"Profile discovery permission required. This feature needs Meta app review approval.",
					);
				}

				return apiError(
					res,
					500,
					responseData.error.message || "Failed to look up post",
				);
			}

			const posts = responseData.data || [];

			// Find the post with matching permalink/shortcode
			const matchingPost = posts.find(
				(post: {
					id: string;
					text?: string | undefined;
					username?: string | undefined;
					media_url?: string | null | undefined;
					media_type?: string | null | undefined;
					timestamp?: string | null | undefined;
					permalink?: string | undefined;
				}) => {
					if (post.permalink) {
						return post.permalink.includes(shortcode!);
					}
					return false;
				},
			);

			if (!matchingPost) {
				return apiError(
					res,
					404,
					"Post not found. It may be private, deleted, or the profile has limited discoverability.",
				);
			}

			return apiSuccess(res, {
				post: {
					id: matchingPost.id,
					text: matchingPost.text || "",
					username: matchingPost.username || username,
					mediaUrl: matchingPost.media_url || null,
					mediaType: matchingPost.media_type || null,
					timestamp: matchingPost.timestamp || null,
					permalink: matchingPost.permalink || postUrl,
				},
			});
		} catch (error: unknown) {
			logger.error("Error looking up post", { error: String(error) });
			return apiError(res, 500, "Failed to look up post");
		}
	},
);
