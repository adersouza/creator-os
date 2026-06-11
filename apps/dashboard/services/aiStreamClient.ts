/**
 * AI Stream Client — SSE streaming for AI generation
 *
 * Connects to /api/ai/stream and yields text chunks as they arrive.
 * Used by WriteTab for progressive "Generate Post" output.
 */

import { logger } from "@/utils/logger";
import { supabase } from "./supabase.js";

export interface StreamOptions {
	prompt: string;
	systemPrompt?: string | undefined;
	model?: string | undefined;
	maxTokens?: number | undefined;
	temperature?: number | undefined;
	signal?: AbortSignal | undefined;
	feature?: string | undefined;
}

/**
 * Stream AI-generated text via SSE.
 * Yields individual text chunks as they arrive from the server.
 */
export async function* streamGenerate(
	options: StreamOptions,
): AsyncGenerator<string> {
	const {
		data: { session },
	} = await supabase.auth.getSession();
	if (!session?.access_token) {
		throw new Error("Not authenticated. Please sign in.");
	}

	const API_BASE = import.meta.env?.VITE_API_URL || "";

	const res = await fetch(`${API_BASE}/api/ai/stream`, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${session.access_token}`,
		},
		body: JSON.stringify({
			prompt: options.systemPrompt
				? `${options.systemPrompt}\n\n${options.prompt}`
				: options.prompt,
			model: options.model,
			maxTokens: options.maxTokens,
			temperature: options.temperature,
			feature: options.feature,
		}),
			...(options.signal ? { signal: options.signal } : {}),
	});

	if (!res.ok) {
		if (res.status === 429) {
			throw new Error(
				"Rate limit exceeded. Please wait a moment and try again.",
			);
		}
		const errText = await res.text().catch(() => "AI streaming failed");
		throw new Error(errText);
	}

	const reader = res.body?.getReader();
	if (!reader) {
		throw new Error("Streaming not supported by browser");
	}

	// Abort stream if server stalls for more than 60 seconds between chunks
	const abortController = new AbortController();
	let timeoutId = setTimeout(() => abortController.abort(), 60_000);

	const decoder = new TextDecoder();
	let buffer = "";

	try {
		while (true) {
			if (abortController.signal.aborted) {
				throw new Error("Stream timed out after 60 seconds of inactivity");
			}

			const { done, value } = await reader.read();
			if (done) break;

			// Reset the timeout on each received chunk
			clearTimeout(timeoutId);
			timeoutId = setTimeout(() => abortController.abort(), 60_000);

			buffer += decoder.decode(value, { stream: true });

			// Process complete SSE events from buffer
			const lines = buffer.split("\n");
			// Keep the last incomplete line in the buffer
			buffer = lines.pop() || "";

			for (const line of lines) {
				const trimmed = line.trim();
				if (!trimmed?.startsWith("data: ")) continue;

				const data = trimmed.slice(6); // Remove "data: " prefix

				if (data === "[DONE]") return;

				try {
					const parsed = JSON.parse(data);
					if (parsed.error) {
						throw new Error(parsed.error);
					}
					if (parsed.text) {
						yield parsed.text;
					}
				} catch (parseErr) {
					// Skip malformed JSON chunks — they're non-critical
					if (
						parseErr instanceof Error &&
						parseErr.message !== "Unexpected end of JSON input"
					) {
						logger.debug("[aiStreamClient] Parse error on chunk", { data });
					}
				}
			}
		}
	} finally {
		clearTimeout(timeoutId);
		reader.releaseLock();
	}
}
