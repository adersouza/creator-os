import { randomUUID } from "@/src/lib/uuid.js";
import type {
	CarouselSlide,
	RepurposedPart,
	ThreadPart,
} from "../../types/aiContent.js";
import { logger } from "@/utils/logger";
import type { AIContext } from "./contextEngine.js";
import { contextToSystemPrompt } from "./contextEngine.js";
import { generateContent, parseAIJson } from "./core.js";
import type { VoiceProfile } from "./ideas.js";
import { buildVoiceContext, loadVoiceProfile } from "./voiceHelpers.js";

export type RepurposeFormat =
	| "threads"
	| "instagram_caption"
	| "carousel"
	| "story"
	| "reel_script";

/**
 * Platform character limits for repurposed content.
 * Threads: 500 chars (Meta API limit)
 * Instagram: 2200 chars (Meta API limit)
 */
const PLATFORM_CHAR_LIMITS: Record<string, number> = {
	threads: 500,
	instagram_caption: 2200,
	carousel: 2200,
	story: 2200,
	reel_script: 2200,
};

/**
 * Enforce platform character limits on AI-generated content.
 * Truncates at the last word boundary before the limit and appends "..."
 */
function enforceCharLimit(content: string, format: RepurposeFormat): string {
	const limit = PLATFORM_CHAR_LIMITS[format];
	if (!limit || content.length <= limit) return content;

	// Truncate at word boundary, leaving room for "..."
	const truncated = content.slice(0, limit - 3);
	const lastSpace = truncated.lastIndexOf(" ");
	const cleanTruncated =
		lastSpace > 0 ? truncated.slice(0, lastSpace) : truncated;
	return `${cleanTruncated}...`;
}

/**
 * Repurpose content to a different format
 */
export const repurposeContent = async (
	originalContent: string,
	targetFormat: RepurposeFormat,
	voiceProfile?: VoiceProfile,
	aiContext?: AIContext,
): Promise<{ content: string; format: string }> => {
	let voiceContext = "";
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		const vp = voiceProfile ?? (await loadVoiceProfile());
		voiceContext = vp ? buildVoiceContext(vp) : "";
	}
	const formatInstructions: Record<RepurposeFormat, string> = {
		threads:
			"Rewrite with a completely different hook/opening. Keep the same core message but make it feel fresh. Under 500 characters.",
		instagram_caption:
			"Adapt for Instagram feed. Add relevant hashtags (5-10). Use line breaks for readability. Include a CTA. Can be longer form.",
		carousel:
			'Break the content into 5-8 carousel slides. Format as JSON array: [{"slide": 1, "text": "..."}, ...]. Slide 1 = hook, last slide = CTA.',
		story:
			'Break into 3-5 Instagram story frames. Short punchy text per frame. Format as JSON array: [{"frame": 1, "text": "...", "sticker_suggestion": "..."}, ...].',
		reel_script:
			"Convert to a voiceover script for a 30-60 second reel. Include [VISUAL CUE] markers. Format: line-by-line script with timing hints.",
	};

	const prompt = `Repurpose this content for a different format.
${voiceContext}
ORIGINAL CONTENT:
"${originalContent}"

TARGET FORMAT: ${targetFormat}
${formatInstructions[targetFormat]}

Return ONLY the adapted content. No explanations.`;

	try {
		const response = await generateContent(prompt);
		const trimmed = response.trim();
		return {
			content: enforceCharLimit(trimmed, targetFormat),
			format: targetFormat,
		};
	} catch (error) {
		logger.error("[aiService] repurposeContent failed:", error);
		throw error;
	}
};

// ===== STYLE DNA EXTRACTION =====

/**
 * Extract writing DNA from a user's top performing posts.
 * This creates a comprehensive style profile that can be injected into
 * content generation prompts for better voice matching.
 *
 * Run this once when user enables "advanced style matching" or periodically
 * to update the profile as their style evolves.
 *
 * @param posts - Array of post content strings (ideally top 15-20 posts)
 * @returns ExtractedStyle object or null if extraction fails
 */

export const repurposeToCarousel = async (
	content: string,
	voiceProfile?: VoiceProfile,
): Promise<RepurposedPart[]> => {
	const vp = voiceProfile ?? (await loadVoiceProfile());
	const voiceContext = vp ? buildVoiceContext(vp) : "";
	const prompt = `Convert this social media post into 4-6 carousel slides.${voiceContext} Each slide needs a short punchy title (under 8 words) and body text (under 100 characters). The first slide should be a hook, the last a CTA.

Post: "${content}"

Return ONLY a JSON array like:
[{"title": "Slide Title", "content": "Slide body text", "order": 1}]`;

	try {
		const response = await generateContent(prompt);
		// Error will throw and be caught by outer try/catch
		const slides =
			parseAIJson<{ title: string; content: string; order: number }[]>(
				response,
			);
		return slides.map((s) => ({ ...s, type: "carousel" as const }));
	} catch (_err) {
		return [];
	}
};

/**
 * Repurpose a post into a story card sequence
 */
export const repurposeToStorySequence = async (
	content: string,
	_voiceProfile?: VoiceProfile,
): Promise<RepurposedPart[]> => {
	const prompt = `Convert this post into a 3-5 part Instagram/Threads story sequence. Each story card should be a single short message (under 80 characters) that builds anticipation. Use a cliffhanger pattern.

Post: "${content}"

Return ONLY a JSON array like:
[{"content": "Story card text", "order": 1}]`;

	try {
		const response = await generateContent(prompt);
		// Error will throw and be caught by outer try/catch
		const cards = parseAIJson<{ content: string; order: number }[]>(response);
		return cards.map((c) => ({ ...c, type: "story" as const }));
	} catch (_err) {
		return [];
	}
};

/**
 * Repurpose a post into a reel script with scene descriptions
 */
export const repurposeToReelScript = async (
	content: string,
	_voiceProfile?: VoiceProfile,
): Promise<RepurposedPart[]> => {
	const prompt = `Convert this post into a short-form video/reel script (30-60 seconds). Break it into 3-5 scenes. Each scene needs spoken text and a visual/scene description.

Post: "${content}"

Return ONLY a JSON array like:
[{"content": "What to say on screen", "sceneDescription": "Visual: close-up of...", "order": 1}]`;

	try {
		const response = await generateContent(prompt);
		// Error will throw and be caught by outer try/catch
		const scenes =
			parseAIJson<
				{ content: string; sceneDescription: string; order: number }[]
			>(response);
		return scenes.map((s) => ({ ...s, type: "reel" as const }));
	} catch (_err) {
		return [];
	}
};

/**
 * Expand a short post into a multi-part thread
 */
export const expandToThread = async (
	content: string,
	_voiceProfile?: VoiceProfile,
): Promise<RepurposedPart[]> => {
	const prompt = `Expand this short post into a 4-6 part thread. The first part should be a compelling hook. Middle parts expand on the idea with details, examples, or insights. The last part should be a CTA. Each part must be under 500 characters.

Post: "${content}"

Return ONLY a JSON array like:
[{"content": "Thread part text", "order": 1}]`;

	try {
		const response = await generateContent(prompt);
		// Error will throw and be caught by outer try/catch
		const parts = parseAIJson<{ content: string; order: number }[]>(response);
		return parts.map((p) => ({
			...p,
			type: "thread" as const,
			content: enforceCharLimit(p.content, "threads"),
		}));
	} catch (_err) {
		return [];
	}
};

/**
 * Condense a long post into a single concise post
 */
export const condensePost = async (
	content: string,
	_voiceProfile?: VoiceProfile,
): Promise<RepurposedPart[]> => {
	const prompt = `Condense this long post into a single punchy post under 280 characters. Keep the core message, remove fluff, maximize impact.

Post: "${content}"

Return ONLY the condensed text, nothing else.`;

	try {
		const result = await generateContent(prompt);
		// Error will throw and be caught by outer try/catch
		return [{ type: "condensed", content: result.trim(), order: 1 }];
	} catch (_err) {
		return [];
	}
};

/**
 * Repurpose a Threads post into Instagram caption style
 */
export const repurposeToInstagramCaption = async (
	content: string,
	_voiceProfile?: VoiceProfile,
): Promise<RepurposedPart[]> => {
	const prompt = `Convert this Threads post into an Instagram caption style. Add:
1. A hook first line (with line break after)
2. Expanded storytelling body
3. A call-to-action
4. 3-5 relevant hashtags at the end
Keep it under 2200 characters. Make it feel native to Instagram.

Post: "${content}"

Return ONLY the Instagram caption text, nothing else.`;

	try {
		const result = await generateContent(prompt);
		// Error will throw and be caught by outer try/catch
		return [
			{
				type: "ig-caption",
				content: enforceCharLimit(result.trim(), "instagram_caption"),
				order: 1,
			},
		];
	} catch (_err) {
		return [];
	}
};

/**
 * Repurpose an Instagram caption into Threads-native style
 */
export const repurposeForThreads = async (
	content: string,
	_voiceProfile?: VoiceProfile,
): Promise<RepurposedPart[]> => {
	const prompt = `Convert this Instagram caption into a Threads-native post. Apply these rules:
1. Strip all hashtags
2. Make it conversational and opinion-driven
3. Keep it under 500 characters
4. Remove "link in bio" or CTA phrases
5. Add a question or hot take to spark replies

Caption: "${content}"

Return ONLY the Threads post text, nothing else.`;

	try {
		const result = await generateContent(prompt);
		// Error will throw and be caught by outer try/catch
		return [
			{
				type: "threads-native",
				content: enforceCharLimit(result.trim(), "threads"),
				order: 1,
			},
		];
	} catch (_err) {
		return [];
	}
};

/**
 * AI-powered hashtag suggestions with reach and competition estimates
 */

export const splitIntoThread = async (
	longContent: string,
	maxChars: number = 500,
): Promise<ThreadPart[]> => {
	const prompt = `Split this long text into a thread of multiple posts (each under ${maxChars} characters). Label each part as "hook" (first), "body" (middle parts), or "cta" (last). Make each part stand alone but flow as a thread. The hook should grab attention. The CTA should drive engagement.

Text: "${longContent}"

Return ONLY a JSON array like:
[{"content": "Part text", "type": "hook", "order": 1}]`;

	try {
		const response = await generateContent(prompt);
		// Error will throw and be caught by outer try/catch
		const parts =
			parseAIJson<
				{ content: string; type: "hook" | "body" | "cta"; order: number }[]
			>(response);
		return parts.map((p) => ({
			...p,
			id: randomUUID(),
			charCount: p.content.length,
		}));
	} catch (_err) {
		return [];
	}
};

/**
 * Generate a complete multi-part thread from a topic/idea
 */
export const generateThreadFromTopic = async (
	topic: string,
	partCount: number = 5,
	tone: string = "engaging",
	voiceProfile?: VoiceProfile,
): Promise<ThreadPart[]> => {
	const vp = voiceProfile ?? (await loadVoiceProfile());
	const threadVoiceContext = vp ? buildVoiceContext(vp) : "";
	let feedbackContext = "";
	try {
		const { buildFeedbackContext } = await import(
			"../../utils/buildFeedbackContext.js"
		);
		feedbackContext = await buildFeedbackContext("content_variation");
	} catch (_err) {}

	const prompt = `Generate a complete ${partCount}-part Threads thread about: "${topic}"
${threadVoiceContext}
Tone: ${tone}
Structure:
- Part 1 = "hook" — attention-grabbing opener that stops the scroll
- Parts 2 to ${partCount - 1} = "body" — valuable content, each builds on the previous part
- Part ${partCount} = "cta" — drives engagement (ask a question, invite discussion)

Rules:
- Each part MUST be under 500 characters
- Each part should work standalone but maintain narrative continuity
- Use short paragraphs and line breaks for readability
- No hashtags in parts (user can add later)
${feedbackContext ? `\nLearning context:\n${feedbackContext}` : ""}

Return ONLY a JSON array like:
[{"content": "Part text here", "type": "hook", "order": 1}]`;

	try {
		const response = await generateContent(prompt);
		// Error will throw and be caught by outer try/catch
		const parts =
			parseAIJson<
				{ content: string; type: "hook" | "body" | "cta"; order: number }[]
			>(response);
		return parts.map((p) => ({
			...p,
			id: randomUUID(),
			charCount: p.content.length,
		}));
	} catch (_err) {
		return [];
	}
};

/**
 * Split long content into carousel slides with title and body
 */
export const splitIntoCarousel = async (
	longContent: string,
	slideCount: number = 5,
): Promise<CarouselSlide[]> => {
	const prompt = `Split this content into exactly ${slideCount} carousel slides. Each slide needs a bold title (under 8 words) and body text (under 120 characters). First slide = hook, last slide = CTA.

Content: "${longContent}"

Return ONLY a JSON array like:
[{"title": "Slide Title", "body": "Slide body text", "order": 1}]`;

	try {
		const response = await generateContent(prompt);
		// Error will throw and be caught by outer try/catch
		const slides =
			parseAIJson<{ title: string; body: string; order: number }[]>(response);
		return slides.map((s) => ({
			...s,
			id: randomUUID(),
		}));
	} catch (_err) {
		return [];
	}
};

/**
 * Generate a weekly content plan with themed posts
 */
