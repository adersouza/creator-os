// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Reply Farming Engine — finds trending posts in niche topics and
 * replies from our accounts to drive profile visits.
 *
 * Mosseri: "reply more than you post" — 5:1 to 10:1 ratio.
 * Buffer: replying to comments boosts engagement 42%.
 * Replies to 10K+ impression posts drive 500-1K profile visits.
 *
 * Non-critical: errors never block publishing. Uses template-based
 * replies (no AI calls) for speed and cost efficiency.
 */

import { decrypt } from "./encryption.js";
import { logger } from "./logger.js";
import { getRedis } from "./redis.js";
import { withRetry } from "./retryUtils.js";
import { getSupabase, getSupabaseAny } from "./supabase.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const THREADS_API_BASE = "https://graph.threads.net/v1.0";
const API_TIMEOUT = 10_000;

/** Max replies any single account can send per day via reply farming */
const MAX_REPLIES_PER_ACCOUNT_PER_DAY = 10;

/** Minimum views on a post to be worth replying to */
const MIN_VIEWS_THRESHOLD = 100;

/** Reply delay range in ms — randomized to appear human */
const DELAY_MIN_MS = 30_000;
const DELAY_MAX_MS = 60_000;

/** Redis key TTLs */
const SEEN_POST_TTL = 86_400; // 24h
const AUTHOR_TTL = 86_400; // 24h
const ACCOUNT_COUNTER_TTL = 86_400; // 24h
const ADVANCED_ACCESS_SUPPRESSION_TTL = 86_400; // 24h
const THREADS_ADVANCED_ACCESS_SUBCODE = 33;

// ---------------------------------------------------------------------------
// Reply Templates — short, lowercase, casual, persona-matched
// ---------------------------------------------------------------------------

const TEMPLATES_QUESTION = [
	"omg this is such a good question",
	"ok but mine might be embarrassing",
	"literally been thinking about this all day",
	"wait i actually have so many answers for this",
	"this question lives in my head rent free",
	"saving this to answer properly later",
];

const TEMPLATES_HOT_TAKE = [
	"this is so real",
	"finally someone said it",
	"the comments on this are gonna be wild",
	"no bc you're actually so right",
	"needed to hear this today",
	"screenshotting this before it goes viral",
];

const TEMPLATES_RELATABLE = [
	"why is this so accurate",
	"felt this in my soul ngl",
	"literally me rn",
	"did you just read my mind",
	"ok i feel seen",
	"this is too relatable it hurts",
];

const TEMPLATES_GAMING = [
	"ok but what rank are you tho",
	"this game is addicting fr",
	"the way i felt this",
	"genuinely can't stop playing",
	"ok we need to talk about this more",
	"the grind is so real",
];

const TEMPLATES_GENERIC = [
	"this >>",
	"no literally",
	"the way i agree with this",
	"period",
	"say it louder",
	"facts",
	"ngl this hit different",
	"underrated take",
];

/**
 * Topic-keyword to template-set mapping. Falls back to generic
 * if the topic doesn't match any niche.
 */
const TOPIC_TEMPLATE_MAP: Record<string, string[][]> = {
	// Dating / relationships / thirst
	dating: [TEMPLATES_QUESTION, TEMPLATES_RELATABLE, TEMPLATES_HOT_TAKE],
	relationships: [TEMPLATES_QUESTION, TEMPLATES_RELATABLE, TEMPLATES_HOT_TAKE],
	love: [TEMPLATES_RELATABLE, TEMPLATES_HOT_TAKE],
	situationship: [TEMPLATES_RELATABLE, TEMPLATES_HOT_TAKE],

	// Gaming
	gaming: [TEMPLATES_GAMING, TEMPLATES_HOT_TAKE],
	valorant: [TEMPLATES_GAMING],
	fortnite: [TEMPLATES_GAMING],
	apex: [TEMPLATES_GAMING],
	cod: [TEMPLATES_GAMING],
	league: [TEMPLATES_GAMING],

	// Anime
	anime: [TEMPLATES_HOT_TAKE, TEMPLATES_RELATABLE],
	manga: [TEMPLATES_HOT_TAKE, TEMPLATES_RELATABLE],

	// General viral / lifestyle
	viral: [TEMPLATES_RELATABLE, TEMPLATES_HOT_TAKE],
	relatable: [TEMPLATES_RELATABLE],
	unpopular: [TEMPLATES_HOT_TAKE],
	hot_take: [TEMPLATES_HOT_TAKE],
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface KeywordSearchPost {
	id: string;
	text: string;
	username: string;
	like_count: number;
	reply_count: number;
	views: number;
}

interface ReplyFarmingResult {
	sent: number;
	failed: number;
	skipped: number;
	details: string[];
}

interface ContentStrategy {
	pillars?: string[] | undefined;
	topics_to_avoid?: string[] | undefined;
}

class ThreadsAdvancedAccessError extends Error {
	readonly subcode = THREADS_ADVANCED_ACCESS_SUBCODE;

	constructor(message: string) {
		super(message);
		this.name = "ThreadsAdvancedAccessError";
	}
}

// ---------------------------------------------------------------------------
// Core Entry Point
// ---------------------------------------------------------------------------

/**
 * Run one reply farming cycle for a specific account group.
 *
 * 1. Pick a random account from the group
 * 2. Pick a random topic from the group's content strategy pillars
 * 3. Keyword-search for trending posts in that topic
 * 4. Filter: >100 views, not our own accounts, not seen before
 * 5. Reply with short template-based replies
 * 6. Respect rate limits (10/account/day, no duplicate posts/authors)
 */
export async function runReplyFarming(
	workspaceId: string,
	groupId: string,
	accountIds: string[],
	maxRepliesPerRun: number,
): Promise<ReplyFarmingResult> {
	const result: ReplyFarmingResult = {
		sent: 0,
		failed: 0,
		skipped: 0,
		details: [],
	};

	if (!accountIds.length) {
		result.details.push("No account IDs provided");
		return result;
	}

	let redis: ReturnType<typeof getRedis>;
	try {
		redis = getRedis();
	} catch (err) {
		const message = err instanceof Error ? err.message : String(err);
		logger.warn("[replyFarming] Redis unavailable, skipping run", {
			groupId,
			error: message,
		});
		result.details.push("Redis unavailable");
		return result;
	}
	const db = getSupabase();

	// ------------------------------------------------------------------
	// 1. Pick a random account and check daily limit
	// ------------------------------------------------------------------
	const account = await pickEligibleAccount(accountIds, redis, db);
	if (!account) {
		result.details.push(
			"No eligible accounts (all at daily limit or missing credentials)",
		);
		return result;
	}

	// ------------------------------------------------------------------
	// 2. Load group content strategy for topic pillars
	// ------------------------------------------------------------------
	const topics = await getGroupTopics(groupId, db);
	if (!topics.length) {
		result.details.push("No content pillars found for group — skipping");
		return result;
	}

	const topic = topics[Math.floor(Math.random() * topics.length)];

	// ------------------------------------------------------------------
	// 3. Keyword search for trending posts
	// ------------------------------------------------------------------
	let posts: KeywordSearchPost[];
	try {
		posts = await keywordSearch(account.token, topic!);
	} catch (err) {
		const msg = err instanceof Error ? err.message : String(err);
		if (isThreadsAdvancedAccessError(err)) {
			await recordAdvancedAccessFailure({
				workspaceId,
				groupId,
				accountId: account.id,
				username: account.username,
				topic: topic!,
				error: msg,
				redis,
			});
			result.details.push(
				`Reply farming disabled for ${account.username}: Advanced Threads API access required`,
			);
			return result;
		}
		if (isAbortError(err)) {
			logger.info("[replyFarming] Keyword search timed out", {
				accountId: account.id,
				topic,
				timeoutMs: API_TIMEOUT,
			});
			result.details.push(`Search timed out for topic "${topic}"`);
			return result;
		}
		logger.warn("[replyFarming] Keyword search failed", {
			accountId: account.id,
			topic,
			error: msg,
		});
		result.details.push(`Search failed for topic "${topic}": ${msg}`);
		return result;
	}

	if (!posts.length) {
		result.details.push(`No posts found for topic "${topic}"`);
		return result;
	}

	// ------------------------------------------------------------------
	// 4. Collect our own usernames to skip self-replies
	// ------------------------------------------------------------------
	const ourUsernames = await getOurUsernames(account.userId, db);

	// ------------------------------------------------------------------
	// 5. Filter and reply
	// ------------------------------------------------------------------
	const dateKey = new Date().toISOString().split("T")[0]!;
	let repliesSent = 0;

	for (const post of posts) {
		if (repliesSent >= maxRepliesPerRun) break;

		// Skip low-engagement posts
		if ((post.views || 0) < MIN_VIEWS_THRESHOLD) {
			result.skipped++;
			continue;
		}

		// Skip our own accounts
		if (post.username && ourUsernames.has(post.username.toLowerCase())) {
			result.skipped++;
			continue;
		}

		// Skip already-replied posts (dedup)
		const seenKey = `reply-farm-seen:${post.id}`;
		const alreadySeen = await redis.get(seenKey);
		if (alreadySeen) {
			result.skipped++;
			continue;
		}

		// Skip same author twice in a day
		const authorKey = `reply-farm-author:${account.id}:${post.username}:${dateKey}`;
		const authorSeen = await redis.get(authorKey);
		if (authorSeen) {
			result.skipped++;
			continue;
		}

		// Re-check account daily counter (could have been incremented by parallel run)
		const counterKey = `reply-farm:${account.id}:${dateKey}`;
		const currentCount = (await redis.get(counterKey)) as number | null;
		if ((currentCount ?? 0) >= MAX_REPLIES_PER_ACCOUNT_PER_DAY) {
			result.details.push(
				`Account ${account.username} hit daily limit mid-run`,
			);
			break;
		}

		// Pick a contextual reply
		const replyText = pickReply(topic!, post.text);

		// ------------------------------------------------------------------
		// 6. Create container + publish reply
		// ------------------------------------------------------------------
		const success = await postReply(
			account.token,
			account.threadsUserId,
			post.id,
			replyText,
		);

		if (success) {
			repliesSent++;
			result.sent++;

			// Mark post as seen (24h)
			await redis.set(seenKey, "1", { ex: SEEN_POST_TTL }).catch((error) => {
				logger.error("[replyFarming] Dedup write failed for seen post", {
					accountId: account.id,
					postId: post.id,
					error: String(error),
				});
			});
			// Mark author as replied-to today
			await redis.set(authorKey, "1", { ex: AUTHOR_TTL }).catch((error) => {
				logger.error("[replyFarming] Dedup write failed for author", {
					accountId: account.id,
					postId: post.id,
					targetUsername: post.username,
					error: String(error),
				});
			});
			// Increment daily counter
			await redis.incr(counterKey).catch((error) => {
				logger.error("[replyFarming] Daily cap counter increment failed", {
					accountId: account.id,
					postId: post.id,
					error: String(error),
				});
			});
			await redis.expire(counterKey, ACCOUNT_COUNTER_TTL).catch((error) => {
				logger.warn("[replyFarming] Daily cap counter TTL update failed", {
					accountId: account.id,
					postId: post.id,
					error: String(error),
				});
			});

			logger.info("[replyFarming] Reply sent", {
				accountId: account.id,
				username: account.username,
				targetPost: post.id,
				targetUsername: post.username,
				topic,
				reply: replyText,
				views: post.views,
			});

			// Human-like delay between replies (30-60s)
			if (repliesSent < maxRepliesPerRun) {
				const delay =
					DELAY_MIN_MS + Math.random() * (DELAY_MAX_MS - DELAY_MIN_MS);
				await new Promise((resolve) => setTimeout(resolve, delay));
			}
		} else {
			result.failed++;
		}
	}

	if (repliesSent === 0 && result.failed === 0) {
		result.details.push(
			`All ${posts.length} posts filtered out for topic "${topic}"`,
		);
	}

	return result;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface EligibleAccount {
	id: string;
	userId: string;
	username: string;
	threadsUserId: string;
	token: string; // already decrypted
}

/**
 * Pick a random account that hasn't hit its daily reply-farm limit.
 * Shuffles the list to rotate which account replies each run.
 */
async function pickEligibleAccount(
	accountIds: string[],
	redis: ReturnType<typeof getRedis>,
	db: ReturnType<typeof getSupabase>,
): Promise<EligibleAccount | null> {
	// Shuffle for rotation
	const shuffled = [...accountIds].sort(() => Math.random() - 0.5);
	const dateKey = new Date().toISOString().split("T")[0]!;

	for (const accountId of shuffled) {
		const capabilityKey = `reply-farm:advanced-access:${accountId}`;
		if (await redis.get(capabilityKey)) continue;

		// Check daily limit in Redis first (cheap)
		const counterKey = `reply-farm:${accountId}:${dateKey}`;
		const count = (await redis.get(counterKey)) as number | null;
		if ((count ?? 0) >= MAX_REPLIES_PER_ACCOUNT_PER_DAY) continue;

		// Load account credentials
		const { data: acc } = await db
			.from("accounts")
			.select(
				"id, user_id, username, threads_user_id, threads_access_token_encrypted, needs_reauth, is_active",
			)
			.eq("id", accountId)
			.maybeSingle();

		if (!acc) continue;
		if (!acc.threads_access_token_encrypted) continue;
		if (!acc.threads_user_id) continue;
		if (!acc.is_active) continue;
		if ((acc as Record<string, unknown>).needs_reauth) continue;

		try {
			const token = decrypt(acc.threads_access_token_encrypted);
			return {
				id: acc.id,
				userId: acc.user_id,
				username: acc.username || acc.id,
				threadsUserId: acc.threads_user_id,
				token,
			};
		} catch {}
	}

	return null;
}

/**
 * Load content strategy pillars for the group.
 * Falls back to generic keywords if no strategy set.
 */
async function getGroupTopics(
	groupId: string,
	db: ReturnType<typeof getSupabase>,
): Promise<string[]> {
	const { data: group } = await db
		.from("account_groups")
		.select("content_strategy")
		.eq("id", groupId)
		.maybeSingle();

	const strategy = group?.content_strategy as ContentStrategy | null;
	if (strategy?.pillars && strategy.pillars.length > 0) {
		return strategy.pillars;
	}

	// Fallback: generic engaging topics
	return ["viral", "relatable", "hot take", "unpopular opinion"];
}

/**
 * Get all usernames belonging to this user so we don't reply to ourselves.
 */
async function getOurUsernames(
	userId: string,
	db: ReturnType<typeof getSupabase>,
): Promise<Set<string>> {
	const { data: accounts } = await db
		.from("accounts")
		.select("username")
		.eq("user_id", userId)
		.not("username", "is", null);

	const set = new Set<string>();
	for (const acc of accounts || []) {
		if (acc.username) set.add(acc.username.toLowerCase());
	}
	return set;
}

/**
 * Execute a Threads keyword search for TOP posts.
 *
 * Uses the same API pattern as `api/discover.ts` — the Threads
 * keyword_search endpoint at `graph.threads.net/v1.0/keyword_search`.
 */
async function keywordSearch(
	accessToken: string,
	query: string,
): Promise<KeywordSearchPost[]> {
	const params = new URLSearchParams({
		q: query,
		search_type: "TOP",
		limit: "25",
		fields: "id,text,username,like_count,reply_count,views",
		access_token: accessToken,
	});

	const response = await withRetry(
		async () => {
			const controller = new AbortController();
			const timeout = setTimeout(() => controller.abort(), API_TIMEOUT);
			try {
				return await fetch(`${THREADS_API_BASE}/keyword_search?${params}`, {
					signal: controller.signal,
				});
			} finally {
				clearTimeout(timeout);
			}
		},
		{
			label: "reply-farming:keyword-search",
			shouldRetry: (error) => {
				if (isAbortError(error)) return false;
				const status =
					(error as { status?: unknown; code?: unknown })?.status ??
					(error as { code?: unknown })?.code;
				return status === 429 || (typeof status === "number" && status >= 500);
			},
		},
	);

	if (!response.ok) {
		const body = await response.text().catch(() => "");
		const parsed = parseThreadsErrorBody(body);
		if (parsed.errorSubcode === THREADS_ADVANCED_ACCESS_SUBCODE) {
			throw new ThreadsAdvancedAccessError(
				parsed.message || "Threads keyword_search requires Advanced Access",
			);
		}
		throw new Error(`HTTP ${response.status}: ${body.slice(0, 200)}`);
	}

	const data = await response.json();
	return (data.data || []) as KeywordSearchPost[];
}

function isThreadsAdvancedAccessError(
	err: unknown,
): err is ThreadsAdvancedAccessError {
	return (
		err instanceof ThreadsAdvancedAccessError ||
		(err instanceof Error &&
			"subcode" in err &&
			(err as { subcode?: number }).subcode === THREADS_ADVANCED_ACCESS_SUBCODE)
	);
}

function isAbortError(err: unknown): boolean {
	if (err instanceof Error) {
		return (
			err.name === "AbortError" ||
			err.message.toLowerCase().includes("operation was aborted")
		);
	}
	return String(err).toLowerCase().includes("operation was aborted");
}

function parseThreadsErrorBody(body: string): {
	errorSubcode: number | null;
	message: string | null;
} {
	try {
		const parsed = JSON.parse(body) as {
			error?: { error_subcode?: number; message?: string };
			error_subcode?: number;
			message?: string;
		};
		return {
			errorSubcode: parsed.error?.error_subcode ?? parsed.error_subcode ?? null,
			message: parsed.error?.message ?? parsed.message ?? null,
		};
	} catch {
		return { errorSubcode: null, message: null };
	}
}

async function recordAdvancedAccessFailure({
	workspaceId,
	groupId,
	accountId,
	username,
	topic,
	error,
	redis,
}: {
	workspaceId: string;
	groupId: string;
	accountId: string;
	username: string;
	topic: string;
	error: string;
	redis: ReturnType<typeof getRedis>;
}) {
	const now = new Date();
	const blockedUntil = new Date(
		now.getTime() + ADVANCED_ACCESS_SUPPRESSION_TTL * 1000,
	).toISOString();
	const dateKey = now.toISOString().split("T")[0]!;
	const suppressionKey = `reply-farm:advanced-access:${accountId}`;
	const warnKey = `reply-farm:advanced-access-warn:${accountId}:${dateKey}`;

	await redis.set(suppressionKey, "1", {
		ex: ADVANCED_ACCESS_SUPPRESSION_TTL,
	});

	const warned = await redis.get(warnKey);
	if (!warned) {
		logger.warn(
			"[replyFarming] Threads keyword_search requires Advanced Access",
			{
				accountId,
				username,
				topic,
				error,
				blockedUntil,
			},
		);
		await redis.set(warnKey, "1", { ex: ADVANCED_ACCESS_SUPPRESSION_TTL });
	}

	const db = getSupabaseAny();
	const { error: upsertError } = await db
		.from("account_capability_errors")
		.upsert(
			{
				workspace_id: workspaceId,
				group_id: groupId,
				account_id: accountId,
				platform: "threads",
				capability: "reply_farming",
				error_code: "needs_advanced_access",
				message:
					"Reply farming disabled - Advanced Threads API access required.",
				metadata: { topic, username, source: "threads_keyword_search" },
				blocked_until: blockedUntil,
				last_seen_at: now.toISOString(),
				resolved_at: null,
			},
			{ onConflict: "account_id,capability,error_code" },
		);

	if (upsertError) {
		logger.warn("[replyFarming] Failed to persist capability error", {
			accountId,
			error: upsertError.message,
		});
	}
}

/**
 * Pick a reply from template sets based on topic + post content heuristics.
 */
function pickReply(topic: string, postText: string): string {
	const lowerText = (postText || "").toLowerCase();
	const lowerTopic = topic.toLowerCase().replace(/\s+/g, "_");

	// Detect question posts (likely engagement bait — highest value)
	const isQuestion =
		lowerText.includes("?") ||
		lowerText.startsWith("what") ||
		lowerText.startsWith("who") ||
		lowerText.startsWith("how") ||
		lowerText.startsWith("which") ||
		lowerText.startsWith("would you") ||
		lowerText.startsWith("do you");

	if (isQuestion) {
		return randomFrom(TEMPLATES_QUESTION);
	}

	// Check topic-specific templates
	const topicSets = TOPIC_TEMPLATE_MAP[lowerTopic];
	if (topicSets && topicSets.length > 0) {
		const chosenSet = topicSets[Math.floor(Math.random() * topicSets.length)];
		return randomFrom(chosenSet!);
	}

	// Detect hot take / opinion posts
	const hotTakeSignals = [
		"unpopular opinion",
		"hot take",
		"idc what anyone says",
		"i don't care",
		"let's be honest",
		"nobody talks about",
		"am i the only one",
	];
	if (hotTakeSignals.some((s) => lowerText.includes(s))) {
		return randomFrom(TEMPLATES_HOT_TAKE);
	}

	// Detect relatable / vulnerable posts
	const relatableSignals = [
		"i feel like",
		"does anyone else",
		"is it just me",
		"why do i",
		"honestly",
		"ngl",
		"not gonna lie",
		"can we normalize",
	];
	if (relatableSignals.some((s) => lowerText.includes(s))) {
		return randomFrom(TEMPLATES_RELATABLE);
	}

	// Fallback: generic engagement reply
	return randomFrom(TEMPLATES_GENERIC);
}

/**
 * Pick a random item from an array.
 */
function randomFrom(arr: string[]): string {
	return arr[Math.floor(Math.random() * arr.length)]!;
}

/**
 * Post a reply to a Threads post using the two-step container→publish flow.
 *
 * Same pattern as `autoReplyEngine.ts:sendThreadsReply` but with
 * already-decrypted token (we decrypt once in pickEligibleAccount).
 */
async function postReply(
	accessToken: string,
	threadsUserId: string,
	replyToId: string,
	text: string,
): Promise<boolean> {
	try {
		// Step 1: Create container with reply_to_id
		const containerParams = new URLSearchParams({
			media_type: "TEXT",
			text,
			reply_to_id: replyToId,
			access_token: accessToken,
		});

		const containerRes = await withRetry(() =>
			fetch(`${THREADS_API_BASE}/${threadsUserId}/threads`, {
				method: "POST",
				body: containerParams,
				signal: AbortSignal.timeout(API_TIMEOUT),
			}),
		);

		const containerData = await containerRes.json();
		if (!containerRes.ok || containerData.error) {
			const errMsg =
				containerData.error?.message || `HTTP ${containerRes.status}`;

			// Don't flag transient Meta 500s — they're not dead tokens
			// See CLAUDE.md: "An unknown error has occurred (code=1, type=OAuthException)"
			logger.warn("[replyFarming] Container creation failed", {
				replyToId,
				error: errMsg,
			});
			return false;
		}

		const containerId = containerData.id as string;

		// Step 2: Publish
		const publishParams = new URLSearchParams({
			creation_id: containerId,
			access_token: accessToken,
		});

		const publishRes = await withRetry(() =>
			fetch(`${THREADS_API_BASE}/${threadsUserId}/threads_publish`, {
				method: "POST",
				body: publishParams,
				signal: AbortSignal.timeout(API_TIMEOUT),
			}),
		);

		const publishData = await publishRes.json();
		if (!publishRes.ok || publishData.error) {
			logger.warn("[replyFarming] Publish failed", {
				replyToId,
				error: publishData.error?.message || `HTTP ${publishRes.status}`,
			});
			return false;
		}

		return true;
	} catch (err) {
		logger.warn("[replyFarming] postReply exception", {
			replyToId,
			error: err instanceof Error ? err.message : String(err),
		});
		return false;
	}
}
