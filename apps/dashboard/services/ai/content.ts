// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { logger } from "@/utils/logger";
import type { AIContext } from "./contextEngine.js";
import { contextToSystemPrompt } from "./contextEngine.js";
import { generateContent, loadUserAIPrefs, STYLE_MAP } from "./core.js";
import type { VoiceProfile } from "./ideas.js";
import { buildVoiceContext, loadVoiceProfile } from "./voiceHelpers.js";

// Whitelist allowed tone values
const ALLOWED_TONES = [
	"professional",
	"casual",
	"witty",
	"inspirational",
	"educational",
	"storytelling",
	"controversial",
	"minimalist",
	"flirty",
	"motivational",
	"humorous",
	"luxury",
	"meme_lord",
];

/**
 * Sanitize a tone value to prevent prompt injection.
 * Returns a whitelisted tone or 'professional' as a safe default.
 */
function sanitizeTone(tone: string): string {
	const normalized = tone.toLowerCase().trim();
	if (ALLOWED_TONES.includes(normalized)) return normalized;
	return "professional"; // safe default
}

/**
 * Sanitize user input that will be interpolated into AI prompts.
 * Strips anything that looks like instruction injection.
 */
function sanitizePromptInput(input: string): string {
	if (!input) return "";
	// Remove patterns that could be used for prompt injection
	return input
		.replace(
			/\b(ignore|disregard|forget)\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?|context)/gi,
			"",
		)
		.replace(/\b(system|assistant|user)\s*:/gi, "")
		.replace(/\b(you are now|act as|pretend to be|new instructions?)\b/gi, "")
		.replace(/<\/?[^>]+(>|$)/g, "") // strip HTML tags
		.trim();
}

export const generatePostContent = async (
	topic?: string,
	tone?: string,
	voiceProfile?: VoiceProfile,
	aiContext?: AIContext,
	accountId?: string,
	platform?: string,
): Promise<string> => {
	// Load user preferences for excluded topics
	const prefs = await loadUserAIPrefs();

	// Use unified AI context if provided, otherwise fall back to voice profile
	let voiceContext = "";
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		const vp = voiceProfile ?? (await loadVoiceProfile());
		voiceContext = vp ? buildVoiceContext(vp) : "";
	}

	// Load feedback context for personalization
	let feedbackContext = "";
	try {
		const { buildFeedbackContext } = await import(
			"../../utils/buildFeedbackContext.js"
		);
		feedbackContext = await buildFeedbackContext("caption");
	} catch {
		// Feedback loading is non-critical
	}

	// Sanitize and use provided tone (from Voice Profile) or fallback to casual
	const safeTone = tone ? sanitizeTone(tone) : "casual";
	const styleDescription = STYLE_MAP[safeTone] || STYLE_MAP.casual;

	// Build avoid topics instruction
	const avoidInstruction = prefs?.excludeTopics?.length
		? `\nAVOID these topics completely: ${prefs.excludeTopics.join(", ")}`
		: "";

	const sanitizedTopic = topic ? sanitizePromptInput(topic) : "";
	const actualTopic =
		sanitizedTopic || "something interesting and engaging for social media";

	const prompt = `Write a viral, engaging Threads post${sanitizedTopic ? ` about "${actualTopic}"` : ""}.
${voiceContext}
STYLE: ${styleDescription}
${safeTone ? `TONE: ${safeTone}` : ""}${avoidInstruction}${feedbackContext}

Make it sound like a human power-user.
Include 1-2 relevant emojis but don't overdo it.
Keep it under 500 characters.
Format it with clean spacing.
Return ONLY the post text, nothing else.`;

	return await generateContent(prompt, undefined, { accountId, platform });
};

export const improvePostContent = async (
	currentContent: string,
	tone?: string,
	voiceProfile?: VoiceProfile,
	aiContext?: AIContext,
	accountId?: string,
	platform?: string,
): Promise<string> => {
	// Load user preferences for excluded topics
	const prefs = await loadUserAIPrefs();

	// Use unified AI context if provided, otherwise fall back to voice profile
	let voiceContext = "";
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		const vp = voiceProfile ?? (await loadVoiceProfile());
		voiceContext = vp ? buildVoiceContext(vp) : "";
	}

	// Load feedback context for personalization
	let feedbackContext = "";
	try {
		const { buildFeedbackContext } = await import(
			"../../utils/buildFeedbackContext.js"
		);
		feedbackContext = await buildFeedbackContext("caption");
	} catch {
		/* non-critical */
	}

	// Sanitize and use provided tone (from Voice Profile) or fallback to casual
	const safeTone = tone ? sanitizeTone(tone) : "casual";
	const styleDescription = STYLE_MAP[safeTone] || STYLE_MAP.casual;

	const avoidInstruction = prefs?.excludeTopics?.length
		? `\nAVOID these topics completely: ${prefs.excludeTopics.join(", ")}`
		: "";

	const prompt = `Rewrite the following social media post to be more punchy, engaging, and viral-ready for the Threads app. Keep the core message but maximize impact.
${voiceContext}
STYLE TO USE: ${styleDescription}${avoidInstruction}${feedbackContext}

Current Post: "${currentContent}"

Return ONLY the improved post text, nothing else.`;

	return await generateContent(prompt, undefined, { accountId, platform });
};

export const addStrongHook = async (
	currentContent: string,
	voiceProfile?: VoiceProfile,
): Promise<string> => {
	// Load voice profile if not provided
	const vp = voiceProfile ?? (await loadVoiceProfile());
	const voiceContext = vp ? buildVoiceContext(vp) : "";

	// Load feedback context for personalization
	let feedbackContext = "";
	try {
		const { buildFeedbackContext } = await import(
			"../../utils/buildFeedbackContext.js"
		);
		feedbackContext = await buildFeedbackContext("caption");
	} catch {
		/* non-critical */
	}

	const prompt = `Add a powerful, scroll-stopping hook to the beginning of this Threads post. The hook should create curiosity, controversy, or immediate value. Keep the rest of the content mostly the same but make it flow naturally from the hook.
${voiceContext}${feedbackContext}

Current Post: "${currentContent}"

Return ONLY the improved post text, nothing else.`;

	try {
		return await generateContent(prompt);
	} catch {
		return currentContent;
	}
};

export const makeShorter = async (
	currentContent: string,
	voiceProfile?: VoiceProfile,
): Promise<string> => {
	const vp = voiceProfile ?? (await loadVoiceProfile());
	const voiceContext = vp ? buildVoiceContext(vp) : "";

	const prompt = `Make this Threads post shorter and more concise while keeping the core message. Remove fluff, tighten sentences, and maximize impact per word. Aim for 30-50% shorter.
${voiceContext}
Current Post: "${currentContent}"

Return ONLY the shortened post text, nothing else.`;

	try {
		return await generateContent(prompt);
	} catch {
		return currentContent;
	}
};

export const makePunchier = async (
	currentContent: string,
	voiceProfile?: VoiceProfile,
): Promise<string> => {
	const vp = voiceProfile ?? (await loadVoiceProfile());
	const voiceContext = vp ? buildVoiceContext(vp) : "";

	const prompt = `Make this Threads post punchier and more impactful. Use stronger verbs, shorter sentences, and more direct language. Add rhythm and power to the writing while keeping the same message.
${voiceContext}
Current Post: "${currentContent}"

Return ONLY the punchier post text, nothing else.`;

	try {
		return await generateContent(prompt);
	} catch {
		return currentContent;
	}
};

export const addEmojiFormatting = async (
	currentContent: string,
	voiceProfile?: VoiceProfile,
): Promise<string> => {
	const vp = voiceProfile ?? (await loadVoiceProfile());
	const voiceContext = vp ? buildVoiceContext(vp) : "";

	const prompt = `Add strategic emojis and better formatting to this Threads post. Use 2-4 relevant emojis that enhance the message. Add line breaks for better readability. Don't overdo it - keep it natural and professional.
${voiceContext}
Current Post: "${currentContent}"

Return ONLY the formatted post text with emojis, nothing else.`;

	try {
		return await generateContent(prompt);
	} catch {
		return currentContent;
	}
};

export const optimizeForVirality = async (
	currentContent: string,
	voiceProfile?: VoiceProfile,
	aiContext?: AIContext,
): Promise<string> => {
	let voiceContext = "";
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		const vp = voiceProfile ?? (await loadVoiceProfile());
		voiceContext = vp ? buildVoiceContext(vp) : "";
	}

	const prompt = `Optimize this Threads post for maximum virality. Apply these viral techniques:
1. Add a curiosity-inducing hook
2. Use pattern interrupts
3. End with a question or CTA that encourages replies
4. Make it shareable and relatable
5. Keep it under 500 characters
${voiceContext}
Current Post: "${currentContent}"

Return ONLY the viral-optimized post text, nothing else.`;

	try {
		return await generateContent(prompt);
	} catch {
		return currentContent;
	}
};

// Re-export types for backwards compatibility

export const generateContentVariations = async (
	originalContent: string,
	competitorUsername: string,
	numberOfVariations: number = 3,
	aiContext?: AIContext,
): Promise<string[]> => {
	const safeUsername = sanitizePromptInput(competitorUsername);
	const safeContent = sanitizePromptInput(originalContent);
	const contextPreamble = aiContext
		? `${contextToSystemPrompt(aiContext)}\n\n`
		: "";
	const prompt = `${contextPreamble}You are an expert social media content strategist. A competitor (@${safeUsername}) posted this successful content:

"${safeContent}"

Generate ${numberOfVariations} unique variations of this content that:
1. Keep the core message/hook but express it differently
2. Add your own unique perspective or twist
3. Make it sound authentic and human (not AI-generated)
4. Stay under 500 characters each
5. Are suitable for the Threads platform
6. Don't copy the structure word-for-word - reimagine the concept

Return ONLY a JSON array of ${numberOfVariations} variations, nothing else. Example format:
["First variation text here", "Second variation text here", "Third variation text here"]`;

	try {
		const response = await generateContent(prompt);

		// Parse JSON from response
		let jsonStr = response;
		if (response.includes("```json")) {
			jsonStr = response.split("```json")[1]!.split("```")[0]!.trim();
		} else if (response.includes("```")) {
			jsonStr = response.split("```")[1]!.split("```")[0]!.trim();
		}

		const variations = JSON.parse(jsonStr) as string[];
		return Array.isArray(variations) ? variations : [];
	} catch (error) {
		logger.error("Content variation parsing error:", error);
		return [];
	}
};

/**
 * Adapt a single competitor post into your own unique version
 */

export const rephraseVariations = async (
	content: string,
	count: number = 3,
	voiceProfile?: VoiceProfile,
	aiContext?: AIContext,
): Promise<{ variation: string; tone: string; charCount: number }[]> => {
	let voiceContext = "";
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		const vp = voiceProfile ?? (await loadVoiceProfile());
		voiceContext = vp ? buildVoiceContext(vp) : "";
	}

	const prompt = `You are an expert social media copywriter. Rephrase this Threads post in ${count} completely different ways, each with a distinct tone:
${voiceContext}
Original Post: "${content}"

Requirements for each variation:
1. Keep the core message intact but completely rephrase the wording
2. Make each variation sound natural and human (not AI-generated)
3. Stay under 500 characters each
4. Each should have a distinctly different tone (e.g., casual, professional, witty, inspirational, edgy)
5. Don't just swap synonyms - reimagine how to express the same idea

Return ONLY a JSON array with exactly ${count} objects. Example format:
[
  {"variation": "The rephrased text here...", "tone": "casual"},
  {"variation": "Another version here...", "tone": "professional"},
  {"variation": "Third unique version...", "tone": "witty"}
]`;

	try {
		const response = await generateContent(prompt);

		// Parse JSON from response
		let jsonStr = response;
		if (response.includes("```json")) {
			jsonStr = response.split("```json")[1]!.split("```")[0]!.trim();
		} else if (response.includes("```")) {
			jsonStr = response.split("```")[1]!.split("```")[0]!.trim();
		}

		const variations = JSON.parse(jsonStr) as {
			variation: string;
			tone: string;
		}[];
		return Array.isArray(variations)
			? variations.map((v) => ({ ...v, charCount: v.variation.length }))
			: [];
	} catch (error) {
		logger.error("Rephrase variations parsing error:", error);
		return [];
	}
};

/**
 * Adapt a media post idea - describe the concept and suggest caption ideas
 * Used when the original post has an image/video
 */

export const generateBatchDrafts = async (
	sourcePosts: { content: string; username: string }[],
	count: number = 5,
	niche?: string,
	voiceProfile?: VoiceProfile,
	aiContext?: AIContext,
): Promise<{ draft: string; inspiration: string; charCount: number }[]> => {
	let voiceContext = "";
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		const vp = voiceProfile ?? (await loadVoiceProfile());
		voiceContext = vp ? buildVoiceContext(vp) : "";
	}
	const sourceList = sourcePosts
		.slice(0, 5) // Limit to 5 source posts to keep prompt manageable
		.map((p, i) => `${i + 1}. @${p.username}: "${p.content}"`)
		.join("\n");

	const prompt = `You are a viral content creator. Using these successful posts as inspiration, generate ${count} completely original drafts:
${voiceContext}
SOURCE INSPIRATION:
${sourceList}

${niche ? `Target Niche: ${niche}` : ""}

Requirements:
1. Each draft must be ORIGINAL - don't copy phrases or structure
2. Take the winning concepts/hooks but express them in YOUR unique voice
3. Mix and match ideas from different sources
4. Keep each under 500 characters
5. Make them sound human and authentic
6. Vary the tone across drafts (some casual, some punchy, some inspirational)
7. Include natural emoji usage (1-3 per post)

Return ONLY a JSON array with ${count} objects. Example format:
[
  {"draft": "Your unique post text here...", "inspiration": "Concept inspired by: hook pattern from @user"},
  {"draft": "Another original draft...", "inspiration": "Inspired by: storytelling format"}
]`;

	try {
		const response = await generateContent(prompt);

		// Parse JSON from response
		let jsonStr = response;
		if (response.includes("```json")) {
			jsonStr = response.split("```json")[1]!.split("```")[0]!.trim();
		} else if (response.includes("```")) {
			jsonStr = response.split("```")[1]!.split("```")[0]!.trim();
		}

		const drafts = JSON.parse(jsonStr) as {
			draft: string;
			inspiration: string;
		}[];
		return Array.isArray(drafts)
			? drafts.map((d) => ({ ...d, charCount: d.draft.length }))
			: [];
	} catch (error) {
		logger.error("Batch drafts parsing error:", error);
		return [];
	}
};

/**
 * Calculate similarity score between two texts
 * Used to warn users if their adapted content is too similar to the original
 */
