/**
 * Get user's inspiration configuration.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiSuccess, serverError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db, type InspirationConfigRow } from "./shared.js";

export async function handleGetConfig(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	try {
		const { data, error } = await db()
			.from("inspiration_config")
			.select("*")
			.eq("user_id", userId)
			.maybeSingle();

		if (error) throw error;

		// Return default config if none exists
		if (!data) {
			return apiSuccess(res, {
				config: {
					enabled: true,
					ideasPerCompetitor: 10,
					adaptationStyle: "casual",
					topicFilters: [],
					notifyNewIdeas: true,
					dailyDigestEnabled: false,
				},
			});
		}

		const configData = data as InspirationConfigRow;

		return apiSuccess(res, {
			config: {
				enabled: configData.enabled,
				ideasPerCompetitor: configData.ideas_per_competitor,
				adaptationStyle: configData.adaptation_style,
				topicFilters: configData.topic_filters || [],
				notifyNewIdeas: configData.notify_new_ideas,
				dailyDigestEnabled: configData.daily_digest_enabled,
				lastScanAt: configData.last_scan_at,
			},
		});
	} catch (error: unknown) {
		logger.error("Get config error", { error: String(error) });
		return serverError(res, "Internal server error");
	}
}
