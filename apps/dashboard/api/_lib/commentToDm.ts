// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Comment-to-DM Funnel — automatically DMs snap info to users who
 * comment on our IG posts with trigger keywords.
 *
 * Keyword-triggered conditional DMs have 7-12x better conversion than
 * blasting every commenter. Only fires when the comment text contains
 * a configured trigger keyword (case-insensitive).
 *
 * Only fires once per user per account (never spam the same person twice).
 *
 * Uses sendPrivateReply (Meta's comment_id-based DM) so we don't need
 * the commenter's IGSID — just the comment_id from the webhook.
 */

import { logger } from "./logger.js";

// ============================================================================
// Trigger Keyword Detection
// ============================================================================

/** Default keywords that signal intent — only DM when comment contains one */
const DEFAULT_TRIGGER_KEYWORDS = [
	"snap",
	"sc",
	"link",
	"dm me",
	"send",
	"how do i",
	"where",
	"add me",
	"username",
];

function escapeRegExp(value: string): string {
	return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Check if a comment contains any trigger keyword (case-insensitive).
 * Uses word-boundary-aware matching so "snap" matches "snap?" and "Snap!"
 * but short keywords don't false-positive inside unrelated words.
 */
export function containsTriggerKeyword(
	commentText: string,
	keywords?: string[],
): { matched: boolean; keyword?: string | undefined } {
	if (!commentText) return { matched: false };

	const list =
		keywords && keywords.length > 0 ? keywords : DEFAULT_TRIGGER_KEYWORDS;

	for (const kw of list) {
		const normalized = kw.trim();
		if (!normalized) continue;
		const pattern = new RegExp(
			`(^|[^\\p{L}\\p{N}_])${escapeRegExp(normalized)}(?=$|[^\\p{L}\\p{N}_])`,
			"iu",
		);
		if (pattern.test(commentText)) {
			return { matched: true, keyword: kw };
		}
	}

	return { matched: false };
}

// ============================================================================
// DM Message Templates — randomized to avoid looking automated
// ============================================================================

const DM_TEMPLATES = [
	"hey! thanks for the comment 💕 add me on snap if u wanna talk more 👻 {snap}",
	"omg hey! u should add my snap 👻 {snap}",
	"heyy 💕 add me 👻 {snap}",
	"hey cutie 😊 my snap is {snap} if u wanna chat 👻",
	"tysm for commenting 💕 add my snap {snap} 👻",
	"hii! lets be friends on snap 👻 {snap}",
];

/** Pick a random template and fill in the snap username */
function buildDmMessage(snapUsername: string): string {
	const template =
		DM_TEMPLATES[Math.floor(Math.random() * DM_TEMPLATES.length)];
	return template!.replace("{snap}", snapUsername);
}

// ============================================================================
// Rate Limit Constants
// ============================================================================

/** Max DMs per account per calendar day */
const MAX_DMS_PER_DAY = 20;
/** Max DMs per account per clock hour */
const MAX_DMS_PER_HOUR = 5;
/** Dedup TTL: don't DM the same commenter from the same account for 30 days */
const DEDUP_TTL_SECONDS = 30 * 24 * 60 * 60; // 30 days

// ============================================================================
// Core Function
// ============================================================================

/**
 * Process a comment event and send a DM with the snap username.
 * Only sends when the comment text contains a trigger keyword.
 *
 * @param igAccountId      - The IG account's `instagram_user_id` (Meta page-scoped ID)
 * @param commentId        - The comment ID from the webhook (used for sendPrivateReply)
 * @param commenterUsername - The commenter's @username (for logging / self-DM guard)
 * @param encryptedToken   - The IG account's encrypted access token
 * @param snapUsername      - The snap username to include in the DM
 * @param loginType        - The IG account login type (for Graph API base URL selection)
 * @param accountUsername  - The IG account's own username (to avoid DMing ourselves)
 * @param commentText      - The comment text (used for keyword matching)
 * @param triggerKeywords  - Custom trigger keywords from content_strategy (optional, uses defaults)
 */
export async function processCommentForDm(
	igAccountId: string,
	commentId: string,
	commenterUsername: string,
	encryptedToken: string,
	snapUsername: string,
	loginType?: string,
	accountUsername?: string,
	commentText?: string,
	triggerKeywords?: string[],
): Promise<{ sent: boolean; reason?: string | undefined }> {
	const logCtx = { igAccountId, commentId, commenterUsername };

	// ── Guard: no snap username configured ──
	if (!snapUsername) {
		return { sent: false, reason: "no_snap_username" };
	}

	// ── Guard: never DM ourselves ──
	if (
		accountUsername &&
		commenterUsername &&
		accountUsername.toLowerCase() === commenterUsername.toLowerCase()
	) {
		logger.debug("[comment-to-dm] Skipping self-comment", logCtx);
		return { sent: false, reason: "self_comment" };
	}

	// ── Guard: missing required fields ──
	if (!commentId || !encryptedToken) {
		logger.warn("[comment-to-dm] Missing commentId or token", logCtx);
		return { sent: false, reason: "missing_fields" };
	}

	// ── Guard: keyword trigger check ──
	// Only DM when comment contains a trigger keyword (7-12x better conversion)
	if (!commentText) {
		logger.debug("[comment-to-dm] No comment text, skipping DM", logCtx);
		return { sent: false, reason: "no_comment_text" };
	}

	const { matched, keyword } = containsTriggerKeyword(
		commentText,
		triggerKeywords,
	);
	if (!matched) {
		logger.debug("[comment-to-dm] No trigger keyword in comment, skipping DM", {
			...logCtx,
			commentPreview: commentText.slice(0, 80),
		});
		return { sent: false, reason: "no_keyword_match" };
	}

	logger.info("[comment-to-dm] Trigger keyword matched", {
		...logCtx,
		keyword,
		commentPreview: commentText.slice(0, 80),
	});

	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();

		// ── Dedup: already DMed this commenter from this account? ──
		// We key on commenterUsername since comment webhooks may not include IGSID
		const dedupKey = `dm-sent:${igAccountId}:${commenterUsername.toLowerCase()}`;
		const alreadySent = await redis.get(dedupKey);
		if (alreadySent) {
			logger.debug("[comment-to-dm] Already DMed this user", logCtx);
			return { sent: false, reason: "already_sent" };
		}

		// ── Rate limit: daily cap ──
		const today = new Date().toISOString().split("T")[0]!;
		const dailyKey = `dm-daily:${igAccountId}:${today}`;
		const dailyCount = (await redis.get<number>(dailyKey)) ?? 0;
		if (dailyCount >= MAX_DMS_PER_DAY) {
			logger.info("[comment-to-dm] Daily DM cap reached", {
				...logCtx,
				dailyCount,
			});
			return { sent: false, reason: "daily_cap" };
		}

		// ── Rate limit: hourly cap ──
		const hour = new Date().toISOString().slice(0, 13); // "2026-04-03T14"
		const hourlyKey = `dm-hourly:${igAccountId}:${hour}`;
		const hourlyCount = (await redis.get<number>(hourlyKey)) ?? 0;
		if (hourlyCount >= MAX_DMS_PER_HOUR) {
			logger.info("[comment-to-dm] Hourly DM cap reached", {
				...logCtx,
				hourlyCount,
			});
			return { sent: false, reason: "hourly_cap" };
		}

		// ── Build message ──
		const message = buildDmMessage(snapUsername);

		// ── Send DM via private reply (uses comment_id, no IGSID needed) ──
		const { sendPrivateReply } = await import("./instagramApi.js");
		const result = await sendPrivateReply(
			encryptedToken,
			igAccountId,
			commentId,
			message,
			loginType,
		);

		if (!result.success) {
			logger.warn("[comment-to-dm] Failed to send DM", {
				...logCtx,
				error: result.error,
			});
			return { sent: false, reason: `send_failed: ${result.error}` };
		}

		// ── Mark as sent + bump counters ──
		await Promise.all([
			redis.set(dedupKey, "1", { ex: DEDUP_TTL_SECONDS }),
			redis.incr(dailyKey),
			redis.incr(hourlyKey),
		]);

		// Set TTL on counters if they were just created (incr returns 1 on first call)
		// Daily key expires at end of day, hourly key expires after 1 hour
		const pipeline = redis.pipeline();
		pipeline.expire(dailyKey, 86400); // 24h
		pipeline.expire(hourlyKey, 3600); // 1h
		await pipeline.exec();

		logger.info("[comment-to-dm] DM sent successfully", {
			...logCtx,
			messageId: result.messageId,
			snapUsername,
		});

		return { sent: true };
	} catch (error: unknown) {
		// Fail-safe: DM failures never block webhook processing
		logger.error("[comment-to-dm] Unexpected error", {
			...logCtx,
			error: error instanceof Error ? error.message : String(error),
		});
		return { sent: false, reason: "unexpected_error" };
	}
}

// ============================================================================
// Helper: resolve snap username for an IG account
// ============================================================================

/**
 * Look up the snap username for an IG account by finding its account_group
 * and checking `content_strategy.snapUsername` on the group.
 *
 * Falls back to the account_group name for persona-based lookup.
 */
export async function resolveSnapUsername(
	igAccountId: string,
	userId: string,
): Promise<string | null> {
	const config = await resolveDmConfig(igAccountId, userId);
	return config?.snapUsername ?? null;
}

/**
 * Resolve full DM config for an IG account: snap username + trigger keywords.
 * Reads from `content_strategy` on the account's group.
 */
export async function resolveDmConfig(
	igAccountId: string,
	userId: string,
): Promise<{ snapUsername: string; dmTriggerKeywords?: string[] | undefined } | null> {
	try {
		const { getSupabase } = await import("./supabase.js");
		const db = getSupabase();

		// Find which group this IG account belongs to
		const { data: igAccount } = await db
			.from("instagram_accounts")
			.select("id, group_id, username")
			.eq("instagram_user_id", igAccountId)
			.maybeSingle();

		if (!igAccount?.group_id) {
			logger.debug("[comment-to-dm] IG account has no group_id", {
				igAccountId,
			});
			return null;
		}

		// Check group's content_strategy for snapUsername + dmTriggerKeywords
		const { data: group } = await db
			.from("account_groups")
			.select("id, name, content_strategy")
			.eq("id", igAccount.group_id)
			.eq("user_id", userId)
			.maybeSingle();

		if (!group) return null;

		const strategy = group.content_strategy as Record<string, unknown> | null;
		if (!strategy?.snapUsername || typeof strategy.snapUsername !== "string") {
			return null;
		}

		// Extract optional custom trigger keywords from content_strategy
		let dmTriggerKeywords: string[] | undefined;
		if (Array.isArray(strategy.dmTriggerKeywords)) {
			const filtered = (strategy.dmTriggerKeywords as unknown[]).filter(
				(k): k is string => typeof k === "string" && k.length > 0,
			);
			if (filtered.length > 0) {
				dmTriggerKeywords = filtered;
			}
		}

		return {
			snapUsername: strategy.snapUsername,
			dmTriggerKeywords,
		};
	} catch (error: unknown) {
		logger.error("[comment-to-dm] Error resolving DM config", {
			igAccountId,
			error: error instanceof Error ? error.message : String(error),
		});
		return null;
	}
}
