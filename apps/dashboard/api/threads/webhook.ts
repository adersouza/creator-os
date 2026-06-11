/**
 * Threads Webhook Endpoint
 *
 * Receives webhook events from Meta for Threads:
 * - replies: When someone replies to the account's posts
 * - mentions: When the account is mentioned in a post
 * - publish: When a post is published
 * - delete: When a post is deleted
 *
 * GET: Webhook verification (hub.mode, hub.verify_token, hub.challenge)
 * POST: Event ingestion (with X-Hub-Signature-256 verification)
 *
 * Docs: https://developers.facebook.com/docs/threads/webhooks
 */

import * as crypto from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../_lib/apiResponse.js";
import { scheduleWebhookReplay } from "../_lib/cron/webhook-processor/retry.js";
import { logger, summarizeUserContent } from "../_lib/logger.js";
import {
	getPrivilegedSupabase,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";
import { incrementAndCheckSigFailures } from "../_lib/webhookMonitor.js";

interface ThreadsNativeValues {
	field: string;
	value: Record<string, unknown>;
}

type ThreadsValuesPayload = ThreadsNativeValues | ThreadsNativeValues[];

interface ThreadsEntryChange {
	field: string;
	value: Record<string, unknown>;
}

interface ThreadsEntry {
	id: string;
	time?: number | undefined;
	changes?: ThreadsEntryChange[] | undefined;
}

interface ThreadsWebhookBody {
	app_id?: string | undefined;
	topic?: string | undefined;
	target_id?: string | undefined;
	time?: number | undefined;
	subscription_id?: string | undefined;
	values?: ThreadsValuesPayload | undefined;
	entry?: ThreadsEntry[] | undefined;
}

const db = () =>
	getPrivilegedSupabase(PRIVILEGED_DB_REASONS.metaWebhookIngestion);

// Disable body parsing to access raw body for signature verification
export const config = { api: { bodyParser: false } };

const MAX_WEBHOOK_BODY_BYTES = 512_000; // 512 KB — well above any real Meta payload

/**
 * Read raw body from request stream for signature verification.
 * Rejects if the body exceeds MAX_WEBHOOK_BODY_BYTES.
 */
async function getRawBody(req: VercelRequest): Promise<Buffer> {
	return new Promise((resolve, reject) => {
		const chunks: Buffer[] = [];
		let totalSize = 0;
		req.on("data", (chunk: Buffer) => {
			totalSize += chunk.length;
			if (totalSize > MAX_WEBHOOK_BODY_BYTES) {
				reject(new Error("Webhook payload exceeds size limit"));
				return;
			}
			chunks.push(chunk);
		});
		req.on("end", () => resolve(Buffer.concat(chunks)));
		req.on("error", reject);
	});
	// NOTE: No req.body fallback here — if the stream is empty, signature
	// verification will fail with 401 (strict rejection). bodyParser: false
	// is set above; if this starts failing, check Vercel bodyParser config.
}

/**
 * Verify X-Hub-Signature-256 header using HMAC-SHA256
 * This ensures the request is genuinely from Meta
 */
function verifySignature(rawBody: Buffer, signature: string): boolean {
	if (!signature.startsWith("sha256=")) return false;
	// Threads webhooks MUST use THREADS_APP_SECRET exclusively (§14)
	const secrets = [process.env.THREADS_APP_SECRET].filter(Boolean) as string[];
	if (secrets.length === 0) {
		logger.error("[Threads Webhook] No app secret configured");
		return false;
	}

	for (const secret of secrets) {
		const expectedSig =
			"sha256=" +
			crypto.createHmac("sha256", secret).update(rawBody).digest("hex");
		const expectedBuf = Buffer.from(expectedSig);
		const actualBuf = Buffer.from(signature);
		if (expectedBuf.length !== actualBuf.length) {
			continue;
		}
		if (crypto.timingSafeEqual(expectedBuf, actualBuf)) {
			return true;
		}
	}
	return false;
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	// =========================================================================
	// GET: Webhook Verification
	// Meta sends a verification request when you configure the webhook
	// =========================================================================
	if (req.method === "GET") {
		const mode = req.query["hub.mode"] as string | undefined;
		const token = req.query["hub.verify_token"] as string | undefined;
		const challenge = req.query["hub.challenge"] as string | undefined;

		const verifyToken = process.env.META_WEBHOOK_VERIFY_TOKEN ?? "";
		const tokenBuf = Buffer.from(token || "");
		const verifyBuf = Buffer.from(verifyToken);
		const tokenMatch =
			mode === "subscribe" &&
			!!token &&
			verifyToken.length > 0 &&
			tokenBuf.length === verifyBuf.length &&
			crypto.timingSafeEqual(tokenBuf, verifyBuf);

		if (tokenMatch) {
			logger.info("[Threads Webhook] Verification successful");
			// Must return the challenge as plain text
			return res.status(200).send(challenge);
		}

		logger.warn("[Threads Webhook] Verification failed - credential mismatch");
		return apiError(res, 403, "Verification failed");
	}

	// =========================================================================
	// POST: Event Ingestion
	// Meta sends webhook events here when activity occurs
	// =========================================================================
	if (req.method === "POST") {
		// Verify signature header exists
		const signature = req.headers["x-hub-signature-256"] as string | undefined;
		if (!signature) {
			logger.warn("[Threads Webhook] Missing X-Hub-Signature-256 header");
			return apiError(res, 401, "Missing signature");
		}

		// Read raw body for signature verification
		let rawBody: Buffer;
		try {
			rawBody = await getRawBody(req);
		} catch (err) {
			const msg = err instanceof Error ? err.message : String(err);
			logger.warn("[Threads Webhook] Body read failed", { error: msg });
			return apiError(res, 413, msg);
		}

		// Verify signature
		if (!verifySignature(rawBody, signature)) {
			logger.warn("[Threads Webhook] Invalid signature", {
				ip:
					req.headers["x-forwarded-for"] ||
					req.headers["x-real-ip"] ||
					"unknown",
				ua: req.headers["user-agent"] || "none",
				sig: `${signature.slice(0, 16)}...`,
			});
			await incrementAndCheckSigFailures("threads");
			return apiError(res, 401, "Invalid signature");
		}

		// Parse JSON body
		let body: ThreadsWebhookBody;
		try {
			body = JSON.parse(rawBody.toString("utf-8"));
		} catch (err) {
			logger.error("[Threads Webhook] Invalid JSON body", {
				error: String(err),
			});
			return apiError(res, 400, "Invalid JSON body");
		}

		// Threads webhook payload format (per Meta docs):
		// { app_id, topic, target_id, time, subscription_id, values: { value: {...}, field: "replies" } }
		// Legacy/fallback format (Graph API style):
		// { entry: [{ id, changes: [{ field, value }] }] }

		logger.info("[Threads Webhook] Raw payload keys", {
			keys: Object.keys(body).join(","),
			hasEntry: !!body.entry,
			hasTopic: !!body.topic,
			hasValues: !!body.values,
		});

		// Replay protection — reject webhooks older than 5 minutes
		const webhookTime = body.time || body.entry?.[0]?.time;
		if (webhookTime) {
			const entryTimeMs = webhookTime > 1e12 ? webhookTime : webhookTime * 1000;
			const webhookAge = Date.now() - entryTimeMs;
			const isInFuture = webhookAge < -5000;
			const isTooOld = webhookAge > 5 * 60 * 1000;
			if (isInFuture || isTooOld) {
				logger.warn("[Threads Webhook] Replay rejected — stale timestamp", {
					age: `${Math.round(webhookAge / 1000)}s`,
					time: webhookTime,
				});
				return apiSuccess(res, { status: "ignored", reason: "stale" });
			}
		}

		// Process events — support both Threads-native and Graph API formats
		const supabase = db();
		const rows: Array<{
			event_type: string;
			threads_user_id: string;
			payload: Record<string, unknown>;
		}> = [];

		if (body.values) {
			// Threads-native webhook format — values can be a single object or an array
			const valuesArr = Array.isArray(body.values)
				? body.values
				: [body.values];
			const threadsUserId = body.target_id as string;

			for (const v of valuesArr) {
				if (!v.field) continue;
				logger.info("[Threads Webhook] Received event (native format)", {
					eventType: v.field,
					threadsUserId,
					topic: body.topic,
					appId: body.app_id,
				});

				rows.push({
					event_type: v.field,
					threads_user_id: threadsUserId,
					payload: v.value,
				});
			}
		} else if (body.entry) {
			// Legacy Graph API format (fallback)
			for (const entry of body.entry) {
				const threadsUserId = entry.id as string;
				const changes = entry.changes || [];

				for (const change of changes) {
					const eventType = change.field as string;
					const value = change.value;

					logger.info("[Threads Webhook] Received event (entry format)", {
						eventType,
						threadsUserId,
					});

					rows.push({
						event_type: eventType,
						threads_user_id: threadsUserId,
						payload: value,
					});
				}
			}
		} else {
				logger.warn("[Threads Webhook] Unrecognized payload format", {
					keys: Object.keys(body).join(","),
					bodySummary: summarizeUserContent(body),
				});
			}

		// Insert events with ON CONFLICT DO NOTHING for deduplication
		// Requires unique constraint on (event_type, threads_user_id, payload_id)
		// See migration: add_webhook_dedup_constraint
		if (rows.length > 0) {
			// Extract payload_id for the dedup column.
			// Fall back to a SHA-256 content hash so distinct events with no id
			// never collapse onto the same "unknown" dedup key.
			const rowsWithPayloadId = rows.map((row) => ({
				...row,
				payload_id:
					(row.payload?.id as string | undefined) ||
					crypto
						.createHash("sha256")
						.update(JSON.stringify(row.payload ?? ""))
						.digest("hex")
						.slice(0, 32),
			}));

			// biome-ignore lint/suspicious/noExplicitAny: threads_webhook_events not in generated types
			const { data: insertedEvents, error } = await (supabase as any)
				.from("threads_webhook_events")
				.upsert(rowsWithPayloadId, {
					onConflict: "event_type,threads_user_id,payload_id",
					ignoreDuplicates: true,
				})
				.select("*");

			if (error) {
				logger.error("[Threads Webhook] Insert error", {
					error: error.message,
				});
				// Return 500 so Meta will retry delivery of these events
				return apiError(res, 500, "Failed to store webhook events");
			}

			const newCount = insertedEvents?.length || 0;
			logger.info("[Threads Webhook] Stored events", {
				attempted: rows.length,
				stored: newCount,
			});

			// Nudge webhook-processor via QStash for near-instant pickup
			if (newCount > 0) {
				scheduleWebhookReplay("threads", 5).catch((err) =>
					logger.debug("[Threads Webhook] QStash nudge failed (non-blocking)", {
						error: err instanceof Error ? err.message : String(err),
					}),
				);
			}
		}

		// Always return 200 to acknowledge receipt
		// Meta will retry on non-2xx responses
		return apiSuccess(res, { received: true });
	}

	return apiError(res, 405, "Method not allowed");
}
