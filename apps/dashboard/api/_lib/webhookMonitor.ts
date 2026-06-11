/**
 * Webhook Signature Failure Monitor
 *
 * Tracks per-platform signature failure counts in Redis and fires a Discord
 * alert when failures exceed the hourly threshold.
 *
 * Design notes:
 * - Alert only, no auto-pause. Auto-pausing based on failure rate is a DoS
 *   vector: an attacker sends bad signatures to trigger the pause and stop
 *   legitimate events from being processed. Alert + human response is safer.
 * - Non-blocking: wrapped in try-catch so monitoring never fails a request.
 * - Threshold is configurable via WEBHOOK_SIG_FAILURE_THRESHOLD (default: 50).
 *   At 2× threshold the alert escalates from WARN to ERROR.
 * - TTL is set on first increment (2h) so keys don't accumulate in Redis.
 */

import { AlertLevel, alert } from "./alerting.js";
import { logger } from "./logger.js";
import { getRedis } from "./redis.js";

export const SIG_FAILURE_THRESHOLD = parseInt(
	process.env.WEBHOOK_SIG_FAILURE_THRESHOLD || "50",
	10,
);

/**
 * Increment the hourly signature failure counter for a platform.
 * Fires a Discord alert if the count crosses SIG_FAILURE_THRESHOLD.
 *
 * Call this immediately after a signature verification failure, before
 * returning the 401 response.
 */
export async function incrementAndCheckSigFailures(
	platform: "threads" | "instagram",
): Promise<void> {
	try {
		const redis = getRedis();
		const hour = new Date().toISOString().slice(0, 13); // "2026-03-08T14"
		const key = `webhook:sig-fail:${platform}:${hour}`;

		const count = await redis.incr(key);
		// Set TTL on first increment so keys don't accumulate indefinitely.
		// 2h window: the current hour + one hour of buffer for late processing.
		if (count === 1) {
			await redis.expire(key, 2 * 3600);
		}

		if (count >= SIG_FAILURE_THRESHOLD) {
			const level =
				count >= SIG_FAILURE_THRESHOLD * 2 ? AlertLevel.ERROR : AlertLevel.WARN;
			await alert(level, `Webhook signature failures spike — ${platform}`, {
				platform,
				failuresThisHour: String(count),
				threshold: String(SIG_FAILURE_THRESHOLD),
				action:
					"Check webhook secret configuration and review source IPs in logs",
			});
		}
	} catch (err) {
		// Non-blocking — monitoring must never fail the webhook request
		logger.debug("[WebhookMonitor] Failed to record signature failure", {
			platform,
			error: err instanceof Error ? err.message : String(err),
		});
	}
}
