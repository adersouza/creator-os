// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Competitor Sync Phase — Competitor profile, posts, and viral spike detection.
 * Extracted from sync-orchestrator.ts.
 *
 * getAllAccessTokens() — fetch all valid access tokens for a user
 * syncCompetitor() — sync a single competitor's profile and posts
 * processCompetitorJob() — process a competitor sync job
 * processCompetitorSyncQueue() — process the competitor sync Redis queue
 */

import { logger, serializeError } from "../logger.js";
import { withRetry } from "../retryUtils.js";

import {
	COMPETITOR_BATCH_DELAY_MS,
	COMPETITOR_BATCH_SIZE,
	COMPETITOR_JOB_PREFIX,
	COMPETITOR_QUEUE_KEY,
	type CompetitorRow,
	type CompetitorSyncJob,
	hasTimeBudget,
	updateSyncJobsTable,
} from "./shared.js";

interface CompetitorAccountTokenRow {
	id: string;
	threads_access_token_encrypted: string | null;
	needs_reauth?: boolean | null;
	is_active?: boolean | null;
	status?: string | null;
	token_expires_at?: string | null;
}

// ============================================================================
// PHASE 4: Competitor Sync - Core Logic
// ============================================================================

export async function getAllAccessTokens(userId: string): Promise<string[]> {
	const { decrypt } = await import("../encryption.js");
	const { getSupabase } = await import("../supabase.js");

	const { data: accounts } = await getSupabase()
		.from("accounts")
		.select(
			"id, threads_access_token_encrypted, needs_reauth, is_active, status, token_expires_at",
		)
		.eq("user_id", userId)
		.eq("is_active", true)
		.eq("needs_reauth", false)
		.eq("status", "active")
		.or(
			`token_expires_at.is.null,token_expires_at.gt.${new Date().toISOString()}`,
		)
		.not("threads_access_token_encrypted", "is", null)
		.order("created_at", { ascending: false })
		.limit(10);

	if (!accounts) return [];

	const tokens: string[] = [];
	for (const acc of accounts as CompetitorAccountTokenRow[]) {
		if (
			!acc.threads_access_token_encrypted ||
			acc.needs_reauth ||
			acc.is_active === false ||
			acc.status !== "active" ||
			(acc.token_expires_at &&
				new Date(acc.token_expires_at).getTime() <= Date.now())
		) {
			continue;
		}
		try {
			tokens.push(decrypt(acc.threads_access_token_encrypted));
		} catch (err) {
			logger.warn("Token decryption failed for competitor sync", {
				accountId: acc.id,
				error: String(err),
			});
		}
	}
	return tokens;
}

export async function syncCompetitor(
	competitorId: string,
	username: string,
	tokens: string[],
	userId?: string,
): Promise<{ success: boolean; error?: string | undefined }> {
	const { getSupabase } = await import("../supabase.js");
	const { detectAccountStatus, updateCompetitorSyncStatus } = await import(
		"../handlers/competitors/shared.js"
	);

	let lastStatus: "private" | "deleted" | "rate_limited" | "error" | null =
		null;
	let lastError: string | undefined;

	for (const token of tokens) {
		try {
			const response = await withRetry(
				() =>
					fetch(
						`https://graph.threads.net/v1.0/profile_lookup?username=${encodeURIComponent(username)}`,
						{
							headers: { Authorization: `Bearer ${token}` },
							signal: AbortSignal.timeout(10000),
						},
					),
				{ label: `competitorProfile:${username}` },
			);

			if (response.status === 401 || response.status === 403) {
				logger.warn(
					"Token expired or invalid during competitor sync, trying next token",
					{ username, status: response.status },
				);
				lastError = `Token rejected with ${response.status}`;
				continue;
			}

			if (!response.ok) {
				const errorBody = await response.text();
				const accountStatus = detectAccountStatus(response.status, errorBody);
				if (accountStatus) {
					lastStatus = accountStatus;
					await updateCompetitorSyncStatus(competitorId, accountStatus);
				}
				lastError = `Threads API returned ${response.status}: ${errorBody.slice(0, 200)}`;
				if (accountStatus && accountStatus !== "rate_limited") {
					return { success: false, error: lastError };
				}
				continue;
			}

			const data = await response.json();

			if (data.error) {
				const errMsg = data.error.message || "";
				if (
					errMsg.includes("expired") ||
					errMsg.includes("Invalid") ||
					data.error.code === 190
				) {
					logger.warn(
						"Token expired (API error) during competitor sync, trying next token",
						{ username, errorCode: data.error.code },
					);
					lastError = errMsg || "Token expired";
					continue;
				}
				const accountStatus = detectAccountStatus(400, errMsg);
				if (accountStatus) {
					lastStatus = accountStatus;
					await updateCompetitorSyncStatus(competitorId, accountStatus);
					return { success: false, error: errMsg || accountStatus };
				}
				lastError = errMsg || "Competitor API error";
				continue;
			}

			// Update competitor profile
			await getSupabase()
				.from("competitors")
				.update({
					display_name: data.name || data.username,
					avatar_url: data.profile_picture_url || "",
					bio: data.biography || "",
					follower_count: data.follower_count || 0,
					is_verified: data.is_verified || false,
					likes_count_7d: data.likes_count || 0,
					quotes_count_7d: data.quotes_count || 0,
					replies_count_7d: data.replies_count || 0,
					reposts_count_7d: data.reposts_count || 0,
					views_count_7d: data.views_count || 0,
					last_synced_at: new Date().toISOString(),
					sync_status: "active",
					consecutive_failures: 0,
				})
				.eq("id", competitorId);

			// Create snapshot
			const today = new Date().toISOString().split("T")[0]!;
			await getSupabase().from("competitor_snapshots").upsert!(
				{
					competitor_id: competitorId,
					...(userId ? { user_id: userId } : {}),
					snapshot_date: today,
					follower_count: data.follower_count || 0,
					likes_count_7d: data.likes_count || 0,
					quotes_count_7d: data.quotes_count || 0,
					replies_count_7d: data.replies_count || 0,
					reposts_count_7d: data.reposts_count || 0,
					views_count_7d: data.views_count || 0,
				},
				{ onConflict: "competitor_id,snapshot_date" },
			);

			// Throttle between profile lookup and post fetch to avoid Meta rate limiting
			await new Promise((r) => setTimeout(r, 300));

			// Also fetch and store posts through the shared status-aware upsert path.
			try {
				const { fetchAndStorePosts } = await import(
					"../handlers/competitors/shared.js"
				);
				const postsResult = await fetchAndStorePosts(
					competitorId,
					username,
					token,
					userId,
				);
				logger.info("Competitor profile and posts synced", {
					username,
					postsCount: postsResult.postsCount,
					accountStatus: postsResult.accountStatus,
				});
			} catch (postsErr) {
				logger.warn("Competitor profile synced but post fetch failed", {
					username,
					error: serializeError(postsErr),
				});
			}

			return { success: true };
		} catch (err) {
			lastError = err instanceof Error ? err.message : String(err);
			logger.warn("Competitor sync token attempt failed", {
				error: String(err),
			});
		}
	}

	if (lastStatus) {
		await updateCompetitorSyncStatus(competitorId, lastStatus);
	} else {
		await updateCompetitorSyncStatus(competitorId, "error");
	}
	return { success: false, error: lastError || "All tokens failed" };
}

export async function processCompetitorJob(
	job: CompetitorSyncJob,
): Promise<void> {
	const { getRedis } = await import("../redis.js");
	const { getSupabase } = await import("../supabase.js");

	logger.debug("[orchestrator] Processing competitor sync job", {
		jobId: job.id,
		competitorCount: job.competitorIds.length,
	});

	// Update job status
	const compJob = await (async () => {
		const data = await getRedis().get(`${COMPETITOR_JOB_PREFIX}${job.id}`);
		if (!data) return null;
		return typeof data === "string" ? JSON.parse(data) : data;
	})();
	if (compJob) {
		await getRedis().set(
			`${COMPETITOR_JOB_PREFIX}${job.id}`,
			JSON.stringify({
				...compJob,
				status: "processing",
				startedAt: Date.now(),
			}),
			{ ex: 3600 },
		);
	}
	await updateSyncJobsTable(job.id, job.userId, {
		job_type: "competitors",
		status: "processing",
		started_at: new Date().toISOString(),
	});

	// Get tokens for this user
	const tokens = await getAllAccessTokens(job.userId);
	if (tokens.length === 0) {
		if (compJob) {
			await getRedis().set(
				`${COMPETITOR_JOB_PREFIX}${job.id}`,
				JSON.stringify({
					...compJob,
					status: "failed",
					error: "No valid tokens",
					completedAt: Date.now(),
				}),
				{ ex: 3600 },
			);
		}
		await updateSyncJobsTable(job.id, job.userId, {
			job_type: "competitors",
			status: "failed",
			error_message: "No valid tokens",
			completed_at: new Date().toISOString(),
		});
		return;
	}

	// Batch-fetch all competitor usernames + follower counts upfront
	const { data: allComps } = await getSupabase()
		.from("competitors")
		.select("id, username, follower_count")
		.in("id", job.competitorIds)
		.or("sync_status.eq.active,sync_status.is.null");

	const usernameMap = new Map<string, string>();
	if (allComps) {
		for (const comp of allComps as CompetitorRow[]) {
			usernameMap.set(comp.id, comp.username);
		}

		// Sort competitor IDs by follower count descending (high-value first)
		const followerMap = new Map<string, number>();
		for (const comp of allComps as CompetitorRow[]) {
			followerMap.set(comp.id, comp.follower_count || 0);
		}
		job.competitorIds.sort(
			(a, b) => (followerMap.get(b) || 0) - (followerMap.get(a) || 0),
		);

		logger.debug("[orchestrator] Competitor sync priority order set", {
			jobId: job.id,
			topCompetitor: job.competitorIds[0]
				? usernameMap.get(job.competitorIds[0])
				: undefined,
			topFollowers: job.competitorIds[0]
				? followerMap.get(job.competitorIds[0])
				: 0,
		});
	}

	const results = { success: 0, failed: 0 };
	let processed = 0;

	for (let i = 0; i < job.competitorIds.length; i += COMPETITOR_BATCH_SIZE) {
		if (!hasTimeBudget()) {
			logger.warn("[orchestrator] Time limit reached during competitor sync", {
				processed,
				total: job.competitorIds.length,
			});
			break;
		}

		const batch = job.competitorIds.slice(i, i + COMPETITOR_BATCH_SIZE);

		const batchResults = await Promise.all(
			batch.map(async (competitorId) => {
				const username = usernameMap.get(competitorId);
				if (!username) {
					return { success: false, error: "Username not found" };
				}
				return syncCompetitor(competitorId, username, tokens, job.userId);
			}),
		);

		for (const result of batchResults) {
			processed++;
			if (result.success) {
				results.success++;
			} else {
				results.failed++;
			}
		}

		// Update progress after each batch
		const lastCompId = batch[batch.length - 1];
		if (compJob) {
			await getRedis().set(
				`${COMPETITOR_JOB_PREFIX}${job.id}`,
				JSON.stringify({
					...compJob,
					status: "processing",
					progress: {
						current: processed,
						total: job.competitorIds.length,
						currentName: usernameMap.get(lastCompId!),
					},
				}),
				{ ex: 3600 },
			);
		}
		await updateSyncJobsTable(job.id, job.userId, {
			current_progress: processed,
			current_account: usernameMap.get(lastCompId!) ?? null,
		});

		if (i + COMPETITOR_BATCH_SIZE < job.competitorIds.length) {
			await new Promise((r) => setTimeout(r, COMPETITOR_BATCH_DELAY_MS));
		}
	}

	if (compJob) {
		await getRedis().set(
			`${COMPETITOR_JOB_PREFIX}${job.id}`,
			JSON.stringify({
				...compJob,
				status: "completed",
				completedAt: Date.now(),
				results,
			}),
			{ ex: 3600 },
		);
	}
	await updateSyncJobsTable(job.id, job.userId, {
		job_type: "competitors",
		status: "completed",
		completed_at: new Date().toISOString(),
		success_count: results.success,
		failed_count: results.failed,
		competitors_synced: results.success,
		current_account: null,
	});

	logger.info("[orchestrator] Competitor sync job completed", {
		jobId: job.id,
		success: results.success,
		failed: results.failed,
	});
}

// ============================================================================
// PHASE 4: Competitor Sync - Process Queue
// ============================================================================

export async function processCompetitorSyncQueue(): Promise<number> {
	const { getRedis } = await import("../redis.js");

	if (!hasTimeBudget()) {
		logger.debug("[orchestrator] No time budget for competitor sync queue");
		return 0;
	}

	const redis = getRedis();
	const queueLength = await redis.llen(COMPETITOR_QUEUE_KEY);
	logger.debug("[orchestrator] Competitor sync queue check", { queueLength });

	if (queueLength === 0) return 0;

	const jobId = (await redis.rpop(COMPETITOR_QUEUE_KEY)) as string | null;
	if (!jobId) return 0;

	const data = await redis.get(`${COMPETITOR_JOB_PREFIX}${jobId}`);
	if (!data) return 0;

	const job: CompetitorSyncJob =
		typeof data === "string" ? JSON.parse(data) : (data as CompetitorSyncJob);

	await processCompetitorJob(job);
	return job.competitorIds.length;
}
