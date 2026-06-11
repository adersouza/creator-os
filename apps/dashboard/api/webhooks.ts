/**
 * Outgoing Webhooks API
 * GET    — list user's webhook subscriptions
 * POST   — create subscription or send test event
 * DELETE — remove subscription
 */

import * as crypto from "node:crypto";
import { apiError, apiSuccess } from "./_lib/apiResponse.js";
import { decrypt, encrypt } from "./_lib/encryption.js";
import { logger } from "./_lib/logger.js";
import { requireStepUp, withAuthDb } from "./_lib/middleware.js";
import { enforceRouteRateLimit } from "./_lib/routeRateLimit.js";
import { validateUrlNotPrivate } from "./_lib/ssrfProtection.js";
import { z, zEnum } from "./_lib/zodCompat.js";

interface WebhookSubscription {
	id: string;
	url: string;
	secret: string | null;
	events: string[];
	active: boolean;
}

const WebhookSchema = z.object({
	url: z.string().url(),
	events: z.array(
		zEnum([
			"post.published",
			"post.scheduled",
			"sync.completed",
			"quickwin.solved",
			"ces.milestone",
			"analytics.updated",
		]),
	),
	secret: z.string().min(16).optional(),
	active: z.boolean().default(true),
	/** Secret TTL in days (default: 90). Secrets older than this should be rotated. */
	secretTtlDays: z.number().min(1).max(365).optional(),
});

/** Default secret expiry: 90 days */
const DEFAULT_SECRET_TTL_DAYS = 90;

// #620: Decrypt webhook secret, falling back to plaintext for legacy entries
function decryptSecret(secret: string): string {
	try {
		return decrypt(secret);
	} catch (error) {
		throw new Error(
			`Failed to decrypt stored webhook secret: ${
				error instanceof Error ? error.message : String(error)
			}`,
		);
	}
}

function signedWebhookHeaders(
	payload: string,
	encryptedSecret: string | null | undefined,
	event: string,
): Record<string, string> {
	const timestamp = Math.floor(Date.now() / 1000).toString();
	const deliveryId = crypto.randomUUID();
	const headers: Record<string, string> = {
		"Content-Type": "application/json",
		"X-Juno33-Event": event,
		"X-Juno33-Timestamp": timestamp,
		"X-Juno33-Delivery-Id": deliveryId,
	};

	if (encryptedSecret) {
		const secret = decryptSecret(encryptedSecret);
		const signedPayload = `${timestamp}.${deliveryId}.${payload}`;
		headers["X-Juno33-Signature-256"] =
			`sha256=${crypto.createHmac("sha256", secret).update(payload).digest("hex")}`;
		headers["X-Juno33-Signature-V2"] =
			`v2=${crypto.createHmac("sha256", secret).update(signedPayload).digest("hex")}`;
	}

	return headers;
}

export default withAuthDb(async (req, res, context) => {
	const { user, userDb } = context;

	if (req.method === "GET") {
		const { data, error } = await userDb
			.from("webhook_subscriptions")
			.select("*")
			.eq("user_id", user.id)
			.order("created_at", { ascending: false });

		if (error) {
			return apiError(res, 500, "Failed to load webhooks");
		}
		return apiSuccess(res, { webhooks: data || [] });
	}

	if (req.method === "POST") {
		const { action } = req.body;

		// Rotate webhook secret
		if (action === "rotate-secret") {
			const stepUp = await requireStepUp(req, res, user.id);
			if (stepUp) return stepUp;

			const rotateAllowed = await enforceRouteRateLimit(res, {
				key: `webhook-rotate:${user.id}`,
				limit: 5,
				windowSeconds: 60,
				failMode: "closed",
				message: "Rate limit exceeded",
			});
			if (!rotateAllowed) return;

			const { webhookId, secret: newSecret } = req.body;
			if (!webhookId) return apiError(res, 400, "webhookId required");
			if (
				!newSecret ||
				typeof newSecret !== "string" ||
				newSecret.length < 16
			) {
				return apiError(res, 400, "New secret must be at least 16 characters");
			}

			const { data: existing } = await userDb
				.from("webhook_subscriptions")
				.select("id")
				.eq("id", webhookId)
				.eq("user_id", user.id)
				.maybeSingle();
			if (!existing) return apiError(res, 404, "Webhook not found");

			const ttlDays =
				typeof req.body.secretTtlDays === "number"
					? Math.min(365, Math.max(1, req.body.secretTtlDays))
					: DEFAULT_SECRET_TTL_DAYS;
			const now = new Date();
			const expiresAt = new Date(now.getTime() + ttlDays * 24 * 60 * 60 * 1000);

			const { error: updateErr } = await userDb
				.from("webhook_subscriptions")
				.update({
					secret: encrypt(newSecret),
					secret_rotated_at: now.toISOString(),
					secret_expires_at: expiresAt.toISOString(),
					updated_at: now.toISOString(),
				})
				.eq("id", webhookId)
				.eq("user_id", user.id);

			if (updateErr) return apiError(res, 500, "Failed to rotate secret");
			return apiSuccess(res, {
				rotated: true,
				expiresAt: expiresAt.toISOString(),
				ttlDays,
			});
		}

		if (action === "test") {
			// #625: Rate limit test events (10/min)
			const testAllowed = await enforceRouteRateLimit(res, {
				key: `webhook-test:${user.id}`,
				limit: 10,
				windowSeconds: 60,
				failMode: "closed",
				message: "Rate limit exceeded",
			});
			if (!testAllowed) return;

			const { webhookId } = req.body;
			if (!webhookId) return apiError(res, 400, "webhookId required");

			const { data: webhookRaw } = await userDb
				.from("webhook_subscriptions")
				.select("*")
				.eq("id", webhookId)
				.eq("user_id", user.id)
				.maybeSingle();
			if (!webhookRaw) return apiError(res, 404, "Webhook not found");
			const webhook = webhookRaw as unknown as WebhookSubscription;

			// #626: SSRF protection on test endpoint
			const ssrfError = await validateUrlNotPrivate(webhook.url);
			if (ssrfError) return apiError(res, 400, "Invalid webhook URL");

			try {
				const testPayload = {
					event: "test",
					timestamp: new Date().toISOString(),
					data: { message: "Test event from Juno33" },
				};
				const body = JSON.stringify(testPayload);
				let headers: Record<string, string>;
				try {
					headers = signedWebhookHeaders(body, webhook.secret, "test");
				} catch (error) {
					logger.error("[webhooks] Failed to sign test webhook", {
						webhookId: webhook.id,
						userId: user.id,
						error: String(error),
					});
					return apiError(res, 500, "Stored webhook secret is invalid");
				}
				const resp = await fetch(webhook.url, {
					method: "POST",
					headers,
					body,
					signal: AbortSignal.timeout(10000),
				});
				return apiSuccess(res, { status: resp.status, ok: resp.ok });
			} catch (_e: unknown) {
				return apiError(res, 400, "Failed to reach webhook URL");
			}
		}

		// Create webhook
		// #625: Rate limit webhook creation (5/min)
		const stepUp = await requireStepUp(req, res, user.id);
		if (stepUp) return stepUp;

		const createAllowed = await enforceRouteRateLimit(res, {
			key: `webhook-create:${user.id}`,
			limit: 5,
			windowSeconds: 60,
			failMode: "closed",
			message: "Rate limit exceeded",
		});
		if (!createAllowed) return;

		const parsed = WebhookSchema.safeParse(req.body);
		if (!parsed.success)
			return apiError(
				res,
				400,
				parsed.error.issues[0]?.message || "Invalid input",
			);

		// #626: SSRF protection on webhook URL
		const ssrfErrorCreate = await validateUrlNotPrivate(parsed.data.url);
		if (ssrfErrorCreate) return apiError(res, 400, "Invalid webhook URL");

		const now = new Date();
		const ttlDays = parsed.data.secretTtlDays ?? DEFAULT_SECRET_TTL_DAYS;
		const secretExpiresAt = parsed.data.secret
			? new Date(now.getTime() + ttlDays * 24 * 60 * 60 * 1000).toISOString()
			: null;

		const { data, error } = await userDb
			.from("webhook_subscriptions")
			.insert({
				user_id: user.id,
				url: parsed.data.url,
				events: parsed.data.events,
				// #620: Encrypt webhook secret at rest
				secret: parsed.data.secret ? encrypt(parsed.data.secret) : null,
				active: parsed.data.active,
				secret_rotated_at: parsed.data.secret ? now.toISOString() : null,
				secret_expires_at: secretExpiresAt,
			})
			.select()
			.maybeSingle();

		if (error) return apiError(res, 500, "Failed to create webhook");
		return apiSuccess(res, { webhook: data });
	}

	if (req.method === "DELETE") {
		const stepUp = await requireStepUp(req, res, user.id);
		if (stepUp) return stepUp;

		const deleteAllowed = await enforceRouteRateLimit(res, {
			key: `webhook-delete:${user.id}`,
			limit: 5,
			windowSeconds: 60,
			failMode: "closed",
			message: "Rate limit exceeded",
		});
		if (!deleteAllowed) return;

		const { webhookId } = req.body;
		if (!webhookId) return apiError(res, 400, "webhookId required");

		const { error, count } = await userDb
			.from("webhook_subscriptions")
			.delete({ count: "exact" })
			.eq("id", webhookId)
			.eq("user_id", user.id);

		if (error) return apiError(res, 500, "Failed to delete webhook");
		if (!count) return apiError(res, 404, "Webhook not found");

		return apiSuccess(res, { deleted: true });
	}

	return apiError(res, 405, "Method not allowed");
});
