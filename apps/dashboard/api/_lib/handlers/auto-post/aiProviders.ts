/**
 * AI Provider Router
 *
 * Handles all LLM API calls (Gemini, xAI/Grok, OpenAI, Anthropic)
 * with automatic Gemini fallback on failure.
 *
 * Extracted from contentSelection.ts for separation of concerns.
 */

import { logger } from "../../logger.js";
import type { Platform } from "../../platform.js";
import { withRetry } from "../../retryUtils.js";
import { estimateAICostUsd, trackAICost } from "../../aiCostTracker.js";
import { recordAIEvalSnapshot } from "../../aiEvalSnapshots.js";

// ---------------------------------------------------------------------------
// Gemini quota circuit breaker — skip all calls for 30 min after quota error
// ---------------------------------------------------------------------------
let geminiQuotaBlockedUntil = 0;

function isGeminiQuotaBlocked(): boolean {
	return Date.now() < geminiQuotaBlockedUntil;
}

function markGeminiQuotaExhausted(): void {
	geminiQuotaBlockedUntil = Date.now() + 30 * 60 * 1000; // 30 min cooldown
	logger.error("Gemini quota exhausted — blocking all Gemini calls for 30 min");
}

export type ProviderCallOptions = {
	provider: string;
	apiKey: string;
	baseUrl?: string | undefined;
	model?: string | undefined;
	keySource?: "user" | "env_fallback" | undefined;
	allowProviderFallback?: boolean | undefined;
	ideaCount: number;
	systemInstruction?: string | undefined;
	actionLog?: {
        		userId: string;
        		accountId?: string | null | undefined;
        		surface: "composer" | "inbox" | "autopilot" | "analytics";
        		actionType: string;
        		inputText?: string | undefined;
        		metadata?: Record<string, unknown> | undefined;
        	} | undefined;
	/** When true, Gemini uses responseMimeType: "application/json" + responseSchema.
	 *  Guarantees valid JSON output — no markdown wrapping, no preamble, no parse failures.
	 *  Only applies to Gemini; other providers fall back to prompt-based JSON. */
	useStructuredOutput?: boolean | undefined;
	structuredOutputSchema?: Record<string, unknown> | undefined;
};

type ProviderUsage = {
	promptTokens: number;
	completionTokens: number;
	thinkingTokens?: number | undefined;
};

type ProviderCallResult = {
	text: string;
	model: string;
	provider: string;
	usage?: ProviderUsage | undefined;
	keySource?: "user" | "env_fallback" | undefined;
};

function resolveKeySource(
	options: ProviderCallOptions,
): "user" | "env_fallback" | undefined {
	if (options.keySource) return options.keySource;
	const envKeys = [
		process.env.GEMINI_API_KEY,
		process.env.GOOGLE_AI_API_KEY,
		process.env.OPENAI_API_KEY,
		process.env.XAI_API_KEY,
		process.env.ANTHROPIC_API_KEY,
	].filter(Boolean);
	return envKeys.includes(options.apiKey) ? "env_fallback" : undefined;
}

function mayUseProviderFallback(options: ProviderCallOptions): boolean {
	return (
		options.allowProviderFallback === true || resolveKeySource(options) !== "user"
	);
}

export function redactAIActionText(value: string | null | undefined): string | null {
	if (!value) return null;
	return value
		.replace(/sk-[A-Za-z0-9_-]{16,}/g, "sk-[REDACTED]")
		.replace(/Bearer\s+[A-Za-z0-9._-]+/g, "Bearer [REDACTED]")
		.replace(/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g, "[EMAIL]")
		.replace(/\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b/g, "[PHONE]")
		.slice(0, 2000);
}

export async function generateWithProvider(
	prompt: string,
	options: ProviderCallOptions,
): Promise<string | null> {
	const startedAt = Date.now();
	let result: ProviderCallResult | null = null;
	try {
		switch (options.provider) {
			case "openai":
				result = await callOpenAIModel(prompt, options);
				break;
			case "xai":
				result = await callXaiModel(prompt, options);
				break;
			case "anthropic":
				result = await callAnthropicModel(prompt, options);
				break;
			default:
				result = await callGeminiModel(prompt, options);
				break;
		}
	} catch (err) {
		// Catch throws (e.g. AI_APICallError: Forbidden) so fallback can fire
		logger.warn("AI provider threw error", {
			provider: options.provider || "gemini",
			error: err instanceof Error ? err.message : String(err),
		});
	}

	// Fallback to xAI if primary failed (null or threw) and xAI key is available
	if (result === null && mayUseProviderFallback(options)) {
		const xaiKey = process.env.XAI_API_KEY;
		const fallbackProvider = options.provider === "xai" ? null : "xai";
		const geminiKey = process.env.GEMINI_API_KEY;
		const geminiFallback =
			options.provider !== "gemini" && options.provider !== undefined
				? "gemini"
				: null;

		if (fallbackProvider === "xai" && xaiKey) {
			logger.warn("Falling back to xAI", {
				originalProvider: options.provider || "gemini",
			});
			try {
				result = await callXaiModel(prompt, {
					...options,
					provider: "xai",
					apiKey: xaiKey,
					model: "grok-4-1-fast",
					keySource: "env_fallback",
				});
			} catch (xaiErr) {
				logger.warn("xAI fallback also failed", {
					error: xaiErr instanceof Error ? xaiErr.message : String(xaiErr),
				});
			}
		}

		// Second fallback: Gemini (if primary wasn't Gemini)
		if (result === null && geminiFallback && geminiKey) {
			logger.warn("Falling back to Gemini", {
				originalProvider: options.provider,
			});
			try {
				result = await callGeminiModel(prompt, {
					...options,
					provider: "gemini",
					apiKey: geminiKey,
					keySource: "env_fallback",
				});
			} catch (geminiErr) {
				// Both fallbacks exhausted — caller will see null with no trace
				// of which provider failed unless we log here.
				logger.error("Both AI providers failed", {
					originalProvider: options.provider,
					geminiError:
						geminiErr instanceof Error
							? geminiErr.message
							: String(geminiErr),
				});
			}
		}
	}

	await logProviderAction(options, prompt, result, Date.now() - startedAt);
	await recordProviderEvalSnapshot(options, prompt, result, Date.now() - startedAt);
	if (result?.usage && options.actionLog) {
		trackAICost(
			options.actionLog.userId,
			result.usage.promptTokens,
			result.usage.completionTokens,
			result.model,
			options.actionLog.actionType,
			result.keySource,
			result.usage.thinkingTokens ?? 0,
		).catch(() => {});
	} else if (result?.usage && result.keySource === "env_fallback") {
		trackAICost(
			"platform",
			result.usage.promptTokens,
			result.usage.completionTokens,
			result.model,
			"generate_with_provider",
			"env_fallback",
			result.usage.thinkingTokens ?? 0,
		).catch(() => {});
	}
	return result?.text ?? null;
}

async function recordProviderEvalSnapshot(
	options: ProviderCallOptions,
	prompt: string,
	result: ProviderCallResult | null,
	latencyMs: number,
): Promise<void> {
	if (!options.actionLog) return;
	const metadata = options.actionLog.metadata ?? {};
	const workspaceId = stringMetadata(metadata, "workspaceId");
	const groupId = stringMetadata(metadata, "groupId");
	const promptText = redactAIActionText(options.actionLog.inputText ?? prompt) ?? "";
	const outputText = redactAIActionText(result?.text);
	try {
		const snapshot = await recordAIEvalSnapshot({
			userId: options.actionLog.userId,
			workspaceId,
			groupId,
			accountId: options.actionLog.accountId ?? null,
			suiteName: `live:${options.actionLog.surface}`,
			caseId: options.actionLog.actionType,
			category: options.actionLog.surface,
			prompt: promptText,
			provider: result?.provider ?? options.provider ?? "gemini",
			model: result?.model ?? options.model ?? "default",
			parameters: {
				ideaCount: options.ideaCount,
				useStructuredOutput: options.useStructuredOutput === true,
				latencyMs,
				keySource: result?.keySource ?? options.keySource ?? null,
				tokensIn: result?.usage?.promptTokens ?? null,
				tokensOut: result?.usage?.completionTokens ?? null,
				thinkingTokens: result?.usage?.thinkingTokens ?? null,
			},
			candidateOutputs: outputText ? [{ text: outputText }] : [],
			filterResults: [],
			judgeScores: [],
			selectedOutput: outputText ? { text: outputText } : null,
			selectedOutputId: result ? `${options.actionLog.actionType}:provider-output` : null,
			passed: result !== null,
			failures: result ? [] : ["provider_returned_null"],
			metadata: {
				...metadata,
				actionType: options.actionLog.actionType,
				surface: options.actionLog.surface,
				source: "generateWithProvider",
			},
		});
		if (!snapshot.ok) {
			logger.warn("Failed to persist AI eval snapshot", {
				surface: options.actionLog.surface,
				actionType: options.actionLog.actionType,
				error: snapshot.error,
			});
		}
	} catch (error) {
		logger.warn("AI eval snapshot persistence threw", {
			surface: options.actionLog.surface,
			actionType: options.actionLog.actionType,
			error: error instanceof Error ? error.message : String(error),
		});
	}
}

function stringMetadata(
	metadata: Record<string, unknown>,
	key: string,
): string | null {
	const value = metadata[key];
	return typeof value === "string" && value.trim().length > 0 ? value : null;
}

async function logProviderAction(
	options: ProviderCallOptions,
	prompt: string,
	result: ProviderCallResult | null,
	latencyMs: number,
): Promise<void> {
	if (!options.actionLog) return;
	try {
		const { getSupabaseAny } = await import("../../supabase.js");
		const modelUsed = result?.model ?? options.model ?? null;
		const usage = result?.usage;
		await getSupabaseAny().from("ai_action_log").insert({
			user_id: options.actionLog.userId,
			account_id: options.actionLog.accountId ?? null,
			surface: options.actionLog.surface,
			action_type: options.actionLog.actionType,
			input_text: redactAIActionText(options.actionLog.inputText ?? prompt),
			output_text: redactAIActionText(result?.text),
			model_used: modelUsed,
			provider: result?.provider ?? options.provider,
			latency_ms: latencyMs,
			tokens_in: usage?.promptTokens ?? null,
			tokens_out: usage?.completionTokens ?? null,
			cost_usd: usage
				? estimateAICostUsd(
						modelUsed ?? "",
						usage.promptTokens,
						usage.completionTokens,
						usage.thinkingTokens ?? 0,
					)
				: null,
			metadata: options.actionLog.metadata ?? {},
		});
	} catch (error) {
		logger.warn("Failed to write AI action log", {
			surface: options.actionLog.surface,
			actionType: options.actionLog.actionType,
			error: error instanceof Error ? error.message : String(error),
		});
	}
}

async function callGeminiModel(
	prompt: string,
	options: ProviderCallOptions,
): Promise<ProviderCallResult | null> {
	if (isGeminiQuotaBlocked()) {
		logger.info("Gemini call skipped — quota circuit breaker active");
		return null;
	}

	// Daily spend limit check
	try {
		const { checkDailySpendLimit } = await import("../../aiCostTracker.js");
		const { allowed, spentUsd, limitUsd } = await checkDailySpendLimit();
		if (!allowed) {
			logger.warn("Gemini call blocked — daily spend limit reached", {
				spentUsd: spentUsd.toFixed(4),
				limitUsd,
			});
			return null;
		}
	} catch (err) {
		// Fail-open is correct (Redis outage shouldn't block all generation)
		// but log it — silently swallowing means a misconfigured cost tracker
		// can disable the spend cap without anyone noticing.
		logger.warn("Spend-limit check failed, allowing call", {
			error: err instanceof Error ? err.message : String(err),
		});
	}
	// gemini-2.5-flash: flash-lite copies examples verbatim, flash generates original content.
	// Cost difference is negligible at our volume (~$1-2/month).
	const modelId = options.model || "gemini-2.5-flash";
	const baseUrl = (
		options.baseUrl || "https://generativelanguage.googleapis.com"
	).replace(/\/$/, "");
	try {
		logger.info("Gemini API request", {
			model: modelId,
			baseUrl,
			hasSystemInstruction: !!options.systemInstruction,
		});

		// Temperature 0.75: creative enough for casual/flirty, constrained enough
		// to follow instructions. topP 0.92 + topK 40 bound the sampling pool.
		// Thinking explicitly disabled — was costing $3.50/M tokens (23x regular input).
		// Removing the param only uses default budget; must set thinkingBudget: 0.
		const genConfig: Record<string, unknown> = {
			temperature: 0.75,
			topP: 0.92,
			topK: 40,
			maxOutputTokens: Math.max(500, options.ideaCount * 80),
			thinkingConfig: { thinkingBudget: 0 },
		};

		// Structured output: forces Gemini to return valid JSON — no markdown,
		// no preamble, no parse failures. 99.9% schema adherence (Google docs).
		// Schema kept minimal to avoid degrading creative quality (Grok/Perplexity research).
		if (options.useStructuredOutput) {
			genConfig.responseMimeType = "application/json";
			genConfig.responseSchema = options.structuredOutputSchema ?? {
				type: "ARRAY",
				items: {
					type: "OBJECT",
					properties: {
						content: {
							type: "STRING",
							description:
								"Post text. MUST be 30-100 characters. Never under 25 chars.",
						},
						viralScore: { type: "INTEGER" },
						sourceIndex: { type: "INTEGER" },
						contentType: { type: "STRING" },
						originalIndex: { type: "INTEGER" },
					},
					required: ["content"],
				},
			};
		}

		const requestBody: Record<string, unknown> = {
			contents: [{ parts: [{ text: prompt }] }],
			generationConfig: genConfig,
			safetySettings: [
				{
					category: "HARM_CATEGORY_SEXUALLY_EXPLICIT",
					threshold: "BLOCK_NONE",
				},
				{ category: "HARM_CATEGORY_HARASSMENT", threshold: "BLOCK_NONE" },
				{
					category: "HARM_CATEGORY_DANGEROUS_CONTENT",
					threshold: "BLOCK_NONE",
				},
				{ category: "HARM_CATEGORY_HATE_SPEECH", threshold: "BLOCK_NONE" },
			],
		};

		// System instruction gets higher priority than user prompt in Gemini
		if (options.systemInstruction) {
			requestBody.systemInstruction = {
				parts: [{ text: options.systemInstruction }],
			};
		}

		const response = await withRetry(
			() =>
				fetch(
					`${baseUrl}/v1beta/models/${modelId}:generateContent?key=${options.apiKey}`,
					{
						method: "POST",
						headers: { "Content-Type": "application/json" },
						signal: AbortSignal.timeout(30000),
						body: JSON.stringify(requestBody),
					},
				),
			{ label: `auto-post:gemini:${modelId}` },
		);

		if (!response.ok) {
			logger.error("Gemini API error during generation", {
				status: response.status,
			});
			// 429 = rate limit, 402 = billing, 403 = quota exceeded
			if (
				response.status === 429 ||
				response.status === 402 ||
				response.status === 403
			) {
				markGeminiQuotaExhausted();
			}
			return null;
		}

		const data = await response.json();
		// With thinkingConfig enabled, Gemini may return multiple parts:
		// parts[0] = thinking (thought: true), parts[1] = actual JSON.
		// Find the last non-thought part to get the real content.
		const parts = data.candidates?.[0]?.content?.parts;
		if (!parts || parts.length === 0) return null;
		const contentPart = [...parts]
			.reverse()
			.find((p: { thought?: boolean | undefined; text?: string | undefined }) => !p.thought && p.text);

		const text = contentPart?.text?.trim();
		if (!text) return null;
		const usageMeta = data.usageMetadata;
		return {
			text,
			model: modelId,
			provider: "gemini",
			keySource: resolveKeySource(options),
			usage: usageMeta
				? {
						promptTokens: usageMeta.promptTokenCount || 0,
						completionTokens: usageMeta.candidatesTokenCount || 0,
						thinkingTokens: usageMeta.thoughtsTokenCount || 0,
					}
				: undefined,
		};
	} catch (err) {
		logger.warn("Gemini API call failed", {
			model: modelId,
			error: String(err),
		});
		return null;
	}
}

async function callXaiModel(
	prompt: string,
	options: ProviderCallOptions,
): Promise<ProviderCallResult | null> {
	const baseUrl = (options.baseUrl || "https://api.x.ai/v1").replace(/\/$/, "");
	const model = options.model || "grok-4-1-fast";
	try {
		logger.info("xAI API request", {
			model,
			baseUrl,
			hasSystemInstruction: !!options.systemInstruction,
		});

		const response = await withRetry(
			() =>
				fetch(`${baseUrl}/chat/completions`, {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						Authorization: `Bearer ${options.apiKey}`,
					},
					signal: AbortSignal.timeout(30000),
					body: JSON.stringify({
						model,
						store: false,
						temperature: 0.8,
						max_tokens: Math.max(500, options.ideaCount * 80),
						messages: [
							{
								role: "system",
								content:
									options.systemInstruction ||
									"You are an elite social media copywriter. Respond with JSON only.",
							},
							{ role: "user", content: prompt },
						],
					}),
				}),
			{ label: `auto-post:xai:${model}` },
		);

		if (!response.ok) {
			const errorText = await response.text().catch(() => "");
			logger.error("xAI API error during generation", {
				status: response.status,
				model,
				error: errorText.slice(0, 200),
			});
			return null;
		}

		const data = await response.json();
		const text = data.choices?.[0]?.message?.content?.trim();
		if (!text) return null;
		return {
			text,
			model,
			provider: "xai",
			keySource: resolveKeySource(options),
			usage: data.usage
				? {
						promptTokens: data.usage.prompt_tokens || 0,
						completionTokens: data.usage.completion_tokens || 0,
					}
				: undefined,
		};
	} catch (err) {
		logger.warn("xAI API call failed", { model, error: String(err) });
		return null;
	}
}

async function callOpenAIModel(
	prompt: string,
	options: ProviderCallOptions,
): Promise<ProviderCallResult | null> {
	const baseUrl = (options.baseUrl || "https://api.openai.com/v1").replace(
		/\/$/,
		"",
	);
	const model = options.model || "gpt-4.1-mini";
	try {
		const response = await withRetry(
			() =>
				fetch(`${baseUrl}/chat/completions`, {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						Authorization: `Bearer ${options.apiKey}`,
					},
					signal: AbortSignal.timeout(30000),
					body: JSON.stringify({
						model,
						temperature: 0.95,
						max_tokens: Math.max(500, options.ideaCount * 80),
						messages: [
							{
								role: "system",
								content:
									options.systemInstruction ||
									"You are an elite social media copywriter. Respond with JSON only.",
							},
							{ role: "user", content: prompt },
						],
					}),
				}),
			{ label: `auto-post:openai:${model}` },
		);

		if (!response.ok) {
			logger.error("OpenAI API error during generation", {
				status: response.status,
			});
			return null;
		}

		const data = await response.json();
		const text = data.choices?.[0]?.message?.content?.trim();
		if (!text) return null;
		return {
			text,
			model,
			provider: "openai",
			keySource: resolveKeySource(options),
			usage: data.usage
				? {
						promptTokens: data.usage.prompt_tokens || 0,
						completionTokens: data.usage.completion_tokens || 0,
					}
				: undefined,
		};
	} catch (err) {
		logger.warn("OpenAI API call failed", { model, error: String(err) });
		return null;
	}
}

async function callAnthropicModel(
	prompt: string,
	options: ProviderCallOptions,
): Promise<ProviderCallResult | null> {
	const baseUrl = (options.baseUrl || "https://api.anthropic.com/v1").replace(
		/\/$/,
		"",
	);
	const model = options.model || "claude-haiku-4-5-20251001";
	const systemText =
		options.systemInstruction ||
		"You are an elite social media writer. Respond with a JSON array only.";
	try {
		const response = await withRetry(
			() =>
				fetch(`${baseUrl}/messages`, {
					method: "POST",
					headers: {
						"Content-Type": "application/json",
						"x-api-key": options.apiKey,
						"anthropic-version": "2023-06-01",
					},
					signal: AbortSignal.timeout(30000),
					body: JSON.stringify({
						model,
						temperature: 0.9,
						max_tokens: Math.max(500, options.ideaCount * 80),
						// System prompt passed as a block array with cache_control set.
						// The system prompt is stable across calls in a queue-fill cycle,
						// so the cache hits on the 2nd+ call for the same persona. Anthropic
						// charges 10% of the input token price for cache reads vs 100% for
						// cache writes — meaningful savings on long system prompts.
						system: [
							{
								type: "text",
								text: systemText,
								cache_control: { type: "ephemeral" },
							},
						],
						messages: [{ role: "user", content: prompt }],
					}),
				}),
			{ label: `auto-post:anthropic:${model}` },
		);

		if (!response.ok) {
			logger.error("Anthropic API error during generation", {
				status: response.status,
			});
			return null;
		}

		const data = await response.json();
		const firstPart = Array.isArray(data.content) ? data.content[0] : null;
		const text =
			firstPart?.text ??
			(typeof data.content === "string" ? data.content : undefined);
		if (!text?.trim()) return null;
		return {
			text: text.trim(),
			model,
			provider: "anthropic",
			keySource: resolveKeySource(options),
			usage: data.usage
				? {
						promptTokens: data.usage.input_tokens || 0,
						completionTokens: data.usage.output_tokens || 0,
					}
				: undefined,
		};
	} catch (err) {
		logger.warn("Anthropic API call failed", { model, error: String(err) });
		return null;
	}
}

export function adjustContentForPlatform(
	content: string,
	platform: Platform,
): string {
	const trimmed = content.trim();
	if (platform === "instagram") {
		return trimmed;
	}
	// Threads: enforce hashtag-free copy and collapse excess whitespace
	const withoutHashtags = trimmed
		.replace(/#[^\s#]+/g, "")
		.replace(/\s{2,}/g, " ")
		.trim();
	return withoutHashtags;
}
