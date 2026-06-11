/**
 * QStash Receiver — Scheduled Post Publish
 *
 * Called by QStash at the exact scheduled_for time to publish a single post.
 * Auth: QStash signature verification (not user auth).
 *
 * POST /api/scheduled-post-publish
 * Body: { postId: string }
 *
 * Returns 200 when: post published, already claimed, not found, or already
 * in a terminal state (these should NOT be retried by QStash).
 * Returns 500 when: actual publish failure or unhandled exception
 * (QStash will retry up to 2 times on 5xx).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { logger } from "./_lib/logger.js";
import { verifyQStashSignature } from "./_lib/qstash.js";
import { getSupabase } from "./_lib/supabase.js";
import { z } from "./_lib/zodCompat.js";

const ScheduledPublishBodySchema = z.object({
	postId: z.string().min(1),
});

// biome-ignore lint/suspicious/noExplicitAny: posts columns not fully typed
const db = (): any => getSupabase();
const EARLY_DELIVERY_TOLERANCE_MS = 5_000;

/** Results where retrying won't help — return 200 so QStash stops. */
const NON_RETRYABLE_RESULTS = new Set(["published", "container_pending", "notified"]);
const NON_RETRYABLE_ERRORS = new Set([
	"not_found",
	"not_found_or_not_scheduled",
	"claim_failed",
	"status_changed_before_publish",
	"status_changed_before_chain_publish",
	"account_not_configured",
	"empty_content",
	"content_too_long",
	"caption_too_long",
	"story_no_media",
	"media_inaccessible",
	"chain_post_too_long",
	"media_timeout",
	"reminder_window",
	"not_notify_mode",
	"notification_unavailable",
	"audit_failed",
	"kill_switch",
]);

function exceptionDetails(err: unknown) {
	return err instanceof Error
		? {
				name: err.name,
				message: err.message,
				stack: err.stack,
			}
		: {
				name: typeof err,
				message: String(err),
				stack: undefined,
			};
}

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST") {
		const { apiError } = await import("./_lib/apiResponse.js");
		return apiError(res, 405, "Method not allowed");
	}

	logger.info("[scheduled-post-publish] Request received", {
		method: req.method,
		hasBody: !!req.body,
	});

	if (!(await verifyQStashSignature(req, res))) return;

	const parsed = ScheduledPublishBodySchema.safeParse(req.body);
	if (!parsed.success) {
		logger.warn("[scheduled-post-publish] Body parse failed", {
			issues: parsed.error.issues.map((issue) => ({
				path: issue.path.join("."),
				code: issue.code,
				message: issue.message,
			})),
		});
		return res
			.status(400)
			.json({ ok: false, skipped: true, reason: "invalid_body" });
	}
	const { postId } = parsed.data;
	const traceId = (req.body as Record<string, unknown>)?.traceId as
		| string
		| undefined;
	if (traceId) {
		logger.info("[scheduled-post-publish] Start", { postId, traceId });
	}
	logger.info("[scheduled-post-publish] Parsed body", { postId, traceId });

	try {
		// Guard: post must still exist and be in scheduled status
		logger.info("[scheduled-post-publish] Loading post", { postId, traceId });
		const { data: post } = await db()
			.from("posts")
			.select("id, status, scheduled_for")
			.eq("id", postId)
			.maybeSingle();

		logger.info("[scheduled-post-publish] Post loaded", {
			postId,
			traceId,
			found: !!post,
			status: post?.status ?? null,
			scheduledFor: post?.scheduled_for ?? null,
		});

		if (!post) {
			logger.warn("[scheduled-post-publish] Skipped before publish", {
				postId,
				traceId,
				reason: "not_found",
			});
			return res
				.status(200)
				.json({ ok: true, skipped: true, reason: "not_found" });
		}

		if (post.status !== "scheduled") {
			logger.warn("[scheduled-post-publish] Skipped before publish", {
				postId,
				traceId,
				reason: "status_not_scheduled",
				status: post.status,
				scheduledFor: post.scheduled_for,
			});
			return res
				.status(200)
				.json({ ok: true, skipped: true, reason: post.status });
		}

		const scheduledAt = post.scheduled_for
			? Date.parse(post.scheduled_for)
			: Number.NaN;
		if (
			Number.isFinite(scheduledAt) &&
			Date.now() + EARLY_DELIVERY_TOLERANCE_MS < scheduledAt
		) {
			logger.info("[scheduled-post-publish] Skipped stale early delivery", {
				postId,
				traceId,
				scheduledFor: post.scheduled_for,
			});
			return res
				.status(200)
				.json({ ok: true, skipped: true, reason: "not_due" });
		}

		// Delegate to the shared publish function
		const { publishSinglePost } = await import("./_lib/publishPost.js");
		logger.info("[scheduled-post-publish] Calling publishSinglePost", {
			postId,
			traceId,
		});
		const result = await publishSinglePost(postId);

		logger.info("[scheduled-post-publish] Done", {
			postId,
			traceId,
			result: result.result,
			error: result.error ?? null,
		});

		// Determine if QStash should retry
		if (NON_RETRYABLE_RESULTS.has(result.result)) {
			return res.status(200).json({ ok: true, ...result });
		}
		if (
			result.result === "skipped" &&
			result.error &&
			NON_RETRYABLE_ERRORS.has(result.error)
		) {
			return res.status(200).json({ ok: true, ...result });
		}
		if (result.result === "rescheduled") {
			// Already rescheduled by publishSinglePost — don't let QStash retry too
			return res.status(200).json({ ok: true, ...result });
		}

		// Actual failure or retryable skip — return 500 so QStash retries
		if (result.result === "failed" || result.result === "skipped") {
			logger.warn("[scheduled-post-publish] Returning 500 for QStash retry", {
				postId,
				result: result.result,
				error: result.error,
			});
			return res
				.status(500)
				.json({ ok: false, result: result.result, error: "publish_failed" });
		}

		return res.status(200).json({ ok: true, ...result });
	} catch (err: unknown) {
		logger.error("[scheduled-post-publish] Unhandled", {
			postId,
			traceId,
			error: exceptionDetails(err),
		});
		import("./_lib/sentryServer.js")
			.then(({ captureServerException }) =>
				captureServerException(err, {
					cronJob: "scheduled-post-publish",
					postId,
				}),
			)
			.catch(() => {});
		return res
			.status(500)
			.json({ ok: false, result: "error", error: "publish_failed" });
	}
}
