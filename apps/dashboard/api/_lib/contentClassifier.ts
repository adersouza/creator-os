/**
 * Content Classifier — classifies posts into content categories.
 * Uses rule-based classification first (saves ~60% of Gemini API calls),
 * falling back to Gemini only for ambiguous posts.
 */

import type { UserAIConfig } from "./aiConfig.js";
import {
	buildAICacheKey,
	getCachedAIResponse,
	setCachedAIResponse,
} from "./aiCache.js";
import { generateWithProvider } from "./handlers/auto-post/aiProviders.js";
import { logger } from "./logger.js";
import { escapeForPrompt } from "./promptUtils.js";

const CONTENT_CATEGORIES = [
	"promotional",
	"educational",
	"entertainment",
	"behind-the-scenes",
	"engagement-bait",
	"inspirational",
	"news",
	"user-generated",
] as const;

export type ContentCategory = (typeof CONTENT_CATEGORIES)[number];

export interface ClassificationResult {
	primary: ContentCategory;
	confidence: number;
	source?: "rule" | "ai" | undefined;
}

// Cost savings: ~60% of posts match rules and skip Gemini entirely
const URL_REGEX = /https?:\/\/\S+/i;
const LIST_MARKER_REGEX = /(?:^|\n)\s*(?:[-•*]|\d+[.)]\s)/;

/**
 * Rule-based classification — fast, free, handles obvious cases.
 * Returns null if the post is ambiguous and needs Gemini.
 */
function classifyByRules(
	caption: string,
	mediaType: string,
): ClassificationResult | null {
	const text = (caption || "").trim();
	const isVisualMedia = /image|video|photo|carousel|reel/i.test(mediaType);

	// Rule 1: Visual media with no/very short text → "entertainment" (visual content)
	if (isVisualMedia && text.length < 20) {
		return { primary: "entertainment", confidence: 0.8, source: "rule" };
	}

	// Rule 2: Contains question mark and substantial text → "engagement-bait"
	if (text.includes("?") && text.length > 50) {
		return { primary: "engagement-bait", confidence: 0.75, source: "rule" };
	}

	// Rule 3: Contains a URL → "promotional" (link share)
	if (URL_REGEX.test(text)) {
		return { primary: "promotional", confidence: 0.7, source: "rule" };
	}

	// Rule 4: Long-form / thread (multiple paragraphs or >500 chars)
	if (text.length > 500 || text.split(/\n\s*\n/).length >= 3) {
		return { primary: "educational", confidence: 0.7, source: "rule" };
	}

	// Rule 5: List markers or numbered points → "educational"
	if (LIST_MARKER_REGEX.test(text)) {
		return { primary: "educational", confidence: 0.7, source: "rule" };
	}

	// Ambiguous — needs Gemini
	return null;
}

/** Cache TTL for classification: 7 days (same text = same classification) */
const CLASSIFICATION_CACHE_TTL = 7 * 24 * 3600;

/**
 * Classify a post into a content category.
 * Tries rule-based first, then Redis cache, then Gemini as last resort.
 */
export async function classifyPost(
	aiConfig: UserAIConfig | string,
	caption: string,
	mediaType: string,
	hashtags: string[],
	platform: string,
	userId: string = "platform",
): Promise<ClassificationResult> {
	// Step 1: Rule-based classification (free, instant)
	const ruleResult = classifyByRules(caption, mediaType);
	if (ruleResult) {
		return ruleResult;
	}

	// Step 2: Check Redis cache by text hash (avoids duplicate Gemini calls)
	const prompt = `Classify this ${platform} post into exactly ONE of these categories: ${CONTENT_CATEGORIES.join(", ")}.

Post caption: "${escapeForPrompt(caption || "(no caption)")}"
Media type: ${mediaType}
Hashtags: ${hashtags.length > 0 ? hashtags.join(", ") : "none"}
Platform: ${platform}

Respond with ONLY a JSON object: {"primary": "<category>", "confidence": <0.0-1.0>}
No other text.`;

	const config =
		typeof aiConfig === "string"
			? {
					provider: "gemini",
					apiKey: aiConfig,
					model: "gemini-2.5-flash",
					source: "user" as const,
				}
			: aiConfig;
	const modelId = config.model || "gemini-2.5-flash";
	const cacheKey = buildAICacheKey(prompt, modelId, 0.2);
	const cached = await getCachedAIResponse(cacheKey);
	if (cached) {
		try {
			const parsed = JSON.parse(cached);
			return { ...parsed, source: "ai" } as ClassificationResult;
		} catch (err) {
			logger.debug("fall through to Gemini", { error: String(err) });
		}
	}

	// Step 3: AI classification (only for ambiguous posts, with retry/fallback)
	try {
		const response = await generateWithProvider(prompt, {
			provider: config.provider,
			apiKey: config.apiKey,
			baseUrl: config.baseUrl,
			model: modelId,
			keySource: config.source,
			ideaCount: 1,
			useStructuredOutput: true,
			structuredOutputSchema: {
				type: "OBJECT",
				properties: {
					primary: { type: "STRING" },
					confidence: { type: "NUMBER" },
				},
				required: ["primary", "confidence"],
			},
			actionLog: {
				userId,
				surface: "analytics",
				actionType: "content_classifier",
				inputText: prompt.slice(0, 4000),
				metadata: { platform, mediaType, provider: config.provider },
			},
		});

		const text = (response || "").trim();
		const jsonMatch = text.match(/\{[^}]+\}/);
		if (!jsonMatch) {
			logger.warn("[contentClassifier] No JSON in response", { text });
			return { primary: "entertainment", confidence: 0.5, source: "ai" };
		}

		const parsed = JSON.parse(jsonMatch[0]);
		const category = CONTENT_CATEGORIES.includes(parsed.primary)
			? parsed.primary
			: "entertainment";
		const confidence =
			typeof parsed.confidence === "number"
				? Math.min(1, Math.max(0, parsed.confidence))
				: 0.5;

		const result = { primary: category as ContentCategory, confidence };

		// Cache for 7 days — same text always gets same classification
		await setCachedAIResponse(
			cacheKey,
			JSON.stringify(result),
			CLASSIFICATION_CACHE_TTL,
		);

		return { ...result, source: "ai" };
	} catch (err: unknown) {
		logger.error("[contentClassifier] Classification failed", {
			error: err instanceof Error ? err.message : String(err),
		});
		return { primary: "entertainment", confidence: 0.3, source: "ai" };
	}
}
