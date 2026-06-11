// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Reply Sync Phase — Fetch and store post replies/conversations.
 * Extracted from sync-orchestrator.ts.
 *
 * fetchRepliesForPost() — fetch top-level replies for a single post
 * processAccountReplies() — process all recent posts for an account
 * processReplySyncQueue() — process the reply sync Redis queue
 */

import type { PostgrestError } from "@supabase/supabase-js";
import { logger, serializeError } from "../logger.js";
import { withRetry } from "../retryUtils.js";
import { sanitizeHtml } from "../sanitize.js";

import {
	DELAY_BETWEEN_ACCOUNTS,
	getJob,
	getQueueLen,
	hasTimeBudget,
	POSTS_PER_ACCOUNT_LIMIT,
	popFromQueue,
	REPLY_JOB_PREFIX,
	REPLY_QUEUE_KEY,
	type ReplyAccountData,
	type ReplyRecord,
	type ReplySyncJob,
	type ThreadsReply,
	updateJob,
	updateSyncJobsTable,
} from "./shared.js";

// ============================================================================
// PHASE 2: Reply Sync - Fetch replies for a post
// ============================================================================

export async function fetchRepliesForPost(
	_postId: string,
	threadsPostId: string,
	accessToken: string,
): Promise<{ replies: ThreadsReply[]; error?: string | undefined }> {
	try {
		const url = `https://graph.threads.net/v1.0/${threadsPostId}/replies?fields=id,text,username,timestamp,like_count,reply_count,replied_to`;
		const response = await withRetry(() =>
			fetch(url, {
				headers: { Authorization: `Bearer ${accessToken}` },
				signal: AbortSignal.timeout(10000),
			}),
		);
		const data = await response.json();
		if (data.error) return { replies: [], error: data.error.message };
		return { replies: data.data || [] };
	} catch (error: unknown) {
		return {
			replies: [],
			error: serializeError(error),
		};
	}
}

export async function processAccountReplies(
	account: ReplyAccountData,
	userId: string,
): Promise<{
	success: boolean;
	postsProcessed: number;
	repliesFound: number;
	error?: string | undefined;
}> {
	const { decrypt } = await import("../encryption.js");
	const { getSupabase } = await import("../supabase.js");

	try {
		// Webhook-first: skip polling if this account receives replies via webhook
		const { data: webhookInfo } = (await getSupabase()
			.from("accounts")
			.select("webhook_replies_active, last_webhook_reply_at")
			.eq("id", account.id)
			.maybeSingle()) as {
			data: {
				webhook_replies_active?: boolean | undefined;
				last_webhook_reply_at?: string | undefined;
			} | null;
		};

		if (
			webhookInfo?.webhook_replies_active &&
			webhookInfo.last_webhook_reply_at
		) {
			const lastWebhook = new Date(webhookInfo.last_webhook_reply_at).getTime();
			const oneDayAgo = Date.now() - 24 * 60 * 60 * 1000;
			if (lastWebhook > oneDayAgo) {
				logger.info("Skipping reply polling (webhook active)", {
					accountId: account.id,
				});
				return { success: true, postsProcessed: 0, repliesFound: 0 };
			}
			await getSupabase()
				.from("accounts")
				.update({ webhook_replies_active: false })
				.eq("id", account.id);
		}

		const accessToken = decrypt(account.threads_access_token_encrypted);

		const sevenDaysAgo = new Date(
			Date.now() - 7 * 24 * 60 * 60 * 1000,
		).toISOString();
		const { data: posts, error: postsError } = (await getSupabase()
			.from("posts")
			.select("id, threads_post_id, content")
			.eq("account_id", account.id)
			.eq("user_id", userId)
			.eq("status", "published")
			.not("threads_post_id", "is", null)
			.gte("created_at", sevenDaysAgo)
			.order("created_at", { ascending: false })
			.limit(POSTS_PER_ACCOUNT_LIMIT)) as {
			data: { id: string; threads_post_id: string; content: string }[] | null;
			error: PostgrestError | null;
		};

		if (postsError || !posts) {
			return {
				success: false,
				postsProcessed: 0,
				repliesFound: 0,
				error: postsError?.message || "Failed to fetch posts",
			};
		}

		let totalReplies = 0;
		const postsProcessed = posts.length;

		const REPLY_BATCH_SIZE = 5;
		const postsWithIds = posts.filter((p) => p.threads_post_id);

		for (let i = 0; i < postsWithIds.length; i += REPLY_BATCH_SIZE) {
			const batch = postsWithIds.slice(i, i + REPLY_BATCH_SIZE);
			const batchResults = await Promise.allSettled(
				batch.map((post) =>
					fetchRepliesForPost(post.id, post.threads_post_id, accessToken),
				),
			);

			const allReplyRecords: ReplyRecord[] = [];
			for (let j = 0; j < batchResults.length; j++) {
				const result = batchResults[j];
				if (result!.status === "rejected" || result!.value.error) {
					logger.warn("Error fetching replies for post", {
						postId: batch[j]!.id,
						error:
							result!.status === "rejected"
								? String(result!.reason)
								: result!.value.error,
					});
					continue;
				}
				const { replies } = result!.value;
				if (replies.length > 0) {
					allReplyRecords.push(
						...replies.map((reply: ThreadsReply) => ({
							post_id: batch[j]!.id,
							threads_reply_id: reply.id,
							threads_user_id: reply.id,
							username: reply.username || "unknown",
							content: sanitizeHtml(reply.text || ""),
							created_at: reply.timestamp
								? new Date(reply.timestamp).toISOString()
								: new Date().toISOString(),
							likes_count: reply.like_count || 0,
							replies_count: reply.reply_count || 0,
						})),
					);
				}
			}

			if (allReplyRecords.length > 0) {
				const { error: upsertError } = await getSupabase()
					.from("post_replies")
					.upsert(allReplyRecords, { onConflict: "threads_reply_id" });

				if (upsertError) {
					logger.error("Error upserting reply batch", {
						error: upsertError.message,
						count: allReplyRecords.length,
					});
				} else {
					totalReplies += allReplyRecords.length;
				}
			}

			// Small delay between batches to avoid rate limiting
			if (i + REPLY_BATCH_SIZE < postsWithIds.length) {
				await new Promise((resolve) => setTimeout(resolve, 200));
			}
		}

		return { success: true, postsProcessed, repliesFound: totalReplies };
	} catch (error: unknown) {
		return {
			success: false,
			postsProcessed: 0,
			repliesFound: 0,
			error: serializeError(error),
		};
	}
}

// ============================================================================
// PHASE 2: Reply Sync - Process Queue
// ============================================================================

export async function processReplySyncQueue(): Promise<number> {
	const { getSupabase } = await import("../supabase.js");

	if (!hasTimeBudget()) {
		logger.debug("[orchestrator] No time budget for reply sync queue");
		return 0;
	}

	const queueLength = await getQueueLen(REPLY_QUEUE_KEY);
	logger.debug("[orchestrator] Reply sync queue check", { queueLength });

	if (queueLength === 0) return 0;

	const jobId = await popFromQueue(REPLY_QUEUE_KEY);
	if (!jobId) return 0;

	const job = await getJob<ReplySyncJob>(REPLY_JOB_PREFIX, jobId);
	if (!job) return 0;

	logger.debug("[orchestrator] Processing reply sync job", {
		jobId: job.id,
		accountCount: job.accountIds.length,
	});

	await updateJob<ReplySyncJob>(REPLY_JOB_PREFIX, job.id, {
		status: "processing",
		startedAt: Date.now(),
	});
	await updateSyncJobsTable(job.id, job.userId, {
		job_type: "replies",
		status: "processing",
		started_at: new Date().toISOString(),
	});

	const { data: accounts, error: accountsError } = await getSupabase()
		.from("accounts")
		.select("id, username, threads_user_id, threads_access_token_encrypted")
		.in("id", job.accountIds)
		.eq("user_id", job.userId)
		.not("threads_access_token_encrypted", "is", null)
		.or("needs_reauth.is.null,needs_reauth.eq.false")
		.or("is_active.is.null,is_active.eq.true");

	if (accountsError || !accounts || accounts.length === 0) {
		await updateJob<ReplySyncJob>(REPLY_JOB_PREFIX, job.id, {
			status: "failed",
			error: "No valid accounts found",
			completedAt: Date.now(),
		});
		await updateSyncJobsTable(job.id, job.userId, {
			job_type: "replies",
			status: "failed",
			error_message: "No valid accounts found",
			completed_at: new Date().toISOString(),
		});
		return 0;
	}

	const results = { success: 0, failed: 0, postsProcessed: 0, repliesFound: 0 };

	for (let i = 0; i < accounts.length; i++) {
		if (!hasTimeBudget()) {
			logger.warn("[orchestrator] Time limit reached during reply sync", {
				processed: i,
				total: accounts.length,
			});
			break;
		}

		const account = accounts[i] as ReplyAccountData;

		await updateJob<ReplySyncJob>(REPLY_JOB_PREFIX, job.id, {
			progress: {
				current: i + 1,
				total: accounts.length,
				currentAccount: account.username,
			},
		});
		await updateSyncJobsTable(job.id, job.userId, {
			current_progress: i + 1,
			current_account: account.username,
		});

		const result = await processAccountReplies(account, job.userId);
		if (result.success) {
			results.success++;
			results.postsProcessed += result.postsProcessed;
			results.repliesFound += result.repliesFound;
		} else {
			results.failed++;
			logger.warn("Reply sync account failed", {
				username: account.username,
				error: result.error,
			});
		}

		if (i < accounts.length - 1) {
			await new Promise((resolve) =>
				setTimeout(resolve, DELAY_BETWEEN_ACCOUNTS),
			);
		}
	}

	await updateJob<ReplySyncJob>(REPLY_JOB_PREFIX, job.id, {
		status: "completed",
		completedAt: Date.now(),
		results,
	});
	await updateSyncJobsTable(job.id, job.userId, {
		job_type: "replies",
		status: "completed",
		completed_at: new Date().toISOString(),
		success_count: results.success,
		failed_count: results.failed,
		posts_processed: results.postsProcessed,
		replies_found: results.repliesFound,
		current_account: null,
	});

	logger.info("[orchestrator] Reply sync job completed", {
		jobId: job.id,
		successAccounts: results.success,
		repliesFound: results.repliesFound,
	});
	return job.accountIds.length;
}
