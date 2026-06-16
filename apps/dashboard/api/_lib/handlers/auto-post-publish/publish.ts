// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * QStash Delayed Publish Endpoint
 *
 * Called by QStash at the exact scheduled_for time to publish a single post.
 * Auth: QStash signature verification (not user auth).
 *
 * POST /api/auto-post-publish
 * Body: { queueItemId, workspaceId, groupId, ownerId, groupName, accountId? }
 *
 * Account selection: Two paths (Phase 2 rebuild, 2026-04-04):
 *   A) Pre-assigned: accountId set at fill time by accountPlanner.ts → validate & use
 *   B) Legacy fallback: round-robin at publish time for items without account_id
 */

import crypto from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { logger } from "../../logger.js";
import { verifyQStashSignature } from "../../qstash.js";
import { getSupabaseAny } from "../../supabase.js";
import { z } from "../../zodCompat.js";
import { isAutoposterHardDisabled } from "../auto-post/killSwitch.js";
import { deriveAutoposterRuntimeModeFromConfig } from "../auto-post/controlPlane.js";
import {
	autoposterHealthSortValue,
	isAutoposterHealthSuppressed,
} from "../auto-post/accountHealth.js";
import {
	getAccountState,
	getGroupAccountStates,
} from "../auto-post/accountState.js";
import {
	buildMediaReuseSignals,
	buildPublishFingerprint,
	findRecentDuplicateFingerprint,
	findRecentMediaFingerprintAcrossAccounts,
	stampQueueItemFingerprint,
} from "../auto-post/publishFingerprint.js";
import { validateDiscoverabilitySafeContent } from "../../discoverabilitySafety.js";
import { verifyAutopublishGatePassToken } from "../auto-post/gatePassToken.js";
import {
	evaluateQueueProvenance,
	stampQueueProvenance,
} from "../auto-post/provenanceGate.js";
import {
	assignQueueItemAccount,
	cancelQueueItem,
	claimQueueItemForPublish,
	deadLetterQueueItem,
	ensureQueueItemScheduleNonce,
	isClaimableQueueStatus,
	isQueueItemDueForDispatch,
	loadQueueItemForPublish,
	markQueueItemNeedsReconciliation,
	QueueItemLoadError,
	recordPublishAttempt,
	releasePublishingQueueItem,
	requeueQueueItemWithBackoff,
	rescheduleQueueItemForFutureDispatch,
	finishPublishAttempt,
	startPublishAttempt,
} from "../auto-post/queueState.js";
import {
	isActiveWindowNow,
	isPolicyTemporarilyBlocked,
	resolvePublishSchedulePolicy,
	satisfiesPlannedAccountConstraints,
	type GroupScheduleConfig,
	type PlannedAccountConstraints,
	type PublishSchedulePolicy,
} from "./accountSchedulePolicy.js";
import {
	getRemainingPostingCapacity,
	type WarmupCapacityState,
} from "../auto-post/warmupCapacity.js";

const db = () => getSupabaseAny();

function hasInternalCronAuth(req: VercelRequest): boolean {
	const expectedSecret = process.env.CRON_SECRET;
	if (!expectedSecret) return false;
	const actual = req.headers.authorization || "";
	const expected = `Bearer ${expectedSecret}`;
	return (
		actual.length === expected.length &&
		crypto.timingSafeEqual(Buffer.from(actual), Buffer.from(expected))
	);
}

const PublishBodySchema = z.object({
	queueItemId: z.string().min(1),
	workspaceId: z.string().min(1),
	groupId: z.string().min(1),
	ownerId: z.string().min(1),
	groupName: z.string().optional().default(""),
	/** Pre-assigned account from fill-time planner (Phase 2 rebuild) */
	accountId: z.string().optional(),
	/** Authoritative schedule version. Stale QStash messages must not publish. */
	scheduleNonce: z.string().optional(),
});

const LOCAL_RATE_LIMIT_RETRY_MINUTES = 15;
const DAILY_CAP_RETRY_MINUTES = 60;
const LIVE_QUOTA_CACHE_SECONDS = 5 * 60;

function retryAtMinutes(minutes: number): Date {
	return new Date(Date.now() + minutes * 60 * 1000);
}

function getLocalTimeParts(
	date: Date,
	timezone: string,
): {
	hour: number;
	minute: number;
	second: number;
} {
	try {
		const parts = Object.fromEntries(
			new Intl.DateTimeFormat("en-US", {
				timeZone: timezone,
				hour: "2-digit",
				minute: "2-digit",
				second: "2-digit",
				hourCycle: "h23",
			})
				.formatToParts(date)
				.map((part) => [part.type, part.value]),
		);
		return {
			hour: Number(parts.hour),
			minute: Number(parts.minute),
			second: Number(parts.second),
		};
	} catch {
		return {
			hour: date.getUTCHours(),
			minute: date.getUTCMinutes(),
			second: date.getUTCSeconds(),
		};
	}
}

function getNextActiveWindowStart(
	timezone: string,
	activeStart: number,
	from: Date = new Date(),
): Date {
	const { hour, minute, second } = getLocalTimeParts(from, timezone);
	let hoursUntilOpen = activeStart - hour;
	if (hoursUntilOpen <= 0) hoursUntilOpen += 24;
	const msUntilCurrentHour =
		hoursUntilOpen * 60 * 60 * 1000 - minute * 60 * 1000 - second * 1000;
	const jitterMs = Math.floor(Math.random() * 10 * 60 * 1000);
	return new Date(
		from.getTime() + Math.max(60_000, msUntilCurrentHour) + jitterMs,
	);
}

function readPlannedAccountConstraints(
	metadata: unknown,
): PlannedAccountConstraints | null {
	if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
		return null;
	}
	const planned = (metadata as Record<string, unknown>).planned_account;
	if (!planned || typeof planned !== "object" || Array.isArray(planned)) {
		return null;
	}
	const record = planned as Record<string, unknown>;
	const accountWindow = record.accountWindow;
	return {
		accountId: typeof record.accountId === "string" ? record.accountId : null,
		candidateAccountIds: Array.isArray(record.candidateAccountIds)
			? record.candidateAccountIds.filter(
					(value): value is string =>
						typeof value === "string" && value.trim().length > 0,
				)
			: null,
		accountWindow:
			accountWindow &&
			typeof accountWindow === "object" &&
			!Array.isArray(accountWindow)
				? {
						start:
							typeof (accountWindow as Record<string, unknown>).start ===
							"number"
								? ((accountWindow as Record<string, unknown>).start as number)
								: null,
						end:
							typeof (accountWindow as Record<string, unknown>).end === "number"
								? ((accountWindow as Record<string, unknown>).end as number)
								: null,
					}
				: null,
		minIntervalMinutes:
			typeof record.minIntervalMinutes === "number"
				? record.minIntervalMinutes
				: null,
		timezone: typeof record.timezone === "string" ? record.timezone : null,
	};
}

function publishCapacityBlockReason(reason: string): string {
	if (reason.includes("suppressed")) return "suppressed_cap_zero";
	if (reason.includes("held")) return "held_cap_exceeded";
	if (reason.includes("warmup")) return "warmup_cap_exceeded";
	if (reason.includes("reduce")) return "reduced_cap_exceeded";
	return `${reason}_exceeded`;
}

async function getPublishCapacityBlock(input: {
	workspaceId: string;
	groupId: string;
	queueItemId: string;
	accountId: string;
	state?: WarmupCapacityState | null | undefined;
	policy: PublishSchedulePolicy;
	now?: Date | undefined;
}): Promise<{
	blocked: boolean;
	reason: string;
	cap: number | null;
	used: number;
	remaining: number | null;
}> {
	const capacity = await getRemainingPostingCapacity({
		workspaceId: input.workspaceId,
		groupId: input.groupId,
		accountId: input.accountId,
		timezone: input.policy.timezone,
		state: input.state,
		now: input.now,
		excludeQueueItemId: input.queueItemId,
	});
	const blocked = capacity.remaining !== null && capacity.remaining <= 0;
	return {
		blocked,
		reason: blocked
			? publishCapacityBlockReason(capacity.reason)
			: capacity.reason,
		cap: capacity.cap,
		used: capacity.used,
		remaining: capacity.remaining,
	};
}

async function loadPublishSchedulePolicyForAccount(input: {
	accountId: string;
	groupId: string;
	groupConfig: GroupScheduleConfig | null;
}): Promise<PublishSchedulePolicy> {
	const [accountScheduleResult, legacyOverrideResult] = await Promise.all([
		db()
			.from("account_schedule")
			.select(
				"active_hours_start, active_hours_end, timezone, min_interval_minutes, paused, status, blocked_until",
			)
			.eq("group_id", input.groupId)
			.eq("account_id", input.accountId)
			.maybeSingle(),
		db()
			.from("auto_post_account_overrides")
			.select("overrides")
			.eq("group_id", input.groupId)
			.eq("account_id", input.accountId)
			.maybeSingle(),
	]);
	const legacyOverride =
		legacyOverrideResult.data?.overrides &&
		typeof legacyOverrideResult.data.overrides === "object" &&
		!Array.isArray(legacyOverrideResult.data.overrides)
			? (legacyOverrideResult.data.overrides as Record<string, unknown>)
			: null;
	return resolvePublishSchedulePolicy({
		accountSchedule: accountScheduleResult.data ?? null,
		legacyOverride,
		groupConfig: input.groupConfig,
	});
}

function isRateLimitErrorMessage(error: string): boolean {
	const lower = error.toLowerCase();
	return (
		lower.includes("rate limit") ||
		lower.includes("rate limited") ||
		lower.includes("too many") ||
		lower.includes("429") ||
		lower.includes("quota")
	);
}

async function requeueWithBackoff(
	queueItemId: string,
	reason: string,
	retryAt: Date,
	retryCount?: number,
	claimToken?: string | null,
): Promise<void> {
	await requeueQueueItemWithBackoff(queueItemId, reason, retryAt, {
		accountId: null,
		poolStatus: "available",
		...(retryCount !== undefined ? { retryCount } : {}),
		...(claimToken ? { claimToken } : {}),
	});
}

async function finalizeAutoposterPublish(values: {
	queueItemId: string;
	claimToken: string;
	threadId: string;
	accountId: string;
	workspaceId: string;
	groupId: string;
	content: string;
	mediaUrls: string[];
	sourceType: string;
	publishedAt: string;
}): Promise<{ postId: string; inserted: boolean }> {
	const { data, error } = await getSupabaseAny().rpc(
		"finalize_autoposter_publish",
		{
			p_queue_item_id: values.queueItemId,
			p_claim_token: values.claimToken,
			p_threads_post_id: values.threadId,
			p_account_id: values.accountId,
			p_workspace_id: values.workspaceId,
			p_group_id: values.groupId,
			p_content: values.content,
			p_media_urls: values.mediaUrls,
			p_source_type: values.sourceType,
			p_published_at: values.publishedAt,
		},
	);

	if (error) {
		throw new Error(
			`finalize_autoposter_publish failed: ${String(error.message ?? error)}`,
		);
	}

	const row = Array.isArray(data) ? data[0] : data;
	if (!row?.post_id) {
		throw new Error("finalize_autoposter_publish returned no post_id");
	}

	return {
		postId: String(row.post_id),
		inserted: row.inserted === true,
	};
}

async function getThreadsLivePublishingQuota(account: {
	id: string;
	threads_user_id?: string | null | undefined;
	threads_access_token_encrypted?: string | null | undefined;
}): Promise<{
	exhausted: boolean;
	used: number;
	limit: number;
	retryAt: Date | null;
} | null> {
	if (!account.threads_user_id || !account.threads_access_token_encrypted) {
		return null;
	}

	const cacheKey = `threads-live-quota:${account.id}`;
	try {
		const { getRedis } = await import("../../redis.js");
		const redis = getRedis();
		const cached = await redis.get(cacheKey);
		if (cached) {
			const parsed =
				typeof cached === "string"
					? JSON.parse(cached)
					: (cached as Record<string, unknown>);
			return {
				exhausted: parsed.exhausted === true,
				used: Number(parsed.used ?? 0),
				limit: Number(parsed.limit ?? 250),
				retryAt: parsed.retryAt ? new Date(parsed.retryAt as string) : null,
			};
		}
	} catch {
		/* cache miss/failure falls through to live check */
	}

	try {
		const { decrypt } = await import("../../encryption.js");
		const accessToken = decrypt(account.threads_access_token_encrypted);
		const url = `https://graph.threads.net/v1.0/${account.threads_user_id}/threads_publishing_limit?fields=quota_usage,config`;
		const response = await fetch(url, {
			headers: { Authorization: `Bearer ${accessToken}` },
			signal: AbortSignal.timeout(8000),
		});
		const data = await response.json();
		if (!response.ok || data.error) {
			logger.warn("[auto-post-publish] Live Threads quota check failed", {
				accountId: account.id,
				status: response.status,
				error: data.error?.message ?? null,
			});
			return null;
		}
		const quotaData = data.data?.[0] || data;
		const used = Number(quotaData.quota_usage ?? 0);
		const limit = Number(quotaData.config?.quota_total ?? 250);
		const durationSeconds = Number(quotaData.config?.quota_duration ?? 86400);
		const exhausted =
			Number.isFinite(used) && Number.isFinite(limit) && used >= limit;
		const retryAt = exhausted
			? new Date(Date.now() + Math.min(durationSeconds, 86400) * 1000)
			: null;
		const result = { exhausted, used, limit, retryAt };

		try {
			const { getRedis } = await import("../../redis.js");
			await getRedis().set(
				cacheKey,
				JSON.stringify({
					exhausted,
					used,
					limit,
					retryAt: retryAt?.toISOString() ?? null,
				}),
				{ ex: LIVE_QUOTA_CACHE_SECONDS },
			);
		} catch {
			/* cache best-effort */
		}

		return result;
	} catch (err) {
		logger.warn("[auto-post-publish] Live Threads quota check threw", {
			accountId: account.id,
			error: err instanceof Error ? err.message : String(err),
		});
		return null;
	}
}

// Self-reply threads removed — replaced by delayed CTA reply cron (cta-reply-worker.ts)
// CTA replies are posted 12-24h after the original post to ride its distribution.

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST") {
		logger.warn("[auto-post-publish] Method not allowed", {
			method: req.method,
		});
		const { apiError } = await import("../../apiResponse.js");
		return apiError(res, 405, "Method not allowed");
	}

	const isInternalRecovery = hasInternalCronAuth(req);
	if (!isInternalRecovery && !(await verifyQStashSignature(req, res))) {
		logger.warn("[auto-post-publish] QStash signature verification failed", {
			bodyKeys: req.body
				? Object.keys(req.body as Record<string, unknown>)
				: [],
			userAgent: req.headers["user-agent"] || null,
			upstashSignaturePresent: Boolean(req.headers["upstash-signature"]),
		});
		return;
	}

	const globalStart = Date.now();
	const parsed = PublishBodySchema.safeParse(req.body);
	if (!parsed.success) {
		logger.warn("[auto-post-publish] Invalid body — parse failed", {
			errors: parsed.error.issues.map(
				(i) => `${i.path.join(".")}: ${i.message}`,
			),
			bodyKeys: req.body
				? Object.keys(req.body as Record<string, unknown>)
				: [],
		});
		return res
			.status(400)
			.json({ ok: false, skipped: true, reason: "invalid_body" });
	}
	const {
		queueItemId,
		workspaceId,
		groupId,
		ownerId,
		groupName,
		accountId: preAssignedAccountId,
		scheduleNonce: requestedScheduleNonce,
	} = parsed.data;
	const traceId = (req.body as Record<string, unknown>)?.traceId as
		| string
		| undefined;
	const parentRunId = (req.body as Record<string, unknown>)?.parentRunId as
		| string
		| undefined;

	if (isAutoposterHardDisabled()) {
		logger.warn("[auto-post-publish] Skip global hard disable", {
			queueItemId,
			traceId,
			groupId,
			workspaceId,
		});
		return res
			.status(200)
			.json({ ok: true, skipped: true, reason: "hard_disabled" });
	}

	const { logRun } = await import("../../autopilotRunLogger.js");
	const runLogger = await logRun({
		userId: ownerId,
		runType: "publish",
		accountId: preAssignedAccountId ?? null,
		trigger: parentRunId ? "replay" : isInternalRecovery ? "cron" : "cron",
		parentRunId: parentRunId ?? null,
		metadata: {
			queueItemId,
			workspaceId,
			groupId,
			groupName,
			traceId: traceId ?? null,
			authPath: isInternalRecovery ? "cron" : "qstash",
		},
	});

	// Hoisted so the outer catch can release the per-account publish lock
	// even if an unhandled exception throws between acquisition and the
	// success/failure paths inside the try block.
	let selectedAccountLock: { release: () => Promise<void> } | null = null;
	let queueClaimToken: string | null = null;
	let publishAttemptId: string | null = null;
	const releaseSelectedAccountLock = async () => {
		if (!selectedAccountLock) return;
		try {
			await selectedAccountLock.release();
		} catch {
			/* TTL fallback */
		} finally {
			selectedAccountLock = null;
		}
	};

	try {
		// 1. Load queue item — only publish if still pending
		const loadStart = Date.now();
		let item: Awaited<ReturnType<typeof loadQueueItemForPublish>>;
		try {
			item = await loadQueueItemForPublish(queueItemId);
		} catch (err) {
			const errMsg = err instanceof Error ? err.message : String(err);
			await runLogger.logStep({
				name: "load_queue_item",
				status: "failed",
				inputs: {
					queueItemId,
					workspaceId,
					groupId,
					preAssignedAccountId: preAssignedAccountId ?? null,
				},
				error: errMsg,
				durationMs: Date.now() - loadStart,
			});
			await runLogger.finishRun("failed", {
				reason: "load_error",
				queueItemId,
				workspaceId,
				groupId,
			});
			if (err instanceof QueueItemLoadError) {
				return res
					.status(503)
					.json({ ok: false, error: "Queue item load failed" });
			}
			throw err;
		}
		await runLogger.logStep({
			name: "load_queue_item",
			status: item ? "success" : "failed",
			inputs: {
				queueItemId,
				workspaceId,
				groupId,
				preAssignedAccountId: preAssignedAccountId ?? null,
			},
			outputs: item
				? {
						id: item.id,
						status: item.status,
						accountId: item.account_id ?? null,
						hasMedia: Boolean(item.media_urls?.length),
						retryCount: item.retry_count ?? 0,
					}
				: null,
			error: item ? null : "Queue item not found",
			durationMs: Date.now() - loadStart,
		});
		if (!item) {
			logger.info("[auto-post-publish] Skip missing queue item", {
				queueItemId,
				traceId,
				groupId,
			});
			await runLogger.finishRun("failed", {
				reason: "not_found",
				queueItemId,
				workspaceId,
				groupId,
			});
			return res
				.status(200)
				.json({ ok: true, skipped: true, reason: "not_found" });
		}
		const plannedAccountConstraints = readPlannedAccountConstraints(
			item.metadata,
		);

		// Only pending/queued rows are claimable. Published/cancelled/dead rows,
		// and in-flight publishing rows, exit cleanly instead of double-posting.
		if (!isClaimableQueueStatus(item.status)) {
			logger.info("[auto-post-publish] Skip terminal queue item", {
				queueItemId,
				traceId,
				groupId,
				status: item.status,
			});
			await runLogger.finishRun("partial", {
				reason: item.status,
				queueItemId,
				workspaceId,
				groupId,
			});
			return res
				.status(200)
				.json({ ok: true, skipped: true, reason: item.status });
		}

		if (item.schedule_nonce && requestedScheduleNonce !== item.schedule_nonce) {
			logger.info("[auto-post-publish] Skip stale schedule nonce", {
				queueItemId,
				traceId,
				groupId,
				requestedScheduleNonce: requestedScheduleNonce ?? null,
				currentScheduleNonce: item.schedule_nonce,
			});
			await runLogger.finishRun("partial", {
				reason: "stale_schedule_nonce",
				queueItemId,
				workspaceId,
				groupId,
			});
			return res.status(200).json({
				ok: true,
				skipped: true,
				reason: "stale_schedule_nonce",
			});
		}

		if (!isQueueItemDueForDispatch(item.scheduled_for, item.next_retry_at)) {
			logger.info("[auto-post-publish] Skip queue item not due", {
				queueItemId,
				traceId,
				groupId,
				scheduledFor: item.scheduled_for,
				nextRetryAt: item.next_retry_at,
			});
			await runLogger.finishRun("partial", {
				reason: "not_due",
				queueItemId,
				workspaceId,
				groupId,
			});
			return res
				.status(200)
				.json({ ok: true, skipped: true, reason: "not_due" });
		}

		logger.info("[auto-post-publish] Start", {
			queueItemId,
			traceId,
			groupId,
			status: item.status,
			authPath: isInternalRecovery ? "cron" : "qstash",
		});

		// 2. Check autoposter + group still enabled
		const { data: wsConfig } = await db()
			.from("auto_post_config")
			.select("is_enabled, group_mode_enabled, enable_ai_queue_fill")
			.eq("workspace_id", workspaceId)
			.maybeSingle();

		// Manual posts bypass master switch — they're explicit user intent, not AI fill
		const isManual = item.source_type === "manual";

		const runtimeMode = deriveAutoposterRuntimeModeFromConfig(
			wsConfig,
			isAutoposterHardDisabled(),
		);

		if (
			!isManual &&
			runtimeMode !== "running" &&
			runtimeMode !== "fill_disabled"
		) {
			logger.info("[auto-post-publish] Skip disabled workspace", {
				queueItemId,
				traceId,
				groupId,
				workspaceId,
				isEnabled: wsConfig?.is_enabled ?? null,
				groupModeEnabled: wsConfig?.group_mode_enabled ?? null,
				runtimeMode,
			});
			await cancelQueueItem(queueItemId, "Autoposter disabled at publish time");
			return res
				.status(200)
				.json({ ok: true, result: "cancelled", reason: "disabled" });
		}

		const { data: groupConfig } = await db()
			.from("auto_post_group_config")
			.select(
				"enabled, timezone, active_hours_start, active_hours_end, post_on_weekends, min_interval_minutes, posts_per_account_per_day",
			)
			.eq("workspace_id", workspaceId)
			.eq("group_id", groupId)
			.maybeSingle();

		if (!isManual && !groupConfig?.enabled) {
			logger.info("[auto-post-publish] Skip disabled group", {
				queueItemId,
				traceId,
				groupId,
				workspaceId,
				groupEnabled: groupConfig?.enabled ?? null,
			});
			await cancelQueueItem(queueItemId, "Group disabled at publish time");
			return res
				.status(200)
				.json({ ok: true, result: "cancelled", reason: "group_disabled" });
		}

		// 2b. Per-account active hours check at publish time
		// The account planner skips active hours (skipActiveHours: true) expecting
		// the publish worker to enforce them. Check here before claiming the item.
		if (!isManual) {
			const effectiveAccountId = preAssignedAccountId || item.account_id;
			if (effectiveAccountId) {
				const schedulePolicy = await loadPublishSchedulePolicyForAccount({
					accountId: effectiveAccountId,
					groupId,
					groupConfig,
				});
				const currentHour = getLocalTimeParts(
					new Date(),
					schedulePolicy.timezone,
				).hour;
				const effectiveStart = schedulePolicy.activeHoursStart;
				const effectiveEnd = schedulePolicy.activeHoursEnd;
				const inWindow =
					!isPolicyTemporarilyBlocked(schedulePolicy, new Date()) &&
					isActiveWindowNow(schedulePolicy, new Date());

				if (!inWindow) {
					// Calculate when the active window next opens and reschedule
					const rescheduleAt = getNextActiveWindowStart(
						schedulePolicy.timezone,
						schedulePolicy.activeHoursStart,
					);

					try {
						const { getQStashClient } = await import("../../qstash.js");
						const { RETRIES, getFailureCallbackUrl, getRequiredAppBaseUrl } =
							await import("../../qstashDefaults.js");
						const { recordInfraEvent } = await import(
							"../../infraTelemetry.js"
						);
						const qstash = getQStashClient();
						const baseUrl = getRequiredAppBaseUrl();
						const failureCb = getFailureCallbackUrl();
						const scheduleNonce = `resched-${queueItemId}-${rescheduleAt.getTime()}`;

						const persistedScheduleNonce = await ensureQueueItemScheduleNonce(
							queueItemId,
							scheduleNonce,
						);

						const result = await qstash.publishJSON({
							url: `${baseUrl}/api/auto-post-publish`,
							body: {
								queueItemId,
								workspaceId,
								groupId,
								ownerId,
								groupName,
								accountId: effectiveAccountId,
								scheduleNonce: persistedScheduleNonce,
								traceId: traceId ?? `resched-${queueItemId}-${Date.now()}`,
							},
							retries: RETRIES.CRITICAL,
							notBefore: Math.floor(rescheduleAt.getTime() / 1000),
							deduplicationId: `auto-post-${queueItemId}-${persistedScheduleNonce}`,
							failureCallback: failureCb,
						});
						await rescheduleQueueItemForFutureDispatch(queueItemId, {
							accountId: effectiveAccountId,
							scheduledFor: rescheduleAt.toISOString(),
							scheduleNonce: persistedScheduleNonce,
							qstashMessageId: result.messageId,
						});
						await recordInfraEvent("autopost-outside-window-reschedule", {
							queueItemId,
							scheduleNonce: persistedScheduleNonce,
							qstashMessageId: result.messageId,
							accountId: effectiveAccountId,
							groupId,
							workspaceId,
						});
					} catch (rescheduleErr) {
						logger.warn(
							"[auto-post-publish] Failed to requeue outside-window item",
							{
								queueItemId,
								accountId: effectiveAccountId,
								error:
									rescheduleErr instanceof Error
										? rescheduleErr.message
										: String(rescheduleErr),
							},
						);
						await rescheduleQueueItemForFutureDispatch(queueItemId, {
							accountId: effectiveAccountId,
							scheduledFor: rescheduleAt.toISOString(),
							lastError:
								"Outside active window — rescheduled without QStash dispatch",
						});
					}

					logger.info("[auto-post-publish] Rescheduled outside active window", {
						queueItemId,
						accountId: effectiveAccountId,
						groupId,
						currentHour,
						effectiveStart,
						effectiveEnd,
						rescheduledTo: rescheduleAt.toISOString(),
					});

					return res.status(200).json({
						ok: true,
						result: "rescheduled",
						reason: "outside_active_window",
					});
				}
			}
		}

		// 3. Atomic claim — prevent double-publish from cron reconciliation
		// The schedule nonce and due-time predicates make stale delayed QStash
		// messages harmless after a row is rescheduled.
		queueClaimToken = await claimQueueItemForPublish(queueItemId, {
			scheduleNonce: requestedScheduleNonce ?? null,
		});
		if (!queueClaimToken) {
			logger.warn("[auto-post-publish] Claim failed", {
				queueItemId,
				traceId,
				groupId,
				workspaceId,
				status: item.status,
				poolStatus: item.pool_status ?? null,
				requestedScheduleNonce: requestedScheduleNonce ?? null,
				scheduleNonce: item.schedule_nonce,
				scheduledFor: item.scheduled_for,
				nextRetryAt: item.next_retry_at,
				qstashMessageId: item.qstash_message_id,
			});
			await recordPublishAttempt({
				queueItemId,
				userId: ownerId,
				workspaceId,
				groupId,
				accountId: preAssignedAccountId ?? item.account_id ?? null,
				result: "claim_failed",
				errorCode: "claim_failed",
				errorMessage:
					"Atomic claim did not match pending/queued due queue item predicates",
				metadata: {
					traceId: traceId ?? null,
					requestedScheduleNonce: requestedScheduleNonce ?? null,
					currentScheduleNonce: item.schedule_nonce,
					status: item.status,
					poolStatus: item.pool_status ?? null,
				},
			});
			await runLogger.finishRun("partial", {
				reason: "claim_failed",
				queueItemId,
				workspaceId,
				groupId,
			});
			return res
				.status(200)
				.json({ ok: true, skipped: true, reason: "claim_failed" });
		}
		publishAttemptId = await startPublishAttempt({
			queueItemId,
			userId: ownerId,
			workspaceId,
			groupId,
			claimToken: queueClaimToken,
			accountId: preAssignedAccountId ?? item.account_id ?? null,
			metadata: {
				traceId: traceId ?? null,
				authPath: isInternalRecovery ? "cron" : "qstash",
				requestedScheduleNonce: requestedScheduleNonce ?? null,
				queueScheduleNonce: item.schedule_nonce,
			},
		});
		const provenanceCheck = evaluateQueueProvenance(item);
		await stampQueueProvenance(queueItemId, provenanceCheck);
		if (provenanceCheck.decision === "manual_allowed") {
			await recordPublishAttempt({
				queueItemId,
				userId: ownerId,
				workspaceId,
				groupId,
				claimToken: queueClaimToken,
				accountId: preAssignedAccountId ?? item.account_id ?? null,
				result: "provenance_manual_allowed",
				metadata: { sourceType: item.source_type },
			});
		} else if (provenanceCheck.decision === "missing") {
			await db()
				.from("auto_post_queue")
				.update({
					status: "needs_review",
					pool_status: "available",
					last_error: `Missing publish provenance: ${provenanceCheck.reasons.join(", ")}`,
					claim_token: null,
					claim_expires_at: null,
					provenance_status: "missing",
					provenance_error: provenanceCheck.reasons.join(","),
				} as Record<string, unknown>)
				.eq("id", queueItemId)
				.eq("claim_token", queueClaimToken);
			await finishPublishAttempt(publishAttemptId, {
				result: "provenance_missing_needs_review",
				accountId: preAssignedAccountId ?? item.account_id ?? null,
				errorCode: "missing_provenance",
				errorMessage: provenanceCheck.reasons.join(","),
				metadata: { fields: provenanceCheck.fields },
			});
			await runLogger.finishRun("partial", {
				reason: "missing_provenance",
				queueItemId,
				workspaceId,
				groupId,
				provenanceErrors: provenanceCheck.reasons,
			});
			return res.status(200).json({
				ok: true,
				result: "provenance_missing_needs_review",
				reasons: provenanceCheck.reasons,
			});
		}

		// 4. Account selection — two paths:
		//    A) Pre-assigned (Phase 2 rebuild): account_id set at fill time → validate & use
		//    B) Legacy fallback: round-robin at publish time (items without account_id)

		const { acquirePublishLock } = await import("../../publishLock.js");

		// biome-ignore lint/suspicious/noExplicitAny: Supabase partial select
		let account: any = null;
		const selectedIdx = 0;

		// Resolve pre-assigned account: prefer QStash body, fall back to DB column
		const resolvedPreAssignedId = preAssignedAccountId || item.account_id;
		const allowShadowbannedPreassigned = !!resolvedPreAssignedId;

		if (resolvedPreAssignedId) {
			// ── Path A: Pre-assigned account (fast path) ──
			const preAssignedState = await getAccountState(resolvedPreAssignedId);
			const { data: preAssigned } = await db()
				.from("accounts")
				.select(
					"id, username, threads_user_id, threads_access_token_encrypted, is_retired, needs_reauth, is_active, is_shadowbanned, status",
				)
				.eq("id", resolvedPreAssignedId)
				.maybeSingle();

			if (
				preAssigned &&
				!preAssigned.is_retired &&
				!preAssigned.needs_reauth &&
				(allowShadowbannedPreassigned || !preAssigned.is_shadowbanned) &&
				preAssigned.is_active !== false &&
				(isManual ||
					!isAutoposterHealthSuppressed(
						preAssignedState?.account_health_score ?? null,
					))
			) {
				// Acquire publish lock (prevents TOCTOU race with concurrent publishes)
				const publishLock = await acquirePublishLock(preAssigned.id);
				if (publishLock.acquired) {
					// Burst guard — no account posts twice in 30 min
					const { count: recentCount } = await db()
						.from("auto_post_queue")
						.select("id", { count: "exact", head: true })
						.eq("account_id", preAssigned.id)
						.eq("status", "published")
						.gte(
							"posted_at",
							new Date(Date.now() - 30 * 60 * 1000).toISOString(),
						);
					if ((recentCount ?? 0) === 0) {
						account = preAssigned;
						selectedAccountLock = publishLock;
						logger.info("[publish] Using pre-assigned account", {
							queueItemId,
							accountId: preAssigned.id,
							username: preAssigned.username,
						});
					} else {
						await publishLock.release();
						logger.info(
							"[publish] Pre-assigned account burst guard hit, falling back",
							{
								queueItemId,
								accountId: preAssigned.id,
							},
						);
					}
				} else {
					logger.info("[publish] Pre-assigned account locked, falling back", {
						queueItemId,
						accountId: preAssigned.id,
					});
				}
			} else {
				logger.info(
					"[publish] Pre-assigned account invalid/inactive, falling back",
					{
						queueItemId,
						accountId: resolvedPreAssignedId,
						exists: !!preAssigned,
						retired: preAssigned?.is_retired,
						needsReauth: preAssigned?.needs_reauth,
						shadowbanned: preAssigned?.is_shadowbanned,
						accountHealthScore: preAssignedState?.account_health_score ?? null,
					},
				);
			}
		}

		// ── Path B: Publish-time account assignment fallback ──
		// If pre-assigned account failed or no account_id at all, pick an active
		// account from the group that still satisfies schedule and cap constraints.
		let scheduleBlockedFallback:
			| {
					accountId: string;
					policy: PublishSchedulePolicy;
				}
			| null = null;
		if (!account && groupId) {
			try {
				const { data: groupRow } = await db()
					.from("account_groups")
					.select("account_ids")
					.eq("id", groupId)
					.maybeSingle();
				const groupAccountIds = (groupRow?.account_ids || []) as string[];

				if (groupAccountIds.length > 0) {
					const { data: candidates } = await db()
						.from("accounts")
						.select(
							"id, username, threads_user_id, threads_access_token_encrypted, is_retired, needs_reauth, is_active, is_shadowbanned, status",
						)
						.in("id", groupAccountIds)
						.not("threads_access_token_encrypted", "is", null)
						.or("status.is.null,status.neq.suspended");

					const viable = (candidates || []).filter(
						(a: Record<string, unknown>) =>
							!a.is_retired &&
							!a.needs_reauth &&
							!a.is_shadowbanned &&
							a.is_active !== false,
					);
					const fallbackStates = await getGroupAccountStates(groupId);
					const fallbackStateMap = new Map(
						fallbackStates.map((state) => [state.account_id, state]),
					);
					const sortedViable = viable
						.filter(
							(candidate: Record<string, unknown>) =>
								isManual ||
								!isAutoposterHealthSuppressed(
									fallbackStateMap.get(candidate.id as string)
										?.account_health_score ?? null,
								),
						)
						.sort(
							(a: Record<string, unknown>, b: Record<string, unknown>) =>
								autoposterHealthSortValue(
									fallbackStateMap.get(b.id as string)?.account_health_score,
								) -
								autoposterHealthSortValue(
									fallbackStateMap.get(a.id as string)?.account_health_score,
								),
						);

					// Try healthiest eligible accounts first until one acquires publish lock.
					for (const candidate of sortedViable) {
						const candidatePolicy = await loadPublishSchedulePolicyForAccount({
							accountId: candidate.id as string,
							groupId,
							groupConfig,
						});
						if (
							isPolicyTemporarilyBlocked(candidatePolicy, new Date()) ||
							!isActiveWindowNow(candidatePolicy, new Date()) ||
							!satisfiesPlannedAccountConstraints({
								selectedAccountId: candidate.id as string,
								plannedAccount: plannedAccountConstraints,
								selectedPolicy: candidatePolicy,
								now: new Date(),
							})
						) {
							logger.info("[publish] Candidate skipped by account schedule", {
								queueItemId,
								accountId: candidate.id,
								scheduleSource: candidatePolicy.source,
								plannedAccountId: plannedAccountConstraints?.accountId ?? null,
							});
							if (!scheduleBlockedFallback) {
								scheduleBlockedFallback = {
									accountId: candidate.id as string,
									policy: candidatePolicy,
								};
							}
							continue;
						}
						const candidateCapacity = await getPublishCapacityBlock({
							workspaceId,
							groupId,
							queueItemId,
							accountId: candidate.id as string,
							state: fallbackStateMap.get(candidate.id as string),
							policy: candidatePolicy,
						});
						if (candidateCapacity.blocked) {
							logger.info("[publish] Candidate skipped by warm-up capacity", {
								queueItemId,
								accountId: candidate.id,
								reason: candidateCapacity.reason,
								cap: candidateCapacity.cap,
								used: candidateCapacity.used,
								remaining: candidateCapacity.remaining,
							});
							continue;
						}
						const publishLock = await acquirePublishLock(candidate.id);
						if (!publishLock.acquired) continue;
						// Burst guard — no double-post in 30 min
						const { count: recentCount } = await db()
							.from("auto_post_queue")
							.select("id", { count: "exact", head: true })
							.eq("account_id", candidate.id)
							.eq("status", "published")
							.gte(
								"posted_at",
								new Date(Date.now() - 30 * 60 * 1000).toISOString(),
							);
						if ((recentCount ?? 0) > 0) {
							await publishLock.release();
							continue;
						}
						account = candidate;
						selectedAccountLock = publishLock;
						// Update the queue item with the assigned account for tracking
						await assignQueueItemAccount(queueItemId, candidate.id);
						logger.info("[publish] Path B: assigned account at publish time", {
							queueItemId,
							accountId: candidate.id,
							username: candidate.username,
						});
						break;
					}
				}
			} catch (fallbackErr) {
				logger.warn("[publish] Path B fallback failed", {
					queueItemId,
					error:
						fallbackErr instanceof Error
							? fallbackErr.message
							: String(fallbackErr),
				});
			}
		}

		// No account available after both paths — requeue with progressive
		// backoff or dead-letter.  The fill-time planner ignores active hours
		// (skipActiveHours: true) so an item may land outside every account's
		// window.  3 retries × 5 min = 15 min, which can't bridge a 6-hour
		// window gap.  Use 6 retries with progressive backoff (5m → 15m →
		// 30m → 1h → 2h → 4h ≈ 8h total) to cover overnight gaps.
		if (!account) {
			if (scheduleBlockedFallback) {
				const rescheduleAt = getNextActiveWindowStart(
					scheduleBlockedFallback.policy.timezone,
					scheduleBlockedFallback.policy.activeHoursStart,
				);
				await requeueWithBackoff(
					queueItemId,
					"outside_active_window",
					rescheduleAt,
					(item.retry_count || 0) + 1,
					queueClaimToken,
				);
				await finishPublishAttempt(publishAttemptId, {
					result: "requeued",
					accountId: scheduleBlockedFallback.accountId,
					errorCode: "outside_active_window",
					errorMessage: "No fallback account satisfied active-window constraints",
				});
				await runLogger.finishRun("partial", {
					reason: "outside_active_window",
					queueItemId,
					workspaceId,
					groupId,
				});
				return res.status(200).json({
					ok: true,
					result: "rescheduled",
					reason: "outside_active_window",
				});
			}
			const retries = (item.retry_count || 0) + 1;
			const reason = resolvedPreAssignedId
				? "pre_assigned_account_unavailable"
				: "no_account_assigned";

			logger.warn("[publish] No account available after Path A + B", {
				queueItemId,
				reason,
				preAssignedId: resolvedPreAssignedId,
				retryCount: retries,
			});

			const MAX_NO_ACCOUNT_RETRIES = 6;
			if (retries >= MAX_NO_ACCOUNT_RETRIES) {
				await deadLetterQueueItem(
					queueItemId,
					`${reason} after ${retries} attempts`,
					{ claimToken: queueClaimToken },
				);
				await finishPublishAttempt(publishAttemptId, {
					result: "dead_letter",
					accountId: resolvedPreAssignedId ?? null,
					errorCode: reason,
					errorMessage: `${reason} after ${retries} attempts`,
				});
				await runLogger.logStep({
					name: "media_prep",
					status: "skipped",
					inputs: { queueItemId },
					outputs: { reason },
					durationMs: 0,
				});
				await runLogger.finishRun("failed", {
					reason,
					queueItemId,
					workspaceId,
					groupId,
				});
				return res
					.status(200)
					.json({ ok: true, result: "dead_letter", reason });
			}

			// Progressive backoff: 5m, 15m, 30m, 1h, 2h, 4h
			const backoffMinutes = [5, 15, 30, 60, 120, 240];
			const delayMs =
				(backoffMinutes[retries - 1] ??
					backoffMinutes[backoffMinutes.length - 1]!) *
				60 *
				1000;
			const rescheduleTime = new Date(Date.now() + delayMs).toISOString();
			await requeueWithBackoff(
				queueItemId,
				`${reason} (attempt ${retries}/${MAX_NO_ACCOUNT_RETRIES}, next in ${backoffMinutes[retries - 1] ?? 240}m)`,
				new Date(rescheduleTime),
				retries,
				queueClaimToken,
			);
			await finishPublishAttempt(publishAttemptId, {
				result: "requeued",
				accountId: resolvedPreAssignedId ?? null,
				errorCode: reason,
				errorMessage: `${reason} (attempt ${retries}/${MAX_NO_ACCOUNT_RETRIES})`,
			});
			await runLogger.finishRun("partial", {
				reason,
				queueItemId,
				workspaceId,
				groupId,
				retryCount: retries,
			});
			return res.status(200).json({ ok: true, result: "rescheduled", reason });
		}

		if (!isManual) {
			const schedulePolicy = await loadPublishSchedulePolicyForAccount({
				accountId: account.id,
				groupId,
				groupConfig,
			});
			const currentHour = getLocalTimeParts(
				new Date(),
				schedulePolicy.timezone,
			).hour;
			const effectiveStart = schedulePolicy.activeHoursStart;
			const effectiveEnd = schedulePolicy.activeHoursEnd;

			if (
				isPolicyTemporarilyBlocked(schedulePolicy, new Date()) ||
				!isActiveWindowNow(schedulePolicy, new Date())
			) {
				await releaseSelectedAccountLock();
				const rescheduleAt = getNextActiveWindowStart(
					schedulePolicy.timezone,
					schedulePolicy.activeHoursStart,
				);

				try {
					const { getQStashClient } = await import("../../qstash.js");
					const { RETRIES, getFailureCallbackUrl, getRequiredAppBaseUrl } =
						await import("../../qstashDefaults.js");
					const { recordInfraEvent } = await import("../../infraTelemetry.js");
					const qstash = getQStashClient();
					const baseUrl = getRequiredAppBaseUrl();
					const scheduleNonce = `resched-${queueItemId}-${rescheduleAt.getTime()}`;
					const persistedScheduleNonce = await ensureQueueItemScheduleNonce(
						queueItemId,
						scheduleNonce,
					);
					const result = await qstash.publishJSON({
						url: `${baseUrl}/api/auto-post-publish`,
						body: {
							queueItemId,
							workspaceId,
							groupId,
							ownerId,
							groupName,
							accountId: account.id,
							scheduleNonce: persistedScheduleNonce,
							traceId: traceId ?? `resched-${queueItemId}-${Date.now()}`,
						},
						retries: RETRIES.CRITICAL,
						notBefore: Math.floor(rescheduleAt.getTime() / 1000),
						deduplicationId: `auto-post-${queueItemId}-${persistedScheduleNonce}`,
						failureCallback: getFailureCallbackUrl(),
					});
					await rescheduleQueueItemForFutureDispatch(queueItemId, {
						accountId: account.id,
						scheduledFor: rescheduleAt.toISOString(),
						scheduleNonce: persistedScheduleNonce,
						qstashMessageId: result.messageId,
					});
					await recordInfraEvent("autopost-outside-window-reschedule", {
						queueItemId,
						scheduleNonce: persistedScheduleNonce,
						qstashMessageId: result.messageId,
						accountId: account.id,
						groupId,
						workspaceId,
					});
				} catch (rescheduleErr) {
					logger.warn(
						"[auto-post-publish] Failed to requeue selected outside-window item",
						{
							queueItemId,
							accountId: account.id,
							error:
								rescheduleErr instanceof Error
									? rescheduleErr.message
									: String(rescheduleErr),
						},
					);
					await rescheduleQueueItemForFutureDispatch(queueItemId, {
						accountId: account.id,
						scheduledFor: rescheduleAt.toISOString(),
						lastError:
							"Selected account outside active window — rescheduled without QStash dispatch",
					});
				}

				logger.info(
					"[auto-post-publish] Rescheduled selected outside active window",
					{
						queueItemId,
						accountId: account.id,
						groupId,
						currentHour,
						effectiveStart,
						effectiveEnd,
						rescheduledTo: rescheduleAt.toISOString(),
					},
				);
				await finishPublishAttempt(publishAttemptId, {
					result: "requeued",
					accountId: account.id,
					errorCode: "outside_active_window",
					errorMessage: "Selected account outside active window",
				});

				return res.status(200).json({
					ok: true,
					result: "rescheduled",
					reason: "outside_active_window",
				});
			}
		}

		if (!isManual) {
			const schedulePolicy = await loadPublishSchedulePolicyForAccount({
				accountId: account.id,
				groupId,
				groupConfig,
			});
			const accountState = await getAccountState(account.id);
			const capacityBlock = await getPublishCapacityBlock({
				workspaceId,
				groupId,
				queueItemId,
				accountId: account.id,
				state: accountState,
				policy: schedulePolicy,
			});
			if (capacityBlock.blocked) {
				await releaseSelectedAccountLock();
				await requeueWithBackoff(
					queueItemId,
					`${capacityBlock.reason} — requeued`,
					retryAtMinutes(24 * 60),
					(item.retry_count || 0) + 1,
					queueClaimToken,
				);
				await finishPublishAttempt(publishAttemptId, {
					result: "requeued",
					accountId: account.id,
					errorCode: capacityBlock.reason,
					errorMessage: `${capacityBlock.reason} — requeued`,
					metadata: {
						cap: capacityBlock.cap,
						used: capacityBlock.used,
						remaining: capacityBlock.remaining,
						timezone: schedulePolicy.timezone,
					},
				});
				await runLogger.finishRun("partial", {
					reason: capacityBlock.reason,
					queueItemId,
					workspaceId,
					groupId,
					accountId: account.id,
				});
				return res.status(200).json({
					ok: true,
					result: "requeued",
					reason: capacityBlock.reason,
				});
			}
		}

		// 6. Rate limits + daily cap (Meta API limits: 25/hr, 250/day)
		const { RATE_LIMITS } = await import("../auto-post/types.js");
		const { data: rateLimitStatus, error: rateLimitError } = await db().rpc(
			"get_rate_limit_status",
			{
				p_account_id: account.id,
				p_hourly_limit: RATE_LIMITS.POSTS_PER_HOUR,
				p_daily_limit: RATE_LIMITS.POSTS_PER_DAY,
			},
		);
		const statusRow = (
			rateLimitStatus as Array<{
				posts_this_hour?: number | undefined;
				posts_today?: number | undefined;
			}> | null
		)?.[0];
		if (rateLimitError || !statusRow) {
			logger.error(
				"[auto-post-publish] Rate-limit status unavailable; failing closed",
				{
					accountId: account.id,
					queueItemId,
					error: rateLimitError?.message ?? "empty_result",
				},
			);
			await releaseSelectedAccountLock();
			await requeueWithBackoff(
				queueItemId,
				"Rate limit status unavailable — requeued",
				retryAtMinutes(LOCAL_RATE_LIMIT_RETRY_MINUTES),
				undefined,
				queueClaimToken,
			);
			await finishPublishAttempt(publishAttemptId, {
				result: "requeued",
				accountId: account.id,
				errorCode: "rate_limit_status_unavailable",
				errorMessage: rateLimitError?.message ?? "empty_result",
			});
			return res.status(200).json({
				ok: true,
				result: "requeued",
				reason: "rate_limit_status_unavailable",
			});
		}
		const currentHourly =
			statusRow.posts_this_hour ?? RATE_LIMITS.POSTS_PER_HOUR;
		const currentDaily = statusRow.posts_today ?? RATE_LIMITS.POSTS_PER_DAY;

		if (
			currentHourly >= RATE_LIMITS.POSTS_PER_HOUR ||
			currentDaily >= RATE_LIMITS.POSTS_PER_DAY
		) {
			await releaseSelectedAccountLock();
			const retryMinutes =
				currentDaily >= RATE_LIMITS.POSTS_PER_DAY
					? DAILY_CAP_RETRY_MINUTES
					: LOCAL_RATE_LIMIT_RETRY_MINUTES;
			await requeueWithBackoff(
				queueItemId,
				"Rate limit at publish time — requeued",
				retryAtMinutes(retryMinutes),
				undefined,
				queueClaimToken,
			);
			await finishPublishAttempt(publishAttemptId, {
				result: "requeued",
				accountId: account.id,
				errorCode: "rate_limit",
				errorMessage: "Rate limit at publish time",
			});
			return res
				.status(200)
				.json({ ok: true, result: "requeued", reason: "rate_limit" });
		}

		if (currentDaily >= RATE_LIMITS.POSTS_PER_DAY - 5) {
			const liveQuota = await getThreadsLivePublishingQuota(account);
			if (liveQuota?.exhausted) {
				await releaseSelectedAccountLock();
				await requeueWithBackoff(
					queueItemId,
					`Live Threads quota exhausted (${liveQuota.used}/${liveQuota.limit}) — requeued`,
					liveQuota.retryAt ?? retryAtMinutes(DAILY_CAP_RETRY_MINUTES),
					undefined,
					queueClaimToken,
				);
				await finishPublishAttempt(publishAttemptId, {
					result: "requeued",
					accountId: account.id,
					errorCode: "live_quota",
					errorMessage: `Live Threads quota exhausted (${liveQuota.used}/${liveQuota.limit})`,
				});
				return res.status(200).json({
					ok: true,
					result: "requeued",
					reason: "live_quota",
				});
			}
		}

		const { checkDailyCap } = await import("../../dailyCap.js");
		const capResult = await checkDailyCap(account.id, "threads");
		if (!capResult.allowed) {
			await releaseSelectedAccountLock();
			await requeueWithBackoff(
				queueItemId,
				"Daily cap exceeded — requeued",
				retryAtMinutes(DAILY_CAP_RETRY_MINUTES),
				undefined,
				queueClaimToken,
			);
			await finishPublishAttempt(publishAttemptId, {
				result: "requeued",
				accountId: account.id,
				errorCode: "daily_cap",
				errorMessage: "Daily cap exceeded",
			});
			return res
				.status(200)
				.json({ ok: true, result: "requeued", reason: "daily_cap" });
		}

		// 7. Publish-time content integrity gate. Fill-time gates are not enough:
		// queued content can be edited or imported by compatibility paths. Before
		// any Graph API side effect, require the fill-time signed gate token to
		// still match the final content and re-run discoverability safety.
		const finalContent = item.content;

		if (!isManual) {
			const gatePass = verifyAutopublishGatePassToken({
				content: finalContent,
				token:
					item.metadata && typeof item.metadata === "object"
						? (item.metadata as Record<string, unknown>).gate_pass
						: null,
			});
			if (!gatePass.ok) {
				await releaseSelectedAccountLock();
				await deadLetterQueueItem(
					queueItemId,
					`Autopublish gate pass invalid: ${gatePass.reason}`,
					{ claimToken: queueClaimToken },
				);
				await finishPublishAttempt(publishAttemptId, {
					result: "dead_letter",
					accountId: account.id,
					errorCode: "autopublish_gate_pass_invalid",
					errorMessage: gatePass.reason,
					metadata: {
						contentHash: gatePass.contentHash,
					},
				});
				return res.status(200).json({
					ok: true,
					result: "dead_letter",
					reason: gatePass.reason,
				});
			}
			const discoverability =
				validateDiscoverabilitySafeContent(finalContent);
			if (!discoverability.discoverabilitySafe) {
				await releaseSelectedAccountLock();
				await deadLetterQueueItem(
					queueItemId,
					`Discoverability blocked: ${discoverability.blockedReason}`,
					{ claimToken: queueClaimToken },
				);
				await finishPublishAttempt(publishAttemptId, {
					result: "dead_letter",
					accountId: account.id,
					errorCode: "discoverability_safety_failed",
					errorMessage: discoverability.blockedReason,
					metadata: {
						blockedTerms: discoverability.blockedTerms,
					},
				});
				return res.status(200).json({
					ok: true,
					result: "dead_letter",
					reason: discoverability.blockedReason,
				});
			}
			const { bannedWordsCheck } = await import("../../contentSafety.js");
			const banned = bannedWordsCheck(finalContent);
			if (banned.flagged) {
				await releaseSelectedAccountLock();
				await deadLetterQueueItem(
					queueItemId,
					`Banned: ${banned.matches.join(", ")}`,
					{ claimToken: queueClaimToken },
				);
				await finishPublishAttempt(publishAttemptId, {
					result: "dead_letter",
					accountId: account.id,
					errorCode: "banned_content",
					errorMessage: `Banned: ${banned.matches.join(", ")}`,
				});
				return res
					.status(200)
					.json({ ok: true, result: "dead_letter", reason: "banned" });
			}
		}

		// 8. Media — use the item's own media_urls (supports carousel), fall back to random
		const mediaStart = Date.now();
		const existingMediaUrls = item.media_urls ?? [];
		const hasExistingMedia = existingMediaUrls.length > 0;
		let mediaUrls: string[] = hasExistingMedia ? existingMediaUrls : [];

		if (!hasExistingMedia) {
			const { shouldAttachMedia, getRandomMediaUrl } = await import(
				"../auto-post/publisher.js"
			);
			// Look up group-level media_attachment_chance (overrides workspace media_chance)
			const { data: gc } = (await db()
				.from("auto_post_group_config")
				.select("media_attachment_chance")
				.eq("group_id", groupId)
				.maybeSingle()) as {
				data: { media_attachment_chance?: number | undefined } | null;
			};
			const groupMediaChance = gc?.media_attachment_chance ?? undefined;
			// biome-ignore lint/suspicious/noExplicitAny: partial config select
			if (shouldAttachMedia(wsConfig as any, undefined, groupMediaChance)) {
				const randomUrl = await getRandomMediaUrl(
					ownerId,
					"all",
					groupId,
					account.id,
				);
				if (randomUrl) mediaUrls = [randomUrl];
			}
		}
		await runLogger.logStep({
			name: "media_prep",
			status: "success",
			inputs: {
				queueItemId,
				accountId: account.id,
				existingMediaCount: existingMediaUrls.length,
			},
			outputs: {
				mediaCount: mediaUrls.length,
				hasExistingMedia,
			},
			durationMs: Date.now() - mediaStart,
		});

		const fingerprint = buildPublishFingerprint({
			workspaceId,
			accountId: account.id,
			platform: item.platform || "threads",
			content: finalContent,
			mediaUrls,
			duplicateWindowHours: item.duplicate_window_hours,
		});
		const mediaReuseSignals =
			mediaUrls.length > 0
				? await buildMediaReuseSignals({
						userId: ownerId,
						content: finalContent,
						mediaUrls,
						fetchPerceptual: true,
					})
				: null;
		await stampQueueItemFingerprint(queueItemId, fingerprint);
		const duplicateMatch = await findRecentDuplicateFingerprint({
			workspaceId,
			accountId: account.id,
			platform: item.platform || "threads",
			normalizedTextHash: fingerprint.normalizedTextHash,
			mediaFingerprint: fingerprint.mediaFingerprint,
			duplicateWindowHours: fingerprint.duplicateWindowHours,
			excludeQueueItemId: queueItemId,
			statuses: ["published", "publishing", "queued", "pending"],
		});
		const crossAccountMediaDuplicate =
			!isManual && mediaUrls.length > 0
				? await findRecentMediaFingerprintAcrossAccounts({
						workspaceId,
						userId: ownerId,
						accountId: account.id,
						platform: item.platform || "threads",
						mediaFingerprint: fingerprint.mediaFingerprint,
						mediaUrlHashes: mediaReuseSignals?.mediaUrlHashes,
						perceptualHashes: mediaReuseSignals?.perceptualHashes,
						duplicateWindowHours: fingerprint.duplicateWindowHours,
						excludeQueueItemId: queueItemId,
						statuses: ["published", "publishing", "queued", "pending"],
					})
				: null;
		if (crossAccountMediaDuplicate) {
			await releaseSelectedAccountLock();
			await deadLetterQueueItem(
				queueItemId,
				`Cross-account media reuse blocked; duplicate queue item ${crossAccountMediaDuplicate.id}`,
				{ claimToken: queueClaimToken },
			);
			await finishPublishAttempt(publishAttemptId, {
				result: "dead_letter",
				accountId: account.id,
				errorCode: "cross_account_media_reuse_blocked",
				errorMessage: `Duplicate media queue item ${crossAccountMediaDuplicate.id}`,
				metadata: {
					duplicateQueueItemId: crossAccountMediaDuplicate.id,
					duplicateStatus: crossAccountMediaDuplicate.status,
					matchType: crossAccountMediaDuplicate.match_type ?? null,
					mediaFingerprint: fingerprint.mediaFingerprint,
				},
			});
			return res.status(200).json({
				ok: true,
				result: "dead_letter",
				reason: "cross_account_media_reuse_blocked",
				duplicateQueueItemId: crossAccountMediaDuplicate.id,
			});
		}
		if (duplicateMatch) {
			if (!isManual) {
				await releaseSelectedAccountLock();
				await deadLetterQueueItem(
					queueItemId,
					`Duplicate publish fingerprint blocked; duplicate queue item ${duplicateMatch.id}`,
					{ claimToken: queueClaimToken },
				);
				await db()
					.from("auto_post_queue")
					.update({
						duplicate_of_queue_item_id: duplicateMatch.id,
						normalized_text_hash: fingerprint.normalizedTextHash,
						media_fingerprint: fingerprint.mediaFingerprint,
						publish_fingerprint: fingerprint.publishFingerprint,
						duplicate_window_hours: fingerprint.duplicateWindowHours,
					} as Record<string, unknown>)
					.eq("id", queueItemId);
				await finishPublishAttempt(publishAttemptId, {
					result: "duplicate_fingerprint_blocked",
					accountId: account.id,
					errorCode: "duplicate_fingerprint_blocked",
					errorMessage: `Duplicate queue item ${duplicateMatch.id}`,
					metadata: {
						duplicateQueueItemId: duplicateMatch.id,
						duplicateStatus: duplicateMatch.status,
						publishFingerprint: fingerprint.publishFingerprint,
					},
				});
				return res.status(200).json({
					ok: true,
					result: "duplicate_fingerprint_blocked",
					duplicateQueueItemId: duplicateMatch.id,
				});
			}

			await recordPublishAttempt({
				queueItemId,
				userId: ownerId,
				workspaceId,
				groupId,
				claimToken: queueClaimToken,
				accountId: account.id,
				result: "duplicate_fingerprint_needs_review",
				errorCode: "manual_duplicate_allowed",
				errorMessage: `Manual duplicate allowed; duplicate queue item ${duplicateMatch.id}`,
				metadata: {
					duplicateQueueItemId: duplicateMatch.id,
					publishFingerprint: fingerprint.publishFingerprint,
				},
			});
		}

		// 8b. Image transform DISABLED — split test showed 85% fewer views vs raw.
		// Transformed median=0 views, raw median=1, raw avg=40 vs transformed avg=6.
		// Threads likely detects manipulation artifacts and suppresses.

		// 9. Resolve spoiler entities (if this post has a spoiler trick)
		let textSpoilerEntities: Array<{
			entity_type: "SPOILER";
			offset: number;
			length: number;
		}> | null = null;
		if (item.text_spoilers) {
			try {
				const { resolveSpoilerEntities } = await import(
					"../auto-post/spoilerTricks.js"
				);
				const meta =
					typeof item.text_spoilers === "string"
						? JSON.parse(item.text_spoilers)
						: item.text_spoilers;
				textSpoilerEntities = resolveSpoilerEntities(finalContent, meta);
			} catch (spoilerErr) {
				logger.warn("[publish] Spoiler metadata parse failed (non-blocking)", {
					queueItemId,
					error:
						spoilerErr instanceof Error
							? spoilerErr.message
							: String(spoilerErr),
				});
			}
		}

		// Time budget check — bail before the expensive Meta API call if we're running out
		const elapsed = Date.now() - (globalStart ?? Date.now());
		if (elapsed > 240_000) {
			logger.warn("[publish] Time budget exhausted before Meta API call", {
				queueItemId,
				elapsedMs: elapsed,
			});
			await releaseSelectedAccountLock();
			await requeueWithBackoff(
				queueItemId,
				"Time budget exhausted — requeued",
				retryAtMinutes(LOCAL_RATE_LIMIT_RETRY_MINUTES),
				undefined,
				queueClaimToken,
			);
			await finishPublishAttempt(publishAttemptId, {
				result: "requeued",
				accountId: account.id,
				errorCode: "time_budget",
				errorMessage: "Time budget exhausted before Meta API call",
			});
			return res
				.status(200)
				.json({ ok: true, result: "requeued", reason: "time_budget" });
		}

		// 10. Publish to Threads — single post (CTA replies handled by cta-reply-worker cron 12-24h later)
		const hasMedia = mediaUrls.length > 0;
		// 80% of media posts get spoiler blur — drives curiosity taps
		const spoilerMedia = hasMedia && Math.random() < 0.8;
		const { postToThreads } = await import("../auto-post/publisher.js");
		const dispatchStart = Date.now();
		const result = await postToThreads(
			account.threads_access_token_encrypted,
			account.threads_user_id,
			finalContent,
			null, // legacy single URL param — use mediaUrls instead
			textSpoilerEntities,
			item.topic_tag || null,
			spoilerMedia,
			mediaUrls, // carousel support: all media URLs
		);
		await runLogger.logStep({
			name: "dispatch",
			status: result.success ? "success" : "failed",
			inputs: {
				queueItemId,
				accountId: account.id,
				contentLength: finalContent.length,
				mediaCount: mediaUrls.length,
				hasSpoilerEntities: Boolean(textSpoilerEntities?.length),
			},
			outputs: {
				success: result.success,
				threadId: result.threadId ?? null,
				retryable: result.retryable ?? null,
			},
			error: result.success ? null : (result.error ?? "Unknown publish error"),
			durationMs: Date.now() - dispatchStart,
		});

		const now = new Date();

		if (result.success && result.threadId) {
			const captureStart = Date.now();
			let finalizedPost: { postId: string; inserted: boolean };
			try {
				finalizedPost = await finalizeAutoposterPublish({
					queueItemId,
					claimToken: queueClaimToken,
					threadId: result.threadId,
					accountId: account.id,
					workspaceId,
					groupId,
					content: finalContent,
					mediaUrls,
					sourceType: "auto-poster",
					publishedAt: now.toISOString(),
				});
			} catch (finalizeErr) {
				const finalizeError =
					finalizeErr instanceof Error
						? finalizeErr.message
						: String(finalizeErr);
				await markQueueItemNeedsReconciliation(queueItemId, {
					accountId: account.id,
					threadId: result.threadId,
					publishedAt: now.toISOString(),
					finalizeError,
					claimToken: queueClaimToken,
				});
				await finishPublishAttempt(publishAttemptId, {
					result: "needs_reconciliation",
					accountId: account.id,
					threadsPostId: result.threadId,
					errorCode: "local_finalize_failed_after_external_publish",
					errorMessage: finalizeError,
				});
				logger.error(
					"[publish] External publish finalized by Meta but local finalization failed",
					{
						queueItemId,
						accountId: account.id,
						threadId: result.threadId,
						error: finalizeError,
					},
				);
				await runLogger.finishRun("failed", {
					reason: "local_finalize_failed_after_external_publish",
					queueItemId,
					workspaceId,
					groupId,
					accountId: account.id,
					threadId: result.threadId,
				});
				return res.status(200).json({
					ok: false,
					result: "needs_reconciliation",
					reason: "local_finalize_failed_after_external_publish",
					threadId: result.threadId,
				});
			}

			// Dispatch engagement sync at 1h + 24h (populates views_at_24h on auto_post_queue)
			if (finalizedPost.postId && result.threadId) {
				try {
					const { dispatchEngagementFetch } = await import(
						"../../qstashSchedule.js"
					);
					await dispatchEngagementFetch(
						finalizedPost.postId,
						result.threadId,
						3600,
					);
					await dispatchEngagementFetch(
						finalizedPost.postId,
						result.threadId,
						86400,
					);
				} catch {
					/* non-critical */
				}
			}

			// Dispatch targeted reply harvest at exactly +15min (Threads only)
			// Research: 15-min reply speed = 391% higher conversion
			if (result.threadId && account?.id) {
				try {
					const { dispatchReplyHarvest } = await import(
						"../../qstashSchedule.js"
					);
					await dispatchReplyHarvest({
						queueItemId,
						workspaceId,
						groupId,
						ownerId,
						accountId: account.id,
						postId: finalizedPost.postId || queueItemId,
					});
				} catch {
					/* non-critical — cron fallback catches missed harvests */
				}
			}

			// Daily counter reset — if it's a new day in the group's timezone, reset before incrementing.
			// Without this, posts_today accumulates across days and blocks publishing.
			{
				const { getTodayInTimezone } = await import(
					"../auto-post/contentSelection.js"
				);
				const { data: gState } = await db()
					.from("auto_post_group_state")
					.select("last_reset_date")
					.eq("workspace_id", workspaceId)
					.eq("group_id", groupId)
					.maybeSingle();
				const gcTz = (
					await db()
						.from("auto_post_group_config")
						.select("timezone")
						.eq("group_id", groupId)
						.maybeSingle()
				)?.data?.timezone;
				const todayStr = getTodayInTimezone(gcTz || undefined);
				if (gState && gState.last_reset_date !== todayStr) {
					await db()
						.from("auto_post_group_state")
						.update({
							posts_today: 0,
							ig_posts_today: 0,
							last_reset_date: todayStr,
							updated_at: now.toISOString(),
						} as Record<string, unknown>)
						.eq("workspace_id", workspaceId)
						.eq("group_id", groupId);
				}
			}

			// Update non-racy fields separately (round-robin index)
			await db()
				.from("auto_post_group_state")
				.update({
					current_account_index: selectedIdx + 1,
					last_post_at: now.toISOString(),
					updated_at: now.toISOString(),
				} as Record<string, unknown>)
				.eq("workspace_id", workspaceId)
				.eq("group_id", groupId);

			// Decrement flop recovery counter on account_autoposter_state
			try {
				const { getSupabaseAny } = await import("../../supabase.js");
				const supabase = getSupabaseAny();
				const { data: autoposterState } = await supabase
					.from("account_autoposter_state")
					.select("flop_proven_remaining")
					.eq("account_id", account.id)
					.gt("flop_proven_remaining", 0)
					.maybeSingle();

				if (!autoposterState?.flop_proven_remaining) {
					// No recovery budget left to decrement.
				} else {
					await supabase
						.from("account_autoposter_state")
						.update({
							flop_proven_remaining: Math.max(
								0,
								autoposterState.flop_proven_remaining - 1,
							),
						})
						.eq("account_id", account.id)
						.gt("flop_proven_remaining", 0);
				}
			} catch {
				/* non-critical */
			}

			// Log activity
			const { logActivity } = await import("../auto-post/publisher.js");
			await logActivity(
				workspaceId,
				"posted",
				`@${account.username}`,
				`[${groupName}] ${finalContent.substring(0, 60)}`,
				undefined,
				undefined,
				groupId,
				groupName,
			);

			logger.info("[publish] OK", {
				queueItemId,
				accountId: account.id,
				threadId: result.threadId,
				scheduleNonce: item.schedule_nonce,
				qstashMessageId: item.qstash_message_id,
			});
			await finishPublishAttempt(publishAttemptId, {
				result: "published",
				accountId: account.id,
				threadsPostId: result.threadId,
				metadata: {
					postId: finalizedPost.postId,
					finalizerInserted: finalizedPost.inserted,
				},
			});
			await runLogger.logStep({
				name: "response_capture",
				status: "success",
				inputs: {
					queueItemId,
					accountId: account.id,
					threadId: result.threadId,
				},
				outputs: {
					postId: finalizedPost.postId,
					threadId: result.threadId,
					engagementSyncQueued: Boolean(finalizedPost.postId),
					finalizerInserted: finalizedPost.inserted,
				},
				durationMs: Date.now() - captureStart,
			});
			await runLogger.finishRun("success", {
				queueItemId,
				workspaceId,
				groupId,
				accountId: account.id,
				postId: finalizedPost.postId,
				threadId: result.threadId,
			});

			// Self-comment disabled — looks bot-obvious (auto-reply within seconds of posting)

			// Automatic cross-replies are intentionally disabled.
			// They create a synthetic engagement pattern that is not worth the reach risk.

			return res
				.status(200)
				.json({ ok: true, result: "published", threadId: result.threadId });
		}

		// 10. Failure — retry or dead letter
		const errorStr = result.error || "Unknown error";
		logger.error("[publish] Failed", {
			queueItemId,
			error: errorStr,
			accountId: account.id,
			scheduleNonce: item.schedule_nonce,
			qstashMessageId: item.qstash_message_id,
		});

		const { isDefinitiveOAuthError } = await import("../../retryUtils.js");

		// Log failure activity only when action is likely required. Retryable
		// publish failures are still tracked in publish_attempts below, but
		// Discord should not page for Meta 5xx/transport noise that the queue
		// will retry automatically.
		const errLowerForTransient = errorStr.toLowerCase();
		const isRetryablePublishFailure =
			result.retryable === true ||
			errLowerForTransient.includes("unknown error") ||
			errLowerForTransient.includes("unexpected error") ||
			/\bhttp\s+5\d\d\b/i.test(errorStr);
		const shouldLogFailureActivity =
			!isRetryablePublishFailure || isDefinitiveOAuthError(errorStr);
		if (shouldLogFailureActivity) {
			const { logActivity } = await import("../auto-post/publisher.js");
			await logActivity(
				workspaceId,
				"error",
				`@${account.username}`,
				`[${groupName}] Publish failed: ${errorStr}`,
				undefined,
				undefined,
				groupId,
				groupName,
			).catch(() => {});
		} else {
			logger.warn("[publish] Retryable publish failure, suppressing Discord alert", {
				queueItemId,
				account: account.username,
				error: errorStr,
				retryable: result.retryable ?? null,
			});
		}

		// OAuth error → attempt inline token refresh, then flag if refresh fails.
		if (isDefinitiveOAuthError(errorStr)) {
			// Attempt inline token refresh before giving up
			let refreshed = false;
			let refreshFailureError: string | null = null;
			try {
				const { decrypt } = await import("../../encryption.js");
				const currentToken = decrypt(account.threads_access_token_encrypted);
				const { refreshThreadsToken } = await import("../../tokenRefresh.js");
				const refreshResult = await refreshThreadsToken(currentToken);
				const refreshData = refreshResult.data;
				if (refreshResult.ok && refreshData.access_token) {
					const { encrypt } = await import("../../encryption.js");
					const newEncryptedToken = encrypt(refreshData.access_token as string);
					const expiresIn = refreshData.expires_in || 5184000;
					await db()
						.from("accounts")
						.update({
							threads_access_token_encrypted: newEncryptedToken,
							token_expires_at: new Date(
								Date.now() + expiresIn * 1000,
							).toISOString(),
							updated_at: now.toISOString(),
						} as Record<string, unknown>)
						.eq("id", account.id);

					// Retry publish with refreshed token (positional params matching postToThreads signature)
					const { postToThreads: retryPostToThreads } = await import(
						"../auto-post/publisher.js"
					);
					const retryResult = await retryPostToThreads(
						newEncryptedToken,
						account.threads_user_id,
						finalContent,
						null,
						textSpoilerEntities,
						item.topic_tag || null,
						spoilerMedia,
						mediaUrls,
					);
					if (retryResult.success) {
						refreshed = true;
						logger.info("[publish] Recovered via inline token refresh", {
							queueItemId,
							account: account.username,
						});
						let retryFinalizedPost: { postId: string; inserted: boolean };
						try {
							retryFinalizedPost = await finalizeAutoposterPublish({
								queueItemId,
								claimToken: queueClaimToken,
								threadId: retryResult.threadId as string,
								accountId: account.id,
								workspaceId,
								groupId,
								content: finalContent,
								mediaUrls,
								sourceType: "auto-poster",
								publishedAt: now.toISOString(),
							});
						} catch (finalizeErr) {
							const finalizeError =
								finalizeErr instanceof Error
									? finalizeErr.message
									: String(finalizeErr);
							await markQueueItemNeedsReconciliation(queueItemId, {
								accountId: account.id,
								threadId: retryResult.threadId as string,
								publishedAt: now.toISOString(),
								finalizeError,
								claimToken: queueClaimToken,
							});
							await finishPublishAttempt(publishAttemptId, {
								result: "needs_reconciliation",
								accountId: account.id,
								threadsPostId: retryResult.threadId as string,
								errorCode: "local_finalize_failed_after_external_publish",
								errorMessage: finalizeError,
							});
							return res.status(200).json({
								ok: false,
								result: "needs_reconciliation",
								reason: "local_finalize_failed_after_external_publish",
								threadId: retryResult.threadId,
							});
						}
						await finishPublishAttempt(publishAttemptId, {
							result: "published",
							accountId: account.id,
							threadsPostId: retryResult.threadId as string,
							metadata: {
								refreshedToken: true,
								postId: retryFinalizedPost.postId,
								finalizerInserted: retryFinalizedPost.inserted,
							},
						});
						return res.status(200).json({
							ok: true,
							result: "published_after_refresh",
							threadId: retryResult.threadId,
						});
					}
				} else {
					refreshFailureError = String(
						refreshData?.error?.message ||
							refreshData?.error ||
							"Token refresh returned no access token",
					);
				}
			} catch (refreshErr) {
				refreshFailureError =
					refreshErr instanceof Error ? refreshErr.message : String(refreshErr);
				logger.error("[publish] Inline token refresh failed", {
					queueItemId,
					error: refreshFailureError,
				});
			}

			// Refresh failed or retry failed — only flag account on definitive auth failures.
			if (!refreshed) {
				if (isDefinitiveOAuthError(refreshFailureError || errorStr)) {
					await db()
						.from("accounts")
						.update({
							needs_reauth: true,
							status: "needs_reauth",
							is_active: false,
							updated_at: now.toISOString(),
						} as Record<string, unknown>)
						.eq("id", account.id);
				} else {
					logger.warn("[publish] Token refresh failure treated as transient", {
						queueItemId,
						account: account.username,
						error: refreshFailureError,
					});
				}
			}
		}

		// Release publish lock on failure so account is available for retry
		await releaseSelectedAccountLock();

		const isPermanentFailure =
			result.retryable === false && !isDefinitiveOAuthError(errorStr);
		const { shouldRetry, calculateBackoff } = await import(
			"../../retryUtils.js"
		);
		const retryCount = item.retry_count || 0;
		if (isPermanentFailure) {
			logger.warn("[publish] Permanent failure, dead-lettering", {
				queueItemId,
				account: account.username,
				error: errorStr,
			});
			await deadLetterQueueItem(queueItemId, errorStr, {
				claimToken: queueClaimToken,
			});
			await finishPublishAttempt(publishAttemptId, {
				result: "dead_letter",
				accountId: account.id,
				errorCode: "permanent_publish_failure",
				errorMessage: errorStr,
			});
		} else if (shouldRetry(retryCount)) {
			const backoff = calculateBackoff(retryCount);
			let retryAt = new Date(
				backoff.getTime() + Math.floor(Math.random() * 30000),
			);
			let retryReason = errorStr;
			if (isRateLimitErrorMessage(errorStr)) {
				const liveQuota = await getThreadsLivePublishingQuota(account);
				if (liveQuota?.exhausted && liveQuota.retryAt) {
					retryAt = liveQuota.retryAt;
					retryReason = `${errorStr}; live quota ${liveQuota.used}/${liveQuota.limit}`;
				} else {
					retryAt = retryAtMinutes(LOCAL_RATE_LIMIT_RETRY_MINUTES);
				}
			}
			await requeueWithBackoff(
				queueItemId,
				retryReason,
				retryAt,
				retryCount + 1,
				queueClaimToken,
			);
			await finishPublishAttempt(publishAttemptId, {
				result: "requeued",
				accountId: account.id,
				errorCode: isRateLimitErrorMessage(errorStr)
					? "rate_limit_publish_failure"
					: "retryable_publish_failure",
				errorMessage: retryReason,
			});
		} else {
			await deadLetterQueueItem(queueItemId, `Max retries: ${errorStr}`, {
				claimToken: queueClaimToken,
			});
			await finishPublishAttempt(publishAttemptId, {
				result: "dead_letter",
				accountId: account.id,
				errorCode: "max_retries",
				errorMessage: errorStr,
			});
		}
		await runLogger.logStep({
			name: "response_capture",
			status: "failed",
			inputs: { queueItemId, accountId: account.id },
			outputs: { retryCount: item.retry_count || 0 },
			error: errorStr,
			durationMs: 0,
		});
		await runLogger.finishRun("failed", {
			queueItemId,
			workspaceId,
			groupId,
			accountId: account.id,
			error: errorStr,
		});

		return res
			.status(200)
			.json({ ok: true, result: "failed", error: "Publish failed" });
	} catch (err: unknown) {
		const errMsg = err instanceof Error ? err.message : String(err);
		logger.error("[publish] Unhandled", { error: errMsg, queueItemId });
		// Report to Sentry for visibility
		import("../../sentryServer.js")
			.then(({ captureServerException }) =>
				captureServerException(err, {
					cronJob: "auto-post-publish",
					queueItemId,
				}),
			)
			.catch(() => {});
		// Release the per-account publish lock — without this, an unhandled
		// throw between lock acquisition and the success/failure paths leaves
		// the account locked for the full 5-min Redis TTL, silently blocking
		// every subsequent publish for that account during the window.
		await releaseSelectedAccountLock();
		try {
			await releasePublishingQueueItem(queueItemId, `Exception: ${errMsg}`, {
				claimToken: queueClaimToken,
			});
		} catch {
			// Best effort
		}
		await finishPublishAttempt(publishAttemptId, {
			result: "error",
			errorCode: "unhandled_exception",
			errorMessage: errMsg,
		});
		await runLogger.logStep({
			name: "response_capture",
			status: "failed",
			inputs: { queueItemId, workspaceId, groupId },
			error: errMsg,
			durationMs: Date.now() - globalStart,
		});
		await runLogger.finishRun("failed", {
			queueItemId,
			workspaceId,
			groupId,
			error: errMsg,
		});
		return res
			.status(200)
			.json({ ok: true, result: "error", error: "Internal publish error" });
	}
}
