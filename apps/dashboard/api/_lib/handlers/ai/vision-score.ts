// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Vision AI Scoring — POST /api/ai/vision-score
 *
 * Scores image quality for social media using Gemini Vision.
 * Body: { imageUrl: string, platform: 'instagram' | 'threads' }
 * Response: { score, breakdown, suggestions, captionAngle, cached }
 */

import * as crypto from "node:crypto";
import { GoogleGenAI } from "@google/genai";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getUserAIConfig } from "../../aiConfig.js";
import { recordDirectAIEvalSnapshot } from "../../aiEvalSnapshots.js";
import { checkAIRateLimit } from "../../aiRateLimit.js";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { trackUsage } from "../../auditLog.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { fetchPublicUrlWithRedirects } from "../../outboundUrlSecurity.js";
import { sanitizeAIOutput } from "../../promptUtils.js";
import { getRedis } from "../../redis.js";
import { requireMinTier } from "../../tierGate.js";

const geminiClients = new Map<string, GoogleGenAI>();

function getGeminiClient(apiKey: string): GoogleGenAI {
	let client = geminiClients.get(apiKey);
	if (!client) {
		client = new GoogleGenAI({ apiKey });
		geminiClients.set(apiKey, client);
	}
	return client;
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

		// Tier gate — Vision Score requires Pro or higher
		if (!(await requireMinTier(user.id, "pro", res))) return;

		const { imageUrl, platform } = req.body || {};
		if (!imageUrl || typeof imageUrl !== "string") {
			return apiError(res, 400, "imageUrl required");
		}

		// SSRF prevention: only allow HTTPS URLs
		try {
			const parsed = new URL(imageUrl);
			if (parsed.protocol !== "https:") {
				return apiError(res, 400, "Only HTTPS image URLs are allowed");
			}
		} catch {
			return apiError(res, 400, "Invalid image URL");
		}

		// Tier-aware rate limit (Free 20/h, Pro 100/h, Empire 500/h)
		const rl = await checkAIRateLimit(user.id, "vision-score");
		if (!rl.allowed)
			return apiError(
				res,
				429,
				"Rate limit exceeded. Please upgrade for higher limits.",
			);

		const redis = getRedis();
		const urlHash = crypto.createHash("sha256").update(imageUrl).digest("hex");
		const cacheKey = `vision-score:${urlHash}`;

		// Check cache
		try {
			const cached = await redis.get(cacheKey);
			if (cached) {
				const parsed = typeof cached === "string" ? JSON.parse(cached) : cached;
				return apiSuccess(res, { ...parsed, cached: true });
			}
		} catch (err) {
			logger.debug("[ai/vision-score] Redis cache read failed", {
				error: String(err),
			});
			// Cache miss, continue
		}

		// Vision scoring currently uses Gemini Vision. Do not pass an OpenAI/xAI
		// key into Gemini just because the text provider is configured.
		const aiConfig = await getUserAIConfig(user.id);
		const geminiApiKey =
			aiConfig?.provider === "gemini"
				? aiConfig.apiKey
				: process.env.GEMINI_API_KEY;
		if (!geminiApiKey)
			return apiError(
				res,
				503,
				"Vision scoring requires a Gemini-capable AI key.",
				{ code: "VISION_PROVIDER_UNAVAILABLE" },
			);

		try {
			// Fetch image as base64
			const imgResp = await fetchPublicUrlWithRedirects(
				imageUrl,
				"ai-vision-score",
				{
					signal: AbortSignal.timeout(15000),
				},
			);
			if (!imgResp?.ok) return apiError(res, 400, "Failed to fetch image");

			const rawContentType = imgResp.headers.get("content-type") || "image/jpeg";
			const contentType = rawContentType.split(";")[0]!.trim();
			if (!contentType.startsWith("image/")) {
				return apiError(res, 400, "URL must point to an image");
			}
			const buffer = await imgResp.arrayBuffer();
			const base64 = Buffer.from(buffer).toString("base64");

			const client = getGeminiClient(geminiApiKey);

			const prompt = `You are an Instagram/social media visual content expert. Analyze this image for ${platform || "social media"} posting quality.

Use this scoring rubric for every dimension:
- 1-40: poor (clear quality issues)
- 41-70: acceptable (functional but not standout)
- 71-90: strong (above average for social)
- 91-100: exceptional (rare, scroll-stopping quality)

Platform: ${platform === "instagram" ? "Instagram (optimal 4:5 portrait, 1080px min, mobile-first crop)" : "Threads (square or portrait, conversational visual style)"}

Rate each category 1-100:
- composition: Rule of thirds, framing, visual balance
- lighting: Exposure, contrast, natural vs artificial
- color: Palette harmony, saturation, warmth
- clarity: Focus, sharpness, noise level
- engagement_potential: Scroll-stopping power, emotional impact, shareability

Return JSON only:
{
  "overall_score": <weighted average>,
  "breakdown": {
    "composition": <score>,
    "lighting": <score>,
    "color": <score>,
    "clarity": <score>,
    "engagement_potential": <score>
  },
  "suggestions": ["<improvement 1>", "<improvement 2>", "<improvement 3>"],
  "caption_angle": "<suggested caption approach based on image content>"
}`;

			const result = await client.models.generateContent({
				model: "gemini-2.0-flash",
				contents: [
					{
						role: "user",
						parts: [
							{ text: prompt },
							{ inlineData: { mimeType: contentType, data: base64 } },
						],
					},
				],
			});

			const text = result.text || "";
			const sanitized = sanitizeAIOutput(text);

			// Parse JSON from response
			const jsonMatch = sanitized.match(/\{[\s\S]*\}/);
			if (!jsonMatch) return apiError(res, 500, "Failed to parse AI response");

			const parsed = JSON.parse(jsonMatch[0]);
			const clampScore = (n: unknown) => Math.min(100, Math.max(1, Math.round(Number(n) || 0)));
			const REQUIRED_KEYS = ["composition", "lighting", "color", "clarity", "engagement_potential"] as const;
			const rawBreakdown = parsed.breakdown || {};
			const breakdown = Object.fromEntries(REQUIRED_KEYS.map(k => [k, clampScore(rawBreakdown[k])]));
			const overall_score = clampScore(parsed.overall_score);
			const response = {
				score: overall_score,
				breakdown,
				suggestions: Array.isArray(parsed.suggestions)
					? parsed.suggestions
					: [],
				captionAngle: parsed.caption_angle || "",
			};

			recordDirectAIEvalSnapshot({
				userId: user.id,
				surface: "ai_vision_score",
				actionType: "score_media",
				category: "media_quality",
				prompt,
				output: response,
				provider: "gemini",
				model: "gemini-2.0-flash",
				parameters: {
					platform: platform || "social",
					contentType,
					imageHash: urlHash,
				},
				passed: true,
				metadata: {
					cacheKey,
					route: "/api/ai/vision-score",
				},
			}).catch((error) => {
				logger.warn("[ai/vision-score] Eval snapshot failed", { error: String(error) });
			});

			// Cache for 24h
			try {
				await redis.set(cacheKey, JSON.stringify(response), { ex: 86400 });
			} catch (err) {
				logger.debug("[ai/vision-score] Redis cache write failed", {
					error: String(err),
				});
				// Cache write failure is non-fatal
			}

			// Track usage
			trackUsage(user.id, "ai/vision-score").catch(() => {});

			return apiSuccess(res, { ...response, cached: false });
		} catch (err) {
			logger.error("[ai/vision-score] Error", { error: String(err) });
			return apiError(res, 500, "Internal server error");
		}
	},
);
