// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Single-post publish orchestrator.
 *
 * Called by:
 * 1. QStash receiver (api/scheduled-post-publish.ts) — exact-time delivery
 * 2. Can also be called by the cron fallback in future refactor
 *
 * Handles both Threads and Instagram posts with full feature parity:
 * - Thread chains (CHAIN_SEPARATOR)
 * - Rate limiting
 * - Inline token refresh
 * - Cross-posting
 * - Notifications
 * - IG container flow (async)
 */

import { isAccountPublishable } from "./accountEligibility.js";
import type { CrossPostRecord } from "./cron/scheduled-posts.js";
import { deliverNotification } from "./deliverNotification.js";
import { decrypt } from "./encryption.js";
import { checkSubscriptionPostLimit } from "./handlers/posts/shared.js";
import { checkIGRateLimit } from "./igRateLimit.js";
import { resolveInstagramTrialReelIntent } from "./instagramTrialReels.js";
import { logger } from "./logger.js";
import {
	enforceOutboundOperatorGuard,
	recordOutboundOperatorResult,
} from "./outboundOperatorGuard.js";
import { withRetry } from "./retryUtils.js";
import { maxBodyChars } from "./socialPlatform.js";
import { runPublishPreflight } from "./publishPreflight.js";
import { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } from "./privilegedDb.js";
import { eqOrNull } from "./supabaseSafe.js";
import type { PostData } from "./threadsApi.js";
import { postToThreads } from "./threadsApi.js";
import { refreshThreadsToken } from "./tokenRefresh.js";

const db = () => getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.publishExecution);

export interface PublishResult {
	result:
		| "published"
		| "failed"
		| "skipped"
		| "notified"
		| "container_pending"
		| "rescheduled";
	error?: string | undefined;
	threadId?: string | undefined;
	mediaId?: string | undefined;
}

const CHAIN_SEPARATOR = "\n---THREAD_CHAIN_SEPARATOR---\n";
const MAX_INSTAGRAM_PUBLISH_RETRIES = 3;

type InstagramPublishFailure = {
	error?: string | undefined;
	retryable?: boolean | undefined;
};

export function shouldRescheduleInstagramFailure(
	igResult: InstagramPublishFailure,
	retryCount: number,
	isTransient: (errorMsg: string) => boolean,
): boolean {
	if (retryCount >= MAX_INSTAGRAM_PUBLISH_RETRIES) return false;
	if (igResult.retryable === false) return false;
	if (igResult.retryable === true) return true;
	return isTransient(igResult.error || "");
}

function isPreviewScheduleOnly(metadata: unknown): boolean {
	const campaignFactory =
		metadata && typeof metadata === "object" && !Array.isArray(metadata)
			? (metadata as Record<string, unknown>).campaign_factory
			: null;
	return (
		!!campaignFactory &&
		typeof campaignFactory === "object" &&
		!Array.isArray(campaignFactory) &&
		(campaignFactory as Record<string, unknown>).preview_schedule_only === true
	);
}

type PublishableReason =
	| "account_inactive"
	| "needs_reauth"
	| "suspended"
	| "token_expired";

type ThreadsPostMetadata = {
	pollAttachment?: PostData["pollAttachment"] | undefined;
	textSpoilers?: PostData["textSpoilers"] | undefined;
	allowlistedCountryCodes?: PostData["allowlistedCountryCodes"] | undefined;
	linkUrl?: PostData["linkUrl"] | undefined;
	gifAttachment?: PostData["gifAttachment"] | undefined;
	textAttachment?: PostData["textAttachment"] | undefined;
	crossreshareToIg?: boolean | undefined;
	crossreshareToIgDarkMode?: boolean | undefined;
	settings?: PostData["settings"] | undefined;
	isSpoiler?: boolean | undefined;
};

function getEligibilityReason(
	reason: string | undefined | null,
): PublishableReason {
	switch (reason) {
		case "account_inactive":
		case "needs_reauth":
		case "suspended":
		case "token_expired":
			return reason;
		default:
			return "account_inactive";
	}
}

function getThreadsMetadata(metadata: unknown): ThreadsPostMetadata {
	const record = metadata as ThreadsPostMetadata | null | undefined;
	return record || {};
}

function metadataRecord(metadata: unknown): Record<string, unknown> {
	return metadata && typeof metadata === "object" && !Array.isArray(metadata)
		? (metadata as Record<string, unknown>)
		: {};
}

function metadataArray<T = unknown>(
	metadata: Record<string, unknown>,
	key: string,
): T[] | undefined {
	const value = metadata[key];
	return Array.isArray(value) ? (value as T[]) : undefined;
}

function metadataBoolean(
	metadata: Record<string, unknown>,
	key: string,
): boolean | undefined {
	const value = metadata[key];
	return typeof value === "boolean" ? value : undefined;
}

function metadataString(
	metadata: Record<string, unknown>,
	key: string,
): string | undefined {
	const value = metadata[key];
	return typeof value === "string" ? value : undefined;
}

function campaignFactoryInstagramPostCaption(
	post: Record<string, unknown>,
	metadata: Record<string, unknown>,
): string {
	const campaignFactory = metadataRecord(metadata.campaign_factory);
	const manifest = metadataRecord(campaignFactory.handoff_manifest);
	const candidate =
		metadataString(campaignFactory, "instagram_post_caption") ||
		metadataString(campaignFactory, "instagramPostCaption") ||
		metadataString(manifest, "instagram_post_caption") ||
		metadataString(manifest, "instagramPostCaption") ||
		(typeof post.content === "string" ? post.content : "");
	return candidate || "";
}

function metadataNumber(
	metadata: Record<string, unknown>,
	key: string,
): number | undefined {
	const value = metadata[key];
	return typeof value === "number" ? value : undefined;
}

function exceptionDetails(err: unknown) {
	return err instanceof Error
		? {
				name: err.name,
				message: err.message,
				stack: err.stack,
			}
		: {
				name: typeof err,
				message: String(err),
				stack: undefined,
			};
}

function preflightIssueSummary(
	preflight: Awaited<ReturnType<typeof runPublishPreflight>>,
) {
	return preflight.issues.map((issue) => ({
		severity: issue.severity,
		code: issue.code,
		message: issue.message,
	}));
}

/**
 * When a post is skipped (e.g. account_inactive, token_expired), increment
 * retry_count. After MAX_SKIP_RETRIES, mark the post as failed with a clear
 * error instead of leaving it stuck in "scheduled" forever.
 */
async function escalateSkip(
	postId: string,
	userId: string,
	currentSkips: number,
	maxRetries: number,
	reason: string,
	userMessage: string,
): Promise<PublishResult> {
	if (currentSkips + 1 >= maxRetries) {
		// Exceeded max skip attempts — fail permanently
		await db()
			.from("posts")
			.update({
				status: "failed",
				error_message: `${userMessage} (skipped ${currentSkips + 1} times)`,
				retry_count: currentSkips + 1,
				updated_at: new Date().toISOString(),
			})
			.eq("id", postId)
			.eq("status", "scheduled");

		await db().from("notifications").insert({
			user_id: userId,
			type: "post_failed",
			title: "Scheduled post failed",
			message: userMessage,
			read: false,
			data: { postId, reason },
		});

		try {
			await deliverNotification({
				userId,
				type: "post_failed",
				title: "Scheduled post failed",
				message: userMessage,
				data: { postId, reason },
			});
		} catch {
			/* non-critical */
		}

		logger.warn("[publishPost] Post failed after max skip retries", {
			postId,
			reason,
			skips: currentSkips + 1,
		});
		return { result: "failed", error: reason };
	}

	// Still under limit — increment and skip (cron will retry next cycle)
	await db()
		.from("posts")
		.update({
			retry_count: currentSkips + 1,
			updated_at: new Date().toISOString(),
		})
		.eq("id", postId)
		.eq("status", "scheduled");

	logger.info("[publishPost] Skip escalation", {
		postId,
		reason,
		skip: currentSkips + 1,
		max: maxRetries,
	});
	return { result: "skipped", error: reason };
}

/**
 * When a post is rate-limited, increment retry_count with a longer fuse
 * than escalateSkip (12 attempts ≈ 1 hour of 5-min cron cycles).
 * After the threshold, fail with a clear message so posts don't accumulate
 * silently on perpetually rate-limited accounts.
 */
const MAX_RATE_LIMIT_RETRIES = 12;

async function escalateRateLimit(
	postId: string,
	userId: string,
	currentRetries: number,
): Promise<PublishResult> {
	if (currentRetries + 1 >= MAX_RATE_LIMIT_RETRIES) {
		await db()
			.from("posts")
			.update({
				status: "failed",
				error_message: `Account rate limit exceeded. Post could not publish within the allowed window (tried ${currentRetries + 1} times over ~1 hour). Please reschedule.`,
				retry_count: currentRetries + 1,
				updated_at: new Date().toISOString(),
			})
			.eq("id", postId)
			.eq("status", "scheduled");

		await db()
			.from("notifications")
			.insert({
				user_id: userId,
				type: "post_failed",
				title: "Scheduled post failed — rate limit",
				message:
					"Account rate limit exceeded. Post could not publish within the allowed window. Please reschedule.",
				read: false,
				data: { postId, reason: "rate_limited" },
			});

		try {
			await deliverNotification({
				userId,
				type: "post_failed",
				title: "Scheduled post failed — rate limit",
				message:
					"Account rate limit exceeded. Post could not publish within the allowed window. Please reschedule.",
				data: { postId, reason: "rate_limited" },
			});
		} catch {
			/* non-critical */
		}

		logger.warn("[publishPost] Post failed after max rate limit retries", {
			postId,
			retries: currentRetries + 1,
		});
		return { result: "failed", error: "rate_limited" };
	}

	await db()
		.from("posts")
		.update({
			retry_count: currentRetries + 1,
			updated_at: new Date().toISOString(),
		})
		.eq("id", postId)
		.eq("status", "scheduled");

	logger.info("[publishPost] Rate limit retry", {
		postId,
		retry: currentRetries + 1,
		max: MAX_RATE_LIMIT_RETRIES,
	});
	return { result: "skipped", error: "rate_limited" };
}

/**
 * Publish a single scheduled post by ID.
 *
 * Loads the post, determines platform, validates, claims atomically,
 * publishes to the platform API, and updates status.
 *
 * Safe to call concurrently — atomic claim prevents double-publish.
 */
export async function publishSinglePost(
	postId: string,
): Promise<PublishResult> {
	logger.info("[publishPost] publishSinglePost entered", { postId });
	// Load post to determine platform and enforce publish-time plan caps.
	const { data: postRow } = await eqOrNull(
		db()
			.from("posts")
			.select(
				"id, user_id, platform, status, scheduled_for, publish_mode, metadata, account_id, instagram_account_id",
			)
			.eq("id", postId),
		"approval_status",
		"approved",
	).maybeSingle();

	if (!postRow) {
		logger.warn("[publishPost] publishSinglePost post not found", { postId });
		return { result: "skipped", error: "not_found" };
	}
	logger.info("[publishPost] publishSinglePost post loaded", {
		postId,
		userId: postRow.user_id,
		platform: postRow.platform,
		status: postRow.status,
		scheduledFor: postRow.scheduled_for ?? null,
		publishMode: postRow.publish_mode ?? null,
		hasAccountId: !!postRow.account_id,
		hasInstagramAccountId: !!postRow.instagram_account_id,
	});
	if (postRow.status !== "scheduled") {
		logger.warn("[publishPost] publishSinglePost status skip", {
			postId,
			status: postRow.status,
		});
		return { result: "skipped", error: postRow.status };
	}
	if (isPreviewScheduleOnly(postRow.metadata)) {
		logger.info("[publishPost] Skipping preview-only scheduled post", {
			postId,
		});
		return { result: "skipped", error: "preview_schedule_only" };
	}
	if (postRow.platform === "instagram" && postRow.publish_mode === "notify") {
		const { notifyInstagramHandoff } = await import("./notifyHandoff.js");
		const result = await notifyInstagramHandoff(postId, "qstash");
		if (result.result === "notified") {
			return { result: "notified" };
		}
		return { result: "skipped", error: result.error };
	}
	const tierCheck = await checkSubscriptionPostLimit(postRow.user_id, {
		targetDate: postRow.scheduled_for || new Date(),
		mode: "publish",
		additionalCount: 1,
	});
	logger.info("[publishPost] Subscription post limit checked", {
		postId,
		allowed: tierCheck.allowed,
		tier: tierCheck.tier,
		used: tierCheck.used,
		limit: tierCheck.limit,
	});
	if (!tierCheck.allowed) {
		logger.info("[publishPost] Skipping post over daily plan cap", {
			postId,
			userId: postRow.user_id,
			tier: tierCheck.tier,
			used: tierCheck.used,
			limit: tierCheck.limit,
		});
		return { result: "skipped", error: "plan_daily_cap" };
	}

	const platform = postRow.platform || "threads";
	const accountId =
		typeof postRow.account_id === "string" && postRow.account_id.length > 0
			? postRow.account_id
			: typeof postRow.instagram_account_id === "string"
				? postRow.instagram_account_id
				: null;
	const groupId = null;
	const outboundGuardPayload = {
		postId,
		platform,
		scheduledFor: postRow.scheduled_for ?? null,
		source: "scheduled-publish",
	};
	logger.info("[publishPost] Outbound guard start", {
		postId,
		platform,
		accountId,
	});
	const outboundGuard = await enforceOutboundOperatorGuard({
		db: db(),
		userId: postRow.user_id,
		actionName: "publish_post",
		riskLevel: "critical",
		scope: { groupId, accountId },
		payload: outboundGuardPayload,
		idempotencyKey: `publish-post:${postId}`,
		metadata: { postId, platform },
	});
	const outboundGuardBlocked = !outboundGuard.allowed ? outboundGuard : null;
	logger.info("[publishPost] Outbound guard result", {
		postId,
		platform,
		allowed: outboundGuard.allowed,
		reason: outboundGuardBlocked?.reason ?? null,
		code: outboundGuardBlocked?.code ?? null,
	});
	if (!outboundGuard.allowed) {
		logger.warn("[publishPost] Outbound publish blocked", {
			postId,
			platform,
			reason: outboundGuard.reason,
			code: outboundGuard.code,
		});
		return { result: "skipped", error: outboundGuard.code };
	}

	// Wrap the actual publish dispatch so any unhandled throw inside
	// publishThreadsPost / publishInstagramPost reaches Sentry. The audit
	// found zero captureServerException calls inside the autoposter pipeline
	// — errors only reach Sentry if they bubble all the way to a route
	// handler, and the inner catches in this file return PublishResult on
	// failure, so without this wrapper a thrown error here is invisible to
	// crash reporting.
	try {
		let result: PublishResult;
		logger.info("[publishPost] Publish dispatch start", { postId, platform });
		if (platform === "instagram") {
			result = await publishInstagramPost(postId);
		} else {
			result = await publishThreadsPost(postId);
		}
		logger.info("[publishPost] Publish dispatch result", {
			postId,
			platform,
			result: result.result,
			error: result.error ?? null,
		});
		await recordOutboundOperatorResult({
			db: db(),
			userId: postRow.user_id,
			actionName: "publish_post",
			riskLevel: "critical",
			scope: { groupId, accountId },
			payload: outboundGuardPayload,
			idempotencyKey: `publish-post:${postId}`,
			outcome:
				result.result === "published" ||
				result.result === "notified" ||
				result.result === "container_pending"
					? "success"
					: "failure",
			message: result.result,
			error: result.error ?? null,
			metadata: { postId, platform, result: result.result },
		});
		return result;
	} catch (err) {
		logger.error("[publishPost] Publish dispatch exception", {
			postId,
			platform,
			error: exceptionDetails(err),
		});
		await recordOutboundOperatorResult({
			db: db(),
			userId: postRow.user_id,
			actionName: "publish_post",
			riskLevel: "critical",
			scope: { groupId, accountId },
			payload: outboundGuardPayload,
			idempotencyKey: `publish-post:${postId}`,
			outcome: "failure",
			message: "publish threw",
			error: err instanceof Error ? err.message : String(err),
			metadata: { postId, platform },
		});
		try {
			const { captureServerException } = await import("./sentryServer.js");
			captureServerException(err, {
				cronJob: "publishPost",
				postId,
				platform,
			});
		} catch {
			// Best effort — never let Sentry import failure mask the original.
		}
		throw err;
	}
}

// ============================================================================
// Threads Publish
// ============================================================================

async function publishThreadsPost(postId: string): Promise<PublishResult> {
	// Import helpers from the cron (exported, not duplicated)
	const {
		checkAndIncrementRateLimit,
		getRateLimitStatus,
		handleCrossPost,
		checkMediaUrlAccessible,
		isTransientError,
	} = await import("./cron/scheduled-posts.js");

	// Load post with joined account data
	const threadsLoadQuery = eqOrNull(
		db()
			.from("posts")
			.select(`
			id, user_id, account_id, content, media_urls, media_type,
			hashtags, quoted_post_id, location_id, metadata, topic_tag,
			scheduled_for, retry_count, text_spoilers,
			accounts!inner (
				id, threads_user_id, threads_access_token_encrypted,
				username, is_active, status, needs_reauth, token_expires_at
			)
		`)
			.eq("id", postId)
			.eq("status", "scheduled"),
		"approval_status",
		"approved",
	);
	const { data: post, error: loadErr } = await threadsLoadQuery.maybeSingle();

	if (loadErr || !post) {
		return { result: "skipped", error: "not_found_or_not_scheduled" };
	}
	if (isPreviewScheduleOnly(post.metadata)) {
		logger.info("[publishPost] Skipping preview-only Threads post", { postId });
		return { result: "skipped", error: "preview_schedule_only" };
	}

	const account = (post as Record<string, unknown>).accounts as {
		id: string;
		threads_user_id: string | null;
		threads_access_token_encrypted: string | null;
		username: string | null;
		is_active: boolean;
		status: string | null;
		needs_reauth: boolean | null;
		token_expires_at: string | null;
	} | null;

	// Shared eligibility check — escalate to failure after 3 skip attempts
	const MAX_SKIP_RETRIES = 3;
	const currentSkips = (post.retry_count as number) || 0;

	if (account) {
		const eligibility = isAccountPublishable(account);
		if (!eligibility.eligible) {
			const eligibilityReason = getEligibilityReason(eligibility.reason);
			const messages: Record<string, string> = {
				account_inactive:
					"Account is inactive. Please reactivate the account or reassign the post.",
				needs_reauth:
					"Account token expired. Please reconnect your account in Settings.",
				suspended: "Account is suspended due to a content policy violation.",
				token_expired:
					"Account token expired. Please reconnect your account in Settings.",
			};
			return escalateSkip(
				postId,
				post.user_id,
				currentSkips,
				MAX_SKIP_RETRIES,
				eligibilityReason,
				messages[eligibilityReason] || "Account is not eligible to publish.",
			);
		}
	}

	if (!account?.threads_access_token_encrypted || !account?.threads_user_id) {
		await db()
			.from("posts")
			.update({
				status: "failed",
				error_message: "Account not properly configured for Threads",
				updated_at: new Date().toISOString(),
			})
			.eq("id", postId);
		return { result: "failed", error: "account_not_configured" };
	}

	// Narrowed account type — validated non-null above
	const validAccount = account as {
		id: string;
		threads_user_id: string;
		threads_access_token_encrypted: string;
		username: string | null;
		is_active: boolean;
		token_expires_at: string | null;
	};

	// Detect thread chains
	const isThreadChain = post.content?.includes(CHAIN_SEPARATOR);

	if (isThreadChain) {
		const chainPosts = post.content
			.split(CHAIN_SEPARATOR)
			.map((p: string) => p.trim())
			.filter((p: string) => p.length > 0);

		if (chainPosts.length >= 2) {
			return publishThreadChain(post, validAccount, chainPosts, {
				checkAndIncrementRateLimit,
				getRateLimitStatus,
				handleCrossPost,
			});
		}
		// Malformed chain — fall through to single post
	}

	// Single post validation
	if (!post.content || post.content.trim().length === 0) {
		await db()
			.from("posts")
			.update({
				status: "failed",
				error_message: "Post content is empty. Please edit and reschedule.",
				updated_at: new Date().toISOString(),
			})
			.eq("id", postId);
		return { result: "failed", error: "empty_content" };
	}

	const contentBytes = Buffer.byteLength(post.content, "utf8");
	if (contentBytes > 500) {
		await db()
			.from("posts")
			.update({
				status: "failed",
				error_message: `Content exceeds 500 byte limit (${contentBytes} bytes). Please edit and reschedule.`,
				updated_at: new Date().toISOString(),
			})
			.eq("id", postId);
		return { result: "failed", error: "content_too_long" };
	}

	// Rate limit check (read-only, before claiming)
	const postAccountId =
		typeof post.account_id === "string" ? post.account_id : null;
	if (!postAccountId) {
		await db()
			.from("posts")
			.update({
				status: "failed",
				error_message: "Post is missing an assigned Threads account",
				updated_at: new Date().toISOString(),
			})
			.eq("id", postId);
		return { result: "failed", error: "missing_account_id" };
	}
	const rateStatus = await getRateLimitStatus(postAccountId);
	if (
		rateStatus &&
		(rateStatus.hourlyRemaining <= 0 || rateStatus.dailyRemaining <= 0)
	) {
		return escalateRateLimit(postId, post.user_id, currentSkips);
	}

	// Atomic claim
	const claimQuery = eqOrNull(
		db()
			.from("posts")
			.update({ status: "publishing", updated_at: new Date().toISOString() })
			.eq("id", postId)
			.eq("status", "scheduled"),
		"approval_status",
		"approved",
	);
	const { data: claimed } = await claimQuery.select("id").maybeSingle();

	if (!claimed) {
		return { result: "skipped", error: "claim_failed" };
	}

	// Media URL check — resolve UUIDs to actual URLs first
	let mediaUrls: string[] = post.media_urls || [];
	if (
		mediaUrls.length > 0 &&
		mediaUrls[0] &&
		!mediaUrls[0].startsWith("http")
	) {
		const { resolveMediaUrls } = await import("./handlers/posts/shared.js");
		const { urls } = await resolveMediaUrls(mediaUrls, post.user_id);
		if (urls.length > 0) {
			mediaUrls = urls;
			await db().from("posts").update({ media_urls: urls }).eq("id", postId);
		}
	}
	if (mediaUrls.length > 0) {
		const mediaError = await checkMediaUrlAccessible(mediaUrls);
		if (mediaError) {
			const isTimeout = mediaError.toLowerCase().includes("timed out");
			await db()
				.from("posts")
				.update({
					status: "failed",
					error_message: mediaError,
					updated_at: new Date().toISOString(),
				})
				.eq("id", postId);
			return {
				result: "failed",
				error: isTimeout ? "media_timeout" : "media_inaccessible",
			};
		}
	}

	const media = mediaUrls.map((url: string) => ({
		type: (!url.includes(".mp4") && !url.includes(".mov")
			? "image"
			: "video") as "image" | "video",
		url,
	}));

	// Build post data
	const metadata = getThreadsMetadata(post.metadata);

	// Media spoiler: only when explicitly set in metadata (manually controlled)
	const hasSpoilerMedia = metadata.isSpoiler;

	// Text spoilers: read from post metadata or text_spoilers column
	const textSpoilerEntities =
		metadata.textSpoilers || post.text_spoilers || undefined;

	const postData: PostData = {
		content: post.content,
		media,
		topics: post.hashtags || [],
		topicTag: post.topic_tag || undefined,
		quotePostId: post.quoted_post_id || undefined,
		locationId: post.location_id || undefined,
		pollAttachment: metadata.pollAttachment,
		isSpoiler: hasSpoilerMedia ? true : undefined,
		// Text spoilers re-enabled (2026-03-27) — ghost-posting was caused by auto_publish, not spoilers
		textSpoilers: textSpoilerEntities,
		allowlistedCountryCodes: metadata.allowlistedCountryCodes,
		linkUrl: metadata.linkUrl,
		gifAttachment: metadata.gifAttachment,
		textAttachment: metadata.textAttachment,
		// Cross-share to Instagram Stories
		crossreshareToIg: metadata.crossreshareToIg ? true : undefined,
		crossreshareToIgDarkMode: metadata.crossreshareToIgDarkMode
			? true
			: undefined,
		settings: metadata.settings || {
			allowReplies: true,
			whoCanReply: "everyone",
		},
	};

	const result = await postToThreads(
		validAccount.threads_access_token_encrypted,
		validAccount.threads_user_id,
		postData,
	);

	if (result.success && result.threadId) {
		// Fetch permalink
		let permalink: string | null = null;
		try {
			const token = decrypt(validAccount.threads_access_token_encrypted);
			const resp = await withRetry(
				() =>
					fetch(
						`https://graph.threads.net/v1.0/${result.threadId}?fields=id,permalink`,
						{
							headers: { Authorization: `Bearer ${token}` },
							signal: AbortSignal.timeout(10000),
						},
					),
				{ label: `publishPostPermalink:${result.threadId}` },
			);
			const data = await resp.json();
			if (data.permalink) permalink = data.permalink;
		} catch {
			// Non-critical
		}

		// Atomic update
		const publishQuery = eqOrNull(
			db()
				.from("posts")
				.update({
					status: "published",
					threads_post_id: result.threadId,
					permalink,
					published_at: new Date().toISOString(),
					updated_at: new Date().toISOString(),
				})
				.eq("id", postId)
				.eq("status", "publishing"),
			"approval_status",
			"approved",
		);
		const { data: published } = await publishQuery.select("id");

		if (!published || published.length === 0) {
			return { result: "skipped", error: "status_changed_before_publish" };
		}

		// Notification
		await db()
			.from("notifications")
			.insert({
				user_id: post.user_id,
				type: "post_published",
				title: "Scheduled post published",
				message: `Your scheduled post to @${validAccount.username} has been published.`,
				read: false,
				data: { postId, threadId: result.threadId, permalink },
			});

		// Rate limit increment (post-publish)
		try {
			await checkAndIncrementRateLimit(postAccountId);
		} catch {
			/* non-fatal */
		}

		// Cross-post
		await handleCrossPost(post as CrossPostRecord, "threads");

		// Dispatch delayed engagement fetches (1h + 24h)
		try {
			const { dispatchEngagementFetch } = await import("./qstashSchedule.js");
			await dispatchEngagementFetch(postId, result.threadId, 3600); // 1h
			await dispatchEngagementFetch(postId, result.threadId, 86400); // 24h
		} catch {
			/* non-critical */
		}

		logger.info("[publishPost] Threads OK", {
			postId,
			threadId: result.threadId,
		});
		return { result: "published", threadId: result.threadId };
	}

	// Failure handling
	const errorMsg = result.error || "Unknown publishing error";
	return handleThreadsFailure(post, validAccount, postData, errorMsg, {
		checkAndIncrementRateLimit,
		isTransientError,
	});
}

// ============================================================================
// Thread Chain Publish
// ============================================================================

async function publishThreadChain(
	post: CrossPostRecord & {
		id: string;
		user_id: string;
		account_id?: string | null | undefined;
		metadata?: Record<string, unknown> | null | undefined;
	},
	account: {
		id: string;
		threads_user_id: string;
		threads_access_token_encrypted: string;
		username: string | null;
	},
	chainPosts: string[],
	helpers: {
		checkAndIncrementRateLimit: (id: string) => Promise<{ allowed: boolean }>;
		getRateLimitStatus: (
			id: string,
		) => Promise<{ hourlyRemaining: number; dailyRemaining: number } | null>;
		handleCrossPost: (
			post: CrossPostRecord,
			platform: "threads" | "instagram",
		) => Promise<void>;
	},
): Promise<PublishResult> {
	// Validate chain posts
	const tooLong = chainPosts.find(
		(p: string) => Buffer.byteLength(p, "utf8") > 500,
	);
	if (tooLong) {
		await db()
			.from("posts")
			.update({
				status: "failed",
				error_message: "A post in the thread chain exceeds the 500 byte limit.",
				updated_at: new Date().toISOString(),
			})
			.eq("id", post.id);
		return { result: "failed", error: "chain_post_too_long" };
	}

	// Rate limit check for full chain
	if (!post.account_id) {
		await db()
			.from("posts")
			.update({
				status: "failed",
				error_message: "Thread chain is missing an assigned Threads account",
				updated_at: new Date().toISOString(),
			})
			.eq("id", post.id);
		return { result: "failed", error: "missing_account_id" };
	}

	const rateStatus = await helpers.getRateLimitStatus(post.account_id);
	if (rateStatus) {
		if (
			rateStatus.hourlyRemaining < chainPosts.length ||
			rateStatus.dailyRemaining < chainPosts.length
		) {
			return { result: "skipped", error: "rate_limited_chain" };
		}
	}

	// Atomic claim
	const claimQuery = eqOrNull(
		db()
			.from("posts")
			.update({ status: "publishing", updated_at: new Date().toISOString() })
			.eq("id", post.id)
			.eq("status", "scheduled"),
		"approval_status",
		"approved",
	);
	const { data: claimed } = await claimQuery.select("id").maybeSingle();

	if (!claimed) {
		return { result: "skipped", error: "claim_failed" };
	}

	const postIds: string[] = [];
	try {
		let replyToId: string | null = null;

		for (let ci = 0; ci < chainPosts.length; ci++) {
			const chainPostData: PostData = {
				content: chainPosts[ci]!,
				replyToId: replyToId || undefined,
				settings: { allowReplies: true, whoCanReply: "everyone" },
			};

			// Retry chain posts up to 3 times (propagation delay can vary)
			let result: Awaited<ReturnType<typeof postToThreads>> | null = null;
			for (let attempt = 0; attempt < 3; attempt++) {
				result = await postToThreads(
					account.threads_access_token_encrypted,
					account.threads_user_id,
					chainPostData,
				);
				if (result.success && result.threadId) break;
				// Only retry "resource does not exist" for post 2+ (propagation lag)
				if (ci > 0 && result.error?.includes("does not exist") && attempt < 2) {
					await new Promise((resolve) => setTimeout(resolve, 5000));
					continue;
				}
				break;
			}

			if (!result?.success || !result?.threadId) {
				throw new Error(
					`Failed to publish thread post ${ci + 1}: ${result?.error || "Unknown error"}`,
				);
			}

			const parentThreadId = result.threadId;
			postIds.push(parentThreadId);
			replyToId = parentThreadId;

			// Wait for parent post to propagate before creating the reply container.
			// 5s base delay + verify the parent container is FINISHED to avoid
			// "resource does not exist" errors on reply_to_id.
			// Reduced from 8s — Meta propagation is typically <5s, and the retry
			// loop (3 attempts × 5s backoff) catches slow propagation cases.
			if (ci < chainPosts.length - 1) {
				await new Promise((resolve) => setTimeout(resolve, 5000));

				// Verify parent post is queryable before proceeding
				try {
					const token = decrypt(account.threads_access_token_encrypted);
					const parentStatusRes = await withRetry(
						() =>
							fetch(
								`https://graph.threads.net/v1.0/${parentThreadId}?fields=id`,
								{
									headers: { Authorization: `Bearer ${token}` },
									signal: AbortSignal.timeout(8000),
								},
							),
						{ label: `publishPostParentStatus:${parentThreadId}` },
					);
					if (!parentStatusRes.ok) {
						// Parent not yet visible — add extra delay
						logger.info(
							"[publishPost] Parent post not yet visible, extra delay",
							{
								parentId: parentThreadId,
								status: parentStatusRes.status,
							},
						);
						await new Promise((resolve) => setTimeout(resolve, 5000));
					}
				} catch {
					// Verification failed — add safety delay
					await new Promise((resolve) => setTimeout(resolve, 3000));
				}
			}
		}

		// Mark as published
		const publishQuery = eqOrNull(
			db()
				.from("posts")
				.update({
					status: "published",
					threads_post_id: postIds[0],
					content: chainPosts[0],
					published_at: new Date().toISOString(),
					updated_at: new Date().toISOString(),
				})
				.eq("id", post.id)
				.eq("status", "publishing"),
			"approval_status",
			"approved",
		);
		const { data: published } = await publishQuery.select("id");

		if (!published || published.length === 0) {
			return {
				result: "skipped",
				error: "status_changed_before_chain_publish",
			};
		}

		// Rate limit increment for all chain posts
		try {
			for (let ri = 0; ri < chainPosts.length; ri++) {
				await helpers.checkAndIncrementRateLimit(post.account_id);
			}
		} catch {
			/* non-fatal */
		}

		await helpers.handleCrossPost(post, "threads");

		logger.info("[publishPost] Chain OK", {
			postId: post.id,
			chainLength: chainPosts.length,
		});
		return { result: "published", threadId: postIds[0] };
	} catch (chainError: unknown) {
		const errorMsg =
			chainError instanceof Error ? chainError.message : String(chainError);
		const existingMeta = (post.metadata as Record<string, unknown>) || {};
		const updatedMeta = {
			...existingMeta,
			...(postIds.length > 0
				? {
						partial_chain_failure: true,
						orphaned_thread_ids: postIds,
						published_count: postIds.length,
						total_chain_length: chainPosts.length,
					}
				: {}),
		};

		await db()
			.from("posts")
			.update({
				status: "failed",
				error_message:
					postIds.length > 0
						? `${errorMsg} | Partially published: ${postIds.length}/${chainPosts.length} posts`
						: errorMsg,
				metadata: updatedMeta,
				updated_at: new Date().toISOString(),
			})
			.eq("id", post.id);

		return { result: "failed", error: errorMsg };
	}
}

// ============================================================================
// Threads Failure Handler (inline token refresh, transient retry)
// ============================================================================

async function handleThreadsFailure(
	post: CrossPostRecord & {
		id: string;
		user_id: string;
		account_id?: string | null | undefined;
		retry_count?: number | null | undefined;
	},
	account: {
		id: string;
		threads_user_id: string;
		threads_access_token_encrypted: string;
		username: string | null;
	},
	postData: PostData,
	errorMsg: string,
	helpers: {
		checkAndIncrementRateLimit: (id: string) => Promise<{ allowed: boolean }>;
		isTransientError: (msg: string) => boolean;
	},
): Promise<PublishResult> {
	const { isDefinitiveOAuthError } = await import("./retryUtils.js");
	const isTokenError = isDefinitiveOAuthError(errorMsg);

	if (isTokenError) {
		// Attempt inline token refresh
		try {
			const currentToken = decrypt(account.threads_access_token_encrypted);
			const refreshResult = await refreshThreadsToken(currentToken);
			const refreshData = refreshResult.data;

			if (refreshResult.ok && refreshData.access_token) {
				const { encrypt } = await import("./encryption.js");
				const newEncryptedToken = encrypt(refreshData.access_token as string);
				const expiresIn = refreshData.expires_in || 5184000;

				await db()
					.from("accounts")
					.update({
						threads_access_token_encrypted: newEncryptedToken,
						token_expires_at: new Date(
							Date.now() + expiresIn * 1000,
						).toISOString(),
						updated_at: new Date().toISOString(),
					})
					.eq("id", account.id);

				const retryResult = await postToThreads(
					newEncryptedToken,
					account.threads_user_id,
					postData,
				);

				if (retryResult.success && retryResult.threadId) {
					const retryPublishQuery = eqOrNull(
						db()
							.from("posts")
							.update({
								status: "published",
								threads_post_id: retryResult.threadId,
								published_at: new Date().toISOString(),
								updated_at: new Date().toISOString(),
							})
							.eq("id", post.id)
							.eq("status", "publishing"),
						"approval_status",
						"approved",
					);
					await retryPublishQuery;

					if (post.account_id) {
						try {
							await helpers.checkAndIncrementRateLimit(post.account_id);
						} catch {
							/* non-fatal */
						}
					}

					logger.info("[publishPost] Published after inline token refresh", {
						postId: post.id,
					});
					return { result: "published", threadId: retryResult.threadId };
				}
			}
		} catch (refreshErr) {
			const refreshErrorMsg =
				refreshErr instanceof Error ? refreshErr.message : String(refreshErr);
			logger.error("[publishPost] Inline token refresh failed", {
				postId: post.id,
				error: refreshErrorMsg,
			});
			if (!isDefinitiveOAuthError(refreshErrorMsg)) {
				const currentRetryCount = (post.retry_count as number) || 0;
				if (currentRetryCount < 3) {
					await db()
						.from("posts")
						.update({
							status: "scheduled",
							scheduled_for: new Date(
								Date.now() + 15 * 60 * 1000,
							).toISOString(),
							retry_count: currentRetryCount + 1,
							error_message: null,
							updated_at: new Date().toISOString(),
						})
						.eq("id", post.id);

					return {
						result: "rescheduled",
						error: `token_refresh_transient: ${refreshErrorMsg}`,
					};
				}
			}
		}

		// Token refresh failed — flag account + deactivate
		await db()
			.from("accounts")
			.update({
				status: "needs_reauth",
				needs_reauth: true,
				is_active: false,
				updated_at: new Date().toISOString(),
			})
			.eq("id", account.id);

		await db()
			.from("posts")
			.update({
				status: "failed",
				error_message:
					"Account token expired. Please reconnect your account in Settings.",
				updated_at: new Date().toISOString(),
			})
			.eq("id", post.id);

		deliverNotification({
			userId: post.user_id,
			type: "token_reauth_needed",
			title: "Threads account needs reconnection",
			message:
				"Your scheduled post couldn't publish because the access token expired. Please reconnect your account in Settings.",
			data: { postId: post.id, accountId: account.id },
		}).catch((error) => {
			logger.warn("[publishPost] Failed to deliver reauth notification", {
				postId: post.id,
				accountId: account.id,
				error: String(error),
			});
		});

		return { result: "failed", error: "token_expired" };
	}

	// Transient error — auto-reschedule
	const currentRetryCount = (post.retry_count as number) || 0;
	if (helpers.isTransientError(errorMsg) && currentRetryCount < 3) {
		await db()
			.from("posts")
			.update({
				status: "scheduled",
				scheduled_for: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
				retry_count: currentRetryCount + 1,
				error_message: null,
				updated_at: new Date().toISOString(),
			})
			.eq("id", post.id);

		return { result: "rescheduled", error: `transient: ${errorMsg}` };
	}

	// Permanent failure
	await db()
		.from("posts")
		.update({
			status: "failed",
			error_message: errorMsg,
			updated_at: new Date().toISOString(),
		})
		.eq("id", post.id);

	await db()
		.from("notifications")
		.insert({
			user_id: post.user_id,
			type: "post_failed",
			title: "Scheduled post failed",
			message: `Failed to publish scheduled post: ${errorMsg}`,
			read: false,
			data: { postId: post.id, error: errorMsg },
		});

	deliverNotification({
		userId: post.user_id,
		type: "post_failed",
		title: "Scheduled post failed",
		message: `Failed to publish scheduled post: ${errorMsg}`,
		data: { postId: post.id, error: errorMsg },
	}).catch((error) => {
		logger.warn("[publishPost] Failed to deliver failure notification", {
			postId: post.id,
			error: String(error),
		});
	});

	return { result: "failed", error: errorMsg };
}

// ============================================================================
// Instagram Publish
// ============================================================================

async function publishInstagramPost(postId: string): Promise<PublishResult> {
	const { handleCrossPost, checkMediaUrlAccessible, isTransientError } =
		await import("./cron/scheduled-posts.js");

	const { postToInstagram } = await import("./instagramApi.js");
	let stage = "entered";
	try {
		logger.info("[publishPost] Instagram publish entered", { postId });

		// Load post with joined IG account data
		stage = "load_post";
		logger.info("[publishPost] Instagram load start", { postId });
		const igLoadQuery = eqOrNull(
			db()
				.from("posts")
				.select(`
			id, user_id, instagram_account_id, content, media_urls,
			ig_media_type, alt_text, location_id, metadata, scheduled_for, retry_count,
			instagram_accounts!inner (
				id, instagram_user_id, instagram_access_token_encrypted,
				facebook_page_access_token_encrypted, username, login_type,
				is_active, status, needs_reauth, token_expires_at, follower_count
			)
		`)
				.eq("id", postId)
				.eq("status", "scheduled")
				.eq("platform", "instagram"),
			"approval_status",
			"approved",
		);
		const { data: post, error: loadErr } = await igLoadQuery.maybeSingle();
		logger.info("[publishPost] Instagram load result", {
			postId,
			found: !!post,
			hasError: !!loadErr,
			error: loadErr ? String(loadErr.message || loadErr) : null,
			status: (post as { status?: string } | null)?.status ?? null,
			scheduledFor:
				(post as { scheduled_for?: string | null } | null)?.scheduled_for ??
				null,
		});

		if (loadErr || !post) {
			return { result: "skipped", error: "not_found_or_not_scheduled" };
		}
		if (isPreviewScheduleOnly(post.metadata)) {
			logger.info("[publishPost] Skipping preview-only Instagram post", {
				postId,
			});
			return { result: "skipped", error: "preview_schedule_only" };
		}

		const igAccount = (post as Record<string, unknown>).instagram_accounts as {
			id: string;
			instagram_user_id: string;
			instagram_access_token_encrypted: string;
			facebook_page_access_token_encrypted: string | null;
			login_type: string | null;
			username: string | null;
				is_active: boolean;
				status: string | null;
				needs_reauth: boolean | null;
				token_expires_at: string | null;
				follower_count?: number | null;
			} | null;

		const loginType = igAccount?.login_type || "facebook";
		logger.info("[publishPost] Instagram account loaded", {
			postId,
			hasAccount: !!igAccount,
			accountId: igAccount?.id ?? null,
			username: igAccount?.username ?? null,
			loginType,
			isActive: igAccount?.is_active ?? null,
			status: igAccount?.status ?? null,
			needsReauth: igAccount?.needs_reauth ?? null,
			hasAccessToken: !!igAccount?.instagram_access_token_encrypted,
			hasPlatformUserId: !!igAccount?.instagram_user_id,
		});

		const igMaxSkipRetries = 3;
		const igCurrentSkips = (post.retry_count as number) || 0;

		if (igAccount) {
			stage = "account_eligibility";
			const igEligibility = isAccountPublishable(igAccount);
			logger.info("[publishPost] Instagram account eligibility result", {
				postId,
				eligible: igEligibility.eligible,
				reason: igEligibility.reason ?? null,
			});
			if (!igEligibility.eligible) {
				const eligibilityReason = getEligibilityReason(igEligibility.reason);
				const igMessages: Record<string, string> = {
					account_inactive:
						"Instagram account is inactive. Please reactivate the account or reassign the post.",
					needs_reauth:
						"Instagram account token expired. Please reconnect in Settings.",
					suspended:
						"Instagram account is suspended due to a content policy violation.",
					token_expired:
						"Instagram account token expired. Please reconnect in Settings.",
				};
				return escalateSkip(
					postId,
					post.user_id,
					igCurrentSkips,
					igMaxSkipRetries,
					eligibilityReason,
					igMessages[eligibilityReason] ||
						"Instagram account is not eligible to publish.",
				);
			}
		}

		if (!igAccount?.instagram_access_token_encrypted) {
			await db()
				.from("posts")
				.update({
					status: "failed",
					error_message: "Instagram account not properly configured",
					updated_at: new Date().toISOString(),
				})
				.eq("id", postId);
			return { result: "failed", error: "account_not_configured" };
		}

		const igMeta = metadataRecord((post as Record<string, unknown>).metadata);
		const trialIntent = resolveInstagramTrialReelIntent({
			metadata: igMeta,
			trialGraduationStrategy:
				metadataString(igMeta, "trialGraduationStrategy") || undefined,
		});
		const igContent = campaignFactoryInstagramPostCaption(
			post as Record<string, unknown>,
			igMeta,
		);
		// Content validation
		const igMaxChars = maxBodyChars("instagram");
		if (igContent.length > igMaxChars) {
			await db()
				.from("posts")
				.update({
					status: "failed",
					error_message: `Caption exceeds ${igMaxChars} character limit (${igContent.length} chars). Please edit and reschedule.`,
					updated_at: new Date().toISOString(),
				})
				.eq("id", postId);
			return { result: "failed", error: "caption_too_long" };
		}

		const mediaAltTexts = (igMeta.mediaAltTexts as string[] | undefined) || [];
		const preClaimMediaUrls = Array.isArray(post.media_urls)
			? post.media_urls
			: [];
		const preClaimMediaType =
			post.ig_media_type ||
			(preClaimMediaUrls.length > 1
				? "CAROUSEL"
				: preClaimMediaUrls.length === 1
					? "REELS"
					: "IMAGE");
		stage = "preclaim_preflight";
		logger.info("[publishPost] Instagram preclaim preflight start", {
			postId,
			mediaCount: preClaimMediaUrls.length,
			mediaType: preClaimMediaType,
			hasTrialReels: metadataBoolean(igMeta, "trialReels") === true,
		});
		const preClaimPreflight = await runPublishPreflight(
			{
				platform: "instagram",
				mode: "api",
				instagramAccountId: post.instagram_account_id,
				content: igContent,
				igMediaType: preClaimMediaType,
				media: preClaimMediaUrls.map((url: string, index: number) => ({
					type:
						preClaimMediaType === "REELS" || preClaimMediaType === "VIDEO"
							? "video"
							: /\.(mp4|mov)(\?|$)/i.test(url)
								? "video"
								: "image",
					url,
					altText: mediaAltTexts[index] || post.alt_text || undefined,
				})),
				collaborators: metadataArray<string>(igMeta, "collaborators"),
				isTrialReel: metadataBoolean(igMeta, "trialReels"),
				trialReels: metadataBoolean(igMeta, "trialReels"),
				instagramTrialReels: trialIntent.enabled ? true : undefined,
				trialGraduationStrategy: trialIntent.strategy,
				brandedContentSponsorIds: metadataArray<string>(
					igMeta,
					"brandedContentSponsorIds",
				),
				isPaidPartnership: metadataBoolean(igMeta, "isPaidPartnership"),
				coverUrl: metadataString(igMeta, "coverUrl"),
				shareToFeed: metadataBoolean(igMeta, "shareToFeed"),
				userTags: metadataArray(igMeta, "userTags"),
				productTags: metadataArray(igMeta, "productTags"),
				thumbOffset: metadataNumber(igMeta, "thumbOffset"),
				audioName: metadataString(igMeta, "audioName"),
				igAudioId: metadataString(igMeta, "igAudioId"),
				commentEnabled: metadataBoolean(igMeta, "commentEnabled"),
				firstComment: metadataString(igMeta, "firstComment"),
				metadata: igMeta,
			},
			{
				account: {
					found: !!igAccount,
					isActive: igAccount?.is_active,
					needsReauth: igAccount?.needs_reauth,
					status: igAccount?.status,
					tokenExpiresAt: igAccount?.token_expires_at,
					hasAccessToken: !!igAccount?.instagram_access_token_encrypted,
					hasPlatformUserId: !!igAccount?.instagram_user_id,
					loginType: igAccount?.login_type,
					followerCount: igAccount?.follower_count,
				},
				checkMediaUrls: false,
			},
		);
		logger.info("[publishPost] Instagram preclaim preflight result", {
			postId,
			ok: preClaimPreflight.ok,
			summary: preClaimPreflight.summary,
			issues: preflightIssueSummary(preClaimPreflight),
		});
		if (!preClaimPreflight.ok) {
			const message =
				preClaimPreflight.issues.find((issue) => issue.severity === "error")
					?.message || "Scheduled Instagram post failed preflight.";
			await db()
				.from("posts")
				.update({
					status: "failed",
					error_message: message,
					updated_at: new Date().toISOString(),
				})
				.eq("id", postId)
				.eq("status", "scheduled");
			await db()
				.from("notifications")
				.insert({
					user_id: post.user_id,
					type: "post_failed",
					title: "Instagram post failed preflight",
					message,
					read: false,
					data: { postId, platform: "instagram", preflight: preClaimPreflight },
				});
			return { result: "failed", error: "publish_preflight_failed" };
		}

		// IG rate limit
		stage = "ig_rate_limit";
		logger.info("[publishPost] Instagram rate limit start", {
			postId,
			instagramAccountId: igAccount.id,
		});
		const igRate = await checkIGRateLimit(igAccount.id);
		logger.info("[publishPost] Instagram rate limit result", {
			postId,
			allowed: igRate?.allowed ?? null,
			reason: igRate?.reason ?? null,
		});
		if (!igRate?.allowed) {
			return escalateRateLimit(postId, post.user_id, igCurrentSkips);
		}

		// Atomic claim
		stage = "atomic_claim";
		logger.info("[publishPost] Instagram atomic claim attempted", { postId });
		const { data: claimed, error: claimErr } = await db()
			.from("posts")
			.update({
				status: "publishing",
				ig_publish_attempts: 1,
				updated_at: new Date().toISOString(),
			})
			.eq("id", postId)
			.eq("status", "scheduled")
			.select("id")
			.maybeSingle();
		logger.info("[publishPost] Instagram atomic claim result", {
			postId,
			claimed: !!claimed,
			error: claimErr ? String(claimErr.message || claimErr) : null,
		});

		if (!claimed) {
			return { result: "skipped", error: "claim_failed" };
		}

		let mediaUrls = post.media_urls || [];

		// Resolve media UUIDs to actual URLs
		if (
			mediaUrls.length > 0 &&
			mediaUrls[0] &&
			!mediaUrls[0].startsWith("http")
		) {
			const { resolveMediaUrls } = await import("./handlers/posts/shared.js");
			const { urls } = await resolveMediaUrls(mediaUrls, post.user_id);
			if (urls.length > 0) {
				mediaUrls = urls;
				await db().from("posts").update({ media_urls: urls }).eq("id", postId);
			}
		}

		// Story validation
		if (post.ig_media_type === "STORIES" && mediaUrls.length === 0) {
			await db()
				.from("posts")
				.update({
					status: "failed",
					error_message: "Instagram Stories require an image or video.",
					updated_at: new Date().toISOString(),
				})
				.eq("id", postId);
			return { result: "failed", error: "story_no_media" };
		}

		// Media URL check
		if (mediaUrls.length > 0) {
			const mediaError = await checkMediaUrlAccessible(mediaUrls);
			if (mediaError) {
				const isTimeout = mediaError.toLowerCase().includes("timed out");
				await db()
					.from("posts")
					.update({
						status: "failed",
						error_message: mediaError,
						updated_at: new Date().toISOString(),
					})
					.eq("id", postId);
				return {
					result: "failed",
					error: isTimeout ? "media_timeout" : "media_inaccessible",
				};
			}
		}

		const resolvedMediaType =
			post.ig_media_type ||
			(mediaUrls.length > 1
				? "CAROUSEL"
				: mediaUrls.length === 1
					? /\.(mp4|mov)(\?|$)/i.test(mediaUrls[0])
						? "REELS"
						: "IMAGE"
					: "IMAGE");
		const firstMediaIsVideo = mediaUrls[0]
			? /\.(mp4|mov)(\?|$)/i.test(mediaUrls[0])
			: false;

		const preflight = await runPublishPreflight(
			{
				platform: "instagram",
				mode: "api",
				instagramAccountId: post.instagram_account_id,
				content: igContent,
				igMediaType: resolvedMediaType,
				media: mediaUrls.map((url: string, index: number) => ({
					type: /\.(mp4|mov)(\?|$)/i.test(url) ? "video" : "image",
					url,
					altText: mediaAltTexts[index] || post.alt_text || undefined,
				})),
				collaborators: metadataArray<string>(igMeta, "collaborators"),
				isTrialReel: metadataBoolean(igMeta, "trialReels"),
				trialReels: metadataBoolean(igMeta, "trialReels"),
				instagramTrialReels: trialIntent.enabled ? true : undefined,
				trialGraduationStrategy: trialIntent.strategy,
				brandedContentSponsorIds: metadataArray<string>(
					igMeta,
					"brandedContentSponsorIds",
				),
				isPaidPartnership: metadataBoolean(igMeta, "isPaidPartnership"),
				coverUrl: metadataString(igMeta, "coverUrl"),
				shareToFeed: metadataBoolean(igMeta, "shareToFeed"),
				userTags: metadataArray(igMeta, "userTags"),
				productTags: metadataArray(igMeta, "productTags"),
				thumbOffset: metadataNumber(igMeta, "thumbOffset"),
				audioName: metadataString(igMeta, "audioName"),
				igAudioId: metadataString(igMeta, "igAudioId"),
				commentEnabled: metadataBoolean(igMeta, "commentEnabled"),
				firstComment: metadataString(igMeta, "firstComment"),
				metadata: igMeta,
			},
			{
				account: {
					found: !!igAccount,
					isActive: igAccount?.is_active,
					needsReauth: igAccount?.needs_reauth,
					status: igAccount?.status,
					tokenExpiresAt: igAccount?.token_expires_at,
					hasAccessToken: !!igAccount?.instagram_access_token_encrypted,
					hasPlatformUserId: !!igAccount?.instagram_user_id,
					loginType: igAccount?.login_type,
					followerCount: igAccount?.follower_count,
				},
				checkMediaUrls: false,
			},
		);
		logger.info("[publishPost] Instagram final preflight result", {
			postId,
			ok: preflight.ok,
			summary: preflight.summary,
			issues: preflightIssueSummary(preflight),
		});
		if (!preflight.ok) {
			const message =
				preflight.issues.find((issue) => issue.severity === "error")?.message ||
				"Scheduled Instagram post failed preflight.";
			await db()
				.from("posts")
				.update({
					status: "failed",
					error_message: message,
					updated_at: new Date().toISOString(),
				})
				.eq("id", postId)
				.eq("status", "scheduled");
			await db()
				.from("notifications")
				.insert({
					user_id: post.user_id,
					type: "post_failed",
					title: "Instagram post failed preflight",
					message,
					read: false,
					data: { postId, platform: "instagram", preflight },
				});
			return { result: "failed", error: "publish_preflight_failed" };
		}

		const igPostData = {
			caption: igContent,
			mediaType: resolvedMediaType as import("./instagramApi.js").IGMediaType,
			imageUrl:
				resolvedMediaType !== "CAROUSEL" &&
				mediaUrls[0] &&
				!(
					resolvedMediaType === "REELS" ||
					resolvedMediaType === "VIDEO" ||
					(resolvedMediaType === "STORIES" && firstMediaIsVideo)
				)
					? mediaUrls[0]
					: undefined,
			videoUrl:
				resolvedMediaType === "REELS" ||
				resolvedMediaType === "VIDEO" ||
				(resolvedMediaType === "STORIES" && firstMediaIsVideo)
					? mediaUrls[0]
					: undefined,
			altText: post.alt_text || undefined,
			locationId:
				((post as Record<string, unknown>).location_id as string) || undefined,
			collaborators: (igMeta.collaborators as string[]) || undefined,
			coverUrl: (igMeta.coverUrl as string) || undefined,
			shareToFeed:
				igMeta.shareToFeed !== undefined
					? (igMeta.shareToFeed as boolean)
					: undefined,
			userTags:
				(igMeta.userTags as Array<{
					username: string;
					x: number;
					y: number;
				}>) || undefined,
			trialReels:
				trialIntent.enabled && resolvedMediaType === "REELS" ? true : undefined,
			trialGraduationStrategy:
				trialIntent.enabled && resolvedMediaType === "REELS"
					? trialIntent.strategy
					: undefined,
			thumbOffset: (igMeta.thumbOffset as number) || undefined,
			audioName: (igMeta.audioName as string) || undefined,
			igAudioId: (igMeta.igAudioId as string) || undefined,
			productTags:
				(igMeta.productTags as Array<{
					product_id: string;
					x?: number | undefined;
					y?: number | undefined;
				}>) || undefined,
			commentEnabled:
				igMeta.commentEnabled !== undefined
					? (igMeta.commentEnabled as boolean)
					: undefined,
			firstComment: (igMeta.firstComment as string) || undefined,
			children:
				resolvedMediaType === "CAROUSEL"
					? mediaUrls.map((url: string, index: number) => ({
							type: (url.match(/\.(mp4|mov|avi)$/i) ? "video" : "image") as
								| "video"
								| "image",
							url,
							altText: mediaAltTexts[index] || undefined,
						}))
					: undefined,
		};

		stage = "post_to_instagram";
		logger.info("[publishPost] Instagram API publish start", {
			postId,
			mediaType: igPostData.mediaType,
			hasImageUrl: !!igPostData.imageUrl,
			hasVideoUrl: !!igPostData.videoUrl,
			childrenCount: igPostData.children?.length ?? 0,
			trialReels: igPostData.trialReels === true,
		});
		const igResult = await postToInstagram(
			igAccount.instagram_access_token_encrypted,
			igAccount.instagram_user_id,
			igPostData,
			igAccount.facebook_page_access_token_encrypted || undefined,
			loginType,
		);
		logger.info("[publishPost] Instagram API publish result", {
			postId,
			success: igResult.success,
			hasMediaId: !!igResult.mediaId,
			hasContainerId: !!igResult.containerId,
			error: igResult.error ?? null,
			retryable: igResult.retryable ?? null,
		});

		if (igResult.success && igResult.mediaId) {
			const { data: published } = await db()
				.from("posts")
				.update({
					status: "published",
					instagram_post_id: igResult.mediaId,
					permalink: igResult.permalink || null,
					published_at: new Date().toISOString(),
					ig_container_status: "PUBLISHED",
					updated_at: new Date().toISOString(),
				} as Record<string, unknown>)
				.eq("id", postId)
				.eq("status", "publishing")
				.select("id");

			if (!published || published.length === 0) {
				return { result: "skipped", error: "status_changed_before_publish" };
			}

			await db()
				.from("notifications")
				.insert({
					user_id: post.user_id,
					type: "post_published",
					title: "Instagram post published",
					message: `Your scheduled post to @${igAccount.username} on Instagram has been published.`,
					read: false,
					data: {
						postId,
						mediaId: igResult.mediaId,
						permalink: igResult.permalink,
						platform: "instagram",
					},
				});

			await handleCrossPost(
				{
					id: post.id,
					user_id: post.user_id,
					content: post.content,
					media_urls: post.media_urls,
					media_type: post.ig_media_type || null,
					metadata: post.metadata ?? null,
					account_id: post.instagram_account_id || undefined,
				},
				"instagram",
			);

			// Schedule engagement syncs at 1h, 6h, 24h (fire-and-forget)
			import("./qstashSchedule.js").then(({ schedulePostPublishSyncs }) =>
				schedulePostPublishSyncs(
					postId,
					igAccount.id,
					post.user_id,
					"instagram",
					"qstash",
				),
			);

			logger.info("[publishPost] IG OK", { postId, mediaId: igResult.mediaId });
			return { result: "published", mediaId: igResult.mediaId };
		}

		if (igResult.containerId) {
			// Container created but not finished — save for ig-container-publisher cron
			await db()
				.from("posts")
				.update({
					ig_container_id: igResult.containerId,
					ig_container_created_at: new Date().toISOString(),
					ig_container_status: "IN_PROGRESS",
					updated_at: new Date().toISOString(),
				})
				.eq("id", postId);

			logger.info("[publishPost] IG container pending", {
				postId,
				containerId: igResult.containerId,
			});
			return { result: "container_pending" };
		}

		// Failure
		const igErrorMsg = igResult.error || "Unknown IG publishing error";
		const igRetryCount = (post.retry_count as number) || 0;

		if (
			shouldRescheduleInstagramFailure(igResult, igRetryCount, isTransientError)
		) {
			await db()
				.from("posts")
				.update({
					status: "scheduled",
					scheduled_for: new Date(Date.now() + 15 * 60 * 1000).toISOString(),
					retry_count: igRetryCount + 1,
					error_message: null,
					updated_at: new Date().toISOString(),
				})
				.eq("id", postId);

			return { result: "rescheduled", error: `transient: ${igErrorMsg}` };
		}

		await db()
			.from("posts")
			.update({
				status: "failed",
				error_message: igErrorMsg,
				updated_at: new Date().toISOString(),
			})
			.eq("id", postId);

		await db()
			.from("notifications")
			.insert({
				user_id: post.user_id,
				type: "post_failed",
				title: "Instagram post failed",
				message: `Failed to publish scheduled Instagram post: ${igErrorMsg}`,
				read: false,
				data: { postId, error: igErrorMsg, platform: "instagram" },
			});

		deliverNotification({
			userId: post.user_id,
			type: "post_failed",
			title: "Instagram post failed",
			message: `Failed to publish scheduled Instagram post: ${igErrorMsg}`,
			data: { postId, error: igErrorMsg, platform: "instagram" },
		}).catch((error) => {
			logger.warn(
				"[publishPost] Failed to deliver Instagram failure notification",
				{
					postId,
					error: String(error),
				},
			);
		});

		return { result: "failed", error: igErrorMsg };
	} catch (err) {
		logger.error("[publishPost] Instagram publish exception", {
			postId,
			stage,
			error: exceptionDetails(err),
		});
		throw err;
	}
}
