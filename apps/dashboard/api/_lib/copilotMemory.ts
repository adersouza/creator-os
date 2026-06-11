// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Co-Pilot Session Memory
 *
 * Extracts user preferences from conversations and persists them
 * so the Co-Pilot can personalize future responses.
 */

import { logger as _driftLogger, logger } from "./logger.js";
import { getSupabase } from "./supabase.js";

const MAX_MEMORY_ITEMS = 10;

interface MemoryItem {
	key: string;
	value: string;
}

/**
 * Extract preferences from a user message + AI response via pattern matching.
 */
export function extractPreferences(
	userMessage: string,
	_aiResponse: string,
): MemoryItem[] {
	const items: MemoryItem[] = [];

	// Caption length preference
	if (/i\s+prefer\s+(short|long)\s+captions?/i.test(userMessage)) {
		const match = userMessage.match(/i\s+prefer\s+(short|long)\s+captions?/i);
		if (match)
			items.push({ key: "caption_length", value: match[1]!.toLowerCase() });
	}

	// Hashtag preference
	if (/i\s+don'?t\s+like\s+hashtags?/i.test(userMessage)) {
		items.push({ key: "hashtag_preference", value: "none" });
	} else if (/i\s+love\s+hashtags?/i.test(userMessage)) {
		items.push({ key: "hashtag_preference", value: "heavy" });
	}

	// Audience context
	// #633: Sanitize extracted values — truncate + strip control chars to prevent prompt injection
	const sanitizeValue = (v: string) =>
		v
			.replace(/\p{Cc}/gu, "")
			.trim()
			.slice(0, 100);

	const audienceMatch = userMessage.match(
		/my\s+audience\s+is\s+mostly\s+(.+?)(?:\.|,|$)/i,
	);
	if (audienceMatch) {
		items.push({
			key: "audience_context",
			value: sanitizeValue(audienceMatch[1]!),
		});
	}

	// Content topic
	const topicMatch = userMessage.match(/i\s+post\s+about\s+(.+?)(?:\.|,|$)/i);
	if (topicMatch) {
		items.push({ key: "content_topic", value: sanitizeValue(topicMatch[1]!) });
	}

	return items;
}

/**
 * Upsert a memory item for a user. Enforces max 10 items by deleting oldest.
 */
export async function storeMemory(
	userId: string,
	key: string,
	value: string,
): Promise<void> {
	try {
		const supabase = getSupabase();

		// Upsert the memory item
		await supabase
			.from("copilot_memory")
			.upsert(
				{ user_id: userId, key, value, updated_at: new Date().toISOString() },
				{ onConflict: "user_id,key" },
			);

		// Enforce cap: count items, delete oldest if over limit
		const { data: allItems } = await supabase
			.from("copilot_memory")
			.select("id, updated_at")
			.eq("user_id", userId)
			.order("updated_at", { ascending: true });

		if (allItems && allItems.length > MAX_MEMORY_ITEMS) {
			const toDelete = allItems.slice(0, allItems.length - MAX_MEMORY_ITEMS);
			const ids = toDelete.map((item: { id: string }) => item.id);
			await supabase.from("copilot_memory").delete().in("id", ids);
		}
	} catch (err) {
		logger.error("[copilotMemory] storeMemory failed", {
			userId,
			key,
			error: String(err),
		});
	}
}

/**
 * Load all memory items for a user as a formatted string.
 */
export async function loadMemory(userId: string): Promise<string> {
	try {
		const supabase = getSupabase();
		const { data } = await supabase
			.from("copilot_memory")
			.select("key, value")
			.eq("user_id", userId)
			.order("updated_at", { ascending: false });

		if (!data || data.length === 0) return "";

		return buildMemoryPrompt(data);
	} catch (err) {
		logger.error("[copilotMemory] loadMemory failed", {
			userId,
			error: String(err),
		});
		return "";
	}
}

/**
 * Build a system prompt fragment from memory items.
 */
export function buildMemoryPrompt(memories: MemoryItem[]): string {
	if (!memories || memories.length === 0) return "";

	const labels: Record<string, string> = {
		caption_length: "prefers {value} captions",
		hashtag_preference: "{value} hashtags",
		audience_context: "audience is mostly {value}",
		content_topic: "posts about {value}",
	};

	const parts = memories.map((m) => {
		const template = labels[m.key];
		if (template) return template.replace("{value}", m.value);
		return `${m.key}: ${m.value}`;
	});

	return `User preferences from past conversations: ${parts.join(", ")}.`;
}

/* ------------------------------------------------------------------ */
/*  Preference Drift Detection                                        */
/* ------------------------------------------------------------------ */

export interface PreferenceDrift {
	field: string;
	oldValue: string;
	newValue: string;
	suggestion: string;
}

const EMOJI_REGEX = /[\p{Emoji_Presentation}\p{Extended_Pictographic}]/gu;

/**
 * Compare the user's last 10 posts against their Style Bible to detect
 * stylistic drift (caption length, emoji usage).
 */
export async function detectPreferenceDrift(
	userId: string,
): Promise<PreferenceDrift[]> {
	const drifts: PreferenceDrift[] = [];

	try {
		const supabase = getSupabase();

		// Get user's accounts
		const { data: accounts } = await supabase
			.from("accounts")
			.select("id")
			.eq("user_id", userId);
		const accountIds = (accounts ?? []).map((a) => a.id);
		if (accountIds.length === 0) return drifts;

		// Get style bible
		// biome-ignore lint/suspicious/noExplicitAny: style_bibles not in generated types
		const { data: styleBible } = await (supabase as any)
			.from("style_bibles")
			.select("profile")
			.eq("user_id", userId)
			.maybeSingle();

		if (!styleBible?.profile) return drifts;

		const profile = styleBible.profile as {
			avgLength?: number | undefined;
			emojiUsage?: "heavy" | "moderate" | "minimal" | "none" | undefined;
		};

		// Get last 10 posts with text
		const { data: posts } = await supabase
			.from("posts")
			.select("text_content")
			.in("account_id", accountIds)
			.not("text_content", "is", null)
			.order("created_at", { ascending: false })
			.limit(10);

		if (!posts || posts.length < 3) return drifts;

		const captions = (
			posts as unknown as Array<{ text_content?: string | null | undefined }>
		)
			.map((p) => p.text_content as string)
			.filter(Boolean);
		if (captions.length === 0) return drifts;

		// Caption length drift
		if (profile.avgLength && profile.avgLength > 0) {
			const currentAvg = Math.round(
				captions.reduce((s: number, c: string) => s + c.length, 0) /
					captions.length,
			);
			const ratio = currentAvg / profile.avgLength;

			if (ratio > 1.4 || ratio < 0.6) {
				const direction = ratio > 1 ? "longer" : "shorter";
				drifts.push({
					field: "caption_length",
					oldValue: `${profile.avgLength} chars`,
					newValue: `${currentAvg} chars`,
					suggestion: `Your captions have been trending ${direction} lately (avg ${profile.avgLength} → ${currentAvg} chars). Want to update your Style Bible?`,
				});
			}
		}

		// Emoji usage drift
		if (profile.emojiUsage) {
			const totalEmojis = captions.reduce(
				(s: number, c: string) => s + (c.match(EMOJI_REGEX)?.length ?? 0),
				0,
			);
			const avgEmojis = totalEmojis / captions.length;

			const currentUsage: string =
				avgEmojis >= 5
					? "heavy"
					: avgEmojis >= 2
						? "moderate"
						: avgEmojis >= 0.5
							? "minimal"
							: "none";

			const levels = ["none", "minimal", "moderate", "heavy"];
			const oldIdx = levels.indexOf(profile.emojiUsage);
			const newIdx = levels.indexOf(currentUsage);

			if (Math.abs(oldIdx - newIdx) >= 2) {
				drifts.push({
					field: "emoji_usage",
					oldValue: profile.emojiUsage,
					newValue: currentUsage,
					suggestion: `Your emoji usage shifted from "${profile.emojiUsage}" to "${currentUsage}". Want to update your Style Bible?`,
				});
			}
		}
	} catch (err) {
		_driftLogger.warn("[copilotMemory] detectPreferenceDrift failed", {
			userId,
			error: String(err),
		});
	}

	return drifts;
}
