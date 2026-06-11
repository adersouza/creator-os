// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import type { ExtractedStyle } from "../../types/voice.js";
import { logger } from "@/utils/logger";
import type { AIContext } from "./contextEngine.js";
import { contextToSystemPrompt } from "./contextEngine.js";
import { generateContent } from "./core.js";
import type { VoiceProfile } from "./ideas.js";
import { buildVoiceContext, loadVoiceProfile } from "./voiceHelpers.js";

export type InspirationAdaptationStyle =
	| "casual"
	| "professional"
	| "witty"
	| "inspirational"
	| "edgy";

// Fresh angle varieties for adaptation
export type InspirationAdaptationAngle =
	| "direct" // Keep the core message, just restyle
	| "counter" // Take opposite/contrarian stance
	| "story" // Personal story/anecdote spin
	| "list" // Expand into actionable list/thread
	| "meme" // Meme-ify with humor/internet culture
	| "question"; // Reframe as engaging question

export const ADAPTATION_ANGLES: Record<
	InspirationAdaptationAngle,
	{ label: string; description: string; prompt: string }
> = {
	direct: {
		label: "Direct Adaptation",
		description: "Keep the core message, restyle in your voice",
		prompt: "Keep the winning concept and restyle it in your voice",
	},
	counter: {
		label: "Counter-Argument",
		description: "Take the opposite or contrarian stance",
		prompt:
			"Take the OPPOSITE stance or contrarian angle. Challenge the original premise while keeping it thought-provoking",
	},
	story: {
		label: "Personal Story",
		description: "Spin it into a personal anecdote",
		prompt:
			"Transform this into a personal story or anecdote. Start with 'I used to...' or 'Last week I...' or similar personal opening",
	},
	list: {
		label: "List Expansion",
		description: "Expand into an actionable list",
		prompt:
			"Expand this into a mini-list or actionable steps. Use numbers or bullet-style formatting (1. 2. 3. or • format)",
	},
	meme: {
		label: "Meme-ify",
		description: "Add humor and internet culture",
		prompt:
			"Make this funny/memey with internet culture vibes. Add humor, relatability, or slight absurdity. Think Twitter/Threads energy",
	},
	question: {
		label: "Question Hook",
		description: "Reframe as an engaging question",
		prompt:
			"Reframe this as an engaging question that sparks discussion. Start with a provocative 'What if...', 'Why do...', 'Have you ever...' etc.",
	},
};

export interface InspirationIdeaResult {
	content: string;
	insight: string;
	tags: string[];
	viralScore: number;
	angle?: InspirationAdaptationAngle | undefined; // Track which angle was used
	formula?: string | null | undefined; // The viral formula extracted (e.g. "Contrarian + curiosity + one-liner")
}

/**
 * Generate AI-adapted inspiration ideas from a competitor's post
 * Used by the Inspiration Engine to create ready-to-post content
 */
export const generateInspirationIdea = async (
	originalContent: string,
	competitorUsername: string,
	style: InspirationAdaptationStyle = "casual",
	extractedStyle?: ExtractedStyle | null,
	angle: InspirationAdaptationAngle = "direct",
	voiceProfile?: VoiceProfile,
	aiContext?: AIContext,
): Promise<InspirationIdeaResult | null> => {
	// Use unified AI context if provided, otherwise fall back to voice profile
	let voiceContext = "";
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		const vp =
			voiceProfile ?? (extractedStyle ? null : await loadVoiceProfile());
		voiceContext = vp ? buildVoiceContext(vp) : "";
	}
	const styleDescriptions: Record<InspirationAdaptationStyle, string> = {
		casual: "casual, conversational, and relatable like talking to a friend",
		professional:
			"professional, authoritative, and polished with industry expertise",
		witty: "witty, clever, and playful with subtle humor and wordplay",
		inspirational:
			"inspirational, motivational, and uplifting with genuine emotion",
		edgy: "bold, provocative, and slightly controversial to spark debate",
	};

	// Get angle-specific prompt instruction
	const angleInstruction =
		ADAPTATION_ANGLES[angle]?.prompt || ADAPTATION_ANGLES.direct.prompt;

	// Build Style DNA context if available (prioritized voice matching)
	const styleDNAContext = extractedStyle
		? `
MATCH THIS CREATOR'S EXACT VOICE (Style DNA):
🎯 Hook patterns: ${extractedStyle.hooks?.patterns?.slice(0, 3).join(" | ") || "N/A"}
🗣️ Signature phrases: ${extractedStyle.vocabulary?.signature_words?.slice(0, 5).join(", ") || "N/A"}
😊 Emoji style: ${extractedStyle.emoji_usage?.frequency || "moderate"} usage, ${extractedStyle.emoji_usage?.placement || "end"} placement${extractedStyle.emoji_usage?.favorites?.length ? `, prefer: ${extractedStyle.emoji_usage.favorites.slice(0, 3).join(" ")}` : ""}
📏 Length: ${extractedStyle.length?.typical_chars || "100-200"} chars (${extractedStyle.length?.preference || "medium"})
🎭 Vibe: ${extractedStyle.tone?.vibe || "conversational"} (${extractedStyle.tone?.energy || "moderate"} energy)
❗ Punctuation: ${extractedStyle.punctuation?.quirks?.slice(0, 2).join(", ") || "standard"}

Write as if YOU are this person. Match their DNA precisely - the "${style}" preset is secondary.

⛔ VIOLATIONS (avoid these):
- Generic motivational fluff
- Corporate jargon
- Phrases they never use
`
		: "";

	const prompt = `Analyze this viral post from @${competitorUsername} and create content for me:

VIRAL POST: "${originalContent}"

STEP 1 - ANALYZE WHY IT WORKED:
- What's the hook type? (question, bold claim, story opener, contrarian take, etc.)
- What emotion does it trigger? (curiosity, FOMO, validation, surprise, etc.)
- What's the format? (list, story, one-liner, thread starter, etc.)

STEP 2 - DECIDE APPROACH:
- If the topic is UNIVERSAL (productivity, mindset, relationships, money, etc.) → Adapt it directly in my voice
- If the topic is NICHE-SPECIFIC to them → Extract the winning formula and apply it to a broader topic
${styleDNAContext}
ADAPTATION ANGLE: ${angleInstruction}
${voiceContext}
STEP 3 - CREATE MY VERSION:
- Use a ${styleDescriptions[style]} tone${extractedStyle ? " (but prioritize Style DNA above)" : ""}
- Stay under 500 characters
- Keep the same hook structure that made the original work
- Include 1-2 relevant emojis naturally

Return ONLY a JSON object (no markdown):
{
  "content": "Your adapted post here",
  "insight": "Why this works: [the psychological trigger/hook type that made the original viral]",
  "tags": ["tag1", "tag2"],
  "viralScore": 75,
  "formula": "hook type + emotion + format (e.g. 'Contrarian claim + curiosity + one-liner')"
}`;

	try {
		const response = await generateContent(prompt);

		// Parse JSON from response
		let jsonStr = response;
		if (response.includes("```json")) {
			jsonStr = response.split("```json")[1]!.split("```")[0]!.trim();
		} else if (response.includes("```")) {
			jsonStr = response.split("```")[1]!.split("```")[0]!.trim();
		}

		const result = JSON.parse(jsonStr);

		// Validate and normalize
		return {
			content: (result.content || "").substring(0, 500),
			insight: result.insight || "Strong hook with clear value proposition",
			tags: Array.isArray(result.tags)
				? result.tags.slice(0, 5).map((t: string) => t.toLowerCase())
				: [],
			viralScore: Math.min(
				100,
				Math.max(0, parseInt(result.viralScore, 10) || 50),
			),
			angle, // Track which angle was used
			formula: result.formula || null, // The viral formula extracted
		};
	} catch (error) {
		logger.error("[generateInspirationIdea] Parse error:", error);
		return null;
	}
};

/**
 * Generate multiple inspiration ideas from a single competitor post
 * Used for "Generate More" feature - automatically cycles through different angles
 */
export const generateInspirationVariants = async (
	originalContent: string,
	competitorUsername: string,
	count: number = 6,
	style: InspirationAdaptationStyle = "casual",
	extractedStyle?: ExtractedStyle | null,
	aiContext?: AIContext,
): Promise<InspirationIdeaResult[]> => {
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

	const styleDescriptions: Record<InspirationAdaptationStyle, string> = {
		casual: "casual, conversational, and relatable",
		professional: "professional, authoritative, and polished",
		witty: "witty, clever, and playful with humor",
		inspirational: "inspirational, motivational, and uplifting",
		edgy: "bold, provocative, and slightly controversial",
	};

	// Get all angles and build angle instructions
	const angleKeys = Object.keys(
		ADAPTATION_ANGLES,
	) as InspirationAdaptationAngle[];
	const angleInstructions = angleKeys
		.slice(0, count)
		.map(
			(key, i) =>
				`${i + 1}. ${ADAPTATION_ANGLES[key].label}: ${ADAPTATION_ANGLES[key].prompt}`,
		)
		.join("\n");

	// Build Style DNA context if available (prioritized voice matching)
	const styleDNAContext = extractedStyle
		? `
MATCH THIS CREATOR'S EXACT VOICE (Style DNA):
🎯 Hook patterns: ${extractedStyle.hooks?.patterns?.slice(0, 3).join(" | ") || "N/A"}
🗣️ Signature phrases: ${extractedStyle.vocabulary?.signature_words?.slice(0, 5).join(", ") || "N/A"}
😊 Emoji style: ${extractedStyle.emoji_usage?.frequency || "moderate"} usage, ${extractedStyle.emoji_usage?.placement || "end"} placement${extractedStyle.emoji_usage?.favorites?.length ? `, prefer: ${extractedStyle.emoji_usage.favorites.slice(0, 3).join(" ")}` : ""}
📏 Length: ${extractedStyle.length?.typical_chars || "100-200"} chars (${extractedStyle.length?.preference || "medium"})
🎭 Vibe: ${extractedStyle.tone?.vibe || "conversational"} (${extractedStyle.tone?.energy || "moderate"} energy)

Write ALL variations as if YOU are this person. The "${style}" preset is secondary to matching their DNA.
`
		: "";

	const aiContextPreamble = aiContext
		? `${contextToSystemPrompt(aiContext)}\n\n`
		: "";

	const prompt = `${aiContextPreamble}Analyze this viral post and create ${Math.min(count, angleKeys.length)} unique variations:

VIRAL POST from @${competitorUsername}: "${originalContent}"

STEP 1 - ANALYZE WHY IT WORKED:
- Hook type: (question, bold claim, story opener, contrarian take, etc.)
- Emotion triggered: (curiosity, FOMO, validation, surprise, etc.)
- Format: (list, story, one-liner, thread starter, etc.)

STEP 2 - FOR EACH VARIATION:
- If topic is UNIVERSAL → adapt directly in my voice
- If topic is NICHE-SPECIFIC → use the same winning formula on a broader topic
${styleDNAContext}
ADAPTATION ANGLES (use one per variation):
${angleInstructions}

STEP 3 - CREATE ${Math.min(count, angleKeys.length)} VARIATIONS:
- Use a ${styleDescriptions[style]} tone${extractedStyle ? " (but prioritize Style DNA above)" : ""}
- Stay under 500 characters each
- Keep the same hook structure that made the original work
- Include 1-2 relevant emojis naturally
${feedbackContext}
Return ONLY a JSON array (no markdown):
[
  {
    "content": "Variation 1 here",
    "insight": "Why this works: [the psychological trigger]",
    "tags": ["tag1", "tag2"],
    "viralScore": 75,
    "angle": "direct",
    "formula": "hook type + emotion + format"
  },
  ...
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

		const results = JSON.parse(jsonStr);

		if (!Array.isArray(results)) {
			return [];
		}

		// Validate and normalize each result, assigning angles based on order if not provided
		return results.slice(0, count).map((result, index) => ({
			content: (result.content || "").substring(0, 500),
			insight: result.insight || "Strong hook with clear value",
			tags: Array.isArray(result.tags)
				? result.tags.slice(0, 5).map((t: string) => t.toLowerCase())
				: [],
			viralScore: Math.min(
				100,
				Math.max(0, parseInt(result.viralScore, 10) || 50),
			),
			angle:
				(result.angle as InspirationAdaptationAngle) ||
				angleKeys[index] ||
				"direct",
			formula: result.formula || null,
		}));
	} catch (error) {
		logger.error("[generateInspirationVariants] Parse error:", error);
		return [];
	}
};

/**
 * Calculate viral score for adapted content based on content analysis
 * Standalone function for recalculating scores without AI
 */
export const calculateInspirationViralScore = (
	content: string,
	hasMedia: boolean = false,
): number => {
	let score = 30; // Base score

	// Length optimization (100-280 chars is sweet spot for Threads)
	const length = content.length;
	if (length >= 100 && length <= 280) {
		score += 15;
	} else if (length >= 50 && length <= 400) {
		score += 8;
	}

	// Media presence bonus
	if (hasMedia) {
		score += 12;
	}

	// Hook detection (first line analysis)
	const firstLine = content.split("\n")[0] || content.substring(0, 60);
	const hookWords = [
		"unpopular opinion",
		"hot take",
		"controversial",
		"here's why",
		"the truth",
		"nobody talks about",
		"secret",
		"hack",
		"thread",
		"pov",
		"stop",
		"warning",
		"reminder",
	];
	if (hookWords.some((word) => firstLine.toLowerCase().includes(word))) {
		score += 18;
	}

	// Question presence (drives replies)
	if (content.includes("?")) {
		score += 10;
	}

	// Emoji presence (engagement boost)
	const emojiRegex =
		/[\u{1F300}-\u{1F9FF}]|[\u{2600}-\u{26FF}]|[\u{2700}-\u{27BF}]/u;
	if (emojiRegex.test(content)) {
		score += 5;
	}

	// Line breaks (readability)
	if (content.includes("\n")) {
		score += 5;
	}

	// Strong opening (personal pronouns, direct address)
	if (/^(I |You |We |My |Your |This )/i.test(firstLine)) {
		score += 5;
	}

	// Controversial/debate-sparking patterns
	if (
		/disagree|wrong|unpopular|controversial|hot take|actually|truth is/i.test(
			content,
		)
	) {
		score += 10;
	}

	return Math.min(100, Math.max(0, score));
};
