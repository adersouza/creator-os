/**
 * QStash Failure Callback Handler
 *
 * POST /api/qstash-failure
 *
 * Called by QStash when a message exhausts all retries and lands in the DLQ.
 * The original message body is forwarded here so we can:
 *   1. Mark the affected post/queue-item as failed in the DB
 *   2. Fire a Discord alert
 *
 * Signature-verified via the standard QStash Receiver.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { z } from "./_lib/zodCompat.js";

// QStash signature is the primary guard; this Zod schema is defense in depth
// to clamp shape (any signed payload — even replayed — gets reject if shape
// mismatched). Each id field is constrained to a reasonable size to prevent
// long-string abuse downstream.
const QStashFailurePayloadSchema = z
	.object({
		postId: z.string().min(1).max(128).optional(),
		queueItemId: z.string().min(1).max(128).optional(),
		jobId: z.string().min(1).max(128).optional(),
	})
	.passthrough();

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST") {
		return res.status(405).json({ error: "Method not allowed" });
	}

	const { verifyQStashSignature } = await import("./_lib/qstash.js");
	if (!(await verifyQStashSignature(req, res))) return;

	const { logger, summarizeUserContent } = await import("./_lib/logger.js");
	const { alert, AlertLevel } = await import("./_lib/alerting.js");

	try {
		const callbackBody =
			typeof req.body === "string" ? JSON.parse(req.body) : req.body;
		const sourceBody = decodeSourceBody(callbackBody?.sourceBody);
		const rawBody =
			sourceBody && typeof sourceBody === "object" ? sourceBody : callbackBody;

		const parsed = QStashFailurePayloadSchema.safeParse(rawBody);
		if (!parsed.success) {
			// Return 200 so QStash doesn't retry the failure-callback itself,
			// but log the contract drift so we notice in Sentry.
			logger.warn("[qstash-failure] Payload schema rejected", {
				issues: parsed.error.issues.map((i) => i.message),
			});
			return res
				.status(400)
				.json({ ok: false, error: "Invalid payload shape" });
		}
		const body = parsed.data;

		// QStash forwards the original destination URL in headers
		const originalUrl =
			(req.headers["upstash-failed-callback-url"] as string) ||
			(req.headers["upstash-forward-url"] as string) ||
			"unknown";

		const postId = body.postId;
		const queueItemId = body.queueItemId;
		const jobId = body.jobId;
		const sourceMessageId = callbackBody?.sourceMessageId as string | undefined;

		logger.error("[qstash-failure] Message exhausted retries", {
			originalUrl,
			postId,
			queueItemId,
			jobId,
			sourceMessageId,
			bodySummary: summarizeUserContent(body),
		});

		const { getPrivilegedSupabaseAny, PRIVILEGED_DB_REASONS } = await import(
			"./_lib/privilegedDb.js"
		);
		const { recordInfraEvent } = await import("./_lib/infraTelemetry.js");
		const db = getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.qstashFailure);
		const { data: queueRow } = queueItemId
			? await db
					.from("auto_post_queue")
					.select(
						"status, schedule_nonce, qstash_message_id, workspace_id, group_id",
					)
					.eq("id", queueItemId)
					.maybeSingle()
			: { data: null };
		const { data: postRow } = postId
			? await db
					.from("posts")
					.select("status, metadata, user_id, qstash_message_id")
					.eq("id", postId)
					.maybeSingle()
			: { data: null };

		// ── Mark scheduled post as failed ──
		if (postId) {
			const currentMessageId =
				typeof postRow?.qstash_message_id === "string"
					? postRow.qstash_message_id
					: typeof postRow?.metadata?.qstash_message_id === "string"
						? postRow.metadata.qstash_message_id
						: null;
			const staleCallback =
				!!sourceMessageId &&
				!!currentMessageId &&
				currentMessageId !== sourceMessageId;

			if (staleCallback) {
				logger.warn("[qstash-failure] Ignoring stale scheduled post callback", {
					postId,
					sourceMessageId,
					currentQstashMessageId: currentMessageId,
				});
				await recordInfraEvent("qstash-dlq-scheduled-post-stale-callback", {
					postId,
					sourceMessageId,
					currentQstashMessageId: currentMessageId,
					postStatus: postRow?.status ?? null,
					userId: postRow?.user_id ?? null,
				});
			} else {
				await db
					.from("posts")
					.update({
						status: "failed",
						error_message: "QStash retries exhausted",
						qstash_dispatch_status: "failed",
						qstash_failure_reason: "qstash_retries_exhausted",
						updated_at: new Date().toISOString(),
					})
					.eq("id", postId)
					.in("status", ["scheduled", "publishing"]);
				await recordInfraEvent("qstash-dlq-scheduled-post", {
					postId,
					sourceMessageId: sourceMessageId ?? null,
					currentQstashMessageId: currentMessageId,
					postStatus: postRow?.status ?? null,
					userId: postRow?.user_id ?? null,
				});
			}
		}

		// ── Mark auto-post queue item as dead_letter ──
		if (queueItemId) {
			const staleCallback =
				!!sourceMessageId &&
				!!queueRow?.qstash_message_id &&
				queueRow.qstash_message_id !== sourceMessageId;

			if (staleCallback) {
				logger.warn("[qstash-failure] Ignoring stale failure callback", {
					queueItemId,
					sourceMessageId,
					currentQstashMessageId: queueRow.qstash_message_id,
				});
				await recordInfraEvent("qstash-dlq-autopost-stale-callback", {
					queueItemId,
					sourceMessageId,
					currentQstashMessageId: queueRow.qstash_message_id,
					queueStatus: queueRow?.status ?? null,
					workspaceId: queueRow?.workspace_id ?? null,
					groupId: queueRow?.group_id ?? null,
				});
			} else {
				await db
					.from("auto_post_queue")
					.update({
						status: "dead_letter",
						dead_letter_reason: "QStash retries exhausted",
						last_error: "QStash retries exhausted",
						qstash_message_id: null,
						schedule_nonce: null,
						claimed_at: null,
						next_retry_at: null,
						updated_at: new Date().toISOString(),
					})
					.eq("id", queueItemId)
					.in("status", ["pending", "queued", "publishing"]);
				await recordInfraEvent("qstash-dlq-autopost", {
					queueItemId,
					sourceMessageId: sourceMessageId ?? null,
					queueStatus: queueRow?.status ?? null,
					scheduleNonce: queueRow?.schedule_nonce ?? null,
					qstashMessageId: queueRow?.qstash_message_id ?? null,
					workspaceId: queueRow?.workspace_id ?? null,
					groupId: queueRow?.group_id ?? null,
				});
			}
		}

		// ── Mark export job as failed ──
		// Status filter mirrors the post path: only an in-flight job should
		// transition to failed. Without this gate, a replayed callback could
		// mark a completed/failed/cancelled job as failed (covering up actual
		// completion in audit trails).
		if (jobId && !postId && !queueItemId && originalUrl.includes("publish-worker")) {
			await db
				.from("publish_jobs")
				.update({
					status: "failed",
					stage: "failed",
					error_code: "QSTASH_RETRIES_EXHAUSTED",
					error_message: "QStash retries exhausted",
					completed_at: new Date().toISOString(),
					updated_at: new Date().toISOString(),
				})
				.eq("id", jobId)
				.in("status", ["queued", "publishing", "retrying"]);
			await recordInfraEvent("qstash-dlq-publish-job", {
				jobId,
				sourceMessageId: sourceMessageId ?? null,
			});
		} else if (jobId && !postId && !queueItemId) {
			await db
				.from("export_jobs")
				.update({ status: "failed", error: "QStash retries exhausted" })
				.eq("id", jobId)
				.in("status", ["pending", "queued", "running", "processing"]);
		}

		// ── Discord alert ──
		const itemType = postId
			? "scheduled post"
			: queueItemId
				? "auto-post"
				: jobId
					? originalUrl.includes("publish-worker")
						? "publish job"
						: "export job"
					: "message";
		const itemId = postId || queueItemId || jobId || "unknown";
		await alert(
			AlertLevel.ERROR,
			`QStash DLQ: ${itemType} failed permanently`,
			{
				itemId,
				originalUrl,
			},
		);

		return res.status(200).json({ ok: true, handled: itemType, itemId });
	} catch (err) {
		logger.error("[qstash-failure] Handler error", { error: String(err) });
		// Report to Sentry so failures are visible in monitoring
		import("./_lib/sentryServer.js")
			.then(({ captureServerException }) =>
				captureServerException(err, { handler: "qstash-failure" }),
			)
			.catch(() => {});
		// Return 200 to prevent QStash from retrying the failure callback itself
		return res
			.status(200)
			.json({ ok: false, error: "Internal error processing failure callback" });
	}
}

function decodeSourceBody(encoded: unknown): unknown {
	if (typeof encoded !== "string" || encoded.length === 0) return null;
	try {
		const decoded = Buffer.from(encoded, "base64").toString("utf8");
		return JSON.parse(decoded);
	} catch {
		return null;
	}
}
