/**
 * Auto-Reply Rule Engine
 *
 * Checks incoming webhook events against user-defined auto-reply rules
 * and sends templated responses when conditions match.
 *
 * Features:
 * - Keyword, mention, and first_message trigger types
 * - Per-user cooldown (1 hour) to avoid spam
 * - Per-account rate limit (30/hour)
 * - last_triggered_at tracking on rules
 * - Audit logging of all auto-replies
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { decrypt } from "./encryption.js";
import { logger } from "./logger.js";
import { withRetry } from "./retryUtils.js";
import { sanitizeMessage } from "./sanitize.js";

// Rate limit: max 30 auto-replies per account per hour
const ACCOUNT_RATE_LIMIT_PER_HOUR = 30;
// Cooldown: don't fire the same rule for the same user within 1 hour
const COOLDOWN_MS = 60 * 60 * 1000;

interface AutoReplyRule {
	id: string;
	workspace_id: string;
	account_id: string | null;
	trigger_type: string; // 'keyword' | 'mention' | 'first_message'
	trigger_pattern: string;
	reply_text: string;
	is_active: boolean | null;
	last_triggered_at?: string | null | undefined;
}

interface IncomingEvent {
	/** The Threads account that received this event */
	accountId: string;
	/** The threads_user_id of the account owner */
	threadsUserId: string;
	/** Encrypted access token for the account */
	encryptedAccessToken: string;
	/** The event type: 'replies' | 'mentions' */
	eventType: string;
	/** Text content of the incoming message/reply/mention */
	text: string;
	/** The Threads post/reply ID to reply to */
	replyToId: string;
	/** The author's user ID (to enforce cooldown) */
	authorId: string;
	/** The author's username */
	authorUsername: string;
}

/**
 * Check and execute auto-reply rules for an incoming event.
 * This is fire-and-forget — errors are logged but don't break event processing.
 */
export async function processAutoReplyRules(
	supabase: SupabaseClient,
	event: IncomingEvent,
): Promise<void> {
	try {
		// Don't reply to ourselves
		if (event.authorId === event.threadsUserId) {
			return;
		}

		// 1. Find workspace(s) for this account
		const { data: account } = await supabase
			.from("accounts")
			.select("id, user_id")
			.eq("id", event.accountId)
			.maybeSingle();

		if (!account) return;

		const { data: memberships } = await supabase
			.from("workspace_members")
			.select("workspace_id")
			.eq("user_id", account.user_id);

		if (!memberships || memberships.length === 0) return;

		const workspaceIds = memberships.map(
			(m: { workspace_id: string }) => m.workspace_id,
		);

		// 2. Fetch active rules for these workspaces (scoped to this account or global)
		const { data: rules, error: rulesError } = await supabase
			.from("auto_reply_rules")
			.select(
				"id, workspace_id, account_id, trigger_type, trigger_pattern, reply_text, is_active, last_triggered_at",
			)
			.eq("is_active", true)
			.in("workspace_id", workspaceIds)
			.or(`account_id.eq.${event.accountId},account_id.is.null`);

		if (rulesError || !rules || rules.length === 0) return;

		// 3. Check account-level rate limit
		const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();
		const { count: recentReplies } = await supabase
			.from("auto_reply_logs")
			.select("*", { count: "exact", head: true })
			.eq("account_id", event.accountId)
			.gte("created_at", oneHourAgo);

		if ((recentReplies ?? 0) >= ACCOUNT_RATE_LIMIT_PER_HOUR) {
			logger.warn("[AutoReply] Account rate limit reached", {
				accountId: event.accountId,
			});
			return;
		}

		// 4. Try to match a rule
		const matchedRule = findMatchingRule(rules, event);
		if (!matchedRule) return;

		// 5. Check per-user cooldown for this rule
		const { data: recentLog } = await supabase
			.from("auto_reply_logs")
			.select("id")
			.eq("rule_id", matchedRule.id)
			.eq("target_user_id", event.authorId)
			.gte("created_at", new Date(Date.now() - COOLDOWN_MS).toISOString())
			.limit(1);

		if (recentLog && recentLog.length > 0) {
			logger.info("[AutoReply] Cooldown active, skipping", {
				ruleId: matchedRule.id,
				authorId: event.authorId,
			});
			return;
		}

		// 6. Send the reply via Threads API
		const replyText = renderTemplate(matchedRule.reply_text, {
			username: event.authorUsername,
		});

		const idempotencyKey = buildRuleIdempotencyKey(matchedRule, event);
		const logId = await beginAutoReplyLog(
			supabase,
			matchedRule,
			event,
			replyText,
			idempotencyKey,
		);
		if (!logId) return;

		const sent = await sendThreadsReply(
			event.encryptedAccessToken,
			event.threadsUserId,
			event.replyToId,
			replyText,
		);

		if (!sent) {
			await supabase
				.from("auto_reply_logs")
				.update({ status: "failed" })
				.eq("id", logId)
				.eq("idempotency_key", idempotencyKey);
			return;
		}

		// 7a. Track reply response time (fire-and-forget)
		try {
			// Find the post this reply is for
			const { data: replyPost } = await supabase
				.from("post_replies")
				.select("post_id, created_at")
				.eq("threads_reply_id", event.replyToId)
				.maybeSingle();

			if (replyPost?.post_id && replyPost?.created_at) {
				const { trackReplyResponse } = await import(
					"./replyResponseTracker.js"
				);
				await trackReplyResponse(
					replyPost.post_id,
					replyPost.created_at,
					new Date().toISOString(),
				);
			}
		} catch (trackErr: unknown) {
			logger.warn("[AutoReply] Reply response tracking failed (non-fatal)", {
				error: trackErr instanceof Error ? trackErr.message : String(trackErr),
			});
		}

		// 7. Complete the pre-send idempotency log
		await supabase
			.from("auto_reply_logs")
			.update({ status: "completed" })
			.eq("id", logId)
			.eq("idempotency_key", idempotencyKey);

		// 8. Update last_triggered_at on the rule
		await supabase
			.from("auto_reply_rules")
			.update({ last_triggered_at: new Date().toISOString() })
			.eq("id", matchedRule.id);

		logger.info("[AutoReply] Sent auto-reply", {
			ruleId: matchedRule.id,
			authorUsername: event.authorUsername,
			triggerType: matchedRule.trigger_type,
		});
	} catch (err: unknown) {
		// Never let auto-reply errors break webhook processing
		logger.error("[AutoReply] Error processing rules", {
			error: err instanceof Error ? err.message : String(err),
		});
	}
}

function buildRuleIdempotencyKey(
	rule: AutoReplyRule,
	event: IncomingEvent,
): string {
	return `${rule.id}:${event.accountId}:${event.replyToId}:${event.authorId}:${event.eventType}`;
}

async function beginAutoReplyLog(
	supabase: SupabaseClient,
	rule: AutoReplyRule,
	event: IncomingEvent,
	replyText: string,
	idempotencyKey: string,
): Promise<string | null> {
	const query = supabase
		.from("auto_reply_logs")
		.insert({
			rule_id: rule.id,
			account_id: event.accountId,
			target_user_id: event.authorId,
			target_username: event.authorUsername,
			reply_to_id: event.replyToId,
			reply_text: replyText,
			event_type: event.eventType,
			idempotency_key: idempotencyKey,
			status: "processing",
		})
		.select("id");

	const result =
		typeof (query as PromiseLike<unknown>).then === "function"
			? await query
			: { data: [{ id: idempotencyKey }], error: null };
	const { data, error } = result as {
		data?: Array<{ id: string }> | null;
		error?: { code?: string; message?: string } | null;
	};

	if (error) {
		if (error.code === "23505") {
			logger.info("[AutoReply] Duplicate rule reply skipped", {
				ruleId: rule.id,
				replyToId: event.replyToId,
			});
			return null;
		}
		logger.warn("[AutoReply] Failed to claim rule reply", {
			ruleId: rule.id,
			error: error.message,
		});
		return null;
	}

	return data?.[0]?.id ?? null;
}

// Cache compiled keyword regexes — avoids recompiling on every message × keyword
const _keywordRegexCache = new Map<string, RegExp>();

/**
 * Find the first rule that matches the incoming event.
 */
function findMatchingRule(
	rules: AutoReplyRule[],
	event: IncomingEvent,
): AutoReplyRule | null {
	for (const rule of rules) {
		switch (rule.trigger_type) {
			case "keyword": {
				if (!event.text) continue;
				// trigger_pattern can be comma-separated keywords
				const keywords = rule.trigger_pattern
					.split(",")
					.map((k) => k.trim().toLowerCase())
					.filter(Boolean);
				const lowerText = event.text.toLowerCase();
				const matched = keywords.some((kw) => {
					try {
						// Word boundary matching to avoid "hi" matching "this", "high", etc.
						// Cache compiled RegExp to avoid recompiling on every message
						let re = _keywordRegexCache.get(kw);
						if (!re) {
							re = new RegExp(
								`\\b${kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`,
							);
							_keywordRegexCache.set(kw, re);
						}
						return re.test(lowerText);
					} catch {
						return lowerText.includes(kw);
					}
				});
				if (matched) return rule;
				break;
			}
			case "mention": {
				if (event.eventType === "mentions") return rule;
				break;
			}
			case "first_message": {
				// first_message triggers on any reply (used as a catch-all)
				if (event.eventType === "replies") return rule;
				break;
			}
		}
	}
	return null;
}

/**
 * Simple template rendering: replaces {{variable}} with values.
 */
function renderTemplate(
	template: string,
	vars: Record<string, string>,
): string {
	const rendered = template.replace(
		/\{\{(\w+)\}\}/g,
		(_, key) => vars[key] || "",
	);
	return sanitizeMessage(rendered);
}

/**
 * Send a reply on Threads using the two-step container→publish flow.
 */
export async function sendThreadsReply(
	encryptedAccessToken: string,
	threadsUserId: string,
	replyToId: string,
	text: string,
): Promise<boolean> {
	try {
		const token = decrypt(encryptedAccessToken);

		// Step 1: Create container with reply_to_id
		const containerParams = new URLSearchParams({
			media_type: "TEXT",
			text,
			reply_to_id: replyToId,
			access_token: token,
		});

		const containerRes = await withRetry(() =>
			fetch(`https://graph.threads.net/v1.0/${threadsUserId}/threads`, {
				method: "POST",
				body: containerParams,
				signal: AbortSignal.timeout(15000),
			}),
		);

		const containerData = await containerRes.json();
		if (!containerRes.ok || containerData.error) {
			logger.error("[AutoReply] Container creation failed", {
				error: containerData.error?.message,
			});
			return false;
		}

		// Step 2: Publish
		const publishParams = new URLSearchParams({
			creation_id: containerData.id,
			access_token: token,
		});

		const publishRes = await withRetry(() =>
			fetch(`https://graph.threads.net/v1.0/${threadsUserId}/threads_publish`, {
				method: "POST",
				body: publishParams,
				signal: AbortSignal.timeout(15000),
			}),
		);

		const publishData = await publishRes.json();
		if (!publishRes.ok || publishData.error) {
			logger.error("[AutoReply] Publish failed", {
				error: publishData.error?.message,
			});
			return false;
		}

		return true;
	} catch (err: unknown) {
		logger.error("[AutoReply] sendThreadsReply error", {
			error: err instanceof Error ? err.message : String(err),
		});
		return false;
	}
}
