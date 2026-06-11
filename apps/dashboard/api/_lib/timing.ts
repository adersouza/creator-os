/**
 * Centralized timing constants — TTLs, timeouts, and durations.
 *
 * Import from here instead of hardcoding values across files.
 * Not every timeout needs to use these (inline AbortSignal.timeout(10_000)
 * is fine for one-off calls), but named constants used in multiple files
 * should be defined here.
 */

// ============================================================================
// Fetch timeouts (milliseconds)
// ============================================================================

/** Standard timeout for Meta Graph API / external service calls */
export const FETCH_TIMEOUT_MS = 10_000;

/** Extended timeout for AI provider calls (Gemini, xAI) */
export const AI_FETCH_TIMEOUT_MS = 30_000;

/** Timeout for image download in transform pipeline */
export const IMAGE_FETCH_TIMEOUT_MS = 15_000;

// ============================================================================
// Redis/cache TTLs (seconds)
// ============================================================================

/** 5 minutes — short-lived cache for rapidly changing data */
export const TTL_5_MIN = 300;

/** 1 hour — standard cache/lock TTL */
export const TTL_1_HOUR = 3_600;

/** 30 days — long-lived dedup/snooze/deprioritize TTL */
export const TTL_30_DAYS = 30 * 24 * 60 * 60;
