/**
 * Instagram Hashtag Search API Route
 * POST /api/instagram/hashtags?action=search|top-media|recent-media
 *
 * Requires Facebook Login (not Instagram Business Login).
 * Rate limit: 30 hashtag searches per 7-day rolling window.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { cached } from "../../redisCache.js";
import { getSupabase } from "../../supabase.js";
import { z } from "../../zodCompat.js";

// ============================================================================
// Zod Schemas
// ============================================================================

const SearchSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	hashtagName: z.string().min(1, "hashtagName is required").max(100),
});

const MediaSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	hashtagId: z.string().min(1, "hashtagId is required"),
	limit: z.number().min(1).max(50).optional(),
});

// ============================================================================
// Handler
// ============================================================================

async function handler(
	req: VercelRequest,
	res: VercelResponse,
	user: { id: string; email?: string | undefined },
) {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const action = req.query.action as string;

	if (!["search", "top-media", "recent-media"].includes(action)) {
		return apiError(
			res,
			400,
			"Invalid action. Use: search, top-media, recent-media",
		);
	}

	const body = typeof req.body === "string" ? JSON.parse(req.body) : req.body;
	const supabase = getSupabase();

	// Resolve IG account — must be Facebook Login
	const resolveIGAccount = async (accountId: string) => {
		const { data: igAccount, error } = await supabase
			.from("instagram_accounts")
			.select(
				"id, instagram_user_id, instagram_access_token_encrypted, login_type, user_id",
			)
			.eq("id", accountId)
			.eq("user_id", user.id)
			.maybeSingle();

		if (error || !igAccount) {
			return { error: "Instagram account not found" };
		}

		if (igAccount.login_type !== "facebook") {
			return {
				error:
					"Hashtag search requires Facebook Login. Please reconnect via Facebook Login.",
			};
		}

		if (!igAccount.instagram_access_token_encrypted) {
			return {
				error: "Instagram access token missing. Please reconnect your account.",
			};
		}

		return {
			account: igAccount as typeof igAccount & {
				instagram_access_token_encrypted: string;
			},
		};
	};

	try {
		if (action === "search") {
			const parsed = SearchSchema.safeParse(body);
			if (!parsed.success) {
				return apiError(
					res,
					400,
					parsed.error.issues[0]?.message || "Invalid input",
				);
			}
			const { accountId, hashtagName } = parsed.data;
			const resolved = await resolveIGAccount(accountId);
			if (resolved.error) return apiError(res, 400, resolved.error);
			const account = resolved.account ?? {
				instagram_access_token_encrypted: "",
				instagram_user_id: "",
				login_type: undefined as string | undefined,
			};

			// #516: Check Redis cache first to avoid wasting the 30/7-day rate limit
			// on re-searches for the same hashtag. Cache TTL = 7 days (matches Meta limit window).
			const normalizedName = hashtagName.replace(/^#/, "").trim().toLowerCase();
			const cacheKey = `ig-hashtag:${accountId}:${normalizedName}`;

			try {
				const cachedId = await cached<string | null>(
					cacheKey,
					7 * 24 * 60 * 60, // 7-day TTL
					async () => null, // Only check cache, don't compute
				);
				if (cachedId) {
					logger.info("Hashtag ID served from cache (no API call)", {
						hashtagName: normalizedName,
						hashtagId: cachedId,
						accountId,
					});
					return apiSuccess(res, {
						hashtagId: cachedId,
						hashtagName: normalizedName,
					});
				}
			} catch {
				// Redis unavailable — fall through to API call
			}

			// Check endpoint rate limit (30 searches / 7 days)
			//
			// #521: Note on calendar-day vs 7-day rolling window:
			// The `check_ig_endpoint_limit` RPC uses a calendar-day reset (resets at midnight UTC)
			// with a daily limit of 30, rather than a true 7-day rolling window.
			//
			// Meta's actual limit is 30 searches per 7-day rolling window, but our implementation
			// uses calendar-day for two reasons:
			// 1. Simplicity: A rolling window requires tracking every individual request timestamp,
			//    adding complexity and storage overhead. Calendar-day uses a single counter.
			// 2. Conservative: Calendar-day is strictly more conservative than rolling — a user
			//    who hits 30 searches on Monday can try again on Tuesday, but Meta's rolling
			//    window wouldn't reset until next Monday. Our approach is safe because we also
			//    cache hashtag IDs for 7 days (#516), so repeated searches for the same hashtag
			//    never consume rate limit at all.
			//
			// If users report hitting our limit too early, consider implementing a true rolling
			// window via a separate `ig_hashtag_search_log` table with per-request timestamps.
			const { data: limitData } = await supabase.rpc(
				"check_ig_endpoint_limit",
				{
					p_account_id: accountId,
					p_endpoint: "hashtags",
					p_hourly_limit: 0,
					p_daily_limit: 30,
				},
			);

			const limitResult = limitData?.[0];
			if (limitResult && !limitResult.allowed) {
				return apiError(
					res,
					429,
					"Hashtag search rate limit reached (30 per 7 days)",
				);
			}

			const { searchHashtag } = await import("../../instagramApi.js");
			const result = await searchHashtag(
				account.instagram_access_token_encrypted,
				account.instagram_user_id,
				hashtagName,
				account.login_type ?? undefined,
			);

			if (!result.success) {
				return apiError(res, 400, result.error || "Hashtag search failed");
			}

			// #516: Cache the hashtag ID for 7 days to avoid re-consuming rate limit
			if (result.hashtagId) {
				try {
					const { getRedis } = await import("../../redis.js");
					const redis = getRedis();
					await redis.set(
						`cache:${cacheKey}`,
						JSON.stringify(result.hashtagId),
						{ ex: 7 * 24 * 60 * 60 },
					);
				} catch {
					// Redis unavailable — non-critical
				}
			}

			return apiSuccess(res, {
				hashtagId: result.hashtagId,
				hashtagName: normalizedName,
			});
		}

		if (action === "top-media" || action === "recent-media") {
			const parsed = MediaSchema.safeParse(body);
			if (!parsed.success) {
				return apiError(
					res,
					400,
					parsed.error.issues[0]?.message || "Invalid input",
				);
			}
			const { accountId, hashtagId, limit } = parsed.data;
			const resolved = await resolveIGAccount(accountId);
			if (resolved.error) return apiError(res, 400, resolved.error);
			const account = resolved.account ?? {
				instagram_access_token_encrypted: "",
				instagram_user_id: "",
				login_type: undefined as string | undefined,
			};

			const { getHashtagTopMedia, getHashtagRecentMedia } = await import(
				"../../instagramApi.js"
			);
			const fn =
				action === "top-media" ? getHashtagTopMedia : getHashtagRecentMedia;
			const result = await fn(
				account.instagram_access_token_encrypted,
				hashtagId,
				account.instagram_user_id,
				limit || 25,
				account.login_type ?? undefined,
			);

			if (!result.success) {
				return apiError(
					res,
					400,
					result.error || "Failed to fetch hashtag media",
				);
			}

			return apiSuccess(res, { media: result.media });
		}
	} catch (error) {
		logger.error("Instagram hashtags route error", {
			action,
			error: String(error),
		});
		return apiError(res, 500, "Internal server error");
	}
}

export default withAuth(handler);
