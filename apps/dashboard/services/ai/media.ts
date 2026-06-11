// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
import type { Platform } from "../../src/types/platform.js";
import { getProviderInfo } from "../../types/aiProvider.js";
import { logger } from "@/utils/logger";
import {
	generateContent,
	getAIConfig,
	getGeminiClient,
	parseAIJson,
} from "./core.js";
import type { VoiceProfile } from "./ideas.js";

export interface MediaAdaptResult {
	concept: string;
	captionIdeas: string[];
	suggestedMediaTypes: string[];
	hooks: string[];
}

export const adaptMediaIdea = async (
	originalContent: string,
	mediaType: "IMAGE" | "VIDEO" | "CAROUSEL",
	mediaDescription?: string,
): Promise<MediaAdaptResult | null> => {
	const prompt = `You are a creative content strategist. Analyze this successful ${mediaType.toLowerCase()} post and help create an adapted version:

Original Caption: "${originalContent}"
Media Type: ${mediaType}
${mediaDescription ? `Media Description: ${mediaDescription}` : ""}

Provide:
1. A brief description of the core concept/idea that made this post successful
2. 3 unique caption ideas that capture the same energy but with original wording
3. Suggested media types/ideas that would work well with these captions
4. 3 powerful hook alternatives to start each caption

Return ONLY valid JSON in this exact format:
{
  "concept": "Brief description of the winning concept (max 100 chars)",
  "captionIdeas": [
    "First unique caption idea under 500 chars",
    "Second caption with different angle",
    "Third creative variation"
  ],
  "suggestedMediaTypes": ["selfie", "screenshot", "behind-the-scenes"],
  "hooks": [
    "First attention-grabbing hook",
    "Second scroll-stopping opener",
    "Third curiosity-inducing start"
  ]
}`;

	try {
		const response = await generateContent(prompt);

		// Parse JSON from response
		let jsonStr = response;
		if (response.includes("```json")) {
			jsonStr = response.split("```json")[1]!.split("```")[0]!.trim();
		} else if (response.includes("```")) {
			jsonStr = response.split("```")[1]!.split("```")[0]!.trim();
		}

		return JSON.parse(jsonStr) as MediaAdaptResult;
	} catch (error) {
		logger.error("Media adapt parsing error:", error);
		return null;
	}
};

/**
 * Generate batch drafts from multiple source posts
 * Takes inspiration from several posts and generates unique adapted drafts
 */

export const generateCaptionFromImage = async (
	imageBase64: string,
	platform: Platform,
	tone?: string,
	voiceProfile?: VoiceProfile,
	accountHandle?: string,
): Promise<{ captions: string[]; hashtags?: string[] | undefined }> => {
	const config = await getAIConfig();
	if (!config?.apiKey) {
		throw new Error("No AI provider configured. Add your API key in Settings.");
	}

	const toneGuide = tone ? `Tone: ${tone}.` : "Tone: casual and authentic.";
	const voiceGuide = voiceProfile?.voice_profile
		? `Writing style: ${voiceProfile.voice_profile}.`
		: "";
	const handleGuide = accountHandle ? `Account: @${accountHandle}.` : "";
	const platformGuide =
		platform === "instagram"
			? "For Instagram: use richer descriptions, include a call-to-action, and suggest 10-15 relevant hashtags."
			: "For Threads: keep it conversational, max 500 characters, no hashtags.";

	const systemPrompt = `You are a social media content expert. Generate exactly 3 engaging ${platform} captions for the image provided. ${toneGuide} ${voiceGuide} ${handleGuide} ${platformGuide}

Return ONLY valid JSON in this format:
{"captions":["caption1","caption2","caption3"]${platform === "instagram" ? ',"hashtags":["tag1","tag2"]' : ""}}`;

	const providerInfo = getProviderInfo(config.provider);
	const model = config.model || providerInfo.defaultModel;

	// Strip data URL prefix if present
	const base64Data = imageBase64.includes(",")
		? (imageBase64.split(",")[1] ?? imageBase64)
		: imageBase64;
	const mimeType = imageBase64.startsWith("data:image/png")
		? "image/png"
		: "image/jpeg";

	try {
		let responseText: string;

		switch (config.provider) {
			case "gemini": {
				const client = getGeminiClient(config.apiKey);
				if (!client) throw new Error("Failed to initialize Gemini client.");
				const result = await client.models.generateContent({
					model: model.includes("flash") ? model : "gemini-2.0-flash",
						contents: [
							{ text: systemPrompt },
							{ inlineData: { mimeType, data: base64Data } },
						],
				});
				responseText = result.text || "";
				break;
			}

			case "openai": {
				const visionModel = model.includes("gpt-4") ? model : "gpt-4o-mini";
				const resp = await fetch("https://api.openai.com/v1/chat/completions", {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						Authorization: `Bearer ${config.apiKey}`,
					},
					body: JSON.stringify({
						model: visionModel,
						messages: [
							{ role: "system", content: systemPrompt },
							{
								role: "user",
								content: [
									{ type: "text", text: "Generate captions for this image:" },
									{
										type: "image_url",
										image_url: { url: `data:${mimeType};base64,${base64Data}` },
									},
								],
							},
						],
						max_tokens: 1024,
						temperature: 0.8,
					}),
				});
				if (!resp.ok) throw new Error(`OpenAI API error: ${resp.status}`);
				const data = await resp.json();
				responseText = data.choices?.[0]?.message?.content || "";
				break;
			}

			case "anthropic": {
				const resp = await fetch("https://api.anthropic.com/v1/messages", {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						"x-api-key": config.apiKey,
						"anthropic-version": "2023-06-01",
						"anthropic-dangerous-direct-browser-access": "true",
					},
					body: JSON.stringify({
						model: model.includes("claude")
							? model
							: "claude-sonnet-4-5-20250929",
						max_tokens: 1024,
						system: systemPrompt,
						messages: [
							{
								role: "user",
								content: [
									{
										type: "image",
										source: {
											type: "base64",
											media_type: mimeType,
											data: base64Data,
										},
									},
									{ type: "text", text: "Generate captions for this image." },
								],
							},
						],
					}),
				});
				if (!resp.ok) throw new Error(`Anthropic API error: ${resp.status}`);
				const data = await resp.json();
				responseText = data.content?.[0]?.text || "";
				break;
			}

			default:
				// Fallback: send image description request without vision
				responseText = await generateContent(
					`${systemPrompt}\n\n[User uploaded an image but your provider doesn't support vision. Generate 3 generic engaging captions for a social media image post.]`,
				);
		}

		// Parse JSON response
		const parsed = parseAIJson<{ captions: string[]; hashtags?: string[] | undefined }>(
			responseText,
		);
		if (
			parsed &&
			Array.isArray(parsed.captions) &&
			parsed.captions.length > 0
		) {
			return parsed;
		}

		// Fallback: try to split by numbered lines
		const lines = responseText
			.split(/\n/)
			.map((l) => l.replace(/^\d+[.)]\s*/, "").trim())
			.filter((l) => l.length > 10);
		return { captions: lines.slice(0, 3) };
	} catch (error: unknown) {
		logger.error("[aiService] Image caption error:", error);
		throw new Error(
			error instanceof Error
				? error.message
				: "Failed to generate captions from image.",
		);
	}
};

/**
 * Identify evergreen posts — high-performing content suitable for reposting.
 * Runs purely on the client side using engagement metrics.
 */
