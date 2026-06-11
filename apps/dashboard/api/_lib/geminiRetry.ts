/**
 * Gemini API retry wrapper.
 *
 * Wraps generateContent calls with exponential backoff
 * to handle quota exhaustion (RESOURCE_EXHAUSTED / 429) gracefully.
 */

import { withRetry } from "./retryUtils.js";

/** Always available — circuit breaker removed (was in-memory, ineffective on Vercel) */
export function isGeminiAvailable(): boolean {
	return true;
}

function isRetryableGeminiError(error: unknown): boolean {
	const err = error as Record<string, unknown>;
	const status = err?.status ?? err?.code ?? err?.httpCode;
	const message = (err?.message as string) || "";

	// Google SDK quota/rate errors
	if (status === 429 || status === 503) return true;
	if ((status as number) >= 500) return true;
	if (message.includes("RESOURCE_EXHAUSTED")) return true;
	if (message.includes("quota")) return true;
	if (message.includes("rate limit")) return true;
	if (message.includes("Too Many Requests")) return true;

	return false;
}

/**
 * Wrap a Gemini generateContent call with retry.
 *
 * Usage:
 *   const response = await withGeminiRetry(() => client.models.generateContent({...}));
 */
export async function withGeminiRetry<T>(fn: () => Promise<T>): Promise<T> {
	return withRetry(fn, {
		maxRetries: 2,
		baseDelayMs: 1000,
		maxDelayMs: 10000,
		shouldRetry: isRetryableGeminiError,
	});
}
