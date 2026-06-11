/**
 * Handler: POST /api/ai?action=generate-single
 *
 * Generate a single post with specific constraints.
 * Lightweight alternative to full batch generation — useful for:
 * - Reactive content (trending topic + specific media)
 * - Regenerating a low-scoring post
 * - On-demand content for specific content types
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { checkAIRateLimit } from "../../aiRateLimit.js";
import { apiError, apiSuccess, getAuthUserOrError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getSupabase } from "../../supabase.js";
import { requireMinTier } from "../../tierGate.js";
import { parseBodyOrError } from "../../validation.js";
import { z, zEnum } from "../../zodCompat.js";

const GenerateSingleSchema = z.object({
	groupId: z.string().min(1),
	contentType: z.string().optional(),
	mediaDescription: z.string().optional(),
	trendingTopic: z.string().optional(),
	platform: zEnum(["threads", "instagram"]).optional(),
});

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST") return apiError(res, 405, "POST only");

	const user = await getAuthUserOrError(req, res);
	if (!user) return;

	const parsed = parseBodyOrError(res, GenerateSingleSchema, req.body);
	if (!parsed) return;
	if (!(await requireMinTier(user.id, "pro", res))) return;
	const rl = await checkAIRateLimit(user.id, "generate-single");
	if (!rl.allowed) {
		return apiError(res, 429, "AI rate limit exceeded. Try again shortly.");
	}

	const { groupId, contentType, mediaDescription, trendingTopic, platform } =
		parsed;

	try {
		// Load group voice profile + content strategy
		const { data: group } = await getSupabase()
			.from("account_groups")
			.select("voice_profile, content_strategy")
			.eq("id", groupId)
			.eq("user_id", user.id)
			.maybeSingle();

		if (!group) return apiError(res, 404, "Group not found");

		// Get AI config
		const { getUserAIConfig, generateSinglePost } = await import(
			"../auto-post/contentSelection.js"
		);
		const aiConfig = await getUserAIConfig(user.id);
		if (!aiConfig?.apiKey) {
			return apiError(res, 400, "No AI API key configured");
		}

		const voiceProfile =
			typeof group.voice_profile === "string"
				? { voice_profile: group.voice_profile }
				: (group.voice_profile as Record<string, unknown> | null);

		const result = await generateSinglePost(
			user.id,
			aiConfig.apiKey,
			{
				contentType,
				mediaDescription,
				trendingTopic,
				platform: platform || "threads",
				groupId,
			},
			voiceProfile,
			group.content_strategy as Record<string, unknown> | null,
		);

		if (!result) {
			return apiError(
				res,
				422,
				"Failed to generate post — try different constraints",
			);
		}

		return apiSuccess(res, result);
	} catch (err) {
		logger.error("generate-single failed", { error: String(err) });
		return apiError(res, 500, "Generation failed");
	}
}
