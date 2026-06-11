// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Auto-Reply Engine — simplified
 *
 * Replies to comments on auto-posted content to boost first-hour reply velocity.
 * Three phases run in sequence every 5 min (via publish-worker Phase 5):
 *
 * 1. Harvest — fetch comments from Threads API for posts 30+ min old
 * 2. Generate — AI-generate contextual replies using voice profile
 * 3. Publish — post replies via Threads API with rate limiting
 *
 * All config is hardcoded. The only toggle is `enable_auto_reply` on
 * auto_post_group_config (boolean, default false).
 */

import { sendThreadsReply } from "../../autoReplyEngine.js";
import { decrypt } from "../../encryption.js";
import { logger, serializeError } from "../../logger.js";
import {
	enforceOutboundOperatorGuard,
	recordOutboundOperatorResult,
} from "../../outboundOperatorGuard.js";
import { escapeForPrompt } from "../../promptUtils.js";
import { withRetry } from "../../retryUtils.js";
import { getSupabaseAny } from "../../supabase.js";
import {
	generateWithProvider,
	getUserAIConfig,
	resolveVoiceProfile,
} from "./contentSelection.js";
import { logActivity } from "./publisher.js";
import type { VoiceProfile } from "./types.js";

const db = () => getSupabaseAny();

// ── Defaults (group config overrides daily limit + harvest window) ──
const DEFAULT_HARVEST_WINDOW_HOURS = 4;
const DEFAULT_DAILY_LIMIT_PER_GROUP = 20; // lowered from 25 — more groups active now
const MAX_REPLIES_PER_HOUR_PER_ACCOUNT = 8;
const HARVEST_BATCH = 10;
const GENERATE_BATCH = 10;
const PUBLISH_BATCH = 5;
const MAX_RETRIES = 3;

// ── Negative comment patterns (Reply Engagement Strategy S8) ──
// Severe negative comments are routed to needs_review instead of auto-replying.
const SEVERE_NEGATIVE_PATTERNS = [
	/\b(kys|kill yourself|die|rope|neck|unalive)\b/i,
	/\b(ugly|hideous|disgusting|gross|nasty|repulsive)\b/i,
	/\b(scam|fraud|fake|catfish|bot|spam|report)\b/i,
	/\b(f+u+c+k+\s*(you|off|u)|stfu|gtfo|eat shit)\b/i,
	/\b(whore|slut|bitch|thot|hoe)\b/i,
	/\b(pedo|predator|groomer|creep)\b/i,
];

/** Returns the matching pattern source if flagged, null if safe */
function matchesNegativePattern(text: string): string | null {
	const lower = text.toLowerCase();
	for (const pattern of SEVERE_NEGATIVE_PATTERNS) {
		if (pattern.test(lower)) return pattern.source;
	}
	return null;
}

// ── Anti-coordination jitter (prevents deterministic reply patterns across accounts) ──
const JITTER_MIN_MS = 8_000; // 8s minimum between published replies
const JITTER_MAX_MS = 45_000; // 45s maximum — wide variance looks human

function jitterDelay(): Promise<void> {
	const ms = JITTER_MIN_MS + Math.random() * (JITTER_MAX_MS - JITTER_MIN_MS);
	return new Promise((resolve) => setTimeout(resolve, ms));
}

// ============================================================================
// Orchestrator
// ============================================================================

export interface AutoReplyResult {
	harvested: number;
	generated: number;
	published: number;
	skipped: number;
	failed: number;
}

export async function processAutoReplyQueue(
	workspaceId: string,
	ownerId: string,
): Promise<AutoReplyResult> {
	const result: AutoReplyResult = {
		harvested: 0,
		generated: 0,
		published: 0,
		skipped: 0,
		failed: 0,
	};

	try {
		// Check agent_paused
		const { data: profile } = await db()
			.from("profiles")
			.select("agent_paused")
			.eq("id", ownerId)
			.maybeSingle();

		if (profile?.agent_paused) return result;

		// Load groups with auto-reply enabled — only field we need
		const { data: configs } = await db()
			.from("auto_post_group_config")
			.select("group_id")
			.eq("workspace_id", workspaceId)
			.eq("enable_auto_reply", true);

		if (!configs || configs.length === 0) return result;

		const groupIds = configs.map((c: { group_id: string }) => c.group_id);

		// Phase 1: Harvest new comments on posts
		result.harvested = await harvestComments(workspaceId, groupIds);

		// Phase 1b: Harvest follow-up replies (thread depth tracking)
		// If a commenter replies BACK to our auto-reply, generate 1 more follow-up
		// (target 2-3 exchanges total, stop at 3). Research: +30% dwell time.
		result.harvested += await harvestFollowUps(workspaceId, groupIds);

		// Phase 2: Generate
		result.generated = await generateReplies(workspaceId, ownerId);

		// Phase 3: Publish
		const pub = await publishReplies(workspaceId, groupIds);
		result.published = pub.published;
		result.skipped = pub.skipped;
		result.failed = pub.failed;
	} catch (err: unknown) {
		logger.error("[AutoReply] Error", {
			workspaceId,
			error: serializeError(err),
		});
	}

	return result;
}

// ============================================================================
// Phase 1: Harvest Comments
// ============================================================================

async function harvestComments(
	workspaceId: string,
	groupIds: string[],
): Promise<number> {
	let total = 0;
	const windowStart = new Date(
		Date.now() - DEFAULT_HARVEST_WINDOW_HOURS * 60 * 60 * 1000,
	).toISOString();
	// Reply speed target: 15 min (Reply Engagement Strategy S2: 391% higher conversion at faster reply)
	const fifteenMinAgo = new Date(Date.now() - 15 * 60 * 1000).toISOString();

	for (const groupId of groupIds) {
		try {
			// Find published posts ready for harvesting
			const { data: posts } = await db()
				.from("auto_post_queue")
				.select("id, workspace_id, account_id, content, threads_post_id")
				.eq("workspace_id", workspaceId)
				.eq("group_id", groupId)
				.eq("status", "published")
				.is("reply_harvested_at", null)
				.lt("posted_at", fifteenMinAgo)
				.gt("posted_at", windowStart)
				.not("threads_post_id", "is", null)
				.limit(HARVEST_BATCH);

			if (!posts?.length) continue;

			// Check daily limit before spending API calls — use group config if available
			const { data: gcReply } = await db()
				.from("auto_post_group_config")
				.select("auto_reply_daily_limit, auto_reply_window_hours")
				.eq("group_id", groupId)
				.maybeSingle();
			const groupDailyLimit =
				((gcReply as Record<string, unknown> | null)
					?.auto_reply_daily_limit as number) ?? DEFAULT_DAILY_LIMIT_PER_GROUP;
			const dailyCount = await getGroupReplyCountToday(groupId);
			if (dailyCount >= groupDailyLimit) {
				for (const p of posts) await markHarvested(p.id);
				continue;
			}
			let remaining = groupDailyLimit - dailyCount;

			// Get group accounts for username filtering (use account_groups.account_ids as source of truth)
			const { data: _grpRow } = await db()
				.from("account_groups")
				.select("account_ids")
				.eq("id", groupId)
				.maybeSingle();
			const _grpIds = (_grpRow?.account_ids || []) as string[];
			const { data: groupAccounts } =
				_grpIds.length > 0
					? await db()
							.from("accounts")
							.select("id, username, threads_access_token_encrypted")
							.in("id", _grpIds)
					: { data: [] };

			if (!groupAccounts?.length) continue;
			const accountMap = new Map(
				groupAccounts.map(
					(a: {
						id: string;
						username: string;
						threads_access_token_encrypted: string;
					}) => [a.id, a] as const,
				),
			);

			for (const post of posts) {
				if (remaining <= 0) {
					await markHarvested(post.id);
					continue;
				}

				const account = accountMap.get(post.account_id);
				if (!account?.threads_access_token_encrypted) {
					await markHarvested(post.id);
					continue;
				}

				try {
					const token = decrypt(account.threads_access_token_encrypted);
					const url = `https://graph.threads.net/v1.0/${post.threads_post_id}/replies?fields=id,text,username,timestamp,replied_to`;
					const response = await withRetry(
						() =>
							fetch(url, {
								headers: { Authorization: `Bearer ${token}` },
								signal: AbortSignal.timeout(15000),
							}),
						{ label: "autoReply-harvest" },
					);

					const data = await response.json();
					if (data.error || !data.data) {
						await markHarvested(post.id);
						continue;
					}

					// Filter: not from ANY of our group's accounts, has text
					const ownUsernames: Set<string> = new Set(
						groupAccounts.map((a: { username: string }) =>
							a.username.toLowerCase(),
						),
					);
					const comments: Array<{
						id: string;
						text: string;
						username: string;
					}> = (
						data.data as Array<{
							id: string;
							text: string;
							username: string;
						}>
					).filter(
						(c: { id: string; text: string; username: string }) =>
							!ownUsernames.has(c.username.toLowerCase()) && c.text?.trim(),
					);

					if (comments.length === 0) {
						await markHarvested(post.id);
						continue;
					}

					// Negative comment routing (Reply Engagement Strategy S8):
					// Flagged comments go to needs_review instead of auto-replying.
					const safeComments: typeof comments = [];
					const flaggedComments: Array<{
						id: string;
						text: string;
						username: string;
						flaggedReason: string;
					}> = [];
					for (const c of comments) {
						const reason = matchesNegativePattern(c.text);
						if (reason) {
							flaggedComments.push({ ...c, flaggedReason: reason });
						} else {
							safeComments.push(c);
						}
					}

					// Route flagged comments to needs_review instead of dropping
					if (flaggedComments.length > 0) {
						const reviewInsert = flaggedComments.map(
							(c: {
								id: string;
								text: string;
								username: string;
								flaggedReason: string;
							}) => ({
								workspace_id: workspaceId,
								group_id: groupId,
								account_id: post.account_id,
								source_post_id: post.id,
								threads_post_id: post.threads_post_id,
								comment_id: c.id,
								comment_username: c.username,
								comment_text: c.text,
								status: "needs_review" as const,
								flagged_reason: c.flaggedReason,
							}),
						);
						const { error: reviewErr } = await db()
							.from("auto_reply_queue")
							.upsert(reviewInsert, {
								onConflict: "comment_id",
								ignoreDuplicates: true,
							});
						if (reviewErr) {
							logger.warn("[AutoReply] Failed to insert flagged comments", {
								error: reviewErr.message,
								count: reviewInsert.length,
							});
						} else {
							logger.info("[AutoReply] Routed negative comments to review", {
								count: flaggedComments.length,
								postId: post.id,
							});
						}
					}

					// Reply to ALL safe comments (ratio = 1.0)
					const toInsert = safeComments
						.slice(0, remaining)
						.map((c: { id: string; text: string; username: string }) => ({
							workspace_id: workspaceId,
							group_id: groupId,
							account_id: post.account_id,
							source_post_id: post.id,
							threads_post_id: post.threads_post_id,
							comment_id: c.id,
							comment_username: c.username,
							comment_text: c.text,
							status: "pending" as const,
						}));

					if (toInsert.length > 0) {
						const { error: insertErr } = await db()
							.from("auto_reply_queue")
							.upsert(toInsert, {
								onConflict: "comment_id",
								ignoreDuplicates: true,
							});

						if (!insertErr) {
							total += toInsert.length;
							remaining -= toInsert.length;
						}
					}

					await markHarvested(post.id);
				} catch (err: unknown) {
					logger.warn("[AutoReply] Harvest error", {
						postId: post.id,
						error: serializeError(err),
					});
					await markHarvested(post.id);
				}
			}
		} catch (err: unknown) {
			logger.error("[AutoReply] Group harvest error", {
				groupId,
				error: serializeError(err),
			});
		}
	}

	return total;
}

// ============================================================================
// Phase 1b: Harvest Follow-Up Replies (Thread Depth Tracking)
// ============================================================================

const MAX_THREAD_DEPTH = 3; // Max exchanges per chain (our reply counts as 1)
const FOLLOWUP_HARVEST_BATCH = 5;

async function harvestFollowUps(
	workspaceId: string,
	groupIds: string[],
): Promise<number> {
	let total = 0;

	try {
		// Find our auto-replies that were posted 5-60 min ago and haven't been checked for follow-ups
		const fiveMinAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString();
		const sixtyMinAgo = new Date(Date.now() - 60 * 60 * 1000).toISOString();

		const { data: postedReplies } = await db()
			.from("auto_reply_queue")
			.select(
				"id, workspace_id, group_id, account_id, source_post_id, threads_post_id, comment_id, comment_username, generated_reply",
			)
			.eq("workspace_id", workspaceId)
			.eq("status", "posted")
			.in("group_id", groupIds)
			.lt("posted_at", fiveMinAgo)
			.gt("posted_at", sixtyMinAgo)
			.is("followup_checked_at" as string, null)
			.limit(FOLLOWUP_HARVEST_BATCH);

		if (!postedReplies?.length) return 0;

		// Load Redis for depth tracking
		let redis: Awaited<
			ReturnType<typeof import("../../redis.js")["getRedis"]>
		> | null = null;
		try {
			const { getRedis } = await import("../../redis.js");
			redis = getRedis();
		} catch {
			// No Redis — skip follow-up tracking
			return 0;
		}

		for (const reply of postedReplies) {
			try {
				// Check depth in Redis
				const depthKey = `reply-depth:${reply.source_post_id}:${reply.comment_username}`;
				const currentDepth = Number(await redis?.get(depthKey)) || 1; // Our first reply = depth 1

				if (currentDepth >= MAX_THREAD_DEPTH) {
					// Already at max depth — mark checked and skip
					await db()
						.from("auto_reply_queue")
						.update({ followup_checked_at: new Date().toISOString() } as Record<
							string,
							unknown
						>)
						.eq("id", reply.id);
					continue;
				}

				// Get account credentials for API call
				const { data: account } = await db()
					.from("accounts")
					.select(
						"id, username, threads_access_token_encrypted, threads_user_id",
					)
					.eq("id", reply.account_id)
					.maybeSingle();

				if (!account?.threads_access_token_encrypted) {
					await db()
						.from("auto_reply_queue")
						.update({ followup_checked_at: new Date().toISOString() } as Record<
							string,
							unknown
						>)
						.eq("id", reply.id);
					continue;
				}

				// Fetch replies on the original post to find follow-up replies.
				const token = decrypt(account.threads_access_token_encrypted);
				const convUrl = `https://graph.threads.net/v1.0/${reply.threads_post_id}/replies?fields=id,text,username,timestamp,replied_to`;
				const response = await withRetry(
					() =>
						fetch(convUrl, {
							headers: { Authorization: `Bearer ${token}` },
							signal: AbortSignal.timeout(15000),
						}),
					{ label: "auto-reply:followup-replies" },
				);
				const convData = await response.json();

				if (convData.error || !convData.data) {
					await db()
						.from("auto_reply_queue")
						.update({ followup_checked_at: new Date().toISOString() } as Record<
							string,
							unknown
						>)
						.eq("id", reply.id);
					continue;
				}

				// Look for replies from the SAME commenter that came AFTER our auto-reply
				// (These are follow-ups to our reply — the commenter is continuing the conversation)
				const ownUsernames = new Set<string>();
				const { data: _grpR } = await db()
					.from("account_groups")
					.select("account_ids")
					.eq("id", reply.group_id)
					.maybeSingle();
				const _grpAIds = (_grpR?.account_ids || []) as string[];
				const { data: groupAccs } =
					_grpAIds.length > 0
						? await db().from("accounts").select("username").in("id", _grpAIds)
						: { data: [] };
				for (const a of groupAccs || []) {
					ownUsernames.add((a.username as string).toLowerCase());
				}

				const targetUsername = reply.comment_username.toLowerCase();
				const followUps = (
					convData.data as Array<{
						id: string;
						text: string;
						username: string;
						timestamp: string;
					}>
				).filter(
					(c) =>
						c.username.toLowerCase() === targetUsername &&
						c.text?.trim() &&
						c.id !== reply.comment_id, // Not the original comment
				);

				// Check if any of these follow-ups are already in the queue
				if (followUps.length > 0) {
					const existingIds = new Set<string>();
					const { data: existing } = await db()
						.from("auto_reply_queue")
						.select("comment_id")
						.in(
							"comment_id",
							followUps.map((f) => f.id),
						);
					for (const e of existing || []) {
						existingIds.add(e.comment_id);
					}

					const newFollowUps = followUps.filter((f) => !existingIds.has(f.id));

					if (newFollowUps.length > 0) {
						// Queue ONE follow-up reply (just the first new one)
						const followUp = newFollowUps[0];
						const { error: insertErr } = await db()
							.from("auto_reply_queue")
							.upsert(
								[
									{
										workspace_id: workspaceId,
										group_id: reply.group_id,
										account_id: reply.account_id,
										source_post_id: reply.source_post_id,
										threads_post_id: reply.threads_post_id,
										comment_id: followUp!.id,
										comment_username: followUp!.username,
										comment_text: followUp!.text,
										status: "pending" as const,
									},
								],
								{ onConflict: "comment_id", ignoreDuplicates: true },
							);

						if (!insertErr) {
							total++;
							// Increment depth in Redis (48h TTL)
							await redis?.set(depthKey, String(currentDepth + 1), {
								ex: 48 * 60 * 60,
							});
						}
					}
				}

				await db()
					.from("auto_reply_queue")
					.update({ followup_checked_at: new Date().toISOString() } as Record<
						string,
						unknown
					>)
					.eq("id", reply.id);
			} catch (err: unknown) {
				logger.warn("[AutoReply] Follow-up harvest error", {
					replyId: reply.id,
					error: serializeError(err),
				});
			}
		}
	} catch (err: unknown) {
		logger.warn("[AutoReply] Follow-up harvest outer error", {
			error: serializeError(err),
		});
	}

	return total;
}

async function markHarvested(
	sourceId: string,
	sourceTable: "auto_post_queue" | "posts" = "auto_post_queue",
): Promise<void> {
	const harvestedAt = new Date().toISOString();
	if (sourceTable === "posts") {
		const { data: post } = await db()
			.from("posts")
			.select("metadata")
			.eq("id", sourceId)
			.maybeSingle();
		const metadata = {
			...((post?.metadata as Record<string, unknown> | null) || {}),
			reply_harvested_at: harvestedAt,
		};
		await db()
			.from("posts")
			.update({ metadata, updated_at: harvestedAt })
			.eq("id", sourceId);
		return;
	}

	await db()
		.from("auto_post_queue")
		.update({ reply_harvested_at: harvestedAt })
		.eq("id", sourceId);
}

// ============================================================================
// Phase 2: Generate Replies
// ============================================================================

async function generateReplies(
	workspaceId: string,
	ownerId: string,
): Promise<number> {
	const { data: items } = await db()
		.from("auto_reply_queue")
		.select("*")
		.eq("workspace_id", workspaceId)
		.eq("status", "pending")
		.order("created_at", { ascending: true })
		.limit(GENERATE_BATCH);

	if (!items?.length) return 0;

	const aiConfig = await getUserAIConfig(ownerId);
	if (!aiConfig?.apiKey) return 0;

	let generated = 0;

	for (const item of items) {
		try {
			const voiceProfile = await resolveVoiceProfile(item.account_id, ownerId);

			// Get original post text for context
			let originalText: string | undefined;
			if (item.source_post_id) {
				const { data: src } = await db()
					.from("auto_post_queue")
					.select("content")
					.eq("id", item.source_post_id)
					.maybeSingle();
				originalText = src?.content || undefined;
			}

			const prompt = buildReplyPrompt(
				item.comment_text,
				item.comment_username,
				voiceProfile,
				originalText,
			);

			const replyText = await generateWithProvider(prompt, {
				provider: aiConfig.provider,
				apiKey: aiConfig.apiKey,
				baseUrl: aiConfig.baseUrl,
				model: aiConfig.model,
				ideaCount: 1,
				actionLog: {
					userId: ownerId,
					accountId: item.account_id,
					surface: "autopilot",
					actionType: "auto_reply_generate",
					inputText: prompt,
					metadata: { queueItemId: item.id },
				},
			});

			if (!replyText) {
				const retries = (item.retry_count || 0) + 1;
				await updateStatus(
					item.id,
					retries >= MAX_RETRIES ? "failed" : "pending",
					"empty_reply",
					retries,
				);
				continue;
			}

			// Variant rotation: AI generates 5 variants, pick one randomly
			// This ensures different reply structures across accounts + over time
			const variants = replyText
				.split("\n")
				.map((l) => l.trim())
				.filter((l) => l.length > 0 && l.length < 300);
			const selectedReply =
				variants.length > 0
					? variants[Math.floor(Math.random() * variants.length)]
					: replyText.split("\n")[0]?.trim() || replyText.trim();

			// Check banned words from voice profile
			if (voiceProfile?.avoid_words?.length) {
				const lower = selectedReply!.toLowerCase();
				const banned = voiceProfile.avoid_words.find((w: string) =>
					lower.includes(w.toLowerCase()),
				);
				if (banned) {
					await db()
						.from("auto_reply_queue")
						.update({
							status: "skipped",
							error_message: `banned: ${banned}`,
							generated_reply: selectedReply,
						})
						.eq("id", item.id);
					continue;
				}
			}

			// Sanitize: strip markdown
			let sanitized = selectedReply!.trim();
			// Remove markdown bold/italic
			sanitized = sanitized
				.replace(/\*\*([^*]+)\*\*/g, "$1")
				.replace(/\*([^*]+)\*/g, "$1");
			// If AI generated labeled replies ("REPLY 1:", "Option A:"), take only the first content line
			if (/^(\*\*)?REPLY\s*\d|^Option\s*[A-Z]/i.test(sanitized)) {
				const lines = sanitized
					.split("\n")
					.filter(
						(l) =>
							l.trim() &&
							!/^(\*\*)?REPLY\s*\d|^Option\s*[A-Z]|^\(assuming/i.test(l.trim()),
					);
				sanitized = lines[0]?.trim() || sanitized;
			}
			// Remove surrounding quotes
			sanitized = sanitized.replace(/^["']|["']$/g, "");
			// Truncate to 300 chars max (Threads reply limit is 500 but keep it short)
			if (sanitized.length > 300)
				sanitized = `${sanitized.substring(0, 297)}...`;

			// Cross-account similarity gate — reject replies too similar to recent replies
			// from OTHER accounts in the same workspace (prevents pattern detection across 90 accounts)
			try {
				const { data: recentReplies } = await db()
					.from("auto_reply_queue")
					.select("generated_reply, account_id")
					.eq("workspace_id", workspaceId)
					.eq("status", "posted")
					.neq("account_id", item.account_id) // Different accounts only
					.gte(
						"posted_at",
						new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
					)
					.limit(30);

				if (recentReplies?.length) {
					const sanitizedLower = sanitized.toLowerCase();
					const sanitizedWords = new Set(sanitizedLower.split(/\s+/));
					for (const recent of recentReplies) {
						if (!recent.generated_reply) continue;
						const recentLower = (
							recent.generated_reply as string
						).toLowerCase();
						const recentWords = new Set(recentLower.split(/\s+/));
						// Jaccard similarity: intersection / union
						let intersection = 0;
						for (const w of sanitizedWords) {
							if (recentWords.has(w)) intersection++;
						}
						const union = new Set([...sanitizedWords, ...recentWords]).size;
						const similarity = union > 0 ? intersection / union : 0;
						if (similarity > 0.7) {
							// Too similar to a recent reply from another account — skip
							await db()
								.from("auto_reply_queue")
								.update({
									status: "skipped",
									error_message: `cross_account_similarity:${similarity.toFixed(2)}`,
									generated_reply: sanitized,
								})
								.eq("id", item.id);
							sanitized = ""; // Signal to skip below
							break;
						}
					}
					if (!sanitized) continue;
				}
			} catch {
				// Non-critical — proceed without similarity check
			}

			await db()
				.from("auto_reply_queue")
				.update({ status: "processing", generated_reply: sanitized })
				.eq("id", item.id);

			generated++;
		} catch (err: unknown) {
			const retries = (item.retry_count || 0) + 1;
			await updateStatus(
				item.id,
				retries >= MAX_RETRIES ? "failed" : "pending",
				serializeError(err),
				retries,
			);
		}
	}

	return generated;
}

function buildReplyPrompt(
	commentText: string,
	commentUsername: string,
	voiceProfile: VoiceProfile | null,
	originalPostText?: string,
): string {
	const voice = voiceProfile?.voice_profile || "casual, friendly";
	const emoji = voiceProfile?.emoji_usage || "minimal";
	const avoid = voiceProfile?.avoid_topics?.join(", ") || "";
	const safe = escapeForPrompt(commentText);
	const safeUser = escapeForPrompt(commentUsername);
	const ctx = originalPostText
		? `\nYOUR ORIGINAL POST:\n"${originalPostText.slice(0, 300)}"\n`
		: "";

	return `You are replying to a comment on YOUR social media post (Threads). Your goal is to create a REPLY CHAIN — every reply should get them to respond again.

VOICE/TONE: ${voice}
EMOJI USAGE: ${emoji}
${avoid ? `AVOID TOPICS: ${avoid}` : ""}
${ctx}
COMMENT by @${safeUser}:
"${safe}"

RULES:
1. Reference what @${safeUser} said — show you read it
2. End with a question or open loop
3. Under 80 characters
4. Sound like a real person texting
5. NEVER say thanks/appreciate/means a lot or use 💕🙏
6. Match their energy — flirty→flirt, competitive→challenge, chaotic→match
7. One emoji MAX, only if natural

GOOD: "stoppp 😵‍💫 what's your type tho?" | "oh yeah? where you taking me first" | "wait you actually think that??"

OUTPUT: Generate exactly 5 different reply variants, each on its own line. Vary the tone, structure, and word choice across all 5. No labels, no numbering, no markdown, no asterisks, no quotes. Just 5 raw text replies, one per line.`;
}

// ============================================================================
// Phase 3: Publish Replies
// ============================================================================

async function publishReplies(
	workspaceId: string,
	_groupIds: string[],
): Promise<{ published: number; skipped: number; failed: number }> {
	const result = { published: 0, skipped: 0, failed: 0 };

	const { data: items } = await db()
		.from("auto_reply_queue")
		.select("*")
		.eq("workspace_id", workspaceId)
		.eq("status", "processing")
		.order("created_at", { ascending: true })
		.limit(PUBLISH_BATCH);

	if (!items?.length) return result;

	// Shuffle to randomize account order each cycle (prevents deterministic patterns)
	for (let i = items.length - 1; i > 0; i--) {
		const j = Math.floor(Math.random() * (i + 1));
		[items[i], items[j]] = [items[j], items[i]];
	}

	// 25% random skip per item — creates natural variance (sometimes 0 replies, sometimes 5)
	const itemsToProcess = items.filter(() => Math.random() > 0.25);
	if (!itemsToProcess.length) return result;

	for (const item of itemsToProcess) {
		try {
			if (!item.generated_reply) {
				await updateStatus(item.id, "failed", "no_reply");
				result.failed++;
				continue;
			}

			// Per-account hourly rate limit
			const hourly = await getAccountReplyCountLastHour(item.account_id);
			if (hourly >= MAX_REPLIES_PER_HOUR_PER_ACCOUNT) {
				await db()
					.from("auto_reply_queue")
					.update({ status: "pending" })
					.eq("id", item.id);
				result.skipped++;
				continue;
			}

			// Per-group daily limit (reads from group config, falls back to default)
			if (item.group_id) {
				const { data: gcPub } = await db()
					.from("auto_post_group_config")
					.select("auto_reply_daily_limit")
					.eq("group_id", item.group_id)
					.maybeSingle();
				const pubDailyLimit =
					((gcPub as Record<string, unknown> | null)
						?.auto_reply_daily_limit as number) ??
					DEFAULT_DAILY_LIMIT_PER_GROUP;
				const daily = await getGroupReplyCountToday(item.group_id);
				if (daily >= pubDailyLimit) {
					await db()
						.from("auto_reply_queue")
						.update({ status: "pending" })
						.eq("id", item.id);
					result.skipped++;
					continue;
				}
			}

			// Get account credentials
			const { data: account } = await db()
				.from("accounts")
				.select("threads_user_id, threads_access_token_encrypted, username")
				.eq("id", item.account_id)
				.maybeSingle();

			if (!account?.threads_access_token_encrypted) {
				await updateStatus(item.id, "failed", "no_credentials");
				result.failed++;
				continue;
			}

			const claimToken = await claimReplyForPublish(item.id);
			if (!claimToken) {
				result.skipped++;
				continue;
			}

			const guardPayload = {
				queueItemId: item.id,
				workspaceId,
				groupId: item.group_id ?? null,
				accountId: item.account_id,
				commentId: item.comment_id,
			};
			const outboundGuard = await enforceOutboundOperatorGuard({
				db: db(),
				userId: item.user_id,
				actionName: "auto_reply",
				riskLevel: "critical",
				scope: {
					workspaceId,
					groupId: item.group_id ?? null,
					accountId: item.account_id,
				},
				payload: guardPayload,
				idempotencyKey: `auto-reply:${item.id}:${claimToken}`,
				metadata: { claimToken },
			});
			if (!outboundGuard.allowed) {
				await releasePublishClaim(
					item.id,
					"pending",
					outboundGuard.reason,
					item.retry_count || 0,
					claimToken,
				);
				result.skipped++;
				continue;
			}

			const success = await sendThreadsReply(
				account.threads_access_token_encrypted,
				account.threads_user_id,
				item.comment_id,
				item.generated_reply,
			);

			if (success) {
				await recordOutboundOperatorResult({
					db: db(),
					userId: item.user_id,
					actionName: "auto_reply",
					riskLevel: "critical",
					scope: {
						workspaceId,
						groupId: item.group_id ?? null,
						accountId: item.account_id,
					},
					payload: guardPayload,
					idempotencyKey: `auto-reply:${item.id}:${claimToken}`,
					outcome: "success",
					message: "auto reply posted",
					metadata: { claimToken },
				});
				await db()
					.from("auto_reply_queue")
					.update({
						status: "posted",
						posted_at: new Date().toISOString(),
						publish_claim_token: null,
						publish_claimed_at: null,
					})
					.eq("id", item.id)
					.eq("publish_claim_token", claimToken);

				await logActivity(
					workspaceId,
					"auto_reply",
					account.username || item.account_id,
					`Replied to @${item.comment_username}: "${item.generated_reply.slice(0, 60)}"`,
					undefined,
					undefined,
					item.group_id || undefined,
				);

				result.published++;

				// Set initial depth in Redis for thread depth tracking
				try {
					const { getRedis } = await import("../../redis.js");
					const redis = getRedis();
					const depthKey = `reply-depth:${item.source_post_id}:${item.comment_username}`;
					// Only set if not already tracking (don't overwrite follow-up depth)
					await redis.set(depthKey, "1", { ex: 48 * 60 * 60, nx: true });
				} catch {
					/* non-critical — depth tracking is best-effort */
				}

				// Jitter: 8-45s delay before next reply to avoid coordinated behavior
				if (itemsToProcess.indexOf(item) < itemsToProcess.length - 1) {
					await jitterDelay();
				}
			} else {
				await recordOutboundOperatorResult({
					db: db(),
					userId: item.user_id,
					actionName: "auto_reply",
					riskLevel: "critical",
					scope: {
						workspaceId,
						groupId: item.group_id ?? null,
						accountId: item.account_id,
					},
					payload: guardPayload,
					idempotencyKey: `auto-reply:${item.id}:${claimToken}`,
					outcome: "failure",
					message: "auto reply send failed",
					metadata: { claimToken },
				});
				const retries = (item.retry_count || 0) + 1;
				await releasePublishClaim(
					item.id,
					retries >= MAX_RETRIES ? "failed" : "pending",
					"publish_failed",
					retries,
					claimToken,
				);
				result.failed++;
			}
		} catch (err: unknown) {
			const retries = (item.retry_count || 0) + 1;
			const claimToken =
				typeof item.publish_claim_token === "string"
					? item.publish_claim_token
					: undefined;
			await releasePublishClaim(
				item.id,
				retries >= MAX_RETRIES ? "failed" : "pending",
				serializeError(err),
				retries,
				claimToken,
			);
			result.failed++;
		}
	}

	return result;
}

// ============================================================================
// Helpers
// ============================================================================

async function claimReplyForPublish(id: string): Promise<string | null> {
	const claimToken =
		typeof crypto !== "undefined" && "randomUUID" in crypto
			? crypto.randomUUID()
			: `${Date.now()}-${Math.random().toString(36).slice(2)}`;

	const query = db()
		.from("auto_reply_queue")
		.update({
			status: "publishing",
			publish_claim_token: claimToken,
			publish_claimed_at: new Date().toISOString(),
		})
		.eq("id", id)
		.eq("status", "processing")
		.select("id");

	const result =
		typeof (query as PromiseLike<unknown>).then === "function"
			? await query
			: { data: [{ id }], error: null };
	const { data, error } = result as {
		data?: Array<{ id: string }> | null;
		error?: { message?: string } | null;
	};

	if (error) {
		logger.warn("[AutoReply] Failed to claim reply for publish", {
			id,
			error: error.message,
		});
		return null;
	}

	return data?.length ? claimToken : null;
}

async function releasePublishClaim(
	id: string,
	status: string,
	error?: string,
	retryCount?: number,
	claimToken?: string,
): Promise<void> {
	const update: Record<string, unknown> = {
		status,
		publish_claim_token: null,
		publish_claimed_at: null,
	};
	if (error) update.error_message = error;
	if (retryCount !== undefined) update.retry_count = retryCount;

	let query = db().from("auto_reply_queue").update(update).eq("id", id);
	if (claimToken) query = query.eq("publish_claim_token", claimToken);
	await query;
}

async function updateStatus(
	id: string,
	status: string,
	error?: string,
	retryCount?: number,
): Promise<void> {
	const update: Record<string, unknown> = { status };
	if (error) update.error_message = error;
	if (retryCount !== undefined) update.retry_count = retryCount;
	if (status !== "publishing") {
		update.publish_claim_token = null;
		update.publish_claimed_at = null;
	}
	await db().from("auto_reply_queue").update(update).eq("id", id);
}

async function getAccountReplyCountLastHour(
	accountId: string,
): Promise<number> {
	const { count } = await db()
		.from("auto_reply_queue")
		.select("id", { count: "exact", head: true })
		.eq("account_id", accountId)
		.eq("status", "posted")
		.gte("posted_at", new Date(Date.now() - 60 * 60 * 1000).toISOString());
	return count || 0;
}

async function getGroupReplyCountToday(groupId: string): Promise<number> {
	const { count } = await db()
		.from("auto_reply_queue")
		.select("id", { count: "exact", head: true })
		.eq("group_id", groupId)
		.eq("status", "posted")
		.gte("posted_at", new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString());
	return count || 0;
}

// ============================================================================
// Targeted Single-Post Harvest (QStash-dispatched at exactly +15min)
// ============================================================================

/**
 * Harvest and reply to comments on a single specific post.
 * Called by auto-reply-harvest.ts endpoint 15 min after publish.
 * Reuses the same harvest → generate → publish pipeline but scoped to one post.
 * Idempotent: if the cron already harvested this post, this is a no-op.
 */
export async function harvestAndReplyForPost(
	workspaceId: string,
	groupId: string,
	ownerId: string,
	accountId: string,
	postId: string,
	queueItemId: string,
	sourceTable: "auto_post_queue" | "posts" = "auto_post_queue",
): Promise<AutoReplyResult> {
	const result: AutoReplyResult = {
		harvested: 0,
		generated: 0,
		published: 0,
		skipped: 0,
		failed: 0,
	};

	try {
		let sourceItem: {
			id: string;
			threads_post_id: string;
			account_id: string;
			content: string;
			reply_harvested_at: string | null;
			workspace_id?: string | null;
			group_id?: string | null;
			owner_id?: string | null;
		} | null = null;

		if (sourceTable === "posts") {
			const { data: post } = await db()
				.from("posts")
				.select(
					"id, threads_post_id, account_id, user_id, group_id, content, metadata",
				)
				.eq("id", postId)
				.eq("status", "published")
				.maybeSingle();
			if (!post?.threads_post_id) return result;
			const metadata = (post.metadata as Record<string, unknown> | null) || {};
			sourceItem = {
				id: post.id,
				threads_post_id: post.threads_post_id,
				account_id: post.account_id,
				content: post.content,
				group_id: (post.group_id as string | null) || null,
				owner_id: (post.user_id as string | null) || null,
				reply_harvested_at:
					typeof metadata.reply_harvested_at === "string"
						? metadata.reply_harvested_at
						: null,
			};
		} else {
			const { data: item } = await db()
				.from("auto_post_queue")
				.select(
					"id, workspace_id, group_id, threads_post_id, account_id, content, reply_harvested_at",
				)
				.eq("id", queueItemId)
				.eq("status", "published")
				.maybeSingle();
			if (!item?.threads_post_id) return result;
			sourceItem = item;
		}

		if (!sourceItem?.threads_post_id) return result;
		if (sourceItem.reply_harvested_at) return result;

		let effectiveWorkspaceId = sourceItem.workspace_id || workspaceId;
		let effectiveGroupId = sourceItem.group_id || groupId;
		let effectiveOwnerId = sourceItem.owner_id || ownerId;
		const effectiveAccountId = sourceItem.account_id || accountId;

		if (!effectiveOwnerId || effectiveOwnerId === ownerId) {
			const { data: sourceAccount } = await db()
				.from("accounts")
				.select("user_id")
				.eq("id", effectiveAccountId)
				.maybeSingle();
			effectiveOwnerId =
				(sourceAccount?.user_id as string | null) || effectiveOwnerId;
		}

		if (sourceTable === "posts" && !sourceItem.group_id) {
			const { data: group } = await db()
				.from("account_groups")
				.select("id")
				.eq("user_id", effectiveOwnerId)
				.contains("account_ids", [effectiveAccountId])
				.maybeSingle();
			effectiveGroupId = (group?.id as string | null) || effectiveGroupId;
		}

		// Check if auto-reply is enabled for the source row's group.
		const { data: gcReply } = await db()
			.from("auto_post_group_config")
			.select("workspace_id, enable_auto_reply, auto_reply_daily_limit")
			.eq("group_id", effectiveGroupId)
			.maybeSingle();

		if (!gcReply?.enable_auto_reply) {
			return result;
		}

		effectiveWorkspaceId =
			((gcReply as Record<string, unknown>).workspace_id as string | null) ||
			effectiveWorkspaceId;

		// Check daily limit
		const groupDailyLimit =
			((gcReply as Record<string, unknown>).auto_reply_daily_limit as number) ??
			DEFAULT_DAILY_LIMIT_PER_GROUP;
		const dailyCount = await getGroupReplyCountToday(effectiveGroupId);
		if (dailyCount >= groupDailyLimit) {
			return result;
		}

		// Get account token
		const { data: account } = await db()
			.from("accounts")
			.select("id, username, threads_access_token_encrypted")
			.eq("id", effectiveAccountId)
			.maybeSingle();

		if (!account?.threads_access_token_encrypted) return result;

		// Fetch comments from Threads API.
		const token = decrypt(account.threads_access_token_encrypted);
		const url = `https://graph.threads.net/v1.0/${sourceItem.threads_post_id}/replies?fields=id,text,username,timestamp,replied_to`;
		const response = await withRetry(
			() =>
				fetch(url, {
					headers: { Authorization: `Bearer ${token}` },
					signal: AbortSignal.timeout(15000),
				}),
			{ label: "autoReply-targeted-harvest" },
		);

		const data = await response.json();
		if (data.error || !data.data) {
			await markHarvested(sourceItem.id, sourceTable);
			return result;
		}

		// Filter out our own accounts' comments (use account_groups.account_ids as source of truth)
		const { data: _grpRow3 } = await db()
			.from("account_groups")
			.select("account_ids")
			.eq("id", effectiveGroupId)
			.maybeSingle();
		const _grpIds3 = (_grpRow3?.account_ids || []) as string[];
		const { data: groupAccounts } =
			_grpIds3.length > 0
				? await db().from("accounts").select("username").in("id", _grpIds3)
				: { data: [] };

		const ownUsernames = new Set(
			(groupAccounts || []).map((a: { username: string }) =>
				a.username.toLowerCase(),
			),
		);
		const comments = (
			data.data as Array<{ id: string; text: string; username: string }>
		).filter(
			(c) => !ownUsernames.has(c.username.toLowerCase()) && c.text?.trim(),
		);

		if (comments.length === 0) {
			await markHarvested(sourceItem.id, sourceTable);
			return result;
		}

		// Insert comments into auto_reply_queue — route negative to needs_review
		for (const comment of comments.slice(0, 5)) {
			// Cap at 5 per post
			try {
				const negReason = matchesNegativePattern(comment.text);
				await db()
					.from("auto_reply_queue")
					.upsert(
						{
							workspace_id: effectiveWorkspaceId,
							group_id: effectiveGroupId,
							account_id: effectiveAccountId,
							source_post_id: sourceItem.id,
							threads_post_id: sourceItem.threads_post_id,
							comment_id: comment.id,
							comment_text: comment.text,
							comment_username: comment.username,
							...(sourceTable === "auto_post_queue"
								? { queue_item_id: sourceItem.id }
								: {}),
							post_content: sourceItem.content,
							status: negReason ? "needs_review" : "pending",
							flagged_reason: negReason || undefined,
						},
						{ onConflict: "comment_id", ignoreDuplicates: true },
					);
				result.harvested++;
			} catch {
				// Idempotent — duplicates are expected
			}
		}

		await markHarvested(sourceItem.id, sourceTable);

		// If we harvested comments, run generate + publish for this batch
		if (result.harvested > 0) {
			result.generated = await generateReplies(
				effectiveWorkspaceId,
				effectiveOwnerId,
			);
			const pub = await publishReplies(effectiveWorkspaceId, [
				effectiveGroupId,
			]);
			result.published = pub.published;
			result.skipped = pub.skipped;
			result.failed = pub.failed;
		}

		logger.info("[AutoReply] Targeted harvest complete", {
			queueItemId,
			postId,
			harvested: result.harvested,
			published: result.published,
		});
	} catch (err) {
		logger.warn("[AutoReply] Targeted harvest failed (non-critical)", {
			queueItemId,
			error: serializeError(err),
		});
	}

	return result;
}
