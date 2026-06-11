// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import { logger } from "@/utils/logger";
import type { AIContext } from "./contextEngine.js";
import { contextToSystemPrompt } from "./contextEngine.js";
import { generateContent } from "./core.js";
import type { VoiceProfile } from "./ideas.js";
import { buildVoiceContext, loadVoiceProfile } from "./voiceHelpers.js";

export type ReplyStyle = "friendly" | "witty" | "promotional";
export type SentimentType =
	| "positive"
	| "neutral"
	| "negative"
	| "toxic"
	| "question";

export interface ReplySuggestion {
	text: string;
	style: ReplyStyle;
	confidence: number; // 0-100
}

function isReplyStyle(value: unknown): value is ReplyStyle {
	return value === "friendly" || value === "witty" || value === "promotional";
}

function parseReplySuggestions(parsed: unknown): ReplySuggestion[] | null {
	if (
		!parsed ||
		typeof parsed !== "object" ||
		!("suggestions" in parsed) ||
		!Array.isArray(parsed.suggestions)
	) {
		return null;
	}

	return parsed.suggestions.map((suggestion) => {
		const entry =
			suggestion && typeof suggestion === "object" ? suggestion : undefined;

		const text =
			entry && "text" in entry
				? String(entry.text || "").substring(0, 500)
				: "";
		const rawStyle = entry && "style" in entry ? entry.style : undefined;
		const rawConfidence =
			entry && "confidence" in entry ? entry.confidence : undefined;

		return {
			text,
			style: isReplyStyle(rawStyle) ? rawStyle : "friendly",
			confidence: Math.min(100, Math.max(0, Number(rawConfidence) || 75)),
		};
	});
}

/**
 * Generate AI-powered reply suggestions based on the incoming reply and original post
 * @param incomingReply - The reply text to respond to
 * @param originalPost - Your original post that was replied to
 * @param preferredStyle - Preferred reply style
 * @returns Array of 3 reply suggestions (one per style)
 */
export const generateReplySuggestions = async (
	incomingReply: string,
	originalPost: string,
	preferredStyle: ReplyStyle = "friendly",
	aiContext?: AIContext,
): Promise<ReplySuggestion[]> => {
	// Use unified AI context if provided, otherwise fall back to voice profile
	let voiceContext = "";
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		const voiceProfile = await loadVoiceProfile();
		voiceContext = voiceProfile ? buildVoiceContext(voiceProfile) : "";
	}

	const prompt = `You are helping craft replies on Threads that sound like a REAL person, not an AI assistant.
${voiceContext}
CONTEXT:
Your original post: "${originalPost.substring(0, 200)}${originalPost.length > 200 ? "..." : ""}"
Someone replied: "${incomingReply.substring(0, 300)}${incomingReply.length > 300 ? "..." : ""}"

Generate 3 reply suggestions with distinct vibes. Each reply should:
- Sound like the person described in the voice profile above (use their vocabulary, tone, emoji style)
- Be under 280 characters
- Match or mirror the energy of their reply
- Feel like a natural conversation, not a corporate response

Return ONLY valid JSON (no markdown, no code blocks):
{
  "suggestions": [
    {"text": "your friendly reply here", "style": "friendly", "confidence": 85},
    {"text": "your witty reply here", "style": "witty", "confidence": 80},
    {"text": "your promotional reply here", "style": "promotional", "confidence": 75}
  ]
}

Style guide:
- friendly: Warm, genuine, builds rapport — like talking to a friend
- witty: Clever, playful, unexpected — shows personality
- promotional: Adds value while engaging — no hard sell, just "hey I have more on this"

Preferred style is "${preferredStyle}" - make that one the strongest.`;

	try {
		const response = await generateContent(prompt);

		if (!response) {
			return getDefaultSuggestions(incomingReply);
		}

		// Parse JSON from response
		let jsonStr = response;
		if (response.includes("```json")) {
			jsonStr = response.split("```json")[1]!.split("```")[0]!.trim();
		} else if (response.includes("```")) {
			jsonStr = response.split("```")[1]!.split("```")[0]!.trim();
		}

		const suggestions = parseReplySuggestions(JSON.parse(jsonStr));
		if (suggestions) {
			return suggestions;
		}

		return getDefaultSuggestions(incomingReply);
	} catch (error) {
		logger.error("[aiService] Error parsing reply suggestions:", error);
		return getDefaultSuggestions(incomingReply);
	}
};

/**
 * Default suggestions when AI fails
 */
const getDefaultSuggestions = (incomingReply: string): ReplySuggestion[] => {
	const isQuestion = incomingReply.includes("?");
	const isPositive = /thank|love|great|awesome|amazing/i.test(incomingReply);

	if (isPositive) {
		return [
			{
				text: "Thank you so much! Really appreciate you taking the time to share that 🙏",
				style: "friendly",
				confidence: 70,
			},
			{ text: "You just made my day! 😄", style: "witty", confidence: 65 },
			{
				text: "Thanks! Glad it resonated - more coming soon!",
				style: "promotional",
				confidence: 60,
			},
		];
	}

	if (isQuestion) {
		return [
			{
				text: "Great question! Let me share my thoughts...",
				style: "friendly",
				confidence: 70,
			},
			{
				text: "Ooh good one! The short answer is...",
				style: "witty",
				confidence: 65,
			},
			{
				text: "Happy to dive deeper on this! Here's my take...",
				style: "promotional",
				confidence: 60,
			},
		];
	}

	return [
		{
			text: "Thanks for sharing your perspective! Really appreciate the engagement.",
			style: "friendly",
			confidence: 70,
		},
		{ text: "Love this take! 💯", style: "witty", confidence: 65 },
		{
			text: "Great point - this adds to the conversation!",
			style: "promotional",
			confidence: 60,
		},
	];
};

/**
 * Generate AI-powered reply suggestions for Instagram comments.
 * Similar to generateReplySuggestions but tailored for Instagram's
 * comment context (media post, caption, longer character limit).
 */
export const generateIGCommentSuggestions = async (
	comment: string,
	postCaption: string,
	preferredStyle: ReplyStyle = "friendly",
	aiContext?: AIContext,
): Promise<ReplySuggestion[]> => {
	// Use unified AI context if provided, otherwise fall back to voice profile
	let voiceContext = "";
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		const voiceProfile = await loadVoiceProfile();
		voiceContext = voiceProfile ? buildVoiceContext(voiceProfile) : "";
	}

	let feedbackContext = "";
	try {
		const { buildFeedbackContext } = await import(
			"../../utils/buildFeedbackContext.js"
		);
		feedbackContext = await buildFeedbackContext("reply_suggestion");
	} catch (_err) {}

	const prompt = `Craft Instagram comment replies that sound like a real person — warm, specific, and engagement-driving.
${voiceContext}
CONTEXT:
Your Instagram post caption: "${postCaption.substring(0, 300)}${postCaption.length > 300 ? "..." : ""}"
Someone commented: "${comment.substring(0, 300)}${comment.length > 300 ? "..." : ""}"

Generate 3 reply suggestions. Each should:
- Sound like the person in the voice profile (their vocabulary, emoji style, tone)
- Be under 300 characters
- Reference something SPECIFIC from their comment (don't be generic)
- Drive further engagement: ask a follow-up question, give a compliment, or share an insight
- Feel natural for Instagram
${feedbackContext ? `\nLearning context:\n${feedbackContext}` : ""}

Return ONLY valid JSON (no markdown, no code blocks):
{
  "suggestions": [
    {"text": "your friendly reply here", "style": "friendly", "confidence": 85},
    {"text": "your witty reply here", "style": "witty", "confidence": 80},
    {"text": "your promotional reply here", "style": "promotional", "confidence": 75}
  ]
}

Style guide:
- friendly: Warm, specific appreciation + follow-up question
- witty: Playful, personality-driven, makes them smile
- promotional: Adds value naturally — "I actually have a deep dive on this..."

Preferred style is "${preferredStyle}" - make that one the strongest.`;

	try {
		const response = await generateContent(prompt);

		if (!response) {
			return getDefaultSuggestions(comment);
		}

		let jsonStr = response;
		if (response.includes("```json")) {
			jsonStr = response.split("```json")[1]!.split("```")[0]!.trim();
		} else if (response.includes("```")) {
			jsonStr = response.split("```")[1]!.split("```")[0]!.trim();
		}

		const suggestions = parseReplySuggestions(JSON.parse(jsonStr));
		if (suggestions) {
			return suggestions;
		}

		return getDefaultSuggestions(comment);
	} catch (error) {
		logger.error("[aiService] Error parsing IG comment suggestions:", error);
		return getDefaultSuggestions(comment);
	}
};

/**
 * Generate AI-powered reply suggestions for Instagram DMs.
 * Context-aware: considers conversation history for continuity.
 */
export const generateIGDMSuggestions = async (
	incomingMessage: string,
	conversationContext: string = "",
	preferredStyle: ReplyStyle = "friendly",
	aiContext?: AIContext,
): Promise<ReplySuggestion[]> => {
	// Use unified AI context if provided, otherwise fall back to voice profile
	let voiceContext = "";
	if (aiContext) {
		voiceContext = contextToSystemPrompt(aiContext);
	} else {
		const voiceProfile = await loadVoiceProfile();
		voiceContext = voiceProfile ? buildVoiceContext(voiceProfile) : "";
	}

	let feedbackContext = "";
	try {
		const { buildFeedbackContext } = await import(
			"../../utils/buildFeedbackContext.js"
		);
		feedbackContext = await buildFeedbackContext("dm_response");
	} catch (_err) {}

	const prompt = `Craft Instagram DM replies that feel personal and human. DMs are private — the tone should be more intimate and conversational than public posts.
${voiceContext}
CONTEXT:
${conversationContext ? `Recent conversation:\n${conversationContext.substring(0, 500)}\n` : ""}
They just sent: "${incomingMessage.substring(0, 300)}${incomingMessage.length > 300 ? "..." : ""}"

Generate 3 DM reply suggestions with DISTINCT tones. Each should:
- Sound like the person in the voice profile having a 1-on-1 conversation
- Be under 500 characters
- Feel like texting a real person, not a brand or bot
- ${conversationContext ? "Continue the conversation naturally based on context above" : "Open warmly since there's no prior context"}
${feedbackContext ? `\nLearning context:\n${feedbackContext}` : ""}

Return ONLY valid JSON (no markdown, no code blocks):
{
  "suggestions": [
    {"text": "your casual/friendly reply", "style": "friendly", "confidence": 85},
    {"text": "your witty/playful reply", "style": "witty", "confidence": 80},
    {"text": "your professional/value-driven reply", "style": "promotional", "confidence": 75}
  ]
}

Style guide:
- friendly: Warm, casual, like texting a friend — use their name if known
- witty: Playful, flirty energy, personality-forward — shows charm
- promotional: Professional but warm — offers value, guides to next step

Preferred style is "${preferredStyle}" - make that one the strongest.`;

	try {
		const response = await generateContent(prompt);

		if (!response) {
			return getDefaultSuggestions(incomingMessage);
		}

		let jsonStr = response;
		if (response.includes("```json")) {
			jsonStr = response.split("```json")[1]!.split("```")[0]!.trim();
		} else if (response.includes("```")) {
			jsonStr = response.split("```")[1]!.split("```")[0]!.trim();
		}

		const suggestions = parseReplySuggestions(JSON.parse(jsonStr));
		if (suggestions) {
			return suggestions;
		}

		return getDefaultSuggestions(incomingMessage);
	} catch (error) {
		logger.error("[aiService] Error parsing IG DM suggestions:", error);
		return getDefaultSuggestions(incomingMessage);
	}
};

/**
 * Analyze sentiment of a reply text
 * @param text - The text to analyze
 * @returns Sentiment classification with confidence
 */
export const analyzeSentiment = async (
	text: string,
): Promise<{
	sentiment: SentimentType;
	confidence: number;
	reason?: string | undefined;
	language?: string | undefined;
	sarcasm_detected?: boolean | undefined;
}> => {
	// Quick local checks for obvious cases (saves API calls)
	const lowerText = text.toLowerCase();

	// Sarcasm indicators — check before positive patterns (sarcasm often uses positive words)
	const sarcasmEmojis = /(?:🙄|😒|💀|☠️|🤡|🫠)/u;
	const sarcasmPhrases =
		/\b(sure jan|oh great|yeah right|wow so|how original|must be nice|good for you|oh really|claro que sí|tá bom|c'est ça)\b/i;
	const hasSarcasmSignal =
		sarcasmEmojis.test(text) || sarcasmPhrases.test(text);

	// Toxic indicators — multilingual (check first)
	const toxicPatterns =
		/\b(hate|stupid|idiot|dumb|trash|garbage|die|kill|worst|sucks|shut up|f\*ck|fk|stfu|idiota|estúpido|basura|mierda|putain|connard|scheiße|arschloch)\b/i;
	if (toxicPatterns.test(lowerText)) {
		return {
			sentiment: "toxic",
			confidence: 90,
			reason: "Contains hostile language",
		};
	}

	// Strongly positive — multilingual
	const positivePatterns =
		/\b(love|amazing|awesome|great|thank|perfect|best|brilliant|fantastic|excellent|incredible|increíble|maravilloso|genial|gracias|obrigado|incrível|magnifique|merci|wunderbar|danke)\b/i;
	const positiveEmojis = /(?:😀|😊|🎉|❤️|💯|🙌|👏|✨|🔥|💪|😍|🥰)/u;

	// If sarcasm signal + positive words → don't trust the positive match, send to AI
	if (
		!hasSarcasmSignal &&
		(positivePatterns.test(lowerText) || positiveEmojis.test(text))
	) {
		return {
			sentiment: "positive",
			confidence: 85,
			reason: "Positive language/emojis detected",
		};
	}

	// Strongly negative (but not toxic) — multilingual
	const negativePatterns =
		/\b(disagree|wrong|bad|terrible|awful|disappointing|annoyed|frustrated|angry|upset|no way|malo|horrible|decepcionante|enojado|ruim|péssimo|horrível|mauvais|décevant|schlecht|enttäuschend)\b/i;
	const negativeEmojis = /[😤😠😡👎💔😢😞]/u;
	if (negativePatterns.test(lowerText) || negativeEmojis.test(text)) {
		return {
			sentiment: "negative",
			confidence: 80,
			reason: "Negative language/emojis detected",
		};
	}

	// For ambiguous cases or sarcasm signals, use AI
	if (text.length > 20 || hasSarcasmSignal) {
		try {
			const escapedText = text
				.substring(0, 500)
				.replace(/"/g, '\\"')
				.replace(/\n/g, "\\n");
			const prompt = `You are an expert multilingual social media sentiment analyst. Analyze this reply with deep nuance, catching sarcasm, irony, backhanded compliments, and cultural idioms.

Reply: "${escapedText}"

CRITICAL: Watch for these traps:
- Sarcasm: "Oh great, another amazing post 🙄" = NEGATIVE not positive
- Backhanded compliments: "Wow you're so brave for posting this" = often NEGATIVE
- Cultural idioms: "no mames" (Spanish) = surprise/disbelief, not toxic
- Emoji mismatch: positive words + 🙄😒💀 = likely sarcastic
- "Sure, Jan" energy: agreement that's actually dismissal

Language: Auto-detect. Analyze in the original language's cultural context.

Return ONLY valid JSON (no markdown):
{
  "sentiment": "positive|neutral|negative|toxic",
  "confidence": 75,
  "reason": "brief explanation",
  "intent": "question|complaint|praise|feedback|spam|joke|sarcasm|agreement|disagreement",
  "urgency": "low|medium|high",
  "suggestedAction": "reply|thank|ignore|escalate|engage",
  "language": "en|es|pt|fr|de|other",
  "sarcasm_detected": false
}`;

			const response = await generateContent(prompt);

			if (response) {
				let jsonStr = response;
				if (response.includes("```")) {
					jsonStr = response
						.replace(/```json?\n?/g, "")
						.replace(/```/g, "")
						.trim();
				}

				const parsed = JSON.parse(jsonStr);
				const validSentiments: SentimentType[] = [
					"positive",
					"neutral",
					"negative",
					"toxic",
				];

				if (validSentiments.includes(parsed.sentiment)) {
					return {
						sentiment: parsed.sentiment as SentimentType,
						confidence: Math.min(
							100,
							Math.max(0, Number(parsed.confidence) || 70),
						),
						reason: String(parsed.reason || "").substring(0, 100),
						language: parsed.language || undefined,
						sarcasm_detected: !!parsed.sarcasm_detected,
					};
				}
			}
		} catch (error) {
			logger.warn("[aiService] Sentiment analysis fallback to neutral:", error);
		}
	}

	// Default to neutral
	return {
		sentiment: "neutral",
		confidence: 60,
		reason: "No strong indicators",
	};
};

/**
 * Batch analyze sentiment for multiple replies (more efficient)
 * Uses local heuristics first, only calls AI for ambiguous cases
 */
export const analyzeSentimentBatch = async (
	texts: string[],
): Promise<
	Map<
		string,
		{
			sentiment: SentimentType;
			confidence: number;
			language?: string | undefined;
			sarcasm_detected?: boolean | undefined;
		}
	>
> => {
	const results = new Map<
		string,
		{
			sentiment: SentimentType;
			confidence: number;
			language?: string | undefined;
			sarcasm_detected?: boolean | undefined;
		}
	>();

	for (const text of texts) {
		const result = await analyzeSentiment(text);
		results.set(text, {
			sentiment: result.sentiment,
			confidence: result.confidence,
			language: result.language,
			sarcasm_detected: result.sarcasm_detected,
		});
	}

	return results;
};

// ========================================
// MATCH TOP POST STYLE & A/B TESTING
// ========================================

export const generateDMResponse = async (
	incomingMessage: string,
	conversationHistory: { role: "user" | "assistant"; content: string }[],
	intent:
		| "engage"
		| "redirect_to_link"
		| "polite_decline"
		| "flirty_tease" = "engage",
	voiceProfile?: VoiceProfile,
	customSystemPrompt?: string,
	aiContext?: AIContext,
): Promise<{ response: string; tokensUsed: number }> => {
	// Load feedback context for personalization
	let feedbackContext = "";
	try {
		const { buildFeedbackContext } = await import(
			"../../utils/buildFeedbackContext.js"
		);
		feedbackContext = await buildFeedbackContext("dm_response");
	} catch {
		/* non-critical */
	}

	const intentPrompts: Record<string, string> = {
		engage:
			"Respond naturally and warmly. Keep it short (1-3 sentences). Match their energy. Build rapport.",
		redirect_to_link:
			"Be engaging. After natural conversation, subtly mention you have more exclusive content on your link. Never be pushy. Make them curious.",
		polite_decline:
			"Politely but firmly exit this conversation. Be graceful, don't engage further with inappropriate topics.",
		flirty_tease:
			"Be playful and teasing. Use emojis. Leave them wanting more. Create mystery and desire. Keep it short and punchy.",
	};

	const voiceInstructions = aiContext
		? `\n${contextToSystemPrompt(aiContext)}`
		: voiceProfile
			? `
VOICE PROFILE:
- Tone: ${voiceProfile.extracted_style?.tone?.vibe || "casual"}
- Energy: ${voiceProfile.extracted_style?.tone?.energy || "moderate"}
- Emoji style: ${voiceProfile.extracted_style?.emoji_usage?.frequency || "moderate"}
- Favorite emojis: ${voiceProfile.extracted_style?.emoji_usage?.favorites?.join(" ") || ""}
${voiceProfile.voice_profile ? `- Voice description: ${voiceProfile.voice_profile}` : ""}`
			: "";

	const conversationContext =
		conversationHistory.length > 0
			? `\nCONVERSATION HISTORY:\n${conversationHistory.map((m) => `${m.role}: ${m.content}`).join("\n")}`
			: "";

	const systemOverride = customSystemPrompt
		? `\nADDITIONAL INSTRUCTIONS: ${customSystemPrompt}`
		: "";

	const prompt = `You are responding to a DM. Never break character. Never mention you're AI.
${voiceInstructions}
${systemOverride}${feedbackContext}

INTENT: ${intent}
${intentPrompts[intent]}
${conversationContext}

INCOMING MESSAGE: "${incomingMessage}"

Respond in 1-3 sentences. Be natural. Match the platform (Instagram DM).`;

	try {
		const response = await generateContent(prompt);

		let cleanResponse = response.trim();
		if (cleanResponse.startsWith('"') && cleanResponse.endsWith('"')) {
			cleanResponse = cleanResponse.slice(1, -1);
		}

		return {
			response: cleanResponse,
			tokensUsed:
				Math.ceil(prompt.length / 4) + Math.ceil(cleanResponse.length / 4),
		};
	} catch (error) {
		logger.error("[aiService] generateDMResponse failed:", error);
		throw error;
	}
};

/**
 * Get user's top performing post content for style matching
 */
