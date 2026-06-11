/**
 * Rate limiting functions for scheduled post publishing.
 * Uses database-backed rate limits with row-level locking.
 */

import { logger } from "../../logger.js";
import type { RateLimitResult } from "./shared.js";
import { db, RATE_LIMITS } from "./shared.js";

/**
 * Check rate limits AND atomically increment if allowed.
 * Uses database function with row-level locking to prevent race conditions
 * between concurrent cron executions.
 *
 * Note: withCronLock prevents overlapping cron instances, so per-account rate limits are safe.
 * The rate limit RPC is called per-post to respect Meta API rate limits.
 */
export async function checkAndIncrementRateLimit(
	accountId: string,
): Promise<{ allowed: boolean; reason?: string | undefined }> {
	try {
		// Call the database function that atomically checks and increments
		const { data, error } = await db().rpc("check_and_increment_rate_limit", {
			p_account_id: accountId,
			p_hourly_limit: RATE_LIMITS.POSTS_PER_HOUR,
			p_daily_limit: RATE_LIMITS.POSTS_PER_DAY,
		});

		if (error) {
			logger.error("Rate limit check error", {
				accountId,
				error: String(error),
			});
			// Fail closed: better to skip a post than exceed API limits
			return { allowed: false, reason: "Rate limit check failed" };
		}

		const result = data?.[0] as RateLimitResult | undefined;

		if (!result) {
			// No result means function didn't return properly, fail closed
			logger.error("Rate limit check returned no result", { accountId });
			return { allowed: false, reason: "Rate limit check returned no result" };
		}

		if (!result.allowed) {
			return {
				allowed: false,
				reason: result.reason || "Rate limit exceeded",
			};
		}

		// Allowed - counter was already incremented by the DB function
		logger.info("Rate limit OK", {
			accountId,
			postsThisHour: result.posts_this_hour,
			hourlyLimit: RATE_LIMITS.POSTS_PER_HOUR,
			postsToday: result.posts_today,
			dailyLimit: RATE_LIMITS.POSTS_PER_DAY,
		});
		return { allowed: true };
	} catch (error) {
		logger.error("Rate limit check exception", {
			accountId,
			error: String(error),
		});
		// Fail closed: better to skip a post than exceed API limits
		return { allowed: false, reason: "Rate limit check exception" };
	}
}

/**
 * Get current rate limit status without incrementing (read-only).
 * Useful for displaying status to users.
 */
export async function getRateLimitStatus(accountId: string): Promise<{
	postsThisHour: number;
	postsToday: number;
	hourlyRemaining: number;
	dailyRemaining: number;
} | null> {
	const failClosed = {
		postsThisHour: RATE_LIMITS.POSTS_PER_HOUR,
		postsToday: RATE_LIMITS.POSTS_PER_DAY,
		hourlyRemaining: 0,
		dailyRemaining: 0,
	};
	try {
		const { data, error } = await db().rpc("get_rate_limit_status", {
			p_account_id: accountId,
			p_hourly_limit: RATE_LIMITS.POSTS_PER_HOUR,
			p_daily_limit: RATE_LIMITS.POSTS_PER_DAY,
		});

		if (error || !data?.[0]) {
			logger.error("Rate limit status check failed (fail-closed)", {
				accountId,
				error: error ? String(error) : "empty_result",
			});
			return failClosed;
		}

		const result = data[0];
		return {
			postsThisHour: result.posts_this_hour,
			postsToday: result.posts_today,
			hourlyRemaining: result.hourly_remaining,
			dailyRemaining: result.daily_remaining,
		};
	} catch (err) {
		logger.error("Rate limit status check exception (fail-closed)", {
			accountId,
			error: String(err),
		});
		return failClosed;
	}
}
