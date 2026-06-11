/**
 * Post Comments — GET /api/posts/comments
 *
 * Returns comments/replies for a specific post from local DB.
 * Works for both Threads (post_replies table) and Instagram (ig_comments table).
 *
 * Query params:
 *   postId: string (required) — the post ID
 *   platform: "threads" | "instagram" (required)
 *   limit: number (default 50, max 100)
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { withAuthDb } from "../../middleware.js";

type UserDb = DbContext["userDb"];

async function handleComments(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	const postId = req.query.postId as string;
	const platform = req.query.platform as string;
	if (!postId) return apiError(res, 400, "postId is required");
	if (!platform || !["threads", "instagram"].includes(platform)) {
		return apiError(res, 400, "platform must be 'threads' or 'instagram'");
	}

	const limit = Math.min(
		100,
		Math.max(1, parseInt(req.query.limit as string, 10) || 50),
	);

	if (platform === "threads") {
		// Verify post belongs to user
		const { data: post } = await userDb
			.from("posts")
			.select("id, content, account_id")
			.eq("id", postId)
			.eq("user_id", userId)
			.maybeSingle();

		if (!post) return apiError(res, 404, "Post not found");

		const { data: replies, error } = await userDb
			.from("post_replies")
			.select(
				"id, username, display_name, avatar_url, content, likes_count, is_read, created_at",
			)
			.eq("post_id", postId)
			.order("created_at", { ascending: false })
			.limit(limit);

		if (error) return apiError(res, 500, "Failed to fetch replies");

		return apiSuccess(res, {
			postId,
			platform,
			postPreview: post.content?.slice(0, 120),
			comments: replies ?? [],
			total: (replies ?? []).length,
		});
	}

	// Instagram — verify post belongs to user
	const { data: post } = await userDb
		.from("posts")
		.select("id, content")
		.eq("id", postId)
		.eq("user_id", userId)
		.maybeSingle();

	if (!post) return apiError(res, 404, "Post not found");

	// ig_comments.post_id is a FK to posts.id — query directly without media_id lookup
	const { data: comments, error } = await userDb
		.from("ig_comments")
		.select("id, comment_id, username, text, created_at, ig_user_id, is_read")
		.eq("post_id", postId)
		.order("created_at", { ascending: false })
		.limit(limit);

	if (error) return apiError(res, 500, "Failed to fetch comments");

	return apiSuccess(res, {
		postId,
		platform,
		postPreview: post.content?.slice(0, 120),
		comments: comments ?? [],
		total: (comments ?? []).length,
	});
}

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, context) =>
		handleComments(req, res, context.user.id, context.userDb),
);
