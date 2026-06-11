/**
 * Delete handlers — single post delete and bulk delete.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { deleteFromThreads } from "../../threadsApi.js";
import { DeletePostSchema, parseBodyOrError } from "../../validation.js";
import {
	db,
	type IgAccountTokenRow,
	type OwnedPostRow,
	type PostRow,
	type ThreadsAccountTokenRow,
} from "./shared.js";

export async function handleDelete(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const parsed = parseBodyOrError(res, DeletePostSchema, req.body);
	if (!parsed) return;
	const { postId } = parsed;

	const { data: post, error: postError } = (await db()
		.from("posts")
		.select(
			"id, user_id, account_id, instagram_account_id, threads_post_id, instagram_post_id, platform, status, metadata",
		)
		.eq("id", postId)
		.eq("user_id", userId)
		.maybeSingle()) as {
		data: (PostRow & { metadata?: Record<string, unknown> | null | undefined }) | null;
		error: unknown;
	};

	if (postError || !post) {
		return apiError(res, 404, "Post not found");
	}

	// Verify user has workspace access to the account that owns this post
	// Authorization: post ownership is verified via user_id on the post itself

	// Delete from platform
	if (post.platform === "instagram" && post.instagram_post_id) {
		// Delete from Instagram
		const { data: igAccount } = (await db()
			.from("instagram_accounts")
			.select("instagram_access_token_encrypted, login_type")
			.eq("id", post.instagram_account_id ?? "")
			.eq("user_id", userId)
			.maybeSingle()) as { data: IgAccountTokenRow | null; error: unknown };

		if (igAccount?.instagram_access_token_encrypted) {
			if ((igAccount.login_type || "instagram") !== "facebook") {
				return apiError(
					res,
					400,
					"Delete unsupported on Instagram Login accounts.",
					{ code: "media_deletion_unsupported_on_ig_login" },
				);
			}
			const { deleteFromInstagram } = await import("../../instagramApi.js");
			await deleteFromInstagram(
				igAccount.instagram_access_token_encrypted,
				post.instagram_post_id,
			);
		}
	} else if (post.threads_post_id) {
		// Delete from Threads
		const { data: account } = (await db()
			.from("accounts")
			.select("threads_access_token_encrypted")
			.eq("id", post.account_id ?? "")
			.eq("user_id", userId)
			.maybeSingle()) as {
			data: ThreadsAccountTokenRow | null;
			error: unknown;
		};

		if (account?.threads_access_token_encrypted) {
			await deleteFromThreads(
				account.threads_access_token_encrypted,
				post.threads_post_id,
			);
		}
	}

	// Cancel QStash message if scheduled (prevents orphaned exact-time delivery)
	if (post.status === "scheduled" && post.metadata?.qstash_message_id) {
		try {
			const { cancelPostPublish } = await import("../../qstashSchedule.js");
			await cancelPostPublish(postId);
		} catch {
			/* Non-critical — message may have already fired */
		}
	}

	const { error: deleteError } = await db()
		.from("posts")
		.delete()
		.eq("id", postId)
		.eq("user_id", userId);

	if (deleteError) {
		return apiError(res, 500, "Failed to delete post");
	}

	return apiSuccess(res, {});
}

/**
 * Handle bulk delete of posts
 * Accepts { postIds: string[] } with a max of 50 items.
 * Verifies ownership for all posts before deleting.
 */
export async function handleDeleteBulk(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { postIds } = req.body || {};

	if (!Array.isArray(postIds) || postIds.length === 0) {
		return apiError(res, 400, "postIds must be a non-empty array");
	}

	if (postIds.length > 50) {
		return apiError(res, 400, "Maximum 50 posts per bulk delete");
	}

	// Validate all entries are non-empty strings
	if (postIds.some((id: unknown) => typeof id !== "string" || !id)) {
		return apiError(res, 400, "All postIds must be non-empty strings");
	}

	// Verify ownership: fetch all posts and confirm they belong to the user
	const { data: posts, error: fetchError } = await db()
		.from("posts")
		.select("id, status, metadata")
		.in("id", postIds)
		.eq("user_id", userId);

	if (fetchError) {
		logger.error("Bulk delete fetch error", { error: String(fetchError) });
		return apiError(res, 500, "Failed to verify post ownership");
	}

	const ownedIds = (posts || []).map((p: OwnedPostRow) => p.id);
	const unauthorizedIds = postIds.filter(
		(id: string) => !ownedIds.includes(id),
	);

	if (unauthorizedIds.length > 0) {
		return apiError(
			res,
			403,
			"Some posts were not found or you don't have permission to delete them",
		);
	}

	// Cancel QStash messages for scheduled posts before deletion
	const scheduledWithQStash = (posts || []).filter(
		// biome-ignore lint/suspicious/noExplicitAny: Supabase untyped select
		(p: any) => p.status === "scheduled" && p.metadata?.qstash_message_id,
	);
	if (scheduledWithQStash.length > 0) {
		try {
			const { cancelPostPublish } = await import("../../qstashSchedule.js");
			await Promise.all(
				scheduledWithQStash.map((p: { id: string }) =>
					cancelPostPublish(p.id).catch(() => {}),
				),
			);
		} catch {
			/* Non-critical */
		}
	}

	// Delete all owned posts in a single query
	const { error: deleteError } = await db()
		.from("posts")
		.delete()
		.in("id", ownedIds)
		.eq("user_id", userId);

	if (deleteError) {
		logger.error("Bulk delete error", { error: String(deleteError) });
		return apiError(res, 500, "Failed to delete posts");
	}

	return apiSuccess(res, { deleted: ownedIds.length });
}
