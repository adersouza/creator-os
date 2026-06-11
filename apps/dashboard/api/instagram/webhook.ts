import * as crypto from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiError, apiSuccess } from "../_lib/apiResponse.js";
import { scheduleWebhookReplay } from "../_lib/cron/webhook-processor/retry.js";
import { logger } from "../_lib/logger.js";
import {
	getPrivilegedSupabase,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";
import { incrementAndCheckSigFailures } from "../_lib/webhookMonitor.js";

const db = () =>
	getPrivilegedSupabase(PRIVILEGED_DB_REASONS.metaWebhookIngestion);

export const config = { api: { bodyParser: false } };

const MAX_WEBHOOK_BODY_BYTES = 512_000; // 512 KB — well above any real Meta payload

async function getRawBody(req: VercelRequest): Promise<Buffer> {
	// Try streaming first (bodyParser: false should preserve the stream)
	const buf = await new Promise<Buffer>((resolve, reject) => {
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

	// If stream was empty but req.body exists, Vercel pre-parsed it.
	// IMPORTANT: Re-serialized JSON may differ from the original raw body
	// (whitespace, key ordering), so HMAC verification against this fallback
	// may produce false negatives. We flag it so the caller can handle it.
	if (buf.length === 0) {
		// Strict rejection — raw body unavailable means HMAC can't be verified.
		// Re-serialized JSON differs from original bytes (whitespace, key order).
		logger.error("[webhook] Raw body unavailable — cannot verify HMAC", {
			platform: "instagram",
			hasBody: !!req.body,
		});
		return buf; // Return empty buffer — HMAC will fail, event rejected
	}

	return buf;
}

function verifySignature(rawBody: Buffer, signature: string): boolean {
	if (!signature.startsWith("sha256=")) return false;
	// Try META_APP_SECRET first, fall back to FACEBOOK_APP_SECRET
	// (IG webhooks may be registered under either app)
	const secret = process.env.META_APP_SECRET;
	if (!secret) {
		logger.error("[IG Webhook] META_APP_SECRET not configured");
		return false;
	}
	const secrets = [secret];

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
	// GET: Webhook verification
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
			logger.info("[IG Webhook] Verification successful");
			return res.status(200).send(challenge);
		}

		logger.warn("[IG Webhook] Verification failed");
		return apiError(res, 403, "Verification failed");
	}

	// POST: Event ingestion
	if (req.method === "POST") {
		const signature = req.headers["x-hub-signature-256"] as string | undefined;
		if (!signature) {
			return apiError(res, 401, "Missing signature");
		}

		let rawBody: Buffer;
		try {
			rawBody = await getRawBody(req);
		} catch (err) {
			const msg = err instanceof Error ? err.message : String(err);
			logger.warn("[IG Webhook] Body read failed", { error: msg });
			return apiError(res, 413, msg);
		}
		const isFallbackBody = !!(rawBody as Buffer & { __isFallback?: boolean | undefined })
			.__isFallback;

		if (!verifySignature(rawBody, signature)) {
			await incrementAndCheckSigFailures("instagram");
			if (isFallbackBody) {
				// Fallback body was re-serialized by Vercel — HMAC mismatch is expected
				// because JSON.stringify may differ from the original raw bytes.
				// SECURITY: We MUST reject instead of proceeding — accepting unverified
				// requests would allow forged webhook events.
				logger.warn(
					"[IG Webhook] Signature verification failed on fallback body — rejecting",
					{
						bodyLen: rawBody.length,
						ip:
							req.headers["x-forwarded-for"] ||
							req.headers["x-real-ip"] ||
							"unknown",
					},
				);
				return apiError(res, 401, "Signature verification failed");
			} else {
				logger.warn("[IG Webhook] Invalid signature", {
					ip:
						req.headers["x-forwarded-for"] ||
						req.headers["x-real-ip"] ||
						"unknown",
					ua: req.headers["user-agent"] || "none",
					receivedSigPrefix: `${signature.slice(0, 12)}...`,
					bodyLen: rawBody.length,
					hadReqBody: !!req.body,
				});
				return apiError(res, 401, "Invalid signature");
			}
		}

		let body: {
			entry?: Array<{
                				id: string;
                				time?: number | undefined;
                				changes?: Array<{ field: string; value: unknown }> | undefined;
                				messaging?: unknown[] | undefined;
                				standby?: unknown[] | undefined;
                				field?: string | undefined;
                				value?: unknown | undefined;
                			}> | undefined;
		};
		try {
			body = JSON.parse(rawBody.toString("utf-8"));
		} catch (err) {
			logger.debug("[IG Webhook] Failed to parse JSON body", {
				error: String(err),
			});
			return apiError(res, 400, "Invalid JSON body");
		}

		// Replay protection — filter stale entries individually so a mixed batch
		// (one fresh + one stale) doesn't silently drop the fresh event.
		const REPLAY_WINDOW_MS = 5 * 60 * 1000;
		const allEntries = body?.entry || [];
		const entries = allEntries.filter((entry) => {
			if (!entry.time) return true;
			const entryTimeMs = entry.time > 1e12 ? entry.time : entry.time * 1000;
			const age = Date.now() - entryTimeMs;
			if (age < -5000 || age > REPLAY_WINDOW_MS) {
				logger.warn("[IG Webhook] Skipping stale entry", {
					age: `${Math.round(age / 1000)}s`,
					entryTime: entry.time,
				});
				return false;
			}
			return true;
		});
		if (allEntries.length > 0 && entries.length === 0) {
			return apiSuccess(res, { status: "ignored", reason: "stale" });
		}

		const supabase = db();
		const rows: Array<{
			event_type: string;
			ig_user_id: string;
			payload: unknown;
		}> = [];

		for (const entry of entries) {
			const igUserId = entry.id as string;

			// Facebook Login format: entry.changes[]
			const changes = entry.changes || [];
			for (const change of changes) {
				rows.push({
					event_type: change.field as string,
					ig_user_id: igUserId,
					payload: change.value,
				});
			}

			// Instagram Login format: entry.messaging[] (no changes wrapper)
			const messaging = entry.messaging || [];
			for (const msgRaw of messaging) {
				const msg = msgRaw as Record<string, unknown>;
				let eventType = "messages";
				if (msg.postback) eventType = "messaging_postbacks";
				else if (msg.reaction) eventType = "message_reactions";
				else if (msg.read) eventType = "messaging_seen";
				else if (msg.message_edit) eventType = "message_edit";
				else if (msg.referral && !msg.message) eventType = "messaging_referral";
				else if (msg.optin) eventType = "messaging_optins";
				else if (
					msg.pass_thread_control ||
					msg.take_thread_control ||
					msg.request_thread_control
				)
					eventType = "messaging_handover";

				// Log story replies with link sticker URL
				const msgMessage = msg.message as Record<string, unknown> | undefined;
				const replyTo = msgMessage?.reply_to as
					| Record<string, unknown>
					| undefined;
				const story = replyTo?.story as Record<string, unknown> | undefined;
				if (story?.link_sticker_url) {
					logger.info("[IG Webhook] Story reply with link sticker", {
						linkStickerUrl: story.link_sticker_url,
					});
				}

				rows.push({
					event_type: eventType,
					ig_user_id: igUserId,
					payload: msg,
				});
			}

			// Standby events use entry.standby[] instead of entry.messaging[]
			const standby = entry.standby || [];
			for (const msg of standby) {
				rows.push({
					event_type: "standby",
					ig_user_id: igUserId,
					payload: msg,
				});
			}

			// Instagram Login format: entry.field + entry.value (comments, live_comments)
			if (entry.field && entry.value) {
				rows.push({
					event_type: entry.field as string,
					ig_user_id: igUserId,
					payload: entry.value,
				});
			}
		}

		if (rows.length > 0) {
			// Extract payload_id for deduplication (prevents duplicate events on Meta retries).
			// Fall back to a SHA-256 content hash so distinct events with no id/mid
			// never collapse onto the same "unknown" dedup key.
			const rowsWithPayloadId = rows.map((row) => ({
				...row,
				payload_id:
					((row.payload as Record<string, unknown> | null | undefined)
						?.id as string) ||
					((row.payload as Record<string, unknown> | null | undefined)
						?.mid as string) ||
					crypto
						.createHash("sha256")
						.update(JSON.stringify(row.payload ?? ""))
						.digest("hex")
						.slice(0, 32),
			}));

			const { data: insertedEvents, error } = await supabase
				.from("ig_webhook_events")
				// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert payload shape mismatch with generated types
				.upsert(rowsWithPayloadId as any, {
					onConflict: "event_type,ig_user_id,payload_id",
					ignoreDuplicates: true,
				})
				.select("*");

			if (error) {
				if (error.code === "23505") {
					logger.info("[IG Webhook] Duplicate event ignored", {
						count: rows.length,
					});
				} else {
					logger.error("[IG Webhook] Insert error", { error: error.message });
					return apiError(res, 500, "Failed to store webhook events");
				}
			}

			const newCount = insertedEvents?.length || 0;
			logger.info("[IG Webhook] Stored events", {
				attempted: rows.length,
				stored: newCount,
			});

			// Nudge webhook-processor via QStash for near-instant pickup
			if (newCount > 0) {
				scheduleWebhookReplay("instagram", 5).catch((err) =>
					logger.debug("[IG Webhook] QStash nudge failed (non-blocking)", {
						error: err instanceof Error ? err.message : String(err),
					}),
				);
			}
		}

		return apiSuccess(res, { received: true });
	}

	return apiError(res, 405, "Method not allowed");
}
