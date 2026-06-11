import { logger } from "../logger.js";
import { checkMetaAppUsage } from "../metaApiConfig.js";

// Re-export so existing callers (analytics-pipeline.ts) need no import changes.
export { MetaRateLimitError } from "../metaApiConfig.js";

export const MAX_EXECUTION_TIME = parseInt(
	process.env.MAX_EXECUTION_TIME || "240000",
	10,
);
// Minimum time that must remain before starting another batch.
// Each batch takes ~20-25s under normal conditions; 35s gives a safe buffer.
const MIN_BATCH_BUDGET = 35000;

export function isTimeBudgetExceeded(startTime: number): boolean {
	return Date.now() - startTime >= MAX_EXECUTION_TIME;
}

/** Returns false if there is not enough budget left to safely start another batch. */
export function hasBatchBudget(startTime: number): boolean {
	return Date.now() - startTime < MAX_EXECUTION_TIME - MIN_BATCH_BUDGET;
}

export const ACCOUNT_CONCURRENCY = parseInt(
	process.env.ANALYTICS_CONCURRENCY ?? "5",
	10,
);
export const POST_BATCH_SIZE = parseInt(
	process.env.ANALYTICS_BATCH_SIZE || "25",
	10,
);
export const DELAY_BETWEEN_BATCHES = parseInt(
	process.env.DELAY_BETWEEN_BATCHES || "500",
	10,
);

import { FETCH_TIMEOUT_MS } from "../timing.js";

export { FETCH_TIMEOUT_MS as FETCH_TIMEOUT } from "../timing.js";

const FETCH_TIMEOUT = FETCH_TIMEOUT_MS;

/**
 * Read the latest cached x-app-usage metrics from Redis.
 *
 * Returns null if no entry exists, Redis is unavailable, or the entry is
 * older than 5 minutes (stale after a quiet period or function restart).
 *
 * Used by batch orchestrators to pre-check Meta API pressure before
 * starting a new batch — complementing the reactive per-call backpressure
 * in checkMetaAppUsage().
 */
export async function readCachedMetaUsage(): Promise<{
	maxPct: number;
	ts: number;
} | null> {
	try {
		const { getRedis } = await import("../redis.js");
		const raw = await getRedis().get("meta:app-usage:latest");
		if (!raw) return null;
		const parsed =
			typeof raw === "string"
				? (JSON.parse(raw) as { maxPct: number; ts: number })
				: (raw as { maxPct: number; ts: number });
		// Discard readings older than 5 minutes — they reflect a past traffic pattern.
		if (Date.now() - parsed.ts > 5 * 60 * 1000) return null;
		return parsed;
	} catch {
		return null; // Non-blocking — Redis unavailable is not a fatal error
	}
}

export async function fetchWithTimeout(
	url: string,
	options: RequestInit = {},
	timeoutMs: number = FETCH_TIMEOUT,
	context?: string,
): Promise<Response> {
	const controller = new AbortController();
	const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

	try {
		const response = await fetch(url, {
			...options,
			signal: controller.signal,
		});

		if (response.status === 429) {
			const retryAfter = response.headers.get("retry-after") || "unknown";
			logger.warn("Rate limited (429) during analytics refresh", {
				context,
				retryAfter,
				url: url.split("?")[0],
			});
		}

		// Delegate x-app-usage backpressure to shared implementation in metaApiConfig.ts
		await checkMetaAppUsage(response, context ?? "fetchWithTimeout");

		return response;
	} finally {
		clearTimeout(timeoutId);
	}
}
