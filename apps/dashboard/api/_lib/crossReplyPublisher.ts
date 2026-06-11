// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Cross-Account Reply Publisher
 *
 * After a successful autoposter publish, a DIFFERENT account from the
 * same group can reply to the post — simulating organic engagement.
 *
 * - Template-based replies (no AI calls)
 * - Daily limit per account (max 5 cross-replies/day) via Redis
 * - Fire-and-forget: errors never block the main publish flow
 * - Dispatched via QStash with 30-60s delay to look natural
 */

import { decrypt } from "./encryption.js";
import { logger } from "./logger.js";
import {
	enforceOutboundOperatorGuard,
	recordOutboundOperatorResult,
} from "./outboundOperatorGuard.js";
import { getRedis } from "./redis.js";
import { withRetry } from "./retryUtils.js";
import { getSupabase } from "./supabase.js";

const THREADS_API_BASE = "https://graph.threads.net/v1.0";
const API_TIMEOUT = 10_000;

/** Max cross-replies any single account can send per day */
const MAX_CROSS_REPLIES_PER_ACCOUNT_PER_DAY = 5;

/** Redis TTL for daily counter */
const COUNTER_TTL = 86_400;

// ---------------------------------------------------------------------------
// Cross-Reply Templates — short casual reactions from a "different person"
// ---------------------------------------------------------------------------

const TEMPLATES_AGREE = [
	"this is so true",
	"literally",
	"no bc this is actually so real",
	"say it louder",
	"finally someone gets it",
	"facts",
];

const TEMPLATES_HYPE = [
	"ok go off",
	"you didn't have to snap like this",
	"the way this hit",
	"screenshotting this",
	"this >>",
	"underrated take fr",
];

const TEMPLATES_QUESTION_REACT = [
	"omg wait same",
	"ok but mine is embarrassing",
	"literally been thinking about this",
	"this is such a good question",
	"save this i need to come back to it",
];

const TEMPLATES_RELATABLE = [
	"why is this so accurate",
	"felt this ngl",
	"did you just read my mind",
	"ok i feel seen",
	"this is too real",
];

const ALL_TEMPLATES = [
	...TEMPLATES_AGREE,
	...TEMPLATES_HYPE,
	...TEMPLATES_RELATABLE,
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface CrossReplyPayload {
	queueItemId: string;
	workspaceId: string;
	groupId: string;
	ownerId: string;
	targetAccountId: string;
	targetThreadsPostId: string;
	postContent: string;
}

interface CrossReplyResult {
	success: boolean;
	replierAccountId?: string | undefined;
	replyThreadsId?: string | undefined;
	error?: string | undefined;
}

// ---------------------------------------------------------------------------
// Core
// ---------------------------------------------------------------------------

/**
 * Execute a cross-reply: pick a different account from the group,
 * post a template reply to the target post, record in DB.
 */
export async function executeCrossReply(
	payload: CrossReplyPayload,
): Promise<CrossReplyResult> {
	const {
		queueItemId,
		workspaceId,
		groupId,
		ownerId,
		targetAccountId,
		targetThreadsPostId,
		postContent,
	} = payload;

	const db = getSupabase();
	const redis = getRedis();

	// 1. Load eligible accounts from the same group (exclude the poster)
	// Use account_groups.account_ids as source of truth (not accounts.group_id)
	const { data: _grpRow } = await db
		.from("account_groups")
		.select("account_ids")
		.eq("id", groupId)
		.maybeSingle();
	const _grpAccountIds = (_grpRow?.account_ids || []) as string[];
	const { data: groupAccounts } =
		_grpAccountIds.length > 0
			? await db
					.from("accounts")
					.select(
						"id, username, threads_user_id, threads_access_token_encrypted, is_active, needs_reauth, is_retired",
					)
					.in("id", _grpAccountIds)
					.eq("user_id", ownerId)
					.neq("id", targetAccountId)
					.not("threads_access_token_encrypted", "is", null)
			: { data: [] };

	const eligible = (groupAccounts || []).filter(
		(a: Record<string, unknown>) =>
			a.is_active !== false && !a.needs_reauth && !a.is_retired,
	);

	if (eligible.length === 0) {
		return { success: false, error: "no_other_accounts" };
	}

	// 2. Shuffle and find one under the daily limit
	const shuffled = [...eligible].sort(() => Math.random() - 0.5);
	const dateKey = new Date().toISOString().split("T")[0]!;

	// biome-ignore lint/suspicious/noExplicitAny: Supabase partial select
	let replier: any = null;

	for (const candidate of shuffled) {
		const counterKey = `cross-reply:${candidate.id}:${dateKey}`;
		const count = (await redis.get(counterKey)) as number | null;
		if ((count ?? 0) >= MAX_CROSS_REPLIES_PER_ACCOUNT_PER_DAY) continue;

		replier = candidate;
		break;
	}

	if (!replier) {
		return { success: false, error: "all_at_daily_limit" };
	}

	// 3. Pick a contextual reply
	const replyText = pickCrossReply(postContent);
	const outboundPayload = {
		queueItemId,
		targetAccountId,
		targetThreadsPostId,
		replierAccountId: replier.id,
		replyText,
		source: "cross-reply-publish",
	};
	const outboundGuard = await enforceOutboundOperatorGuard({
		db,
		userId: ownerId,
		actionName: "cross_reply",
		riskLevel: "high",
		scope: {
			workspaceId,
			groupId,
			accountId: replier.id,
		},
		payload: outboundPayload,
		idempotencyKey: `cross-reply:${queueItemId}:${replier.id}`,
		metadata: {
			queueItemId,
			targetAccountId,
			targetThreadsPostId,
			source: "cross-reply-publish",
		},
	});
	if (!outboundGuard.allowed) {
		logger.warn("[crossReply] Blocked by outbound operator guard", {
			queueItemId,
			replierAccountId: replier.id,
			code: outboundGuard.code,
			reason: outboundGuard.reason,
		});
		return {
			success: false,
			replierAccountId: replier.id,
			error: outboundGuard.code,
		};
	}

	// 4. Decrypt token and publish the reply
	let token: string;
	try {
		token = decrypt(replier.threads_access_token_encrypted);
	} catch {
		await recordOutboundOperatorResult({
			db,
			userId: ownerId,
			actionName: "cross_reply",
			riskLevel: "high",
			scope: { workspaceId, groupId, accountId: replier.id },
			payload: outboundPayload,
			idempotencyKey: `cross-reply:${queueItemId}:${replier.id}`,
			outcome: "failure",
			message: "token decrypt failed",
			error: "token_decrypt_failed",
			metadata: { queueItemId, source: "cross-reply-publish" },
		});
		return { success: false, error: "token_decrypt_failed" };
	}

	const replyResult = await postThreadsReply(
		token,
		replier.threads_user_id,
		targetThreadsPostId,
		replyText,
	);

	if (!replyResult.success) {
		await recordOutboundOperatorResult({
			db,
			userId: ownerId,
			actionName: "cross_reply",
			riskLevel: "high",
			scope: { workspaceId, groupId, accountId: replier.id },
			payload: outboundPayload,
			idempotencyKey: `cross-reply:${queueItemId}:${replier.id}`,
			outcome: "failure",
			message: "cross-reply failed",
			error: replyResult.error ?? null,
			metadata: { queueItemId, source: "cross-reply-publish" },
		});
		// Record the failed attempt
		await db
			.from("auto_cross_replies")
			.insert({
				user_id: ownerId,
				workspace_id: workspaceId,
				group_id: groupId,
				target_post_id: queueItemId,
				target_account_id: targetAccountId,
				target_threads_post_id: targetThreadsPostId,
				replier_account_id: replier.id,
				content: replyText,
				chain_position: 1,
				status: "failed",
				scheduled_for: new Date().toISOString(),
				error_message: replyResult.error ?? null,
			})
			.then(null, () => {});

		return {
			success: false,
			replierAccountId: replier.id,
			error: replyResult.error,
		};
	}

	// 5. Record success in DB
	await db
		.from("auto_cross_replies")
		.insert({
			user_id: ownerId,
			workspace_id: workspaceId,
			group_id: groupId,
			target_post_id: queueItemId,
			target_account_id: targetAccountId,
			target_threads_post_id: targetThreadsPostId,
			replier_account_id: replier.id,
			replier_threads_post_id: replyResult.replyId ?? null,
			content: replyText,
			chain_position: 1,
			status: "published",
			scheduled_for: new Date().toISOString(),
			published_at: new Date().toISOString(),
		})
		.then(null, (err: unknown) => {
			logger.warn("[crossReply] DB insert failed (non-blocking)", {
				error: String(err),
			});
		});

	await recordOutboundOperatorResult({
		db,
		userId: ownerId,
		actionName: "cross_reply",
		riskLevel: "high",
		scope: { workspaceId, groupId, accountId: replier.id },
		payload: outboundPayload,
		idempotencyKey: `cross-reply:${queueItemId}:${replier.id}`,
		outcome: "success",
		message: "cross-reply published",
		metadata: {
			queueItemId,
			replyThreadsId: replyResult.replyId ?? null,
			source: "cross-reply-publish",
		},
	});

	// 6. Increment Redis daily counter
	const counterKey = `cross-reply:${replier.id}:${dateKey}`;
	await redis.incr(counterKey).catch((error) => {
		logger.error("[crossReply] Rate counter increment failed", {
			queueItemId,
			accountId: replier.id,
			error: String(error),
		});
	});
	await redis.expire(counterKey, COUNTER_TTL).catch((error) => {
		logger.warn("[crossReply] Rate counter TTL update failed", {
			queueItemId,
			accountId: replier.id,
			error: String(error),
		});
	});

	logger.info("[crossReply] Published", {
		queueItemId,
		targetAccount: targetAccountId,
		replierAccount: replier.id,
		replierUsername: replier.username,
		replyId: replyResult.replyId,
		content: replyText,
	});

	return {
		success: true,
		replierAccountId: replier.id,
		replyThreadsId: replyResult.replyId,
	};
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Pick a reply template based on the original post content.
 */
function pickCrossReply(postContent: string): string {
	const lower = (postContent || "").toLowerCase();

	if (lower.includes("?")) {
		return randomFrom(TEMPLATES_QUESTION_REACT);
	}

	if (
		lower.includes("hot take") ||
		lower.includes("unpopular") ||
		lower.includes("prove me")
	) {
		return randomFrom(TEMPLATES_AGREE);
	}

	if (
		lower.includes("feel") ||
		lower.includes("miss") ||
		lower.includes("lonely") ||
		lower.includes("wish")
	) {
		return randomFrom(TEMPLATES_RELATABLE);
	}

	// Default: random from all templates
	return randomFrom(ALL_TEMPLATES);
}

function randomFrom(arr: string[]): string {
	return arr[Math.floor(Math.random() * arr.length)]!;
}

/**
 * Post a reply to a Threads post using the two-step container + publish flow.
 * Same pattern as replyFarming.ts:postReply but returns the reply's thread ID.
 */
async function postThreadsReply(
	accessToken: string,
	threadsUserId: string,
	replyToId: string,
	text: string,
): Promise<{
	success: boolean;
	replyId?: string | undefined;
	error?: string | undefined;
}> {
	try {
		// Step 1: Create container
		const containerRes = await withRetry(() =>
			fetch(`${THREADS_API_BASE}/${threadsUserId}/threads`, {
				method: "POST",
				body: new URLSearchParams({
					media_type: "TEXT",
					text,
					reply_to_id: replyToId,
					access_token: accessToken,
				}),
				signal: AbortSignal.timeout(API_TIMEOUT),
			}),
		);

		const containerData = await containerRes.json();
		if (!containerRes.ok || !containerData.id) {
			const errMsg =
				containerData.error?.message || `HTTP ${containerRes.status}`;
			return { success: false, error: `container: ${errMsg}` };
		}

		// Step 2: Publish
		const publishRes = await withRetry(() =>
			fetch(`${THREADS_API_BASE}/${threadsUserId}/threads_publish`, {
				method: "POST",
				body: new URLSearchParams({
					creation_id: containerData.id,
					access_token: accessToken,
				}),
				signal: AbortSignal.timeout(API_TIMEOUT),
			}),
		);

		const publishData = await publishRes.json();
		if (!publishRes.ok || !publishData.id) {
			const errMsg = publishData.error?.message || `HTTP ${publishRes.status}`;
			return { success: false, error: `publish: ${errMsg}` };
		}

		return { success: true, replyId: publishData.id as string };
	} catch (err) {
		return {
			success: false,
			error: err instanceof Error ? err.message : String(err),
		};
	}
}
