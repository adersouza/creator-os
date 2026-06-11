/**
 * Flush IG Insights Cache
 * DELETE /api/instagram/flush-insights-cache?accountId=<id>
 *
 * Removes the ig-no-insights Redis key so the next sync will re-attempt
 * fetching insights for accounts that may have recently gained permissions.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { withAuth } from "../../middleware.js";
import { getRedis } from "../../redis.js";
import { z } from "../../zodCompat.js";
import { verifyAnyAccountOwnership } from "../helpers/verifyOwnership.js";

const FlushSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
});

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "DELETE") {
			return apiError(res, 405, "Method not allowed");
		}

		const parsed = FlushSchema.safeParse(req.query);
		if (!parsed.success) {
			return apiError(
				res,
				400,
				parsed.error.issues[0]?.message ?? "Invalid request",
			);
		}

		const { accountId } = parsed.data;
		const owned = await verifyAnyAccountOwnership(res, accountId, user.id);
		if (!owned) return;

		const key = `ig-no-insights:${accountId}`;

		await getRedis()
			.del(key)
			.catch(() => {});

		return apiSuccess(res, { flushed: true, accountId });
	},
);
