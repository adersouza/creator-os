/**
 * Sync Progress Tracking
 *
 * Atomic progress tracking for QStash-based parallel sync.
 * Uses Redis INCR for atomic counters + Supabase for Realtime UI updates.
 *
 * Flow:
 *   1. queueSync creates job → createSyncJob(userId, totalAccounts)
 *   2. Each QStash worker completes → reportAccountSyncComplete(jobId, userId, success)
 *   3. Frontend polls via handleJobStatus → reads Redis job
 *   4. Frontend Realtime → reads sync_jobs DB table
 */

import { logger } from "./logger.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "./privilegedDb.js";
import { getRedis } from "./redis.js";

const JOB_PREFIX = "sync-jobs:job:";
const USER_PREFIX = "sync-jobs:user:";
const PROGRESS_KEY = "sync-progress:";
const SUCCESS_KEY = "sync-success:";
const FAILED_KEY = "sync-failed:";

import { TTL_1_HOUR } from "./timing.js";

const TTL = TTL_1_HOUR;
const db = () => getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.syncProgress);

/**
 * Create a sync job for progress tracking.
 * No Redis queue — all accounts are fanned out to QStash individually.
 * Returns the job ID for passing to QStash workers.
 */
export async function createSyncJob(
	userId: string,
	totalAccounts: number,
): Promise<string> {
	const redis = getRedis();
	const jobId = `job_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

	// Store job metadata in Redis (same shape as legacy SyncJob for backward compat)
	const job = {
		id: jobId,
		userId,
		accountIds: [], // No longer stored — accounts are fanned out
		igAccountIds: [],
		status: "processing",
		createdAt: Date.now(),
		startedAt: Date.now(),
		progress: {
			current: 0,
			total: totalAccounts,
		},
	};

	await redis.set(`${JOB_PREFIX}${jobId}`, JSON.stringify(job), { ex: TTL });
	await redis.set(`${USER_PREFIX}${userId}`, jobId, { ex: TTL });

	// Initialize atomic counters
	await redis.set(`${PROGRESS_KEY}${jobId}`, 0, { ex: TTL });
	await redis.set(`${SUCCESS_KEY}${jobId}`, 0, { ex: TTL });
	await redis.set(`${FAILED_KEY}${jobId}`, 0, { ex: TTL });

	// Write to sync_jobs table for Realtime UI
	try {
		await db().from("sync_jobs").upsert(
			{
				id: jobId,
				user_id: userId,
				status: "processing",
				account_count: totalAccounts,
				current_progress: 0,
				success_count: 0,
				failed_count: 0,
				created_at: new Date().toISOString(),
				started_at: new Date().toISOString(),
			},
			{ onConflict: "id" },
		);
	} catch (err) {
		logger.warn("Failed to write sync job to DB", { error: String(err) });
	}

	logger.info("Sync job created", { jobId, userId, totalAccounts });
	return jobId;
}

/**
 * Report completion of a single account sync.
 * Called by /api/sync/threads-account and /api/sync/ig-account after each sync.
 * Uses Redis INCR for atomic counting — safe under concurrent QStash workers.
 * Deduplicates by accountId so QStash retries don't double-count.
 */
export async function reportAccountSyncComplete(
	jobId: string,
	userId: string,
	success: boolean,
	accountId?: string,
): Promise<void> {
	const redis = getRedis();

	// Dedup guard: prevent QStash retries from double-counting the same account.
	// SETNX is atomic — only the first call for this account succeeds.
	if (accountId) {
		const dedupKey = `sync-dedup:${jobId}:${accountId}`;
		const isNew = await redis.set(dedupKey, success ? "1" : "0", {
			ex: TTL,
			nx: true,
		});
		if (!isNew) return; // Already reported for this account
	}

	// Atomic increments — these never race
	const current = await redis.incr(`${PROGRESS_KEY}${jobId}`);
	if (success) {
		await redis.incr(`${SUCCESS_KEY}${jobId}`);
	} else {
		await redis.incr(`${FAILED_KEY}${jobId}`);
	}

	// Read counters + job metadata
	const [successCount, failedCount, jobStr] = await Promise.all([
		redis.get(`${SUCCESS_KEY}${jobId}`),
		redis.get(`${FAILED_KEY}${jobId}`),
		redis.get(`${JOB_PREFIX}${jobId}`),
	]);

	if (!jobStr) return;

	const job =
		typeof jobStr === "string"
			? JSON.parse(jobStr)
			: (jobStr as Record<string, unknown>);
	const total = job.progress?.total || 0;
	const isComplete = current >= total;

	const sc = Number(successCount) || 0;
	const fc = Number(failedCount) || 0;

	// Update Redis job for polling path (handleJobStatus reads this)
	job.progress = { current, total };
	job.results = {
		success: sc,
		failed: fc,
		suspended: [],
		reactivated: [],
	};
	if (isComplete) {
		job.status = "completed";
		job.completedAt = Date.now();
	} else {
		job.status = "processing";
	}
	await redis.set(`${JOB_PREFIX}${jobId}`, JSON.stringify(job), { ex: TTL });

	// Update DB for Realtime path
	try {
		const update: Record<string, unknown> = {
			current_progress: current,
			success_count: sc,
			failed_count: fc,
			status: isComplete ? "completed" : "processing",
		};
		if (isComplete) {
			update.completed_at = new Date().toISOString();
		}
		await db().from("sync_jobs").update(update).eq("id", jobId);
	} catch (err) {
		// Non-fatal — Redis is primary, DB is for Realtime only
		logger.warn("Failed to update sync progress in DB", {
			jobId,
			error: String(err),
		});
	}

	if (isComplete) {
		logger.info("Sync job complete", {
			jobId,
			userId,
			total,
			success: sc,
			failed: fc,
		});
	}
}
