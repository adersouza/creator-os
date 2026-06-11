import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess, methodNotAllowed } from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { sendWebPushToUser } from "../../webPushDelivery.js";

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method !== "POST") return methodNotAllowed(res);

		const rl = await checkRateLimit({
			key: `test-push:${user.id}`,
			limit: 5,
			windowSeconds: 60,
			failMode: "open",
		});
		if (!rl.allowed) {
			return apiError(res, 429, "Too many test notifications. Try again shortly.");
		}

		const result = await sendWebPushToUser(user.id, {
			title: "Juno33 notifications are ready",
			body: "This device can receive Notify Me reminders.",
			tag: "juno33-test-push",
			requireInteraction: false,
			data: { url: "/composer", source: "test-push" },
		});

		logger.info("[notifications:test-push]", {
			userId: user.id,
			attempted: result.attempted,
			sent: result.sent,
			expired: result.expired,
			failed: result.failed,
			configured: result.configured,
		});

		return apiSuccess(res, {
			delivered: result.sent > 0,
			push: result,
		});
	},
);
