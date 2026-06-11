/**
 * Queue a single inspiration idea to auto-post queue (Empire tier only).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	badRequest,
	notFound,
	serverError,
} from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getUserTier } from "../../tierGate.js";
import {
	db,
	IdSchema,
	type InspirationIdeaContentRow,
	type WorkspaceRow,
} from "./shared.js";

export async function handleQueue(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	// Check tier - only Empire can queue
	const tier = await getUserTier(userId);
	if (tier !== "empire") {
		return apiError(res, 403, "Auto-queue is Empire tier only");
	}

	const parsed = IdSchema.safeParse(req.body);
	if (!parsed.success) {
		return badRequest(res, `Invalid input: ${parsed.error.issues[0]?.message}`);
	}
	const { id } = parsed.data;

	try {
		// Get the idea content
		const { data: idea, error: ideaError } = await db()
			.from("inspiration_ideas")
			.select("adapted_content")
			.eq("id", id)
			.eq("user_id", userId)
			.maybeSingle();

		if (ideaError || !idea) {
			return notFound(res, "Idea not found");
		}

		const ideaData = idea as InspirationIdeaContentRow;

		// Get user's workspace
		const { data: workspace } = await db()
			.from("workspaces")
			.select("id")
			.eq("owner_id", userId)
			.limit(1)
			.maybeSingle();

		if (!workspace) {
			return badRequest(res, "No workspace found");
		}

		const workspaceData = workspace as WorkspaceRow;

		// Add to auto-post queue
		const { error: queueError } = await db()
			.from("auto_post_queue")
			.insert({
				workspace_id: workspaceData.id,
				content: ideaData.adapted_content ?? "",
				status: "queued",
				source_type: "inspiration",
				scheduled_for: new Date().toISOString(),
			});

		if (queueError) throw queueError;

		// Update idea status
		const { error: updateError } = await db()
			.from("inspiration_ideas")
			.update({
				status: "queued",
				queued: true,
				queued_at: new Date().toISOString(),
			})
			.eq("id", id)
			.eq("user_id", userId);

		if (updateError) throw updateError;

		return apiSuccess(res);
	} catch (error: unknown) {
		logger.error("Queue idea error", { error: String(error) });
		return serverError(res, "Internal server error");
	}
}
