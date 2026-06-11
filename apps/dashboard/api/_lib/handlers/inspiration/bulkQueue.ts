/**
 * Bulk-queue top inspiration ideas to auto-post queue (Empire tier only).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	badRequest,
	serverError,
} from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { getUserTier } from "../../tierGate.js";
import {
	BulkQueueSchema,
	db,
	type InspirationIdeaContentRow,
	type WorkspaceRow,
} from "./shared.js";

export async function handleBulkQueue(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	// Check tier - only Empire can bulk queue
	const tier = await getUserTier(userId);
	if (tier !== "empire") {
		return apiError(res, 403, "Bulk queue is Empire tier only");
	}

	const parsed = BulkQueueSchema.safeParse(req.body);
	if (!parsed.success) {
		return badRequest(res, `Invalid input: ${parsed.error.issues[0]?.message}`);
	}
	const { count } = parsed.data;

	try {
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

		// Get top ideas that aren't already queued
		const { data: ideas, error: fetchError } = await db()
			.from("inspiration_ideas")
			.select("id, adapted_content")
			.eq("user_id", userId)
			.in("status", ["pending", "saved"])
			.eq("queued", false)
			.order("viral_score", { ascending: false })
			.limit(count);

		if (fetchError) throw fetchError;

		let queued = 0;
		let failed = 0;

		for (const idea of (ideas || []) as InspirationIdeaContentRow[]) {
			try {
				// Add to auto-post queue
				await db()
					.from("auto_post_queue")
					.insert({
						workspace_id: workspaceData.id,
						content: idea.adapted_content ?? "",
						status: "queued",
						source_type: "inspiration",
						scheduled_for: new Date().toISOString(),
					});

				// Update idea status
				await db()
					.from("inspiration_ideas")
					.update({
						status: "queued",
						queued: true,
						queued_at: new Date().toISOString(),
					})
					.eq("id", idea.id);

				queued++;
			} catch (err) {
				logger.debug("Failed to queue inspiration idea", {
					ideaId: idea.id,
					error: String(err),
				});
				failed++;
			}
		}

		return apiSuccess(res, { queued, failed });
	} catch (error: unknown) {
		logger.error("Bulk queue error", { error: String(error) });
		return serverError(res, "Internal server error");
	}
}
