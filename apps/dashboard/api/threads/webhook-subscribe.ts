/**
 * Threads Webhook Subscription Endpoint
 *
 * POST /api/threads/webhook-subscribe
 *
 * Subscribes to Threads webhook fields (replies, mentions) for the authenticated user.
 * Requires the user to have a connected Threads account.
 *
 * Docs: https://developers.facebook.com/docs/threads/webhooks
 */

import { apiError, apiSuccess } from "../_lib/apiResponse.js";
import { logger } from "../_lib/logger.js";
import { withAuth } from "../_lib/middleware.js";
import {
	getPrivilegedSupabase,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";

const db = () =>
	getPrivilegedSupabase(PRIVILEGED_DB_REASONS.metaWebhookSubscription);

const THREADS_WEBHOOK_FIELDS = [
	"replies",
	"mentions",
	"delete",
	"publish",
] as const;

function resolveThreadsWebhookCallback(callbackUrl?: string): string {
	if (callbackUrl) return callbackUrl;
	const baseCandidate =
		process.env.THREADS_WEBHOOK_BASE_URL ||
		process.env.THREADS_REDIRECT_URI ||
		process.env.APP_URL ||
		(process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "");

	if (!baseCandidate) {
		throw new Error("Threads webhook callback base URL not configured");
	}

	const normalizedBase = baseCandidate
		.replace(/\/auth\/threads\/callback$/, "")
		.replace(/\/$/, "");

	return `${normalizedBase}/api/threads/webhook`;
}

export async function subscribeThreadsWebhooks(
	callbackOverride?: string,
): Promise<{ success: boolean; fields?: string[] | undefined; error?: string | undefined }> {
	const appId = process.env.THREADS_CLIENT_ID;
	const appSecret =
		process.env.THREADS_CLIENT_SECRET || process.env.THREADS_APP_SECRET;
	// Must match what threads/webhook.ts and instagram/webhook.ts check
	const verifyToken = process.env.META_WEBHOOK_VERIFY_TOKEN;

	if (!appId || !appSecret) {
		return { success: false, error: "Threads app credentials not configured" };
	}

	if (!verifyToken) {
		return { success: false, error: "Webhook verify token not configured" };
	}

	try {
		// Step 1: Get a proper app access token (Threads uses TH|...|... format)
		// Ref: Threads API Postman collection → Authorization → Get App Access Token
		const tokenUrl = `https://graph.threads.net/oauth/access_token?grant_type=client_credentials&client_id=${appId}&client_secret=${appSecret}`;
		const tokenRes = await fetch(tokenUrl, {
			signal: AbortSignal.timeout(10000),
		});
		const tokenData = await tokenRes.json();

		if (!tokenRes.ok || !tokenData.access_token) {
			logger.error(
				"[Threads Webhook Subscribe] Failed to get app access token",
				{
					error: String(
						tokenData.error?.message || tokenData.error || tokenData,
					),
				},
			);
			return {
				success: false,
				error:
					tokenData.error?.message || "Failed to get Threads app access token",
			};
		}

		const appAccessToken = tokenData.access_token;
		logger.info("[Threads Webhook Subscribe] Got app access token");

		// Step 2: Subscribe to webhook fields using the real app token
		// NOTE: Threads webhooks are app-level and configured via the Meta App Dashboard.
		// Programmatic subscription via /{app_id}/subscriptions may return "Object does not exist"
		// or silently fail. This endpoint is kept as a convenience attempt but the primary
		// configuration path is the Meta Developer Dashboard → Threads → Webhooks.
		const callbackUrl = resolveThreadsWebhookCallback(callbackOverride);
		const subscribeUrl = `https://graph.threads.net/v1.0/${appId}/subscriptions`;

		const params = new URLSearchParams({
			object: "user",
			callback_url: callbackUrl,
			fields: THREADS_WEBHOOK_FIELDS.join(","),
			verify_token: verifyToken,
			access_token: appAccessToken,
		});

		const response = await fetch(subscribeUrl, {
			method: "POST",
			headers: { "Content-Type": "application/x-www-form-urlencoded" },
			body: params,
			signal: AbortSignal.timeout(15000),
		});

		const data = await response.json();

		if (!response.ok || data.error) {
			logger.error("[Threads Webhook Subscribe] Error", {
				error: String(data.error?.message || data.error || data),
			});
			return {
				success: false,
				error: data.error?.message || "Failed to subscribe to Threads webhooks",
			};
		}

		logger.info("[Threads Webhook Subscribe] Subscribed to fields", {
			fields: THREADS_WEBHOOK_FIELDS,
			callbackUrl,
		});
		return { success: true, fields: [...THREADS_WEBHOOK_FIELDS] };
	} catch (error: unknown) {
		logger.error("[Threads Webhook Subscribe] Error", { error: String(error) });
		return {
			success: false,
			error: error instanceof Error ? error.message : String(error),
		};
	}
}

export default withAuth(async (req, res, user) => {
	if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

	const { accountId, callbackUrl } = req.body || {};

	if (!accountId) {
		return apiError(res, 400, "accountId is required");
	}

	const { data: account } = await db()
		.from("accounts")
		.select("id")
		.eq("id", accountId)
		.eq("user_id", user.id)
		.maybeSingle();

	if (!account) {
		return apiError(res, 404, "Account not found");
	}

	try {
		const result = await subscribeThreadsWebhooks(callbackUrl);

		if (!result.success) {
			return apiError(
				res,
				500,
				result.error || "Failed to subscribe to Threads webhooks",
			);
		}

		return apiSuccess(res, {
			fields: result.fields ?? [...THREADS_WEBHOOK_FIELDS],
			message: "Successfully subscribed to Threads webhooks",
		});
	} catch (error: unknown) {
		logger.error("[Threads Webhook Subscribe] Error", { error: String(error) });
		return apiError(res, 500, "Failed to subscribe to webhooks");
	}
});
