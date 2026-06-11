/**
 * Client-Side Rate Limiter for MCP Tool Calls
 *
 * Prevents runaway agent behavior by:
 * 1. Sliding window: max N calls per minute
 * 2. Exponential backoff on 429 responses
 * 3. Cooldown period after consecutive rate limits
 *
 * This is a local safety net — the backend also enforces rate limits,
 * but this prevents the agent from hammering the API with retries.
 */

/** Max tool calls per sliding window */
const MAX_CALLS_PER_MINUTE = 60;
const WINDOW_MS = 60_000;

/** Backoff state for 429 responses */
let consecutive429s = 0;
let backoffUntil = 0;

/** Sliding window of call timestamps */
const callTimestamps: number[] = [];

/**
 * Check if a tool call is allowed. Returns null if allowed,
 * or an error message with wait time if rate limited.
 */
export function checkRateLimit(): { blocked: true; waitMs: number; reason: string } | null {
	const now = Date.now();

	// Check backoff from 429 responses
	if (now < backoffUntil) {
		const waitMs = backoffUntil - now;
		return {
			blocked: true,
			waitMs,
			reason: `Rate limited by server. Backing off for ${Math.ceil(waitMs / 1000)}s (${consecutive429s} consecutive 429s).`,
		};
	}

	// Prune old timestamps outside the window
	while (callTimestamps.length > 0 && callTimestamps[0] < now - WINDOW_MS) {
		callTimestamps.shift();
	}

	// Check sliding window
	if (callTimestamps.length >= MAX_CALLS_PER_MINUTE) {
		const oldestInWindow = callTimestamps[0];
		const waitMs = oldestInWindow + WINDOW_MS - now;
		return {
			blocked: true,
			waitMs,
			reason: `Client rate limit: ${MAX_CALLS_PER_MINUTE} calls/minute exceeded. Wait ${Math.ceil(waitMs / 1000)}s.`,
		};
	}

	// Allow the call
	callTimestamps.push(now);
	return null;
}

/**
 * Called when a 429 response is received. Applies exponential backoff.
 * @param retryAfterMs - Server-suggested retry delay (from Retry-After header)
 */
export function recordRateLimit(retryAfterMs?: number): void {
	consecutive429s++;
	// Exponential backoff: 2s, 4s, 8s, 16s, 32s (cap at 60s)
	const exponentialMs = Math.min(2000 * Math.pow(2, consecutive429s - 1), 60_000);
	const waitMs = retryAfterMs ? Math.max(retryAfterMs, exponentialMs) : exponentialMs;
	backoffUntil = Date.now() + waitMs;
}

/**
 * Called on successful API response. Resets the 429 backoff counter.
 */
export function recordSuccess(): void {
	if (consecutive429s > 0) {
		consecutive429s = 0;
		backoffUntil = 0;
	}
}
