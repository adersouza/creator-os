// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * AI Image Generation — POST /api/ai/generate-image
 *
 * Generates images via OpenAI DALL-E 3 or Flux (fal.ai).
 * Requires auth. Rate limited to 10 generations/day per user.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { fetchPublicUrlWithRedirects } from "../../outboundUrlSecurity.js";
import { withRetry } from "../../retryUtils.js";
import { getUserTier, requireMinTier } from "../../tierGate.js";

// ---------------------------------------------------------------------------
// Rate limit: tier-aware daily image generation limits via Redis
// Free: 5/day, Pro: 15/day, Empire: 50/day
// ---------------------------------------------------------------------------

const IMAGE_TIER_LIMITS: Record<string, number> = {
	free: 5,
	pro: 15,
	agency: 30,
	empire: 50,
};

// Lua script: atomic check-and-increment to prevent TOCTOU race conditions.
// KEYS[1] = rate limit key, ARGV[1] = limit, ARGV[2] = TTL seconds
// Returns [allowed (0|1), current count after operation]
const ATOMIC_RATE_LIMIT_SCRIPT = `
local count = tonumber(redis.call('GET', KEYS[1]) or '0')
if count >= tonumber(ARGV[1]) then
  return {0, count}
end
local newCount = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
return {1, newCount}
`;

async function checkDailyImageLimit(
	userId: string,
): Promise<{ allowed: boolean; remaining: number; limit: number }> {
	let tier: string;
	try {
		tier = await getUserTier(userId);
	} catch {
		tier = "free";
	}
	const limit = IMAGE_TIER_LIMITS[tier] || IMAGE_TIER_LIMITS.free;

	try {
		const { getRedis } = await import("../../redis.js");
		const redis = getRedis();
		const key = `ai-image-gen:${userId}`;

		// Atomic: check + increment in a single Redis EVAL — no race condition
		const result = (await redis.eval(
			ATOMIC_RATE_LIMIT_SCRIPT,
			[key],
			[String(limit), "86400"],
		)) as [number, number];

		const [allowed, count] = result;
		return {
			allowed: allowed === 1,
			remaining: Math.max(0, limit! - count),
			limit: limit!,
		};
	} catch (err) {
		logger.error("[generate-image] Rate limit check failed", {
			userId,
			error: String(err),
		});
		return { allowed: false, remaining: 0, limit: limit! };
	}
}

// ---------------------------------------------------------------------------
// Provider: OpenAI DALL-E 3
// ---------------------------------------------------------------------------

async function generateWithDalle(
	apiKey: string,
	prompt: string,
	size: string,
	style: string,
): Promise<{ url: string; revised_prompt?: string | undefined }> {
	const validSizes = ["1024x1024", "1792x1024", "1024x1792"];
	const validatedSize = validSizes.includes(size) ? size : "1024x1024";
	const validStyles = ["vivid", "natural"];
	const validatedStyle = validStyles.includes(style) ? style : "vivid";

	const resp = await withRetry(() =>
		fetch("https://api.openai.com/v1/images/generations", {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${apiKey}`,
			},
			body: JSON.stringify({
				model: "dall-e-3",
				prompt,
				n: 1,
				size: validatedSize,
				style: validatedStyle,
				response_format: "url",
			}),
		}),
	);

	if (!resp.ok) {
		const errorBody = await resp.text();
		logger.error("[generate-image] DALL-E error", {
			status: resp.status,
			body: errorBody.slice(0, 500),
		});
		throw new Error(`DALL-E API error: ${resp.status}`);
	}

	const data = await resp.json();
	const image = data.data?.[0];
	if (!image?.url) {
		throw new Error("No image URL in DALL-E response");
	}

	return {
		url: image.url,
		revised_prompt: image.revised_prompt,
	};
}

// ---------------------------------------------------------------------------
// Provider: Flux via fal.ai
// ---------------------------------------------------------------------------

async function generateWithFlux(
	apiKey: string,
	prompt: string,
	quality: "fast" | "quality",
	size: string,
): Promise<{ url: string }> {
	const model =
		quality === "quality" ? "fal-ai/flux-pro/v1.1" : "fal-ai/flux/schnell";

	// Map size strings to fal.ai image_size format
	const sizeMap: Record<string, { width: number; height: number }> = {
		"1024x1024": { width: 1024, height: 1024 },
		"1792x1024": { width: 1792, height: 1024 },
		"1024x1792": { width: 1024, height: 1792 },
	};
	const imageSize = sizeMap[size] || sizeMap["1024x1024"];

	const resp = await withRetry(() =>
		fetch(`https://fal.run/${model}`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Key ${apiKey}`,
			},
			body: JSON.stringify({
				prompt,
				image_size: imageSize,
				num_images: 1,
			}),
		}),
	);

	if (!resp.ok) {
		const errorBody = await resp.text();
		logger.error("[generate-image] Flux error", {
			status: resp.status,
			body: errorBody.slice(0, 500),
		});
		throw new Error(`Flux API error: ${resp.status}`);
	}

	const data = await resp.json();
	const imageUrl = data.images?.[0]?.url;
	if (!imageUrl) {
		throw new Error("No image URL in Flux response");
	}

	return { url: imageUrl };
}

// ---------------------------------------------------------------------------
// Handler
// ---------------------------------------------------------------------------

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") {
			return apiError(res, 405, "Method not allowed");
		}

		// Tier gate — Image generation requires Pro or higher
		if (!(await requireMinTier(user.id, "pro", res))) return;

		const { prompt, provider, style, size, quality } = req.body || {};

		if (!prompt || typeof prompt !== "string") {
			return apiError(res, 400, "prompt is required and must be a string");
		}

		if (prompt.length > 4000) {
			return apiError(res, 400, "Prompt must be under 4000 characters");
		}

		// Rate limit check — tier-aware daily limits
		const rl = await checkDailyImageLimit(user.id);
		res.setHeader("X-RateLimit-Limit", String(rl.limit));
		res.setHeader("X-RateLimit-Remaining", String(rl.remaining));
		if (!rl.allowed) {
			return apiError(
				res,
				429,
				`Daily image generation limit reached (${rl.limit}/day for your plan). Try again tomorrow.`,
				{ code: "RATE_LIMITED" },
			);
		}

		const selectedProvider = provider === "flux" ? "flux" : "openai";

		try {
			let resultUrl: string;
			let revisedPrompt: string | undefined;

			if (selectedProvider === "flux") {
				// Use platform-level FAL_KEY
				const falKey = process.env.FAL_KEY;
				if (!falKey) {
					return apiError(
						res,
						503,
						"Flux image generation is not configured. Use OpenAI instead.",
						{ code: "NO_FAL_KEY" },
					);
				}

				const result = await generateWithFlux(
					falKey,
					prompt,
					quality === "quality" ? "quality" : "fast",
					size || "1024x1024",
				);
				resultUrl = result.url;

				logger.info("[generate-image] Flux generation complete", {
					userId: user.id,
					quality: quality || "fast",
				});
			} else {
				// OpenAI DALL-E 3
				let openaiKey: string | null = null;

				const { getSupabase } = await import("../../supabase.js");
				const { data: aiConfig } = await getSupabase()
					.from("ai_config")
					.select("provider, api_key")
					.eq("user_id", user.id)
					.maybeSingle();

				if (aiConfig?.provider === "openai" && aiConfig.api_key) {
					// Decrypt stored key; fallback to raw value for legacy plaintext keys
					try {
						const { decrypt } = await import("../../encryption.js");
						openaiKey = decrypt(aiConfig.api_key);
					} catch {
						openaiKey = aiConfig.api_key;
					}
				}

				if (!openaiKey) {
					openaiKey = process.env.OPENAI_API_KEY || null;
				}

				if (!openaiKey) {
					return apiError(
						res,
						503,
						"No OpenAI API key found. Configure OpenAI as your AI provider in Settings, or use Flux.",
						{ code: "NO_OPENAI_KEY" },
					);
				}

				const result = await generateWithDalle(
					openaiKey,
					prompt,
					size || "1024x1024",
					style || "vivid",
				);
				resultUrl = result.url;
				revisedPrompt = result.revised_prompt;

				logger.info("[generate-image] DALL-E generation complete", {
					userId: user.id,
				});
			}

			// ── PERSIST TO SUPABASE STORAGE ──
			// Standard provider URLs expire quickly. We must upload to our own bucket.
			const { getSupabase } = await import("../../supabase.js");
			const supabase = getSupabase();

			// 1. Fetch the image data
			const imageResp = await fetchPublicUrlWithRedirects(
				resultUrl,
				"ai-generated-image",
				{ signal: AbortSignal.timeout(30_000) },
			);
			if (!imageResp?.ok)
				throw new Error("Failed to fetch generated image for persistence");
			const blob = await imageResp.blob();
			const buffer = Buffer.from(await blob.arrayBuffer());

			// 2. Upload to user's media folder
			const filename = `ai-gen-${Date.now()}-${Math.random().toString(36).slice(2, 7)}.png`;
			const storagePath = `ai-generations/${user.id}/${filename}`;

			const { error: uploadError } = await supabase.storage
				.from("media")
				.upload(storagePath, buffer, {
					contentType: "image/png",
					upsert: true,
				});

			if (uploadError) {
				logger.error("[generate-image] Storage upload failed", {
					error: uploadError,
				});
				// If upload fails, fallback to the original provider URL so we don't block the user
				return apiSuccess(res, {
					url: resultUrl,
					revised_prompt: revisedPrompt,
					provider: selectedProvider,
					is_persistent: false,
				});
			}

			// 3. Get Public URL
			const {
				data: { publicUrl },
			} = supabase.storage.from("media").getPublicUrl(storagePath);

			return apiSuccess(res, {
				url: publicUrl,
				revised_prompt: revisedPrompt,
				provider: selectedProvider,
				is_persistent: true,
			});
		} catch (err: unknown) {
			logger.error("[generate-image] Generation failed", {
				userId: user.id,
				provider: selectedProvider,
				error: err instanceof Error ? err.message : String(err),
			});
			return apiError(res, 502, "Image generation failed. Please try again.");
		}
	},
);
