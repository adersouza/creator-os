/**
 * Webhook retry and replay scheduling.
 * Handles dead-letter classification, exponential backoff, and QStash replay scheduling.
 */

import type { SupabaseClient } from "@supabase/supabase-js";
import { logger, serializeError } from "../../logger.js";
import type { Platform } from "../../platform.js";
import { getQStashClient } from "../../qstash.js";
import { RETRIES } from "../../qstashDefaults.js";
import { getRedis } from "../../redis.js";
import { calculateBackoff, shouldRetry } from "../../retryUtils.js";
import type {
	IgWebhookEvent,
	ThreadsWebhookEvent,
	WebhookEventUpdate,
} from "./shared.js";
import { WEBHOOK_TABLES } from "./shared.js";

export async function scheduleWebhookReplay(
	platform: Platform,
	delaySeconds: number = 60,
): Promise<void> {
	try {
		const cronSecret = process.env.CRON_SECRET;
		const baseUrl =
			process.env.APP_URL ||
			(process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "");
		if (!cronSecret || !baseUrl) {
			logger.warn(
				"Cannot schedule webhook replay — missing CRON_SECRET or APP_URL/VERCEL_URL",
			);
			return;
		}

		try {
			const redis = getRedis();
			const dedupKey = `webhook-replay:${platform}`;
			const ttl = Math.max(delaySeconds, 15);
			const wasSet = await redis.set(dedupKey, "1", { nx: true, ex: ttl });
			if (wasSet !== "OK") {
				logger.debug("Webhook replay already scheduled", { platform });
				return;
			}
		} catch (err) {
			logger.debug("Redis unavailable for replay dedup — continuing", {
				error: serializeError(err),
			});
		}

		const qstash = getQStashClient();
		await qstash.publishJSON({
			url: `${baseUrl}/api/cron/webhook-processor?platform=${platform}`,
			body: { platform },
			delay: delaySeconds,
			retries: RETRIES.CRITICAL,
			headers: {
				Authorization: `Bearer ${cronSecret}`,
			},
		});
	} catch (err) {
		logger.error("Failed to schedule webhook replay", {
			platform,
			error: serializeError(err),
		});
	}
}

export async function markWebhookEventForRetry(
	supabase: SupabaseClient,
	platform: Platform,
	event: ThreadsWebhookEvent | IgWebhookEvent,
	errorMessage: string,
): Promise<void> {
	const table = WEBHOOK_TABLES[platform];
	const retryCount = event.retry_count ?? 0;

	if (!shouldRetry(retryCount)) {
		await supabase
			.from(table)
			.update({
				processed: true,
				processed_at: new Date().toISOString(),
				error: `Max retries exceeded: ${errorMessage}`,
				dead_letter: true,
				dead_letter_at: new Date().toISOString(),
				dead_letter_reason: `Exhausted ${retryCount} retries: ${errorMessage}`,
			} as WebhookEventUpdate)
			.eq("id", event.id);
		return;
	}

	const nextRetryAt = calculateBackoff(retryCount, 30000);
	await supabase
		.from(table)
		.update({
			error: errorMessage,
			last_error: errorMessage,
			retry_count: retryCount + 1,
			next_retry_at: nextRetryAt.toISOString(),
		} as WebhookEventUpdate)
		.eq("id", event.id);

	const delaySeconds = Math.max(
		30,
		Math.round((nextRetryAt.getTime() - Date.now()) / 1000),
	);
	await scheduleWebhookReplay(platform, delaySeconds);
}
