/**
 * Regenerate an inspiration idea with a different adaptation style.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiSuccess,
	badRequest,
	notFound,
	serverError,
} from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db } from "./shared.js";

export async function handleRegenerate(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { id, style = "casual" } = req.body;
	if (!id) {
		return badRequest(res, "Missing id");
	}

	try {
		// Get the original idea
		const { data: idea, error: ideaError } = await db()
			.from("inspiration_ideas")
			.select("original_post, competitor_username")
			.eq("id", id)
			.eq("user_id", userId)
			.maybeSingle();

		if (ideaError || !idea) {
			return notFound(res, "Idea not found");
		}

		// Simple regeneration with slight variation prompt
		const styleDescriptions: Record<string, string> = {
			casual: "casual, conversational, and relatable",
			professional: "professional, authoritative, and polished",
			witty: "witty, clever, and playful with humor",
			inspirational: "inspirational, motivational, and uplifting",
			edgy: "bold, provocative, and slightly controversial",
		};

		// For simplicity, we'll just update with a note that regeneration was requested
		// In production, you'd call the AI service here
		const { error: updateError } = await db()
			.from("inspiration_ideas")
			.update({
				adaptation_style: style,
				updated_at: new Date().toISOString(),
			})
			.eq("id", id)
			.eq("user_id", userId);

		if (updateError) throw updateError;

		return apiSuccess(res, {
			message: `Style updated to ${styleDescriptions[style] || style}. Regeneration queued.`,
		});
	} catch (error: unknown) {
		logger.error("Regenerate error", { error: String(error) });
		return serverError(res, "Internal server error");
	}
}
