/**
 * Engagement Sync Phase — Auto-post engagement, reply metrics, and mentions.
 * Extracted from sync-orchestrator.ts.
 *
 * processAutoPostEngagement() — fetch 24h metrics for auto-posted content
 * processReplyMetrics() — update metrics on sent replies
 * processMentions() — sync mentions for accounts
 * processEngagementJob() — dispatch to the right sub-processor
 * processEngagementSyncQueue() — process the engagement sync Redis queue
 */

import type { PostgrestError } from "@supabase/supabase-js";
import { logger } from "../logger.js";
import { withRetry } from "../retryUtils.js";
import { sanitizeHtml } from "../sanitize.js";

import {
	type AutoPostQueueRow,
	ENGAGEMENT_DELAY_BETWEEN_ITEMS,
	ENGAGEMENT_JOB_PREFIX,
	ENGAGEMENT_QUEUE_KEY,
	type EngagementSyncJob,
	hasTimeBudget,
	type MentionsAccountRow,
	type ReplyMetricsAccountRow,
	type SentReplyRow,
	type ThreadsReplyData,
	updateSyncJobsTable,
} from "./shared.js";

// ============================================================================
// PHASE 3: Engagement Sync - Auto-Post Engagement
// ============================================================================

export async function processAutoPostEngagement(
	job: EngagementSyncJob,
): Promise<{ updated: number; failed: number }> {
	const { decrypt } = await import("../encryption.js");
	const { getSupabaseAny } = await import("../supabase.js");

	const results = { updated: 0, failed: 0 };

	if (!job.workspaceId) return results;

	const twentyFourHoursAgo = new Date(
		Date.now() - 24 * 60 * 60 * 1000,
	).toISOString();

	const { data: posts, error } = (await getSupabaseAny()
		.from("auto_post_queue")
		.select(
			`id, threads_post_id, account_id, accounts!auto_post_queue_account_id_fkey(threads_access_token_encrypted)`,
		)
		.eq("workspace_id", job.workspaceId)
		.eq("status", "published")
		.not("threads_post_id", "is", null)
		.is("engagement_fetched_at", null)
		.lt("posted_at", twentyFourHoursAgo)
		.limit(50)) as {
		data: AutoPostQueueRow[] | null;
		error: PostgrestError | null;
	};

	if (error || !posts) return results;

	for (const post of posts) {
		if (!hasTimeBudget()) {
			logger.info(
				"[orchestrator] Time budget exceeded in auto-post engagement",
				{ updated: results.updated },
			);
			break;
		}
		const account = post.accounts as AutoPostQueueRow["accounts"];
		if (!account?.threads_access_token_encrypted || !post.threads_post_id)
			continue;

		try {
			let token: string;
			try {
				token = decrypt(account.threads_access_token_encrypted);
			} catch (decryptErr) {
				logger.warn("Token decryption failed, skipping post", {
					postId: post.id,
					error: String(decryptErr),
				});
				results.failed++;
				continue;
			}
			const metricsUrl = `https://graph.threads.net/v1.0/${post.threads_post_id}/insights?metric=views,likes,replies,reposts,quotes,shares`;
			const response = await withRetry(() =>
				fetch(metricsUrl, {
					headers: { Authorization: `Bearer ${token}` },
					signal: AbortSignal.timeout(15000),
				}),
			);
			const data = await response.json();

			if (data.data) {
				const metrics: Record<string, number> = {};
				for (const m of data.data) {
					metrics[m.name] = m.values?.[0]?.value || 0;
				}

				const views = metrics.views || 0;
				const engagement =
					(metrics.likes || 0) +
					(metrics.replies || 0) * 2 +
					(metrics.reposts || 0) * 1.5;
				const engagementRate = views > 0 ? (engagement / views) * 100 : 0;

				await getSupabaseAny()
					.from("auto_post_queue")
					.update({
						views_at_24h: metrics.views || 0,
						likes_count: metrics.likes || 0,
						replies_count: metrics.replies || 0,
						reposts_count: metrics.reposts || 0,
						engagement_rate: engagementRate,
						engagement_fetched_at: new Date().toISOString(),
					})
					.eq("id", post.id);

				results.updated++;
			} else {
				results.failed++;
			}
		} catch (err) {
			logger.warn("Engagement sync failed for post", {
				postId: post.id,
				error: String(err),
			});
			results.failed++;
		}

		await new Promise((r) => setTimeout(r, ENGAGEMENT_DELAY_BETWEEN_ITEMS));
	}

	return results;
}

// ============================================================================
// PHASE 3: Engagement Sync - Reply Metrics
// ============================================================================

export async function processReplyMetrics(
	job: EngagementSyncJob,
): Promise<{ updated: number; failed: number }> {
	const { decrypt } = await import("../encryption.js");
	const { getSupabaseAny } = await import("../supabase.js");

	const results = { updated: 0, failed: 0 };

	const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();
	const { data: sentReplies, error } = (await getSupabaseAny()
		.from("sent_replies")
		.select("id, threads_reply_id, account_id")
		.eq("user_id", job.userId)
		.not("threads_reply_id", "is", null)
		.or(`metrics_updated_at.is.null,metrics_updated_at.lt.${oneHourAgo}`)
		.limit(100)) as {
		data: SentReplyRow[] | null;
		error: PostgrestError | null;
	};

	if (error || !sentReplies || sentReplies.length === 0) return results;

	const replysByAccount = new Map<string, SentReplyRow[]>();
	for (const reply of sentReplies) {
		const list = replysByAccount.get(reply.account_id) || [];
		list.push(reply);
		replysByAccount.set(reply.account_id, list);
	}

	for (const [accountId, replies] of Array.from(replysByAccount.entries())) {
		const { data: account } = (await getSupabaseAny()
			.from("accounts")
			.select("threads_access_token_encrypted")
			.eq("id", accountId)
			.eq("user_id", job.userId)
			.maybeSingle()) as {
			data: ReplyMetricsAccountRow | null;
			error: PostgrestError | null;
		};

		if (!account?.threads_access_token_encrypted) continue;

		let token: string;
		try {
			token = decrypt(account.threads_access_token_encrypted);
		} catch (decryptErr) {
			logger.warn("Token decryption failed, skipping account replies", {
				accountId,
				error: String(decryptErr),
			});
			continue;
		}

		for (const reply of replies) {
			if (!hasTimeBudget()) break;
			try {
				const url = `https://graph.threads.net/v1.0/${reply.threads_reply_id}?fields=id,like_count,reply_count`;
				const response = await withRetry(() =>
					fetch(url, {
						headers: { Authorization: `Bearer ${token}` },
						signal: AbortSignal.timeout(15000),
					}),
				);
				const data = await response.json();

				if (!data.error) {
					await getSupabaseAny()
						.from("sent_replies")
						.update({
							likes_count: (data as ThreadsReplyData).like_count || 0,
							reply_count: data.reply_count || 0,
							metrics_updated_at: new Date().toISOString(),
						})
						.eq("id", reply.id);

					results.updated++;
				} else {
					results.failed++;
				}
			} catch (err) {
				logger.warn("Reply metrics sync failed", {
					replyId: reply.id,
					error: String(err),
				});
				results.failed++;
			}

			await new Promise((r) => setTimeout(r, ENGAGEMENT_DELAY_BETWEEN_ITEMS));
		}
	}

	return results;
}

// ============================================================================
// PHASE 3: Engagement Sync - Mentions
// ============================================================================

export async function processMentions(
	job: EngagementSyncJob,
): Promise<{ updated: number; failed: number }> {
	const { decrypt } = await import("../encryption.js");
	const { getSupabase } = await import("../supabase.js");

	const results = { updated: 0, failed: 0 };

	if (!job.accountIds || job.accountIds.length === 0) return results;

	for (const accountId of job.accountIds) {
		if (!hasTimeBudget()) break;
		const { data: account } = (await getSupabase()
			.from("accounts")
			.select(
				"threads_user_id, threads_access_token_encrypted, needs_reauth, is_active",
			)
			.eq("id", accountId)
			.eq("user_id", job.userId)
			.maybeSingle()) as {
			data: MentionsAccountRow | null;
			error: PostgrestError | null;
		};

		if (!account?.threads_access_token_encrypted) continue;
		if (account.needs_reauth || account.is_active === false) continue;

		try {
			let token: string;
			try {
				token = decrypt(account.threads_access_token_encrypted);
			} catch (decryptErr) {
				logger.warn("Token decryption failed, skipping mentions", {
					accountId,
					error: String(decryptErr),
				});
				results.failed++;
				continue;
			}
			const url = `https://graph.threads.net/v1.0/${account.threads_user_id}/mentions?fields=id,text,username,timestamp&limit=50`;
			const response = await withRetry(() =>
				fetch(url, {
					headers: { Authorization: `Bearer ${token}` },
					signal: AbortSignal.timeout(15000),
				}),
			);
			const data = await response.json();

			if (data.data && data.data.length > 0) {
				const mentionRows = data.data.map(
					(mention: {
						id: string;
						username?: string | undefined;
						text?: string | undefined;
						timestamp?: string | undefined;
					}) => ({
						account_id: accountId,
						user_id: job.userId,
						threads_mention_id: mention.id,
						username: mention.username,
						content: sanitizeHtml(mention.text || ""),
						timestamp: mention.timestamp
							? new Date(mention.timestamp).toISOString()
							: new Date().toISOString(),
					}),
				);
				await getSupabase()
					.from("mentions")
					.upsert(mentionRows, { onConflict: "threads_mention_id" });
				results.updated += data.data.length;
			}
		} catch (err) {
			logger.warn("Mention sync failed", {
				accountId,
				error: String(err),
			});
			results.failed++;
		}

		await new Promise((r) => setTimeout(r, ENGAGEMENT_DELAY_BETWEEN_ITEMS));
	}

	return results;
}

// ============================================================================
// PHASE 3: Engagement Sync - Process Engagement Job
// ============================================================================

export async function processEngagementJob(
	job: EngagementSyncJob,
): Promise<void> {
	const { getRedis } = await import("../redis.js");

	logger.debug("[orchestrator] Processing engagement sync job", {
		jobId: job.id,
		type: job.type,
	});

	// Update job status
	const engJob = await (async () => {
		const data = await getRedis().get(`${ENGAGEMENT_JOB_PREFIX}${job.id}`);
		if (!data) return null;
		return typeof data === "string" ? JSON.parse(data) : data;
	})();
	if (engJob) {
		await getRedis().set(
			`${ENGAGEMENT_JOB_PREFIX}${job.id}`,
			JSON.stringify({
				...engJob,
				status: "processing",
				startedAt: Date.now(),
			}),
			{ ex: 3600 },
		);
	}

	await updateSyncJobsTable(job.id, job.userId, {
		job_type: job.type,
		status: "processing",
		started_at: new Date().toISOString(),
	});

	let results: { updated: number; failed: number };

	switch (job.type) {
		case "auto-post-engagement":
			results = await processAutoPostEngagement(job);
			break;
		case "reply-metrics":
			results = await processReplyMetrics(job);
			break;
		case "mentions":
			results = await processMentions(job);
			break;
		default:
			results = { updated: 0, failed: 0 };
	}

	// Update completed status
	if (engJob) {
		await getRedis().set(
			`${ENGAGEMENT_JOB_PREFIX}${job.id}`,
			JSON.stringify({
				...engJob,
				status: "completed",
				completedAt: Date.now(),
				results,
			}),
			{ ex: 3600 },
		);
	}

	await updateSyncJobsTable(job.id, job.userId, {
		job_type: job.type,
		status: "completed",
		completed_at: new Date().toISOString(),
		success_count: results.updated,
		failed_count: results.failed,
		engagement_updated: results.updated,
	});

	logger.info("[orchestrator] Engagement sync job completed", {
		jobId: job.id,
		updated: results.updated,
		failed: results.failed,
	});
}

// ============================================================================
// PHASE 3: Engagement Sync - Process Queue
// ============================================================================

export async function processEngagementSyncQueue(): Promise<number> {
	const { getRedis } = await import("../redis.js");

	if (!hasTimeBudget()) {
		logger.debug("[orchestrator] No time budget for engagement sync queue");
		return 0;
	}

	const redis = getRedis();
	const queueLength = await redis.llen(ENGAGEMENT_QUEUE_KEY);
	logger.debug("[orchestrator] Engagement sync queue check", { queueLength });

	if (queueLength === 0) return 0;

	let totalProcessed = 0;
	const MAX_JOBS_PER_RUN = 5;

	for (let i = 0; i < MAX_JOBS_PER_RUN; i++) {
		if (!hasTimeBudget()) {
			logger.debug("[orchestrator] Engagement sync time budget exceeded", {
				processed: totalProcessed,
			});
			break;
		}

		const currentLen = await redis.llen(ENGAGEMENT_QUEUE_KEY);
		if (currentLen === 0) break;

		const jobId = (await redis.rpop(ENGAGEMENT_QUEUE_KEY)) as string | null;
		if (!jobId) break;

		const data = await redis.get(`${ENGAGEMENT_JOB_PREFIX}${jobId}`);
		if (!data) {
			// Job data expired from Redis before processing — mark DB record as failed
			try {
				const { getSupabase } = await import("../supabase.js");
				await getSupabase()
					.from("sync_jobs")
					.update({
						status: "failed",
						completed_at: new Date().toISOString(),
						error_message: "Job data expired from Redis before processing",
					})
					.eq("id", jobId);
			} catch {
				/* ignore — stale recovery will catch it */
			}
			continue;
		}

		const job: EngagementSyncJob =
			typeof data === "string" ? JSON.parse(data) : (data as EngagementSyncJob);

		await processEngagementJob(job);
		totalProcessed++;
	}

	return totalProcessed;
}
