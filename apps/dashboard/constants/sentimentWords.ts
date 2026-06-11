/**
 * Sentiment Analysis Word Lists
 *
 * Used for keyword-based sentiment detection in Instagram comments.
 * These can be customized or extended per user/workspace in the future.
 */

export const POSITIVE_WORDS = new Set([
  "love", "great", "amazing", "awesome", "beautiful", "wonderful", "perfect",
  "fantastic", "incredible", "excellent", "stunning", "gorgeous", "best",
  "thank", "thanks", "congrats", "congratulations", "bravo", "inspiring",
  "fire", "lit", "slay", "queen", "king", "goals", "obsessed", "iconic",
]);

export const NEGATIVE_WORDS = new Set([
  "hate", "ugly", "terrible", "horrible", "worst", "bad", "awful", "disgusting",
  "boring", "lame", "cringe", "disappointed", "disappointing", "overrated",
  "mid", "meh", "nah", "ugh", "yikes", "fail",
]);

export const TOXIC_WORDS = new Set([
  "stupid", "idiot", "dumb", "loser", "trash", "pathetic", "worthless",
  "die", "kill", "shut up", "stfu", "kys",
]);

/**
 * Analyze sentiment of text based on keyword matching
 */
export function analyzeSentiment(text: string | null | undefined): "positive" | "negative" | "toxic" | "neutral" {
  if (!text || typeof text !== "string" || text.trim().length === 0) {
    return "neutral";
  }

  const lowerText = text.toLowerCase();
  const words = lowerText.split(/\s+/);

  // Check for toxic words/phrases first (highest priority)
  // Check multi-word phrases against full text, single words against word list
  for (const toxic of TOXIC_WORDS) {
    if (toxic.includes(" ") ? lowerText.includes(toxic) : words.includes(toxic)) {
      return "toxic";
    }
  }

  // Check for negative words
  for (const word of words) {
    if (NEGATIVE_WORDS.has(word)) {
      return "negative";
    }
  }

  // Check for positive words
  for (const word of words) {
    if (POSITIVE_WORDS.has(word)) {
      return "positive";
    }
  }

  return "neutral";
}

/**
 * Future enhancement: Allow custom word lists per user
 */
export interface CustomSentimentWords {
  positive?: string[];
  negative?: string[];
  toxic?: string[];
}

export function createCustomSentimentAnalyzer(custom: CustomSentimentWords) {
  const positiveSet = new Set([...POSITIVE_WORDS, ...(custom.positive || [])]);
  const negativeSet = new Set([...NEGATIVE_WORDS, ...(custom.negative || [])]);
  const toxicSet = new Set([...TOXIC_WORDS, ...(custom.toxic || [])]);

  return (text: string | null | undefined): "positive" | "negative" | "toxic" | "neutral" => {
    if (!text || typeof text !== "string" || text.trim().length === 0) {
      return "neutral";
    }

    const lowerText = text.toLowerCase();
    const words = lowerText.split(/\s+/);

    for (const toxic of toxicSet) {
      if (toxic.includes(" ") ? lowerText.includes(toxic) : words.includes(toxic)) {
        return "toxic";
      }
    }

    for (const word of words) {
      if (negativeSet.has(word)) return "negative";
    }

    for (const word of words) {
      if (positiveSet.has(word)) return "positive";
    }

    return "neutral";
  };
}
