/**
 * POST /api/beta/feedback
 *
 * Submits beta feedback from an authenticated beta user.
 * Stores feedback in the beta_feedback JSONB array on the user's profile.
 */

import type { Database, Json } from "../../../../types/supabase.js";
import { apiError, apiSuccess, badRequest } from "../../apiResponse.js";
import type { DbContext } from "../../dbContext.js";
import { logger } from "../../logger.js";
import { withAuthDb } from "../../middleware.js";
import { z } from "../../zodCompat.js";

type ProfileUpdate = Database["public"]["Tables"]["profiles"]["Update"];

const FeedbackSchema = z.object({
	feedback: z
		.string()
		.min(1, "Feedback is required")
		.max(2000, "Feedback must be under 2000 characters"),
	category: z.string().optional().default("general"),
});

export default withAuthDb(async (req, res, context: DbContext) => {
	const { user, userDb } = context;
	if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

	try {
		// Verify user is a beta user
		const { data: profile } = await userDb
			.from("profiles")
			.select("is_beta_user, beta_feedback")
			.eq("id", user.id)
			.maybeSingle();

		if (!profile?.is_beta_user) {
			return apiError(res, 403, "Only beta users can submit feedback");
		}

		const parsed = FeedbackSchema.safeParse(req.body);
		if (!parsed.success) {
			return badRequest(
				res,
				parsed.error.issues[0]?.message || "Invalid input",
			);
		}

		const { feedback, category } = parsed.data;

		// Append to existing beta_feedback JSONB array on profile
		const existingFeedback = Array.isArray(profile.beta_feedback)
			? profile.beta_feedback
			: [];

		// Limit to 50 feedback entries per user to prevent abuse
		if (existingFeedback.length >= 50) {
			return apiError(
				res,
				400,
				"Feedback limit reached. Thank you for all your input!",
			);
		}

		const newEntry = {
			text: feedback,
			category,
			submitted_at: new Date().toISOString(),
		};

		const update: ProfileUpdate = {
			beta_feedback: [...existingFeedback, newEntry] as Json,
		};

		const { error } = await userDb
			.from("profiles")
			.update(update)
			.eq("id", user.id);

		if (error) {
			logger.error("[beta/feedback] Update error", { error: String(error) });
			return apiError(res, 500, "Failed to submit feedback");
		}

		logger.info("[beta/feedback] Feedback submitted", {
			userId: user.id,
			category,
			totalEntries: existingFeedback.length + 1,
		});

		return apiSuccess(res, {
			success: true,
			message: "Thank you for your feedback!",
			totalSubmitted: existingFeedback.length + 1,
		});
	} catch (err) {
		logger.error("[beta/feedback] Error", { error: String(err) });
		return apiError(res, 500, "Internal server error");
	}
});
