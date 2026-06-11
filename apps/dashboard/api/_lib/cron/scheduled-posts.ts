/**
 * Scheduled Posts Processing Cron Job
 * Runs every 5 minutes to publish posts when their scheduled time arrives.
 *
 * Schedule: every 5 minutes (configured in vercel.json)
 *
 * This file is a thin orchestrator. All implementation logic lives in
 * sub-modules under ./scheduled-posts/:
 *   - shared.ts         — Types, constants, transient error detection
 *   - rateLimit.ts      — Rate limit check/increment (DB-backed)
 *   - mediaValidation.ts — Media URL accessibility checks
 *   - crossPost.ts      — Cross-platform post queuing (Threads <-> IG)
 *   - maintenance.ts    — Cleanup, retry, orphan rescue
 *   - publishThreads.ts — Threads publishing pipeline
 *   - publishInstagram.ts — Instagram publishing pipeline
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { alertCronFailure } from "../alerting.js";
import { trackCronRun, withCronLock } from "../cronUtils.js";
import { logger, serializeError } from "../logger.js";
import { getSupabase } from "../supabase.js";

export type { CrossPostRecord } from "./scheduled-posts/index.js";
// Re-export everything from sub-modules for backward compatibility.
// Consumers like publishPost.ts and publish-worker.ts import from this file.
export {
	checkAndIncrementRateLimit,
	checkMediaUrlAccessible,
	config,
	getRateLimitStatus,
	handleCrossPost,
	isTransientError,
	RATE_LIMITS,
} from "./scheduled-posts/index.js";

// Import orchestration functions
import {
	cleanupOrphanedPosts,
	cleanupRejectedQueue,
	rescueStuckIGPosts,
	rescueStuckThreadsPosts,
	retryFailedPosts,
} from "./scheduled-posts/maintenance.js";
import {
	processNewIGPosts,
	retryIGContainers,
} from "./scheduled-posts/publishInstagram.js";
import { processThreadsPosts } from "./scheduled-posts/publishThreads.js";
import type { ProcessingStats } from "./scheduled-posts/shared.js";

const db = () => getSupabase();

// ============================================================================
// Main Handler
// ============================================================================

export default async function handler(req: VercelRequest, res: VercelResponse) {
	// Strict cron secret check — no x-vercel-cron fallback (spoofable header)
	const { verifyCronAuth } = await import("../apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const supabase = db();

	const lockResult = await withCronLock(
		supabase,
		"scheduled-posts",
		async () => {
			return trackCronRun(supabase, "scheduled-posts", async () => {
				const itemsProcessed = await processScheduledPosts();
				return { itemsProcessed };
			});
		},
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ success: true });
}

// ============================================================================
// Orchestrator
// ============================================================================

export async function processScheduledPosts(): Promise<number> {
	logger.info("Starting scheduled posts processing");

	const stats: ProcessingStats = {
		found: 0,
		published: 0,
		failed: 0,
		retried: 0,
		rateLimited: 0,
		errors: [],
	};

	try {
		const startTime = Date.now();
		const MAX_RUNTIME_MS = 140_000; // 140s budget (publish-worker has 180s maxDuration)

		// ================================================================
		// STEP 0a: Clean up old rejected rows from auto_post_queue (>7 days)
		// ================================================================
		await cleanupRejectedQueue();

		// ================================================================
		// STEP 0b: Retry recently failed posts with transient errors
		// ================================================================
		await retryFailedPosts(stats);

		// ================================================================
		// STEP 0.5: Cleanup orphaned "publishing" posts (stuck > 30 min)
		// ================================================================
		await cleanupOrphanedPosts();

		// ================================================================
		// STEP 0.6: Rescue stuck Threads scheduled posts (overdue > 30 min)
		// ================================================================
		await rescueStuckThreadsPosts(stats);

		// ================================================================
		// STEP 1: Process Threads scheduled posts
		// ================================================================
		await processThreadsPosts(stats, startTime, MAX_RUNTIME_MS);

		// ================================================================
		// STEP 1.5 + 2: Process Instagram (container retry + new posts)
		// ================================================================
		if (Date.now() - startTime > MAX_RUNTIME_MS) {
			logger.warn(
				"Approaching timeout after Threads posts, skipping Instagram processing",
			);
			logger.info("Threads stats", { ...stats });
			return stats.published;
		}

		logger.info("Checking for Instagram scheduled posts");

		// STEP 1 (IG): Retry posts with existing containers
		await retryIGContainers(stats, startTime, MAX_RUNTIME_MS);

		// STEP 1.5: Rescue stuck IG scheduled posts
		await rescueStuckIGPosts();

		// STEP 2: Process new scheduled IG posts
		await processNewIGPosts(stats, startTime, MAX_RUNTIME_MS);

		logger.info("Processing complete", { ...stats });
		return stats.published;
	} catch (error: unknown) {
		const errorMessage = serializeError(error);
		logger.error("Fatal error", {
			error: errorMessage,
		});
		// Report to Sentry
		try {
			const { captureServerException } = await import("../sentryServer.js");
			await captureServerException(error, { cronJob: "scheduled-posts" });
		} catch (_sentryErr) {
			logger.warn("[scheduled-posts] Sentry capture failed", {
				error: String(_sentryErr),
			});
		}
		alertCronFailure("scheduled-posts", errorMessage);
		throw error;
	}
}
