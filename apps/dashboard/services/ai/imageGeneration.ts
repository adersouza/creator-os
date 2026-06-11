/**
 * AI Image Generation Client
 *
 * Calls the server-side /api/ai/generate-image endpoint.
 * Keeps API keys off the client.
 */

import { logger } from "@/utils/logger";
import { supabase } from "../supabase.js";

export type ImageProvider = "openai" | "flux";
export type ImageStyle = "vivid" | "natural";
export type ImageSize = "1024x1024" | "1792x1024" | "1024x1792";
export type FluxQuality = "fast" | "quality";

export interface GenerateImageOptions {
	prompt: string;
	provider?: ImageProvider | undefined;
	style?: ImageStyle | undefined;
	size?: ImageSize | undefined;
	quality?: FluxQuality | undefined;
}

export interface GenerateImageResult {
	url: string;
	revised_prompt?: string | undefined;
	provider: ImageProvider;
}

const API_BASE = import.meta.env?.VITE_API_URL || "";

/**
 * Generate an image via the server-side proxy.
 * Returns the generated image URL and metadata.
 */
export async function generateImage(
	options: GenerateImageOptions,
): Promise<GenerateImageResult> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session?.access_token) {
		throw new Error("Not authenticated. Please sign in.");
	}

	const controller = new AbortController();
	const timeoutId = setTimeout(() => controller.abort(), 60_000); // 60s for image gen

	try {
		const res = await fetch(`${API_BASE}/api/ai/generate-image`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify(options),
			signal: controller.signal,
		});

		if (res.status === 429) {
			throw new Error(
				"Daily image generation limit reached (10/day). Try again tomorrow.",
			);
		}

		const data = await res.json();

		if (!res.ok || !data.success) {
			throw new Error(data.error || "Image generation failed");
		}

		return {
			url: data.url,
			revised_prompt: data.revised_prompt,
			provider: data.provider || "openai",
		};
	} catch (err: unknown) {
		if (err instanceof Error && err.name === "AbortError") {
			throw new Error("Image generation timed out after 60 seconds");
		}
		if (err instanceof Error) throw err;
		logger.error("[imageGeneration] Request failed:", err);
		throw new Error("Failed to generate image");
	} finally {
		clearTimeout(timeoutId);
	}
}
