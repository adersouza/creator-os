/**
 * Update user's inspiration configuration.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiSuccess, serverError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db } from "./shared.js";

export async function handleUpdateConfig(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const updates = req.body;

	try {
		// Map to database column names
		const dbUpdates: Record<string, unknown> = {};
		if (updates.enabled !== undefined) dbUpdates.enabled = updates.enabled;
		if (updates.ideasPerCompetitor !== undefined)
			dbUpdates.ideas_per_competitor = updates.ideasPerCompetitor;
		if (updates.adaptationStyle !== undefined)
			dbUpdates.adaptation_style = updates.adaptationStyle;
		if (updates.topicFilters !== undefined)
			dbUpdates.topic_filters = updates.topicFilters;
		if (updates.notifyNewIdeas !== undefined)
			dbUpdates.notify_new_ideas = updates.notifyNewIdeas;
		if (updates.dailyDigestEnabled !== undefined)
			dbUpdates.daily_digest_enabled = updates.dailyDigestEnabled;

		const { error } = await db()
			.from("inspiration_config")
			.upsert({
				user_id: userId,
				...dbUpdates,
			});

		if (error) throw error;

		return apiSuccess(res);
	} catch (error: unknown) {
		logger.error("Update config error", { error: String(error) });
		return serverError(res, "Internal server error");
	}
}
