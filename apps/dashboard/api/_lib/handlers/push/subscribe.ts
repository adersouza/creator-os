/**
 * Push Subscription Management — POST/DELETE /api/push/subscribe
 *
 * POST: Register a new push subscription for the authenticated user.
 * DELETE: Remove a push subscription by endpoint.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import {
	apiError,
	apiSuccess,
	badRequest,
	methodNotAllowed,
} from "../../apiResponse.js";
import { logger } from "../../logger.js";
import { withAuth } from "../../middleware.js";
import { checkRateLimit } from "../../rateLimiter.js";
import { getSupabase } from "../../supabase.js";

export default withAuth(
	async (req: VercelRequest, res: VercelResponse, user) => {
		if (req.method === "POST") {
			return handleSubscribe(req, res, user);
		}
		if (req.method === "DELETE") {
			return handleUnsubscribe(req, res, user);
		}
		return methodNotAllowed(res);
	},
);

async function handleSubscribe(
	req: VercelRequest,
	res: VercelResponse,
	user: { id: string; email?: string | undefined },
): Promise<VercelResponse> {
	// Rate limit: 10 subscribe requests per minute per user
	const rl = await checkRateLimit({
		key: `push-subscribe:${user.id}`,
		limit: 10,
		windowSeconds: 60,
		failMode: "open",
	});
	if (!rl.allowed) {
		return apiError(res, 429, "Too many requests. Please wait a moment.");
	}

	const { subscription } = req.body || {};
	if (
		!subscription?.endpoint ||
		!subscription?.keys?.p256dh ||
		!subscription?.keys?.auth
	) {
		return badRequest(res, "Missing subscription endpoint or keys");
	}

	try {
		const { error } = await getSupabase()
			.from("push_subscriptions")
			.upsert(
				{
					user_id: user.id,
					endpoint: subscription.endpoint,
					p256dh: subscription.keys.p256dh,
					auth: subscription.keys.auth,
					user_agent:
						typeof req.headers["user-agent"] === "string"
							? req.headers["user-agent"].slice(0, 500)
							: null,
					created_at: new Date().toISOString(),
				},
				{ onConflict: "user_id,endpoint" },
			);

		if (error) {
			logger.warn("Failed to upsert push subscription", {
				error: error.message,
			});
			return apiError(res, 500, "Failed to save subscription");
		}

		return apiSuccess(res, { subscribed: true }, 201);
	} catch (err) {
		logger.error("Push subscribe error", { error: String(err) });
		return apiError(res, 500, "Internal error");
	}
}

async function handleUnsubscribe(
	req: VercelRequest,
	res: VercelResponse,
	user: { id: string; email?: string | undefined },
): Promise<VercelResponse> {
	const { endpoint } = req.body || {};
	if (!endpoint) {
		return badRequest(res, "Missing endpoint");
	}

	try {
		await getSupabase()
			.from("push_subscriptions")
			.delete()
			.eq("user_id", user.id)
			.eq("endpoint", endpoint);

		return apiSuccess(res, { unsubscribed: true });
	} catch (err) {
		logger.error("Push unsubscribe error", { error: String(err) });
		return apiError(res, 500, "Internal error");
	}
}
