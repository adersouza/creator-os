/**
 * Webhook Processor Shared Utilities
 *
 * Helpers used by both Threads and Instagram webhook event processors.
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
} from "./types.js";

/** Parse webhook timestamp — handles both ISO 8601 strings and Unix seconds */
export function parseWebhookTimestamp(ts: string | number): string {
	if (typeof ts === "string") {
		const d = new Date(ts);
		if (!Number.isNaN(d.getTime())) return d.toISOString();
	}
	if (typeof ts === "number") {
		// Unix seconds (10 digits) vs milliseconds (13 digits)
		const ms = ts > 1e12 ? ts : ts * 1000;
		const d = new Date(ms);
		if (!Number.isNaN(d.getTime())) return d.toISOString();
	}
	return new Date().toISOString();
}

export async function getAccountToken(
	supabase: SupabaseClient,
	accountId: string,
): Promise<string> {
	const { data } = await supabase
		.from("accounts")
		.select("threads_access_token_encrypted")
		.eq("id", accountId)
		.maybeSingle();
	return data?.threads_access_token_encrypted || "";
}

export const WEBHOOK_TABLES: Record<Platform, string> = {
	threads: "threads_webhook_events",
	instagram: "ig_webhook_events",
};

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
