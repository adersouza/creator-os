/**
 * Media Vision Analysis
 *
 * Analyzes images using Gemini Vision to generate descriptions and tags.
 * Used to ensure captions match media content (no gym pic with turtle caption).
 *
 * Two modes:
 * 1. analyzeMediaItem() — analyze a single media URL, return description + tags
 * 2. backfillMediaDescriptions() — batch-analyze all untagged media in the library
 */

import { GoogleGenAI } from "@google/genai";
import { recordDirectAIEvalSnapshot } from "./aiEvalSnapshots.js";
import { logger } from "./logger.js";
import { fetchPublicUrlWithRedirects } from "./outboundUrlSecurity.js";
import { sanitizeAIOutput } from "./promptUtils.js";
import { getRedis } from "./redis.js";
import { getSupabase } from "./supabase.js";

// biome-ignore lint/suspicious/noExplicitAny: new columns not in generated types
const db = (): any => getSupabase();

let geminiClient: GoogleGenAI | null = null;

function getClient(): GoogleGenAI | null {
	const key = process.env.GOOGLE_AI_API_KEY || process.env.GEMINI_API_KEY;
	if (!key) return null;
	if (!geminiClient) {
		geminiClient = new GoogleGenAI({ apiKey: key });
	}
	return geminiClient;
}

export interface MediaVisionResult {
	description: string; // e.g. "woman in gym clothes doing deadlifts, high contrast lighting"
	tags: string[]; // e.g. ["gym", "fitness", "deadlift", "athletic", "selfie"]
	contentType: string; // e.g. "gym_selfie", "food", "landscape", "portrait"
	mood: string; // e.g. "confident", "playful", "moody"
	captionHint: string; // e.g. "fitness motivation or gym humor"
}

/**
 * Analyze a single image URL with Gemini Vision.
 * Returns a description, tags, content type, mood, and caption hint.
 * Results are cached in Redis for 30 days (media doesn't change).
 */
export async function analyzeMediaItem(
	imageUrl: string,
	mimeType?: string,
): Promise<MediaVisionResult | null> {
	const client = getClient();
	if (!client) {
		logger.warn("[mediaVision] No Gemini API key available");
		return null;
	}

	// Check Redis cache first
	const redis = getRedis();
	const { createHash } = await import("node:crypto");
	const cacheKey = `media-vision:${createHash("sha256").update(imageUrl).digest("hex").slice(0, 32)}`;
	if (redis) {
		try {
			const cached = await redis.get(cacheKey);
			if (cached) return JSON.parse(cached as string);
		} catch {
			// Non-critical
		}
	}

	try {
		// Fetch image as base64
		const imgResp = await fetchPublicUrlWithRedirects(
			imageUrl,
			"media-vision",
			{
				signal: AbortSignal.timeout(15000),
			},
		);
		if (!imgResp?.ok) {
			logger.warn("[mediaVision] Failed to fetch image", {
				url: imageUrl.slice(0, 80),
				status: imgResp?.status,
			});
			return null;
		}

		const contentType =
			mimeType || imgResp.headers.get("content-type") || "image/jpeg";
		const buffer = await imgResp.arrayBuffer();
		const base64 = Buffer.from(buffer).toString("base64");

		const prompt = `Analyze this image for social media posting. Be specific about what you see.

Return JSON only:
{
  "description": "<1-2 sentence description of what's in the image — be specific about people, setting, activity, clothing>",
  "tags": ["<5-8 specific tags describing the image content>"],
  "content_type": "<one of: gym_selfie, gym_workout, mirror_selfie, portrait, outfit, food, landscape, meme, text_graphic, lifestyle, pet, other>",
  "mood": "<one of: confident, playful, moody, sexy, casual, energetic, funny, serious, cute, mysterious>",
  "caption_hint": "<what kind of caption would match this image — e.g. 'fitness motivation', 'thirst trap humor', 'late night vibes'>"
}`;

		// Bail before the API call if the platform daily spend cap is hit.
		// Vision calls are roughly 10x text-call cost, so this gate matters
		// most here — a cache-miss batch of 20 in backfillMediaDescriptions
		// would otherwise burn unattributed.
		const { checkDailySpendLimit, trackAICost } = await import(
			"./aiCostTracker.js"
		);
		const { allowed } = await checkDailySpendLimit();
		if (!allowed) {
			logger.warn(
				"[mediaVision] Vision call skipped — daily spend limit reached",
			);
			return null;
		}

		const modelId = "gemini-2.0-flash";
		const result = await client.models.generateContent({
			model: modelId,
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

		// Attribute platform-key spend.
		const usage = (
			result as {
				usageMetadata?: {
                    					promptTokenCount?: number | undefined;
                    					candidatesTokenCount?: number | undefined;
                    				} | undefined;
			}
		).usageMetadata;
		if (usage) {
			trackAICost(
				"platform",
				usage.promptTokenCount ?? 0,
				usage.candidatesTokenCount ?? 0,
				modelId,
				"media_vision",
				"env_fallback",
			).catch(() => {});
		}

		const text = result.text || "";
		const sanitized = sanitizeAIOutput(text);
		const jsonMatch = sanitized.match(/\{[\s\S]*\}/);
		if (!jsonMatch) {
			logger.warn("[mediaVision] Failed to parse Gemini response", {
				url: imageUrl.slice(0, 80),
			});
			return null;
		}

		const parsed = JSON.parse(jsonMatch[0]);
		const visionResult: MediaVisionResult = {
			description: parsed.description || "",
			tags: Array.isArray(parsed.tags) ? parsed.tags : [],
			contentType: parsed.content_type || "other",
			mood: parsed.mood || "casual",
			captionHint: parsed.caption_hint || "",
		};

		recordDirectAIEvalSnapshot({
			userId: "platform",
			surface: "media_vision",
			actionType: "analyze_media_item",
			category: "media_quality",
			prompt,
			output: visionResult,
			provider: "gemini",
			model: modelId,
			parameters: {
				contentType,
				cacheKey,
			},
			passed: true,
			metadata: {
				route: "api/_lib/mediaVision.analyzeMediaItem",
			},
		}).catch((error) => {
			logger.warn("[mediaVision] Eval snapshot failed", { error: String(error) });
		});

		// Cache for 30 days (media doesn't change)
		if (redis) {
			try {
				await redis.set(cacheKey, JSON.stringify(visionResult), {
					ex: 2592000,
				});
			} catch {
				// Non-critical
			}
		}

		return visionResult;
	} catch (err) {
		logger.warn("[mediaVision] Analysis failed", {
			url: imageUrl.slice(0, 80),
			error: err instanceof Error ? err.message : String(err),
		});
		return null;
	}
}

/**
 * Backfill all untagged images in the media library.
 * Processes in batches to avoid timeout. Returns count of analyzed items.
 * Call from a cron job or API endpoint.
 */
export async function backfillMediaDescriptions(
	batchSize = 20,
): Promise<{ analyzed: number; skipped: number; errors: number }> {
	const stats = { analyzed: 0, skipped: 0, errors: 0 };

	// Fetch untagged images (skip videos for now — would need thumbnail extraction)
	const { data: untagged, error } = await db()
		.from("media")
		.select("id, url, storage_url, mime_type")
		.is("ai_description", null)
		.like("mime_type", "image%")
		.order("created_at", { ascending: false })
		.limit(batchSize);

	if (error || !untagged?.length) {
		logger.info("[mediaVision] No untagged images to process", {
			error: error?.message,
		});
		return stats;
	}

	logger.info(`[mediaVision] Processing ${untagged.length} untagged images`);

	for (const media of untagged as {
		id: string;
		url: string | null;
		storage_url: string | null;
		mime_type: string | null;
	}[]) {
		const imageUrl = media.url || media.storage_url;
		if (!imageUrl) {
			stats.skipped++;
			continue;
		}

		const result = await analyzeMediaItem(
			imageUrl,
			media.mime_type || undefined,
		);
		if (!result) {
			stats.errors++;
			// Mark as processed even on failure to avoid retrying bad URLs forever
			await db()
				.from("media")
				.update({
					ai_description: "_analysis_failed",
					updated_at: new Date().toISOString(),
				})
				.eq("id", media.id);
			continue;
		}

		// Store results
		await db()
			.from("media")
			.update({
				ai_description: result.description,
				ai_tags: {
					tags: result.tags,
					contentType: result.contentType,
					mood: result.mood,
					captionHint: result.captionHint,
				},
				tags: result.tags,
				updated_at: new Date().toISOString(),
			})
			.eq("id", media.id);

		stats.analyzed++;

		// Small delay between API calls to avoid rate limiting
		await new Promise((resolve) => setTimeout(resolve, 500));
	}

	logger.info("[mediaVision] Backfill complete", stats);
	return stats;
}
