// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Analytics Handlers: queue-sync + job-status
 *
 * Parallel QStash fan-out sync. Every account (Threads + IG) gets its own
 * QStash job with a dedicated 60s Vercel budget. Progress is tracked
 * atomically via Redis INCR counters + Supabase Realtime.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getQStashClient } from "../../qstash.js";
import { getJobStatus, getRedis, getUserCurrentJob } from "../../redis.js";
import { getSupabase } from "../../supabase.js";
import { neqOrNull } from "../../supabaseSafe.js";
import { createSyncJob } from "../../syncProgress.js";
import { parseBodyOrError, parseQueryOrError } from "../../validation.js";
import { z } from "../../zodCompat.js";

const db = () => getSupabase();

// ============================================================================
// Zod Schemas
// ============================================================================

const QueueSyncSchema = z.object({
	accountIds: z.array(z.string()).optional(),
	igAccountIds: z.array(z.string()).optional(),
	trigger: z.string().optional(),
});

const JobStatusSchema = z.object({
	jobId: z.string().optional(),
});

// ============================================================================
// POST /api/analytics?action=queue-sync
// Fan out ALL accounts to QStash for parallel processing.
// ============================================================================

export async function handleQueueSync(req: VercelRequest, res: VercelResponse) {
	logger.info("handleQueueSync called");

	const authHeader = req.headers.authorization;
	if (!authHeader?.startsWith("Bearer ")) {
		return apiError(res, 401, "Missing or invalid authorization header");
	}

	const authToken = authHeader.replace("Bearer ", "");
	const {
		data: { user },
		error: authError,
	} = await db().auth.getUser(authToken);

	if (authError || !user) {
		return apiError(res, 401, "Invalid or expired token");
	}

	const userId = user.id;

	if (
		!process.env.UPSTASH_REDIS_REST_URL ||
		!process.env.UPSTASH_REDIS_REST_TOKEN
	) {
		return apiError(res, 503, "Queue service not configured", {
			details:
				"Set UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN environment variables",
		});
	}

	try {
		// Check if user already has an active job
		const existingJob = await getUserCurrentJob(userId);
		if (
			existingJob &&
			(existingJob.status === "queued" || existingJob.status === "processing")
		) {
			const jobAgeMs = Date.now() - existingJob.createdAt;
			const STALE_THRESHOLD = 10 * 60 * 1000; // 10 minutes

			if (jobAgeMs < STALE_THRESHOLD) {
				return apiSuccess(res, {
					queued: false,
					existingJob: true,
					job: existingJob,
					message: "You already have a sync in progress",
				});
			}

			// Stale job — clear it so a new one can be created
			logger.warn("Clearing stale sync job", {
				jobId: existingJob.id,
				status: existingJob.status,
				ageMinutes: Math.round(jobAgeMs / 60000),
			});
			const redis = getRedis();
			await redis.del(`sync-jobs:job:${existingJob.id}`);
			await redis.del(`sync-jobs:user:${userId}`);
		}

		// Parse body
		const parsed = parseBodyOrError(res, QueueSyncSchema, req.body);
		if (!parsed) return;
		let { accountIds, igAccountIds, trigger } = parsed;

		// Dashboard-open trigger: deduplicate with 15-min cooldown
		if (trigger === "dashboard-open") {
			const redis = getRedis();
			const cooldownKey = `dashboard-sync-cooldown:${userId}`;
			const existing = await redis.get(cooldownKey);
			if (existing) {
				return apiSuccess(res, {
					queued: false,
					message: "Recent sync already triggered",
				});
			}
			await redis.set(cooldownKey, "1", { ex: 900 });
		}

		// Fetch / validate accounts in parallel
		const [resolvedAccountIds, resolvedIgAccountIds] = await Promise.all([
			// Threads: validate provided IDs or fetch all active
			(accountIds && accountIds.length > 0
				? db()
						.from("accounts")
						.select("id")
						.eq("user_id", userId)
						.in("id", accountIds)
				: neqOrNull(
						db()
							.from("accounts")
							.select("id")
							.eq("user_id", userId)
							.eq("is_active", true),
						"status",
						"suspended",
					)
			).then(({ data }: { data: { id: string }[] | null }) =>
				(data || []).map((a: { id: string }) => a.id),
			),
			// IG: validate provided IDs or fetch all active
			(igAccountIds && igAccountIds.length > 0
				? db()
						.from("instagram_accounts")
						.select("id")
						.eq("user_id", userId)
						.in("id", igAccountIds)
				: neqOrNull(
						db()
							.from("instagram_accounts")
							.select("id")
							.eq("user_id", userId)
							.eq("is_active", true),
						"status",
						"suspended",
					)
			).then(({ data }: { data: { id: string }[] | null }) =>
				(data || []).map((a: { id: string }) => a.id),
			),
		]);
		accountIds = resolvedAccountIds;
		igAccountIds = resolvedIgAccountIds;

		const threadsIds = accountIds ?? [];
		const igIds = igAccountIds ?? [];

		if (threadsIds.length === 0 && igIds.length === 0) {
			return apiSuccess(res, {
				queued: false,
				message: "No accounts to sync",
			});
		}

		// Bust IG no-insights cache (fire-and-forget — not on critical path)
		if (igIds.length > 0) {
			const redis = getRedis();
			Promise.all(
				igIds.map((id) => redis.del(`ig-no-insights:${id}`).catch(() => {})),
			).catch(() => {});
		}

		// Create job for progress tracking (no Redis queue — all QStash)
		const totalAccounts = threadsIds.length + igIds.length;
		const jobId = await createSyncJob(userId, totalAccounts);

		// Fan out ALL accounts to QStash via a single batch call
		const baseUrl = process.env.APP_URL || `https://${process.env.VERCEL_URL}`;
		const qstash = getQStashClient();
		const dateKey = new Date().toISOString().split("T")[0]!;

		const messages = [
			...threadsIds.map((accountId, i) => ({
				url: `${baseUrl}/api/sync/threads-account`,
				body: { accountId, userId, syncType: "metrics", jobId },
				retries: 3,
				delay: Math.floor(i / 10) * 2, // Stagger: 10 accounts per 2s wave
				deduplicationId: `threads-${accountId}-${dateKey}`,
			})),
			...igIds.map((accountId, i) => ({
				url: `${baseUrl}/api/sync/ig-account`,
				body: { accountId, userId, syncType: "metrics", jobId },
				retries: 3,
				delay: Math.floor(i / 10) * 2, // Stagger: 10 accounts per 2s wave
				deduplicationId: `ig-${accountId}-${dateKey}`,
			})),
		];

		const { MAX_BATCH_SIZE } = await import("../../qstashDefaults.js");
		let dispatched = 0;

		// Chunk into batches to stay under QStash limits
		for (let start = 0; start < messages.length; start += MAX_BATCH_SIZE) {
			const chunk = messages.slice(start, start + MAX_BATCH_SIZE);
			try {
				await qstash.batchJSON(chunk);
				dispatched += chunk.length;
			} catch (qErr) {
				logger.warn(
					"QStash batchJSON failed, falling back to parallel dispatch",
					{
						error: String(qErr),
						chunkStart: start,
						chunkSize: chunk.length,
					},
				);
				const results = await Promise.allSettled(
					chunk.map((msg) =>
						qstash.publishJSON({
							url: msg.url,
							body: msg.body,
							retries: msg.retries,
							delay: msg.delay,
							deduplicationId: msg.deduplicationId,
						}),
					),
				);
				dispatched += results.filter((r) => r.status === "fulfilled").length;
			}
		}

		logger.info("Sync fan-out complete", {
			jobId,
			totalAccounts,
			dispatched,
			threadsCount: threadsIds.length,
			igCount: igIds.length,
		});

		return apiSuccess(res, {
			queued: true,
			job: {
				id: jobId,
				status: "processing",
				accountCount: totalAccounts,
				createdAt: Date.now(),
			},
			message: `Sync dispatched for ${totalAccounts} accounts`,
		});
	} catch (error: unknown) {
		const message = error instanceof Error ? error.message : String(error);
		logger.error("Queue sync error", { error: message });
		return apiError(res, 500, "Failed to queue sync job", {
			details: message,
		});
	}
}

// ============================================================================
// POST /api/analytics?action=job-status
// Get job status for polling.
// ============================================================================

export async function handleJobStatus(req: VercelRequest, res: VercelResponse) {
	const authHeader = req.headers.authorization;
	if (!authHeader?.startsWith("Bearer ")) {
		return apiError(res, 401, "Missing or invalid authorization header");
	}

	const authToken = authHeader.replace("Bearer ", "");
	const {
		data: { user },
		error: authError,
	} = await db().auth.getUser(authToken);

	if (authError || !user) {
		return apiError(res, 401, "Invalid or expired token");
	}

	if (
		!process.env.UPSTASH_REDIS_REST_URL ||
		!process.env.UPSTASH_REDIS_REST_TOKEN
	) {
		return apiError(res, 503, "Queue service not configured");
	}

	try {
		const parsed =
			req.method === "GET"
				? parseQueryOrError(res, JobStatusSchema, req.query)
				: parseBodyOrError(res, JobStatusSchema, req.body);
		if (!parsed) return;
		const { jobId } = parsed;

		const job = jobId
			? await getJobStatus(jobId)
			: await getUserCurrentJob(user.id);

		if (!job) {
			return apiSuccess(res, {
				job: null,
				message: "No active sync job found",
			});
		}

		if (job.userId !== user.id) {
			return apiError(res, 403, "Access denied");
		}

		return apiSuccess(res, { job });
	} catch (error: unknown) {
		const message = error instanceof Error ? error.message : String(error);
		logger.error("Job status error", { error: message });
		return apiError(res, 500, "Failed to get job status", {
			details: message,
		});
	}
}
