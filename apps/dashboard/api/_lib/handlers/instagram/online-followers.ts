/**
 * Instagram Online Followers API
 * GET /api/instagram/online-followers?accountId={uuid}
 *
 * Returns hourly audience activity data (hours 0-23 UTC).
 */

import { apiError, apiSuccess, handleIgAuthError } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { getSupabase } from "../../supabase.js";

export default withAuth(async (req, res, user) => {
	if (req.method !== "GET") return apiError(res, 405, "Method not allowed");

	// #678: Rate limit IG data endpoints
	const { checkRateLimit } = await import("../../rateLimiter.js");
	const rl = await checkRateLimit({
		key: `ig-online-followers:${user.id}`,
		limit: 20,
		windowSeconds: 60,
		failMode: "open",
	});
	if (!rl.allowed) return apiError(res, 429, "Rate limit exceeded");

	const accountId = req.query.accountId as string;
	if (!accountId) return apiError(res, 400, "accountId is required");

	try {
		// Check Redis cache first (6-hour TTL)
		let cached: Record<string, unknown> | null = null;
		try {
			const { getRedis } = await import("../../redis.js");
			const redis = getRedis();
			const cacheKey = `ig:online_followers:${accountId}`;
			const raw = await redis.get(cacheKey);
			if (raw) {
				cached = typeof raw === "string" ? JSON.parse(raw) : raw;
			}
		} catch (err) {
			logger.debug("Redis unavailable, skip cache", { error: String(err) });
		}

		if (cached) {
			return apiSuccess(res, cached);
		}

		// Fetch account
		const { data: account, error: accountError } = (await getSupabase()
			.from("instagram_accounts")
			.select("instagram_access_token_encrypted, instagram_user_id, login_type")
			.eq("id", accountId)
			.eq("user_id", user.id)
			.maybeSingle()) as {
			data: {
				instagram_access_token_encrypted: string;
				instagram_user_id: string;
				login_type: string;
			} | null;
			error: { message: string } | null;
		};

		if (accountError || !account) {
			return apiError(res, 404, "Instagram account not found");
		}

		if (!account.instagram_access_token_encrypted) {
			return apiError(res, 400, "Account token not available");
		}

		const loginType = account.login_type || "instagram";
		logger.info("[IG OnlineFollowers] Fetching", { accountId, loginType });

		const { getOnlineFollowers } = await import("../../instagramApi.js");

		const result = await getOnlineFollowers(
			account.instagram_access_token_encrypted,
			account.instagram_user_id,
			loginType,
		);

		if (!result.success) {
			return await handleIgAuthError(
				res,
				accountId,
				user.id,
				result.error || "Unknown error",
			);
		}

		const payload = {
			hours: result.data,
			timezone: "UTC",
			period: "last_30_days",
		};

		// Cache in Redis for 6 hours
		try {
			const { getRedis } = await import("../../redis.js");
			const redis = getRedis();
			await redis.set(
				`ig:online_followers:${accountId}`,
				JSON.stringify(payload),
				{ ex: 21600 },
			);
		} catch (err) {
			logger.debug("Redis unavailable, skip", { error: String(err) });
		}

		return apiSuccess(res, payload);
	} catch (error: unknown) {
		logger.error("[IG OnlineFollowers] Error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
});
