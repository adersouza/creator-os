/**
 * Grok x_search client for trending topic discovery.
 *
 * Uses xAI Responses API via @ai-sdk/xai provider with x_search tool
 * for real-time X/Twitter trend analysis. Wrapped in withRetry() with
 * circuit breaker for resilience.
 *
 * API key is read lazily at call time (not module import).
 */

import { createXai } from "@ai-sdk/xai";
import { generateText } from "ai";
import { trackAIUsage } from "./aiUsageTracking.js";
import { logger } from "./logger.js";
import { withRetry } from "./retryUtils.js";

// Lazy singleton provider — initialized on first call
let _xaiProvider: ReturnType<typeof createXai> | null = null;

function getXai() {
	if (!_xaiProvider) {
		const apiKey = process.env.XAI_API_KEY;
		if (!apiKey) throw new Error("XAI_API_KEY not configured");
		_xaiProvider = createXai({ apiKey });
	}
	return _xaiProvider;
}

/** Check if Grok search is available (API key present) */
export function isGrokAvailable(): boolean {
	return !!process.env.XAI_API_KEY;
}

export interface TrendResult {
	topic: string;
	context: string;
	relevanceScore: number;
	sources: Array<{ url: string; title?: string | undefined }>;
}

/**
 * Search for trending topics on X related to the given keywords.
 *
 * Uses Grok with x_search tool to discover real-time trends,
 * returning structured TrendResult[] data.
 */
export async function searchTrends(
	keywords: string[],
	options?: {
		fromDate?: string | undefined; // ISO8601 YYYY-MM-DD
		toDate?: string | undefined;
		userId?: string | undefined;
	},
): Promise<TrendResult[]> {
	const xai = getXai();
	const modelId = process.env.XAI_TREND_MODEL || "grok-4-fast-reasoning";

	try {
		return await withRetry(
			async () => {
				const result = await generateText({
					model: xai.responses(modelId),
					prompt: `Find the top trending topics on X (Twitter) right now that are related to these keywords: ${keywords.join(", ")}.

Return ONLY a JSON array (no markdown, no code fences) where each element has:
- "topic": string (concise topic name)
- "context": string (1-2 sentence explanation of why it's trending)
- "relevanceScore": number (0-100, how relevant to the keywords)

Example format:
[{"topic":"AI Agents","context":"Major announcements from tech companies about autonomous AI agents.","relevanceScore":85}]

Return up to 10 topics, sorted by relevanceScore descending.`,
					tools: {
						x_search: xai.tools.xSearch({
							...(options?.fromDate && { fromDate: options.fromDate }),
							...(options?.toDate && { toDate: options.toDate }),
						}),
					},
				});
				const usage = (
					result as {
						usage?:
							| {
									inputTokens?: number | undefined;
									outputTokens?: number | undefined;
									promptTokens?: number | undefined;
									completionTokens?: number | undefined;
							  }
							| undefined;
					}
				).usage;
				if (usage) {
					trackAIUsage(
						options?.userId ?? "platform",
						{
							promptTokens: usage.inputTokens ?? usage.promptTokens ?? 0,
							completionTokens:
								usage.outputTokens ?? usage.completionTokens ?? 0,
						},
						modelId,
						"grok_search",
						"env_fallback",
					);
				}

				return parseGrokTrendResponse(result.text, result.sources);
			},
			{
				maxRetries: 2,
				baseDelayMs: 1000,
				maxDelayMs: 10000,
				shouldRetry: isRetryableXaiError,
			},
		);
	} catch (error) {
		if (isXaiAccessError(error)) {
			logger.info("[trend-scanner] X search unavailable, skipping scan", {
				model: modelId,
				error: error instanceof Error ? error.message : String(error),
			});
			return [];
		}
		throw error;
	}
}

/** Determine if an xAI API error is retryable */
function isRetryableXaiError(error: unknown): boolean {
	const err = error as Record<string, unknown>;
	const status = err?.status ?? err?.code;

	// Do NOT retry auth/forbidden/deprecated errors
	if (status === 401 || status === 403 || status === 410) return false;

	// Retry rate limits and server errors
	if (status === 429 || (typeof status === "number" && status >= 500))
		return true;

	const message = ((err?.message as string) || "").toLowerCase();
	if (message.includes("rate limit")) return true;
	if (message.includes("too many requests")) return true;

	return false;
}

function isXaiAccessError(error: unknown): boolean {
	const err = error as Record<string, unknown>;
	const status = err?.status ?? err?.code;
	if (status === 401 || status === 403 || status === 410) return true;

	const message = ((err?.message as string) || String(error)).toLowerCase();
	return (
		message.includes("forbidden") ||
		message.includes("unauthorized") ||
		message.includes("not allowed") ||
		message.includes("model not allowed") ||
		message.includes("api key")
	);
}

/** Parse Grok text response into structured TrendResult[] */
function parseGrokTrendResponse(
	text: string,
	sources?: Array<{ url: string; title?: string | undefined }> | unknown,
): TrendResult[] {
	try {
		// Strip markdown code fences if present
		let cleaned = text.trim();
		if (cleaned.startsWith("```")) {
			cleaned = cleaned
				.replace(/^```(?:json)?\s*\n?/, "")
				.replace(/\n?```\s*$/, "");
		}

		const parsed = JSON.parse(cleaned);

		if (!Array.isArray(parsed)) {
			return [];
		}

		// Normalize sources into a flat array
		const sourceList: Array<{ url: string; title?: string | undefined }> =
			Array.isArray(sources)
				? sources.map(
						(s: { url?: string | undefined; title?: string | undefined }) => ({
							url: s.url || "",
							...(s.title && { title: s.title }),
						}),
					)
				: [];

		return parsed
			.filter(
				(item: Record<string, unknown>) =>
					typeof item?.topic === "string" &&
					typeof item?.context === "string" &&
					typeof item?.relevanceScore === "number" &&
					(item.relevanceScore as number) >= 0 &&
					(item.relevanceScore as number) <= 100,
			)
			.map((item: Record<string, unknown>) => ({
				topic: item.topic,
				context: item.context,
				relevanceScore: item.relevanceScore,
				sources: item.sources || sourceList,
			})) as unknown as TrendResult[];
	} catch (_err) {
		return [];
	}
}
