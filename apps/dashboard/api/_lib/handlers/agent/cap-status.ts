/**
 * Agent Publish Cap Status
 *
 * GET /api/agent/cap-status?accountId=X&platform=threads|instagram
 *
 * Lightweight endpoint so the agent can self-check remaining daily budget
 * before attempting to publish (avoids discovering the cap via a 429).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../../apiResponse.js";
import { checkDailyCap } from "../../dailyCap.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

		const { accountId, platform } = req.query as {
			accountId?: string | undefined;
			platform?: string | undefined;
		};

		if (!accountId) return apiError(res, 400, "accountId is required");

		const plat = platform === "instagram" ? "instagram" : ("threads" as const);
		const accountTable =
			plat === "instagram" ? "instagram_accounts" : "accounts";
		const { data: ownedAccount } = await getSupabase()
			.from(accountTable)
			.select("id")
			.eq("id", accountId)
			.eq("user_id", user.id)
			.maybeSingle();

		if (!ownedAccount) return apiError(res, 404, "Account not found");

		const result = await checkDailyCap(accountId, plat);

		return apiSuccess(res, {
			accountId,
			platform: plat,
			used: result.used,
			limit: result.limit,
			remaining: result.limit - result.used,
			allowed: result.allowed,
		});
	},
);
