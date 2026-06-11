// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Auto-Post Content Selection Module
 *
 * Handles content selection, AI adaptation, queue auto-fill,
 * competitor post sourcing, and voice profile resolution.
 */

import { logger } from "../../logger.js";
import { getSupabase } from "../../supabase.js";
import type { Account, ExtractedStyle, VoiceProfile } from "./types.js";

const db = () => getSupabase();

/**
 * Detect thirst/dating niche from voice profile and content strategy.
 * Extracted into a helper so it can be used by both selectContentTypes
 * (for deterministic content distribution) and the prompt builder.
 */
export function detectThirstNiche(
	voiceProfile?: VoiceProfile | null,
	toneNotes?: string | null,
): boolean {
	const voiceText = voiceProfile?.voice_profile?.toLowerCase() ?? "";
	const toneText = toneNotes?.toLowerCase() ?? "";
	const signal = `${voiceText} ${toneText}`;
	return (
		signal.includes("thirst") ||
		signal.includes("dating") ||
		signal.includes("sexy") ||
		signal.includes("flirt") ||
		signal.includes("spicy") ||
		signal.includes("gfe") ||
		signal.includes("onlyfans") ||
		signal.includes("seduct") ||
		signal.includes("innuendo")
	);
}

// ============================================================================
// Timezone Helpers
// ============================================================================

export function getLocalTime(
	now: Date,
	timezone: string | undefined,
): { hour: number; dayOfWeek: number } {
	const tz = timezone || "America/New_York";
	try {
		const parts = new Intl.DateTimeFormat("en-US", {
			timeZone: tz,
			hour: "numeric",
			hour12: false,
			weekday: "short",
		}).formatToParts(now);

		const hourPart = parts.find((p) => p.type === "hour");
		const weekdayPart = parts.find((p) => p.type === "weekday");

		const hour = hourPart ? parseInt(hourPart.value, 10) : now.getHours();
		const dayMap: Record<string, number> = {
			Sun: 0,
			Mon: 1,
			Tue: 2,
			Wed: 3,
			Thu: 4,
			Fri: 5,
			Sat: 6,
		};
		const dayOfWeek = weekdayPart
			? (dayMap[weekdayPart.value] ?? now.getDay())
			: now.getDay();

		return { hour, dayOfWeek };
	} catch (err) {
		logger.debug("Failed to parse local time for timezone", {
			timezone: tz,
			error: String(err),
		});
		return { hour: now.getHours(), dayOfWeek: now.getDay() };
	}
}

export function getTodayInTimezone(timezone: string | undefined): string {
	const tz = timezone || "America/New_York";
	try {
		const formatter = new Intl.DateTimeFormat("en-CA", {
			timeZone: tz,
			year: "numeric",
			month: "2-digit",
			day: "2-digit",
		});
		return formatter.format(new Date());
	} catch (err) {
		logger.debug("Failed to format today's date for timezone", {
			timezone: tz,
			error: String(err),
		});
		return new Date().toISOString().split("T")[0]!;
	}
}

/**
 * Daily post target with ±2 variation from the config value.
 * Simple random jitter so accounts don't all post the same count.
 */
export function getDailyPostTarget(
	baseTarget: number,
	accountId: string,
	dateStr: string,
): number {
	// Deterministic hash per account+date — same account gets same target all day,
	// but different accounts and different days get different targets.
	// Uses FNV-1a for better distribution with short strings.
	let hash = 2166136261; // FNV offset basis
	const seed = `${dateStr}|${accountId}|${dateStr}`;
	for (let i = 0; i < seed.length; i++) {
		hash ^= seed.charCodeAt(i);
		hash = Math.imul(hash, 16777619); // FNV prime
	}
	hash = hash >>> 0; // ensure unsigned

	// Map hash to a tight range around base. Old distribution had 10% at 2x base
	// which caused 53% more AI generation calls and blew the Gemini budget.
	const normalized = hash % 100; // 0-99
	let target: number;
	if (normalized < 30) {
		// 30% chance: base - 1 (light day)
		target = baseTarget - 1;
	} else if (normalized < 70) {
		// 40% chance: base (normal day)
		target = baseTarget;
	} else {
		// 30% chance: base + 1 (busy day)
		target = baseTarget + 1;
	}
	return Math.max(1, target);
}

// ============================================================================
// Warmup Logic
// ============================================================================

export function calculateWarmupAllowance(
	warmup: NonNullable<Account["ai_config"]>["warmup"] | undefined,
): number | null {
	if (!warmup?.warmup_enabled || !warmup.warmup_start_date) {
		return null;
	}

	if (warmup.warmup_completed_at) {
		return null;
	}

	const startDate = new Date(warmup.warmup_start_date);
	const today = new Date();
	startDate.setHours(0, 0, 0, 0);
	today.setHours(0, 0, 0, 0);

	const daysSinceStart = Math.floor(
		(today.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24),
	);

	const allowance =
		warmup.warmup_start_posts + daysSinceStart * warmup.warmup_increment;

	return Math.min(allowance, warmup.warmup_target);
}

export function getWarmupDayNumber(
	warmup: NonNullable<Account["ai_config"]>["warmup"] | undefined,
): number {
	if (!warmup?.warmup_start_date) return 0;

	const startDate = new Date(warmup.warmup_start_date);
	const today = new Date();
	startDate.setHours(0, 0, 0, 0);
	today.setHours(0, 0, 0, 0);

	return (
		Math.floor(
			(today.getTime() - startDate.getTime()) / (1000 * 60 * 60 * 24),
		) + 1
	);
}

// ============================================================================
// Competitor Content Sourcing
// ============================================================================

// ============================================================================
// AI Configuration & Voice Profile
// ============================================================================

// Canonical implementation lives in api/_lib/aiConfig.ts — re-export for
// backward compatibility with all downstream importers.
export { getUserAIConfig } from "../../aiConfig.js";

export async function getUserExtractedStyle(
	userId: string,
): Promise<ExtractedStyle | null> {
	try {
		const { data: accounts } = await db()
			.from("accounts")
			.select("ai_config")
			.eq("user_id", userId)
			.not("ai_config", "is", null);

		if (!accounts || accounts.length === 0) return null;

		for (const account of accounts) {
			const aiConfig = account.ai_config as Record<string, unknown> | null;
			if (aiConfig?.extracted_style) {
				return aiConfig.extracted_style as ExtractedStyle;
			}
		}
		return null;
	} catch (err) {
		logger.debug("Failed to fetch extracted style for user", {
			userId,
			error: String(err),
		});
		return null;
	}
}

export function getAccountExtractedStyle(
	account: Account,
): ExtractedStyle | null {
	try {
		const aiConfig = account.ai_config as Record<string, unknown> | null;
		if (aiConfig?.extracted_style) {
			return aiConfig.extracted_style as ExtractedStyle;
		}
		return null;
	} catch (err) {
		logger.debug("Failed to parse account extracted style", {
			error: String(err),
		});
		return null;
	}
}

async function getAccountVoiceProfile(
	accountId: string,
): Promise<VoiceProfile | null> {
	try {
		const { data } = await db()
			.from("accounts")
			.select("ai_config")
			.eq("id", accountId)
			.maybeSingle();

		if (!data?.ai_config) return null;
		return data.ai_config as VoiceProfile;
	} catch (err) {
		logger.debug("Failed to fetch voice profile for account", {
			accountId,
			error: String(err),
		});
		return null;
	}
}

async function getGroupVoiceProfile(
	accountId: string,
	ownerId: string,
): Promise<VoiceProfile | null> {
	try {
		const { data: groups } = await db()
			.from("account_groups")
			.select("voice_profile, account_ids")
			.eq("user_id", ownerId)
			.not("voice_profile", "is", null);

		if (!groups || groups.length === 0) return null;

		for (const group of groups) {
			const accountIds = (group.account_ids || []) as string[];
			if (accountIds.includes(accountId) && group.voice_profile) {
				return group.voice_profile as VoiceProfile;
			}
		}

		return null;
	} catch (err) {
		logger.debug("Failed to fetch group voice profile for account", {
			accountId,
			error: String(err),
		});
		return null;
	}
}

export async function getWorkspaceVoiceProfile(
	ownerId: string,
): Promise<VoiceProfile | null> {
	try {
		const { data } = await db()
			.from("accounts")
			.select("ai_config")
			.eq("user_id", ownerId)
			.not("ai_config", "is", null)
			.limit(1)
			.maybeSingle();

		if (!data?.ai_config) return null;
		return data.ai_config as VoiceProfile;
	} catch (err) {
		logger.debug("Failed to fetch workspace voice profile for owner", {
			ownerId,
			error: String(err),
		});
		return null;
	}
}

export async function resolveVoiceProfile(
	accountId: string,
	ownerId: string,
): Promise<VoiceProfile | null> {
	const accountProfile = await getAccountVoiceProfile(accountId);
	if (accountProfile?.voice_profile) {
		logger.info("Using account-level voice profile", { accountId });
		return accountProfile;
	}

	const groupProfile = await getGroupVoiceProfile(accountId, ownerId);
	if (groupProfile?.voice_profile) {
		logger.info("Using group-level voice profile", { accountId });
		return groupProfile;
	}

	const workspaceProfile = await getWorkspaceVoiceProfile(ownerId);
	if (workspaceProfile) {
		logger.info("Using workspace-level voice profile fallback", { accountId });
	}
	return workspaceProfile;
}

/**
 * Simple similarity check — returns true if content is too similar to any recent post.
 * Uses normalized trigram overlap as a cheap approximation.
 * Threshold lowered from 0.55 to 0.45 to catch near-paraphrases.
 */
export function isTooSimilar(
	content: string,
	recentContents: string[],
	threshold = 0.45,
): boolean {
	const normalize = (s: string) =>
		s
			.toLowerCase()
			.replace(/[^a-z0-9 ]/g, "")
			.trim();
	const trigrams = (s: string): Set<string> => {
		const n = normalize(s);
		const t = new Set<string>();
		for (let i = 0; i < n.length - 2; i++) t.add(n.slice(i, i + 3));
		return t;
	};

	const contentTrigrams = trigrams(content);
	if (contentTrigrams.size === 0) return false;

	for (const recent of recentContents) {
		const recentTrigrams = trigrams(recent);
		if (recentTrigrams.size === 0) continue;
		let overlap = 0;
		for (const t of contentTrigrams) if (recentTrigrams.has(t)) overlap++;
		const similarity =
			overlap / Math.max(contentTrigrams.size, recentTrigrams.size);
		if (similarity > threshold) return true;
	}
	return false;
}

import type { SinglePostConstraints } from "./promptBuilder.js";
// Import from promptBuilder.ts (used internally by checkAndFillQueueWithAI)
// and re-export for backward compatibility
import {
	generateAIPostIdeas,
	generateSinglePost,
	generateVariations,
} from "./promptBuilder.js";

export type { ProviderCallOptions } from "./aiProviders.js";
// Re-export from aiProviders.ts for backward compatibility
export {
	adjustContentForPlatform,
	generateWithProvider,
} from "./aiProviders.js";
// Re-export from queueFill.ts for backward compatibility
export {
	calculateNaturalPostTimes,
	checkAndFillQueueWithAI,
	countPendingPosts,
} from "./queueFill.js";
export type { SinglePostConstraints };
export { generateAIPostIdeas, generateSinglePost, generateVariations };
