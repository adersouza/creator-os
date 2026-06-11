/**
 * Trends API Route
 * POST /api/trends?action=search
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "./_lib/apiResponse.js";
import { trackUsage } from "./_lib/auditLog.js";
import { decrypt } from "./_lib/encryption.js";
import { logger } from "./_lib/logger.js";
import { withAuth } from "./_lib/middleware.js";
import {
	getPrivilegedSupabase,
	PRIVILEGED_DB_REASONS,
} from "./_lib/privilegedDb.js";
import { withRetry } from "./_lib/retryUtils.js";
import { z, zEnum } from "./_lib/zodCompat.js";

interface ThreadsAccountRow {
	id: string;
	threads_access_token_encrypted: string | null;
	username: string | null;
}

interface IgAccountRow {
	id: string;
	instagram_user_id: string | null;
	instagram_access_token_encrypted: string | null;
	username: string | null;
	login_type: string | null;
}

interface TrendsPost {
	id: string;
	platform: string;
	content: string;
	mediaUrl?: string | undefined;
	mediaType?: string | undefined;
	permalink?: string | undefined;
	timestamp: string;
	username: string;
	likeCount: number;
	replyCount: number;
	repostCount: number;
	viewCount: number;
}

const SearchSchema = z.object({
	query: z.string().min(1, "query is required"),
	searchType: zEnum(["RECENT", "TOP"]).optional().default("RECENT"),
	searchMode: zEnum(["KEYWORD", "HASHTAG"]).optional().default("KEYWORD"),
	mediaType: z.string().optional(),
	limit: z.number().int().min(1).max(100).optional().default(25),
	platform: zEnum(["threads", "instagram", "all"])
		.optional()
		.default("threads"),
});

// Create Supabase client lazily to avoid crashes at module load time

async function handleSearch(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = SearchSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}

	const { query, searchType, searchMode, mediaType, limit, platform } =
		parsed.data;
	const authorUsername = req.body?.authorUsername as string | undefined;

	const allPosts: TrendsPost[] = [];
	const seenPostIds = new Set<string>();
	const db = getPrivilegedSupabase(
		PRIVILEGED_DB_REASONS.trendSearchTokenLookup,
	);

	// ---- Threads search ----
	if (platform === "threads" || platform === "all") {
		const { data: accounts } = await db
			.from("accounts")
			.select("id, threads_access_token_encrypted, username")
			.eq("user_id", userId);

		for (const account of (accounts || []) as ThreadsAccountRow[]) {
			try {
				if (!account.threads_access_token_encrypted) continue;
				const accessToken = decrypt(account.threads_access_token_encrypted);

				// NOTE: like_count, reply_count, repost_count, views are undocumented on media objects
				// but returned by the API in practice. If they stop working, engagement will default to 0.
				const searchParams = new URLSearchParams({
					q: query,
					search_type: searchType,
					search_mode: searchMode,
					limit: String(limit),
					fields:
						"id,text,media_url,media_type,permalink,timestamp,username,like_count,reply_count,repost_count,views",
				});

				if (mediaType && mediaType !== "all") {
					searchParams.set("media_type", mediaType.toUpperCase());
				}

				if (authorUsername) {
					searchParams.set("author_username", authorUsername);
				}

				searchParams.set("access_token", accessToken);
				const response = await withRetry(
					() =>
						fetch(
							`https://graph.threads.net/v1.0/keyword_search?${searchParams}`,
							{ signal: AbortSignal.timeout(10000) },
						),
					{ label: "trends:threads-keyword-search" },
				);

				if (response.ok) {
					const data = await response.json();
					const posts = data.data || [];

					for (const post of posts) {
						if (!seenPostIds.has(post.id)) {
							seenPostIds.add(post.id);
							allPosts.push({
								id: post.id,
								platform: "threads",
								content: post.text || "",
								mediaUrl: post.media_url,
								mediaType: post.media_type,
								permalink: post.permalink,
								timestamp: post.timestamp,
								username: post.username,
								likeCount: post.like_count || 0,
								replyCount: post.reply_count || 0,
								repostCount: post.repost_count || 0,
								viewCount: post.views || 0,
							});
						}
					}
				}
			} catch (e) {
				logger.warn("Search failed for account", {
					accountId: account.id,
					error: String(e),
				});
			}
		}
	}

	// ---- Instagram hashtag search ----
	if (platform === "instagram" || platform === "all") {
		const { data: igAccounts } = await db
			.from("instagram_accounts")
			.select(
				"id, instagram_user_id, instagram_access_token_encrypted, username, login_type",
			)
			.eq("user_id", userId)
			.eq("is_active", true)
			.not("instagram_access_token_encrypted", "is", null);

		// IG hashtag search requires Facebook Login (graph.facebook.com)
		const fbAccount = ((igAccounts || []) as IgAccountRow[]).find(
			(a: IgAccountRow) => a.login_type === "facebook",
		);
		if (fbAccount) {
			try {
				const accessToken = decrypt(
					fbAccount.instagram_access_token_encrypted ?? "",
				);
				const igUserId = fbAccount.instagram_user_id;

				// Step 1: Search for hashtag ID
				const hashtagSearchUrl = `https://graph.facebook.com/v25.0/ig_hashtag_search?q=${encodeURIComponent(query)}&user_id=${igUserId}`;
				const hashtagRes = await withRetry(
					() =>
						fetch(hashtagSearchUrl, {
							headers: { Authorization: `Bearer ${accessToken}` },
							signal: AbortSignal.timeout(10000),
						}),
					{ label: "trends:instagram-hashtag-search" },
				);

				if (hashtagRes.ok) {
					const hashtagData = await hashtagRes.json();
					const hashtagId = hashtagData.data?.[0]?.id;

					if (hashtagId) {
						// Step 2: Get top or recent media for the hashtag
						const edge = searchType === "TOP" ? "top_media" : "recent_media";
						const mediaUrl = `https://graph.facebook.com/v25.0/${hashtagId}/${edge}?user_id=${igUserId}&fields=id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count`;
						const mediaRes = await withRetry(
							() =>
								fetch(mediaUrl, {
									headers: { Authorization: `Bearer ${accessToken}` },
									signal: AbortSignal.timeout(10000),
								}),
							{ label: "trends:instagram-hashtag-media" },
						);

						if (mediaRes.ok) {
							const mediaData = await mediaRes.json();
							for (const post of mediaData.data || []) {
								if (!seenPostIds.has(post.id)) {
									seenPostIds.add(post.id);
									allPosts.push({
										id: post.id,
										platform: "instagram",
										content: post.caption || "",
										mediaUrl: post.media_url,
										mediaType: post.media_type,
										permalink: post.permalink,
										timestamp: post.timestamp,
										username: "", // IG hashtag search doesn't return username
										likeCount: post.like_count || 0,
										replyCount: post.comments_count || 0,
										repostCount: 0,
										viewCount: 0,
									});
								}
							}
						}
					}
				}
			} catch (e) {
				logger.warn("[trends:ig] IG hashtag search failed", {
					error: String(e),
				});
			}
		}
	}

	if (!allPosts.length && platform !== "all") {
		// Only error if zero results AND we had no accounts
		// (empty results with valid accounts is fine)
	}

	allPosts.sort(
		(a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
	);

	return apiSuccess(res, {
		posts: allPosts.slice(0, limit),
		totalFound: allPosts.length,
	});
}

export default withAuth(async (req, res, user) => {
	const action = req.query.action as string;

	// "config" action accepts GET + POST; all others are POST-only
	if (req.method !== "POST" && action !== "config") {
		return apiError(res, 405, "Method not allowed");
	}

	try {
		switch (action) {
			case "search":
				trackUsage(user.id, "trends.search");
				return handleSearch(req, res, user.id);
			case "config":
				return (
					await import("./_lib/handlers/misc/trending-config.js")
				).default(req, res);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Trends API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
