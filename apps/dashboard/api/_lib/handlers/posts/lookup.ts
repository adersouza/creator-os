// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Lookup handlers — post lookup by URL and location search.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { withRetry } from "../../retryUtils.js";
import {
	db,
	type IgAccountTokenRow,
	type LocationItem,
	type ThreadsAccountTokenRow,
	type ThreadsApiPostItem,
} from "./shared.js";

/**
 * Look up a Threads post by URL to get its numeric ID for quoting
 * Uses the profile_posts API to find the matching post
 */
export async function handleLookupPost(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { postUrl } = req.body;

	if (!postUrl || typeof postUrl !== "string") {
		return apiError(res, 400, "Post URL is required");
	}

	// Validate it's a Threads URL
	if (!postUrl.includes("threads.net") && !postUrl.includes("threads.com")) {
		return apiError(res, 400, "Must be a Threads URL");
	}

	// Get user's access token
	const { data: accounts } = (await db()
		.from("accounts")
		.select("threads_access_token_encrypted")
		.eq("user_id", userId)
		.limit(1)) as { data: ThreadsAccountTokenRow[] | null; error: unknown };

	if (!accounts?.length || !accounts[0]!.threads_access_token_encrypted) {
		return apiError(
			res,
			400,
			"No connected Threads account. Please connect an account first.",
		);
	}

	const accessToken = decrypt(accounts[0]!.threads_access_token_encrypted);

	try {
		// Parse URL to extract username
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
			{ label: `postLookup:${username}` },
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
		const matchingPost = posts.find((post: ThreadsApiPostItem) => {
			if (post.permalink) {
				return post.permalink.includes(shortcode!);
			}
			return false;
		});

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
}

/**
 * Search for locations by query string
 * Uses Threads API search_location endpoint
 */
export async function handleSearchLocations(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { query, accountId, platform } = req.body;

	if (!query || typeof query !== "string" || !query.trim()) {
		return apiError(res, 400, "Search query is required");
	}

	if (query.trim().length > 256) {
		return apiError(res, 400, "Search query must be 256 characters or fewer");
	}

	if (!accountId) {
		return apiError(res, 400, "Account ID is required");
	}

	if (platform && !["instagram", "threads"].includes(platform)) {
		return apiError(
			res,
			400,
			"Invalid platform. Must be 'instagram' or 'threads'",
		);
	}

	try {
		let searchUrl: string;
		let accessToken: string;

		if (platform === "instagram") {
			// Instagram: use Facebook Places API via instagram_accounts token
			const { data: igAccount, error: igError } = (await db()
				.from("instagram_accounts")
				.select("instagram_access_token_encrypted")
				.eq("id", accountId)
				.eq("user_id", userId)
				.maybeSingle()) as { data: IgAccountTokenRow | null; error: unknown };

			if (igError || !igAccount?.instagram_access_token_encrypted) {
				return apiError(
					res,
					404,
					"Instagram account not found or not connected",
				);
			}

			accessToken = decrypt(igAccount.instagram_access_token_encrypted);
			searchUrl = `https://graph.facebook.com/v25.0/search?type=place&q=${encodeURIComponent(query.trim())}`;
		} else {
			// Threads: use Threads API location_search
			const { data: account, error: accountError } = (await db()
				.from("accounts")
				.select("threads_access_token_encrypted")
				.eq("id", accountId)
				.eq("user_id", userId)
				.maybeSingle()) as {
				data: ThreadsAccountTokenRow | null;
				error: unknown;
			};

			if (accountError || !account?.threads_access_token_encrypted) {
				return apiError(res, 404, "Account not found or not connected");
			}

			accessToken = decrypt(account.threads_access_token_encrypted);
			searchUrl = `https://graph.threads.net/v1.0/location_search?q=${encodeURIComponent(query.trim())}&fields=id,address,city,country,name,latitude,longitude,postal_code`;
		}

		logger.info("Location search", {
			query: query.trim(),
			platform: platform || "threads",
		});

		const response = await withRetry(
			() =>
				fetch(searchUrl, {
					headers: { Authorization: `Bearer ${accessToken}` },
					signal: AbortSignal.timeout(10000),
				}),
			{ label: `locationSearch:${platform || "threads"}` },
		);
		const data = await response.json();

		if (data.error) {
			logger.error("Location search API error", { error: String(data.error) });
			const errorMessage = data.error.message || "Failed to search locations";
			const errorCode = data.error.code;

			return apiSuccess(res, {
				locations: [],
				error: `API Error (${errorCode}): ${errorMessage}`,
			});
		}

		// Transform response to Location format
		const locations = (data.data || []).map((loc: LocationItem) => ({
			id: loc.id,
			name: loc.name,
		}));

		return apiSuccess(res, {
			locations,
		});
	} catch (error: unknown) {
		logger.error("Location search error", { error: String(error) });
		return apiError(res, 500, "Failed to search locations");
	}
}
