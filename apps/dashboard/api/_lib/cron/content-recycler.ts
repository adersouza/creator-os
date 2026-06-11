// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Content Recycling Engine — reuse proven winners
 *
 * After 7 days, scores every published post:
 *   - Views > group avg × 2 = evergreen candidate
 *   - Reply rate > 2% = conversation starter
 *   - Follower delta > 0 = converter (highest value)
 *
 * For identified evergreen posts:
 *   1. AI rewrites the post (keep pattern, change surface words)
 *   2. Queues rewrite for a DIFFERENT account in the same group
 *   3. Waits 14+ days before recycling same pattern
 *   4. Tracks if recycled versions perform similarly
 *
 * Runs weekly via daily-orchestrator (Saturdays).
 */

import {
	filterContent,
	resolveFilterConfig,
} from "../handlers/auto-post/contentFilter.js";
import {
	generateWithProvider,
	getUserAIConfig,
	resolveVoiceProfile,
} from "../handlers/auto-post/contentSelection.js";
import { logger, serializeError } from "../logger.js";
import { getSupabase } from "../supabase.js";

// biome-ignore lint/suspicious/noExplicitAny: new columns not in generated types
const db = (): any => getSupabase();

const LOG_PREFIX = "[content-recycler]";

const MIN_DAYS_BEFORE_RECYCLE = 14;
const MIN_DAYS_BEFORE_DIRECT_REQUEUE = 2; // Direct requeue after 2 days (competitors do same day)
const MAX_DIRECT_REQUEUES_PER_WEEK = 3; // Max 3 direct requeues per post per week
const MIN_POSTS_FOR_AVG = 10;
const EVERGREEN_VIEW_MULTIPLIER = 2.0;
const CONVERSATION_REPLY_RATE = 0.02;
const DIRECT_REQUEUE_VIEW_MULTIPLIER = 3.0; // Higher bar for word-for-word reuse

// ============================================================================
// Types
// ============================================================================

interface EvergreenCandidate {
	postId: string;
	content: string;
	accountId: string;
	groupId: string;
	userId: string;
	views: number;
	replies: number;
	publishedAt: string;
	evergreenReason: string;
}

interface RecycleResult {
	candidatesFound: number;
	recycled: number;
	skipped: number;
	failed: number;
}

// ============================================================================
// Main Orchestrator
// ============================================================================

export async function processContentRecycling(): Promise<RecycleResult> {
	const result: RecycleResult = {
		candidatesFound: 0,
		recycled: 0,
		skipped: 0,
		failed: 0,
	};

	try {
		// Find groups with enough post history
		const { data: groups } = await db()
			.from("account_groups")
			.select("id, name, user_id, account_ids")
			.not("account_ids", "is", null);

		if (!groups || groups.length === 0) return result;

		for (const group of groups) {
			try {
				await processGroup(group, result);
			} catch (err) {
				logger.error(`${LOG_PREFIX} Group processing failed`, {
					groupId: group.id,
					error: serializeError(err),
				});
			}
		}

		logger.info(`${LOG_PREFIX} Complete`, { ...result });
	} catch (err) {
		logger.error(`${LOG_PREFIX} Fatal error`, { error: serializeError(err) });
	}

	return result;
}

// ============================================================================
// Per-Group Processing
// ============================================================================

async function processGroup(
	group: { id: string; name: string; user_id: string; account_ids: string[] },
	result: RecycleResult,
): Promise<void> {
	const accountIds = (group.account_ids || []) as string[];
	if (accountIds.length < 2) return; // Need 2+ accounts to cross-recycle

	const recycleCutoff = new Date(
		Date.now() - MIN_DAYS_BEFORE_RECYCLE * 24 * 60 * 60 * 1000,
	).toISOString();

	// Get all posts from this group (last 30 days) for baseline
	const { data: allPosts } = await db()
		.from("posts")
		.select(
			"id, content, views_count, replies_count, account_id, published_at, recycled_from_id",
		)
		.in("account_id", accountIds)
		.eq("platform", "threads")
		.eq("status", "published")
		.not("views_count", "is", null)
		.gte(
			"published_at",
			new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString(),
		);

	if (!allPosts || allPosts.length < MIN_POSTS_FOR_AVG) return;

	// Calculate group averages
	const avgViews =
		allPosts.reduce(
			(s: number, p: { views_count: number }) => s + (p.views_count || 0),
			0,
		) / allPosts.length;

	// Find evergreen candidates (7+ days old, above threshold)
	const candidates: EvergreenCandidate[] = [];

	for (const post of allPosts) {
		// Must be old enough to recycle
		if (post.published_at > recycleCutoff) continue;

		// Skip already recycled posts
		if (post.recycled_from_id) continue;

		// Skip posts already recycled FROM this one
		const { data: existingRecycles } = await db()
			.from("posts")
			.select("id")
			.eq("recycled_from_id", post.id)
			.limit(1);
		if (existingRecycles && existingRecycles.length > 0) continue;

		const views = post.views_count || 0;
		const replies = post.replies_count || 0;
		const replyRate = views > 0 ? replies / views : 0;

		let reason = "";
		if (views > avgViews * EVERGREEN_VIEW_MULTIPLIER) {
			reason = "high_views";
		} else if (replyRate > CONVERSATION_REPLY_RATE) {
			reason = "conversation_starter";
		}

		if (!reason) continue;

		candidates.push({
			postId: post.id,
			content: post.content || "",
			accountId: post.account_id,
			groupId: group.id,
			userId: group.user_id,
			views,
			replies,
			publishedAt: post.published_at,
			evergreenReason: reason,
		});
	}

	result.candidatesFound += candidates.length;
	if (candidates.length === 0) return;

	// Sort by views (best first)
	candidates.sort((a, b) => b.views - a.views);

	// Get workspace for queue insertion
	const { data: ws } = await db()
		.from("workspaces")
		.select("id")
		.eq("owner_id", group.user_id)
		.maybeSingle();
	const workspaceId = ws?.id || "";

	const filterConfig = resolveFilterConfig(null, 140, 3, 5);

	// ── Redis for cross-account dedup (Evergreen Recycling 2026, Section 9) ──
	// Max 2 accounts per post per 48h to prevent coordinated detection
	type RedisLike = {
		get: (k: string) => Promise<string | null>;
		incr: (k: string) => Promise<number>;
		expire: (k: string, s: number) => Promise<unknown>;
	};
	let redis: RedisLike | null = null;
	try {
		const { getRedis } = await import("../redis.js");
		redis = getRedis() as unknown as RedisLike;
	} catch {
		/* fail-open */
	}

	// ── Phase 1: Direct requeue (word-for-word, different account) ��─
	// Top performers (3x+ avg views) get reposted verbatim — this is what competitors do
	const directRequeueCutoff = new Date(
		Date.now() - MIN_DAYS_BEFORE_DIRECT_REQUEUE * 24 * 60 * 60 * 1000,
	).toISOString();
	const oneWeekAgo = new Date(
		Date.now() - 7 * 24 * 60 * 60 * 1000,
	).toISOString();
	const directCandidates = candidates.filter(
		(c) =>
			c.views > avgViews * DIRECT_REQUEUE_VIEW_MULTIPLIER &&
			c.publishedAt <= directRequeueCutoff,
	);

	let directRequeued = 0;
	for (const candidate of directCandidates.slice(0, 5)) {
		try {
			// Check weekly requeue count for this content
			const { count: weeklyCount } = await db()
				.from("auto_post_queue")
				.select("id", { count: "exact", head: true })
				.eq("source_content", candidate.content)
				.eq("source_type", "recycled_direct")
				.gte("created_at", oneWeekAgo);

			if ((weeklyCount ?? 0) >= MAX_DIRECT_REQUEUES_PER_WEEK) continue;

			// Cross-account dedup: max 2 accounts per post per 48h
			if (redis) {
				try {
					const dedupKey = `recycler-dedup:${candidate.postId}`;
					const count = Number(await redis.get(dedupKey)) || 0;
					if (count >= 2) {
						logger.debug(
							`${LOG_PREFIX} Cross-account dedup: max 2 accounts in 48h`,
							{
								postId: candidate.postId,
								count,
							},
						);
						continue;
					}
				} catch {
					/* fail-open */
				}
			}

			// Pick a different account in the group
			const otherAccounts = accountIds.filter(
				(id) => id !== candidate.accountId,
			);
			if (otherAccounts.length === 0) continue;
			const targetAccountId =
				otherAccounts[Math.floor(Math.random() * otherAccounts.length)];

			const scheduledFor = new Date(
				Date.now() + (30 + Math.random() * 120) * 60 * 1000,
			);
			const { error: insertError } = await db()
				.from("auto_post_queue")
				.insert({
					workspace_id: workspaceId,
					group_id: group.id,
					account_id: targetAccountId,
					content: candidate.content, // Word-for-word — no AI rewrite
					status: "pending",
					scheduled_for: scheduledFor.toISOString(),
					source_type: "recycled_direct",
					source_content: candidate.content,
					predicted_viral_score: Math.min(95, Math.round(candidate.views / 8)),
				});

			if (!insertError) {
				directRequeued++;
				result.recycled++;
				// Track cross-account usage
				if (redis) {
					try {
						const dedupKey = `recycler-dedup:${candidate.postId}`;
						await redis.incr(dedupKey);
						await redis.expire(dedupKey, 48 * 60 * 60);
					} catch {
						/* fail-open */
					}
				}
				logger.info(`${LOG_PREFIX} Direct requeued proven hook`, {
					originalId: candidate.postId,
					views: candidate.views,
					targetAccount: targetAccountId,
					contentPreview: candidate.content.substring(0, 50),
				});
			}
		} catch (err) {
			logger.warn(`${LOG_PREFIX} Direct requeue failed`, {
				postId: candidate.postId,
				error: serializeError(err),
			});
		}
	}

	// ── Phase 2: AI rewrite (original flow — for candidates not direct-requeued) ──
	const toRewrite = candidates
		.filter((c) => !directCandidates.includes(c))
		.slice(0, 3);

	// Get AI config
	const aiConfig = await getUserAIConfig(group.user_id);
	if (!aiConfig) {
		result.skipped += toRewrite.length;
		return;
	}

	for (const candidate of toRewrite) {
		try {
			// Cross-account dedup: max 2 accounts per post per 48h
			if (redis) {
				try {
					const dedupKey = `recycler-dedup:${candidate.postId}`;
					const count = Number(await redis.get(dedupKey)) || 0;
					if (count >= 2) {
						result.skipped++;
						continue;
					}
				} catch {
					/* fail-open */
				}
			}

			// Pick a different account in the group
			const otherAccounts = accountIds.filter(
				(id) => id !== candidate.accountId,
			);
			if (otherAccounts.length === 0) {
				result.skipped++;
				continue;
			}
			const targetAccountId =
				otherAccounts[Math.floor(Math.random() * otherAccounts.length)];

			// Get voice profile for target account
			const voice = await resolveVoiceProfile(targetAccountId!, group.user_id);
			const voiceDesc = voice?.voice_profile || "casual, authentic creator";

			// AI rewrite
			const prompt = `Rewrite this viral post in your own words. Keep the SAME hook pattern, energy, and length. Change the specific details so it reads as an original thought, not a copy.

ORIGINAL (got ${candidate.views} views): "${candidate.content}"

YOUR VOICE: ${voiceDesc}

RULES:
- Keep the same structure and emotional hook
- Change specific words/details but preserve the pattern
- Stay under 140 characters
- Keep it lowercase and casual — broken grammar is fine
- Do NOT add hashtags, links, or CTAs
- Output ONLY the rewritten post text, nothing else.`;

			const raw = await generateWithProvider(prompt, {
				provider: aiConfig.provider,
				apiKey: aiConfig.apiKey,
				baseUrl: aiConfig.baseUrl,
				model: aiConfig.model,
				ideaCount: 1,
				actionLog: {
					userId: group.user_id,
					accountId: targetAccountId,
					surface: "autopilot",
					actionType: "content_recycle",
					inputText: prompt,
					metadata: { groupId: group.id },
				},
			});

			if (!raw) {
				result.failed++;
				continue;
			}

			let content = raw
				.replace(/^["']|["']$/g, "")
				.replace(/\n/g, " ")
				.trim();

			// Filter
			const filterResult = filterContent(content, filterConfig);
			if (!filterResult.passed) {
				result.skipped++;
				continue;
			}

			if (content.length > 140) content = `${content.slice(0, 137)}...`;
			if (content.length < 5) {
				result.skipped++;
				continue;
			}

			// Insert into auto_post_queue
			const scheduledFor = new Date(
				Date.now() + (30 + Math.random() * 120) * 60 * 1000,
			);

			const { error: insertError } = await db()
				.from("auto_post_queue")
				.insert({
					workspace_id: workspaceId,
					group_id: group.id,
					account_id: targetAccountId,
					content,
					status: "pending",
					scheduled_for: scheduledFor.toISOString(),
					source_type: "recycled",
					source_content: candidate.content,
					predicted_viral_score: Math.min(90, Math.round(candidate.views / 10)),
				});

			if (insertError) {
				result.failed++;
				logger.error(`${LOG_PREFIX} Queue insert failed`, {
					error: String(insertError),
				});
			} else {
				result.recycled++;
				// Track cross-account usage
				if (redis) {
					try {
						const dedupKey = `recycler-dedup:${candidate.postId}`;
						await redis.incr(dedupKey);
						await redis.expire(dedupKey, 48 * 60 * 60);
					} catch {
						/* fail-open */
					}
				}
				logger.info(`${LOG_PREFIX} Recycled evergreen post`, {
					originalId: candidate.postId,
					originalViews: candidate.views,
					targetAccount: targetAccountId,
					reason: candidate.evergreenReason,
				});
			}
		} catch (err) {
			result.failed++;
			logger.error(`${LOG_PREFIX} Recycle failed`, {
				postId: candidate.postId,
				error: serializeError(err),
			});
		}
	}

	if (directRequeued > 0 || toRewrite.length > 0) {
		logger.info(`${LOG_PREFIX} Group summary`, {
			groupId: group.id,
			directRequeued,
			aiRewritten: result.recycled - directRequeued,
			totalCandidates: candidates.length,
		});
	}
}
