/**
 * GET/POST /api/ai/keys — Manage per-user AI API keys
 *
 * GET:  Returns masked keys for the authenticated user
 * POST: Saves/updates the user's AI API keys
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { encrypt } from "../../encryption.js";
import { withAuth } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { getSupabase } from "../../supabase.js";

function maskKey(key: string | null | undefined): string | null {
	if (!key || key.length < 8) return key ? "****" : null;
	return `${key.slice(0, 4)}…${key.slice(-4)}`;
}

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		const supabase = getSupabase();

		if (req.method === "GET") {
			const { data, error } = await supabase
				.from("ai_config")
				.select("provider, api_key, model, base_url, updated_at")
				.eq("user_id", user.id)
				.maybeSingle();

			if (error) {
				return apiError(res, 500, "Failed to fetch AI config");
			}

			return apiSuccess(res, {
				provider: data?.provider || null,
				apiKey: maskKey(data?.api_key),
				hasKey: Boolean(data?.api_key),
				model: data?.model || null,
				baseUrl: data?.base_url || null,
				updatedAt: data?.updated_at || null,
			});
		}

		if (req.method === "POST") {
			const rl = await checkRateLimit({
				key: `ai-keys:${user.id}`,
				limit: 10,
				windowSeconds: 3600,
				failMode: "closed",
			});
			if (!rl.allowed) {
				return apiError(res, 429, "Too many requests");
			}

			const { provider, apiKey, model, baseUrl } = req.body || {};

			if (!apiKey || typeof apiKey !== "string") {
				return apiError(res, 400, "apiKey is required");
			}

			const { error } = await supabase.from("ai_config").upsert(
				{
					user_id: user.id,
					provider: provider || "gemini",
					api_key: encrypt(apiKey),
					model: model || null,
					base_url: baseUrl || null,
					updated_at: new Date().toISOString(),
				},
				{ onConflict: "user_id" },
			);

			if (error) {
				return apiError(res, 500, "Failed to save AI config");
			}

			// Clear cached health status so next check validates the new key
			try {
				const { invalidateKeyHealth } = await import("../../aiConfig.js");
				await invalidateKeyHealth(user.id);
			} catch {
				/* non-blocking */
			}

			return apiSuccess(res, { saved: true });
		}

		return apiError(res, 405, "Method not allowed");
	},
);
