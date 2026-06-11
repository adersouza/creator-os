// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Shadowban Recovery Protocol — automated 7-day recovery sequence
 *
 * When an account is flagged as shadowbanned (is_shadowbanned = true
 * on account_health_snapshots), this protocol runs an automated
 * recovery sequence:
 *
 *   Day 1-3: SILENCE — stop posting entirely
 *   Day 4-5: 1 safe post/day (questions only, zero CTAs, zero sexual content)
 *   Day 6-7: 1 normal strategy post. If views return > 0, recovery succeeded.
 *   Day 8+:  Gradual ramp 1 → 2 → 3 posts/day
 *
 * If recovery fails after 2 cycles (14 days), mark permanently dead.
 *
 * Also tracks content posted in 48 hours BEFORE each shadowban.
 * Builds "shadowban trigger" patterns to feed back into quality gate.
 *
 * Runs daily via daily-orchestrator.
 */

import { AlertLevel, alert } from "../alerting.js";
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

const LOG_PREFIX = "[shadowban-recovery]";

// ============================================================================
// Recovery Phases
// ============================================================================

type RecoveryPhase =
	| "silence"
	| "safe_posting"
	| "normal_test"
	| "ramp_up"
	| "recovered"
	| "permanently_dead";

function getRecoveryPhase(
	daysSinceBan: number,
	cycleNumber: number,
): RecoveryPhase {
	if (cycleNumber >= 3) return "permanently_dead";

	const dayInCycle = daysSinceBan % 7;

	if (dayInCycle < 3) return "silence"; // Day 0-2: No posting
	if (dayInCycle < 5) return "safe_posting"; // Day 3-4: Safe content only
	if (dayInCycle < 7) return "normal_test"; // Day 5-6: Normal strategy test
	return "ramp_up"; // Day 7+: Gradual ramp
}

// ============================================================================
// Types
// ============================================================================

interface RecoveryResult {
	accountsInRecovery: number;
	silenced: number;
	safePostsQueued: number;
	normalTestsQueued: number;
	recovered: number;
	permanentlyDead: number;
	triggerPatternsFound: number;
}

// ============================================================================
// Main Orchestrator
// ============================================================================

export async function processShadowbanRecovery(): Promise<RecoveryResult> {
	const result: RecoveryResult = {
		accountsInRecovery: 0,
		silenced: 0,
		safePostsQueued: 0,
		normalTestsQueued: 0,
		recovered: 0,
		permanentlyDead: 0,
		triggerPatternsFound: 0,
	};

	try {
		// Get all shadowbanned accounts from health snapshots
		const { data: bannedAccounts } = await db()
			.from("account_health_snapshots")
			.select(
				"account_id, user_id, account_name, is_shadowbanned, consecutive_dead_days, auto_disabled, auto_disabled_at, recovery_attempts",
			)
			.eq("account_table", "accounts")
			.eq("is_shadowbanned", true)
			.eq("period_days", 7);

		if (!bannedAccounts || bannedAccounts.length === 0) {
			logger.info(`${LOG_PREFIX} No shadowbanned accounts`);
			return result;
		}

		result.accountsInRecovery = bannedAccounts.length;
		logger.info(
			`${LOG_PREFIX} Processing ${bannedAccounts.length} shadowbanned accounts`,
		);

		for (const account of bannedAccounts) {
			try {
				await processAccountRecovery(account, result);
			} catch (err) {
				logger.error(`${LOG_PREFIX} Account recovery failed`, {
					accountId: account.account_id,
					error: serializeError(err),
				});
			}
		}

		// Analyze shadowban triggers (content posted before bans)
		result.triggerPatternsFound = await analyzeShadowbanTriggers();

		logger.info(`${LOG_PREFIX} Complete`, { ...result });

		// Discord summary if anything happened
		if (
			result.recovered > 0 ||
			result.permanentlyDead > 0 ||
			result.safePostsQueued > 0
		) {
			await alert(AlertLevel.INFO, "Shadowban recovery update", {
				inRecovery: String(result.accountsInRecovery),
				silenced: String(result.silenced),
				safePostsQueued: String(result.safePostsQueued),
				recovered: String(result.recovered),
				permanentlyDead: String(result.permanentlyDead),
			});
		}
	} catch (err) {
		logger.error(`${LOG_PREFIX} Fatal error`, { error: serializeError(err) });
	}

	return result;
}

// ============================================================================
// Per-Account Recovery
// ============================================================================

async function processAccountRecovery(
	account: {
		account_id: string;
		user_id: string;
		account_name: string;
		consecutive_dead_days: number;
		auto_disabled_at: string | null;
		recovery_attempts: number;
	},
	result: RecoveryResult,
): Promise<void> {
	const daysSinceBan = account.consecutive_dead_days || 0;
	const cycleNumber = account.recovery_attempts || 0;
	const phase = getRecoveryPhase(daysSinceBan, cycleNumber);

	// Check if account has recovered (views > 0 on recent posts)
	const hasViews = await checkForViewRecovery(account.account_id);

	if (hasViews) {
		// RECOVERED! Unflag and re-enable
		await db()
			.from("account_health_snapshots")
			.update({
				is_shadowbanned: false,
				consecutive_dead_days: 0,
				auto_disabled: false,
				health_score: 20, // Start at "struggling" tier
				health_tier: "struggling",
				posts_per_day_override: 2,
			})
			.eq("account_table", "accounts")
			.eq("account_id", account.account_id)
			.eq("period_days", 7);

		await db()
			.from("accounts")
			.update({ is_active: true })
			.eq("id", account.account_id);

		result.recovered++;
		logger.info(`${LOG_PREFIX} Account RECOVERED`, {
			account: account.account_name,
			daysSinceBan,
		});
		return;
	}

	switch (phase) {
		case "silence":
			// Ensure account is disabled (no posting)
			await db()
				.from("accounts")
				.update({ is_active: false })
				.eq("id", account.account_id);
			result.silenced++;
			break;

		case "safe_posting": {
			// Re-enable with 1 post/day, safe content only
			await db()
				.from("accounts")
				.update({ is_active: true })
				.eq("id", account.account_id);

			await db()
				.from("account_health_snapshots")
				.update({ posts_per_day_override: 1 })
				.eq("account_table", "accounts")
				.eq("account_id", account.account_id)
				.eq("period_days", 7);

			// Queue a safe post (question format, no CTAs)
			const safeQueued = await queueSafeRecoveryPost(account);
			if (safeQueued) result.safePostsQueued++;
			break;
		}

		case "normal_test":
			// 1 normal strategy post
			await db()
				.from("account_health_snapshots")
				.update({ posts_per_day_override: 1 })
				.eq("account_table", "accounts")
				.eq("account_id", account.account_id)
				.eq("period_days", 7);
			result.normalTestsQueued++;
			// Let the normal autoposter handle content
			break;

		case "ramp_up": {
			// Gradual ramp: 1 → 2 → 3 over days
			const rampDay = daysSinceBan - 7;
			const rampPosts = Math.min(3, 1 + Math.floor(rampDay / 2));
			await db()
				.from("account_health_snapshots")
				.update({ posts_per_day_override: rampPosts })
				.eq("account_table", "accounts")
				.eq("account_id", account.account_id)
				.eq("period_days", 7);
			break;
		}

		case "permanently_dead":
			// Mark as permanently dead after 3 failed cycles
			await db()
				.from("accounts")
				.update({ is_active: false })
				.eq("id", account.account_id);

			await db()
				.from("account_health_snapshots")
				.update({
					auto_disabled: true,
					health_score: 0,
					health_tier: "dead",
					posts_per_day_override: 0,
				})
				.eq("account_table", "accounts")
				.eq("account_id", account.account_id)
				.eq("period_days", 7);

			result.permanentlyDead++;
			logger.warn(`${LOG_PREFIX} Account permanently dead`, {
				account: account.account_name,
				cycles: cycleNumber,
			});
			break;
	}
}

// ============================================================================
// Recovery Detection
// ============================================================================

async function checkForViewRecovery(accountId: string): Promise<boolean> {
	const threeDaysAgo = new Date(
		Date.now() - 3 * 24 * 60 * 60 * 1000,
	).toISOString();

	const { data: recentPosts } = await db()
		.from("posts")
		.select("views_count, engagement_fetched_at")
		.eq("account_id", accountId)
		.eq("platform", "threads")
		.eq("status", "published")
		.not("engagement_fetched_at", "is", null)
		.gte("published_at", threeDaysAgo)
		.limit(5);

	if (!recentPosts || recentPosts.length === 0) return false;

	// Any post with >0 views = recovery signal
	return recentPosts.some(
		(p: { views_count: number }) => (p.views_count || 0) > 0,
	);
}

// ============================================================================
// Safe Recovery Post Generation
// ============================================================================

async function queueSafeRecoveryPost(account: {
	account_id: string;
	user_id: string;
	account_name: string;
}): Promise<boolean> {
	const aiConfig = await getUserAIConfig(account.user_id);
	if (!aiConfig) return false;

	const voice = await resolveVoiceProfile(account.account_id, account.user_id);
	const voiceDesc = voice?.voice_profile || "casual, authentic creator";

	// Get workspace for queue insertion
	const { data: ws } = await db()
		.from("workspaces")
		.select("id")
		.eq("owner_id", account.user_id)
		.maybeSingle();
	if (!ws) return false;

	// Get account's group
	const { data: acc } = await db()
		.from("accounts")
		.select("group_id")
		.eq("id", account.account_id)
		.maybeSingle();

	const prompt = `Generate ONE safe, engagement-friendly question post for Threads.

VOICE: ${voiceDesc}

RULES — THIS IS A RECOVERY POST, MUST BE ULTRA SAFE:
- MUST be a question that invites replies
- Zero CTAs, zero links, zero mentions
- Zero sexual content, zero thirst trap energy
- Zero controversial takes
- Keep it relatable and universally appealing
- Under 80 characters
- Lowercase, casual, 0-1 emojis
- Examples of safe recovery posts:
  "what's the most unhinged thing you do when you're home alone"
  "be honest how many alarms do you set in the morning"
  "what song are you currently playing on repeat"
  "do you eat the crust or nah"

OUTPUT: Just the post text, nothing else.`;

	const raw = await generateWithProvider(prompt, {
		provider: aiConfig.provider,
		apiKey: aiConfig.apiKey,
		baseUrl: aiConfig.baseUrl,
		model: aiConfig.model,
		ideaCount: 1,
	});

	if (!raw) return false;

	let content = raw
		.replace(/^["']|["']$/g, "")
		.replace(/\n/g, " ")
		.trim();
	const filterConfig = resolveFilterConfig(null, 100, 1, 5);
	const filterResult = filterContent(content, filterConfig);
	if (!filterResult.passed) return false;
	if (content.length > 100) content = `${content.slice(0, 97)}...`;

	// Schedule 2-6 hours from now (during a reasonable time)
	const scheduledFor = new Date(
		Date.now() + (2 + Math.random() * 4) * 60 * 60 * 1000,
	);

	const { error } = await db()
		.from("auto_post_queue")
		.insert({
			workspace_id: ws.id,
			group_id: acc?.group_id || null,
			account_id: account.account_id,
			content,
			status: "pending",
			scheduled_for: scheduledFor.toISOString(),
			source_type: "recovery",
		});

	if (error) {
		logger.error(`${LOG_PREFIX} Failed to queue recovery post`, {
			error: String(error),
		});
		return false;
	}

	logger.info(`${LOG_PREFIX} Safe recovery post queued`, {
		account: account.account_name,
		content: content.slice(0, 50),
		scheduledFor: scheduledFor.toISOString(),
	});

	return true;
}

// ============================================================================
// Shadowban Trigger Analysis
// ============================================================================

/**
 * Analyze content posted in 48 hours BEFORE each shadowban detection.
 * Build patterns that may trigger shadowbans.
 */
async function analyzeShadowbanTriggers(): Promise<number> {
	try {
		// Get recently shadowbanned accounts (last 7 days)
		const { data: recentBans } = await db()
			.from("account_health_snapshots")
			.select("account_id, computed_at")
			.eq("account_table", "accounts")
			.eq("is_shadowbanned", true)
			.eq("period_days", 7)
			.gte(
				"computed_at",
				new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
			);

		if (!recentBans || recentBans.length === 0) return 0;

		const triggerPatterns = new Map<string, number>();

		for (const ban of recentBans) {
			const banTime = new Date(ban.computed_at);
			const beforeBan = new Date(
				banTime.getTime() - 48 * 60 * 60 * 1000,
			).toISOString();

			// Get posts from 48h before ban
			const { data: preBanPosts } = await db()
				.from("posts")
				.select("content")
				.eq("account_id", ban.account_id)
				.eq("platform", "threads")
				.eq("status", "published")
				.gte("published_at", beforeBan)
				.lte("published_at", banTime.toISOString());

			for (const post of preBanPosts || []) {
				const content = (post.content || "").toLowerCase();

				// Detect common trigger patterns
				if (/\bdm\b|snap|add me/i.test(content))
					triggerPatterns.set(
						"cta_dm_snap",
						(triggerPatterns.get("cta_dm_snap") || 0) + 1,
					);
				if (/link.*bio|bio.*link/i.test(content))
					triggerPatterns.set(
						"cta_link_bio",
						(triggerPatterns.get("cta_link_bio") || 0) + 1,
					);
				if (/🍑|🍆|👅|💦|🔥.*🔥/u.test(content))
					triggerPatterns.set(
						"suggestive_emoji_cluster",
						(triggerPatterns.get("suggestive_emoji_cluster") || 0) + 1,
					);
				if (content.length > 200)
					triggerPatterns.set(
						"long_post_200plus",
						(triggerPatterns.get("long_post_200plus") || 0) + 1,
					);
				if (/#\w+.*#\w+.*#\w+/i.test(content))
					triggerPatterns.set(
						"multiple_hashtags",
						(triggerPatterns.get("multiple_hashtags") || 0) + 1,
					);
			}
		}

		// Store trigger patterns as agent note
		if (triggerPatterns.size > 0) {
			const sorted = [...triggerPatterns.entries()].sort(
				([, a], [, b]) => b - a,
			);
			const noteContent = JSON.stringify({
				date: new Date().toISOString().split("T")[0]!,
				triggers: sorted.map(([pattern, count]) => ({
					pattern,
					occurrences: count,
				})),
				totalBannedAccounts: recentBans.length,
				recommendation: "Add top trigger patterns to content filter blacklist",
			});

			// Delete existing then insert (cron functions don't have user context)
			await db()
				.from("agent_notes")
				.delete()
				.eq("key", "shadowban-triggers")
				.is("account_group_id", null);
			await db().from("agent_notes").insert({
				key: "shadowban-triggers",
				value: noteContent,
				updated_at: new Date().toISOString(),
			});
		}

		return triggerPatterns.size;
	} catch (err) {
		logger.error(`${LOG_PREFIX} Trigger analysis failed`, {
			error: serializeError(err),
		});
		return 0;
	}
}
