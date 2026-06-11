/**
 * POST /api/ai/insight-to-caption — Generate 3 caption hooks from an AI insight
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";

interface CaptionItem {
	style: string;
	text?: string | undefined;
	[key: string]: unknown;
}

interface ParsedCaptions {
	captions: CaptionItem[];
}

import {
	AI_CACHE_TTL,
	buildAICacheKey,
	getCachedAIResponse,
	setCachedAIResponse,
} from "../../aiCache.js";
import { getUserAIConfig } from "../../aiConfig.js";
import { checkAIRateLimit } from "../../aiRateLimit.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { escapeForPrompt, sanitizeAIOutput } from "../../promptUtils.js";
import { requireMinTier } from "../../tierGate.js";
import { generateWithProvider } from "../auto-post/aiProviders.js";

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		// Tier gate — Insight-to-Caption requires Pro or higher
		if (!(await requireMinTier(user.id, "pro", res))) return;

		const { insight } = req.body || {};
		if (!insight || typeof insight !== "string" || insight.length < 10) {
			return apiError(res, 400, "insight is required (min 10 chars)");
		}

		// Tier-aware rate limit (Free 20/h, Pro 100/h, Empire 500/h)
		const rl = await checkAIRateLimit(user.id, "insight-to-caption");
		res.setHeader("X-RateLimit-Limit", String(rl.limit));
		res.setHeader("X-RateLimit-Remaining", String(rl.remaining));
		if (!rl.allowed) {
			return apiError(
				res,
				429,
				"Rate limit exceeded. Please upgrade for higher limits.",
				{ code: "RATE_LIMITED" },
			);
		}

		const aiConfig = await getUserAIConfig(user.id);
		if (!aiConfig) {
			return apiError(
				res,
				503,
				"AI features temporarily unavailable. Add your own API key in Settings for immediate access.",
				{ code: "NO_API_KEY" },
			);
		}

		const model = aiConfig.model || "gemini-2.5-flash";
		const systemPrompt = `You are a social media caption writer. Given an analytics insight, generate exactly 3 caption hooks for a Threads/Instagram post. Each must be a compelling opening that makes people stop scrolling.

The 3 styles:
1. **Thread hook** — Conversational, addresses the audience directly, teases data. Example tone: "Your audience loves when you ask questions. Here's what the data says..."
2. **Authority hook** — First-person expertise, positions the creator as someone who's done the work. Example tone: "I analyzed 50 of my posts. The #1 pattern behind my best content..."
3. **Curiosity hook** — Surprising or counterintuitive angle, creates an open loop. Example tone: "Plot twist: my most engaged posts aren't the ones I spent the most time on..."

Rules:
- Each caption should be 1-3 sentences (the hook + a teaser)
- Ground them in the specific insight provided
- Make them ready to post as-is (the user will expand from here)
- Return valid JSON only, no markdown fencing

Insight: "${escapeForPrompt(insight.substring(0, 1000))}"

Return JSON: { "captions": [ { "style": "thread", "text": "..." }, { "style": "authority", "text": "..." }, { "style": "curiosity", "text": "..." } ] }`;

		try {
			const cacheKey = buildAICacheKey(systemPrompt, model, 0.7, user.id);
			const cached = await getCachedAIResponse(cacheKey);
			if (cached) {
				try {
					const parsed = JSON.parse(cached);
					return apiSuccess(res, { captions: parsed.captions, cached: true });
				} catch (err) {
					logger.debug(
						"Failed to parse cached AI caption response, regenerating",
						{ error: String(err) },
					);
					// cached value corrupted, regenerate
				}
			}

			const raw = await generateWithProvider(systemPrompt, {
				provider: aiConfig.provider,
				apiKey: aiConfig.apiKey,
				baseUrl: aiConfig.baseUrl,
				model,
				keySource: aiConfig.source,
				ideaCount: 3,
				useStructuredOutput: true,
				structuredOutputSchema: {
					type: "OBJECT",
					properties: {
						captions: {
							type: "ARRAY",
							items: {
								type: "OBJECT",
								properties: {
									style: { type: "STRING" },
									text: { type: "STRING" },
								},
								required: ["style", "text"],
							},
						},
					},
					required: ["captions"],
				},
				actionLog: {
					userId: user.id,
					surface: "analytics",
					actionType: "insight_to_caption",
					inputText: insight.slice(0, 2000),
					metadata: { provider: aiConfig.provider },
				},
			});
			if (!raw) {
				return apiError(res, 502, "Caption generation failed");
			}

			// Parse JSON from response (strip markdown fencing if present)
			const jsonStr = raw.trim().replace(/^```json?\s*/i, "").replace(/\s*```$/i, "");
			let parsed: ParsedCaptions;
			try {
				parsed = JSON.parse(jsonStr);
			} catch (_err) {
				logger.error("[ai/insight-to-caption] Failed to parse JSON", { raw });
				return apiError(res, 502, "AI returned invalid format");
			}

			if (
				!parsed.captions ||
				!Array.isArray(parsed.captions) ||
				parsed.captions.length !== 3
			) {
				return apiError(res, 502, "AI returned unexpected structure");
			}

			// Sanitize AI output
			parsed.captions = parsed.captions.map((c: CaptionItem) => ({
				...c,
				text: c.text ? sanitizeAIOutput(c.text) : "",
			}));

			await setCachedAIResponse(
				cacheKey,
				JSON.stringify(parsed),
				AI_CACHE_TTL.CONTENT_GENERATION,
			);

			return apiSuccess(res, { captions: parsed.captions });
		} catch (err: unknown) {
			logger.error("[ai/insight-to-caption] Failed", {
				userId: user.id,
				error: err instanceof Error ? err.message : String(err),
			});
			return apiError(res, 502, "Caption generation failed");
		}
	},
);
