/**
 * Discover API Route
 * Unified endpoint for keyword search and saved searches management
 *
 * POST /api/discover?action=search - Execute keyword search
 * POST /api/discover?action=save-search - Save a search query
 * GET  /api/discover?action=get-searches - Get user's saved searches
 * DELETE /api/discover?action=delete-search - Delete a saved search
 * POST /api/discover?action=refresh-search - Manually refresh a search's metrics
 * GET  /api/discover?action=get-snapshots - Get snapshot history for a search
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

interface IGAccount {
	id: string;
	instagram_user_id: string;
	instagram_access_token_encrypted: string;
	login_type: string;
}

interface DiscoverPost {
	id: string;
	platform: string;
	content: string;
	mediaUrl: string | undefined;
	mediaType: string | undefined;
	permalink: string | undefined;
	timestamp: string;
	username: string;
	likeCount: number;
	replyCount: number;
	repostCount: number;
	viewCount: number;
	engagementScore: number;
	trendScore?: number | undefined;
}

import {
	apiError,
	apiSuccess,
	badRequest,
	methodNotAllowed,
	notFound,
	serverError,
} from "../../apiResponse.js";
import { logAudit, trackUsage } from "../../auditLog.js";
import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { getRedis } from "../../redis.js";
import { withRetry } from "../../retryUtils.js";
import { getSupabase } from "../../supabase.js";
import { z, zEnum } from "../../zodCompat.js";
import { getDecryptedThreadsTokenByUser } from "../../tokenAccess.js";

// ============================================================================
// Zod Schemas
// ============================================================================

const SearchSchema = z.object({
	query: z.string().min(1, "Query is required"),
	searchType: z.string().optional().default("RECENT"),
	searchMode: z.string().optional().default("KEYWORD"),
	mediaType: z.string().optional(),
	limit: z.number().int().min(1).max(100).optional().default(25),
	// Validated to only allow known platform values — prevents silently searching the wrong platform
	platform: zEnum(["threads", "instagram", "all"]).optional().default("threads"),
});

// SaveSearchSchema and SearchIdSchema removed — saved_searches tables dropped

// ============================================================================
// Supabase Client
// ============================================================================

// ============================================================================
// Tier Limits
// ============================================================================

// TIER_LIMITS removed — saved_searches tables dropped

// ============================================================================
// Action Handlers
// ============================================================================

async function handleSearch(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = SearchSchema.safeParse(req.body);
	if (!parsed.success) {
		return badRequest(res, `Invalid input: ${parsed.error.issues[0]?.message}`);
	}
	const { query, searchType, searchMode, mediaType, limit, platform } =
		parsed.data;
	const authorUsername = req.body?.authorUsername as string | undefined;

	// #543: Cache search results for 15 minutes to reduce Meta API calls
	const discoverCacheKey = `cache:discover:${userId}:${platform}:${searchType}:${searchMode}:${mediaType || "ALL"}:${authorUsername || "ALL"}:${query}`;
	try {
		const cachedResult = await getRedis().get(discoverCacheKey);
		if (cachedResult) {
			return apiSuccess(res, cachedResult as Record<string, unknown>);
		}
	} catch {
		// Redis down — proceed without cache
	}

	const allPosts: DiscoverPost[] = [];
	const seenPostIds = new Set<string>();
	let totalEngagement = 0;

	// #544: Category/niche filtering is not supported by the Meta API.
	// The Threads keyword_search endpoint (graph.threads.net/v1.0/keyword_search)
	// only supports: q, search_type, search_mode, media_type, author_username, limit.
	// The Instagram ig_hashtag_search endpoint similarly has no category parameter.
	// To add niche filtering, we would need to:
	// 1. Fetch results from Meta API as-is
	// 2. Cross-reference usernames with a local niche/category mapping table
	// 3. Filter client-side based on that mapping
	// This is a Meta API limitation — not something we can work around server-side.

	// ---- Threads search ----
	if (platform === "threads" || platform === "all") {
		const threadsTokenData = await getDecryptedThreadsTokenByUser(userId);

		if (threadsTokenData) {
			try {
				const accessToken = threadsTokenData.token;

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

				if (mediaType && mediaType !== "ALL") {
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
							{ signal: AbortSignal.timeout(6000) },
						),
					{ label: "discover:threads-keyword-search" },
				);

				if (response.ok) {
					const data = await response.json();
					for (const post of data.data || []) {
						if (!seenPostIds.has(post.id)) {
							seenPostIds.add(post.id);
							const engagement =
								(post.like_count || 0) +
								(post.reply_count || 0) * 2 +
								(post.repost_count || 0) * 3;
							totalEngagement += engagement;

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
								engagementScore: engagement,
							});
						}
					}
				}
			} catch (e) {
				logger.warn("Search failed for account", {
					accountId: threadsTokenData.accountId,
					error: String(e),
				});
			}
		}
	}

	// ---- Instagram hashtag search ----
	if (platform === "instagram" || platform === "all") {
		const { data: igAccounts } = (await getSupabase()
			.from("instagram_accounts")
			.select(
				"id, instagram_user_id, instagram_access_token_encrypted, login_type",
			)
			.eq("user_id", userId)
			.eq("is_active", true)
			.not("instagram_access_token_encrypted", "is", null)) as {
			data: IGAccount[] | null;
			error: unknown;
		};

		const fbAccount = (igAccounts || []).find(
			(a: IGAccount) => a.login_type === "facebook",
		);
		if (fbAccount) {
			try {
				const accessToken = decrypt(fbAccount.instagram_access_token_encrypted);
				const igUserId = fbAccount.instagram_user_id;

				let hashtagRes: Response;
				hashtagRes = await withRetry(
					() =>
						fetch(
							`https://graph.facebook.com/v25.0/ig_hashtag_search?q=${encodeURIComponent(query)}&user_id=${igUserId}`,
							{
								headers: { Authorization: `Bearer ${accessToken}` },
								signal: AbortSignal.timeout(10000),
							},
						),
					{ label: "discover:instagram-hashtag-search" },
				);

				if (hashtagRes.ok) {
					const hashtagData = await hashtagRes.json();
					const hashtagId = hashtagData.data?.[0]?.id;

					if (hashtagId) {
						const edge = searchType === "TOP" ? "top_media" : "recent_media";
						let mediaRes: Response;
						mediaRes = await withRetry(
							() =>
								fetch(
									`https://graph.facebook.com/v25.0/${hashtagId}/${edge}?user_id=${igUserId}&fields=id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count`,
									{
										headers: { Authorization: `Bearer ${accessToken}` },
										signal: AbortSignal.timeout(6000),
									},
								),
							{ label: "discover:instagram-hashtag-media" },
						);

						if (mediaRes.ok) {
							const mediaData = await mediaRes.json();
							for (const post of mediaData.data || []) {
								if (!seenPostIds.has(post.id)) {
									seenPostIds.add(post.id);
									const engagement =
										(post.like_count || 0) + (post.comments_count || 0) * 2;
									totalEngagement += engagement;

									allPosts.push({
										id: post.id,
										platform: "instagram",
										content: post.caption || "",
										mediaUrl: post.media_url,
										mediaType: post.media_type,
										permalink: post.permalink,
										timestamp: post.timestamp,
										username: "",
										likeCount: post.like_count || 0,
										replyCount: post.comments_count || 0,
										repostCount: 0,
										viewCount: 0,
										engagementScore: engagement,
									});
								}
							}
						}
					}
				}
			} catch (e) {
				logger.warn("[discover:ig] IG hashtag search failed", {
					error: String(e),
				});
			}
		}
	}

	// #548: Composite scoring and ranking for discover results.
	// Instead of just sorting by timestamp, rank by a composite score that
	// weighs engagement, view count, and recency. This ensures trending/viral
	// content surfaces above low-engagement recent posts.
	const now = Date.now();
	for (const post of allPosts) {
		const ageHours = Math.max(
			1,
			(now - new Date(post.timestamp).getTime()) / (1000 * 60 * 60),
		);
		// Engagement score already computed above (likes + replies*2 + reposts*3)
		const engagementWeight = post.engagementScore || 0;
		// Views add a secondary signal (lower weight to avoid inflating low-engagement viral content)
		const viewWeight = Math.log10(Math.max(1, post.viewCount || 0));
		// Recency decay: content older than 24h gets progressively penalized
		const recencyMultiplier = Math.max(0.1, 1 / Math.log2(ageHours + 1));
		// Composite score: engagement is primary, views secondary, recency as multiplier
		post.trendScore =
			Math.round(
				(engagementWeight + viewWeight * 5) * recencyMultiplier * 100,
			) / 100;
	}

	// Sort by composite trend score (descending), with timestamp as tiebreaker
	allPosts.sort((a, b) => {
		const scoreDiff = (b.trendScore || 0) - (a.trendScore || 0);
		if (scoreDiff !== 0) return scoreDiff;
		return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
	});

	const searchResult = {
		posts: allPosts.slice(0, limit),
		totalFound: allPosts.length,
		totalEngagement,
		avgEngagement:
			allPosts.length > 0 ? Math.round(totalEngagement / allPosts.length) : 0,
	};

	// #543: Cache results for 15 minutes
	if (allPosts.length > 0) {
		getRedis()
			.set(discoverCacheKey, JSON.stringify(searchResult), { ex: 900 })
			.catch(() => {});
	}

	// #553: Track search history in feature_usage for analytics on what users search for.
	// Stored as feature_name with query encoded (truncated to 100 chars for DB constraint).
	// Fire-and-forget — never blocks the search response.
	const truncatedQuery = query.slice(0, 80);
	void getSupabase()
		.from("feature_usage")
		.insert({
			user_id: userId,
			feature_name: `discover_search:${platform}:${truncatedQuery}`,
		})
		.then(() => {});

	return apiSuccess(res, searchResult);
}

// saved_searches tables dropped — stubs return empty/gone
async function handleSaveSearch(
	_req: VercelRequest,
	res: VercelResponse,
	_userId: string,
) {
	return apiError(res, 410, "Saved searches feature has been removed");
}

async function handleGetSearches(
	_req: VercelRequest,
	res: VercelResponse,
	_userId: string,
) {
	return apiError(res, 410, "Saved searches feature has been removed");
}

async function handleDeleteSearch(
	_req: VercelRequest,
	res: VercelResponse,
	_userId: string,
) {
	return apiError(res, 410, "Saved searches feature has been removed");
}

async function handleRefreshSearch(
	_req: VercelRequest,
	res: VercelResponse,
	_userId: string,
) {
	return notFound(res, "Saved searches feature has been removed");
}

async function handleGetSnapshots(
	_req: VercelRequest,
	res: VercelResponse,
	_userId: string,
) {
	return apiError(res, 410, "Saved searches feature has been removed");
}

async function handleCheckLimits(
	_req: VercelRequest,
	res: VercelResponse,
	_userId: string,
) {
	return apiError(res, 410, "Saved searches feature has been removed");
}

// ============================================================================
// Main Handler
// ============================================================================

export default withAuth(async (req, res, user) => {
	const action = req.query.action as string;
	const userId = user.id;

	// #541: Rate limit Discover API — prevents exhausting Meta API quotas
	const rl = await checkRateLimit({
		key: `discover:${userId}`,
		limit: 30,
		windowSeconds: 60,
		failMode: "closed",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "Rate limit exceeded. Try again shortly.");
	}

	try {
		// GET actions
		if (req.method === "GET") {
			switch (action) {
				case "get-searches":
					return handleGetSearches(req, res, userId);
				case "get-snapshots":
					return handleGetSnapshots(req, res, userId);
				case "check-limits":
					return handleCheckLimits(req, res, userId);
				default:
					return badRequest(res, `Unknown GET action: ${action}`);
			}
		}

		// POST actions
		if (req.method === "POST") {
			switch (action) {
				case "search": {
					const searchPlatform = req.body?.platform || "threads";
					const searchSearchType = req.body?.searchType || "RECENT";
					trackUsage(
						userId,
						`discover.search.${searchPlatform}.${searchSearchType}`,
					);
					return handleSearch(req, res, userId);
				}
				case "save-search":
					return handleSaveSearch(req, res, userId);
				case "refresh-search":
					return handleRefreshSearch(req, res, userId);
				default:
					return badRequest(res, `Unknown POST action: ${action}`);
			}
		}

		// DELETE actions
		if (req.method === "DELETE") {
			switch (action) {
				case "delete-search":
					logAudit(userId, "discover.delete-search", { req });
					return handleDeleteSearch(req, res, userId);
				default:
					return badRequest(res, `Unknown DELETE action: ${action}`);
			}
		}

		return methodNotAllowed(res);
	} catch (error: unknown) {
		logger.error("Discover API error", { error: String(error) });
		return serverError(res, "Internal server error");
	}
});
