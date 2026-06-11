/**
 * Get competitors that have generated inspiration ideas (with counts).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiSuccess, serverError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db, type InspirationIdeaCompetitorRow } from "./shared.js";

export async function handleGetCompetitors(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	try {
		const { data, error } = await db()
			.from("inspiration_ideas")
			.select("competitor_username, competitor_avatar_url")
			.eq("user_id", userId)
			.or("status.is.null,status.neq.dismissed");

		if (error) throw error;

		const ideas = (data || []) as InspirationIdeaCompetitorRow[];

		// Group by username
		const grouped = ideas.reduce(
			(acc, row) => {
				const username = row.competitor_username;
				if (!acc[username]) {
					acc[username] = {
						username,
						avatarUrl: row.competitor_avatar_url,
						count: 0,
					};
				}
				acc[username].count++;
				return acc;
			},
			{} as Record<
				string,
				{ username: string; avatarUrl?: string | undefined; count: number }
			>,
		);

		const competitors = (
			Object.values(grouped) as {
				username: string;
				avatarUrl?: string | undefined;
				count: number;
			}[]
		).sort((a, b) => b.count - a.count);

		return apiSuccess(res, { competitors });
	} catch (error: unknown) {
		logger.error("Get competitors error", { error: String(error) });
		return serverError(res, "Internal server error");
	}
}
