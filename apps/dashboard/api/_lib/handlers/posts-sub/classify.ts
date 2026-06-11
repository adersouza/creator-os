/**
 * POST /api/posts/classify — Classify posts into content categories
 * Accepts { postIds: string[] } (max 20 per request)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getUserAIConfig } from "../../aiConfig.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { classifyPost } from "../../contentClassifier.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { getSupabase, getSupabaseAny } from "../../supabase.js";

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		const { postIds } = req.body || {};
		if (!Array.isArray(postIds) || postIds.length === 0) {
			return apiError(res, 400, "postIds array is required");
		}
		if (postIds.length > 20) {
			return apiError(res, 400, "Maximum 20 posts per request");
		}
		if (
			!postIds.every((id: unknown) => typeof id === "string" && id.length > 0)
		) {
			return apiError(res, 400, "postIds must be non-empty strings");
		}

		// Rate limit
		const rl = await checkRateLimit({
			key: `classify:${user.id}`,
			limit: 30,
			windowSeconds: 60,
			failMode: "closed",
		});
		if (!rl.allowed) {
			return apiError(res, 429, "Rate limit exceeded");
		}

		// Get AI config
		const aiConfig = await getUserAIConfig(user.id);
		if (!aiConfig) {
			return apiError(
				res,
				503,
				"AI features temporarily unavailable. Add your own API key in Settings for immediate access.",
				{ code: "NO_API_KEY" },
			);
		}

		const supabase = getSupabase();

		// Fetch posts (IDOR fix: scope to authenticated user)
		const { data: posts, error: fetchError } = await supabase
			.from("posts")
			.select("id, content, media_type, platform, account_id")
			.in("id", postIds)
			.eq("user_id", user.id);

		if (fetchError) {
			logger.error("[posts/classify] Fetch failed", {
				error: fetchError.message,
			});
			return apiError(res, 500, "Failed to fetch posts");
		}

		if (!posts || posts.length === 0) {
			return apiError(res, 404, "No posts found");
		}

		// Classify each post
		const results: Array<{ id: string; category: string; confidence: number }> =
			[];

		for (const post of posts) {
			const caption = post.content || "";
			const hashtags = caption.match(/#\w+/g) || [];
			const platform = post.platform || "threads";
			const mediaType = post.media_type || "TEXT";

			const classification = await classifyPost(
				aiConfig,
				caption,
				mediaType,
				hashtags,
				platform,
				user.id,
			);

			// Update post in DB (content_category columns added via migration)
			await getSupabaseAny()
				.from("posts")
				.update({
					content_category: classification.primary,
					content_category_confidence: classification.confidence,
				})
				.eq("id", post.id);

			results.push({
				id: post.id,
				category: classification.primary,
				confidence: classification.confidence,
			});
		}

		return apiSuccess(res, { classified: results.length, results });
	},
);
