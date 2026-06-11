import * as crypto from "node:crypto";
import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";

const db = () => getSupabaseAny();

export const QUEUE_STATUSES = [
	"needs_review",
	"pending",
	"queued",
	"publishing",
	"published",
	"rejected",
	"dead_letter",
	"cancelled",
] as const;

export type AutoPostQueueStatus = (typeof QUEUE_STATUSES)[number];

export const CLAIMABLE_QUEUE_STATUSES: readonly AutoPostQueueStatus[] = [
	"pending",
	"queued",
];

export const TERMINAL_QUEUE_STATUSES: readonly AutoPostQueueStatus[] = [
	"published",
	"rejected",
	"dead_letter",
	"cancelled",
];

export const RESCHEDULABLE_QUEUE_STATUSES: readonly AutoPostQueueStatus[] = [
	"pending",
	"queued",
	"publishing",
];

export const POOL_AVAILABLE_STATUS = "available";
export const POOL_CLAIMED_STATUS = "claimed";

export function isKnownQueueStatus(
	status: string | null | undefined,
): status is AutoPostQueueStatus {
	return QUEUE_STATUSES.includes(status as AutoPostQueueStatus);
}

export function isClaimableQueueStatus(
	status: string | null | undefined,
): boolean {
	return CLAIMABLE_QUEUE_STATUSES.includes(status as AutoPostQueueStatus);
}

export function isTerminalQueueStatus(
	status: string | null | undefined,
): boolean {
	return TERMINAL_QUEUE_STATUSES.includes(status as AutoPostQueueStatus);
}

export function isReschedulableQueueStatus(
	status: string | null | undefined,
): boolean {
	return RESCHEDULABLE_QUEUE_STATUSES.includes(status as AutoPostQueueStatus);
}

export function poolStatusForQueueStatus(
	status: string,
	hasAssignedAccount = false,
): string | null {
	if (status === "pending") return POOL_AVAILABLE_STATUS;
	if (status === "queued") {
		return hasAssignedAccount ? POOL_CLAIMED_STATUS : POOL_AVAILABLE_STATUS;
	}
	if (status === "publishing" || status === "published") {
		return POOL_CLAIMED_STATUS;
	}
	if (status === "needs_review") return POOL_AVAILABLE_STATUS;
	return null;
}

export interface AutoPostQueueItem {
	id: string;
	status: string;
	pool_status?: string | null | undefined;
	content: string;
	media_urls: string[] | null;
	platform?: string | null | undefined;
	source_content: string | null;
	source_type: string | null;
	source_competitor_id?: string | null | undefined;
	retry_count: number | null;
	text_spoilers: unknown;
	topic_tag: string | null;
	account_id: string | null;
	metadata: unknown;
	schedule_nonce: string | null;
	qstash_message_id: string | null;
	next_retry_at: string | null;
	scheduled_for: string | null;
	claim_token: string | null;
	claim_expires_at: string | null;
	external_published_at?: string | null | undefined;
	finalize_error?: string | null | undefined;
	normalized_text_hash?: string | null | undefined;
	media_fingerprint?: string | null | undefined;
	publish_fingerprint?: string | null | undefined;
	duplicate_window_hours?: number | null | undefined;
	content_fingerprint?: string | null | undefined;
	generation_id?: string | null | undefined;
	source_id?: string | null | undefined;
	provenance_status?: string | null | undefined;
	provenance_error?: string | null | undefined;
}

export type PublishAttemptResult =
	| "started"
	| "claim_failed"
	| "requeued"
	| "dead_letter"
	| "published"
	| "needs_reconciliation"
	| "reconciled"
	| "reconcile_failed"
	| "failed"
	| "error"
	| "duplicate_fingerprint_blocked"
	| "duplicate_fingerprint_needs_review"
	| "provenance_missing_blocked"
	| "provenance_missing_needs_review"
	| "provenance_manual_allowed";

export interface PublishAttemptValues {
	queueItemId: string;
	userId?: string | null | undefined;
	workspaceId?: string | null | undefined;
	groupId?: string | null | undefined;
	claimToken?: string | null | undefined;
	accountId?: string | null | undefined;
	metaContainerId?: string | null | undefined;
	threadsPostId?: string | null | undefined;
	result: PublishAttemptResult;
	errorCode?: string | null | undefined;
	errorMessage?: string | null | undefined;
	completedAt?: string | null | undefined;
	metadata?: Record<string, unknown> | undefined;
}

function sanitizeAttemptError(error: string | null | undefined): string | null {
	if (!error) return null;
	return error.slice(0, 2000);
}

async function nextPublishAttemptNumber(queueItemId: string): Promise<number> {
	try {
		const { count } = await db()
			.from("publish_attempts")
			.select("id", { count: "exact", head: true })
			.eq("queue_item_id", queueItemId);
		return (count ?? 0) + 1;
	} catch (error) {
		logger.warn("nextPublishAttemptNumber failed", {
			queueItemId,
			error: String(error),
		});
		return 1;
	}
}

export async function recordPublishAttempt(
	values: PublishAttemptValues,
): Promise<string | null> {
	try {
		const attemptNumber = await nextPublishAttemptNumber(values.queueItemId);
		const { data, error } = await db()
			.from("publish_attempts")
			.insert({
				queue_item_id: values.queueItemId,
				user_id: values.userId ?? null,
				workspace_id: values.workspaceId ?? null,
				group_id: values.groupId ?? null,
				claim_token: values.claimToken ?? null,
				account_id: values.accountId ?? null,
				attempt_number: attemptNumber,
				meta_container_id: values.metaContainerId ?? null,
				threads_post_id: values.threadsPostId ?? null,
				result: values.result,
				error_code: values.errorCode ?? null,
				error_message: sanitizeAttemptError(values.errorMessage),
				completed_at:
					values.completedAt ??
					(values.result === "started" ? null : new Date().toISOString()),
				metadata: values.metadata ?? {},
			} as Record<string, unknown>)
			.select("id")
			.maybeSingle();

		if (error) {
			logger.warn("recordPublishAttempt failed", {
				queueItemId: values.queueItemId,
				result: values.result,
				error: String(error),
			});
			return null;
		}

		return (data?.id as string | undefined) ?? null;
	} catch (error) {
		logger.warn("recordPublishAttempt threw", {
			queueItemId: values.queueItemId,
			result: values.result,
			error: String(error),
		});
		return null;
	}
}

export async function startPublishAttempt(
	values: Omit<PublishAttemptValues, "result" | "completedAt">,
): Promise<string | null> {
	return recordPublishAttempt({ ...values, result: "started" });
}

export async function finishPublishAttempt(
	attemptId: string | null | undefined,
	values: {
		accountId?: string | null | undefined;
		metaContainerId?: string | null | undefined;
		threadsPostId?: string | null | undefined;
		result: Exclude<PublishAttemptResult, "started">;
		errorCode?: string | null | undefined;
		errorMessage?: string | null | undefined;
		completedAt?: string | null | undefined;
		metadata?: Record<string, unknown> | undefined;
	},
): Promise<void> {
	if (!attemptId) return;
	try {
		const update: Record<string, unknown> = {
			result: values.result,
			completed_at: values.completedAt ?? new Date().toISOString(),
			error_code: values.errorCode ?? null,
			error_message: sanitizeAttemptError(values.errorMessage),
		};
		if (values.accountId !== undefined) update.account_id = values.accountId;
		if (values.metaContainerId !== undefined) {
			update.meta_container_id = values.metaContainerId;
		}
		if (values.threadsPostId !== undefined) {
			update.threads_post_id = values.threadsPostId;
		}
		if (values.metadata !== undefined) update.metadata = values.metadata;

		const { error } = await db()
			.from("publish_attempts")
			.update(update)
			.eq("id", attemptId);

		if (error) {
			logger.warn("finishPublishAttempt failed", {
				attemptId,
				result: values.result,
				error: String(error),
			});
		}
	} catch (error) {
		logger.warn("finishPublishAttempt threw", {
			attemptId,
			result: values.result,
			error: String(error),
		});
	}
}

export function isQueueItemDueForDispatch(
	scheduledFor: string | null | undefined,
	nextRetryAt: string | null | undefined,
	now: Date = new Date(),
): boolean {
	if (!scheduledFor) return false;
	const scheduledTime = new Date(scheduledFor).getTime();
	if (!Number.isFinite(scheduledTime) || scheduledTime > now.getTime()) {
		return false;
	}
	if (!nextRetryAt) return true;
	const retryTime = new Date(nextRetryAt).getTime();
	return Number.isFinite(retryTime) && retryTime <= now.getTime();
}

export function explainQueueItemPublishClaim(
	item: Pick<
		AutoPostQueueItem,
		| "status"
		| "scheduled_for"
		| "next_retry_at"
		| "schedule_nonce"
		| "claim_token"
		| "claim_expires_at"
	>,
	options?: {
		scheduleNonce?: string | null | undefined;
		now?: Date | undefined;
	},
): string[] {
	const now = options?.now ?? new Date();
	const reasons: string[] = [];

	if (!isClaimableQueueStatus(item.status)) {
		reasons.push("wrong_status");
	}

	if (!item.scheduled_for) {
		reasons.push("missing_scheduled_for");
	} else {
		const scheduledTime = new Date(item.scheduled_for).getTime();
		if (!Number.isFinite(scheduledTime)) {
			reasons.push("invalid_scheduled_for");
		} else if (scheduledTime > now.getTime()) {
			reasons.push("future_scheduled_for");
		}
	}

	if (item.next_retry_at) {
		const nextRetryTime = new Date(item.next_retry_at).getTime();
		if (!Number.isFinite(nextRetryTime)) {
			reasons.push("invalid_next_retry_at");
		} else if (nextRetryTime > now.getTime()) {
			reasons.push("future_next_retry_at");
		}
	}

	const requestedNonce = options?.scheduleNonce ?? null;
	if (requestedNonce) {
		if (item.schedule_nonce !== requestedNonce) {
			reasons.push("stale_schedule_nonce");
		}
	} else if (item.schedule_nonce) {
		reasons.push("missing_requested_schedule_nonce");
	}

	if (item.claim_token) {
		if (!item.claim_expires_at) {
			reasons.push("unexpired_claim");
		} else {
			const claimExpiresTime = new Date(item.claim_expires_at).getTime();
			if (!Number.isFinite(claimExpiresTime)) {
				reasons.push("invalid_claim_expires_at");
			} else if (claimExpiresTime > now.getTime()) {
				reasons.push("unexpired_claim");
			}
		}
	}

	return reasons;
}

export class QueueItemLoadError extends Error {
	queueItemId: string;

	constructor(queueItemId: string, cause: unknown) {
		super("Failed to load auto-post queue item");
		this.name = "QueueItemLoadError";
		this.queueItemId = queueItemId;
		this.cause = cause;
	}
}

export async function loadQueueItemForPublish(
	queueItemId: string,
): Promise<AutoPostQueueItem | null> {
	const { data, error } = await db()
		.from("auto_post_queue")
		.select(
			"id, status, pool_status, content, media_urls, platform, source_content, source_type, source_competitor_id, retry_count, text_spoilers, topic_tag, account_id, metadata, schedule_nonce, qstash_message_id, next_retry_at, scheduled_for, claim_token, claim_expires_at, normalized_text_hash, media_fingerprint, publish_fingerprint, duplicate_window_hours, content_fingerprint, generation_id, source_id, provenance_status, provenance_error",
		)
		.eq("id", queueItemId)
		.maybeSingle();

	if (error) {
		logger.error("loadQueueItemForPublish failed", {
			queueItemId,
			error: String(error),
		});
		throw new QueueItemLoadError(queueItemId, error);
	}
	if (!data) return null;
	return data as AutoPostQueueItem;
}

export async function cancelQueueItem(
	queueItemId: string,
	lastError: string,
): Promise<void> {
	await db()
		.from("auto_post_queue")
		.update({
			status: "cancelled" satisfies AutoPostQueueStatus,
			last_error: lastError,
			claim_token: null,
			claim_expires_at: null,
		} as Record<string, unknown>)
		.eq("id", queueItemId);
}

export async function cancelQueueItemsByIds(
	queueItemIds: string[],
	lastError: string,
): Promise<number> {
	if (queueItemIds.length === 0) return 0;

	const { data, error } = await db()
		.from("auto_post_queue")
		.update({
			status: "cancelled" satisfies AutoPostQueueStatus,
			last_error: lastError,
			schedule_nonce: null,
			qstash_message_id: null,
			claim_token: null,
			claim_expires_at: null,
		} as Record<string, unknown>)
		.in("id", queueItemIds)
		.select("id");

	if (error) {
		logger.error("cancelQueueItemsByIds failed", {
			error: String(error),
			ids: queueItemIds.slice(0, 5),
		});
	}

	return data?.length ?? 0;
}

/**
 * Hard-delete queue items from the database (permanent, no recovery).
 * Used when cancel (status change) isn't sufficient.
 */
export async function hardDeleteQueueItems(
	queueItemIds: string[],
): Promise<number> {
	if (queueItemIds.length === 0) return 0;

	const { data, error } = await db()
		.from("auto_post_queue")
		.delete()
		.in("id", queueItemIds)
		.select("id");

	if (error) {
		logger.error("hardDeleteQueueItems failed", {
			error: String(error),
			ids: queueItemIds.slice(0, 5),
		});
	}

	return data?.length ?? 0;
}

export async function claimQueueItemForPublish(
	queueItemId: string,
	options?: {
		scheduleNonce?: string | null | undefined;
		now?: Date | undefined;
		leaseMinutes?: number | undefined;
	},
): Promise<string | null> {
	const now = options?.now ?? new Date();
	const nowIso = now.toISOString();
	const claimToken = crypto.randomUUID();
	const claimExpiresAt = new Date(
		now.getTime() + (options?.leaseMinutes ?? 10) * 60 * 1000,
	).toISOString();

	const { data, error } = await db().rpc(
		"claim_auto_post_queue_item_for_publish",
		{
			p_queue_item_id: queueItemId,
			p_schedule_nonce: options?.scheduleNonce ?? null,
			p_claim_token: claimToken,
			p_claim_expires_at: claimExpiresAt,
			p_now: nowIso,
		},
	);

	if (error) {
		logger.error("claimQueueItemForPublish failed", {
			queueItemId,
			error: String(error),
		});
		return null;
	}

	const claimedId = Array.isArray(data)
		? (data[0]?.id as string | undefined)
		: ((data as { id?: string } | null | undefined)?.id as string | undefined);

	if (!claimedId) {
		const { data: currentRow, error: currentRowError } = await db()
			.from("auto_post_queue")
			.select(
				"status, pool_status, claimed_at, scheduled_for, next_retry_at, schedule_nonce, qstash_message_id, claim_token, claim_expires_at",
			)
			.eq("id", queueItemId)
			.maybeSingle();

		logger.warn("claimQueueItemForPublish matched no rows", {
			queueItemId,
			currentRow: currentRow
				? {
						status: currentRow.status,
						pool_status: currentRow.pool_status,
						claimed_at: currentRow.claimed_at,
						scheduled_for: currentRow.scheduled_for,
						next_retry_at: currentRow.next_retry_at,
						schedule_nonce: currentRow.schedule_nonce,
						qstash_message_id: currentRow.qstash_message_id,
						claim_token: currentRow.claim_token,
						claim_expires_at: currentRow.claim_expires_at,
						claim_reasons: explainQueueItemPublishClaim(
							currentRow as Pick<
								AutoPostQueueItem,
								| "status"
								| "scheduled_for"
								| "next_retry_at"
								| "schedule_nonce"
								| "claim_token"
								| "claim_expires_at"
							>,
							{ scheduleNonce: options?.scheduleNonce ?? null, now },
						),
					}
				: null,
			currentRowError: currentRowError ? String(currentRowError) : null,
		});
	}

	return claimedId ? claimToken : null;
}

export async function assignQueueItemAccount(
	queueItemId: string,
	accountId: string,
): Promise<void> {
	await db()
		.from("auto_post_queue")
		.update({ account_id: accountId } as Record<string, unknown>)
		.eq("id", queueItemId);
}

export async function queueQueueItemForDispatch(
	queueItemId: string,
	values: {
		accountId: string;
		scheduleNonce: string;
		poolStatus?: string | undefined;
	},
): Promise<void> {
	await db()
		.from("auto_post_queue")
		.update({
			account_id: values.accountId,
			status: "queued" satisfies AutoPostQueueStatus,
			schedule_nonce: values.scheduleNonce,
			...(values.poolStatus ? { pool_status: values.poolStatus } : {}),
		} as Record<string, unknown>)
		.eq("id", queueItemId);
}

export async function ensureQueueItemScheduleNonce(
	queueItemId: string,
	fallbackNonce: string,
): Promise<string> {
	const { data: updated } = await db()
		.from("auto_post_queue")
		.update({ schedule_nonce: fallbackNonce })
		.eq("id", queueItemId)
		.in("status", [...CLAIMABLE_QUEUE_STATUSES])
		.is("schedule_nonce", null)
		.select("schedule_nonce")
		.maybeSingle();

	return (updated?.schedule_nonce as string | null) || fallbackNonce;
}

export async function updateQueueItemScheduledFor(
	queueItemId: string,
	scheduledFor: string,
): Promise<void> {
	const { error, data } = await db()
		.from("auto_post_queue")
		.update({ scheduled_for: scheduledFor } as Record<string, unknown>)
		.eq("id", queueItemId)
		.select("id")
		.maybeSingle();

	if (error || !data) {
		logger.error("updateQueueItemScheduledFor failed", {
			queueItemId,
			scheduledFor,
			error: error ? String(error) : "no rows matched",
		});
		throw new Error(
			`Failed to update scheduled_for for queue item ${queueItemId}`,
		);
	}
}

export async function rescheduleQueueItemForFutureDispatch(
	queueItemId: string,
	values: {
		accountId: string | null;
		scheduledFor: string;
		scheduleNonce?: string | null | undefined;
		qstashMessageId?: string | null | undefined;
		lastError?: string | null | undefined;
	},
): Promise<void> {
	const nextStatus: AutoPostQueueStatus = values.qstashMessageId
		? "queued"
		: "pending";
	const nextPoolStatus = values.qstashMessageId
		? POOL_CLAIMED_STATUS
		: POOL_AVAILABLE_STATUS;

	const { data, error } = await db()
		.from("auto_post_queue")
		.update({
			status: nextStatus,
			pool_status: nextPoolStatus,
			account_id: values.accountId,
			scheduled_for: values.scheduledFor,
			claimed_at: null,
			claim_token: null,
			claim_expires_at: null,
			schedule_nonce: values.scheduleNonce ?? null,
			qstash_message_id: values.qstashMessageId ?? null,
			...(values.lastError !== undefined
				? { last_error: values.lastError }
				: {}),
		} as Record<string, unknown>)
		.eq("id", queueItemId)
		.in("status", [...RESCHEDULABLE_QUEUE_STATUSES])
		.select(
			"id, status, pool_status, account_id, scheduled_for, claimed_at, schedule_nonce, qstash_message_id",
		)
		.maybeSingle();

	if (error || !data) {
		logger.error("rescheduleQueueItemForFutureDispatch failed", {
			queueItemId,
			accountId: values.accountId,
			scheduledFor: values.scheduledFor,
			scheduleNonce: values.scheduleNonce ?? null,
			qstashMessageId: values.qstashMessageId ?? null,
			error: error ? String(error) : "no rows matched",
		});
		throw new Error(
			`Failed to reschedule queue item ${queueItemId} for future dispatch`,
		);
	}
}

export async function markQueueItemDispatched(
	queueItemId: string,
	values: {
		qstashMessageId?: string | null | undefined;
		scheduleNonce: string;
	},
): Promise<void> {
	await db()
		.from("auto_post_queue")
		.update({
			qstash_message_id: values.qstashMessageId ?? null,
			schedule_nonce: values.scheduleNonce,
		} as Record<string, unknown>)
		.eq("id", queueItemId)
		.in("status", [...CLAIMABLE_QUEUE_STATUSES]);
}

export async function requeueQueueItem(
	queueItemId: string,
	values: {
		account_id?: string | null | undefined;
		last_error: string;
		next_retry_at?: string | null | undefined;
		pool_status?: string | null | undefined;
		retry_count?: number | undefined;
		scheduled_for?: string | undefined;
		status?: string | undefined;
	},
): Promise<void> {
	await db()
		.from("auto_post_queue")
		.update({
			status: values.status ?? ("pending" satisfies AutoPostQueueStatus),
			pool_status: values.pool_status,
			account_id: values.account_id,
			retry_count: values.retry_count,
			scheduled_for: values.scheduled_for,
			next_retry_at: values.next_retry_at,
			last_error: values.last_error,
			claim_token: null,
			claim_expires_at: null,
		} as Record<string, unknown>)
		.eq("id", queueItemId);
}

export async function requeueQueueItemWithBackoff(
	queueItemId: string,
	reason: string,
	retryAt: string | Date,
	options?: {
		accountId?: string | null | undefined;
		poolStatus?: string | null | undefined;
		retryCount?: number | undefined;
		status?: string | undefined;
		claimToken?: string | null | undefined;
	},
): Promise<void> {
	const retryAtIso =
		typeof retryAt === "string"
			? new Date(retryAt).toISOString()
			: retryAt.toISOString();

	let query = db()
		.from("auto_post_queue")
		.update({
			status: options?.status ?? ("pending" satisfies AutoPostQueueStatus),
			pool_status: options?.poolStatus ?? POOL_AVAILABLE_STATUS,
			account_id: options?.accountId ?? null,
			retry_count: options?.retryCount,
			scheduled_for: retryAtIso,
			next_retry_at: retryAtIso,
			claimed_at: null,
			claim_token: null,
			claim_expires_at: null,
			schedule_nonce: null,
			qstash_message_id: null,
			last_error: reason,
		} as Record<string, unknown>)
		.eq("id", queueItemId);

	if (options?.claimToken) query = query.eq("claim_token", options.claimToken);
	await query;
}

export async function retryQueueItem(
	queueItemId: string,
	scheduledFor: string,
	options?: {
		workspaceId?: string | null | undefined;
	},
): Promise<void> {
	let query = db()
		.from("auto_post_queue")
		.update({
			status: "pending" satisfies AutoPostQueueStatus,
			pool_status: POOL_AVAILABLE_STATUS,
			account_id: null,
			retry_count: 0,
			last_error: null,
			scheduled_for: scheduledFor,
			next_retry_at: null,
			schedule_nonce: null,
			qstash_message_id: null,
			claim_token: null,
			claim_expires_at: null,
		} as Record<string, unknown>)
		.eq("id", queueItemId);

	if (options?.workspaceId) {
		query = query.eq("workspace_id", options.workspaceId);
	}

	await query;
}

export async function deadLetterQueueItem(
	queueItemId: string,
	lastError: string,
	options?: { claimToken?: string | null | undefined },
): Promise<void> {
	let query = db()
		.from("auto_post_queue")
		.update({
			status: "dead_letter" satisfies AutoPostQueueStatus,
			last_error: lastError,
			claim_token: null,
			claim_expires_at: null,
		} as Record<string, unknown>)
		.eq("id", queueItemId);

	if (options?.claimToken) query = query.eq("claim_token", options.claimToken);
	await query;
}

export async function deadLetterQueueItems(
	queueItemIds: string[],
	lastError: string,
): Promise<void> {
	if (queueItemIds.length === 0) return;

	await db()
		.from("auto_post_queue")
		.update({
			status: "dead_letter" satisfies AutoPostQueueStatus,
			last_error: lastError,
			claim_token: null,
			claim_expires_at: null,
		} as Record<string, unknown>)
		.in("id", queueItemIds);
}

export async function markQueueItemPublished(
	queueItemId: string,
	accountId: string,
	threadId: string,
	postedAt: string,
	options?: { claimToken?: string | null | undefined },
): Promise<void> {
	let query = db()
		.from("auto_post_queue")
		.update({
			status: "published" satisfies AutoPostQueueStatus,
			posted_at: postedAt,
			account_id: accountId,
			threads_post_id: threadId,
			claimed_at: null,
			claim_token: null,
			claim_expires_at: null,
		} as Record<string, unknown>)
		.eq("id", queueItemId);

	if (options?.claimToken) query = query.eq("claim_token", options.claimToken);
	const { data, error } = await query.select("id").maybeSingle();
	if (error || !data) {
		logger.error("markQueueItemPublished failed", {
			queueItemId,
			accountId,
			threadId,
			error: error ? String(error) : "no rows matched",
		});
		throw new Error(`Failed to mark queue item ${queueItemId} published`);
	}
}

export async function markQueueItemNeedsReconciliation(
	queueItemId: string,
	values: {
		accountId: string;
		threadId: string;
		publishedAt: string;
		finalizeError: string;
		claimToken?: string | null | undefined;
	},
): Promise<void> {
	let query = db()
		.from("auto_post_queue")
		.update({
			status: "needs_reconciliation",
			account_id: values.accountId,
			threads_post_id: values.threadId,
			external_published_at: values.publishedAt,
			finalize_error: values.finalizeError,
			last_error: values.finalizeError,
			claim_token: null,
			claim_expires_at: null,
		} as Record<string, unknown>)
		.eq("id", queueItemId);

	if (values.claimToken) query = query.eq("claim_token", values.claimToken);
	await query;
}

export async function releasePublishingQueueItem(
	queueItemId: string,
	lastError: string,
	options?: { claimToken?: string | null | undefined },
): Promise<void> {
	let query = db()
		.from("auto_post_queue")
		.update({
			status: "pending" satisfies AutoPostQueueStatus,
			pool_status: POOL_AVAILABLE_STATUS,
			account_id: null,
			last_error: lastError,
			claim_token: null,
			claim_expires_at: null,
		} as Record<string, unknown>)
		.eq("id", queueItemId)
		.eq("status", "publishing");

	if (options?.claimToken) query = query.eq("claim_token", options.claimToken);
	await query;
}

export async function reopenQueuedQueueItem(
	queueItemId: string,
): Promise<void> {
	await db()
		.from("auto_post_queue")
		.update({
			status: "pending" satisfies AutoPostQueueStatus,
			pool_status: POOL_AVAILABLE_STATUS,
			schedule_nonce: null,
			qstash_message_id: null,
			claim_token: null,
			claim_expires_at: null,
		} as Record<string, unknown>)
		.eq("id", queueItemId)
		.eq("status", "queued");
}

export async function recoverQueueItemsToPending(
	queueItemIds: string[],
	lastError: string,
	options?: {
		accountId?: string | null | undefined;
		poolStatus?: string | null | undefined;
		retryCountById?: Map<string, number> | undefined;
	},
): Promise<void> {
	for (const queueItemId of queueItemIds) {
		await db()
			.from("auto_post_queue")
			.update({
				status: "pending" satisfies AutoPostQueueStatus,
				pool_status: options?.poolStatus ?? POOL_AVAILABLE_STATUS,
				account_id: options?.accountId ?? null,
				retry_count: options?.retryCountById?.get(queueItemId),
				schedule_nonce: null,
				qstash_message_id: null,
				claim_token: null,
				claim_expires_at: null,
				last_error: lastError,
			} as Record<string, unknown>)
			.eq("id", queueItemId);
	}
}
