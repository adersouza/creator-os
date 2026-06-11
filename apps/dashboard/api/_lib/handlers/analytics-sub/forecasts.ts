import { apiError, apiSuccess, badRequest } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";
import { verifyAccountOwnership } from "../helpers/verifyOwnership.js";

/**
 * Trend Forecasting API
 *
 * GET ?action=latest&accountId=X         — Get latest forecast for account
 * GET ?action=signals&accountId=X        — Get actionable signals only
 * POST action=generate&accountId=X       — Force-regenerate forecast (rate limited)
 */
export default withAuth(async (req, res, user) => {
	const action = (
		req.method === "GET" ? req.query.action : req.body?.action
	) as string;
	const accountId = (req.query.accountId || req.body?.accountId) as string;
	const supabase = getSupabase();

	try {
		switch (action) {
			case "latest": {
				if (!accountId) return badRequest(res, "accountId required");

				// Verify account ownership
				const account = await verifyAccountOwnership(res, accountId, user.id);
				if (!account) return;

				const { data } = await supabase
					.from("trend_forecasts")
					.select("*")
					.eq("user_id", user.id)
					.eq("account_id", accountId)
					.order("forecast_date", { ascending: false })
					.limit(1)
					.maybeSingle();

				return apiSuccess(res, { forecast: data || null });
			}

			case "signals": {
				if (!accountId) return badRequest(res, "accountId required");

				// #686: Verify account ownership for signals action
				const sigAccount = await verifyAccountOwnership(
					res,
					accountId,
					user.id,
				);
				if (!sigAccount) return;

				const { data } = await supabase
					.from("trend_forecasts")
					.select(
						"signals, follower_trend, engagement_trend, best_hours, rising_topics, declining_topics",
					)
					.eq("user_id", user.id)
					.eq("account_id", accountId)
					.order("forecast_date", { ascending: false })
					.limit(1)
					.maybeSingle();

				return apiSuccess(res, {
					signals: data?.signals || [],
					trends: data || null,
				});
			}

			case "generate": {
				if (req.method !== "POST") return apiError(res, 405, "POST required");
				if (!accountId) return badRequest(res, "accountId required");

				const genAccount = await verifyAccountOwnership(
					res,
					accountId,
					user.id,
				);
				if (!genAccount) return;

				// Rate limit: 1 generation per account per hour
				const { getRedis } = await import("../../redis.js");
				const redis = getRedis();
				const rateKey = `forecast-gen:${accountId}`;
				const existing = await redis.get(rateKey);
				if (existing) {
					return apiError(
						res,
						429,
						"Forecast was recently generated. Try again later.",
					);
				}
				await redis.set(rateKey, "1", { ex: 3600 });

				try {
					const { generateForecast } = await import("../../trendEngine.js");
					const forecast = await generateForecast(supabase, user.id, accountId);
					return apiSuccess(res, { forecast });
				} catch (genErr) {
					// Clear rate-limit key so user can retry after failure
					await redis.del(rateKey).catch(() => {});
					throw genErr;
				}
			}

			default:
				return badRequest(res, `Unknown action: ${action}`);
		}
	} catch (err: unknown) {
		logger.error("[forecasts] API error", { error: String(err) });
		return apiError(res, 500, "Internal server error");
	}
});

export const config = {
	maxDuration: 120,
};
