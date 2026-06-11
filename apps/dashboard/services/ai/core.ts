// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * AI Service Core - Multi-provider support
 *
 * Primary path: server-side proxy (/api/ai/generate) keeps API keys off the client.
 * Fallback: direct client-side calls for non-Gemini providers or when proxy is unavailable.
 */
import { GoogleGenAI } from "@google/genai";
import {
	type AIProviderConfig,
	type AIProviderType,
	getProviderInfo,
} from "../../types/aiProvider.js";
import type { Json } from "../../types/supabase.js";
import { logger } from "@/utils/logger";
import { generateViaProxy } from "../aiProxyClient.js";
import { supabase } from "../supabase.js";
import { AIGenerationError } from "./errors.js";

// Re-export for backward compatibility
export { AIGenerationError } from "./errors.js";

// Cached config and clients
let cachedConfig: AIProviderConfig | null = null;

function getExcludeTopics(settingValue: Json): string[] {
	if (
		!settingValue ||
		Array.isArray(settingValue) ||
		typeof settingValue !== "object"
	) {
		return [];
	}

	const excludeTopics = settingValue.excludeTopics;
	if (!Array.isArray(excludeTopics)) {
		return [];
	}

	return excludeTopics.filter(
		(topic): topic is string => typeof topic === "string",
	);
}

export const loadAIConfig = async (): Promise<AIProviderConfig | null> => {
	logger.log("[aiService] loadAIConfig called");

	try {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		const userId = session?.user?.id;

		logger.log("[aiService] Supabase session check:", {
			hasSession: !!session,
			userId: userId || "none",
		});

		if (!userId) {
			logger.log("[aiService] No Supabase user session found");
			return null;
		}

		const { data, error } = await supabase
			.from("ai_config")
			.select("*")
			.eq("user_id", userId)
			.maybeSingle();

		if (error) {
			logger.error(
				"[aiService] Failed to load AI config from Supabase:",
				error,
			);
			return null;
		}

		if (data) {
			logger.log("[aiService] Loaded config from Supabase:", {
				provider: data.provider,
				hasApiKey: !!data.api_key,
				keyLength: data.api_key?.length,
				keyPreview: data.api_key
					? `${data.api_key.substring(0, 10)}...`
					: "EMPTY",
			});
			cachedConfig = {
				provider: (data.provider || "gemini") as AIProviderType,
				apiKey: data.api_key || "",
				baseUrl: data.base_url || undefined,
				model: data.model || undefined,
				lastValidatedAt: data.last_validated_at
					? new Date(data.last_validated_at)
					: undefined,
			};
			return cachedConfig;
		}

		logger.log("[aiService] No AI config found in Supabase for user");
		return null;
	} catch (error) {
		logger.error("[aiService] Failed to load AI config from Supabase:", error);
		return null;
	}
};

// Get config - always loads fresh to ensure latest key
export const getAIConfig = async (): Promise<AIProviderConfig | null> => {
	// Always load fresh to ensure we have the latest saved config
	return await loadAIConfig();
};

// Clear cached config (call when user changes settings)
export const clearAIConfigCache = () => {
	cachedConfig = null;
};

// Initialize Gemini client
export const getGeminiClient = (apiKey: string): GoogleGenAI | null => {
	if (!apiKey) {
		logger.error("[aiService] No API key provided to getGeminiClient");
		return null;
	}

	// Always create a new client with the provided API key to ensure we're using the latest key
	try {
		logger.log(
			"[aiService] Creating new Gemini client with API key length:",
			apiKey.length,
			"preview:",
			`${apiKey.substring(0, 10)}...`,
		);
		const client = new GoogleGenAI({ apiKey });
		return client;
	} catch (e) {
		logger.error("[aiService] Failed to initialize Gemini:", e);
		return null;
	}
};

// Generic completion function for OpenAI-compatible APIs
export const callOpenAICompatible = async (
	apiKey: string,
	baseUrl: string,
	model: string,
	prompt: string,
	systemPrompt?: string,
): Promise<string> => {
	const messages: Array<{ role: string; content: string }> = [];

	if (systemPrompt) {
		messages.push({ role: "system", content: systemPrompt });
	}
	messages.push({ role: "user", content: prompt });

	const response = await fetch(`${baseUrl}/chat/completions`, {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			Authorization: `Bearer ${apiKey}`,
		},
		body: JSON.stringify({
			model,
			messages,
			max_tokens: 1024,
			temperature: 0.7,
		}),
	});

	if (!response.ok) {
		const error = await response.text();
		throw new Error(`API error: ${response.status} - ${error}`);
	}

	const data = await response.json();
	return data.choices?.[0]?.message?.content || "";
};

// Call Anthropic API
export const callAnthropic = async (
	apiKey: string,
	model: string,
	prompt: string,
	systemPrompt?: string,
): Promise<string> => {
	const response = await fetch("https://api.anthropic.com/v1/messages", {
		method: "POST",
		headers: {
			"Content-Type": "application/json",
			"x-api-key": apiKey,
			"anthropic-version": "2023-06-01",
			"anthropic-dangerous-direct-browser-access": "true",
		},
		body: JSON.stringify({
			model,
			max_tokens: 1024,
			system:
				systemPrompt ||
				"You are a helpful assistant for social media content creation.",
			messages: [{ role: "user", content: prompt }],
		}),
	});

	if (!response.ok) {
		const error = await response.text();
		throw new Error(`Anthropic API error: ${response.status} - ${error}`);
	}

	const data = await response.json();
	return data.content?.[0]?.text || "";
};

// Classify error and throw AIGenerationError with appropriate retryable flag
function throwClassifiedError(error: unknown): never {
	if (!(error instanceof Error)) {
		throw new AIGenerationError(
			"Failed to generate content. Please check your API key.",
		);
	}
	const msg = error.message.toLowerCase();
	// Timeout
	if (
		msg.includes("timed out") ||
		msg.includes("timeout") ||
		error.name === "AbortError"
	) {
		throw new AIGenerationError(
			"Generation timed out. Try shorter content or try again.",
			true,
		);
	}
	// Rate limit
	if (
		msg.includes("429") ||
		msg.includes("rate limit") ||
		msg.includes("too many requests")
	) {
		throw new AIGenerationError(
			"AI rate limit reached. Please wait a moment and try again.",
			true,
		);
	}
	// Auth errors
	if (
		msg.includes("401") ||
		msg.includes("403") ||
		msg.includes("unauthorized") ||
		msg.includes("forbidden") ||
		msg.includes("invalid.*key") ||
		msg.includes("api key")
	) {
		throw new AIGenerationError(
			"API key is invalid or expired. Check your AI settings.",
		);
	}
	// Network errors
	if (
		msg.includes("network") ||
		msg.includes("fetch") ||
		msg.includes("econnrefused") ||
		msg.includes("enotfound") ||
		msg.includes("failed to fetch")
	) {
		throw new AIGenerationError(
			"Network error. Check your connection and try again.",
			true,
		);
	}
	throw new AIGenerationError(error.message);
}

// Main generate function - uses server-side proxy for Gemini, falls back to direct calls
export const generateContent = async (
	prompt: string,
	systemPrompt?: string,
	options?: {
		responseMimeType?: string | undefined;
		maxTokens?: number | undefined;
		accountId?: string | undefined;
		platform?: string | undefined;
	},
): Promise<string> => {
	logger.log("[aiService] generateContent called");

	// Validate prompt length to prevent cost abuse
	const MAX_PROMPT_LENGTH = 10000; // ~2500 tokens
	if (prompt.length > MAX_PROMPT_LENGTH) {
		throw new AIGenerationError(
			"Input too long. Please shorten your content to under 10,000 characters.",
		);
	}
	if (!prompt.trim()) {
		throw new AIGenerationError("Please provide some content to work with.");
	}

	const config = await getAIConfig();
	const provider = config?.provider || "gemini";
	const providerInfo = getProviderInfo(provider);
	const model = config?.model || providerInfo.defaultModel;

	// ── Primary path: server-side proxy (keeps API keys off the client) ──
	if (provider === "gemini" || !config?.apiKey) {
		logger.log("[aiService] Using server-side proxy for generation");
		try {
			return await generateViaProxy({
				prompt,
				systemPrompt,
				model: provider === "gemini" ? model : undefined,
				responseMimeType: options?.responseMimeType,
				maxTokens: options?.maxTokens,
				accountId: options?.accountId,
				platform: options?.platform,
			});
		} catch (proxyErr) {
			// If proxy failed and we have no client-side key, rethrow
			if (!config?.apiKey) {
				throw proxyErr;
			}
			logger.log(
				"[aiService] Proxy failed, falling back to direct call:",
				proxyErr,
			);
		}
	}

	// ── Fallback: direct client-side calls (non-Gemini or proxy failure) ──
	// Never make direct API calls from the browser — always use proxy
	if (typeof window !== "undefined") {
		logger.warn(
			"[aiService] Direct API call attempted from browser, redirecting to proxy",
		);
		return generateViaProxy({ prompt, systemPrompt });
	}

	if (!config?.apiKey) {
		throw new AIGenerationError(
			"No AI provider configured. Please add your API key in Settings.",
		);
	}

	try {
		switch (config.provider) {
			case "gemini": {
				const client = getGeminiClient(config.apiKey);
				if (!client) {
					throw new AIGenerationError(
						"Failed to initialize Gemini client. Check your API key.",
					);
				}
				const fullPrompt = systemPrompt
					? `${systemPrompt}\n\n${prompt}`
					: prompt;

				const timeoutPromise = new Promise<never>((_, reject) => {
					setTimeout(
						() => reject(new Error("AI request timed out after 30 seconds")),
						30000,
					);
				});

				const response = await Promise.race([
					client.models.generateContent({
						model,
						contents: fullPrompt,
						config: {
							...(options?.responseMimeType
								? { responseMimeType: options.responseMimeType }
								: {}),
							...(options?.maxTokens
								? { maxOutputTokens: options.maxTokens }
								: {}),
						},
					}),
					timeoutPromise,
				]);
				return response.text || "";
			}

			case "openai": {
				return await callOpenAICompatible(
					config.apiKey,
					"https://api.openai.com/v1",
					model,
					prompt,
					systemPrompt,
				);
			}

			case "anthropic": {
				return await callAnthropic(config.apiKey, model, prompt, systemPrompt);
			}

			case "groq": {
				return await callOpenAICompatible(
					config.apiKey,
					"https://api.groq.com/openai/v1",
					model,
					prompt,
					systemPrompt,
				);
			}

			case "custom": {
				if (!config.baseUrl) {
					throw new AIGenerationError("Custom endpoint requires a base URL.");
				}
				return await callOpenAICompatible(
					config.apiKey,
					config.baseUrl,
					model || "default",
					prompt,
					systemPrompt,
				);
			}

			default:
				throw new AIGenerationError("Unknown AI provider.");
		}
	} catch (error: unknown) {
		if (error instanceof AIGenerationError) throw error;
		logger.error("AI generation error:", error);
		throwClassifiedError(error);
	}
};

/**
 * Generate content with automatic retry and exponential backoff.
 * Wraps generateContent with up to 3 attempts.
 * Use this as the primary entry point for all AI generation calls.
 */
export async function generateWithRetry(
	prompt: string,
	systemPrompt?: string,
	options?: {
		responseMimeType?: string | undefined;
		maxTokens?: number | undefined;
		maxRetries?: number | undefined;
	},
): Promise<string> {
	const maxRetries = options?.maxRetries ?? 3;
	let lastError: Error | null = null;

	for (let attempt = 0; attempt < maxRetries; attempt++) {
		try {
			return await generateContent(prompt, systemPrompt, options);
		} catch (err) {
			lastError = err instanceof Error ? err : new Error(String(err));

			// Non-retryable errors: don't retry
			if (err instanceof AIGenerationError && !err.retryable) {
				throw err;
			}

			if (attempt < maxRetries - 1) {
				logger.warn(
					`[aiService] Attempt ${attempt + 1}/${maxRetries} failed: ${lastError.message}. Retrying...`,
				);
				// Exponential backoff: 1s, 3s, 5s
				await new Promise((r) => setTimeout(r, (attempt + 1) * 2000 - 1000));
			}
		}
	}

	throw lastError || new Error("AI generation failed after retries");
}

// Test connection to AI provider
export const testAIConnection = async (
	config: AIProviderConfig,
): Promise<{ success: boolean; message: string }> => {
	if (!config.apiKey) {
		return { success: false, message: "API key is required" };
	}

	const providerInfo = getProviderInfo(config.provider);
	const model = config.model || providerInfo.defaultModel;
	const testPrompt = 'Say "Hello" in one word.';

	try {
		switch (config.provider) {
			case "gemini": {
				const client = new GoogleGenAI({ apiKey: config.apiKey });
				const response = await client.models.generateContent({
					model,
					contents: testPrompt,
				});
				if (response.text) {
					return { success: true, message: "Connection successful!" };
				}
				return { success: false, message: "No response from Gemini" };
			}

			case "openai": {
				const result = await callOpenAICompatible(
					config.apiKey,
					"https://api.openai.com/v1",
					model,
					testPrompt,
				);
				return {
					success: !!result,
					message: result ? "Connection successful!" : "No response",
				};
			}

			case "anthropic": {
				const result = await callAnthropic(config.apiKey, model, testPrompt);
				return {
					success: !!result,
					message: result ? "Connection successful!" : "No response",
				};
			}

			case "groq": {
				const result = await callOpenAICompatible(
					config.apiKey,
					"https://api.groq.com/openai/v1",
					model,
					testPrompt,
				);
				return {
					success: !!result,
					message: result ? "Connection successful!" : "No response",
				};
			}

			case "custom": {
				if (!config.baseUrl) {
					return {
						success: false,
						message: "Base URL is required for custom endpoints",
					};
				}
				const result = await callOpenAICompatible(
					config.apiKey,
					config.baseUrl,
					model || "default",
					testPrompt,
				);
				return {
					success: !!result,
					message: result ? "Connection successful!" : "No response",
				};
			}

			default:
				return { success: false, message: "Unknown provider" };
		}
	} catch (error: unknown) {
		logger.error("Connection test failed:", error);
		return {
			success: false,
			message:
				error instanceof Error
					? error.message
					: "Connection failed. Check your API key and try again.",
		};
	}
};

// ===== Exported AI Functions (compatible with existing geminiService) =====

// Style mapping for content generation
export const STYLE_MAP: Record<string, string> = {
	professional:
		"Professional and authoritative - use industry terms, data-driven insights, thought leadership",
	casual:
		"Casual and conversational - like texting a friend, use contractions, be relatable",
	flirty:
		"Flirty and playful - use charm, wit, subtle teasing, be magnetic and charismatic",
	motivational:
		"Motivational and inspiring - uplift, encourage, use powerful language",
	humorous:
		"Humorous and witty - use clever wordplay, self-deprecating humor, be entertaining",
	educational:
		"Educational and informative - teach something valuable, use clear explanations",
	luxury: "Luxury and aspirational - sophisticated, exclusive, premium feel",
	meme_lord:
		"Meme lord energy - internet humor, trendy references, chaotic but relatable",
};

// Load user's AI preferences from Supabase (excludeTopics only - tone comes from Voice Profiles)
export const loadUserAIPrefs = async (): Promise<{
	excludeTopics: string[];
} | null> => {
	try {
		const {
			data: { session },
		} = await supabase.auth.getSession();
		if (!session?.user) return null;

		const { data, error } = await supabase
			.from("user_settings")
			.select("setting_value")
			.eq("user_id", session.user.id)
			.eq("setting_key", "aiInsights")
			.maybeSingle();

		if (error) {
			logger.error("[aiService] Failed to load AI prefs:", error);
			return null;
		}

		if (data?.setting_value) {
			return {
				excludeTopics: getExcludeTopics(data.setting_value),
			};
		}
		return null;
	} catch (error) {
		logger.error("[aiService] Error loading AI prefs:", error);
		return null;
	}
};

export function parseAIJson<T>(response: string): T {
	let jsonStr = response;
	if (response.includes("```json")) {
		jsonStr = response.split("```json")[1]!.split("```")[0]!.trim();
	} else if (response.includes("```")) {
		jsonStr = response.split("```")[1]!.split("```")[0]!.trim();
	}
	return JSON.parse(jsonStr) as T;
}

/**
 * Repurpose a post into carousel slides with titles
 */
