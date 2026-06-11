/**
 * buildFeedbackContext — Unified feedback context builder
 * Combines both feedback systems (aiFeedbackService + aiFeedback) with caching.
 * Returns a string to inject into AI prompts. Never blocks on failure.
 */

import type { AIFeature } from "../services/aiFeedbackService.js";

interface CacheEntry {
  value: string;
  expiresAt: number;
}

const CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes
const cache = new Map<string, CacheEntry>();

/**
 * Build a combined feedback context string for AI prompts.
 * Merges structured style preferences (ai_feedback table) with
 * thumbs up/down sentiment examples (user_settings table).
 *
 * @param feature - The AI feature key to scope preferences to
 * @returns A prompt-ready string, or empty string on failure
 */
export async function buildFeedbackContext(
  feature: AIFeature,
): Promise<string> {
  try {
    const cached = cache.get(feature);
    if (cached && cached.expiresAt > Date.now()) {
      return cached.value;
    }

    const [styleHint, sentimentContext] = await Promise.all([
      loadStyleHint(feature),
      loadSentimentContext(),
    ]);

    const parts: string[] = [];
    if (styleHint) parts.push(styleHint);
    if (sentimentContext) parts.push(sentimentContext);

    const result =
      parts.length > 0
        ? `\n\nUSER FEEDBACK CONTEXT:\n${parts.join("\n")}`
        : "";

    cache.set(feature, { value: result, expiresAt: Date.now() + CACHE_TTL_MS });
    return result;
  } catch {
    return "";
  }
}

async function loadStyleHint(feature: AIFeature): Promise<string | null> {
  try {
    const { getPreferredStyle } = await import(
      "../services/aiFeedbackService.js"
    );
    return await getPreferredStyle(feature);
  } catch {
    return null;
  }
}

async function loadSentimentContext(): Promise<string> {
  try {
    const { loadFeedbackContext } = await import("./aiFeedback.js");
    return await loadFeedbackContext();
  } catch {
    return "";
  }
}

/**
 * Invalidate cached feedback context. Call after new feedback is submitted.
 */
export function invalidateFeedbackCache(): void {
  cache.clear();
}
