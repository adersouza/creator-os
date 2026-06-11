// biome-ignore-all lint/style/noNonNullAssertion: Existing API route style uses non-null assertions in narrow validation paths.
/**
 * AI Alt Text — POST /api/ai/alt-text
 *
 * Generates concise accessibility alt text for an owned/public image URL.
 * Body: { imageUrl: string, platform?: "instagram" | "threads", postType?: string }
 */

import * as crypto from "node:crypto";
import { GoogleGenAI } from "@google/genai";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { getUserAIConfig } from "../_lib/aiConfig.js";
import { recordDirectAIEvalSnapshot } from "../_lib/aiEvalSnapshots.js";
import { checkAIRateLimit } from "../_lib/aiRateLimit.js";
import { apiError, apiSuccess } from "../_lib/apiResponse.js";
import { trackUsage } from "../_lib/auditLog.js";
import { logger } from "../_lib/logger.js";
import { withAuth } from "../_lib/middleware.js";
import { fetchPublicUrlWithRedirects } from "../_lib/outboundUrlSecurity.js";
import { sanitizeAIOutput } from "../_lib/promptUtils.js";
import { getRedis } from "../_lib/redis.js";
import { requireMinTier } from "../_lib/tierGate.js";
import { z } from "../_lib/zodCompat.js";

export const config = { maxDuration: 60 };

const BodySchema = z.object({
	imageUrl: z.string().url(),
	platform: z.enum(["instagram", "threads"]).optional(),
	postType: z.string().max(32).optional(),
});

const geminiClients = new Map<string, GoogleGenAI>();

function getGeminiClient(apiKey: string): GoogleGenAI {
	let client = geminiClients.get(apiKey);
	if (!client) {
		client = new GoogleGenAI({ apiKey });
		geminiClients.set(apiKey, client);
	}
	return client;
}

function normalizeAltText(value: unknown): string {
	const raw = typeof value === "string" ? value : "";
	return raw
		.replace(/^["']|["']$/g, "")
		.replace(/\s+/g, " ")
		.trim()
		.slice(0, 100);
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") return apiError(res, 405, "Method not allowed");
		if (!(await requireMinTier(user.id, "pro", res))) return;

		const parsed = BodySchema.safeParse(req.body || {});
		if (!parsed.success) return apiError(res, 400, "Invalid alt text request");
		const { imageUrl, platform = "instagram", postType = "feed" } = parsed.data as {
			imageUrl: string;
			platform?: "instagram" | "threads";
			postType?: string;
		};

		try {
			const url = new URL(imageUrl);
			if (url.protocol !== "https:") {
				return apiError(res, 400, "Only HTTPS image URLs are allowed");
			}
		} catch {
			return apiError(res, 400, "Invalid image URL");
		}

		const rl = await checkAIRateLimit(user.id, "alt-text");
		if (!rl.allowed) {
			return apiError(res, 429, "Rate limit exceeded. Try again later.");
		}

		const redis = getRedis();
		const cacheHash = crypto
			.createHash("sha256")
			.update(`${imageUrl}:${platform}:${postType}`)
			.digest("hex");
		const cacheKey = `alt-text:${cacheHash}`;

		try {
			const cached = await redis.get(cacheKey);
			if (cached) {
				const data = typeof cached === "string" ? JSON.parse(cached) : cached;
				return apiSuccess(res, { ...data, cached: true });
			}
		} catch (err) {
			logger.debug("[ai/alt-text] Redis cache read failed", { error: String(err) });
		}

		const aiConfig = await getUserAIConfig(user.id);
		const geminiApiKey =
			aiConfig?.provider === "gemini" ? aiConfig.apiKey : process.env.GEMINI_API_KEY;
		if (!geminiApiKey) {
			return apiError(res, 503, "Alt text generation requires a Gemini-capable AI key.", {
				code: "VISION_PROVIDER_UNAVAILABLE",
			});
		}

		try {
			const imageResponse = await fetchPublicUrlWithRedirects(
				imageUrl,
				"ai-alt-text",
				{ signal: AbortSignal.timeout(15000) },
			);
			if (!imageResponse?.ok) return apiError(res, 400, "Failed to fetch image");

			const contentType = (imageResponse.headers.get("content-type") || "image/jpeg")
				.split(";")[0]!
				.trim();
			if (!contentType.startsWith("image/")) {
				return apiError(res, 400, "URL must point to an image");
			}

			const buffer = await imageResponse.arrayBuffer();
			const base64 = Buffer.from(buffer).toString("base64");
			const client = getGeminiClient(geminiApiKey);
			const prompt = `Write accessibility alt text for a ${platform} ${postType} image.

Rules:
- Describe only visible content.
- Keep it under 100 characters.
- Do not say "image of" or "photo of".
- Do not add marketing copy, hashtags, emoji, or speculation.

Return JSON only:
{
  "altText": "<concise alt text>",
  "confidence": 0.0,
  "suggestions": ["<optional short note>"]
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

			const sanitized = sanitizeAIOutput(result.text || "");
			const jsonMatch = sanitized.match(/\{[\s\S]*\}/);
			if (!jsonMatch) return apiError(res, 500, "Failed to parse AI response");
			const json = JSON.parse(jsonMatch[0]);
			const response = {
				altText: normalizeAltText(json.altText),
				confidence: Math.max(0, Math.min(1, Number(json.confidence) || 0.75)),
				suggestions: Array.isArray(json.suggestions)
					? json.suggestions.slice(0, 3).map((s: unknown) => String(s))
					: [],
			};
			if (!response.altText) return apiError(res, 500, "AI returned empty alt text");

			recordDirectAIEvalSnapshot({
				userId: user.id,
				surface: "ai_alt_text",
				actionType: "generate_alt_text",
				category: "accessibility",
				prompt,
				output: response,
				provider: "gemini",
				model: "gemini-2.0-flash",
				parameters: {
					platform,
					postType,
					contentType,
					imageHash: cacheHash,
				},
				passed: true,
				metadata: {
					cacheKey,
					route: "/api/ai/alt-text",
				},
			}).catch((error) => {
				logger.warn("[ai/alt-text] Eval snapshot failed", { error: String(error) });
			});

			try {
				await redis.set(cacheKey, JSON.stringify(response), { ex: 86400 });
			} catch (err) {
				logger.debug("[ai/alt-text] Redis cache write failed", { error: String(err) });
			}
			trackUsage(user.id, "ai/alt-text").catch(() => {});
			return apiSuccess(res, { ...response, cached: false });
		} catch (err) {
			logger.error("[ai/alt-text] Error", { error: String(err) });
			return apiError(res, 500, "Internal server error");
		}
	},
);
