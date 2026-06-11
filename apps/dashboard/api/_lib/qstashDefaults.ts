/**
 * QStash publish defaults — centralized retry counts, failure callbacks,
 * and batch-size caps so every call site stays consistent.
 *
 * Retry tiers:
 *   CRITICAL (3) — scheduled posts, auto-post publish
 *   IMPORTANT (2) — analytics sync, engagement, queue-fill, export
 *   BEST_EFFORT (1) — DM backfill, recovery nudges, cron-to-cron
 *
 * Failure callback:
 *   Critical publishes include a `failureCallback` URL so the app is
 *   notified when QStash exhausts all retries. The handler at
 *   /api/qstash-failure records the failure + fires a Discord alert.
 */

/** Maximum messages per batchJSON call (QStash limit is 1 000) */
export const MAX_BATCH_SIZE = 100;

/** Retry tiers */
export const RETRIES = {
	CRITICAL: 3,
	IMPORTANT: 2,
	BEST_EFFORT: 1,
} as const;

/** Resolve the absolute app base URL for internal job callbacks. */
export function getRequiredAppBaseUrl(): string {
	const base =
		process.env.APP_URL ||
		(process.env.VERCEL_URL ? `https://${process.env.VERCEL_URL}` : "");

	if (!base) {
		throw new Error(
			"Missing APP_URL or VERCEL_URL for QStash/internal callback routing",
		);
	}

	return base.replace(/\/+$/, "");
}

/** Build the absolute failure-callback URL */
export function getFailureCallbackUrl(): string {
	return `${getRequiredAppBaseUrl()}/api/qstash-failure`;
}
