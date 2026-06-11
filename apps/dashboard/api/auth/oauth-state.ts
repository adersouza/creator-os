/**
 * OAuth State Management API
 *
 * POST /api/auth/oauth-state — store OAuth state in Redis with 10-min TTL
 * Used for server-side CSRF verification in OAuth callbacks.
 */

import { apiError, apiSuccess } from "../_lib/apiResponse.js";
import { logger } from "../_lib/logger.js";
import { withAuth } from "../_lib/middleware.js";
import {
	enforceRouteRateLimit,
	getClientIp,
} from "../_lib/routeRateLimit.js";

export default withAuth(async (req, res, user) => {
	if (req.method !== "POST") {
		return apiError(res, 405, "Method not allowed");
	}

	const ipAllowed = await enforceRouteRateLimit(res, {
		key: `auth-ip:oauth-state:ip:${getClientIp(req)}:minute`,
		limit: 5,
		windowSeconds: 60,
		failMode: "closed",
		message: "Too many auth requests. Try again shortly.",
	});
	if (!ipAllowed) return;

	const { state } = req.body;

	if (!state || typeof state !== "string" || state.trim() === "") {
		return apiError(res, 400, "state parameter is required");
	}

	// Validate state format: alphanumeric/dash/underscore, 8-128 chars
	if (!/^[a-zA-Z0-9_-]{8,128}$/.test(state)) {
		return apiError(res, 400, "Invalid state format");
	}

	try {
		const { getRedis } = await import("../_lib/redis.js");
		const redis = getRedis();
		const key = `oauth_state:${user.id}:${state}`;
		await redis.set(key, "1", { ex: 600 }); // 10-minute TTL
		return apiSuccess(res, { stored: true });
	} catch (err) {
		logger.warn("[oauth-state] Failed to store state in Redis", {
			error: String(err),
		});
		return apiError(
			res,
			503,
			"Could not start OAuth securely. Please try again.",
			{ code: "OAUTH_STATE_UNAVAILABLE" },
		);
	}
});
