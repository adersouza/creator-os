/**
 * Unified Webhook Event Processor
 *
 * Cron job that processes queued webhook events from both platforms:
 * - Threads: replies, mentions, publish events
 * - Instagram: comments, live_comments, mentions, story_insights, messaging, message_reactions, message_edit, messaging_seen, follow
 *
 * Runs every 2 minutes via Vercel Cron, plus on-demand via QStash replay.
 *
 * This file is a thin orchestrator. Platform-specific processors, retry logic,
 * batch event loops, and shared types live in api/_lib/cron/webhook-processor/.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { alertCronFailure } from "../_lib/alerting.js";
import { verifyCronAuth } from "../_lib/apiResponse.js";
import { trackCronRun, withCronLock } from "../_lib/cronUtils.js";
import { logger } from "../_lib/logger.js";
import {
	getPrivilegedSupabase,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";
import { verifyQStashSignature } from "../_lib/qstash.js";

// Lazy-import batch loops inside handler to avoid Vercel bundler tracing issues
// with the webhook-processor subdirectory (ERR_MODULE_NOT_FOUND at runtime).

// ============================================================================
// Main Handler
// ============================================================================

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST" && req.method !== "GET") {
		return res.status(405).json({ error: "Method not allowed" });
	}

	const hasQStashSignature =
		typeof req.headers["upstash-signature"] === "string";
	if (hasQStashSignature) {
		if (!(await verifyQStashSignature(req, res))) {
			return;
		}
	} else if (!verifyCronAuth(req, res)) {
		return;
	}

	const platformParam =
		typeof req.query.platform === "string" ? req.query.platform : "both";
	const runThreads = platformParam === "threads" || platformParam === "both";
	const runIg = platformParam === "instagram" || platformParam === "both";

	const supabase = getPrivilegedSupabase(
		PRIVILEGED_DB_REASONS.cronWebhookProcessing,
	);

	const lockResult = await withCronLock(
		supabase,
		"webhook-processor",
		async () => {
			return trackCronRun(supabase, "webhook-processor", async () => {
				try {
					const startTime = Date.now();
					const { processThreadsWebhookEvents, processIgWebhookEvents } =
						await import("../_lib/cron/webhook-processor/event-loop.js");
					// Process Threads events first, then Instagram events
					const threadsCount = runThreads
						? await processThreadsWebhookEvents(supabase, startTime)
						: 0;
					const igCount = runIg
						? await processIgWebhookEvents(supabase, startTime)
						: 0;

					// Process queued outgoing webhook deliveries (Pro/Empire retry queue)
					let outgoingCount = 0;
					try {
						const { processWebhookDeliveries } = await import(
							"../_lib/webhookDispatcher.js"
						);
						outgoingCount = await processWebhookDeliveries();
					} catch (outErr) {
						logger.warn(
							"[webhook-processor] Outgoing delivery processing failed",
							{
								error:
									outErr instanceof Error ? outErr.message : String(outErr),
							},
						);
					}

					return { itemsProcessed: threadsCount + igCount + outgoingCount };
				} catch (error) {
					try {
						const { captureServerException } = await import(
							"../_lib/sentryServer.js"
						);
						await captureServerException(error, {
							cronJob: "webhook-processor",
						});
					} catch (_sentryErr) {
						logger.warn("[webhook-processor] Sentry capture failed", {
							error: String(_sentryErr),
						});
					}
					alertCronFailure(
						"webhook-processor",
						error instanceof Error ? error.message : String(error),
					);
					throw error;
				}
			});
		},
		65,
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ success: true });
}
