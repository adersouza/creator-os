import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getRedis } from "../../redis.js";

/**
 * GET /api/user/rec-profile
 * Returns per-category recommendation success rates from Redis.
 */
async function handler(
	req: VercelRequest,
	res: VercelResponse,
	user: { id: string },
) {
	if (req.method !== "GET") {
		return apiError(res, 405, "Method not allowed");
	}

	try {
		const redis = getRedis();
		const key = `rec:success:${user.id}`;

		// #632: Read from hash structure (compatible with HINCRBY writes from recSuccessModel)
		const raw = await redis.hgetall(key);
		if (!raw || Object.keys(raw).length === 0) {
			return apiSuccess(res, { categories: [] });
		}

		// Reconstruct category stats from hash fields like "category:acted", "category:improved"
		const data: Record<string, { acted: number; improved: number }> = {};
		for (const [field, value] of Object.entries(raw)) {
			const lastColon = field.lastIndexOf(":");
			if (lastColon === -1) continue;
			const cat = field.substring(0, lastColon);
			const metric = field.substring(lastColon + 1);
			if (!data[cat]) data[cat] = { acted: 0, improved: 0 };
			if (metric === "acted") data[cat].acted = Number(value) || 0;
			if (metric === "improved") data[cat].improved = Number(value) || 0;
		}

		const categories = Object.entries(data).map(([category, stats]) => ({
			category,
			acted: stats.acted,
			improved: stats.improved,
			rate:
				stats.acted > 0 ? Math.round((stats.improved / stats.acted) * 100) : 50,
		}));

		return apiSuccess(res, { categories });
	} catch (err) {
		logger.error("[rec-profile] Error", { error: String(err) });
		return apiError(res, 500, "Internal server error");
	}
}

export default withAuth(handler);
