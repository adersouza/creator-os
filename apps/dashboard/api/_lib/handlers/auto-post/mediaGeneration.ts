/**
 * Auto-Post Media Generation Helper
 *
 * Generates images for auto-poster queue items that need media.
 * Uses OpenAI DALL-E 3 or Flux via the same logic as the API route.
 * Best-effort, non-blocking — returns null on failure.
 */

import { logger } from "../../logger.js";
import type { Platform } from "../../platform.js";
import { withRetry } from "../../retryUtils.js";
import { detectPersonaName } from "./promptBuilder.js";
import type { VoiceProfile } from "./types.js";

/**
 * Generate an image for a post based on its content.
 *
 * @param content - The post text to generate an image for
 * @param userId - The user ID (for resolving API keys)
 * @param platform - Target platform (affects prompt styling)
 * @returns Image URL or null on failure
 */
export async function generateImageForPost(
	content: string,
	userId: string,
	platform: Platform,
	voiceProfile?: VoiceProfile | null,
): Promise<string | null> {
	try {
		// Build an image prompt from the post content
		const platformHint =
			platform === "instagram"
				? "Instagram-optimized, square format, scroll-stopping"
				: "eye-catching, modern social media";

		// Sanitize content to prevent prompt injection from adversarial content
		const sanitized = content
			.slice(0, 300)
			.replace(
				/ignore\s+(previous|above|all)\s+(instructions?|prompts?|rules?)/gi,
				"",
			)
			.replace(/instead\s+(generate|create|make|draw|show|output)/gi, "")
			.replace(/system\s*:?\s*prompt/gi, "")
			.replace(/\bdo\s+not\b.*?\b(follow|obey|listen)\b/gi, "")
			.replace(/[^\w\s.,!?;:'"()\-@#&%]/g, " ")
			.replace(/\s{2,}/g, " ")
			.trim();

		// Media Strategy 2026 Section 6: photographic language, not AI-community terms.
		// Include imperfection cues for authenticity. Specify camera/lens for realism.
		const imageSubject = subjectForVoiceProfile(voiceProfile);
		const imagePrompt = `Candid lifestyle photo of ${imageSubject}, ${platformHint}. Topic: "${sanitized || "casual lifestyle moment"}". Shot on Canon R5, 85mm f/1.4, natural window light, shallow depth of field. Slightly imperfect — natural skin texture, subtle motion blur on hands, not overly retouched. Warm muted tones. 4:5 vertical aspect ratio. No text overlays, no logos, no filters.`;

		// Try OpenAI first (user key or platform key)
		const openaiKey = await resolveOpenAIKey(userId);
		if (openaiKey) {
			const url = await generateDalle(openaiKey, imagePrompt);
			if (url) {
				logger.info("[mediaGeneration] Generated image via DALL-E", {
					userId,
					platform,
				});
				return url;
			}
		}

		// Try Flux as fallback (platform key only)
		const falKey = process.env.FAL_KEY;
		if (falKey) {
			const url = await generateFlux(falKey, imagePrompt);
			if (url) {
				logger.info("[mediaGeneration] Generated image via Flux", {
					userId,
					platform,
				});
				return url;
			}
		}

		logger.debug("[mediaGeneration] No image provider available", { userId });
		return null;
	} catch (err) {
		logger.error("[mediaGeneration] Failed to generate image", {
			userId,
			platform,
			error: err instanceof Error ? err.message : String(err),
		});
		return null;
	}
}

function subjectForVoiceProfile(voiceProfile?: VoiceProfile | null): string {
	const persona = detectPersonaName(voiceProfile?.voice_profile);
	if (persona === "larissa") {
		return "a college-age woman in a casual campus or bedroom lifestyle moment";
	}
	if (persona === "lola") {
		return "an athletic adult woman in a casual gym, gaming, or post-workout lifestyle moment";
	}
	if (persona === "stacey") {
		return "an adult woman in a casual creator setup with subtle anime, gaming, or internet-culture styling";
	}
	if (persona === "gfe") {
		return "an adult woman in a soft, intimate home lifestyle moment";
	}

	const voice = voiceProfile?.voice_profile?.trim();
	if (!voice) return "an adult creator in a candid lifestyle moment";
	return `an adult creator whose visual style matches this account voice: "${voice
		.replace(/["\n\r]/g, " ")
		.slice(0, 180)}"`;
}

/**
 * Check if the user has image generation capability configured.
 */
export async function hasImageGenerationCapability(
	userId: string,
): Promise<boolean> {
	// Check for platform Flux key
	if (process.env.FAL_KEY) return true;

	// Check for platform OpenAI key
	if (process.env.OPENAI_API_KEY) return true;

	// Check if user has OpenAI configured
	const openaiKey = await resolveOpenAIKey(userId);
	return !!openaiKey;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

async function resolveOpenAIKey(userId: string): Promise<string | null> {
	try {
		const { getSupabase } = await import("../../supabase.js");
		const { data } = await getSupabase()
			.from("ai_config")
			.select("provider, api_key")
			.eq("user_id", userId)
			.maybeSingle();

		if (data?.provider === "openai" && data.api_key) {
			return data.api_key;
		}
	} catch (err) {
		logger.debug("[mediaGeneration] Could not resolve user AI key", {
			error: String(err),
		});
	}

	return process.env.OPENAI_API_KEY || null;
}

async function generateDalle(
	apiKey: string,
	prompt: string,
): Promise<string | null> {
	try {
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
					size: "1024x1024",
					style: "vivid",
					response_format: "url",
				}),
			}),
		);

		if (!resp.ok) {
			logger.warn("[mediaGeneration] DALL-E returned non-OK", {
				status: resp.status,
			});
			return null;
		}

		const data = await resp.json();
		return data.data?.[0]?.url || null;
	} catch (err) {
		logger.warn("[mediaGeneration] DALL-E fetch failed", {
			error: String(err),
		});
		return null;
	}
}

async function generateFlux(
	apiKey: string,
	prompt: string,
): Promise<string | null> {
	try {
		const resp = await withRetry(() =>
			fetch("https://fal.run/fal-ai/flux/schnell", {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Key ${apiKey}`,
				},
				body: JSON.stringify({
					prompt,
					image_size: { width: 1024, height: 1024 },
					num_images: 1,
				}),
			}),
		);

		if (!resp.ok) {
			logger.warn("[mediaGeneration] Flux returned non-OK", {
				status: resp.status,
			});
			return null;
		}

		const data = await resp.json();
		return data.images?.[0]?.url || null;
	} catch (err) {
		logger.warn("[mediaGeneration] Flux fetch failed", {
			error: String(err),
		});
		return null;
	}
}
