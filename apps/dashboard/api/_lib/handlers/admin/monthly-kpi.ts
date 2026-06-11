/**
 * GET /api/admin/monthly-kpi
 *
 * Returns the latest monthly KPI data from Redis.
 */

import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAdminRole } from "../../middleware.js";
import { getRedis } from "../../redis.js";

export default withAdminRole(async (req, res, user) => {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	// #671: Rate limit admin endpoints
	const { checkRateLimit } = await import("../../rateLimiter.js");
	const rl = await checkRateLimit({
		key: `admin-kpi:${user.id}`,
		limit: 30,
		windowSeconds: 60,
		failMode: "open",
	});
	if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

	try {
		const redis = getRedis();
		const now = new Date();
		const yearMonth = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;

		// Try current month first, then previous month
		let data = await redis.get(`kpi:monthly:${yearMonth}`);
		if (!data) {
			const prev = new Date(now.getUTCFullYear(), now.getUTCMonth() - 1);
			const prevYM = `${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, "0")}`;
			data = await redis.get(`kpi:monthly:${prevYM}`);
		}

		if (!data) {
			return apiSuccess(res, { data: null });
		}

		const parsed = typeof data === "string" ? JSON.parse(data) : data;
		return apiSuccess(res, { data: parsed });
	} catch (error) {
		logger.error("[admin/monthly-kpi] Failed", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
