// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Voice Profile Helpers
 * Shared utilities for loading and formatting voice profiles across all AI features.
 * Includes Style Bible integration — style bible takes priority over generic voice profile.
 */

import { logger } from "@/utils/logger";
import { supabase } from "../supabase.js";
import type { VoiceProfile } from "./ideas.js";

// ---------------------------------------------------------------------------
// Style Bible types & loader
// ---------------------------------------------------------------------------

export interface StyleBibleProfile {
	avgLength: number;
	toneWords: string[];
	emojiUsage: "heavy" | "moderate" | "minimal" | "none";
	hashtagStyle: "inline" | "block" | "none";
	ctaPatterns: string[];
	sentenceStyle: "short" | "mixed" | "long";
	personality: string;
}

export interface StyleBible {
	id: string;
	user_id: string;
	account_id: string | null;
	sample_captions: string[];
	extracted_profile: StyleBibleProfile;
	created_at: string;
	updated_at: string;
}

/**
 * Load the user's style bible (account-specific first, then global fallback).
 */
export const loadStyleBible = async (
	accountId?: string,
): Promise<StyleBible | null> => {
	try {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session?.user) return null;

		// Try account-specific first
		if (accountId) {
			const { data } = await supabase
				.from("style_bibles")
				.select("*")
				.eq("user_id", session.user.id)
				.eq("account_id", accountId)
				.maybeSingle();
			if (data) return data as unknown as StyleBible;
		}

		// Fallback to global (null account_id)
		const { data } = await supabase
			.from("style_bibles")
			.select("*")
			.eq("user_id", session.user.id)
			.is("account_id", null)
			.maybeSingle();

		return (data as unknown as StyleBible) ?? null;
	} catch (error) {
		logger.error("[voiceHelpers] loadStyleBible error:", error);
		return null;
	}
};

/**
 * Build a style bible context string for AI prompt injection.
 */
export const buildStyleBibleContext = (sb: StyleBibleProfile): string => {
	const parts: string[] = [];

	if (sb.personality) parts.push(`PERSONALITY: ${sb.personality}`);
	if (sb.toneWords?.length) parts.push(`TONE: ${sb.toneWords.join(", ")}`);
	if (sb.emojiUsage) parts.push(`EMOJI USAGE: ${sb.emojiUsage}`);
	if (sb.hashtagStyle) parts.push(`HASHTAG STYLE: ${sb.hashtagStyle}`);
	if (sb.sentenceStyle) parts.push(`SENTENCE STYLE: ${sb.sentenceStyle}`);
	if (sb.avgLength) parts.push(`AVG CAPTION LENGTH: ~${sb.avgLength} chars`);
	if (sb.ctaPatterns?.length)
		parts.push(`CTA PATTERNS: ${sb.ctaPatterns.join(", ")}`);

	if (parts.length === 0) return "";
	return `\n📖 STYLE BIBLE (HIGHEST PRIORITY — match this writing style exactly):\n${parts.join("\n")}`;
};

/**
 * Build combined voice context: style bible (priority) + voice profile (fallback enrichment).
 */
export const buildCombinedVoiceContext = async (
	vp?: VoiceProfile | null,
	accountId?: string,
): Promise<string> => {
	const styleBible = await loadStyleBible(accountId);
	const parts: string[] = [];

	if (styleBible?.extracted_profile) {
		parts.push(buildStyleBibleContext(styleBible.extracted_profile));
	}

	if (vp) {
		parts.push(buildVoiceContext(vp));
	}

	return parts.join("\n");
};

/**
 * Load the current user's voice profile from Supabase.
 * Returns the VoiceProfile stored in the account's ai_config, or null.
 */
export const loadVoiceProfile = async (
	accountId?: string,
): Promise<VoiceProfile | null> => {
	try {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session?.user) return null;

		// Try to get the active account's ai_config which contains the voice profile
		let query = supabase
			.from("accounts")
			.select("ai_config")
			.eq("user_id", session.user.id);

		if (accountId) {
			// Filter to the specific account when accountId is provided
			query = query.eq("id", accountId);
		}

		const { data: accounts, error } = await query.limit(1);

		if (error || !accounts || accounts.length === 0) {
			return null;
		}

		const aiConfig = accounts[0]!.ai_config as VoiceProfile | null;
		if (!aiConfig) return null;

		return aiConfig;
	} catch (error) {
		logger.error("[voiceHelpers] loadVoiceProfile error:", error);
		return null;
	}
};

/**
 * Build a voice context string from a VoiceProfile for injection into AI prompts.
 * Returns a formatted string describing the user's writing style, or empty string.
 */
export const buildVoiceContext = (vp: VoiceProfile): string => {
	const parts: string[] = [];

	if (vp.voice_profile) {
		parts.push(`VOICE/PERSONA: ${vp.voice_profile}`);
	}

	if (vp.focus_topics?.length) {
		parts.push(`FOCUS TOPICS: ${vp.focus_topics.join(", ")}`);
	}

	if (vp.avoid_topics?.length) {
		parts.push(`AVOID TOPICS: ${vp.avoid_topics.join(", ")}`);
	}

	if (vp.avoid_words?.length) {
		parts.push(`NEVER USE THESE WORDS: ${vp.avoid_words.join(", ")}`);
	}

	if (vp.emoji_usage) {
		parts.push(`EMOJI USAGE: ${vp.emoji_usage}`);
	}

	if (vp.cta_style && vp.cta_style !== "none") {
		parts.push(`CTA STYLE: ${vp.cta_style}`);
	}

	// Include extracted style DNA if available
	const es = vp.extracted_style;
	if (es) {
		if (es.tone?.vibe) parts.push(`TONE: ${es.tone.vibe}`);
		if (es.tone?.energy) parts.push(`ENERGY: ${es.tone.energy}`);
		if (es.vocabulary?.signature_words?.length) {
			parts.push(
				`SIGNATURE WORDS: ${es.vocabulary.signature_words.join(", ")}`,
			);
		}
		if (es.vocabulary?.tone_markers?.length) {
			parts.push(`TONE MARKERS: ${es.vocabulary.tone_markers.join(", ")}`);
		}
		if (es.hooks?.patterns?.length) {
			parts.push(`HOOK PATTERNS: ${es.hooks.patterns.join(", ")}`);
		}
		if (es.length?.preference) {
			parts.push(`LENGTH PREFERENCE: ${es.length.preference}`);
		}
		if (es.emoji_usage?.frequency) {
			parts.push(`EMOJI FREQUENCY: ${es.emoji_usage.frequency}`);
		}
		if (es.emoji_usage?.favorites?.length) {
			parts.push(`FAVORITE EMOJIS: ${es.emoji_usage.favorites.join(" ")}`);
		}
	}

	if (parts.length === 0) return "";

	return `\n🎭 VOICE PROFILE (MATCH THIS EXACTLY):\n${parts.join("\n")}`;
};
