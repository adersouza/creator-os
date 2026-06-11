/**
 * Per-account publish lock using Upstash Redis.
 *
 * Prevents two concurrent QStash-dispatched publishes from posting to the
 * same account within the burst guard window. Uses SET NX EX (atomic acquire).
 *
 * The lock key is held for 30 minutes (matching the burst guard), so even if
 * the publishing function crashes without releasing, the lock auto-expires
 * and the next cycle can publish.
 *
 * Unlike the DB-based burst guard (which has a TOCTOU race when two QStash
 * jobs fire simultaneously), Redis SET NX is truly atomic — only one caller
 * wins the lock.
 */

import { logger } from "./logger.js";

const LOCK_PREFIX = "publish-lock:";
// 5 minutes — just long enough to prevent TOCTOU double-publish from concurrent
// QStash jobs. min_interval_minutes in DB handles the real spacing enforcement.
// Previous 30-min TTL caused "all accounts busy" gridlock in groups with ≤10 accounts
// when QStash fired multiple items within the lock window.
const DEFAULT_TTL_SECONDS = 5 * 60;

interface PublishLockResult {
	acquired: boolean;
	release: () => Promise<void>;
}

async function acquireDbFallbackLock(
	accountId: string,
	ttlSeconds: number,
): Promise<PublishLockResult> {
	const { getSupabaseAny } = await import("./supabase.js");
	const db = getSupabaseAny();
	const ownerToken = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
	const expiresAt = new Date(Date.now() + ttlSeconds * 1000).toISOString();

	await db
		.from("publish_locks")
		.delete()
		.eq("account_id", accountId)
		.lte("expires_at", new Date().toISOString());

	const { error } = await db.from("publish_locks").insert({
		account_id: accountId,
		owner_token: ownerToken,
		expires_at: expiresAt,
	});

	if (error) {
		const { recordInfraEvent } = await import("./infraTelemetry.js");
		await recordInfraEvent("publish-lock-db-busy", { accountId });
		logger.info("Publish lock DB fallback busy, skipping", { accountId });
		return { acquired: false, release: async () => {} };
	}

	const { recordInfraEvent } = await import("./infraTelemetry.js");
	await recordInfraEvent("publish-lock-db-fallback", {
		accountId,
		expiresAt,
	});

	return {
		acquired: true,
		release: async () => {
			try {
				await db
					.from("publish_locks")
					.delete()
					.eq("account_id", accountId)
					.eq("owner_token", ownerToken);
			} catch {
				// TTL cleanup on the next acquire is sufficient fallback behavior.
			}
		},
	};
}

export async function acquirePublishLock(
	accountId: string,
	ttlSeconds = DEFAULT_TTL_SECONDS,
): Promise<PublishLockResult> {
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
			logger.info("Publish lock: account recently published, skipping", {
				accountId,
			});
			return noop;
		}

		return {
			acquired: true,
			release: async () => {
				// NOTE: We intentionally do NOT release the lock after publishing.
				// The lock acts as a 30-min cooldown — it auto-expires via TTL.
				// This method exists for symmetry with syncLock and for future use
				// if we ever need early release (e.g., publish failure that should
				// allow immediate retry).
				try {
					await redis.del(key);
				} catch {
					// Lock will auto-expire via TTL — safe to ignore
				}
			},
		};
	} catch (error) {
		const { recordInfraEvent } = await import("./infraTelemetry.js");
		await recordInfraEvent("publish-lock-redis-error", {
			accountId,
			error: error instanceof Error ? error.message : String(error),
		});
		logger.warn("Publish lock Redis error — using DB fallback lock", {
			accountId,
			error: error instanceof Error ? error.message : String(error),
		});
		return acquireDbFallbackLock(accountId, ttlSeconds);
	}
}
