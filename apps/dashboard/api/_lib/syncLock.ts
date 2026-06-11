/**
 * Per-account sync lock using Upstash Redis.
 *
 * Prevents two concurrent QStash-dispatched syncs for the same account
 * from racing and overwriting each other's metrics (last-write-wins).
 *
 * Uses SET NX EX (atomic acquire) + DEL (release in finally).
 */

import { logger } from "./logger.js";

const LOCK_PREFIX = "sync-lock:";
const DEFAULT_TTL_SECONDS = 55; // Under Vercel's 60s function timeout

interface SyncLockResult {
	acquired: boolean;
	release: () => Promise<void>;
}

export async function acquireSyncLock(
	accountId: string,
	ttlSeconds = DEFAULT_TTL_SECONDS,
): Promise<SyncLockResult> {
	const noop = { acquired: false, release: async () => {} };

	try {
		const { getRedis } = await import("./redis.js");
		const redis = getRedis();
		const key = `${LOCK_PREFIX}${accountId}`;

		// SET key value NX EX ttl — atomic acquire
		const result = await redis.set(key, Date.now().toString(), {
			nx: true,
			ex: ttlSeconds,
		});

		if (!result) {
			logger.info("Sync lock skipped — another sync in progress", {
				accountId,
			});
			return noop;
		}

		return {
			acquired: true,
			release: async () => {
				try {
					await redis.del(key);
				} catch {
					// Lock will auto-expire via TTL — safe to ignore
				}
			},
		};
	} catch (error) {
		// Fail closed: if Redis is down, block sync to prevent data races.
		// Syncs resume within ~2 min when Redis recovers (lock TTL auto-expires).
		logger.warn("Sync lock Redis error — blocking sync (fail-closed)", {
			accountId,
			error: error instanceof Error ? error.message : String(error),
		});
		return { acquired: false, release: async () => {} };
	}
}
