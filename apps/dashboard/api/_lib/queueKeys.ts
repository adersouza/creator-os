/**
 * Centralized Redis queue key definitions + shared job types.
 * Prevents key string duplication across auto-post.ts, replies.ts, and sync-orchestrator.ts.
 */

// ── Engagement sync queue ────────────────────────────────────────────────────
export const ENGAGEMENT_QUEUE_KEY = "engagement-sync-jobs:queue";
export const ENGAGEMENT_JOB_PREFIX = "engagement-sync-jobs:job:";
export const ENGAGEMENT_USER_JOB_PREFIX = "engagement-sync-jobs:user:";

// ── Reply sync queue ─────────────────────────────────────────────────────────
export const REPLY_QUEUE_KEY = "reply-sync-jobs:queue";
export const REPLY_JOB_PREFIX = "reply-sync-jobs:job:";
export const REPLY_USER_JOB_PREFIX = "reply-sync-jobs:user:";

// ── Shared job types ─────────────────────────────────────────────────────────
export interface EngagementSyncJob {
	id: string;
	userId: string;
	type: "auto-post-engagement" | "reply-metrics" | "mentions";
	workspaceId?: string | undefined;
	accountIds?: string[] | undefined;
	status: "queued" | "processing" | "completed" | "failed";
	createdAt: number;
	startedAt?: number | undefined;
	completedAt?: number | undefined;
	progress?: { current: number; total: number } | undefined;
	results?: { updated: number; failed: number } | undefined;
	error?: string | undefined;
}

export interface ReplySyncJob {
	id: string;
	userId: string;
	accountIds: string[];
	status: "queued" | "processing" | "completed" | "failed";
	createdAt: number;
	startedAt?: number | undefined;
	completedAt?: number | undefined;
	progress?: {
        		current: number;
        		total: number;
        		currentAccount?: string | undefined;
        	} | undefined;
	results?: {
        		success: number;
        		failed: number;
        		postsProcessed: number;
        		repliesFound: number;
        	} | undefined;
	error?: string | undefined;
}
