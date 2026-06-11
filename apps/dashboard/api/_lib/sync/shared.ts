/**
 * Shared configuration, types, and utility functions for sync phases.
 * Extracted from sync-orchestrator.ts to keep the orchestrator thin.
 */

import { logger, serializeError } from "../logger.js";
import { withRetry } from "../retryUtils.js";

// ============================================================================
// Re-export queue key types from shared module
// ============================================================================

export {
	ENGAGEMENT_JOB_PREFIX,
	ENGAGEMENT_QUEUE_KEY,
	type EngagementSyncJob,
	REPLY_JOB_PREFIX,
	REPLY_QUEUE_KEY,
	type ReplySyncJob,
} from "../queueKeys.js";

// ============================================================================
// Configuration
// ============================================================================

// sync-orchestrator has a 180s Vercel budget. Keep a small response/cleanup
// reserve while letting low-priority phases like reply-chain pulse make
// meaningful progress instead of self-capping at the old 60s runtime.
export const MAX_EXECUTION_TIME = Number.parseInt(
	process.env.SYNC_ORCHESTRATOR_BUDGET_MS ?? "170000",
	10,
);
export const DELAY_BETWEEN_ACCOUNTS = 100; // 100ms between batches
export const CONCURRENCY_LIMIT = parseInt(
	process.env.SYNC_CONCURRENCY ?? "3",
	10,
);
// IG accounts above this limit are fanned out to QStash rather than processed inline.
// Each QStash job gets its own Vercel 60s budget; inline processing at ~400ms/account
// means >20 IG accounts risks hitting MAX_EXECUTION_TIME.
export const IG_DIRECT_LIMIT = parseInt(
	process.env.IG_DIRECT_LIMIT || "20",
	10,
);
export const POSTS_PER_ACCOUNT_LIMIT = 50;
export const ENGAGEMENT_DELAY_BETWEEN_ITEMS = 100;
export const COMPETITOR_BATCH_SIZE = 5;
export const COMPETITOR_BATCH_DELAY_MS = 500;
export const ENGAGEMENT_WEIGHTS = {
	like: 1,
	reply: 3,
	repost: 2,
	view: 0.01,
} as const;

// ============================================================================
// Analytics Sync Queue Keys & Types
// ============================================================================

export interface SyncJob {
	id: string;
	userId: string;
	accountIds: string[];
	igAccountIds?: string[] | undefined;
	ig_account_ids?: string[] | undefined;
	status: "queued" | "processing" | "completed" | "failed";
	createdAt: number;
	startedAt?: number | undefined;
	completedAt?: number | undefined;
	progress?:
		| {
				current: number;
				total: number;
				currentAccount?: string | undefined;
		  }
		| undefined;
	results?:
		| {
				success: number;
				failed: number;
				suspended: string[];
				needsReauth?: string[] | undefined;
				reactivated: string[];
		  }
		| undefined;
	error?: string | undefined;
}

export const SYNC_QUEUE_KEY = "sync-jobs:queue";
export const SYNC_JOB_PREFIX = "sync-jobs:job:";
export const SYNC_USER_JOB_PREFIX = "sync-jobs:user:";

// ============================================================================
// Competitor Sync Queue Keys & Types
// ============================================================================

export interface CompetitorSyncJob {
	id: string;
	userId: string;
	competitorIds: string[];
	status: "queued" | "processing" | "completed" | "failed";
	createdAt: number;
	startedAt?: number | undefined;
	completedAt?: number | undefined;
	progress?:
		| { current: number; total: number; currentName?: string | undefined }
		| undefined;
	results?: { success: number; failed: number } | undefined;
	error?: string | undefined;
}

export const COMPETITOR_QUEUE_KEY = "competitor-sync-jobs:queue";
export const COMPETITOR_JOB_PREFIX = "competitor-sync-jobs:job:";

// ============================================================================
// Account Cache Types
// ============================================================================

export interface AccountData {
	id: string;
	user_id: string;
	username?: string | undefined;
	threads_user_id?: string | undefined;
	threads_access_token_encrypted?: string | undefined;
	status?: string | undefined;
	is_active?: boolean | undefined;
	followers_count?: number | undefined;
	last_synced_at?: string | undefined;
}

import { TTL_1_HOUR } from "../timing.js";
export const ACCOUNT_CACHE_PREFIX = "account-cache:";
export const ACCOUNT_CACHE_TTL = TTL_1_HOUR;

export interface ReplyAccountData {
	id: string;
	username: string;
	threads_user_id: string;
	threads_access_token_encrypted: string;
}

export interface SyncResult {
	accountId: string;
	username?: string | undefined;
	success: boolean;
	suspended?: boolean | undefined;
	needsReauth?: boolean | undefined;
	reactivated?: boolean | undefined;
	skipped?: boolean | undefined;
	error?: string | undefined;
}

// ============================================================================
// Additional Row Types (typed API + DB shapes)
// ============================================================================

export interface SyncJobUpdate {
	status?: string;
	job_type?: string;
	account_count?: number;
	started_at?: string;
	completed_at?: string | null;
	current_progress?: number;
	current_account?: string | null;
	success_count?: number;
	failed_count?: number;
	suspended_accounts?: string[];
	reactivated_accounts?: string[];
	error_message?: string | null;
	posts_processed?: number;
	replies_found?: number;
	engagement_updated?: number;
	competitors_synced?: number;
}

export interface ThreadsInsightMetric {
	name: string;
	total_value?: { value: number } | undefined;
	values?: { value: number }[] | undefined;
}

export interface AccountUpdate {
	username?: string;
	avatar_url?: string | null;
	bio?: string | null;
	last_synced_at?: string;
	updated_at?: string;
	status?: string;
	is_active?: boolean;
	followers_count?: number;
}

export interface IgAccountRow {
	id: string;
	user_id: string;
	username: string;
	instagram_user_id: string;
	instagram_access_token_encrypted: string;
	login_type?: string | undefined;
	follower_count?: number | undefined;
	last_milestone_celebrated?: string | null | undefined;
	last_synced_at?: string | null | undefined;
	is_active?: boolean | undefined;
}

export interface StaleJobRow {
	id: string;
}

export interface StaleQueuedJobRow {
	id: string;
	job_type: string;
}

export interface ThreadsReply {
	id: string;
	text?: string | undefined;
	username?: string | undefined;
	timestamp?: string | undefined;
	like_count?: number | undefined;
	reply_count?: number | undefined;
}

export interface ReplyRecord {
	post_id: string;
	threads_reply_id: string;
	threads_user_id: string;
	username: string;
	content: string;
	created_at: string;
	likes_count: number;
	replies_count: number;
}

export interface AutoPostQueueRow {
	id: string;
	threads_post_id: string | null;
	account_id: string;
	accounts: { threads_access_token_encrypted: string | null } | null;
}

export interface SentReplyRow {
	id: string;
	threads_reply_id: string | null;
	account_id: string;
}

export interface ReplyMetricsAccountRow {
	threads_access_token_encrypted: string | null;
}

export interface ThreadsReplyData {
	like_count?: number | undefined;
	reply_count?: number | undefined;
	error?: { message: string } | undefined;
}

export interface MentionsAccountRow {
	threads_user_id: string | null;
	threads_access_token_encrypted: string | null;
	needs_reauth: boolean | null;
	is_active: boolean | null;
}

export interface AccountTokenRow {
	id: string;
	threads_access_token_encrypted: string;
}

export interface CompetitorPost {
	id: string;
	text?: string | undefined;
	media_url?: string | undefined;
	media_type?: string | undefined;
	permalink?: string | undefined;
	timestamp?: string | undefined;
	like_count?: number | undefined;
	reply_count?: number | undefined;
	repost_count?: number | undefined;
	views?: number | undefined;
	username?: string | undefined;
}

export interface CompetitorRow {
	id: string;
	username: string;
	follower_count?: number | undefined;
}

// ============================================================================
// Shared time budget tracker (set once at orchestrator start)
// ============================================================================

let orchestratorStartTime = Date.now();

export function setOrchestratorStartTime(time: number): void {
	orchestratorStartTime = time;
}

export function getOrchestratorStartTime(): number {
	return orchestratorStartTime;
}

export function hasTimeBudget(reserveMs: number = 5000): boolean {
	return Date.now() - orchestratorStartTime < MAX_EXECUTION_TIME - reserveMs;
}

// ============================================================================
// Shared Redis Helpers
// ============================================================================

export async function getJob<T>(
	prefix: string,
	jobId: string,
): Promise<T | null> {
	const { getRedis } = await import("../redis.js");
	const redis = getRedis();
	const data = await redis.get(`${prefix}${jobId}`);
	if (!data) return null;
	return typeof data === "string" ? JSON.parse(data) : (data as T);
}

export async function updateJob<T>(
	prefix: string,
	jobId: string,
	updates: Partial<T>,
): Promise<void> {
	const { getRedis } = await import("../redis.js");
	const redis = getRedis();
	const job = await getJob<T>(prefix, jobId);
	if (!job) return;
	const updated = { ...job, ...updates };
	await redis.set(`${prefix}${jobId}`, JSON.stringify(updated), { ex: 3600 });
}

export async function popFromQueue(queueKey: string): Promise<string | null> {
	const { getRedis } = await import("../redis.js");
	const redis = getRedis();
	const jobId = await redis.rpop(queueKey);
	return jobId as string | null;
}

export async function getQueueLen(queueKey: string): Promise<number> {
	const { getRedis } = await import("../redis.js");
	const redis = getRedis();
	return redis.llen(queueKey);
}

export async function queueSyncJob(
	userId: string,
	accountIds: string[],
	igAccountIds: string[] = [],
): Promise<SyncJob> {
	const { getRedis } = await import("../redis.js");
	const redis = getRedis();
	const jobId = `job_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

	const job: SyncJob = {
		id: jobId,
		userId,
		accountIds,
		igAccountIds,
		status: "queued",
		createdAt: Date.now(),
		progress: { current: 0, total: accountIds.length + igAccountIds.length },
	};

	await redis.set(`${SYNC_JOB_PREFIX}${jobId}`, JSON.stringify(job), {
		ex: 3600,
	});
	await redis.set(`${SYNC_USER_JOB_PREFIX}${userId}`, jobId, { ex: 3600 });
	await redis.lpush(SYNC_QUEUE_KEY, jobId);
	// Rolling TTL prevents unbounded list growth if workers crash mid-dequeue
	await redis.expire(SYNC_QUEUE_KEY, 7200).catch(() => {});

	logger.info("Job queued", { jobId, userId, accountCount: accountIds.length });
	return job;
}

export async function updateSyncJobsTable(
	jobId: string,
	userId: string,
	updates: SyncJobUpdate,
): Promise<void> {
	try {
			const { getSupabase } = await import("../supabase.js");
			await getSupabase()
				.from("sync_jobs")
				.upsert({ id: jobId, user_id: userId, ...updates }, {
					onConflict: "id",
				});
	} catch (error) {
		logger.error("Failed to update sync_jobs table", {
			error: serializeError(error),
		});
	}
}

// ============================================================================
// Account Cache (Redis-based to reduce DB egress)
// ============================================================================

export async function getCachedAccount(
	accountId: string,
): Promise<AccountData | null> {
	try {
		const { getRedis } = await import("../redis.js");
		const redis = getRedis();
		const cached = await redis.get(`${ACCOUNT_CACHE_PREFIX}${accountId}`);
		if (cached) {
			return typeof cached === "string"
				? JSON.parse(cached)
				: (cached as AccountData);
		}
		return null;
	} catch (err) {
		logger.debug("Redis cache miss for account", {
			accountId,
			error: String(err),
		});
		return null;
	}
}

export async function setCachedAccount(account: AccountData): Promise<void> {
	try {
		const { getRedis } = await import("../redis.js");
		const redis = getRedis();
		await redis.set(
			`${ACCOUNT_CACHE_PREFIX}${account.id}`,
			JSON.stringify(account),
			{ ex: ACCOUNT_CACHE_TTL },
		);
	} catch (err) {
		logger.debug("Redis cache write failed for account", {
			accountId: account.id,
			error: String(err),
		});
	}
}

export async function invalidateAccountCache(accountId: string): Promise<void> {
	try {
		const { getRedis } = await import("../redis.js");
		const redis = getRedis();
		await redis.del(`${ACCOUNT_CACHE_PREFIX}${accountId}`);
	} catch (err) {
		logger.debug("Redis cache invalidation failed", {
			accountId,
			error: String(err),
		});
	}
}

// ============================================================================
// Fetch with timeout
// ============================================================================

export async function fetchWithTimeout(
	url: string,
	options: RequestInit = {},
	timeoutMs: number = 10000,
	context?: string,
): Promise<Response> {
	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), timeoutMs);
	try {
		const response = await withRetry(() =>
			fetch(url, {
				...options,
				signal: controller.signal,
			}),
		);
		if (response.status === 429) {
			const retryAfter = response.headers.get("retry-after") || "unknown";
			logger.warn("Rate limited (429)", {
				context,
				retryAfter,
				url: url.split("?")[0],
			});
		}
		return response;
	} finally {
		clearTimeout(timeout);
	}
}
