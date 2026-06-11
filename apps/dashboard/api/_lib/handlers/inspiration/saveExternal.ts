/**
 * Save an external post (from search results) as inspiration.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	badRequest,
	serverError,
} from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db, getSupabaseAny } from "./shared.js";

export async function handleSaveExternal(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { post } = req.body;
	if (!post?.content) {
		return badRequest(res, "Post with content is required");
	}

	try {
		// Check if we already saved this post (by permalink or content hash)
		if (post.id) {
			const { count: existingCount } = await getSupabaseAny()
				.from("inspiration_ideas")
				.select("*", { count: "exact", head: true })
				.eq("user_id", userId)
				.eq("original_post->id", post.id);

			if (existingCount && existingCount > 0) {
				return apiError(res, 409, "Post already saved to inspiration");
			}
		}

		// Calculate engagement score
		const engagementScore =
			(post.likeCount || 0) +
			(post.replyCount || 0) * 2 +
			(post.repostCount || 0) * 3;

		// Calculate a simple viral score based on engagement
		const viralScore = Math.min(
			100,
			Math.round(Math.log10(Math.max(1, engagementScore)) * 25),
		);

		// Save as inspiration idea (without AI adaptation - the original IS the adapted content)
		const { data, error } = await db()
			.from("inspiration_ideas")
			.insert({
				user_id: userId,
				original_post: {
					id: post.id || `external-${Date.now()}`,
					content: post.content,
					mediaUrl: post.mediaUrl,
					mediaType: post.mediaType,
					permalink: post.permalink,
					engagementScore,
					likes: post.likeCount || 0,
					replies: post.replyCount || 0,
					reposts: post.repostCount || 0,
				},
				competitor_username: post.username || "discovered",
				adapted_content: post.content, // Use original as adapted (no AI transformation)
				viral_score: viralScore,
				ai_insight: `Saved from search results. Engagement: ${engagementScore.toLocaleString()}`,
				topic_tags: [], // Could extract hashtags from content
				adaptation_style: "casual",
				status: "saved", // Mark as saved directly
				saved: true,
				generated_at: new Date().toISOString(),
				expires_at: new Date(
					Date.now() + 90 * 24 * 60 * 60 * 1000,
				).toISOString(), // 90 days for saved items
			})
			.select()
			.maybeSingle();

		if (error) throw error;

		return apiSuccess(res, { idea: data }, 201);
	} catch (error: unknown) {
		logger.error("Save external error", { error: String(error) });
		return serverError(res, "Internal server error");
	}
}
