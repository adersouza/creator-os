/**
 * Fetch the authenticated user's AI API key.
 *
 * Thin wrapper around the canonical getUserAIConfig (api/_lib/aiConfig.ts).
 * Kept for backward compatibility — 10+ callers import getUserAIKey.
 */

import { getUserAIConfig } from "./aiConfig.js";

export interface UserAIKeyResult {
	apiKey: string;
	source: "user" | "env_fallback";
}

/**
 * Resolve the AI API key for a given user.
 * Delegates to the canonical getUserAIConfig for decryption, fallback, etc.
 */
export async function getUserAIKey(
	userId: string,
): Promise<UserAIKeyResult | null> {
	const config = await getUserAIConfig(userId);
	if (!config) return null;
	return { apiKey: config.apiKey, source: config.source || "user" };
}
