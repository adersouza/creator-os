/**
 * Get inspiration ideas with filtering, sorting, and pagination.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiSuccess, serverError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { db, type InspirationIdeaRow } from "./shared.js";

export async function handleGetIdeas(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const {
		competitor,
		minScore,
		maxScore,
		status,
		saved,
		queued,
		topicTag,
		sortBy = "viral_score",
		sortOrder = "desc",
		limit = 50,
		offset = 0,
	} = req.body || {};

	try {
		let query = db()
			.from("inspiration_ideas")
			.select("*")
			.eq("user_id", userId)
			.or("status.is.null,status.neq.dismissed");

		// Apply filters
		if (competitor) query = query.eq("competitor_username", competitor);
		if (minScore !== undefined) query = query.gte("viral_score", minScore);
		if (maxScore !== undefined) query = query.lte("viral_score", maxScore);
		if (status) {
			if (Array.isArray(status)) {
				query = query.in("status", status);
			} else {
				query = query.eq("status", status);
			}
		}
		if (saved !== undefined) query = query.eq("saved", saved);
		if (queued !== undefined) query = query.eq("queued", queued);
		if (topicTag) query = query.contains("topic_tags", [topicTag]);

		// Sorting and pagination
		query = query
			.order(sortBy, { ascending: sortOrder === "asc" })
			.range(offset, offset + limit - 1);

		const { data, error } = await query;

		if (error) throw error;

		// Transform snake_case to camelCase for frontend
		const ideas = ((data || []) as unknown as InspirationIdeaRow[]).map(
			(row) => ({
				id: row.id,
				userId: row.user_id,
				workspaceId: row.workspace_id,
				originalPost: row.original_post,
				competitorId: row.competitor_id,
				competitorUsername: row.competitor_username || "unknown",
				competitorAvatarUrl: row.competitor_avatar_url,
				adaptedContent: row.adapted_content || "",
				viralScore: row.viral_score || 0,
				aiInsight: row.ai_insight || "",
				topicTags: row.topic_tags || [],
				adaptationStyle: row.adaptation_style,
				adaptationAngle: row.adaptation_angle,
				viralFormula: row.viral_formula,
				status: row.status,
				saved: row.saved,
				queued: row.queued,
				queuedAt: row.queued_at,
				postedAt: row.posted_at,
				generatedAt: row.generated_at,
				expiresAt: row.expires_at,
				createdAt: row.created_at,
			}),
		);

		return apiSuccess(res, { ideas });
	} catch (error: unknown) {
		logger.error("Get ideas error", { error: String(error) });
		return serverError(res, "Internal server error");
	}
}
