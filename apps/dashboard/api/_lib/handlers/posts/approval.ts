/**
 * Approval handler — approve or reject posts.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { canApprovePost } from "../../postAuthorization.js";
import { db, type PostUpdateData } from "./shared.js";

/**
 * Handle post approval/rejection
 */
export async function handleApproval(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	status: "approved" | "rejected",
) {
	const { postId, notes } = req.body;

	if (!postId) {
		return apiError(res, 400, "postId required");
	}

	// Get the post — no user_id filter here because workspace admins may approve team members' posts
	const { data: post } = await db()
		.from("posts")
		.select("id, user_id, account_id, instagram_account_id, scheduled_for")
		.eq("id", postId)
		.maybeSingle();

	if (!post) return apiError(res, 404, "Post not found");

	const typedPost = post as {
		id: string;
		user_id: string;
		account_id: string | null;
		instagram_account_id: string | null;
		scheduled_for: string | null;
	};

	// Cross-tenant IDOR guard — scoped to the workspace containing the post's account
	// Use whichever account ID is set (Threads = account_id, IG = instagram_account_id)
	const effectiveAccountId = typedPost.account_id || typedPost.instagram_account_id;
	const allowed = await canApprovePost(
		db(),
		userId,
		typedPost.user_id,
		effectiveAccountId,
	);
	if (!allowed) {
		return apiError(res, 403, "Only admins and owners can approve posts");
	}

	const now = new Date().toISOString();
	const updateData: PostUpdateData = { approval_status: status };
	if (notes) {
		updateData.approval_notes = notes;
	}
	// If approved and has a scheduled time, transition to "scheduled" so the
	// publish cron picks it up. Otherwise fall back to "draft".
	if (status === "approved") {
		updateData.approved_by = userId;
		updateData.approved_at = now;
		updateData.status = typedPost.scheduled_for ? "scheduled" : "draft";
	} else {
		updateData.rejected_by = userId;
		updateData.rejected_at = now;
		updateData.status = "draft";
		updateData.scheduled_for = null;
	}

	const postsDb = db();
	const { data, error } = await postsDb
		.from("posts")
		.update(updateData)
		.eq("id", postId)
		.select()
		.maybeSingle();

	if (error) {
		logger.error("Post approval update error", { error: String(error) });
		return apiError(res, 500, "Failed to update post approval");
	}

	return apiSuccess(res, { post: data, status });
}
