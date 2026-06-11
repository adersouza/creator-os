/**
 * Upstash Redis client for job queue
 *
 * Required environment variables:
 * - UPSTASH_REDIS_REST_URL
 * - UPSTASH_REDIS_REST_TOKEN
 */

import { Redis } from "@upstash/redis";
import { logger } from "./logger.js";

let redis: Redis | null = null;

export function getRedis(): Redis {
	if (!redis) {
		const url = process.env.UPSTASH_REDIS_REST_URL;
		const token = process.env.UPSTASH_REDIS_REST_TOKEN;

		if (!url || !token) {
			throw new Error(
				"Missing UPSTASH_REDIS_REST_URL or UPSTASH_REDIS_REST_TOKEN environment variables",
			);
		}

		redis = new Redis({ url, token });
	}
	return redis;
}

// Job types
export interface SyncJob {
	id: string;
	userId: string;
	accountIds: string[];
	igAccountIds?: string[] | undefined;
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
        		suspended: string[];
        		reactivated: string[];
        	} | undefined;
	error?: string | undefined;
}

// Redis key prefixes for sync jobs (shared with syncProgress.ts)
const JOB_PREFIX = "sync-jobs:job:";
const USER_JOB_PREFIX = "sync-jobs:user:";

function isValidSyncJob(obj: unknown): obj is SyncJob {
	const o = obj as Record<string, unknown>;
	return (
		!!o &&
		typeof o.id === "string" &&
		typeof o.userId === "string" &&
		Array.isArray(o.accountIds) &&
		["queued", "processing", "completed", "failed"].includes(
			o.status as string,
		) &&
		typeof o.createdAt === "number"
	);
}

// Get job status
export async function getJobStatus(jobId: string): Promise<SyncJob | null> {
	const redis = getRedis();
	const data = await redis.get(`${JOB_PREFIX}${jobId}`);
	if (!data) return null;
	try {
		const parsed = typeof data === "string" ? JSON.parse(data) : data;
		if (!isValidSyncJob(parsed)) {
			logger.warn("Invalid job structure in Redis", { jobId });
			return null;
		}
		return parsed;
	} catch {
		logger.warn("Corrupted job data in Redis", { jobId });
		return null;
	}
}

// Get user's current job
export async function getUserCurrentJob(
	userId: string,
): Promise<SyncJob | null> {
	const redis = getRedis();
	const jobId = await redis.get(`${USER_JOB_PREFIX}${userId}`);
	if (!jobId) return null;
	return getJobStatus(jobId as string);
}
