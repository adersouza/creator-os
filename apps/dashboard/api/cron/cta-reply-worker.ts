// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * CTA Reply Worker — Delayed CTA replies to high-performing posts
 *
 * Replaces the old immediate self-reply thread system. Instead of creating
 * a 2-part thread at publish time, this cron finds posts that are 12-24h old
 * with good engagement and replies to them with a CTA (e.g. "Write me on Snap: xyz").
 *
 * Why this works better:
 * - The reply inherits the parent post's distribution (shows as a thread chain)
 * - Engaged users get notified about the reply
 * - CTA is separated from bait content, doesn't hurt original engagement rate
 * - Varying CTA wording avoids pattern detection
 *
 * Runs every 30 minutes via Vercel cron.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

export const config = {
	maxDuration: 60,
};

const JOB_NAME = "cta-reply-worker";

// Default CTA templates if none configured on the group
const DEFAULT_CTA_TEMPLATES = [
	"Write me on Snap: {handle}",
	"Find me on snap: {handle}",
	"Here's my Snap: {handle}",
	"let's talk on snap: {handle}",
	"Add me on snap: {handle}",
	"DM me on snap: {handle}",
	"Snap me: {handle}",
];

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const { withCronLock, trackCronRun } = await import("../_lib/cronUtils.js");
	const { getSupabaseAny } = await import("../_lib/supabase.js");
	const { logger } = await import("../_lib/logger.js");

	const db = getSupabaseAny();

	const lockResult = await withCronLock(db, JOB_NAME, async () => {
		return trackCronRun(db, JOB_NAME, async () => {
			// 1. Find groups with CTA reply enabled
			const { data: groups } = await db
				.from("auto_post_group_config")
				.select(
					"group_id, workspace_id, cta_reply_enabled, cta_templates, cta_reply_min_likes, cta_reply_delay_hours",
				)
				.eq("enabled", true)
				.eq("cta_reply_enabled", true);

			if (!groups || groups.length === 0) {
				return { itemsProcessed: 0, metadata: { reason: "no_cta_groups" } };
			}

			let totalReplied = 0;
			let totalSkipped = 0;
			let totalFailed = 0;

			for (const group of groups as Array<Record<string, unknown>>) {
				const groupId = group.group_id as string;
				const workspaceId = group.workspace_id as string;
				const minLikes = (group.cta_reply_min_likes as number) ?? 5;
				const delayHours = (group.cta_reply_delay_hours as number) ?? 16;
				const templates = (group.cta_templates as string[]) ?? [];

				try {
					const result = await processGroup(db, logger, {
						groupId,
						workspaceId,
						minLikes,
						delayHours,
						templates,
					});
					totalReplied += result.replied;
					totalSkipped += result.skipped;
					totalFailed += result.failed;
				} catch (err) {
					logger.error(`[${JOB_NAME}] Group processing failed`, {
						groupId,
						error: err instanceof Error ? err.message : String(err),
					});
					totalFailed++;
				}
			}

			logger.info(`[${JOB_NAME}] Complete`, {
				totalReplied,
				totalSkipped,
				totalFailed,
			});
			return {
				itemsProcessed: totalReplied,
				metadata: {
					replied: totalReplied,
					skipped: totalSkipped,
					failed: totalFailed,
				},
			};
		});
	});

	if ("skipped" in lockResult && lockResult.skipped) {
		res.json({ ok: true, skipped: "locked" });
		return;
	}

	const payload = "result" in lockResult ? lockResult.result : {};
	res.json({ ok: true, ...payload });
}

// ============================================================================
// Core logic
// ============================================================================

interface GroupCtaConfig {
	groupId: string;
	workspaceId: string;
	minLikes: number;
	delayHours: number;
	templates: string[];
}

// biome-ignore lint/suspicious/noExplicitAny: logger type varies
async function processGroup(db: any, logger: any, config: GroupCtaConfig) {
	const { groupId, workspaceId, minLikes, delayHours } = config;
	const now = new Date();

	// Window: posts that are delayHours to delayHours+12h old
	const windowStart = new Date(
		now.getTime() - (delayHours + 12) * 60 * 60 * 1000,
	).toISOString();
	const windowEnd = new Date(
		now.getTime() - delayHours * 60 * 60 * 1000,
	).toISOString();

	// Find published posts in the window that haven't gotten a CTA reply yet
	const { data: eligiblePosts } = await db
		.from("auto_post_queue")
		.select("id, account_id, threads_post_id, posted_at, group_id, metadata")
		.eq("group_id", groupId)
		.eq("status", "published")
		.is("cta_replied_at", null)
		.gte("posted_at", windowStart)
		.lte("posted_at", windowEnd)
		.not("account_id", "is", null)
		.order("posted_at", { ascending: false });

	if (!eligiblePosts || eligiblePosts.length === 0) {
		return { replied: 0, skipped: 0, failed: 0 };
	}

	// Get the thread IDs for these posts (we need the Threads post ID to reply to)
	const accountIds = [
		...new Set(
			eligiblePosts.map((p: Record<string, unknown>) => p.account_id as string),
		),
	];
	const threadIds = [
		...new Set(
			eligiblePosts
				.map((p: Record<string, unknown>) => p.threads_post_id as string | null)
				.filter((id: string | null): id is string => Boolean(id)),
		),
	];

	if (threadIds.length === 0) {
		return {
			replied: 0,
			skipped: eligiblePosts.length,
			failed: 0,
		};
	}

	// Get post performance from the posts table by exact Threads post ID.
	const { data: postMetrics } = await db
		.from("posts")
		.select("id, threads_post_id, account_id, likes_count, views_count")
		.in("threads_post_id", threadIds)
		.eq("status", "published")
		.gte("published_at", windowStart)
		.lte("published_at", windowEnd);

	// Build a lookup keyed by exact Threads post ID.
	const postLookup = new Map<
		string,
		{ thread_id: string; likes: number; views: number }
	>();
	if (postMetrics) {
		for (const p of postMetrics as Array<Record<string, unknown>>) {
			const threadId = p.threads_post_id as string | null;
			if (!threadId) continue;
			postLookup.set(threadId, {
				thread_id: threadId,
				likes: (p.likes_count as number) ?? 0,
				views: (p.views_count as number) ?? 0,
			});
		}
	}

	// Load account tokens for publishing the reply
	const { data: accounts } = await db
		.from("accounts")
		.select(
			"id, user_id, username, threads_user_id, threads_access_token_encrypted, is_active, needs_reauth",
		)
		.in("id", accountIds);

	const accountMap = new Map<string, Record<string, unknown>>();
	if (accounts) {
		for (const a of accounts as Array<Record<string, unknown>>) {
			if (a.is_active !== false && !a.needs_reauth) {
				accountMap.set(a.id as string, a);
			}
		}
	}

	// Load CTA handles per account (from account bio or group config)
	// For now, use the templates with the account username as handle
	const effectiveTemplates =
		config.templates.length > 0 ? config.templates : DEFAULT_CTA_TEMPLATES;

	let replied = 0;
	let skipped = 0;
	let failed = 0;

	// Process max 3 posts per group per run to avoid burst patterns
	const postsToProcess = eligiblePosts.slice(0, 3);

	for (const queueItem of postsToProcess as Array<Record<string, unknown>>) {
		const accountId = queueItem.account_id as string;
		const account = accountMap.get(accountId);
		if (!account) {
			skipped++;
			continue;
		}

		const queueThreadId = queueItem.threads_post_id as string | null;
		const postData = queueThreadId ? postLookup.get(queueThreadId) : null;

		if (!postData?.thread_id) {
			// Can't find the Threads post ID — skip
			skipped++;
			continue;
		}

		// Check engagement threshold
		if (postData.likes < minLikes) {
			// Mark as skipped so we don't re-check it
			await db
				.from("auto_post_queue")
				.update({ cta_replied_at: now.toISOString() } as Record<
					string,
					unknown
				>)
				.eq("id", queueItem.id);
			skipped++;
			continue;
		}

		// Pick a random CTA template
		const template =
			effectiveTemplates[Math.floor(Math.random() * effectiveTemplates.length)];
		const username = (account.username as string) || "me";
		const ctaText = template!.replace("{handle}", username);

		// Publish the reply using the Threads API
		try {
			const { decrypt } = await import("../_lib/encryption.js");
			const { enforceOutboundOperatorGuard, recordOutboundOperatorResult } =
				await import("../_lib/outboundOperatorGuard.js");
			const { withRetry } = await import("../_lib/retryUtils.js");
			const userId = (account.user_id as string | null) || "";
			const outboundPayload = {
				queueItemId: queueItem.id,
				parentThreadId: postData.thread_id,
				ctaText,
				source: JOB_NAME,
			};
			const outboundGuard = await enforceOutboundOperatorGuard({
				db,
				userId,
				actionName: "cta_reply",
				riskLevel: "high",
				scope: { workspaceId, groupId, accountId },
				payload: outboundPayload,
				idempotencyKey: `cta-reply:${queueItem.id}:${accountId}`,
				metadata: { queueItemId: queueItem.id, source: JOB_NAME },
			});
			if (!outboundGuard.allowed) {
				logger.warn(`[${JOB_NAME}] CTA reply blocked by outbound guard`, {
					accountId,
					queueItemId: queueItem.id,
					code: outboundGuard.code,
					reason: outboundGuard.reason,
				});
				skipped++;
				continue;
			}
			const token = decrypt(account.threads_access_token_encrypted as string);
			const threadsUserId = account.threads_user_id as string;
			const lockId = `pending:${crypto.randomUUID()}`;
			const { data: lockedRows, error: lockError } = await db
				.from("auto_post_queue")
				.update({ cta_reply_thread_id: lockId } as Record<string, unknown>)
				.eq("id", queueItem.id)
				.is("cta_replied_at", null)
				.is("cta_reply_thread_id", null)
				.select("id");
			if (lockError) {
				logger.warn(`[${JOB_NAME}] CTA reply lock failed`, {
					queueItemId: queueItem.id,
					error: lockError.message,
				});
				failed++;
				continue;
			}
			if (!lockedRows || lockedRows.length === 0) {
				skipped++;
				continue;
			}

			// Create reply container
			const createUrl = `https://graph.threads.net/v1.0/${threadsUserId}/threads`;
			const createResponse = await withRetry(() =>
				fetch(createUrl, {
					method: "POST",
					headers: {
						"Content-Type": "application/x-www-form-urlencoded",
						Authorization: `Bearer ${token}`,
					},
					body: new URLSearchParams({
						media_type: "TEXT",
						text: ctaText,
						reply_to_id: postData.thread_id,
					}),
					signal: AbortSignal.timeout(10_000),
				}),
			);

			const createData = await createResponse.json();
			if (!createResponse.ok || !createData.id) {
				logger.warn(`[${JOB_NAME}] Reply container failed`, {
					accountId,
					error: createData.error?.message || "Unknown error",
				});
				await recordOutboundOperatorResult({
					db,
					userId,
					actionName: "cta_reply",
					riskLevel: "high",
					scope: { workspaceId, groupId, accountId },
					payload: outboundPayload,
					idempotencyKey: `cta-reply:${queueItem.id}:${accountId}`,
					outcome: "failure",
					message: "CTA reply container failed",
					error: createData.error?.message || "Unknown error",
					metadata: { queueItemId: queueItem.id, source: JOB_NAME },
				});
				await db
					.from("auto_post_queue")
					.update({ cta_reply_thread_id: null } as Record<string, unknown>)
					.eq("id", queueItem.id)
					.eq("cta_reply_thread_id", lockId);
				failed++;
				continue;
			}

			// Publish the container
			const publishUrl = `https://graph.threads.net/v1.0/${threadsUserId}/threads_publish`;
			const publishResponse = await withRetry(() =>
				fetch(publishUrl, {
					method: "POST",
					headers: {
						"Content-Type": "application/x-www-form-urlencoded",
						Authorization: `Bearer ${token}`,
					},
					body: new URLSearchParams({
						creation_id: createData.id,
					}),
					signal: AbortSignal.timeout(10_000),
				}),
			);

			const publishData = await publishResponse.json();
			if (!publishResponse.ok || !publishData.id) {
				logger.warn(`[${JOB_NAME}] Reply publish failed`, {
					accountId,
					error: publishData.error?.message || "Unknown error",
				});
				await recordOutboundOperatorResult({
					db,
					userId,
					actionName: "cta_reply",
					riskLevel: "high",
					scope: { workspaceId, groupId, accountId },
					payload: outboundPayload,
					idempotencyKey: `cta-reply:${queueItem.id}:${accountId}`,
					outcome: "failure",
					message: "CTA reply publish failed",
					error: publishData.error?.message || "Unknown error",
					metadata: {
						queueItemId: queueItem.id,
						source: JOB_NAME,
						containerId: createData.id,
					},
				});
				await db
					.from("auto_post_queue")
					.update({ cta_reply_thread_id: null } as Record<string, unknown>)
					.eq("id", queueItem.id)
					.eq("cta_reply_thread_id", lockId);
				failed++;
				continue;
			}

			// Mark the queue item as CTA-replied
			await db
				.from("auto_post_queue")
				.update({
					cta_replied_at: now.toISOString(),
					cta_reply_thread_id: publishData.id,
				} as Record<string, unknown>)
				.eq("id", queueItem.id)
				.eq("cta_reply_thread_id", lockId);

			await recordOutboundOperatorResult({
				db,
				userId,
				actionName: "cta_reply",
				riskLevel: "high",
				scope: { workspaceId, groupId, accountId },
				payload: outboundPayload,
				idempotencyKey: `cta-reply:${queueItem.id}:${accountId}`,
				outcome: "success",
				message: "CTA reply published",
				metadata: {
					queueItemId: queueItem.id,
					source: JOB_NAME,
					replyThreadId: publishData.id,
				},
			});

			logger.info(`[${JOB_NAME}] CTA reply posted`, {
				accountId,
				username,
				parentThreadId: postData.thread_id,
				replyThreadId: publishData.id,
				likes: postData.likes,
				ctaText,
			});

			replied++;
		} catch (err) {
			logger.error(`[${JOB_NAME}] Reply failed`, {
				accountId,
				error: err instanceof Error ? err.message : String(err),
			});
			failed++;
		}
	}

	// Mark remaining eligible posts that are too old (past the window) so we don't recheck
	// Remaining eligible posts (if any) will be picked up on the next run if still in window

	return { replied, skipped, failed };
}
