// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { logger } from "@/utils/logger";
import { dataService } from "../dataService.js";
import { analyzeTopPostStructure, calculateSimilarity } from "./analytics.js";
import type { AIContext } from "./contextEngine.js";
import { contextToSystemPrompt } from "./contextEngine.js";
import { generateContent } from "./core.js";
import { buildVoiceContext, loadVoiceProfile } from "./voiceHelpers.js";

export const adaptCompetitorPost = async (
	originalContent: string,
	competitorUsername: string,
	style: "casual" | "professional" | "witty" | "inspirational" = "casual",
	aiContext?: AIContext,
): Promise<string> => {
	// Use unified AI context if provided, otherwise fall back to voice profile
	let voiceContext = "";
	let voiceProfile = null;
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		voiceProfile = await loadVoiceProfile();
		voiceContext = voiceProfile ? buildVoiceContext(voiceProfile) : "";
	}

	// Load feedback context for personalization
	let feedbackContext = "";
	try {
		const { buildFeedbackContext } = await import(
			"../../utils/buildFeedbackContext.js"
		);
		feedbackContext = await buildFeedbackContext("content_variation");
	} catch {
		/* non-critical */
	}

	const styleDescriptions: Record<string, string> = {
		casual: "casual, conversational, and relatable",
		professional: "professional, authoritative, and polished",
		witty: "witty, clever, and playful with humor",
		inspirational: "inspirational, motivational, and uplifting",
	};

	// Determine target length from voice profile or default
	const targetLength = voiceProfile?.extracted_style?.length?.typical_chars
		? `Stay around ${voiceProfile.extracted_style.length.typical_chars} characters (your typical length).`
		: "Stay under 500 characters.";

	const prompt = voiceContext
		? `Transform this viral post from @${competitorUsername} into YOUR voice. The result must sound like YOU wrote it from scratch — not like a rewrite.
${voiceContext}

ORIGINAL POST: "${originalContent}"
${feedbackContext}
ADAPTATION RULES:
1. Extract the CONCEPT or HOOK that made this post work
2. Rewrite from scratch in YOUR voice using your signature phrases and tone
3. Use YOUR hook patterns — don't copy their hook style
4. Add YOUR perspective, angle, or experience
5. ${targetLength}
6. Match YOUR formatting style (line breaks, emoji placement, punctuation)
7. Use a ${styleDescriptions[style]} approach
8. The final post should pass the "did I write this?" test

Return ONLY the new post text, nothing else.`
		: `Transform this viral post from @${competitorUsername} into your own unique version:

Original: "${originalContent}"
${feedbackContext}
Requirements:
1. Keep the winning hook/concept but make it YOUR voice
2. Use a ${styleDescriptions[style]} tone
3. Add a fresh angle or personal touch
4. Stay under 500 characters
5. Make it feel original, not copied
6. Include 1-2 relevant emojis naturally

Return ONLY the new post text, nothing else.`;

	try {
		return await generateContent(prompt);
	} catch {
		return "";
	}
};

export interface AdaptedPost {
	content: string;
	originalContent: string;
	adaptationType: "inspired" | "reframed" | "expanded" | "contrarian";
	hashtags: string[];
	suggestedMedia?: string | undefined;
	similarityScore: number; // 0-100, lower is more unique
	hooks: string[];
}

/**
 * Adapt/transform an existing post into a new unique version
 * Used for the "Adapt Idea" button in Live Feed
 */
export const adaptPostIdea = async (
	originalContent: string,
	adaptationType:
		| "inspired"
		| "reframed"
		| "expanded"
		| "contrarian" = "inspired",
	userNiche?: string,
	userStyle?: "casual" | "professional" | "witty" | "inspirational" | "edgy",
): Promise<AdaptedPost | null> => {
	const adaptationInstructions: Record<string, string> = {
		inspired:
			"Create a completely new post inspired by the same topic/theme, but with your own unique angle and voice. Do NOT copy any phrases.",
		reframed:
			"Take the core insight and present it from a completely different perspective or for a different audience.",
		expanded:
			"Build on the idea with additional depth, examples, or a personal story. Make it richer and more valuable.",
		contrarian:
			"Challenge or flip the original take. Present the opposite viewpoint or an unexpected counter-argument.",
	};

	const styleGuide = userStyle
		? {
				casual:
					"Use conversational, friendly language. Short sentences. Relatable.",
				professional:
					"Polished but not stiff. Clear value. Authoritative but approachable.",
				witty:
					"Add clever wordplay, unexpected twists, or humor. Be memorable.",
				inspirational:
					"Uplifting, motivating. Paint a vision. Use powerful imagery.",
				edgy: "Bold, provocative, challenges norms. Attention-grabbing but not offensive.",
			}[userStyle]
		: "";

	const prompt = `You are a creative content strategist. Transform this post into something completely new and original.

ORIGINAL POST:
"${originalContent}"

ADAPTATION TYPE: ${adaptationInstructions[adaptationType]}

${userNiche ? `USER'S NICHE: ${userNiche}` : ""}
${styleGuide ? `WRITING STYLE: ${styleGuide}` : ""}

CRITICAL REQUIREMENTS:
1. The output must be COMPLETELY ORIGINAL - no copied phrases or structure
2. Must feel like a different person wrote it
3. Keep under 500 characters for Threads
4. Start with a strong hook that stops the scroll
5. Include natural emoji usage (1-3 max)
6. Must add genuine value, not just reword

Return ONLY a JSON object:
{
  "content": "Your completely original post here",
  "hooks": ["Alternative opening hook 1", "Alternative opening hook 2"],
  "hashtags": ["relevant", "niche", "tags"],
  "suggestedMedia": "Brief description if an image/carousel would enhance this, or null",
  "uniquenessRating": 8
}`;

	try {
		const response = await generateContent(prompt);

		let jsonStr = response;
		if (response.includes("```json")) {
			jsonStr = response.split("```json")[1]!.split("```")[0]!.trim();
		} else if (response.includes("```")) {
			jsonStr = response.split("```")[1]!.split("```")[0]!.trim();
		}

		const adapted = JSON.parse(jsonStr);

		// Calculate actual similarity score
		const similarityScore = calculateSimilarity(
			originalContent,
			adapted.content,
		);

		// If too similar, warn or regenerate
		if (similarityScore > 60) {
			logger.warn("[adaptPostIdea] High similarity detected:", similarityScore);
		}

		return {
			content: adapted.content,
			originalContent,
			adaptationType,
			hashtags: adapted.hashtags || [],
			suggestedMedia: adapted.suggestedMedia || undefined,
			similarityScore,
			hooks: adapted.hooks || [],
		};
	} catch (error) {
		logger.error("Adapt post idea error:", error);
		return null;
	}
};

/**
 * Quick quote formatter - wraps content for quote posting
 */
export const formatQuotePost = (
	originalContent: string,
	originalHandle: string,
	userComment?: string,
): string => {
	const truncatedOriginal =
		originalContent.length > 200
			? `${originalContent.slice(0, 197)}...`
			: originalContent;

	const quote = userComment
		? `${userComment}\n\n"${truncatedOriginal}"\n— @${originalHandle}`
		: `"${truncatedOriginal}"\n— @${originalHandle}`;

	return quote.slice(0, 500); // Ensure within Threads limit
};

// ===== GROWTH DIAGNOSIS AI FUNCTIONS =====

export const matchTopPostStyle = async (
	currentContent: string,
	topPostContent: string,
): Promise<string> => {
	const structure = analyzeTopPostStructure(topPostContent);

	const prompt = `You are a social media content optimizer. Transform the following post to match the EXACT style and structure of a top-performing post.

TOP POST ANALYSIS:
- Hook length: ${structure.hookLength} characters
- Total length: ${structure.totalLength} characters
- Emoji count: ${structure.emojiCount} (placed at: ${structure.emojiPositions.join(", ")})
- Sentence count: ${structure.sentenceCount}
- Average sentence length: ${structure.avgSentenceLength} chars
- Has question: ${structure.hasQuestion}
- CTA type: ${structure.ctaType}
- Line breaks: ${structure.lineBreaks}
- Tone: ${structure.tone}
- Structure: ${structure.structure}

TOP POST (for reference):
"""
${topPostContent}
"""

CONTENT TO TRANSFORM:
"""
${currentContent}
"""

RULES:
1. Keep the CORE MESSAGE of the original content
2. Match the hook style (length, punch, emoji placement)
3. Match the sentence structure and rhythm
4. Match the emoji usage pattern (count and positions)
5. Match the CTA style if present
6. Match the tone (${structure.tone})
7. Keep it under 500 characters
8. Do NOT copy the top post - just match its STYLE

Return ONLY the transformed content, nothing else.`;

	try {
		const response = await generateContent(prompt);
		return response.trim();
	} catch (error) {
		logger.error("[aiService] matchTopPostStyle error:", error);
		throw error;
	}
};

export const getTopPostForStyleMatch = async (): Promise<{
	content: string;
	engagement: number;
} | null> => {
	try {
		const publishedPosts = (await dataService.getPublishedPostsForAI({
			limit: 500,
		})).filter(
			(p) =>
				p.content &&
				p.content.length > 5,
		);

		if (publishedPosts.length === 0) {
			return null;
		}

		// Sort by engagement (likes + replies + shares)
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

		const topPost = sorted[0];
		return {
			content: topPost!.content,
			engagement:
				(topPost!.likes || 0) +
				(topPost!.replies || 0) +
				(topPost!.performance?.shares || 0),
		};
	} catch (error) {
		logger.error("[aiService] getTopPostForStyleMatch error:", error);
		return null;
	}
};

// ===== CONTENT REPURPOSING =====
