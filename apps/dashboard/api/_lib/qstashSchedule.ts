/**
 * QStash dispatch utilities for scheduled posts.
 *
 * dispatchPostPublish() — sends a QStash message with notBefore for exact-time delivery.
 * cancelPostPublish()  — cancels a pending QStash message (best-effort).
 *
 * Both are fail-safe: QStash errors are logged but never propagate.
 * Callers that need exact-time guarantees must check dispatchPostPublish()
 * returning a messageId before marking scheduling as successful.
 */

import { logger } from "./logger.js";
import { getRequiredAppBaseUrl } from "./qstashDefaults.js";
import { getSupabase } from "./supabase.js";

// biome-ignore lint/suspicious/noExplicitAny: posts.metadata is untyped JSONB
const db = (): any => getSupabase();

/**
 * Dispatch a QStash message to publish a scheduled post at its exact time.
 * Stores the QStash messageId in posts.metadata for cancel/tracking.
 *
 * Returns the messageId on success, null on failure.
 * Failures are logged but never thrown — the cron is the fallback.
 */
export async function dispatchPostPublish(
	postId: string,
	scheduledFor: Date,
): Promise<string | null> {
	try {
		const { getQStashClient } = await import("./qstash.js");
		const { RETRIES, getFailureCallbackUrl } = await import(
			"./qstashDefaults.js"
		);
		const qstash = getQStashClient();
		const scheduledUnix = Math.floor(scheduledFor.getTime() / 1000);

		const result = await qstash.publishJSON({
			url: `${getRequiredAppBaseUrl()}/api/scheduled-post-publish`,
			body: {
				postId,
				traceId: `sched-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
			},
			notBefore: scheduledUnix,
			retries: RETRIES.CRITICAL,
			deduplicationId: `post-${postId}-${scheduledUnix}`,
			failureCallback: getFailureCallbackUrl(),
		});

		// Store messageId in first-class columns and metadata for compatibility.
		const { data: post } = await db()
			.from("posts")
			.select("metadata,qstash_message_id")
			.eq("id", postId)
			.maybeSingle();

		const metadata = {
			...(post?.metadata || {}),
			qstash_message_id: result.messageId,
		};
		await db()
			.from("posts")
			.update({
				metadata,
				qstash_message_id: result.messageId,
				qstash_dispatched_at: new Date().toISOString(),
				qstash_dispatch_status: "dispatched",
				qstash_failure_reason: null,
			})
			.eq("id", postId);

		logger.info("[qstash-schedule] Dispatched", {
			postId,
			messageId: result.messageId,
			scheduledFor: scheduledFor.toISOString(),
		});

		return result.messageId;
	} catch (err) {
		logger.warn("[qstash-schedule] Dispatch failed (cron fallback active)", {
			postId,
			error: String(err),
		});
		return null;
	}
}

/**
 * Cancel a known QStash message id without reading posts.metadata.
 * Best-effort for superseded reschedules where metadata already points at
 * the replacement exact-time message.
 */
export async function cancelQStashMessage(
	messageId: string,
	context: Record<string, unknown> = {},
): Promise<void> {
	try {
		const { getQStashClient } = await import("./qstash.js");
		const qstash = getQStashClient();
		await qstash.messages.delete(messageId);
		logger.info("[qstash-schedule] Cancelled message", {
			...context,
			messageId,
		});
	} catch (err) {
		logger.warn("[qstash-schedule] Cancel message failed (non-critical)", {
			...context,
			messageId,
			error: String(err),
		});
	}
}

/**
 * Dispatch a delayed engagement fetch for a published post.
 * Fires at `delaySec` after now to fetch Threads/IG metrics and update DB.
 * Best-effort — never throws. Called after successful publish.
 */
export async function dispatchEngagementFetch(
	postId: string,
	threadsPostId: string,
	delaySec: number,
): Promise<void> {
	try {
		const { getQStashClient } = await import("./qstash.js");
		const qstash = getQStashClient();

		await qstash.publishJSON({
			url: `${getRequiredAppBaseUrl()}/api/sync?action=post-engagement`,
			body: { postId, threadsPostId },
			delay: delaySec,
			retries: 2,
			deduplicationId: `engagement-${postId}-${delaySec}`,
		});

		logger.info("[qstash-schedule] Engagement fetch dispatched", {
			postId,
			threadsPostId: threadsPostId.slice(0, 12),
			delaySec,
		});
	} catch (err) {
		logger.warn(
			"[qstash-schedule] Engagement fetch dispatch failed (non-critical)",
			{
				postId,
				error: String(err),
			},
		);
	}
}

/**
 * Schedule account-level engagement syncs at 1h, 6h, and 24h after publish.
 * Fire-and-forget — errors are logged but never thrown.
 */
export async function schedulePostPublishSyncs(
	postId: string,
	accountId: string,
	userId: string | undefined,
	platform: "threads" | "instagram",
	source = "publish",
): Promise<void> {
	try {
		const { getQStashClient } = await import("./qstash.js");
		const qstash = getQStashClient();
		const syncUrl =
			platform === "instagram"
				? `${getRequiredAppBaseUrl()}/api/sync/ig-account`
				: `${getRequiredAppBaseUrl()}/api/sync/threads-account`;

		const body: Record<string, unknown> = {
			accountId,
			syncType: "recent",
			trigger: "post-publish",
		};
		if (userId) body.userId = userId;

		await Promise.all(
			[3600, 21600, 86400].map((delaySec) =>
				qstash.publishJSON({
					url: syncUrl,
					body,
					retries: 2,
					delay: delaySec,
					deduplicationId: `${platform}-${source}-${postId}-${delaySec}`,
				}),
			),
		);
	} catch (err) {
		logger.warn(
			"[qstash-schedule] Post-publish sync scheduling failed (non-critical)",
			{
				postId,
				platform,
				error: String(err),
			},
		);
	}
}

/**
 * Dispatch a delayed cross-reply from a different account in the same group.
 * Fires 30-60s after publish to simulate organic engagement.
 * Fire-and-forget — never throws.
 */
export async function dispatchCrossReply(payload: {
	queueItemId: string;
	workspaceId: string;
	groupId: string;
	ownerId: string;
	targetAccountId: string;
	targetThreadsPostId: string;
	postContent: string;
}): Promise<void> {
	try {
		const { getQStashClient } = await import("./qstash.js");
		const qstash = getQStashClient();

		// Random delay between 30-60 seconds
		const delaySec = 30 + Math.floor(Math.random() * 31);

		await qstash.publishJSON({
			url: `${getRequiredAppBaseUrl()}/api/cross-reply-publish`,
			body: payload,
			delay: delaySec,
			retries: 1,
			deduplicationId: `cross-reply-${payload.queueItemId}`,
		});

		logger.info("[qstash-schedule] Cross-reply dispatched", {
			queueItemId: payload.queueItemId,
			delaySec,
		});
	} catch (err) {
		logger.warn(
			"[qstash-schedule] Cross-reply dispatch failed (non-critical)",
			{
				queueItemId: payload.queueItemId,
				error: String(err),
			},
		);
	}
}

/**
 * Dispatch a targeted reply harvest exactly 15 min after a post publishes.
 * Research: 15-min reply speed = 391% higher conversion (Reply Engagement Strategy S2).
 * The existing 15-min cron is the fallback — this ensures precise timing.
 */
export async function dispatchReplyHarvest(payload: {
	queueItemId: string;
	workspaceId: string;
	groupId: string;
	ownerId: string;
	accountId: string;
	postId: string;
	sourceTable?: "auto_post_queue" | "posts" | undefined;
}): Promise<void> {
	try {
		const { getQStashClient } = await import("./qstash.js");
		const qstash = getQStashClient();
		const sourceTable = payload.sourceTable || "auto_post_queue";

		await qstash.publishJSON({
			url: `${getRequiredAppBaseUrl()}/api/auto-reply-harvest`,
			body: {
				...payload,
				sourceTable,
			},
			delay: 900, // 15 minutes
			retries: 1, // Best-effort — cron is the fallback
			deduplicationId: `reply-harvest-${sourceTable}-${payload.queueItemId}`,
		});

		logger.info("[qstash-schedule] Reply harvest dispatched (15min)", {
			queueItemId: payload.queueItemId,
			postId: payload.postId,
			sourceTable,
		});
	} catch (err) {
		logger.warn(
			"[qstash-schedule] Reply harvest dispatch failed (non-critical)",
			{
				queueItemId: payload.queueItemId,
				error: String(err),
			},
		);
	}
}

/**
 * Cancel a pending QStash message for a post.
 * Best-effort — never throws. Called on reschedule, delete, or move-to-draft.
 */
export async function cancelPostPublish(postId: string): Promise<void> {
	try {
		const { data: post } = await db()
			.from("posts")
			.select("metadata")
			.eq("id", postId)
			.maybeSingle();

		const messageId = post?.qstash_message_id || post?.metadata?.qstash_message_id;
		if (!messageId) return;

		await cancelQStashMessage(messageId, { postId });

		// Clear messageId from metadata
		const metadata = { ...(post.metadata || {}) };
		delete metadata.qstash_message_id;
		await db()
			.from("posts")
			.update({
				metadata,
				qstash_message_id: null,
				qstash_dispatch_status: null,
				qstash_dispatched_at: null,
				qstash_failure_reason: null,
			})
			.eq("id", postId);

		logger.info("[qstash-schedule] Cancelled", { postId, messageId });
	} catch (err) {
		logger.warn("[qstash-schedule] Cancel failed (non-critical)", {
			postId,
			error: String(err),
		});
	}
}
