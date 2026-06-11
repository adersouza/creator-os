// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Analytics Dispatch Logic
 *
 * Cohort-based stale account detection + QStash fan-out.
 * Extracted from analytics-dispatcher cron for use by sync-orchestrator.
 */

import { logger } from "./logger.js";
import { getQStashClient } from "./qstash.js";
import { getRedis } from "./redis.js";
import { getSupabase } from "./supabase.js";

interface ThreadsAccountRow {
	id: string;
	user_id: string;
	username: string | null;
	threads_user_id: string;
}

interface IgAccountRow {
	id: string;
	user_id: string;
	username: string | null;
	instagram_user_id: string;
}

const db = () => getSupabase();

// Hard cap on QStash messages per dispatch cycle — safety net against runaway loops
const MAX_QSTASH_MESSAGES_PER_CYCLE = parseInt(
	process.env.MAX_QSTASH_MESSAGES_PER_CYCLE || "800",
	10,
);

// Cohort-based stale thresholds (ms)
const COHORT_THRESHOLDS: Record<string, number> = {
	hot: 30 * 60 * 1000, // 30 min
	warm: 4 * 60 * 60 * 1000, // 4 hours
	cold: 12 * 60 * 60 * 1000, // 12 hours
	dormant: 24 * 60 * 60 * 1000, // 24 hours
};

export async function dispatchAnalyticsSync(
	options: { fullSync?: boolean | undefined } = {},
): Promise<number> {
	const qstash = getQStashClient();
	const redis = getRedis();
	const baseUrl = process.env.APP_URL || `https://${process.env.VERCEL_URL}`;

	// Defer dispatch if analytics-pipeline is currently running a full inline refresh.
	// analytics-pipeline.ts sets this flag at start and clears it on completion;
	// the 310s TTL is the safety net if the pipeline crashes mid-run.
	// Skip this check when called with fullSync (i.e. from analytics-pipeline itself).
	if (!options.fullSync) {
		const pipelineActive = await redis.get("analytics-pipeline:active");
		if (pipelineActive) {
			logger.info(
				"Dispatch deferred — analytics-pipeline is currently running",
			);
			return 0;
		}
	}
	const isFullSync = options.fullSync ?? false;
	const dateKey = new Date().toISOString().split("T")[0]!;

	// Reclassify cohorts every 6 hours
	const cohortKey = "cohort-classify:last";
	const lastClassify = await redis.get(cohortKey);
	if (!lastClassify || Date.now() - Number(lastClassify) > 6 * 3600 * 1000) {
		try {
			await db().rpc("classify_account_cohorts");
			await redis.set(cohortKey, String(Date.now()), { ex: 21600 });
			logger.info("Reclassified account cohorts");
		} catch (err) {
			logger.warn("Cohort classification failed (non-fatal)", {
				error: String(err),
			});
		}
	}

	let dispatched = 0;
	let failedCount = 0;

	// Query each cohort with its appropriate stale threshold
	for (const [cohort, thresholdMs] of Object.entries(COHORT_THRESHOLDS)) {
		if (dispatched >= MAX_QSTASH_MESSAGES_PER_CYCLE) break;
		const staleThreshold = isFullSync
			? undefined
			: new Date(Date.now() - thresholdMs).toISOString();
		const syncType = isFullSync
			? "full"
			: cohort === "hot"
				? "recent"
				: "metrics";
		// Dormant/cold need higher limits so the loop can skip Redis-deduped accounts
		// and still reach un-dispatched accounts further down the staleness list.
		const limit = isFullSync
			? 500
			: cohort === "hot"
				? 100
				: cohort === "warm"
					? 100
					: cohort === "cold"
						? 150
						: 250; // dormant — covers 200+ IG accounts

		let threadsQuery = db()
			.from("accounts")
			.select("id, user_id, username, threads_user_id")
			.not("threads_access_token_encrypted", "is", null)
			.not("threads_user_id", "is", null)
			.eq("is_active", true)
			.eq("sync_cohort", cohort)
			.order("last_synced_at", { ascending: true, nullsFirst: true })
			.limit(limit);

		if (staleThreshold) {
			threadsQuery = threadsQuery.or(
				`last_synced_at.is.null,last_synced_at.lt.${staleThreshold}`,
			);
		}

		const { data: threadsAccounts, error: threadsError } = await threadsQuery;

		if (threadsError) {
			logger.error("Failed to query Threads accounts", {
				cohort,
				error: threadsError.message ?? JSON.stringify(threadsError),
				code: (threadsError as { code?: string | undefined }).code,
				details: (threadsError as { details?: string | undefined }).details,
				hint: (threadsError as { hint?: string | undefined }).hint,
			});
			throw new Error(
				`DB query failed for Threads accounts (cohort=${cohort}): ${threadsError.message ?? JSON.stringify(threadsError)}`,
			);
		}

		let igQuery = db()
			.from("instagram_accounts")
			.select("id, user_id, username, instagram_user_id")
			.not("instagram_access_token_encrypted", "is", null)
			.not("instagram_user_id", "is", null)
			.eq("is_active", true)
			.eq("sync_cohort", cohort)
			.order("last_synced_at", { ascending: true, nullsFirst: true })
			.limit(limit);

		if (staleThreshold) {
			igQuery = igQuery.or(
				`last_synced_at.is.null,last_synced_at.lt.${staleThreshold}`,
			);
		}

		const { data: igAccounts, error: igError } = await igQuery;

		if (igError) {
			logger.error("Failed to query Instagram accounts", {
				cohort,
				error: igError.message ?? JSON.stringify(igError),
				code: (igError as { code?: string | undefined }).code,
				details: (igError as { details?: string | undefined }).details,
				hint: (igError as { hint?: string | undefined }).hint,
			});
			throw new Error(
				`DB query failed for Instagram accounts (cohort=${cohort}): ${igError.message ?? JSON.stringify(igError)}`,
			);
		}

		const cohortAccounts: Array<{
			id: string;
			user_id: string;
			username: string | null;
			endpoint: string;
			platform_user_id?: string | undefined;
		}> = [
			...(threadsAccounts || []).map((a: ThreadsAccountRow) => ({
				...a,
				endpoint: "threads-account",
				platform_user_id: a.threads_user_id,
			})),
			...(igAccounts || []).map((a: IgAccountRow) => ({
				...a,
				endpoint: "ig-account",
				platform_user_id: a.instagram_user_id,
			})),
		];

		logger.info("Dispatching cohort", {
			cohort,
			syncType,
			threadsCount: threadsAccounts?.length || 0,
			igCount: igAccounts?.length || 0,
		});

		// Publish QStash messages with staggered delivery
		for (let i = 0; i < cohortAccounts.length; i++) {
			if (dispatched >= MAX_QSTASH_MESSAGES_PER_CYCLE) {
				logger.warn("QStash dispatch cap reached", {
					dispatched,
					cap: MAX_QSTASH_MESSAGES_PER_CYCLE,
				});
				break;
			}
			const acct = cohortAccounts[i];

			// Redis dedup: skip if already dispatched this cycle
			const dedupKey = `analytics-sync:${acct!.id}:${syncType}`;
			let existing: string | null = null;
			try {
				existing = (await redis.get(dedupKey)) as string | null;
			} catch (redisErr) {
				logger.warn("Redis dedup GET failed — dispatching without dedup", {
					accountId: acct!.id,
					error: String(redisErr),
				});
			}
			if (existing) continue;

			// Delta sync: skip if recently updated via webhook
			if (acct!.platform_user_id) {
				try {
					const webhookKey =
						acct!.endpoint === "ig-account"
							? `webhook-active:ig:${acct!.platform_user_id}`
							: `webhook-active:${acct!.platform_user_id}`;
					const webhookActive = await redis.get(webhookKey);
					if (webhookActive) {
						logger.debug("Skipping dispatch (webhook-active)", {
							accountId: acct!.id,
							endpoint: acct!.endpoint,
						});
						continue;
					}
				} catch {
					// Non-blocking — proceed with dispatch if Redis check fails
				}
			}

			try {
				const dedupBaseMs = isFullSync ? 24 * 60 * 60 * 1000 : thresholdMs;
				const dedupTtl = Math.max(Math.floor(dedupBaseMs / 1000), 1800);
				const { RETRIES } = await import("./qstashDefaults.js");
				await qstash.publishJSON({
					url: `${baseUrl}/api/sync/${acct!.endpoint}`,
					body: {
						accountId: acct!.id,
						userId: acct!.user_id,
						syncType,
						...(isFullSync ? { force: true } : {}),
					},
					retries: RETRIES.IMPORTANT,
					delay: dispatched * 2,
					deduplicationId: `${acct!.id}-${dateKey}-${syncType}`,
				});

				try {
					await redis.set(dedupKey, "1", { ex: dedupTtl });
				} catch (redisErr) {
					logger.warn(
						"Redis dedup SET failed — dispatch succeeded without dedup marker",
						{
							accountId: acct!.id,
							error: String(redisErr),
						},
					);
				}
				dispatched++;
			} catch (err) {
				failedCount++;
				logger.error("Failed to dispatch QStash message", {
					accountId: acct!.id,
					error: String(err),
				});
			}
		}
	}

	// Fallback: also dispatch accounts without a cohort (newly added)
	const fallbackWindowMs = 4 * 60 * 60 * 1000;
	const fallbackThreshold = isFullSync
		? undefined
		: new Date(Date.now() - fallbackWindowMs).toISOString();
	const fallbackLimit = isFullSync ? 200 : 50;

	let unclassifiedThreadsQuery = db()
		.from("accounts")
		.select("id, user_id, username, threads_user_id")
		.not("threads_access_token_encrypted", "is", null)
		.not("threads_user_id", "is", null)
		.eq("is_active", true)
		.is("sync_cohort", null)
		.order("last_synced_at", { ascending: true, nullsFirst: true })
		.limit(fallbackLimit);

	if (fallbackThreshold) {
		unclassifiedThreadsQuery = unclassifiedThreadsQuery.or(
			`last_synced_at.is.null,last_synced_at.lt.${fallbackThreshold}`,
		);
	}

	const { data: unclassifiedThreads } = await unclassifiedThreadsQuery;

	let unclassifiedIgQuery = db()
		.from("instagram_accounts")
		.select("id, user_id, username, instagram_user_id")
		.not("instagram_access_token_encrypted", "is", null)
		.not("instagram_user_id", "is", null)
		.eq("is_active", true)
		.is("sync_cohort", null)
		.order("last_synced_at", { ascending: true, nullsFirst: true })
		.limit(fallbackLimit);

	if (fallbackThreshold) {
		unclassifiedIgQuery = unclassifiedIgQuery.or(
			`last_synced_at.is.null,last_synced_at.lt.${fallbackThreshold}`,
		);
	}

	const { data: unclassifiedIG } = await unclassifiedIgQuery;

	const unclassified: Array<{
		id: string;
		user_id: string;
		username: string | null;
		endpoint: string;
		platform_user_id?: string | undefined;
	}> = [
		...(unclassifiedThreads || []).map((a: ThreadsAccountRow) => ({
			...a,
			endpoint: "threads-account",
			platform_user_id: a.threads_user_id,
		})),
		...(unclassifiedIG || []).map((a: IgAccountRow) => ({
			...a,
			endpoint: "ig-account",
			platform_user_id: a.instagram_user_id,
		})),
	];

	for (const acct of unclassified) {
		if (dispatched >= MAX_QSTASH_MESSAGES_PER_CYCLE) {
			logger.warn("QStash dispatch cap reached in fallback loop", {
				dispatched,
				cap: MAX_QSTASH_MESSAGES_PER_CYCLE,
			});
			break;
		}
		const dedupKey = `analytics-sync:${acct.id}:metrics`;
		let existing: string | null = null;
		try {
			existing = (await redis.get(dedupKey)) as string | null;
		} catch (redisErr) {
			logger.warn("Redis dedup GET failed — dispatching without dedup", {
				accountId: acct.id,
				error: String(redisErr),
			});
		}
		if (existing) continue;

		// Delta sync: skip if recently updated via webhook
		if (acct.platform_user_id) {
			try {
				const webhookKey =
					acct.endpoint === "ig-account"
						? `webhook-active:ig:${acct.platform_user_id}`
						: `webhook-active:${acct.platform_user_id}`;
				const webhookActive = await redis.get(webhookKey);
				if (webhookActive) {
					logger.debug("Skipping unclassified dispatch (webhook-active)", {
						accountId: acct.id,
					});
					continue;
				}
			} catch {
				// Non-blocking
			}
		}

		try {
			const { RETRIES: RETRIES2 } = await import("./qstashDefaults.js");
			await qstash.publishJSON({
				url: `${baseUrl}/api/sync/${acct.endpoint}`,
				body: { accountId: acct.id, userId: acct.user_id, syncType: "metrics" },
				retries: RETRIES2.IMPORTANT,
				delay: dispatched * 2,
				deduplicationId: `${acct.id}-${dateKey}-metrics`,
			});
			try {
				await redis.set(dedupKey, "1", { ex: 14400 });
			} catch (redisErr) {
				logger.warn(
					"Redis dedup SET failed — dispatch succeeded without dedup marker",
					{
						accountId: acct.id,
						error: String(redisErr),
					},
				);
			}
			dispatched++;
		} catch (err) {
			failedCount++;
			logger.error("Failed to dispatch unclassified account", {
				accountId: acct.id,
				error: String(err),
			});
		}
	}

	logger.info("Analytics dispatch complete", { dispatched, failedCount });

	// Alert if >20% of dispatch attempts failed
	const totalAttempted = dispatched + failedCount;
	if (totalAttempted > 0 && failedCount > totalAttempted * 0.2) {
		try {
			const { alertCronFailure } = await import("./alerting.js");
			alertCronFailure(
				"qstash-dispatch",
				`${failedCount}/${totalAttempted} messages failed (${Math.round((failedCount / totalAttempted) * 100)}%)`,
			);
		} catch {
			// Best-effort alerting
		}
	}

	return dispatched;
}
