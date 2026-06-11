/**
 * Instagram Insights API Route
 * POST /api/instagram/insights?action=account-insights|post-insights|publishing-limit
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, handleIgAuthError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getRedis } from "../../redis.js";
import { getSupabase } from "../../supabase.js";
import { z, zEnum } from "../../zodCompat.js";

// ---------------------------------------------------------------------------
// Row / API Types
// ---------------------------------------------------------------------------

interface IgAccountRow {
	instagram_access_token_encrypted: string | null;
	instagram_user_id: string | null;
	login_type: string | null;
	needs_reauth: boolean | null;
}

interface PostCarouselRow {
	instagram_post_id: string | null;
	ig_media_type: string | null;
	content_surface?: string | null | undefined;
	media_type?: string | null | undefined;
	metadata?: Record<string, unknown> | null | undefined;
}

// ---------------------------------------------------------------------------
// Zod Schemas
// ---------------------------------------------------------------------------

const AccountInsightsSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	period: zEnum(["day", "week", "days_28"]).optional(),
});

const PostInsightsSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	mediaId: z.string().min(1, "mediaId is required"),
});

const PublishingLimitSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
});

async function handleAccountInsights(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = AccountInsightsSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, period } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select(
			"instagram_access_token_encrypted, instagram_user_id, login_type, needs_reauth",
		)
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as unknown as {
		data: IgAccountRow | null;
		error: Error | null;
	};

	if (accountError || !account) {
		logger.error("[IG Insights] Account lookup failed", {
			accountId,
			userId,
			error: accountError?.message,
		});
		return apiError(res, 404, "Instagram account not found");
	}

	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	// Early exit for accounts that need re-authentication — avoids hammering Meta API
	if (account.needs_reauth) {
		return apiError(
			res,
			401,
			"Account needs re-authentication. Please reconnect your Instagram account.",
		);
	}

	const loginType = account.login_type || "instagram";
	const resolvedPeriod = period || "day";

	// 5-minute cache to avoid hammering Meta API on every frontend poll
	const cacheKey = `ig-insights:${accountId}:${resolvedPeriod}`;
	try {
		const cached = await getRedis().get(cacheKey);
		if (cached) {
			return apiSuccess(res, {
				insights: cached as Record<string, unknown>,
				cached: true,
			});
		}
	} catch {
		// Redis down — proceed without cache
	}

	logger.info("[IG Insights] Fetching account insights", {
		accountId,
		loginType,
		period: resolvedPeriod,
	});

	// Lazy import to avoid module crashes
	const { getInstagramAccountInsights } = await import("../../instagramApi.js");

	const result = await getInstagramAccountInsights(
		account.instagram_access_token_encrypted as string,
		account.instagram_user_id as string,
		resolvedPeriod,
		loginType,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	// Cache successful result for 5 minutes
	if (result.insights) {
		getRedis()
			.set(cacheKey, JSON.stringify(result.insights), { ex: 300 })
			.catch(() => {});
	}

	return apiSuccess(res, { insights: result.insights });
}

async function handlePostInsights(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = PostInsightsSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { mediaId, accountId } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as unknown as {
		data: IgAccountRow | null;
		error: Error | null;
	};

	if (accountError || !account) {
		logger.error("[IG Insights] Post insights account lookup failed", {
			accountId,
			userId,
			error: accountError?.message,
		});
		return apiError(res, 404, "Instagram account not found");
	}

	const loginType = account.login_type || "instagram";
	const { data: post } = (await getSupabase()
		.from("posts")
		.select("instagram_post_id, ig_media_type, content_surface, media_type, metadata")
		.eq("instagram_post_id", mediaId)
		.eq("instagram_account_id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as unknown as {
		data: PostCarouselRow | null;
		error: Error | null;
	};
	const campaignMeta =
		post?.metadata &&
		typeof post.metadata === "object" &&
		"campaign_factory" in post.metadata &&
		typeof post.metadata.campaign_factory === "object"
			? (post.metadata.campaign_factory as Record<string, unknown>)
			: {};
	const contentSurface =
		post?.content_surface ||
		(campaignMeta.content_surface as string | undefined) ||
		(campaignMeta.contentSurface as string | undefined);
	const igMediaType =
		post?.ig_media_type ||
		(campaignMeta.ig_media_type as string | undefined) ||
		(campaignMeta.igMediaType as string | undefined) ||
		post?.media_type ||
		undefined;
	logger.info("[IG Insights] Fetching post insights", {
		mediaId,
		loginType,
		contentSurface,
		igMediaType,
	});

	const { getInstagramPostMetrics } = await import("../../instagramApi.js");

	const result = await getInstagramPostMetrics(
		account.instagram_access_token_encrypted as string,
		mediaId,
		loginType,
		igMediaType,
		contentSurface,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	return apiSuccess(res, { metrics: result.metrics });
}

const CarouselChildrenSchema = z.object({
	postId: z.string().min(1, "postId is required"),
	accountId: z.string().min(1, "accountId is required"),
});

async function handleCarouselChildren(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = CarouselChildrenSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { postId, accountId } = parsed.data;

	// Look up post to get instagram_post_id
	const { data: post } = (await getSupabase()
		.from("posts")
		.select("instagram_post_id, ig_media_type")
		.eq("id", postId)
		.eq("user_id", userId)
		.maybeSingle()) as unknown as {
		data: PostCarouselRow | null;
		error: Error | null;
	};

	if (!post?.instagram_post_id) {
		return apiError(res, 404, "Post not found or not an Instagram post");
	}

	if (post.ig_media_type !== "CAROUSEL_ALBUM") {
		return apiError(res, 400, "Post is not a carousel");
	}

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as unknown as {
		data: IgAccountRow | null;
		error: Error | null;
	};

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}

	const loginType = account.login_type || "instagram";
	logger.info("[IG Insights] Fetching carousel children", {
		postId,
		loginType,
	});

	const { getCarouselChildInsights } = await import("../../instagramApi.js");

	const result = await getCarouselChildInsights(
		account.instagram_access_token_encrypted as string,
		post.instagram_post_id as string,
		loginType,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	return apiSuccess(res, { children: result.children });
}

const TaggedPostsSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
});

async function handleTaggedPosts(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = TaggedPostsSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as unknown as {
		data: IgAccountRow | null;
		error: Error | null;
	};

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}
	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const loginType = account.login_type || "instagram";
	logger.info("[IG Insights] Fetching tagged posts", { accountId, loginType });

	const { getTaggedMedia } = await import("../../instagramApi.js");
	const result = await getTaggedMedia(
		account.instagram_access_token_encrypted as string,
		account.instagram_user_id as string,
		loginType,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	return apiSuccess(res, {
		media: result.media ?? [],
		count: (result.media ?? []).length,
	});
}

const MentionedMediaSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	mediaId: z.string().min(1, "mediaId is required"),
});

async function handleMentionedMedia(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = MentionedMediaSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId, mediaId } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as unknown as {
		data: IgAccountRow | null;
		error: Error | null;
	};

	if (accountError || !account) {
		return apiError(res, 404, "Instagram account not found");
	}
	if (!account.instagram_access_token_encrypted) {
		return apiError(res, 400, "Account token not available");
	}

	const loginType = account.login_type || "instagram";
	logger.info("[IG Insights] Fetching mentioned media", {
		accountId,
		mediaId,
		loginType,
	});

	const { getMentionedMedia } = await import("../../instagramApi.js");
	const result = await getMentionedMedia(
		account.instagram_access_token_encrypted as string,
		account.instagram_user_id as string,
		mediaId,
		loginType,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	return apiSuccess(res, { media: result.media ?? null });
}

async function handlePublishingLimit(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = PublishingLimitSchema.safeParse(req.body);
	if (!parsed.success) {
		return apiError(
			res,
			400,
			`Invalid input: ${parsed.error.issues[0]?.message}`,
		);
	}
	const { accountId } = parsed.data;

	const { data: account, error: accountError } = (await getSupabase()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as unknown as {
		data: IgAccountRow | null;
		error: Error | null;
	};

	if (accountError || !account) {
		logger.error("[IG Insights] Publishing limit account lookup failed", {
			accountId,
			userId,
			error: accountError?.message,
		});
		return apiError(res, 404, "Instagram account not found");
	}

	const loginType = account.login_type || "instagram";
	logger.info("[IG Insights] Checking publishing limit", {
		accountId,
		loginType,
	});

	const { checkPublishingLimit } = await import("../../instagramApi.js");

	const result = await checkPublishingLimit(
		account.instagram_access_token_encrypted as string,
		account.instagram_user_id as string,
		loginType,
	);

	if (!result.success) {
		return await handleIgAuthError(
			res,
			accountId,
			userId,
			result.error || "Unknown error",
		);
	}

	return apiSuccess(res, { quota: result.quota });
}

export default withAuth(async (req, res, user) => {
	const userId = user.id;

	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const action = req.query.action as string;

	try {
		switch (action) {
			case "account-insights":
				return handleAccountInsights(req, res, userId);
			case "post-insights":
				return handlePostInsights(req, res, userId);
			case "carousel-children":
				return handleCarouselChildren(req, res, userId);
			case "publishing-limit":
				return handlePublishingLimit(req, res, userId);
			case "tagged-posts":
				return handleTaggedPosts(req, res, userId);
			case "mentioned-media":
				return handleMentionedMedia(req, res, userId);
			default:
				return apiError(res, 400, `Unknown action: ${action}`);
		}
	} catch (error: unknown) {
		logger.error("Instagram insights API error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
