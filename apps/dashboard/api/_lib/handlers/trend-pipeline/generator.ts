/**
 * Trend Post Generator
 *
 * Generates a Threads post from a trending topic using Gemini with
 * voice profile injection. Mirrors the voice/style pattern from
 * contentSelection.ts for consistency.
 */

import { withGeminiRetry } from "../../geminiRetry.js";
import { recordDirectAIEvalSnapshot } from "../../aiEvalSnapshots.js";
import { trackGeminiResponseCost } from "../../aiUsageTracking.js";
import { logger } from "../../logger.js";
import { FORMAT_DESCRIPTIONS } from "./formatWeights.js";
import type {
	ExtractedStyle,
	FilteredTrend,
	TrendFormat,
	VoiceProfile,
} from "./types.js";

export async function generateTrendPost(params: {
	trend: FilteredTrend;
	format: TrendFormat;
	voiceProfile: VoiceProfile | null;
	extractedStyle: ExtractedStyle | null;
	focusTopics?: string[] | undefined;
	userAIConfig: {
		provider: string;
		apiKey: string;
		baseUrl?: string | undefined;
		model?: string | undefined;
		source?: "user" | "env_fallback" | undefined;
	};
	userId?: string | undefined;
}): Promise<string | null> {
	try {
		const { trend, format, voiceProfile, extractedStyle, userAIConfig } =
			params;
		const geminiConfig = resolveGeminiConfig(userAIConfig);
		if (!geminiConfig) {
			logger.warn("[trend-scanner] Gemini key unavailable for trend generation", {
				provider: userAIConfig.provider,
				model: userAIConfig.model,
				source: userAIConfig.source,
			});
			return null;
		}

		// Build voice section (matches contentSelection.ts pattern exactly)
		const voiceParts: string[] = [];
		if (voiceProfile?.voice_profile) {
			voiceParts.push(`WRITING PERSONALITY:\n${voiceProfile.voice_profile}`);
		}
		if (voiceProfile?.focus_topics && voiceProfile.focus_topics.length > 0) {
			voiceParts.push(
				`FOCUS TOPICS (lean into these): ${voiceProfile.focus_topics.join(", ")}`,
			);
		}
		if (voiceProfile?.avoid_topics && voiceProfile.avoid_topics.length > 0) {
			voiceParts.push(
				`AVOID TOPICS (never touch these): ${voiceProfile.avoid_topics.join(", ")}`,
			);
		}
		if (voiceProfile?.avoid_words && voiceProfile.avoid_words.length > 0) {
			voiceParts.push(
				`BANNED WORDS (never use): ${voiceProfile.avoid_words.join(", ")}`,
			);
		}
		if (voiceProfile?.emoji_usage) {
			voiceParts.push(`EMOJI USAGE: ${voiceProfile.emoji_usage}`);
		}
		if (voiceProfile?.cta_style && voiceProfile.cta_style !== "none") {
			voiceParts.push(`CTA STYLE: ${voiceProfile.cta_style}`);
		}

		const voiceSection =
			voiceParts.length > 0
				? `\n== YOUR CLIENT'S VOICE (match this EXACTLY) ==\n${voiceParts.join("\n")}\n`
				: "";

		// Build extracted style DNA section (matches contentSelection.ts pattern exactly)
		const styleParts: string[] = [];
		if (extractedStyle?.tone?.vibe)
			styleParts.push(`Tone/vibe: ${extractedStyle.tone.vibe}`);
		if (extractedStyle?.tone?.energy)
			styleParts.push(`Energy level: ${extractedStyle.tone.energy}`);
		if (
			extractedStyle?.hooks?.patterns &&
			extractedStyle.hooks.patterns.length > 0
		) {
			styleParts.push(
				`Hook patterns to mimic: ${extractedStyle.hooks.patterns.join(" | ")}`,
			);
		}
		if (
			extractedStyle?.vocabulary?.signature_words &&
			extractedStyle.vocabulary.signature_words.length > 0
		) {
			styleParts.push(
				`Signature words/phrases to naturally weave in: ${extractedStyle.vocabulary.signature_words.join(", ")}`,
			);
		}
		if (extractedStyle?.emoji_usage?.frequency)
			styleParts.push(
				`Emoji frequency: ${extractedStyle.emoji_usage.frequency}`,
			);
		if (extractedStyle?.emoji_usage?.placement)
			styleParts.push(
				`Emoji placement: ${extractedStyle.emoji_usage.placement}`,
			);
		if (
			extractedStyle?.emoji_usage?.favorites &&
			extractedStyle.emoji_usage.favorites.length > 0
		) {
			styleParts.push(
				`Preferred emojis: ${extractedStyle.emoji_usage.favorites.join(" ")}`,
			);
		}
		if (extractedStyle?.length?.typical_chars)
			styleParts.push(
				`Typical post length: ${extractedStyle.length.typical_chars} chars`,
			);
		if (extractedStyle?.length?.preference)
			styleParts.push(`Length preference: ${extractedStyle.length.preference}`);
		if (
			extractedStyle?.punctuation?.quirks &&
			extractedStyle.punctuation.quirks.length > 0
		) {
			styleParts.push(
				`Punctuation quirks: ${extractedStyle.punctuation.quirks.join(", ")}`,
			);
		}

		const styleExtractSection =
			styleParts.length > 0
				? `\n== WRITING STYLE DNA (internalize these patterns) ==\n${styleParts.map((p) => `- ${p}`).join("\n")}\n`
				: "";

		// Assemble full prompt
		const prompt = [
			"You are a social media content creator. Write a single Threads post about a trending topic. The post must sound natural and authentic -- not like AI wrote it. Return ONLY the post text, no quotes, no labels, no explanation.",
			"",
			`FORMAT: ${FORMAT_DESCRIPTIONS[format]}`,
			voiceSection,
			styleExtractSection,
			`TRENDING TOPIC: ${trend.topic}`,
			`CONTEXT: ${trend.context}`,
			"",
			"Do NOT include URLs or source links. Do NOT mention where you found this trend.",
			"",
			"Keep it under 500 characters. Threads posts should be punchy and scannable.",
		]
			.join("\n")
			.trim();

		// Call Gemini via withGeminiRetry
		const { GoogleGenAI } = await import("@google/genai");
		const client = new GoogleGenAI({ apiKey: geminiConfig.apiKey });
		const model = geminiConfig.model;

		const response = await withGeminiRetry(() =>
			client.models.generateContent({
				model,
				contents: prompt,
				config: { thinkingConfig: { thinkingBudget: 0 } },
			}),
		);
		trackGeminiResponseCost(
			params.userId ?? "platform",
			response,
			model,
			"trend_pipeline_generator",
			geminiConfig.source,
		);

		const text = response.text?.trim();
		if (!text) {
			logger.warn("Gemini returned empty response for trend", {
				topic: trend.topic,
				format,
			});
			return null;
		}

		recordDirectAIEvalSnapshot({
			userId: params.userId ?? "platform",
			surface: "trend_pipeline_generator",
			actionType: "generate_trend_post",
			category: "content_generation",
			prompt,
			output: text,
			provider: "gemini",
			model,
			parameters: {
				format,
				keySource: geminiConfig.source ?? null,
				hasVoiceProfile: Boolean(params.voiceProfile),
				hasExtractedStyle: Boolean(params.extractedStyle),
			},
			passed: true,
			metadata: {
				topic: trend.topic,
				route: "api/_lib/handlers/trend-pipeline/generator.generateTrendPost",
			},
		}).catch((error) => {
			logger.warn("Trend pipeline eval snapshot failed", { error: String(error) });
		});

		return text;
	} catch (err) {
		logger.error("Failed to generate trend post", {
			topic: params.trend.topic,
			format: params.format,
			error: String(err),
		});
		return null;
	}
}

function resolveGeminiConfig(userAIConfig: {
	provider: string;
	apiKey: string;
	model?: string | undefined;
	source?: "user" | "env_fallback" | undefined;
}): { apiKey: string; model: string; source?: "user" | "env_fallback" } | null {
	if (userAIConfig.provider === "gemini") {
		return {
			apiKey: userAIConfig.apiKey,
			model: userAIConfig.model || "gemini-2.5-flash",
			...(userAIConfig.source && { source: userAIConfig.source }),
		};
	}

	if (process.env.GEMINI_API_KEY) {
		return {
			apiKey: process.env.GEMINI_API_KEY,
			model: "gemini-2.5-flash",
			source: "env_fallback",
		};
	}

	return null;
}
