/**
 * Handlers for reply sync (queued and legacy).
 * Action: "sync"
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import pLimit from "p-limit";
import { apiSuccess, serverError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getRedis } from "../../redis.js";
import { getSupabase } from "../../supabase.js";
import { neqOrNull } from "../../supabaseSafe.js";
import {
	ACCOUNT_CONCURRENCY,
	type AccountRecord,
	getUserCurrentReplyJob,
	processAccountReplies,
	queueReplySyncJob,
} from "./shared.js";

export async function handleSync(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	// Check if Redis is configured for queue-based sync
	const redis = getRedis();
	if (redis) {
		// Queue-based sync (preferred)
		return handleQueuedSync(req, res, userId);
	}

	// Fallback to synchronous sync if Redis not configured
	return handleSyncLegacy(req, res, userId);
}

// Queue-based reply sync (preferred when Redis is available)
async function handleQueuedSync(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	try {
		// Check if user already has an active job
		const existingJob = await getUserCurrentReplyJob(userId);
		if (
			existingJob &&
			(existingJob.status === "queued" || existingJob.status === "processing")
		) {
			return apiSuccess(res, {
				queued: false,
				existingJob: true,
				job: existingJob,
				message: "You already have a reply sync in progress",
			});
		}

		// Get account IDs to sync
		let { accountIds } = req.body;

		if (accountIds && accountIds.length > 0) {
			const uniqueIds = [...new Set(accountIds as string[])].filter(Boolean);
			const base = getSupabase()
				.from("accounts")
				.select("id")
				.eq("user_id", userId)
				.in("id", uniqueIds)
				.not("threads_access_token_encrypted", "is", null);
			const { data: accounts } = await neqOrNull(base, "status", "suspended");
			accountIds = (accounts || []).map((a: { id: string }) => a.id);
		} else {
			// If no account IDs provided, get all active accounts for user
			const base = getSupabase()
				.from("accounts")
				.select("id")
				.eq("user_id", userId)
				.not("threads_access_token_encrypted", "is", null);
			const { data: accounts } = await neqOrNull(base, "status", "suspended");

			accountIds = (accounts || []).map((a: { id: string }) => a.id);
		}

		if (accountIds.length === 0) {
			return apiSuccess(res, {
				queued: false,
				message: "No accounts to sync",
			});
		}

		// Queue the job
		const job = await queueReplySyncJob(userId, accountIds);

		// Also write to sync_jobs table for Realtime updates
		try {
			await getSupabase()
				.from("sync_jobs")
				.upsert(
					{
						id: job.id,
						user_id: userId,
						job_type: "replies",
						status: "queued",
						account_count: accountIds.length,
						current_progress: 0,
						created_at: new Date(job.createdAt).toISOString(),
					},
					{ onConflict: "id" },
				);
		} catch (dbError) {
			logger.warn("Failed to write to sync_jobs table", {
				error: String(dbError),
			});
		}

		logger.info("Queued reply sync job", {
			jobId: job.id,
			accountCount: accountIds.length,
		});

		return apiSuccess(res, {
			queued: true,
			job: {
				id: job.id,
				status: job.status,
				accountCount: accountIds.length,
				createdAt: job.createdAt,
			},
			message: `Reply sync queued for ${accountIds.length} accounts`,
		});
	} catch (error: unknown) {
		const message = error instanceof Error ? error.message : String(error);
		logger.error("Queue sync error", { error: message });
		return serverError(res, "Failed to queue reply sync", message);
	}
}

// Legacy synchronous sync (fallback when Redis not configured)
async function handleSyncLegacy(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { data: accounts, error: accountsError } = await getSupabase()
		.from("accounts")
		.select("*")
		.eq("user_id", userId)
		.not("threads_access_token_encrypted", "is", null)
		.limit(500);

	if (accountsError) {
		return serverError(res, "Failed to fetch accounts");
	}

	const accountsArray = (accounts || []) as AccountRecord[];

	if (accountsArray.length === 0) {
		return apiSuccess(res, {
			repliesFound: 0,
			postsProcessed: 0,
			accountsProcessed: 0,
		});
	}

	// Process accounts in parallel with controlled concurrency
	const limit = pLimit(ACCOUNT_CONCURRENCY);

	logger.info("Processing accounts for reply sync", {
		accountCount: accountsArray.length,
		concurrency: ACCOUNT_CONCURRENCY,
	});
	const startTime = Date.now();

	const results = await Promise.allSettled(
		accountsArray.map((account) => limit(() => processAccountReplies(account))),
	);

	// Aggregate results
	let totalReplies = 0;
	let totalPostsProcessed = 0;
	let successCount = 0;
	let failureCount = 0;

	for (const result of results) {
		if (result.status === "fulfilled") {
			totalReplies += result.value.repliesFound;
			totalPostsProcessed += result.value.postsProcessed;
			if (result.value.success) {
				successCount++;
			} else {
				failureCount++;
			}
		} else {
			failureCount++;
			logger.error("Account processing rejected", {
				reason: String(result.reason),
			});
		}
	}

	const duration = Date.now() - startTime;
	logger.info("Reply sync completed", {
		durationMs: duration,
		successCount,
		failureCount,
		totalReplies,
	});

	return apiSuccess(res, {
		repliesFound: totalReplies,
		postsProcessed: totalPostsProcessed,
		accountsProcessed: accountsArray.length,
		accountsSucceeded: successCount,
		accountsFailed: failureCount,
		durationMs: duration,
	});
}
