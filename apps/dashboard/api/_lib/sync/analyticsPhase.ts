// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Analytics Sync Phase — Profile + followers sync and stale job cleanup.
 * Extracted from sync-orchestrator.ts.
 *
 * syncAccount() — lightweight sync (profile + followers_count)
 * syncIgAccount() — Instagram account sync via refreshInstagramAccountAnalytics()
 * cleanupStaleAnalyticsJobs() — recovers stuck DB rows
 * _processAnalyticsSyncQueue() — legacy queue processing (kept for reference)
 */

import type { PostgrestError } from "@supabase/supabase-js";
import { logger, serializeError } from "../logger.js";

import {
	type AccountData,
	type AccountUpdate,
	CONCURRENCY_LIMIT,
	DELAY_BETWEEN_ACCOUNTS,
	fetchWithTimeout,
	getCachedAccount,
	getJob,
	getOrchestratorStartTime,
	getQueueLen,
	hasTimeBudget,
	IG_DIRECT_LIMIT,
	type IgAccountRow,
	invalidateAccountCache,
	popFromQueue,
	queueSyncJob,
	type StaleJobRow,
	type StaleQueuedJobRow,
	SYNC_JOB_PREFIX,
	SYNC_QUEUE_KEY,
	type SyncJob,
	type SyncResult,
	setCachedAccount,
	type ThreadsInsightMetric,
	updateJob,
	updateSyncJobsTable,
} from "./shared.js";

// ============================================================================
// PHASE 1: Analytics Sync - Sync Single Account (Profile + Followers Only)
// NOTE: This is a lightweight sync (profile + followers_count).
// Post-level metrics are handled by Phase 0's QStash fan-out
// which dispatches to refreshThreadsAccountAnalytics() per account.
// ============================================================================

export async function syncAccount(
	accountId: string,
	userId: string,
	/** Pre-fetched prior follower count (avoids N+1 query when called in batch) */
	priorFollowerCount?: number | null,
): Promise<SyncResult> {
	const { decrypt } = await import("../encryption.js");
	const { getSupabase } = await import("../supabase.js");

	try {
		let account = await getCachedAccount(accountId);

		if (!account) {
			const { data, error: accountError } = await getSupabase()
				.from("accounts")
				.select(
					"id, user_id, username, threads_user_id, threads_access_token_encrypted, status, followers_count, last_synced_at, is_active",
				)
				.eq("id", accountId)
				.eq("user_id", userId)
				.maybeSingle();

			account = data as AccountData | null;
			if (accountError || !account) {
				return { accountId, success: false, error: "Account not found" };
			}
			await setCachedAccount(account);
		} else if (account.user_id !== userId) {
			return { accountId, success: false, error: "Account not found" };
		}

		if (!account.threads_access_token_encrypted || !account.threads_user_id) {
			return {
				accountId,
				username: account.username,
				success: false,
				error: "No OAuth credentials",
			};
		}

		// Skip inactive accounts (waste reduction — no API calls for deactivated accounts)
		if (account.status === "suspended" || account.is_active === false) {
			logger.info("Skipping inactive Threads account", {
				username: account.username,
				accountId,
				status: account.status,
			});
			return {
				accountId,
				username: account.username,
				success: true,
				skipped: true,
			};
		}

		const PROFILE_FRESHNESS_MS =
			parseInt(process.env.PROFILE_FRESHNESS_MINUTES ?? "360", 10) * 60 * 1000;
		if (account.last_synced_at) {
			const lastSynced = new Date(account.last_synced_at).getTime();
			if (lastSynced > Date.now() - PROFILE_FRESHNESS_MS) {
				logger.info("Skipping account (fresh)", {
					username: account.username,
					lastSynced: account.last_synced_at,
				});
				return {
					accountId,
					username: account.username,
					success: true,
					skipped: true,
				};
			}
		}

		// Delta sync: skip if recently updated via webhook and last_synced_at is within 15 min
		if (account.threads_user_id && account.last_synced_at) {
			try {
				const { getRedis } = await import("../redis.js");
				const webhookActive = await getRedis().get(
					`webhook-active:${account.threads_user_id}`,
				);
				if (webhookActive) {
					const lastSynced = new Date(account.last_synced_at).getTime();
					if (lastSynced > Date.now() - 15 * 60 * 1000) {
						logger.info("Skipping account (webhook-active, recently synced)", {
							username: account.username,
							threadsUserId: account.threads_user_id,
							lastSynced: account.last_synced_at,
						});
						return {
							accountId,
							username: account.username,
							success: true,
							skipped: true,
						};
					}
				}
			} catch (redisErr) {
				logger.debug("Redis webhook-active check failed (non-blocking)", {
					error: serializeError(redisErr),
				});
			}
		}

		let token: string;
		try {
			token = decrypt(account.threads_access_token_encrypted);
		} catch (err) {
			logger.warn("Token decryption failed for sync", {
				accountId,
				username: account.username,
				error: String(err),
			});
			return {
				accountId,
				username: account.username,
				success: false,
				error: "Token decryption failed",
			};
		}

		// Fetch profile
		const profileUrl = `https://graph.threads.net/v1.0/${account.threads_user_id}?fields=id,username,threads_profile_picture_url,threads_biography`;
		const profileResponse = await fetchWithTimeout(
			profileUrl,
			{ headers: { Authorization: `Bearer ${token}` } },
			10000,
			`account:${account.username || accountId}`,
		);
		const profileData = await profileResponse.json();

		if (!profileResponse.ok || profileData.error) {
			const errorMessage = profileData.error?.message || "Unknown error";
			const errorCode = profileData.error?.code;

			// OAuthException (code 190): token expired or invalidated — user must reconnect.
			// Must NOT be classified as "suspended" (content policy ban); they require different
			// UI affordances and the token-refresh cron filters on needs_reauth, not status.
			if (errorCode === 190) {
				await getSupabase()
					.from("accounts")
					.update({
						status: "needs_reauth",
						needs_reauth: true,
						is_active: false,
						updated_at: new Date().toISOString(),
					})
					.eq("id", accountId);
				await invalidateAccountCache(accountId);
				logger.warn("Token expired during sync — account flagged for re-auth", {
					accountId,
					username: account.username,
				});
				return {
					accountId,
					username: account.username,
					success: false,
					needsReauth: true,
					error: errorMessage,
				};
			}

			// Genuine account suspension: content policy violation or platform ban
			const isSuspended =
				errorCode === 100 ||
				errorCode === 10 ||
				errorMessage.toLowerCase().includes("suspended");

			if (isSuspended) {
				await getSupabase()
					.from("accounts")
					.update({
						status: "suspended",
						is_active: false,
						updated_at: new Date().toISOString(),
					})
					.eq("id", accountId);
				await invalidateAccountCache(accountId);
				return {
					accountId,
					username: account.username,
					success: false,
					suspended: true,
					error: errorMessage,
				};
			}
			return {
				accountId,
				username: account.username,
				success: false,
				error: `Profile fetch failed: ${errorMessage}`,
			};
		}

		// Fetch followers count
		let followersCount: number | null = null;
		try {
			const insightsUrl = `https://graph.threads.net/v1.0/${account.threads_user_id}/threads_insights?metric=followers_count`;
			const insightsResponse = await fetchWithTimeout(
				insightsUrl,
				{ headers: { Authorization: `Bearer ${token}` } },
				10000,
				`insights:${account.username || accountId}`,
			);
			const insightsData = await insightsResponse.json();

			if (insightsData.data) {
				const followerMetric = insightsData.data.find(
					(m: ThreadsInsightMetric) => m.name === "followers_count",
				);
				if (followerMetric) {
					const value =
						followerMetric.total_value?.value ??
						followerMetric.values?.[followerMetric.values.length - 1]?.value;
					if (typeof value === "number" && value > 0) {
						followersCount = value;
					}
				}
			}
		} catch (err) {
			logger.warn("Failed to fetch follower metrics", {
				accountId,
				error: String(err),
			});
		}

		// Update account
		const wasReactivated = account.status === "suspended";
		const updateData: AccountUpdate = {
			username: profileData.username,
			avatar_url: profileData.threads_profile_picture_url || null,
			bio: profileData.threads_biography || "",
			last_synced_at: new Date().toISOString(),
			updated_at: new Date().toISOString(),
			status: "active",
			is_active: true,
		};
		if (followersCount !== null) {
			updateData.followers_count = followersCount;
		}

		await getSupabase().from("accounts").update(updateData).eq("id", accountId);
		await invalidateAccountCache(accountId);

		// Store daily analytics
		const todayKey = new Date().toISOString().split("T")[0]!;
		if (followersCount !== null) {
			let followerGrowth = 0;
			try {
				// Use pre-fetched value if available (batch mode), else query individually
				let prevFollowers: number | undefined;
				if (priorFollowerCount !== undefined && priorFollowerCount !== null) {
					prevFollowers = priorFollowerCount;
				} else {
					const { data: latestData } = await getSupabase()
						.from("account_analytics")
						.select("followers_count")
						.eq("account_id", accountId)
						.lt("date", todayKey)
						.order("date", { ascending: false })
						.limit(1)
						.maybeSingle();
					prevFollowers =
						(latestData as { followers_count?: number | undefined } | null)
							?.followers_count ?? undefined;
				}
				if (prevFollowers) {
					followerGrowth = followersCount - prevFollowers;
				}
			} catch (err) {
				logger.warn("Failed to compute follower growth delta", {
					accountId,
					error: String(err),
				});
			}

			// Check-then-update: if a row already exists for today, only update follower
			// columns — don't clobber metrics (views, likes, etc.) written by analyticsSync
			const { data: existingAnalyticsRow } = await getSupabase()
				.from("account_analytics")
				.select("account_id")
				.eq("account_id", accountId)
				.eq("date", todayKey!)
				.maybeSingle();

			if (existingAnalyticsRow) {
				await getSupabase()
					.from("account_analytics")
					.update({
						followers_count: followersCount,
						follower_growth: followerGrowth,
					})
					.eq("account_id", accountId)
					.eq("date", todayKey!);
			} else {
				await getSupabase().from("account_analytics").upsert!(
					{
						account_id: accountId,
						date: todayKey,
						followers_count: followersCount,
						follower_growth: followerGrowth,
					},
					{ onConflict: "account_id,date" },
				);
			}
		}

		// Invalidate dashboard cache so follower count update is visible immediately
		const { invalidateDashboard } = await import("../dashboardCache.js");
		invalidateDashboard(accountId).catch(() => {});

		return {
			accountId,
			username: account.username,
			success: true,
			reactivated: wasReactivated,
		};
	} catch (error: unknown) {
		return {
			accountId,
			success: false,
			error: serializeError(error),
		};
	}
}

export async function syncIgAccount(
	igAccountId: string,
	userId: string,
): Promise<SyncResult> {
	const { getSupabase } = await import("../supabase.js");
	const { refreshInstagramAccountAnalytics } = await import(
		"../analyticsSync.js"
	);

	try {
		const { data: account, error } = (await getSupabase()
			.from("instagram_accounts")
			.select(
				"id, user_id, username, instagram_user_id, instagram_access_token_encrypted, login_type, follower_count, last_milestone_celebrated, last_synced_at, is_active",
			)
			.eq("id", igAccountId)
			.eq("user_id", userId)
			.maybeSingle()) as {
			data: IgAccountRow | null;
			error: PostgrestError | null;
		};

		if (error || !account) {
			return {
				accountId: igAccountId,
				success: false,
				error: "Instagram account not found",
			};
		}

		if (
			!account.instagram_access_token_encrypted ||
			!account.instagram_user_id
		) {
			return {
				accountId: igAccountId,
				username: account.username,
				success: false,
				error: "No OAuth credentials",
			};
		}

		// Skip inactive IG accounts (waste reduction — Phase 0 dispatch already filters these)
		if (account.is_active === false) {
			logger.debug("Skipping inactive IG account", {
				username: account.username,
				igAccountId,
			});
			return {
				accountId: igAccountId,
				username: account.username,
				success: true,
				skipped: true,
			};
		}

		// Skip if recently synced (within 2 hours) — QStash path already handles these
		if (account.last_synced_at) {
			const lastSynced = new Date(account.last_synced_at).getTime();
			const twoHoursAgo = Date.now() - 2 * 60 * 60 * 1000;
			if (lastSynced > twoHoursAgo) {
				logger.debug("Skipping IG account (recently synced by QStash)", {
					username: account.username,
					lastSynced: account.last_synced_at,
				});
				return {
					accountId: igAccountId,
					username: account.username,
					success: true,
					skipped: true,
				};
			}
		}

		// Delta sync: skip if recently updated via webhook and last_synced_at is within 15 min
		if (account.instagram_user_id && account.last_synced_at) {
			try {
				const { getRedis } = await import("../redis.js");
				const webhookActive = await getRedis().get(
					`webhook-active:ig:${account.instagram_user_id}`,
				);
				if (webhookActive) {
					const lastSynced = new Date(account.last_synced_at).getTime();
					if (lastSynced > Date.now() - 15 * 60 * 1000) {
						logger.info(
							"Skipping IG account (webhook-active, recently synced)",
							{
								username: account.username,
								igUserId: account.instagram_user_id,
								lastSynced: account.last_synced_at,
							},
						);
						return {
							accountId: igAccountId,
							username: account.username,
							success: true,
							skipped: true,
						};
					}
				}
			} catch (redisErr) {
				logger.debug("Redis webhook-active check failed (non-blocking)", {
					error: serializeError(redisErr),
				});
			}
		}

		const result = await refreshInstagramAccountAnalytics(
			// biome-ignore lint/suspicious/noExplicitAny: IgAccountRow and IGAccountRow are structurally equivalent
			account as any,
			"metrics",
		);

		// Invalidate dashboard cache after a real (non-skipped) sync so fresh
		// metrics are visible immediately without waiting for 30-min TTL expiry.
		if (result.success && !result.skipped) {
			const { invalidateDashboard } = await import("../dashboardCache.js");
			invalidateDashboard(igAccountId).catch(() => {});
		}

		return {
			accountId: igAccountId,
			username: account.username,
			success: result.success,
			skipped: result.skipped,
			error: result.error,
		};
	} catch (err) {
		return {
			accountId: igAccountId,
			success: false,
			error: serializeError(err),
		};
	}
}

// ============================================================================
// PHASE 1: Analytics Sync - Process Queue
// ============================================================================

/**
 * Cleanup stale analytics sync jobs (DB only).
 * User-triggered syncs now fan out to QStash directly — no Redis queue processing.
 * This just recovers stuck DB rows for clean Realtime state.
 */
export async function cleanupStaleAnalyticsJobs(): Promise<void> {
	const { getSupabase } = await import("../supabase.js");

	// Recover jobs stuck in "processing" for >20 minutes (accounts for QStash retries + Meta API latency)
	try {
		const { data: staleJobs } = await getSupabase()
			.from("sync_jobs")
			.update({
				status: "failed",
				completed_at: new Date().toISOString(),
				error_message: "Stale job recovery: stuck in processing >20min",
			})
			.eq("status", "processing")
			.lt("started_at", new Date(Date.now() - 20 * 60 * 1000).toISOString())
			.select("id");
		if (staleJobs && staleJobs.length > 0) {
			logger.warn("[orchestrator] Recovered stale processing jobs", {
				count: staleJobs.length,
				ids: staleJobs.map((j: StaleJobRow) => j.id),
			});
		}
	} catch (e) {
		logger.warn("[orchestrator] Stale job recovery check failed", {
			error: serializeError(e),
		});
	}

	// Recover jobs stuck in "queued" for >2 hours
	try {
		const { data: staleQueued } = await getSupabase()
			.from("sync_jobs")
			.update({
				status: "failed",
				completed_at: new Date().toISOString(),
				error_message: "Stale job recovery: stuck in queue > 2 hours",
			})
			.eq("status", "queued")
			.lt("updated_at", new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString())
			.select("id");
		if (staleQueued && staleQueued.length > 0) {
			logger.warn("[orchestrator] Recovered stale queued jobs", {
				count: staleQueued.length,
			});
		}
	} catch (e) {
		logger.warn("[orchestrator] Stale queued job recovery failed", {
			error: serializeError(e),
		});
	}
}

// Legacy Phase 4 processing — kept for reference but no longer called by the orchestrator.
// User-triggered syncs now fan out all accounts to QStash directly.
export async function _processAnalyticsSyncQueue(): Promise<number> {
	const { getSupabase } = await import("../supabase.js");
	const { dispatchWebhook } = await import("../webhookDispatcher.js");

	// Recover stale jobs stuck in "processing" for >10 minutes (Vercel timeout orphans)
	try {
		const { data: staleJobs } = await getSupabase()
			.from("sync_jobs")
			.update({
				status: "failed",
				completed_at: new Date().toISOString(),
				error_message:
					"Stale job recovery: stuck in processing (Vercel timeout)",
			})
			.eq("status", "processing")
			.lt("started_at", new Date(Date.now() - 10 * 60 * 1000).toISOString())
			.select("id");
		if (staleJobs && staleJobs.length > 0) {
			logger.warn("[orchestrator] Recovered stale processing jobs", {
				count: staleJobs.length,
				ids: staleJobs.map((j: StaleJobRow) => j.id),
			});
		}
	} catch (e) {
		logger.warn("[orchestrator] Stale job recovery check failed", {
			error: serializeError(e),
		});
	}

	// Recover stale jobs stuck in "queued" for >2 hours (engagement starvation prevention)
	try {
		const { data: staleQueued } = await getSupabase()
			.from("sync_jobs")
			.update({
				status: "failed",
				completed_at: new Date().toISOString(),
				error_message: "Stale job recovery: stuck in queue > 2 hours",
			})
			.eq("status", "queued")
			.lt("updated_at", new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString())
			.select("id, job_type");
		if (staleQueued && staleQueued.length > 0) {
			logger.warn("[orchestrator] Recovered stale queued jobs", {
				count: staleQueued.length,
				jobs: staleQueued.map((j: StaleQueuedJobRow) => ({
					id: j.id,
					type: j.job_type,
				})),
			});
		}
	} catch (e) {
		logger.warn("[orchestrator] Stale queued job recovery failed", {
			error: serializeError(e),
		});
	}

	const queueLength = await getQueueLen(SYNC_QUEUE_KEY);
	logger.debug("[orchestrator] Analytics sync queue check", { queueLength });

	if (queueLength === 0) return 0;

	const jobId = await popFromQueue(SYNC_QUEUE_KEY);
	if (!jobId) return 0;

	const job = await getJob<SyncJob>(SYNC_JOB_PREFIX, jobId);
	if (!job) {
		logger.warn("[orchestrator] Analytics sync job not found", { jobId });
		return 0;
	}

	const igAccountIds = Array.isArray(job.igAccountIds)
		? job.igAccountIds
		: Array.isArray(job.ig_account_ids)
			? job.ig_account_ids
			: [];
	const totalAccounts = job.accountIds.length + igAccountIds.length;

	logger.debug("[orchestrator] Processing analytics sync job", {
		jobId,
		userId: job.userId,
		accountCount: totalAccounts,
		threadsCount: job.accountIds.length,
		igCount: igAccountIds.length,
	});

	// Priority-based ordering
	if (job.accountIds.length > 1) {
		const { data: accountMeta } = await getSupabase()
			.from("accounts")
			.select("id, last_synced_at, followers_count")
			.in("id", job.accountIds);

		if (accountMeta && accountMeta.length > 0) {
			const priorityMap = new Map<string, number>();
			for (const acct of accountMeta) {
				const lastSynced = acct.last_synced_at
					? new Date(acct.last_synced_at).getTime()
					: 0;
				const staleness = Date.now() - lastSynced;
				const followerBoost =
					Math.log10((acct.followers_count || 1) + 1) * 3_600_000;
				priorityMap.set(acct.id, staleness + followerBoost);
			}
			job.accountIds.sort(
				(a: string, b: string) =>
					(priorityMap.get(b) || 0) - (priorityMap.get(a) || 0),
			);
		}
	}

	await updateJob<SyncJob>(SYNC_JOB_PREFIX, jobId, {
		status: "processing",
		startedAt: Date.now(),
	});
	await updateSyncJobsTable(jobId, job.userId, {
		status: "processing",
		account_count: totalAccounts,
		started_at: new Date().toISOString(),
	});

	const results: SyncResult[] = [];
	const suspended: string[] = [];
	const needsReauth: string[] = [];
	const reactivated: string[] = [];
	const failedErrors: string[] = [];
	let success = 0;
	let failed = 0;
	let processed = 0;

	// Batch pre-fetch prior follower counts to avoid N+1 queries inside syncAccount
	const todayKeyForBatch = new Date().toISOString().split("T")[0]!;
	const priorFollowersMap = new Map<string, number>();
	try {
		// Fetch the most recent analytics row per account (before today)
		// Using a single query with distinct on account_id
		const { data: priorRows } = await getSupabase()
			.from("account_analytics")
			.select("account_id, followers_count, date")
			.in("account_id", job.accountIds)
			.lt("date", todayKeyForBatch)
			.order("date", { ascending: false });
		if (priorRows) {
			// Keep only the most recent row per account_id
			for (const row of priorRows as Array<{
				account_id: string;
				followers_count: number | null;
			}>) {
				if (
					!priorFollowersMap.has(row.account_id) &&
					row.followers_count != null
				) {
					priorFollowersMap.set(row.account_id, row.followers_count);
				}
			}
		}
	} catch (priorErr) {
		logger.warn(
			"[orchestrator] Failed to batch-fetch prior follower counts, falling back to per-account",
			{
				error: String(priorErr),
			},
		);
	}

	for (
		let batchStart = 0;
		batchStart < job.accountIds.length;
		batchStart += CONCURRENCY_LIMIT
	) {
		if (!hasTimeBudget()) {
			logger.warn(
				"[orchestrator] Time limit reached in analytics sync, re-queuing",
				{
					processed,
					remainingThreads: job.accountIds.length - batchStart,
					remainingIg: igAccountIds.length,
				},
			);
			const remainingAccounts = job.accountIds.slice(batchStart);
			await queueSyncJob(job.userId, remainingAccounts, igAccountIds);
			// Nudge orchestrator to pick up continuation immediately
			try {
				const { getQStashClient } = await import("../qstash.js");
				const { RETRIES: R } = await import("../qstashDefaults.js");
				const qstash = getQStashClient();
				const baseUrl =
					process.env.APP_URL || `https://${process.env.VERCEL_URL}`;
				await qstash.publishJSON({
					url: `${baseUrl}/api/cron/sync-orchestrator`,
					body: { nudge: true, continuation: true },
					headers: {
						Authorization: `Bearer ${process.env.CRON_SECRET}`,
					},
					retries: R.BEST_EFFORT,
					delay: 5, // 5s delay to let current invocation release the cron lock
				});
			} catch (_nudgeErr) {
				// Non-fatal — next cron cycle picks it up
			}
			await updateJob<SyncJob>(SYNC_JOB_PREFIX, jobId, {
				status: "completed",
				completedAt: Date.now(),
				progress: { current: processed, total: totalAccounts },
				results: { success, failed, suspended, reactivated, needsReauth },
			});
			return processed;
		}

		const batchEnd = Math.min(
			batchStart + CONCURRENCY_LIMIT,
			job.accountIds.length,
		);
		const batch = job.accountIds.slice(batchStart, batchEnd);

		await updateJob<SyncJob>(SYNC_JOB_PREFIX, jobId, {
			progress: {
				current: Math.min(processed + 1, totalAccounts),
				total: totalAccounts,
				currentAccount: batch[0],
			},
		});

		const batchResults = await Promise.all(
			batch.map(async (accountId) => {
				const result = await syncAccount(
					accountId,
					job.userId,
					priorFollowersMap.get(accountId) ?? null,
				);
				return { accountId, result };
			}),
		);

		for (const { accountId, result } of batchResults) {
			results.push(result);
			processed++;
			if (result.success) {
				success++;
				if (result.skipped) {
					logger.debug("Account skipped (fresh)", {
						username: result.username || accountId,
					});
				} else if (result.reactivated) {
					reactivated.push(result.username || accountId);
				}
			} else if (result.needsReauth) {
				needsReauth.push(result.username || accountId);
				failed++;
				if (result.error)
					failedErrors.push(`${result.username || accountId}: ${result.error}`);
			} else if (result.suspended) {
				suspended.push(result.username || accountId);
				failed++;
				if (result.error)
					failedErrors.push(`${result.username || accountId}: ${result.error}`);
			} else {
				failed++;
				if (result.error)
					failedErrors.push(`${result.username || accountId}: ${result.error}`);
			}
			logger.debug("Sync account result", {
				processed,
				total: totalAccounts,
				username: result.username || accountId,
				success: result.success,
				skipped: result.skipped,
			});
		}

		await updateSyncJobsTable(jobId, job.userId, {
			current_progress: processed,
			current_account:
				batchResults[batchResults.length - 1]?.result?.username ||
				batch[batch.length - 1] ||
				null,
			success_count: success,
			failed_count: failed,
			suspended_accounts: suspended,
			reactivated_accounts: reactivated,
		});

		if (batchEnd < job.accountIds.length) {
			await new Promise((resolve) =>
				setTimeout(resolve, DELAY_BETWEEN_ACCOUNTS),
			);
		}
	}

	// --- Instagram accounts (if any) ---
	if (igAccountIds.length > 0) {
		// Large IG batches are fanned out to QStash — each account gets its own 60s budget.
		// Processing >IG_DIRECT_LIMIT accounts inline risks exceeding MAX_EXECUTION_TIME
		// (210 accounts × 400ms/call ≈ 28s at concurrency=3, plus Threads overhead = timeout).
		if (igAccountIds.length > IG_DIRECT_LIMIT) {
			const baseUrl =
				process.env.APP_URL || `https://${process.env.VERCEL_URL}`;
			const { getQStashClient } = await import("../qstash.js");
			const { RETRIES: R } = await import("../qstashDefaults.js");
			const { getRedis: getRedisInner } = await import("../redis.js");
			const qstash = getQStashClient();
			const redis = getRedisInner();
			const dateKey = new Date().toISOString().split("T")[0]!;
			let fanned = 0;
			for (let i = 0; i < igAccountIds.length; i++) {
				const igId = igAccountIds[i];
				const dedupKey = `analytics-sync:${igId}:metrics`;
				const existing = await redis.get(dedupKey).catch(() => null);
				if (existing) continue;
				try {
					await qstash.publishJSON({
						url: `${baseUrl}/api/sync/ig-account`,
						body: { accountId: igId, userId: job.userId, syncType: "metrics" },
						retries: R.IMPORTANT,
						delay: i * 2,
						deduplicationId: `${igId}-${dateKey}-metrics`,
					});
					await redis.set(dedupKey, "1", { ex: 86400 }).catch(() => {});
					fanned++;
				} catch (qErr) {
					logger.warn("[orchestrator] Failed to fan out IG account to QStash", {
						igId,
						error: String(qErr),
					});
				}
			}
			logger.info("[orchestrator] Large IG batch fanned out to QStash", {
				total: igAccountIds.length,
				dispatched: fanned,
			});
			processed += igAccountIds.length;
		} else {
			for (
				let igStart = 0;
				igStart < igAccountIds.length;
				igStart += CONCURRENCY_LIMIT
			) {
				if (!hasTimeBudget()) {
					logger.warn(
						"[orchestrator] Time limit reached during IG analytics sync, re-queuing",
						{
							processed,
							remainingIg: igAccountIds.length - igStart,
						},
					);
					// Re-queue only if small enough to fit in a single invocation;
					// otherwise fan remaining accounts to QStash to avoid infinite re-queue loops.
					const remainingIg = igAccountIds.slice(igStart);
					if (remainingIg.length <= IG_DIRECT_LIMIT) {
						await queueSyncJob(job.userId, [], remainingIg);
					} else {
						const baseUrl =
							process.env.APP_URL || `https://${process.env.VERCEL_URL}`;
						const { getQStashClient } = await import("../qstash.js");
						const { RETRIES: R2 } = await import("../qstashDefaults.js");
						const { getRedis: getRedisInner } = await import("../redis.js");
						const qstash = getQStashClient();
						const redis = getRedisInner();
						const dateKey = new Date().toISOString().split("T")[0]!;
						for (let i = 0; i < remainingIg.length; i++) {
							const igId = remainingIg[i];
							try {
								await qstash.publishJSON({
									url: `${baseUrl}/api/sync/ig-account`,
									body: {
										accountId: igId,
										userId: job.userId,
										syncType: "metrics",
									},
									retries: R2.IMPORTANT,
									delay: i * 2,
									deduplicationId: `${igId}-${dateKey}-metrics`,
								});
								await redis
									.set(`analytics-sync:${igId}:metrics`, "1", { ex: 86400 })
									.catch(() => {});
							} catch {
								/* non-fatal */
							}
						}
					}
					await updateJob<SyncJob>(SYNC_JOB_PREFIX, jobId, {
						status: "completed",
						completedAt: Date.now(),
						progress: { current: processed, total: totalAccounts },
						results: { success, failed, suspended, reactivated, needsReauth },
					});
					return processed;
				}

				const batchEnd = Math.min(
					igStart + CONCURRENCY_LIMIT,
					igAccountIds.length,
				);
				const batch = igAccountIds.slice(igStart, batchEnd);

				await updateJob<SyncJob>(SYNC_JOB_PREFIX, jobId, {
					progress: {
						current: Math.min(processed + 1, totalAccounts),
						total: totalAccounts,
						currentAccount: batch[0],
					},
				});

				const batchResults = await Promise.all(
					batch.map(async (accountId: string) => {
						const result = await syncIgAccount(accountId, job.userId);
						return { accountId, result };
					}),
				);

				for (const { accountId, result } of batchResults) {
					results.push(result);
					processed++;
					if (result.success) {
						success++;
					} else if (result.suspended) {
						suspended.push(result.username || accountId);
						failed++;
						if (result.error)
							failedErrors.push(
								`IG:${result.username || accountId}: ${result.error}`,
							);
					} else if (!result.skipped) {
						failed++;
						if (result.error)
							failedErrors.push(
								`IG:${result.username || accountId}: ${result.error}`,
							);
					}
					logger.debug("IG sync account result", {
						processed,
						total: totalAccounts,
						username: result.username || accountId,
						success: result.success,
						skipped: result.skipped,
					});
				}

				await updateSyncJobsTable(jobId, job.userId, {
					current_progress: processed,
					current_account:
						batchResults[batchResults.length - 1]?.result?.username ||
						batch[batch.length - 1] ||
						null,
					success_count: success,
					failed_count: failed,
					suspended_accounts: suspended,
					reactivated_accounts: reactivated,
				});

				if (batchEnd < igAccountIds.length) {
					await new Promise((resolve) =>
						setTimeout(resolve, DELAY_BETWEEN_ACCOUNTS),
					);
				}
			}
		} // end else (IG_DIRECT_LIMIT branch)
	}

	await updateJob<SyncJob>(SYNC_JOB_PREFIX, jobId, {
		status: "completed",
		completedAt: Date.now(),
		progress: { current: totalAccounts, total: totalAccounts },
		results: { success, failed, suspended, reactivated },
	});

	// Build error_message from collected failures (truncate to 1000 chars)
	const errorSummary =
		failedErrors.length > 0
			? failedErrors.slice(0, 10).join("; ").slice(0, 1000)
			: null;

	await updateSyncJobsTable(jobId, job.userId, {
		status: "completed",
		current_progress: totalAccounts,
		current_account: null,
		success_count: success,
		failed_count: failed,
		suspended_accounts: suspended,
		reactivated_accounts: reactivated,
		completed_at: new Date().toISOString(),
		error_message: errorSummary,
	});

	const duration = Date.now() - getOrchestratorStartTime();
	logger.info("[orchestrator] Analytics sync job completed", {
		jobId,
		durationMs: duration,
		success,
		failed,
		needsReauth: needsReauth.length,
		suspended: suspended.length,
		total: totalAccounts,
	});

	// Alert if failure rate exceeds 30%
	if (totalAccounts > 5 && failed / totalAccounts > 0.3) {
		const { alertCronFailure } = await import("../alerting.js");
		alertCronFailure(
			"sync-orchestrator",
			`High failure rate: ${failed}/${totalAccounts} accounts failed (${Math.round((failed * 100) / totalAccounts)}%). Top errors: ${errorSummary || "unknown"}`,
		);
		logger.error("[orchestrator] High analytics sync failure rate", {
			jobId,
			failed,
			total: totalAccounts,
			failurePct: Math.round((failed * 100) / totalAccounts),
		});
	}

	// Dispatch outgoing webhook (fire and forget)
	dispatchWebhook(job.userId, "sync.completed", {
		accountIds: [...job.accountIds, ...igAccountIds],
		postsUpdated: success,
		metricsRefreshed: true,
	});

	return totalAccounts;
}
