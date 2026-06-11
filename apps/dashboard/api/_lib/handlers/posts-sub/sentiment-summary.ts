/**
 * Post Sentiment Summary — Redis-cached aggregation
 *
 * GET /api/posts?action=sentiment-summary&postId=...
 * GET /api/posts?action=sentiment-summary&postIds=id1,id2,id3  (batch, max 50)
 *
 * Returns pre-computed sentiment data accumulated from webhook processing.
 * Much faster than sentiment-scan (no DB query, no re-analysis).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { withAuthDb } from "../../middleware.js";

type UserDb = DbContext["userDb"];

async function handleSentimentSummary(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	const postId = req.query.postId as string | undefined;
	const postIds = req.query.postIds as string | undefined;

	if (!postId && !postIds) {
		return apiError(res, 400, "postId or postIds is required");
	}

	const { getPostSentimentSummary, getPostSentimentSummaries } = await import(
		"../../sentimentTracker.js"
	);

	// Single post
	if (postId) {
		const { data: ownedPost, error: ownedPostError } = await userDb
			.from("posts")
			.select("id")
			.eq("id", postId)
			.eq("user_id", userId)
			.maybeSingle();
		if (ownedPostError) {
			return apiError(res, 500, "Failed to verify post ownership");
		}
		if (!ownedPost) {
			return apiError(res, 404, "Post not found");
		}

		const summary = await getPostSentimentSummary(postId);
		if (!summary) {
			return apiSuccess(res, {
				postId,
				total: 0,
				breakdown: { positive: 0, negative: 0, neutral: 0, question: 0 },
				score: 0,
				verdict: "No sentiment data",
			});
		}
		return apiSuccess(res, summary as unknown as Record<string, unknown>);
	}

	// Batch
	const ids = (postIds as string)
		.split(",")
		.map((id) => id.trim())
		.filter(Boolean)
		.slice(0, 50);

	if (ids.length === 0) {
		return apiError(res, 400, "postIds must contain at least one ID");
	}

	const { data: ownedPosts, error: ownedPostsError } = await userDb
		.from("posts")
		.select("id")
		.eq("user_id", userId)
		.in("id", ids);
	if (ownedPostsError) {
		return apiError(res, 500, "Failed to verify post ownership");
	}

	const ownedIds = (ownedPosts || []).map((p: { id: string }) => p.id);
	const summaries = await getPostSentimentSummaries(ownedIds);
	const result: Record<string, unknown> = {};
	for (const id of ownedIds) {
		result[id] = summaries.get(id) || {
			postId: id,
			total: 0,
			breakdown: { positive: 0, negative: 0, neutral: 0, question: 0 },
			score: 0,
			verdict: "No sentiment data",
		};
	}

	return apiSuccess(res, { summaries: result });
}

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, context) =>
		handleSentimentSummary(req, res, context.user.id, context.userDb),
);
