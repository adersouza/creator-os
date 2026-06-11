/**
 * Shared types, schemas, and utilities for reply handlers.
 */

import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import {
	ENGAGEMENT_JOB_PREFIX,
	ENGAGEMENT_QUEUE_KEY,
	ENGAGEMENT_USER_JOB_PREFIX,
	type EngagementSyncJob,
	REPLY_JOB_PREFIX,
	REPLY_QUEUE_KEY,
	REPLY_USER_JOB_PREFIX,
	type ReplySyncJob,
} from "../../queueKeys.js";
import { getRedis } from "../../redis.js";
import { withRetry } from "../../retryUtils.js";
import { getSupabase } from "../../supabase.js";
import { z, zEnum } from "../../zodCompat.js";

// ============================================================================
// Zod Schemas
// ============================================================================

export const PostReplySchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	replyToId: z.string().min(1, "replyToId is required"),
	content: z
		.string()
		.min(1, "content is required")
		.max(500, "Content exceeds 500 character limit"),
	replyToUsername: z.string().optional(),
	media: z
		.object({
			type: zEnum(["image", "video"]),
			url: z.string().url(),
		})
		.optional(),
});

export const ManageReplySchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
	replyId: z.string().min(1, "replyId is required"),
	hide: z.boolean(),
});

// Unified send schema — matches frontend src/services/api/posts.ts::sendReply.
// Body is the descriptor attached to a conversation row in the new operator
// inbox; `kind` drives which Graph endpoint we hit.
export const SendReplySchema = z.object({
	platform: zEnum(["threads", "instagram"]),
	accountId: z.string().min(1, "accountId is required"),
	replyToId: z.string().min(1, "replyToId is required"),
	conversationId: z.string().optional(),
	context: z
		.object({
			conversationId: z.string().optional(),
			lastSeenAt: z.string().datetime().optional(),
			lastTurnId: z.string().optional(),
		})
		.optional(),
	content: z
		.string()
		.min(1, "content is required")
		.max(2200, "content too long"),
	kind: zEnum(["dm", "comment", "reply"]),
	replyToUsername: z.string().optional(),
});

export type SendReplyInput = typeof SendReplySchema["_output"];

// ============================================================================
// Types
// ============================================================================

export interface AccountRecord {
	id: string;
	username?: string | undefined;
	threads_user_id?: string | undefined;
	threads_access_token_encrypted?: string | undefined;
}

// ============================================================================
// Redis Queue Utilities for Reply Sync
// ============================================================================

export async function getUserCurrentReplyJob(
	userId: string,
): Promise<ReplySyncJob | null> {
	const redis = getRedis();
	if (!redis) return null;

	const jobId = await redis.get(`${REPLY_USER_JOB_PREFIX}${userId}`);
	if (!jobId) return null;

	const data = await redis.get(`${REPLY_JOB_PREFIX}${jobId}`);
	if (!data) return null;

	return typeof data === "string" ? JSON.parse(data) : (data as ReplySyncJob);
}

export async function queueReplySyncJob(
	userId: string,
	accountIds: string[],
): Promise<ReplySyncJob> {
	const redis = getRedis();
	if (!redis) throw new Error("Redis not configured");

	const jobId = `reply_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

	const job: ReplySyncJob = {
		id: jobId,
		userId,
		accountIds,
		status: "queued",
		createdAt: Date.now(),
		progress: {
			current: 0,
			total: accountIds.length,
		},
	};

	await redis.set(`${REPLY_JOB_PREFIX}${jobId}`, JSON.stringify(job), {
		ex: 3600,
	});
	await redis.set(`${REPLY_USER_JOB_PREFIX}${userId}`, jobId, { ex: 3600 });
	await redis.lpush(REPLY_QUEUE_KEY, jobId);
	// Cap queue length to prevent unbounded growth under backpressure
	await redis.ltrim(REPLY_QUEUE_KEY, 0, 9999);
	await redis.expire(REPLY_QUEUE_KEY, 86400);

	return job;
}

export async function getUserCurrentEngagementJob(
	userId: string,
	type: string,
): Promise<EngagementSyncJob | null> {
	const redis = getRedis();
	if (!redis) return null;

	const jobId = await redis.get(
		`${ENGAGEMENT_USER_JOB_PREFIX}${userId}:${type}`,
	);
	if (!jobId) return null;

	const data = await redis.get(`${ENGAGEMENT_JOB_PREFIX}${jobId}`);
	if (!data) return null;

	return typeof data === "string"
		? JSON.parse(data)
		: (data as EngagementSyncJob);
}

export async function queueEngagementSyncJob(
	userId: string,
	type: "reply-metrics" | "mentions",
	extra: { accountIds?: string[] | undefined } = {},
): Promise<EngagementSyncJob> {
	const redis = getRedis();
	if (!redis) throw new Error("Redis not configured");

	const jobId = `eng_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

	const job: EngagementSyncJob & { accountIds?: string[] | undefined } = {
		id: jobId,
		userId,
		type,
		status: "queued",
		createdAt: Date.now(),
		...extra,
	};

	await redis.set(`${ENGAGEMENT_JOB_PREFIX}${jobId}`, JSON.stringify(job), {
		ex: 3600,
	});
	await redis.set(`${ENGAGEMENT_USER_JOB_PREFIX}${userId}:${type}`, jobId, {
		ex: 3600,
	});
	await redis.lpush(ENGAGEMENT_QUEUE_KEY, jobId);
	// Cap queue length to prevent unbounded growth under backpressure
	await redis.ltrim(ENGAGEMENT_QUEUE_KEY, 0, 9999);

	return job;
}

// ============================================================================
// Account Reply Processing (used by sync handlers)
// ============================================================================

// Concurrency limit for parallel account processing (3 accounts at a time)
export const ACCOUNT_CONCURRENCY = 3;

// Process a single account's replies - extracted for parallel processing
export async function processAccountReplies(account: AccountRecord): Promise<{
	accountId: string;
	success: boolean;
	repliesFound: number;
	postsProcessed: number;
	error?: string | undefined;
}> {
	if (!account.threads_access_token_encrypted || !account.threads_user_id) {
		return {
			accountId: account.id,
			success: true,
			repliesFound: 0,
			postsProcessed: 0,
		};
	}

	let totalReplies = 0;
	let postsProcessed = 0;

	try {
		const token = decrypt(account.threads_access_token_encrypted);

		// OPTIMIZATION: Only fetch posts that actually have replies (replies_count > 0)
		const { data: posts } = await getSupabase()
			.from("posts")
			.select("*")
			.eq("account_id", account.id)
			.eq("status", "published")
			.not("threads_post_id", "is", null)
			.gt("replies_count", 0)
			.order("replies_count", { ascending: false })
			.limit(50);

		// Process posts in parallel batches of 5
		const BATCH_SIZE = 5;
		interface PostRecord {
			id: string;
			threads_post_id?: string | undefined;
		}
		const postsArray = (posts || []) as PostRecord[];

		for (let i = 0; i < postsArray.length; i += BATCH_SIZE) {
			const batch = postsArray.slice(i, i + BATCH_SIZE);

			const batchResults = await Promise.all(
				batch.map(async (post: PostRecord) => {
					if (!post.threads_post_id) return { replies: 0 };

					try {
						const repliesUrl = `https://graph.threads.net/v1.0/${post.threads_post_id}/replies?fields=id,text,timestamp,username,like_count,reply_count,owner{profile_picture_url}`;
						const repliesResponse = await withRetry(
							() =>
								fetch(repliesUrl, {
									headers: { Authorization: `Bearer ${token}` },
									signal: AbortSignal.timeout(10000),
								}),
							{ label: `syncReplies:${post.threads_post_id}` },
						);
						const repliesData = await repliesResponse.json();

						if (repliesData.error) return { replies: 0 };

						interface ThreadsReply {
							id: string;
							username?: string | undefined;
							text?: string | undefined;
							like_count?: number | undefined;
							reply_count?: number | undefined;
							owner?: { profile_picture_url?: string | undefined } | undefined;
						}
						// Collect all replies for batch upsert
						const repliesToInsert = (repliesData.data || ([] as ThreadsReply[]))
							.filter(
								(reply: ThreadsReply) => reply.username !== account.username,
							)
							.map((reply: ThreadsReply) => ({
								post_id: post.id,
								threads_reply_id: reply.id,
								threads_user_id: reply.id.split("_")[0] || "",
								username: reply.username,
								display_name: reply.username,
								avatar_url: reply.owner?.profile_picture_url || null,
								content: reply.text || "",
								likes_count: reply.like_count || 0,
								replies_count: reply.reply_count || 0,
							}));

						if (repliesToInsert.length > 0) {
							const { error: upsertError } = await getSupabase()
								.from("post_replies")
								// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert type workaround
								.upsert(repliesToInsert as any, {
									onConflict: "threads_reply_id",
									ignoreDuplicates: true,
								});

							if (!upsertError) {
								return { replies: repliesToInsert.length };
							}
						}
						return { replies: 0 };
					} catch (e) {
						logger.error("Error processing post", {
							postId: post.id,
							error: String(e),
						});
						return { replies: 0 };
					}
				}),
			);

			postsProcessed += batch.length;
			totalReplies += batchResults.reduce((sum, r) => sum + r.replies, 0);

			// Small delay between batches to avoid rate limiting
			if (i + BATCH_SIZE < postsArray.length) {
				await new Promise((resolve) => setTimeout(resolve, 50));
			}
		}

		return {
			accountId: account.id,
			success: true,
			repliesFound: totalReplies,
			postsProcessed,
		};
	} catch (e: unknown) {
		const message = e instanceof Error ? e.message : String(e);
		logger.error("Error processing account", {
			accountId: account.id,
			error: message,
		});
		return {
			accountId: account.id,
			success: false,
			repliesFound: totalReplies,
			postsProcessed,
			error: message,
		};
	}
}
