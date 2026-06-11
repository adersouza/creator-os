/**
 * Webhook Subscription Endpoint
 *
 * Subscribes an Instagram account to webhook events.
 * Supports BOTH login types:
 *   - Instagram Login: POST graph.instagram.com/{ig_user_id}/subscribed_apps
 *   - Facebook Login: POST graph.facebook.com/{page_id}/subscribed_apps
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../_lib/apiResponse.js";
import { decrypt } from "../_lib/encryption.js";
import { logger } from "../_lib/logger.js";
import {
	getPrivilegedSupabase,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";
import { z } from "../_lib/zodCompat.js";

const db = () =>
	getPrivilegedSupabase(PRIVILEGED_DB_REASONS.metaWebhookSubscription);

// ============================================================================
// Webhook Fields
// ============================================================================

const FB_LOGIN_WEBHOOK_FIELD_LIST = [
	"feed",
	"comments",
	"live_comments",
	"mentions",
	"messages",
	"message_reactions",
	"messaging_postbacks",
	"messaging_seen",
	"messaging_referral",
	"messaging_optins",
	"message_edit",
] as const;

/** Full set of IG webhook fields — keep in sync with IG Login subscribe (line ~111) */
const FB_LOGIN_WEBHOOK_FIELDS = FB_LOGIN_WEBHOOK_FIELD_LIST.join(",");

/**
 * Instagram Login webhook fields.
 *
 * NOTE (WEBHOOK-3): `story_insights` webhook events are only available for
 * accounts connected via Facebook Login (subscribed through the Page's
 * subscribed_apps endpoint above), NOT Instagram Login. If you need
 * story_insights webhooks, the account must use the Facebook Login flow.
 */
const IG_LOGIN_WEBHOOK_FIELD_LIST = [
	"comments",
	"live_comments",
	"mentions",
	"messages",
	"message_reactions",
	"messaging_postbacks",
	"messaging_seen",
	"messaging_referral",
	"messaging_optins",
	"messaging_handover",
	"standby",
	"message_edit",
] as const;

const IG_LOGIN_WEBHOOK_FIELDS = IG_LOGIN_WEBHOOK_FIELD_LIST.join(",");

interface WebhookSubscriptionVerification {
	verified: boolean;
	subscribedFields: string[];
	missingFields: string[];
	error?: string | undefined;
}

function collectSubscribedFields(payload: unknown): string[] {
	const fields = new Set<string>();
	const visit = (value: unknown) => {
		if (!value || typeof value !== "object") return;
		const record = value as Record<string, unknown>;
		const subscribedFields = record.subscribed_fields;
		if (Array.isArray(subscribedFields)) {
			for (const field of subscribedFields) {
				if (typeof field === "string") fields.add(field);
			}
		}
		const data = record.data;
		if (Array.isArray(data)) {
			for (const item of data) visit(item);
		}
	};
	visit(payload);
	return [...fields].sort();
}

function verifySubscribedFields(
	payload: unknown,
	requiredFields: readonly string[],
): WebhookSubscriptionVerification {
	const subscribedFields = collectSubscribedFields(payload);
	const missingFields = requiredFields.filter(
		(field) => !subscribedFields.includes(field),
	);
	return {
		verified: missingFields.length === 0,
		subscribedFields,
		missingFields,
	};
}

async function fetchSubscriptionVerification(
	url: string,
	requiredFields: readonly string[],
): Promise<WebhookSubscriptionVerification> {
	try {
		const response = await fetch(url, {
			method: "GET",
			signal: AbortSignal.timeout(15000),
		});
		const data = await response.json();
		if (!response.ok || data.error) {
			return {
				verified: false,
				subscribedFields: [],
				missingFields: [...requiredFields],
				error:
					data.error?.message ||
					`Subscription verification failed with HTTP ${response.status}`,
			};
		}
		return verifySubscribedFields(data, requiredFields);
	} catch (error: unknown) {
		return {
			verified: false,
			subscribedFields: [],
			missingFields: [...requiredFields],
			error: error instanceof Error ? error.message : String(error),
		};
	}
}

// ============================================================================
// Supabase Admin Client
// ============================================================================

// ============================================================================
// Handler
// ============================================================================

const WebhookSubscribeSchema = z.object({
	accountId: z.string().min(1, "accountId is required"),
});

// Simple type check instead of Zod (avoids Zod v3/v4 type resolution issues on Vercel)
function isResubscribeAll(
	body: unknown,
): body is { action: "resubscribe-all" } {
	return (
		typeof body === "object" &&
		body !== null &&
		(body as { action?: string | undefined }).action === "resubscribe-all"
	);
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	// No CORS headers - this is a server-to-server endpoint (requires Authorization)

	if (req.method !== "POST") return apiError(res, 405, "Method not allowed");

	try {
		// Auth
		const authHeader = req.headers.authorization;
		if (!authHeader?.startsWith("Bearer "))
			return apiError(res, 401, "Missing authorization");

		const authToken = authHeader.replace("Bearer ", "");
		const {
			data: { user },
			error: authError,
		} = await db().auth.getUser(authToken);

		if (authError || !user) return apiError(res, 401, "Invalid token");

		// Check for resubscribe-all action
		if (isResubscribeAll(req.body)) {
			return handleResubscribeAll(req, res, user.id);
		}

		const parsed = WebhookSubscribeSchema.safeParse(req.body);
		if (!parsed.success) {
			return apiError(
				res,
				400,
				`Invalid input: ${parsed.error.issues[0]?.message}`,
			);
		}
		const { accountId } = parsed.data;

		// Fetch account
		const { data: account, error: fetchErr } = await db()
			.from("instagram_accounts")
			.select(
				"id, user_id, login_type, instagram_user_id, instagram_access_token_encrypted, facebook_page_id, facebook_page_access_token_encrypted",
			)
			.eq("id", accountId)
			.eq("user_id", user.id)
			.maybeSingle();

		if (fetchErr || !account) return apiError(res, 404, "Account not found");

		const loginType = account.login_type || "instagram";

		if (loginType === "facebook") {
			// Facebook Login: subscribe via Page ID + Page token
			const pageId = account.facebook_page_id;
			const encryptedPageToken = account.facebook_page_access_token_encrypted;

			if (!pageId || !encryptedPageToken)
				return apiError(
					res,
					400,
					"Missing Facebook Page credentials for this account",
				);

			const pageToken = decrypt(encryptedPageToken);
			const result = await subscribePageToWebhooks(pageId, pageToken);
			if (!result.success) {
				return apiError(
					res,
					400,
					result.error || "Failed to subscribe to webhooks",
				);
			}

			return apiSuccess(res, {
				pageId,
				subscribedFields: FB_LOGIN_WEBHOOK_FIELDS.split(","),
				verification: result.verification,
			});
		} else {
			// Instagram Login: subscribe via IG User ID + IG token
			const igUserId = account.instagram_user_id;
			const encryptedToken = account.instagram_access_token_encrypted;

			if (!igUserId || !encryptedToken)
				return apiError(
					res,
					400,
					"Missing Instagram credentials for this account",
				);

			const igToken = decrypt(encryptedToken);
			const result = await subscribeInstagramUserToWebhooks(igUserId, igToken);
			if (!result.success) {
				return apiError(
					res,
					400,
					result.error || "Failed to subscribe to webhooks",
				);
			}

			return apiSuccess(res, {
				igUserId,
				subscribedFields: IG_LOGIN_WEBHOOK_FIELDS.split(","),
				verification: result.verification,
			});
		}
	} catch (error: unknown) {
		logger.error("[webhook-subscribe] Error", { error: String(error) });
		return apiError(res, 500, "Internal server error");
	}
}

/**
 * Standalone function to subscribe a page to webhooks.
 * Called from fb-callback after successful login.
 */
export async function subscribePageToWebhooks(
	pageId: string,
	pageAccessToken: string,
): Promise<{
	success: boolean;
	error?: string | undefined;
	verification?: WebhookSubscriptionVerification | undefined;
}> {
	try {
		const subscribeUrl = `https://graph.facebook.com/v25.0/${pageId}/subscribed_apps`;
		const response = await fetch(subscribeUrl, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				subscribed_fields: FB_LOGIN_WEBHOOK_FIELDS,
				access_token: pageAccessToken,
			}),
			signal: AbortSignal.timeout(15000),
		});

		const data = await response.json();

		if (!response.ok || data.error) {
			logger.error("[webhook-subscribe] Auto-subscribe failed", {
				error: String(data?.error?.message || data),
			});
			return {
				success: false,
				error: data.error?.message || "Subscription failed",
			};
		}

		const verification = await fetchSubscriptionVerification(
			`${subscribeUrl}?access_token=${encodeURIComponent(pageAccessToken)}`,
			FB_LOGIN_WEBHOOK_FIELD_LIST,
		);
		if (!verification.verified) {
			logger.warn("[webhook-subscribe] Page webhook verification incomplete", {
				pageId,
				missingFields: verification.missingFields,
				error: verification.error,
			});
		}

		logger.info("[webhook-subscribe] Auto-subscribed page to webhooks", {
			pageId,
			verified: verification.verified,
		});
		return { success: true, verification };
	} catch (error: unknown) {
		logger.error("[webhook-subscribe] Auto-subscribe error", {
			error: String(error),
		});
		return {
			success: false,
			error: error instanceof Error ? error.message : String(error),
		};
	}
}

export async function subscribeInstagramUserToWebhooks(
	instagramUserId: string,
	instagramAccessToken: string,
): Promise<{
	success: boolean;
	error?: string | undefined;
	verification?: WebhookSubscriptionVerification | undefined;
}> {
	try {
		const subscribeUrl = `https://graph.instagram.com/v25.0/${instagramUserId}/subscribed_apps`;
		const response = await fetch(subscribeUrl, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				subscribed_fields: IG_LOGIN_WEBHOOK_FIELDS,
				access_token: instagramAccessToken,
			}),
			signal: AbortSignal.timeout(15000),
		});

		const data = await response.json();

		if (!response.ok || data.error) {
			logger.error("[webhook-subscribe] IG subscription failed", {
				error: String(data?.error?.message || data),
			});
			return {
				success: false,
				error: data.error?.message || "Subscription failed",
			};
		}

		const verification = await fetchSubscriptionVerification(
			`${subscribeUrl}?access_token=${encodeURIComponent(instagramAccessToken)}`,
			IG_LOGIN_WEBHOOK_FIELD_LIST,
		);
		if (!verification.verified) {
			logger.warn("[webhook-subscribe] IG webhook verification incomplete", {
				igUserId: instagramUserId,
				missingFields: verification.missingFields,
				error: verification.error,
			});
		}

		logger.info("[webhook-subscribe] Subscribed via Instagram Login", {
			igUserId: instagramUserId,
			verified: verification.verified,
		});
		return { success: true, verification };
	} catch (error: unknown) {
		logger.error("[webhook-subscribe] IG subscribe error", {
			error: String(error),
		});
		return {
			success: false,
			error: error instanceof Error ? error.message : String(error),
		};
	}
}

// ============================================================================
// Resubscribe All Accounts
// ============================================================================

async function handleResubscribeAll(
	_req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	const { data: accounts, error } = await db()
		.from("instagram_accounts")
		.select(
			"id, login_type, instagram_user_id, instagram_access_token_encrypted, facebook_page_id, facebook_page_access_token_encrypted",
		)
		.eq("user_id", userId);

	if (error || !accounts) {
		return apiError(res, 500, "Failed to fetch accounts");
	}

	const results: Array<{
		accountId: string;
		success: boolean;
		error?: string | undefined;
		verification?: WebhookSubscriptionVerification | undefined;
	}> = [];

	for (const account of accounts) {
		const loginType = account.login_type || "instagram";
		if (loginType === "facebook") {
			if (
				!account.facebook_page_id ||
				!account.facebook_page_access_token_encrypted
			) {
				results.push({
					accountId: account.id,
					success: false,
					error: "Missing page credentials",
				});
				continue;
			}
			const pageToken = decrypt(account.facebook_page_access_token_encrypted);
			const result = await subscribePageToWebhooks(
				account.facebook_page_id,
				pageToken,
			);
			results.push({
				accountId: account.id,
				success: result.success,
				error: result.error,
				verification: result.verification,
			});
		} else {
			if (
				!account.instagram_user_id ||
				!account.instagram_access_token_encrypted
			) {
				results.push({
					accountId: account.id,
					success: false,
					error: "Missing Instagram credentials",
				});
				continue;
			}
			const igToken = decrypt(account.instagram_access_token_encrypted);
			const result = await subscribeInstagramUserToWebhooks(
				account.instagram_user_id,
				igToken,
			);
			results.push({
				accountId: account.id,
				success: result.success,
				error: result.error,
				verification: result.verification,
			});
		}
	}

	const succeeded = results.filter((r) => r.success).length;
	const failed = results.filter((r) => !r.success).length;
	const verified = results.filter((r) => r.verification?.verified).length;
	const verificationFailed = results.filter(
		(r) => r.success && r.verification && !r.verification.verified,
	).length;
	logger.info("[webhook-subscribe] Resubscribed all accounts", {
		succeeded,
		failed,
		verified,
		verificationFailed,
	});

	return apiSuccess(res, {
		total: results.length,
		succeeded,
		failed,
		verified,
		verificationFailed,
		results,
	});
}
