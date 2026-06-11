import type { Json } from "../../types/supabase.js";
import type { ExtractedStyle } from "../../types/voice.js";
import { logger } from "@/utils/logger";
import { dataService } from "../dataService.js";
import { supabase } from "../supabase.js";
import { generateContent } from "./core.js";
import type { VoiceProfile } from "./ideas.js";

function isJsonValue(value: unknown): value is Json {
	if (
		value === null ||
		typeof value === "string" ||
		typeof value === "number" ||
		typeof value === "boolean"
	) {
		return true;
	}

	if (Array.isArray(value)) {
		return value.every((item) => isJsonValue(item));
	}

	if (typeof value !== "object") {
		return false;
	}

	return Object.values(value).every(
		(item) => item === undefined || isJsonValue(item),
	);
}

export const extractStyleDNA = async (
	posts: string[],
): Promise<ExtractedStyle | null> => {
	if (!posts || posts.length < 3) {
		logger.warn(
			"[aiService] extractStyleDNA: Need at least 3 posts for meaningful extraction",
		);
		return null;
	}

	const postsContext = posts
		.slice(0, 20)
		.map((p, i) => `${i + 1}. ${p}`)
		.join("\n\n");

	const prompt = `Analyze these posts from a single creator and extract their EXACT writing DNA. Be extremely specific - I need to clone their voice precisely.

POSTS:
${postsContext}

Extract and return a JSON object. PRIORITIZE by impact (hooks and vocabulary matter most):

{
  "hooks": {
    "patterns": ["list 3-5 opening patterns they use - be specific like 'Unpopular opinion:', 'Hot take:', etc."],
    "examples": ["direct quotes of their best hooks - max 15 words each"]
  },
  "vocabulary": {
    "signature_words": ["words or phrases they overuse intentionally - max 10, be very specific"],
    "avoid_words": ["words they seem to never use - max 5"],
    "tone_markers": ["exact phrases that define their unique voice - max 5, quote directly"]
  },
  "tone": {
    "vibe": "describe their overall vibe in 3-5 words (e.g., 'casual, bold, slightly confrontational, relatable')",
    "energy": "low-key" | "moderate" | "high-energy" | "chaotic"
  },
  "length": {
    "typical_chars": "estimate typical character count range (e.g., '80-180')",
    "preference": "very-short" | "short" | "medium" | "long"
  },
  "sentence_patterns": {
    "avg_length": "short" | "medium" | "long",
    "structure": "simple" | "compound" | "fragmented" | "mixed",
    "rhythm": "description of their writing cadence"
  },
  "emoji_usage": {
    "frequency": "none" | "rare" | "moderate" | "heavy",
    "placement": "start" | "end" | "inline" | "emphasis",
    "favorites": ["most used emojis - list up to 5"]
  },
  "punctuation": {
    "quirks": ["specific punctuation habits like 'lots of !', 'minimal commas', 'uses ... for drama'"],
    "question_frequency": "never" | "rare" | "often" | "signature"
  },
  "closings": {
    "patterns": ["how they typically end posts"],
    "cta_style": "none" | "soft" | "direct" | "link-focused"
  },
  "formatting": {
    "line_breaks": "minimal" | "moderate" | "heavy",
    "lists": true | false,
    "caps_usage": "none" | "emphasis" | "shouting"
  }
}

CRITICAL: Be extremely specific. Quote actual examples. This will be used to generate content that sounds EXACTLY like this person wrote it.

Return ONLY valid JSON, no markdown.`;

	try {
		const response = await generateContent(prompt);

		// Parse JSON response
		const jsonMatch = response.match(/\{[\s\S]*\}/);
		if (!jsonMatch) {
			logger.error("[aiService] extractStyleDNA: No JSON found in response");
			return null;
		}

		const extracted: ExtractedStyle = JSON.parse(jsonMatch[0]);
		extracted.extracted_at = new Date().toISOString();

		logger.info(
			"[aiService] extractStyleDNA: Successfully extracted style DNA",
		);
		return extracted;
	} catch (error) {
		logger.error("[aiService] extractStyleDNA failed:", error);
		return null;
	}
};

/**
 * Result type for style extraction operations that may fail due to insufficient data.
 */
export type StyleExtractionResult =
	| { success: true; style: ExtractedStyle }
	| { success: false; error: "need_more_posts"; postsCount: number }
	| { success: false; error: "extraction_failed"; postsCount: number }
	| { success: false; error: "save_failed"; postsCount: number };

/**
 * Get top posts for style extraction
 * Returns content strings sorted by engagement
 */
export const getTopPostsForStyleExtraction = async (
	limit: number = 20,
): Promise<string[]> => {
	try {
		const publishedPosts = (await dataService.getPublishedPostsForAI({
			limit: 500,
		})).filter(
			(p) =>
				p.content &&
				p.content.length > 20, // Need meaningful content
		);

		if (publishedPosts.length === 0) {
			return [];
		}

		// Sort by engagement (replies weighted most, then shares, then likes)
		const sorted = publishedPosts.sort((a, b) => {
			const engA =
				(a.likes || 0) +
				(a.replies || 0) * 2 +
				(a.performance?.shares || 0) * 3;
			const engB =
				(b.likes || 0) +
				(b.replies || 0) * 2 +
				(b.performance?.shares || 0) * 3;
			return engB - engA;
		});

		return sorted.slice(0, limit).map((p) => p.content);
	} catch (error) {
		logger.error("[aiService] getTopPostsForStyleExtraction error:", error);
		return [];
	}
};

/**
 * Save extracted style DNA to an account's ai_config
 * This merges the extracted style with existing voice profile settings
 */
export const saveExtractedStyleToAccount = async (
	accountId: string,
	extractedStyle: ExtractedStyle,
): Promise<boolean> => {
	try {
		// First get existing ai_config
		const { data: account, error: fetchError } = await supabase
			.from("accounts")
			.select("ai_config")
			.eq("id", accountId)
			.maybeSingle();

		if (fetchError) {
			logger.error("[aiService] Failed to fetch account:", fetchError);
			return false;
		}

		// Merge extracted style with existing config
		const existingConfig = (account?.ai_config as VoiceProfile) || {};
		const updatedConfig: VoiceProfile = {
			...existingConfig,
			extracted_style: extractedStyle,
		};
		if (!isJsonValue(updatedConfig)) {
			logger.error(
				"[aiService] Extracted style config is not JSON-serializable",
			);
			return false;
		}

		// Save back to account
		const { error: updateError } = await supabase
			.from("accounts")
			.update({ ai_config: updatedConfig })
			.eq("id", accountId);

		if (updateError) {
			logger.error("[aiService] Failed to save extracted style:", updateError);
			return false;
		}

		logger.info("[aiService] Saved extracted style to account:", accountId);
		return true;
	} catch (error) {
		logger.error("[aiService] saveExtractedStyleToAccount error:", error);
		return false;
	}
};

/**
 * Full extraction flow: get posts, extract style, save to account
 * Call this when user clicks "Analyze My Style" button
 *
 * Returns ExtractedStyle | null for backwards compatibility.
 * Use extractAndSaveStyleDNAWithStatus() for structured error info.
 */
export const extractAndSaveStyleDNA = async (
	accountId: string,
): Promise<ExtractedStyle | null> => {
	const result = await extractAndSaveStyleDNAWithStatus(accountId);
	return result.success ? result.style : null;
};

/**
 * Full extraction flow with structured error reporting.
 * Returns a discriminated union so callers can distinguish
 * "not enough posts" from other failures.
 */
export const extractAndSaveStyleDNAWithStatus = async (
	accountId: string,
): Promise<StyleExtractionResult> => {
	try {
		// Get top posts for this account
		const posts = await getTopPostsForStyleExtraction(20);

		if (posts.length < 3) {
			logger.warn(
				`[aiService] Not enough posts for style extraction (have ${posts.length}, need 3)`,
			);
			return {
				success: false,
				error: "need_more_posts",
				postsCount: posts.length,
			};
		}

		// Extract style DNA
		const extractedStyle = await extractStyleDNA(posts);

		if (!extractedStyle) {
			return {
				success: false,
				error: "extraction_failed",
				postsCount: posts.length,
			};
		}

		// Save to account
		const saved = await saveExtractedStyleToAccount(accountId, extractedStyle);

		if (!saved) {
			logger.warn("[aiService] Extraction succeeded but save failed");
			return { success: false, error: "save_failed", postsCount: posts.length };
		}

		return { success: true, style: extractedStyle };
	} catch (error) {
		logger.error("[aiService] extractAndSaveStyleDNAWithStatus error:", error);
		return { success: false, error: "extraction_failed", postsCount: 0 };
	}
};

// ===== INSPIRATION ENGINE AI FUNCTIONS =====
