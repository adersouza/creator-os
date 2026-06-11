import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
/**
 * GET /api/ai/low-hanging-fruit?accountId=...&platform=...
 *
 * Returns top 3 low-hanging-fruit recommendations for an account.
 */

import { getLowHangingFruit } from "../../lowHangingFruit.js";
import { withAuth } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { requireMinTier } from "../../tierGate.js";

export default withAuth(async (req, res, user) => {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	// Tier gate — Quick Wins requires Pro or higher
	if (!(await requireMinTier(user.id, "pro", res))) return;

	const accountId = req.query.accountId as string;
	const platform = (req.query.platform as string) || "threads";

	if (!accountId) {
		return apiError(res, 400, "accountId is required");
	}

	// Rate limit: 30 requests/hour per user
	const rl = await checkRateLimit({
		key: `low-hanging:${user.id}`,
		limit: 30,
		windowSeconds: 3600,
		failMode: "closed",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "Rate limit exceeded. Please wait a moment.");
	}

	try {
		const result = await getLowHangingFruit(user.id, accountId, platform);
		return apiSuccess(res, {
			recommendations: result.recommendations,
			solved: result.solved,
			regressed: result.regressed,
		});
	} catch (err) {
		logger.error("[ai/low-hanging-fruit] Failed to generate recommendations", {
			error: String(err),
		});
		return apiError(res, 500, "Failed to generate recommendations");
	}
});
