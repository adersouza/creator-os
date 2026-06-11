/**
 * Agent Circuit Breaker
 *
 * Automatically pauses the agent when anomalous behavior is detected.
 * Uses Redis counters for distributed state across Vercel instances.
 *
 * Trip conditions (all auto-pause the agent):
 * - >3 consecutive publish/schedule failures (broken pipeline)
 * - >250 calls/hr (runaway agent loop)
 * - >25 identical calls in 5min (stuck in retry loop)
 *
 * Session call limit (blocks session, does NOT trip breaker):
 * - >200 calls per 4-hour session window
 *
 * When tripped: sets agent_paused=true, sends push/email + Discord alert.
 * Agent must be manually unpaused after investigation.
 */

import { logger } from "./logger.js";

// ---------------------------------------------------------------------------
// Redis key prefixes
// ---------------------------------------------------------------------------

const PREFIX = "agent-cb";
const HOURLY_KEY = (userId: string) => `${PREFIX}:hourly:${userId}`;
const FAIL_STREAK_KEY = (userId: string) => `${PREFIX}:fail-streak:${userId}`;
const DEDUP_KEY = (userId: string, hash: string) =>
	`${PREFIX}:dedup:${userId}:${hash}`;
const TRIPPED_KEY = (userId: string) => `${PREFIX}:tripped:${userId}`;

// ---------------------------------------------------------------------------
// Thresholds
// ---------------------------------------------------------------------------

const HOURLY_CALL_LIMIT = 250;
const HOURLY_WINDOW_SECONDS = 3600;

const CONSECUTIVE_FAIL_LIMIT = 3;
const FAIL_STREAK_TTL_SECONDS = 1800; // 30min — resets if no failures

const DEDUP_CALL_LIMIT = 25;
const DEDUP_WINDOW_SECONDS = 300; // 5 minutes

const SESSION_CALL_LIMIT = 200;
const SESSION_TTL_SECONDS = 14400; // 4 hours

const SESSION_KEY = (userId: string, sessionId: string) =>
	`${PREFIX}:session:${userId}:${sessionId}`;

const PUBLISH_TOOLS = new Set([
	"publish_post",
	"schedule_post",
	"bulk_schedule",
	"publish_threads_post",
	"publish_instagram_post",
	"schedule_threads_post",
	"schedule_instagram_post",
]);

// ---------------------------------------------------------------------------
// Trip reason type
// ---------------------------------------------------------------------------

export interface TripReason {
	condition: "hourly_limit" | "consecutive_failures" | "dedup_loop";
	detail: string;
	threshold: number;
	actual: number;
}

export interface CircuitBreakerStatus {
	tripped: boolean;
	reason?: TripReason | undefined;
	trippedAt?: string | undefined;
	counters: {
		hourlyCalls: number;
		hourlyLimit: number;
		consecutiveFailures: number;
		failLimit: number;
		sessionCalls?: number | undefined;
		sessionLimit?: number | undefined;
	};
}

// ---------------------------------------------------------------------------
// Core logic
// ---------------------------------------------------------------------------

/**
 * Record an agent tool call and check all trip conditions.
 * Returns null if OK, or a TripReason if the breaker should trip.
 *
 * Called from withAuth middleware on every API-key write request.
 */
export async function checkAndRecord(
	userId: string,
	toolName: string,
	paramsHash: string,
	success: boolean,
): Promise<TripReason | null> {
	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();

		// --- Check 1: Hourly call volume ---
		const hourlyKey = HOURLY_KEY(userId);
		const hourlyCalls = await redis.incr(hourlyKey);
		// Always refresh TTL to prevent orphaned keys if crash occurs between INCR and EXPIRE
		await redis.expire(hourlyKey, HOURLY_WINDOW_SECONDS);
		if (hourlyCalls > HOURLY_CALL_LIMIT) {
			return {
				condition: "hourly_limit",
				detail: `${hourlyCalls} calls in the last hour (limit: ${HOURLY_CALL_LIMIT})`,
				threshold: HOURLY_CALL_LIMIT,
				actual: hourlyCalls,
			};
		}

		// --- Check 2: Consecutive publish/schedule failures ---
		if (PUBLISH_TOOLS.has(toolName)) {
			const failKey = FAIL_STREAK_KEY(userId);
			if (success) {
				// Reset streak on success
				await redis.del(failKey);
			} else {
				const streak = await redis.incr(failKey);
				await redis.expire(failKey, FAIL_STREAK_TTL_SECONDS);
				if (streak > CONSECUTIVE_FAIL_LIMIT) {
					return {
						condition: "consecutive_failures",
						detail: `${streak} consecutive publish/schedule failures`,
						threshold: CONSECUTIVE_FAIL_LIMIT,
						actual: streak,
					};
				}
			}
		}

		// --- Check 3: Identical call dedup ---
		const dedupKey = DEDUP_KEY(userId, paramsHash);
		const dedupCount = await redis.incr(dedupKey);
		await redis.expire(dedupKey, DEDUP_WINDOW_SECONDS);
		if (dedupCount > DEDUP_CALL_LIMIT) {
			return {
				condition: "dedup_loop",
				detail: `${dedupCount} identical calls in ${DEDUP_WINDOW_SECONDS / 60} minutes (limit: ${DEDUP_CALL_LIMIT})`,
				threshold: DEDUP_CALL_LIMIT,
				actual: dedupCount,
			};
		}

		return null;
	} catch (err) {
		// Redis failure → fail open (don't block agent on infra issues)
		logger.warn("[CircuitBreaker] Redis check failed — failing open", {
			userId,
			error: String(err),
		});
		return null;
	}
}

/**
 * Record actual outcome of a tool call — call AFTER the handler runs.
 * checkAndRecord runs pre-handler (before we know success/failure) so
 * the consecutive-failure streak counter would never increment without
 * this follow-up. Idempotent: hourly + dedup are not bumped (they were
 * already counted by checkAndRecord).
 */
export async function recordOutcome(
	userId: string,
	toolName: string,
	success: boolean,
): Promise<TripReason | null> {
	if (!PUBLISH_TOOLS.has(toolName)) return null;
	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();
		const failKey = FAIL_STREAK_KEY(userId);

		if (success) {
			await redis.del(failKey);
			return null;
		}

		const streak = await redis.incr(failKey);
		await redis.expire(failKey, FAIL_STREAK_TTL_SECONDS);
		if (streak > CONSECUTIVE_FAIL_LIMIT) {
			return {
				condition: "consecutive_failures",
				detail: `${streak} consecutive publish/schedule failures`,
				threshold: CONSECUTIVE_FAIL_LIMIT,
				actual: streak,
			};
		}
		return null;
	} catch (err) {
		logger.warn("[CircuitBreaker] Redis recordOutcome failed", {
			userId,
			toolName,
			error: String(err),
		});
		return null;
	}
}

/**
 * Trip the breaker: pause agent + notify user + Discord alert.
 */
export async function trip(userId: string, reason: TripReason): Promise<void> {
	try {
		// 1. Set agent_paused = true
		const { getSupabaseAny } = await import("./supabase.js");
		await getSupabaseAny()
			.from("profiles")
			.update({ agent_paused: true })
			.eq("id", userId);

		// 2. Record trip in Redis (for status endpoint)
		try {
			const { getRedis } = await import("./redis.js");
			const redis = getRedis();
			await redis.set(
				TRIPPED_KEY(userId),
				JSON.stringify({
					reason,
					trippedAt: new Date().toISOString(),
				}),
				{ ex: 86400 }, // 24h TTL
			);
		} catch {
			// Non-fatal — the DB pause is what matters
		}

		// 3. Send user notification (push + email)
		try {
			const { createNotification } = await import("./createNotification.js");
			await createNotification({
				userId,
				type: "agent_circuit_breaker",
				title: "Agent auto-paused",
				message: `Circuit breaker tripped: ${reason.detail}. Review agent activity and unpause when ready.`,
				data: { reason },
			});
		} catch (err) {
			logger.warn("[CircuitBreaker] Notification failed", {
				error: String(err),
			});
		}

		// 4. Discord alert (fire-and-forget)
		try {
			const { alert, AlertLevel } = await import("./alerting.js");
			await alert(AlertLevel.CRITICAL, "Agent circuit breaker tripped", {
				condition: reason.condition,
				detail: reason.detail,
				threshold: String(reason.threshold),
				actual: String(reason.actual),
			});
		} catch {
			// Non-fatal
		}

		logger.error("[CircuitBreaker] TRIPPED — agent paused", {
			userId,
			condition: reason.condition,
			detail: reason.detail,
		});
	} catch (err) {
		logger.error("[CircuitBreaker] Failed to trip breaker", {
			userId,
			error: String(err),
		});
	}
}

/**
 * Get current circuit breaker status for a user.
 * Pass sessionId to include session call counter in the response.
 */
export async function getStatus(
	userId: string,
	sessionId?: string,
): Promise<CircuitBreakerStatus> {
	const result: CircuitBreakerStatus = {
		tripped: false,
		counters: {
			hourlyCalls: 0,
			hourlyLimit: HOURLY_CALL_LIMIT,
			consecutiveFailures: 0,
			failLimit: CONSECUTIVE_FAIL_LIMIT,
		},
	};

	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();

		const [hourlyResult, failResult, tripResult] = await Promise.allSettled([
			redis.get(HOURLY_KEY(userId)),
			redis.get(FAIL_STREAK_KEY(userId)),
			redis.get(TRIPPED_KEY(userId)),
		]);
		const hourlyCalls =
			hourlyResult.status === "fulfilled" ? hourlyResult.value : null;
		const failStreak =
			failResult.status === "fulfilled" ? failResult.value : null;
		const tripData =
			tripResult.status === "fulfilled" ? tripResult.value : null;

		result.counters.hourlyCalls = Number(hourlyCalls) || 0;
		result.counters.consecutiveFailures = Number(failStreak) || 0;

		if (sessionId) {
			try {
				const sessionCalls = await redis.get(SESSION_KEY(userId, sessionId));
				result.counters.sessionCalls = Number(sessionCalls) || 0;
				result.counters.sessionLimit = SESSION_CALL_LIMIT;
			} catch {
				// Non-fatal
			}
		}

		if (tripData) {
			const parsed =
				typeof tripData === "string" ? JSON.parse(tripData) : tripData;
			result.tripped = true;
			result.reason = parsed.reason;
			result.trippedAt = parsed.trippedAt;
		}
	} catch (err) {
		logger.warn("[CircuitBreaker] Status check failed", {
			userId,
			error: String(err),
		});
	}

	return result;
}

/**
 * Reset the circuit breaker (clear trip state + counters).
 * Called when user unpauses agent.
 */
export async function reset(userId: string): Promise<void> {
	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();

		const results = await Promise.allSettled([
			redis.del(TRIPPED_KEY(userId)),
			redis.del(HOURLY_KEY(userId)),
			redis.del(FAIL_STREAK_KEY(userId)),
		]);

		const failures = results.filter((r) => r.status === "rejected");
		if (failures.length > 0) {
			logger.warn("[CircuitBreaker] Partial reset failure", {
				userId,
				failedCount: failures.length,
				errors: failures.map((r) =>
					String((r as PromiseRejectedResult).reason),
				),
			});
		}

		logger.info("[CircuitBreaker] Reset", { userId });
	} catch (err) {
		logger.warn("[CircuitBreaker] Reset failed", {
			userId,
			error: String(err),
		});
	}
}

/**
 * Check per-session call limit. Returns 429 info but does NOT trip the breaker.
 * Tracked via Redis counter with 4-hour TTL per session.
 */
export async function checkSessionCallLimit(
	userId: string,
	sessionId: string,
): Promise<{ allowed: boolean; count: number; limit: number }> {
	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();
		const key = SESSION_KEY(userId, sessionId);
		const count = await redis.incr(key);
		if (count === 1) {
			await redis.expire(key, SESSION_TTL_SECONDS);
		}
		return {
			allowed: count <= SESSION_CALL_LIMIT,
			count,
			limit: SESSION_CALL_LIMIT,
		};
	} catch {
		// Fail open — Redis issues shouldn't block agent
		return { allowed: true, count: 0, limit: SESSION_CALL_LIMIT };
	}
}

/**
 * Create a stable hash of tool name + params for dedup detection.
 * Uses a simple string hash — not cryptographic, just consistent.
 */
export function computeParamsHash(
	toolName: string,
	path: string,
	method: string,
): string {
	const input = `${toolName}:${method}:${path}`;
	let hash = 0;
	for (let i = 0; i < input.length; i++) {
		const char = input.charCodeAt(i);
		hash = (hash << 5) - hash + char;
		hash |= 0; // Convert to 32bit integer
	}
	return hash.toString(36);
}
