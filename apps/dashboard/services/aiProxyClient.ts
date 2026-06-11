/**
 * AI Proxy Client
 *
 * Thin client that calls the server-side /api/ai/generate endpoint
 * instead of hitting AI providers directly from the browser.
 */

import { logger } from "@/utils/logger";
import { AIGenerationError } from "./ai/errors.js";
import { supabase } from "./supabase.js";

export interface GenerateOptions {
	prompt: string;
	systemPrompt?: string | undefined;
	model?: string | undefined;
	maxTokens?: number | undefined;
	temperature?: number | undefined;
	responseMimeType?: string | undefined;
	/** Feature name for cost tracking (e.g. "content_generation", "hashtag_suggestion") */
	feature?: string | undefined;
	/** Account ID for server-side voice profile injection */
	accountId?: string | undefined;
	/** Platform context for character limit injection */
	platform?: string | undefined;
}

interface GenerateResponse {
	success: boolean;
	text?: string | undefined;
	model?: string | undefined;
	error?: string | undefined;
}

const API_BASE = import.meta.env?.VITE_API_URL || "";

/**
 * Call the server-side AI proxy. Returns generated text or throws AIGenerationError.
 */
export async function generateViaProxy(
	options: GenerateOptions,
): Promise<string> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session?.access_token) {
		throw new AIGenerationError("Not authenticated. Please sign in.");
	}

	const controller = new AbortController();
	const timeoutId = setTimeout(() => controller.abort(), 30_000);

	try {
		const res = await fetch(`${API_BASE}/api/ai/generate`, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				Authorization: `Bearer ${session.access_token}`,
			},
			body: JSON.stringify(options),
			signal: controller.signal,
		});

		if (res.status === 429) {
			throw new AIGenerationError(
				"Rate limit exceeded. Please wait a moment and try again.",
				true,
			);
		}

		const data: GenerateResponse = await res.json();

		if (!res.ok || !data.success) {
			logger.error("[aiProxyClient] Server error:", data.error);
			throw new AIGenerationError(
				data.error || "AI generation failed",
				res.status >= 500,
			);
		}

		return data.text || "";
	} catch (err: unknown) {
		if (err instanceof AIGenerationError) throw err;
		if (err instanceof Error && err.name === "AbortError") {
			throw new AIGenerationError(
				"AI request timed out after 30 seconds",
				true,
			);
		}
		logger.error("[aiProxyClient] Request failed:", err);
		throw new AIGenerationError(
			err instanceof Error ? err.message : "Failed to reach AI service",
			true,
		);
	} finally {
		clearTimeout(timeoutId);
	}
}
