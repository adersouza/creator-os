/**
 * Sentiment Analysis Utility
 * 
 * Provides rule-based sentiment detection for social media comments.
 * Includes support for slang, emojis, and basic multilingual patterns.
 */

export type SentimentType = "positive" | "negative" | "neutral" | "question";

// Positive keywords (English + common slang + multilingual)
const POSITIVE_KEYWORDS = [
	"love", "great", "awesome", "amazing", "fantastic", "excellent", "wonderful", 
	"brilliant", "perfect", "best", "thank", "thanks", "appreciate", "helpful", 
	"incredible", "nice", "good", "beautiful", "fire", "goat", "legend", "insane", 
	"peak", "dope", "sick", "lit", "valid", "based", "real", "facts", "truth", 
	"inspiring", "motivated", "slay", "ate", "chef's kiss", "massive w", "huge w",
	"queen", "king", "underrated", "gamechanger", "obsessed", "vibe", "vibes",
	// Spanish
	"genial", "increíble", "maravilloso", "excelente", "gracias", "bueno", "encanta",
	// Portuguese
	"incrível", "maravilhoso", "obrigado", "obrigada", "ótimo", "bom", "legal",
	// French
	"magnifique", "merci", "superbe", "génial", "formidable", "bon",
	// German
	"wunderbar", "fantastisch", "danke", "großartig", "toll", "gut"
];

const POSITIVE_EMOJIS = [
	"❤️", "🔥", "💯", "👏", "🙌", "😍", "🎉", "✨", "💪", "👑", "🚀", "💎", "✅", 
	"🤩", "🥳", "🥰", "👌", "🤝", "🎈", "🌟"
];

// Negative keywords (English + common slang + multilingual)
const NEGATIVE_KEYWORDS = [
	"hate", "bad", "awful", "terrible", "horrible", "worst", "disappointing", 
	"useless", "stupid", "dumb", "trash", "garbage", "sucks", "boring", "annoying", 
	"cringe", "mid", "ratio", "cap", "fake", "fraud", "scam", "waste", "boring",
	"cancelled", "dead", "flop", "fell off", "L", "huge l", "massive l", "weird",
	"stop", "dont", "don't", "no", "never", "disgusting", "pathetic",
	// Spanish
	"odio", "horrible", "terrible", "basura", "asco", "malo", "no",
	// Portuguese
	"ódio", "horrível", "terrível", "lixo", "nojo", "ruim", "não",
	// French
	"déteste", "nul", "horrible", "dégoûtant", "affreux", "mauvais", "non",
	// German
	"hass", "schrecklich", "furchtbar", "müll", "ekelhaft", "schlecht", "nein"
];

const NEGATIVE_EMOJIS = [
	"😡", "👎", "💀", "🤮", "😤", "🙄", "🤬", "🤡", "💩", "🚫", "❌", "😒", "🤢",
	"😠", "🖕", "💔", "📉"
];

/**
 * Analyze sentiment of text using keyword and emoji matching.
 * Returns: positive, negative, neutral, or question
 */
export function analyzeSentiment(text: string | null | undefined): SentimentType {
	if (!text || typeof text !== "string" || text.trim().length === 0) {
		return "neutral";
	}

	const lowerText = text.toLowerCase();

	// 1. Question detection (highest priority)
	const questionWords = ["how", "what", "why", "when", "where", "who", "can you", "could you", "is it", "are you", "should i"];
	const isQuestion = lowerText.includes("?") || 
					   questionWords.some(word => lowerText.startsWith(word));
	
	if (isQuestion) return "question";

	// 2. Score calculation
	let positiveScore = 0;
	let negativeScore = 0;

	// Check words (with word boundary for short slang like "W" or "L")
	POSITIVE_KEYWORDS.forEach(keyword => {
		if (keyword.length <= 2) {
			// Short slang needs boundaries
			const regex = new RegExp(`\b${keyword}\b`, "i");
			if (regex.test(lowerText)) positiveScore += 2; // Slang "W" is strong
		} else if (lowerText.includes(keyword)) {
			positiveScore++;
		}
	});

	NEGATIVE_KEYWORDS.forEach(keyword => {
		if (keyword.length <= 2) {
			const regex = new RegExp(`\b${keyword}\b`, "i");
			if (regex.test(lowerText)) negativeScore += 2; // Slang "L" is strong
		} else if (lowerText.includes(keyword)) {
			negativeScore++;
		}
	});

	// Check emojis (usually very high signal)
	POSITIVE_EMOJIS.forEach(emoji => {
		if (text.includes(emoji)) positiveScore += 2;
	});

	NEGATIVE_EMOJIS.forEach(emoji => {
		if (text.includes(emoji)) negativeScore += 2;
	});

	// 3. Final verdict
	if (positiveScore > negativeScore) {
		return "positive";
	} else if (negativeScore > positiveScore) {
		return "negative";
	}

	return "neutral";
}
