/**
 * Get inspiration idea status counts.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiSuccess, serverError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db, type InspirationIdeaStatusRow } from "./shared.js";

export async function handleGetCounts(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	try {
		const { data, error } = await db()
			.from("inspiration_ideas")
			.select("status")
			.eq("user_id", userId)
			.or("status.is.null,status.neq.dismissed");

		if (error) throw error;

		const ideas = (data || []) as InspirationIdeaStatusRow[];

		const counts = {
			total: ideas.length,
			pending: ideas.filter((d) => d.status === "pending").length,
			saved: ideas.filter((d) => d.status === "saved").length,
			queued: ideas.filter((d) => d.status === "queued").length,
		};

		return apiSuccess(res, { counts });
	} catch (error: unknown) {
		logger.error("Get counts error", { error: String(error) });
		return serverError(res, "Internal server error");
	}
}
