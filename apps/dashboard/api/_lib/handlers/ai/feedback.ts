/**
 * POST /api/ai/feedback — Store user feedback on AI features
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";

type UserDb = DbContext["userDb"];

async function handleFeedback(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
	userDb: UserDb,
) {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const rl = await checkRateLimit({
		key: `ai-feedback:${userId}`,
		limit: 20,
		windowSeconds: 3600,
		failMode: "closed",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "Too many requests");
	}

	const { feature, suggestionContent, wasUsed, wasEdited, context } =
		req.body || {};

	if (!feature || typeof feature !== "string") {
		return apiError(res, 400, "feature is required");
	}

	try {
		const { error } = await userDb.from("ai_feedback").insert({
			user_id: userId,
			feature,
			suggestion_content: suggestionContent || null,
			was_used: wasUsed ?? null,
			was_edited: wasEdited ?? null,
			context: context || null,
		});

		if (error) {
			logger.error("[ai/feedback] Insert failed", {
				userId,
				error: error.message,
			});
			return apiError(res, 500, "Failed to save feedback");
		}

		return apiSuccess(res, { saved: true });
	} catch (err: unknown) {
		logger.error("[ai/feedback] Error", {
			userId,
			error: err instanceof Error ? err.message : String(err),
		});
		return apiError(res, 500, "Internal error");
	}
}

export default withAuthDb(
	async (req: VercelRequest, res: VercelResponse, context) =>
		handleFeedback(req, res, context.user.id, context.userDb),
);
