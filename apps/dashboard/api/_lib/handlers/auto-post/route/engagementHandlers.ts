/**
 * Engagement handler modules for auto-post API.
 * Handles: log-activity, sync-engagement, fetch-engagement
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../../apiResponse.js";
import { logger } from "../../../logger.js";
import { getRedis } from "../../../redis.js";
import { requireMinTier } from "../../../tierGate.js";
import {
	db,
	getPostMetricsLazy,
	getUserCurrentEngagementJob,
	queueEngagementSyncJob,
	verifyWorkspaceAccess,
} from "./routeHelpers.js";

export async function handleLogActivity(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const {
		workspaceId,
		activityType,
		accountHandle,
		postIndex,
		nextPostIn,
		message,
	} = req.body;

	if (!workspaceId) return apiError(res, 400, "workspaceId is required");
	if (!activityType) return apiError(res, 400, "activityType is required");

	// Fix 10: Verify workspace access BEFORE tier check.
	// This ensures a user can't probe tier-gated features for workspaces they don't belong to.
	if (!(await verifyWorkspaceAccess(userId, workspaceId, res))) return;
	if (!(await requireMinTier(userId, "empire", res))) return;

	const { data: activity, error: insertError } = await db()
		.from("auto_post_activity")
		.insert({
			workspace_id: workspaceId,
			activity_type: activityType,
			account_handle: accountHandle,
			post_index: postIndex,
			next_post_in: nextPostIn,
			message,
			created_at: new Date().toISOString(),
		})
		.select()
		.maybeSingle();

	if (insertError) {
		logger.error("Activity insert error", {
			error: String(insertError),
			code: insertError.code,
			hint: insertError.hint,
		});
		return apiError(res, 500, "Failed to log activity");
	}

	return apiSuccess(res, { activity });
}

/**
 * Sync engagement metrics for posts that were published 24+ hours ago
 * Queue-based: queues job for background processing
 */
export async function handleSyncEngagement(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { workspaceId } = req.body;
	if (!workspaceId) return apiError(res, 400, "workspaceId is required");

	// Subscription tier check — sync engagement requires Pro or higher
	if (!(await requireMinTier(userId, "pro", res))) return;

	const redis = getRedis();
	if (!redis) {
		return apiError(res, 503, "Queue service not configured");
	}

	try {
		// Check for existing job
		const existingJob = await getUserCurrentEngagementJob(
			userId,
			"auto-post-engagement",
		);
		if (
			existingJob &&
			(existingJob.status === "queued" || existingJob.status === "processing")
		) {
			return apiSuccess(res, {
				queued: false,
				existingJob: true,
				job: existingJob,
				message: "You already have an engagement sync in progress",
			});
		}

		// Queue the job
		const job = await queueEngagementSyncJob(userId, "auto-post-engagement", {
			workspaceId,
		});

		// Write to sync_jobs table for Realtime
		try {
			await db()
				.from("sync_jobs")
				.upsert(
					{
						id: job.id,
						user_id: userId,
						job_type: "engagement",
						status: "queued",
						current_progress: 0,
						created_at: new Date(job.createdAt).toISOString(),
					},
					{ onConflict: "id" },
				);
		} catch (dbError) {
			logger.warn("Failed to write to sync_jobs", { error: String(dbError) });
		}

		logger.info("Queued engagement sync job", { jobId: job.id, workspaceId });

		return apiSuccess(res, {
			queued: true,
			job: {
				id: job.id,
				status: job.status,
				createdAt: job.createdAt,
			},
			message: "Engagement sync queued",
		});
	} catch (error: unknown) {
		logger.error("Queue sync error", { error: String(error) });
		return apiError(res, 500, "Failed to queue engagement sync");
	}
}

/**
 * Fetch engagement metrics for a specific post
 */
export async function handleFetchEngagement(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { postId } = req.body;
	if (!postId) return apiError(res, 400, "postId is required");

	const supabase = db();

	// Get the post with account info — check auto_post_queue first, fall back to posts table
	let post: {
		id: string;
		threads_post_id: string | null;
		account_id: string | null;
		accounts: unknown;
	} | null = null;
	let sourceTable: "auto_post_queue" | "posts" = "auto_post_queue";

	const { data: queuePost } = await supabase
		.from("auto_post_queue")
		.select(
			`
      id,
      threads_post_id,
      account_id,
      accounts!auto_post_queue_account_id_fkey (
        id,
        access_token_encrypted
      )
    `,
		)
		.eq("id", postId)
		.maybeSingle();

	if (queuePost) {
		post = queuePost;
	} else {
		// Post may have moved to posts table after publishing
		const { data: publishedPost } = await supabase
			.from("posts")
			.select(
				`
        id,
        threads_post_id,
        account_id,
        accounts!posts_account_id_fkey (
          id,
          access_token_encrypted
        )
      `,
			)
			.eq("id", postId)
			.maybeSingle();
		if (publishedPost) {
			post = publishedPost;
			sourceTable = "posts";
		}
	}

	if (!post) {
		return apiError(res, 404, "Post not found");
	}

	// Verify ownership via account — deny if account_id is null
	if (!post.account_id) {
		return apiError(res, 403, "Not authorized");
	}
	const { data: accountOwner } = await db()
		.from("accounts")
		.select("user_id")
		.eq("id", post.account_id)
		.maybeSingle();
	if (!accountOwner || accountOwner.user_id !== userId) {
		return apiError(res, 403, "Not authorized");
	}

	const account = post.accounts as unknown as {
		id: string;
		access_token_encrypted: string;
	} | null;

	if (!account?.access_token_encrypted) {
		return apiError(res, 400, "Account token not found");
	}

	if (!post.threads_post_id) {
		return apiError(res, 400, "Post has no Threads ID");
	}

	const result = await getPostMetricsLazy(
		account.access_token_encrypted,
		post.threads_post_id,
	);

	if (!result.success) {
		logger.error("Failed to fetch post metrics", { error: result.error });
		return apiError(res, 500, "Failed to fetch engagement metrics");
	}

	// Update the post with metrics in the source table
	if (sourceTable === "auto_post_queue") {
		const { error: updateError } = await supabase
			.from("auto_post_queue")
			.update({
				views_at_24h: result.metrics?.views,
				likes_count: result.metrics?.likes,
				replies_count: result.metrics?.replies,
				reposts_count: result.metrics?.reposts,
				engagement_rate: result.metrics?.engagementRate,
				engagement_fetched_at: new Date().toISOString(),
			})
			.eq("id", postId);
		if (updateError) {
			logger.error("[engagementHandlers] Failed to update auto_post_queue metrics", { postId, error: String(updateError) });
			return apiError(res, 500, "Failed to update post metrics");
		}
	} else {
		// Post is in posts table — update metrics there
		const { error: updateError } = await supabase
			.from("posts")
			.update({
				views_count: result.metrics?.views,
				likes_count: result.metrics?.likes,
				replies_count: result.metrics?.replies,
				reposts_count: result.metrics?.reposts,
				engagement_rate: result.metrics?.engagementRate,
			})
			.eq("id", postId);
		if (updateError) {
			logger.error("[engagementHandlers] Failed to update posts table metrics", { postId, error: String(updateError) });
			return apiError(res, 500, "Failed to update post metrics");
		}
	}

	return apiSuccess(res, { metrics: result.metrics, source: sourceTable });
}
