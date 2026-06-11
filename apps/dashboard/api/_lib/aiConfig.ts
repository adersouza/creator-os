/**
 * Canonical AI Configuration Resolver
 *
 * Single source of truth for resolving a user's AI provider config.
 * Replaces 4 duplicate getUserAIConfig implementations across the codebase.
 *
 * Resolution order:
 * 1. User's ai_config table row (decrypt stored key)
 * 2. Env var fallback (GEMINI_API_KEY / XAI_API_KEY) respecting workspace ai_provider
 */

import { logger } from "./logger.js";
import { withRetry } from "./retryUtils.js";
import { getSupabase, getSupabaseAny } from "./supabase.js";
import { TTL_1_HOUR, TTL_5_MIN } from "./timing.js";

export interface UserAIConfig {
	provider: string;
	apiKey: string;
	baseUrl?: string | undefined;
	model?: string | undefined;
	/** Where the key came from — useful for logging/debugging */
	source?: "user" | "env_fallback" | undefined;
}

/**
 * Resolve the AI config for a given user.
 *
 * 1. Check ai_config table for user's own key (decrypt if encrypted)
 * 2. Fallback to env vars (respecting workspace ai_provider preference)
 * 3. Return null if no key found anywhere
 */
export async function getUserAIConfig(
	userId: string,
): Promise<UserAIConfig | null> {
	try {
		const { data, error } = await getSupabase()
			.from("ai_config")
			.select("provider, api_key, model, base_url")
			.eq("user_id", userId)
			.maybeSingle();

		if (!error && data?.api_key) {
			// Decrypt stored key; if decrypt fails AND key looks encrypted, bail
			let apiKey: string;
			try {
				const { decrypt } = await import("./encryption.js");
				apiKey = decrypt(data.api_key);
			} catch {
				// Only use raw value if it looks like a plaintext API key (not encrypted blob)
				if (data.api_key.startsWith("AI") || data.api_key.length < 100) {
					apiKey = data.api_key;
				} else {
					logger.warn("[aiConfig] Key appears encrypted but decrypt failed", {
						userId,
					});
					return null;
				}
			}

			// flash-lite copies examples verbatim — always upgrade to flash
			let model = data.model || undefined;
			if (model?.includes("flash-lite")) {
				model = "gemini-2.5-flash";
			}

			return {
				provider: data.provider || "gemini",
				apiKey,
				baseUrl: data.base_url || undefined,
				model,
				source: "user",
			};
		}
	} catch (err) {
		logger.warn("[aiConfig] Failed to fetch ai_config", {
			userId,
			error: String(err),
		});
	}

	// No user key — fall back to env vars
	return getEnvFallbackConfig(userId);
}

/**
 * Env var fallback: respects workspace-level ai_provider preference.
 */
async function getEnvFallbackConfig(
	userId: string,
): Promise<UserAIConfig | null> {
	try {
		const { data: wsConfig } = await getSupabaseAny()
			.from("auto_post_config")
			.select("ai_provider")
			.eq("user_id", userId)
			.maybeSingle();

		const wsProvider = (wsConfig as { ai_provider?: string | undefined } | null)
			?.ai_provider;

		if (wsProvider === "xai" && process.env.XAI_API_KEY) {
			return {
				provider: "xai",
				apiKey: process.env.XAI_API_KEY,
				model: "grok-4-1-fast",
				source: "env_fallback",
			};
		}
		// Prefer OpenAI (GPT-4o-mini) over Gemini — Gemini's verbosity is architectural
		if (process.env.OPENAI_API_KEY) {
			return {
				provider: "openai",
				apiKey: process.env.OPENAI_API_KEY,
				model: "gpt-4o-mini",
				source: "env_fallback",
			};
		}
		if (process.env.GEMINI_API_KEY) {
			return {
				provider: "gemini",
				apiKey: process.env.GEMINI_API_KEY,
				model: "gemini-2.5-flash",
				source: "env_fallback",
			};
		}
	} catch {
		// Last resort: try env vars without workspace config
		if (process.env.OPENAI_API_KEY) {
			return {
				provider: "openai",
				apiKey: process.env.OPENAI_API_KEY,
				model: "gpt-4o-mini",
				source: "env_fallback",
			};
		}
		if (process.env.GEMINI_API_KEY) {
			return {
				provider: "gemini",
				apiKey: process.env.GEMINI_API_KEY,
				model: "gemini-2.5-flash",
				source: "env_fallback",
			};
		}
	}

	logger.info(
		"[aiConfig] No AI config: ai_config table empty and no env var fallback",
		{ userId },
	);
	return null;
}

// ============================================================================
// Provider Resolution (workspace override + load-split)
// ============================================================================

export interface ResolveProviderOptions {
	/** Workspace-level ai_provider preference (from auto_post_config) */
	workspaceProvider?: string | undefined;
	/** Fraction of Gemini calls to route to xAI (0-1, default 0.3) */
	xaiLoadSplitRatio?: number | undefined;
	/**
	 * Hero/tone-critical flag (W3). When true AND ANTHROPIC_API_KEY is set,
	 * routes to Claude Haiku 4.5 regardless of workspace preference or split.
	 * Defaults to false so regular posts stay on the xAI/Gemini split.
	 */
	isHeroPost?: boolean | undefined;
	/** Explicitly allow user-key flows to move onto platform env keys. */
	allowPlatformFallback?: boolean | undefined;
}

/**
 * Apply workspace-level provider overrides and load-splitting on top of
 * the base getUserAIConfig result.
 *
 * Consolidates identical logic that was duplicated in configResolver.ts
 * and queueFill.ts.
 *
 * Order:
 * 0. If isHeroPost AND ANTHROPIC_API_KEY set → use Claude Haiku 4.5 (W3)
 * 1. If workspace wants xAI and XAI_API_KEY is set → use xAI
 * 2. If provider is Gemini and no explicit workspace pref → 30% load-split to xAI
 * 3. Otherwise return base config unchanged
 */
export function resolveProvider(
	baseConfig: UserAIConfig | null,
	options: ResolveProviderOptions = {},
): UserAIConfig | null {
	if (!baseConfig) return null;

	const {
		workspaceProvider,
		xaiLoadSplitRatio = 0.3,
		isHeroPost,
		allowPlatformFallback = false,
	} = options;
	const canUsePlatformFallback =
		baseConfig.source !== "user" || allowPlatformFallback;

	if (!canUsePlatformFallback) {
		return baseConfig;
	}

	// W3 model router: hero / tone-critical posts → Claude Haiku 4.5.
	// Only takes effect when ANTHROPIC_API_KEY is configured; otherwise
	// falls through to the existing xAI/Gemini routing (fail-open).
	if (isHeroPost) {
		const anthropicKey = process.env.ANTHROPIC_API_KEY;
		if (anthropicKey) {
			return {
				provider: "anthropic",
				apiKey: anthropicKey,
				model: "claude-haiku-4-5-20251001",
				source: "env_fallback",
			};
		}
		logger.debug(
			"[aiConfig] isHeroPost=true but ANTHROPIC_API_KEY not set; falling through",
		);
	}

	// Workspace explicit override to xAI
	if (workspaceProvider === "xai") {
		const xaiKey = process.env.XAI_API_KEY;
		if (xaiKey) {
			return {
				provider: "xai",
				apiKey: xaiKey,
				model: "grok-4-1-fast",
				source: "env_fallback",
			};
		}
		logger.warn("[aiConfig] Workspace wants xai but XAI_API_KEY not set");
	}

	// Load-split: route a fraction of Gemini calls to xAI for cost/performance balance
	if (baseConfig.provider === "gemini" && !workspaceProvider) {
		const xaiKey = process.env.XAI_API_KEY;
		if (xaiKey && Math.random() < xaiLoadSplitRatio) {
			return {
				provider: "xai",
				apiKey: xaiKey,
				model: "grok-4-1-fast",
				source: "env_fallback",
			};
		}
	}

	return baseConfig;
}

// ============================================================================
// Key Health Check (Phase 4) + Discord Alert (Phase 5)
// ============================================================================

/**
 * Redis key for AI key health status. TTLs:
 * - Valid key: cached for 1 hour (avoid repeated checks in hot cron loops)
 * - Invalid key: cached for 5 minutes (allow quick retry after key rotation)
 */
const HEALTH_KEY_PREFIX = "ai_key_health:";
const HEALTH_VALID_TTL = TTL_1_HOUR;
const HEALTH_INVALID_TTL = TTL_5_MIN;
const ALERT_DEDUP_PREFIX = "ai_key_alert:";
const ALERT_DEDUP_TTL = TTL_1_HOUR;

/**
 * Check if an AI key is healthy (can make API calls).
 * Results are cached in Redis to avoid hammering provider APIs.
 *
 * @returns true if key is valid, false if invalid/unknown
 */
export async function isKeyHealthy(
	config: UserAIConfig,
	userId: string,
): Promise<boolean> {
	// Env fallback keys are assumed healthy (managed by us, not user)
	if (config.source === "env_fallback") return true;

	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();
		const cacheKey = `${HEALTH_KEY_PREFIX}${userId}`;

		// Check cache first
		const cached = await redis.get<string>(cacheKey);
		if (cached === "valid") return true;
		if (cached === "invalid") return false;

		// No cache — validate with a lightweight API call
		const valid = await validateKeyWithProvider(config);

		// Cache result
		await redis.set(cacheKey, valid ? "valid" : "invalid", {
			ex: valid ? HEALTH_VALID_TTL : HEALTH_INVALID_TTL,
		});

		// Fire Discord alert on failure
		if (!valid) {
			await alertKeyFailure(userId, config.provider);
		}

		return valid;
	} catch {
		// Redis down or other infra error — fail open (assume healthy)
		return true;
	}
}

/**
 * Invalidate the cached health status for a user's AI key.
 * Call this when a key is updated (e.g., POST /api/ai/keys).
 */
export async function invalidateKeyHealth(userId: string): Promise<void> {
	try {
		const { getRedis } = await import("./redis.js");
		await getRedis().del(`${HEALTH_KEY_PREFIX}${userId}`);
	} catch {
		/* non-blocking */
	}
}

/**
 * Lightweight validation: send a minimal request to the provider's API.
 * Gemini: list models (free, fast). xAI/OpenAI: empty completions with max_tokens=1.
 */
async function validateKeyWithProvider(config: UserAIConfig): Promise<boolean> {
	try {
		if (config.provider === "gemini") {
			const baseUrl = (
				config.baseUrl || "https://generativelanguage.googleapis.com"
			).replace(/\/$/, "");
			const res = await withRetry(
				() =>
					fetch(`${baseUrl}/v1beta/models?key=${config.apiKey}&pageSize=1`, {
						signal: AbortSignal.timeout(8000),
					}),
				{ label: "ai-config:gemini-key-health" },
			);
			return res.ok;
		}

		if (config.provider === "xai") {
			const res = await withRetry(
				() =>
					fetch("https://api.x.ai/v1/models", {
						headers: { Authorization: `Bearer ${config.apiKey}` },
						signal: AbortSignal.timeout(8000),
					}),
				{ label: "ai-config:xai-key-health" },
			);
			return res.ok;
		}

		if (config.provider === "openai") {
			const res = await withRetry(
				() =>
					fetch("https://api.openai.com/v1/models", {
						headers: { Authorization: `Bearer ${config.apiKey}` },
						signal: AbortSignal.timeout(8000),
					}),
				{ label: "ai-config:openai-key-health" },
			);
			return res.ok;
		}

		if (config.provider === "anthropic") {
			// Anthropic doesn't have a list-models endpoint; use a minimal message
			const res = await withRetry(
				() =>
					fetch("https://api.anthropic.com/v1/messages", {
						method: "POST",
						headers: {
							"Content-Type": "application/json",
							"x-api-key": config.apiKey,
							"anthropic-version": "2023-06-01",
						},
						body: JSON.stringify({
							model: config.model || "claude-3-5-sonnet-20241022",
							max_tokens: 1,
							messages: [{ role: "user", content: "hi" }],
						}),
						signal: AbortSignal.timeout(8000),
					}),
				{ label: "ai-config:anthropic-key-health" },
			);
			// 200 = valid, 401/403 = invalid key, anything else = infra issue (assume valid)
			if (res.status === 401 || res.status === 403) return false;
			return true;
		}

		// Unknown provider — assume valid
		return true;
	} catch {
		// Timeout or network error — assume valid (don't block on infra issues)
		return true;
	}
}

/**
 * Fire a Discord alert for AI key failure, deduped 1/hr/user via Redis.
 */
async function alertKeyFailure(
	userId: string,
	provider: string,
): Promise<void> {
	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();
		const dedupKey = `${ALERT_DEDUP_PREFIX}${userId}`;

		// Check dedup
		const existing = await redis.get(dedupKey);
		if (existing) return;

		// Set dedup lock
		await redis.set(dedupKey, "1", { ex: ALERT_DEDUP_TTL });

		// Fire alert
		const { alert, AlertLevel } = await import("./alerting.js");
		await alert(AlertLevel.ERROR, "AI API key validation failed", {
			userId: `${userId.substring(0, 8)}...`,
			provider,
			action:
				"User's AI key returned 401/403. Check ai_config table or ask user to re-enter key.",
		});
	} catch {
		// Non-blocking — alert failure must never break the pipeline
	}
}
