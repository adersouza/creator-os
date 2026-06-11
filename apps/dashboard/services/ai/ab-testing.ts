import { logger } from "@/utils/logger";
import type { AIContext } from "./contextEngine.js";
import { contextToSystemPrompt } from "./contextEngine.js";
import { generateContent } from "./core.js";
import type { VoiceProfile } from "./ideas.js";
import { buildVoiceContext, loadVoiceProfile } from "./voiceHelpers.js";

export interface ABVariation {
	id: string;
	label: string;
	content: string;
	changeType: "hook" | "cta" | "tone" | "format";
	description: string;
}

/**
 * Generate A/B test variations of a post
 * Creates 3 variations: different hook, different CTA, different format
 */
export const generateABVariations = async (
	originalContent: string,
	voiceProfile?: VoiceProfile,
	aiContext?: AIContext,
): Promise<ABVariation[]> => {
	// Use unified AI context if provided, otherwise fall back to voice profile
	let voiceContext = "";
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		const vp = voiceProfile ?? (await loadVoiceProfile());
		voiceContext = vp ? buildVoiceContext(vp) : "";
	}

	const prompt = `You are an A/B testing expert for social media. Create 3 variations of this post for testing different approaches.
${voiceContext}
ORIGINAL POST:
"""
${originalContent}
"""

Create these 3 specific variations:

1. HOOK VARIATION: Same message, but with a completely different opening line (hook). Make it more attention-grabbing.

2. CTA VARIATION: Same message, but change the ending to have a different call-to-action. Could be a question, invitation to comment, or action prompt.

3. FORMAT VARIATION: Same message, but restructure it - different line breaks, emoji placement, or sentence structure.

Return as JSON array with exactly 3 objects:
[
  {"changeType": "hook", "content": "...", "description": "Changed hook to..."},
  {"changeType": "cta", "content": "...", "description": "Changed CTA to..."},
  {"changeType": "format", "content": "...", "description": "Restructured to..."}
]

Each content must be under 500 characters. Return ONLY valid JSON, no markdown.`;

	try {
		const response = await generateContent(prompt);

		// Parse JSON response
		const jsonMatch = response.match(/\[[\s\S]*\]/);
		if (!jsonMatch) {
			throw new Error("Invalid JSON response");
		}

		const variations = JSON.parse(jsonMatch[0]) as Array<{
			changeType: "hook" | "cta" | "tone" | "format";
			content: string;
			description: string;
		}>;

		return variations.map((v, i) => ({
			id: `variation-${i + 1}`,
			label: `Variation ${String.fromCharCode(65 + i)}`, // A, B, C
			content: v.content.substring(0, 500),
			changeType: v.changeType,
			description: v.description,
		}));
	} catch (error) {
		logger.error("[aiService] generateABVariations error:", error);
		// Return fallback variations
		return [
			{
				id: "variation-1",
				label: "Variation A",
				content: originalContent,
				changeType: "hook",
				description: "Original content",
			},
		];
	}
};

/**
 * Generate A/B test variants that differ only in the tested element
 */
export const generateABTestVariants = async (
	originalContent: string,
	testType: "hook" | "cta" | "emoji" | "length" | "tone",
	variantCount: number = 2,
	voiceProfile?: VoiceProfile,
	aiContext?: AIContext,
): Promise<{ label: string; content: string; changeDescription: string }[]> => {
	let voiceContext = "";
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		const vp = voiceProfile ?? (await loadVoiceProfile());
		voiceContext = vp ? buildVoiceContext(vp) : "";
	}
	const testInstructions: Record<string, string> = {
		hook: "Change ONLY the opening hook/first line. Keep everything else identical.",
		cta: "Change ONLY the call-to-action at the end. Keep everything else identical.",
		emoji:
			"Change ONLY the emoji usage (add, remove, or swap emojis). Keep text identical.",
		length: "Create a shorter version AND a longer version. Keep core message.",
		tone: "Rewrite in a different tone (casual vs professional, etc). Keep same message.",
	};

	const prompt = `Create ${variantCount} variations of this post for A/B testing.
${voiceContext}
ORIGINAL POST:
"${originalContent}"

TEST TYPE: ${testType}
INSTRUCTION: ${testInstructions[testType]}

Return JSON array:
[
  {
    "label": "A",
    "content": "the variation",
    "changeDescription": "what was changed"
  }
]

CRITICAL:
- Variant A should be the original or very close
- Other variants should differ ONLY in the tested element
- Keep character count similar (unless testing length)
- Return ONLY valid JSON`;

	try {
		const response = await generateContent(prompt);
		const jsonMatch = response.match(/\[[\s\S]*\]/);
		if (!jsonMatch) throw new Error("No JSON array found");
		return JSON.parse(jsonMatch[0]);
	} catch (error) {
		logger.error("[aiService] generateABTestVariants failed:", error);
		return [];
	}
};

/**
 * Analyze A/B test results and determine winner
 */
