/**
 * Handlers for syncing reply metrics (queued and legacy).
 * Action: "sync-metrics"
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiSuccess, serverError } from "../../apiResponse.js";
import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { getRedis } from "../../redis.js";
import { withRetry } from "../../retryUtils.js";
import { getSupabase, getSupabaseAny } from "../../supabase.js";
import {
	getUserCurrentEngagementJob,
	queueEngagementSyncJob,
} from "./shared.js";

export async function handleSyncMetrics(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	// Check if Redis is available for queue-based sync
	const redis = getRedis();
	if (redis) {
		return handleQueuedSyncMetrics(req, res, userId);
	}

	// Fallback to synchronous sync
	return handleSyncMetricsLegacy(req, res, userId);
}

// Queue-based reply metrics sync
async function handleQueuedSyncMetrics(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	try {
		// Check for existing job
		const existingJob = await getUserCurrentEngagementJob(
			userId,
			"reply-metrics",
		);
		if (
			existingJob &&
			(existingJob.status === "queued" || existingJob.status === "processing")
		) {
			return apiSuccess(res, {
				queued: false,
				existingJob: true,
				job: existingJob,
				message: "You already have a reply metrics sync in progress",
			});
		}

		// Queue the job
		const job = await queueEngagementSyncJob(userId, "reply-metrics");

		// Write to sync_jobs table for Realtime
		try {
			await getSupabase()
				.from("sync_jobs")
				.upsert(
					{
						id: job.id,
						user_id: userId,
						job_type: "reply-metrics",
						status: "queued",
						current_progress: 0,
						created_at: new Date(job.createdAt).toISOString(),
					},
					{ onConflict: "id" },
				);
		} catch (dbError) {
			logger.warn("Failed to write to sync_jobs", { error: String(dbError) });
		}

		logger.info("Queued reply-metrics sync job", { jobId: job.id });

		return apiSuccess(res, {
			queued: true,
			job: {
				id: job.id,
				status: job.status,
				createdAt: job.createdAt,
			},
			message: "Reply metrics sync queued",
		});
	} catch (error: unknown) {
		logger.error("Queue sync-metrics error", {
			error: error instanceof Error ? error.message : String(error),
		});
		return serverError(res, "Internal server error");
	}
}

// Legacy synchronous reply metrics sync
async function handleSyncMetricsLegacy(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	// Get all sent replies with threads_reply_id
	const { data: sentReplies, error: fetchError } = await getSupabase()
		.from("sent_replies")
		.select("id, threads_reply_id, account_id")
		.eq("user_id", userId)
		.not("threads_reply_id", "is", null)
		.limit(100);

	if (fetchError || !sentReplies) {
		return serverError(res, "Failed to fetch sent replies");
	}

	if (sentReplies.length === 0) {
		return apiSuccess(res, {
			message: "No sent replies to sync",
			updatedCount: 0,
		});
	}

	interface SentReply {
		id: string;
		account_id: string;
		threads_reply_id: string;
	}
	// Group by account to minimize token decryption
	const sentRepliesArray = sentReplies as SentReply[];
	const replysByAccount = new Map<string, SentReply[]>();
	for (const reply of sentRepliesArray) {
		const list = replysByAccount.get(reply.account_id) || [];
		list.push(reply);
		replysByAccount.set(reply.account_id, list);
	}

	let updatedCount = 0;

	// Batch-fetch all accounts upfront (eliminates N+1 per-account queries)
	const accountIds = Array.from(replysByAccount.keys());
	const { data: accountRows } = await getSupabase()
		.from("accounts")
		.select("id, threads_access_token_encrypted")
		.in("id", accountIds)
		.eq("user_id", userId);

	const tokensByAccount = new Map<string, string>();
	for (const acct of (accountRows || []) as {
		id: string;
		threads_access_token_encrypted?: string | undefined;
	}[]) {
		if (acct.threads_access_token_encrypted) {
			tokensByAccount.set(
				acct.id,
				decrypt(acct.threads_access_token_encrypted),
			);
		}
	}

	// Collect all metric updates, then batch-write
	const updates: {
		id: string;
		likes_count: number;
		replies_count: number;
		metrics_updated_at: string;
	}[] = [];

	for (const [accountId, replies] of Array.from(replysByAccount.entries())) {
		const token = tokensByAccount.get(accountId);
		if (!token) continue;

		for (const reply of replies) {
			try {
				const insightsUrl = `https://graph.threads.net/v1.0/${reply.threads_reply_id}?fields=id,like_count,reply_count`;
				const response = await withRetry(
					() =>
						fetch(insightsUrl, {
							headers: { Authorization: `Bearer ${token}` },
							signal: AbortSignal.timeout(10000),
						}),
					{ label: `replyMetrics:${reply.threads_reply_id}` },
				);
				const data = await response.json();

				if (!response.ok || data.error) continue;

				updates.push({
					id: reply.id,
					likes_count: data.like_count || 0,
					replies_count: data.reply_count || 0,
					metrics_updated_at: new Date().toISOString(),
				});

				updatedCount++;
				// Rate limiting for Meta API
				await new Promise((resolve) => setTimeout(resolve, 100));
			} catch (error) {
				logger.error("Failed to sync metrics for reply", {
					replyId: reply.id,
					error: String(error),
				});
			}
		}
	}

	// Batch update all metrics in one pass
	if (updates.length > 0) {
		await Promise.all(
			updates.map((u) =>
				getSupabaseAny()
					.from("sent_replies")
					.update({
						likes_count: u.likes_count,
						replies_count: u.replies_count,
						metrics_updated_at: u.metrics_updated_at,
					})
					.eq("id", u.id),
			),
		);
	}

	return apiSuccess(res, {
		message: `Synced metrics for ${updatedCount} replies`,
		updatedCount,
	});
}
