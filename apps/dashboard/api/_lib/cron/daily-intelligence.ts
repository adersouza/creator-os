// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Daily Intelligence — Consolidated Cron Job
 *
 * Merges daily crons into one sequential pipeline:
 *   Phase 1: power-user-scoring   (pure DB, ~5-30s)
 *   Phase 2: quickwin-monitor     (DB + Redis, ~10s)
 *   Phase 3: competitor-snapshots  (Threads API, ~60-240s)
 *
 * Each phase has its own try/catch and checks time budget before starting.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { alertCronFailure } from "../alerting.js";
import { createNotification } from "../createNotification.js";
import { trackCronRun, withCronLock } from "../cronUtils.js";
import { decrypt } from "../encryption.js";
import {
	detectAccountStatus,
	updateCompetitorSyncStatus,
} from "../handlers/competitors/shared.js";
import { logger } from "../logger.js";
import { isAuthError as isMetaAuthError } from "../metaErrors.js";
import {
	checkRegressions,
	checkResultReminders,
} from "../regressionDetector.js";
import { getSupabase, getSupabaseAny } from "../supabase.js";

export const config = {
	maxDuration: 300,
};

const MAX_EXECUTION_TIME = 290_000; // 290s safety margin for 300s maxDuration
const POWER_USER_SCORING_BATCH_SIZE = 50;

const db = () => getSupabase();
const dbAny = () => getSupabaseAny();

// ============================================================================
// Shared helpers
// ============================================================================

function clamp(value: number, min: number, max: number): number {
	return Math.max(min, Math.min(max, value));
}

function hasTimeBudget(startTime: number): boolean {
	return Date.now() - startTime < MAX_EXECUTION_TIME;
}

function elapsed(startTime: number): number {
	return Date.now() - startTime;
}

// ============================================================================
// Phase results type
// ============================================================================

interface PhaseResult {
	status: "success" | "skipped" | "error";
	durationMs: number;
	detail?: Record<string, unknown> | undefined;
	error?: string | undefined;
}

// ============================================================================
// Phase 1: Power User Scoring (pure DB, fastest)
// ============================================================================

async function computeScoreForUser(userId: string): Promise<number> {
	const now = new Date();
	const weekAgo = new Date(
		now.getTime() - 7 * 24 * 60 * 60 * 1000,
	).toISOString();
	const twoWeeksAgo = new Date(
		now.getTime() - 14 * 24 * 60 * 60 * 1000,
	).toISOString();

	// Posts per week (across all accounts)
	const { count: postsCount } = await db()
		.from("posts")
		.select("id", { count: "exact", head: true })
		.eq("user_id", userId)
		.eq("status", "published")
		.gte("published_at", weekAgo);
	const postsPerWeek = postsCount || 0;

	// Co-Pilot queries per week
	const { count: copilotCount } = await db()
		.from("feature_usage")
		.select("id", { count: "exact", head: true })
		.eq("user_id", userId)
		.eq("feature_name", "copilot")
		.gte("used_at", weekAgo);
	const copilotQueriesPerWeek = copilotCount || 0;

	// Login frequency: distinct days with feature_usage in last 14 days
	const { data: usageDays } = await db()
		.from("feature_usage")
		.select("used_at")
		.eq("user_id", userId)
		.gte("used_at", twoWeeksAgo);

	const distinctDays = new Set<string>();
	if (usageDays) {
		for (const row of usageDays) {
			if (row.used_at)
				distinctDays.add(new Date(row.used_at).toISOString().split("T")[0]!);
		}
	}
	const loginDaysLast14 = distinctDays.size;

	// Feature breadth: distinct feature categories
	const { data: features } = await db()
		.from("feature_usage")
		.select("feature_name")
		.eq("user_id", userId)
		.gte("used_at", twoWeeksAgo);

	const distinctCategories = new Set<string>();
	if (features) {
		for (const row of features) {
			const category =
				(row.feature_name || "").split(".")[0] || row.feature_name;
			distinctCategories.add(category);
		}
	}
	const distinctFeatureCategories = distinctCategories.size;

	// Compute score
	const posting = clamp(Math.round((postsPerWeek / 5) * 30), 0, 30);
	const copilot = clamp(Math.round((copilotQueriesPerWeek / 10) * 20), 0, 20);
	const loginFrequency = clamp(Math.round((loginDaysLast14 / 10) * 25), 0, 25);
	const featureBreadth = clamp(
		Math.round((distinctFeatureCategories / 8) * 25),
		0,
		25,
	);

	return clamp(posting + copilot + loginFrequency + featureBreadth, 0, 100);
}

export async function phasePowerUserScoring(): Promise<PhaseResult> {
	const phaseStart = Date.now();
	logger.info("[daily-intelligence] Phase 1: power-user-scoring started");

	const { data: users, error } = await db()
		.from("profiles")
		.select("id")
		.limit(10000);

	if (error || !users) {
		throw new Error(`Failed to fetch profiles: ${String(error)}`);
	}

	let updated = 0;
	for (let i = 0; i < users.length; i += POWER_USER_SCORING_BATCH_SIZE) {
		const batch = users.slice(i, i + POWER_USER_SCORING_BATCH_SIZE);
		const results = await Promise.allSettled(
			batch.map(async (user) => {
				const score = await computeScoreForUser(user.id);
				const { error: updateError } = await db()
					.from("profiles")
					.update({
						power_user_score: score,
						updated_at: new Date().toISOString(),
					})
					.eq("id", user.id);

				if (updateError) {
					throw new Error(
						`Failed to update profile score: ${String(updateError)}`,
					);
				}
			}),
		);

		for (const [index, result] of results.entries()) {
			if (result.status === "fulfilled") {
				updated++;
				continue;
			}

			logger.warn("[daily-intelligence] Power score failed for user", {
				userId: batch[index]?.id,
				error:
					result.reason instanceof Error
						? result.reason.message
						: String(result.reason),
			});
		}
	}

	logger.info("[daily-intelligence] Phase 1: power-user-scoring complete", {
		updated,
		total: users.length,
	});
	return {
		status: "success",
		durationMs: Date.now() - phaseStart,
		detail: { usersScored: updated, totalUsers: users.length },
	};
}

// ============================================================================
// Phase 2: Quick Win Monitor (DB + Redis)
// ============================================================================

export async function phaseQuickwinMonitor(): Promise<PhaseResult> {
	const phaseStart = Date.now();
	logger.info("[daily-intelligence] Phase 2: quickwin-monitor started");

	let regressionsDetected = 0;
	let remindersSent = 0;

	// 2a. Regression detection (batched per user+category to avoid notification spam)
	try {
		const events = await checkRegressions();
		regressionsDetected = events.length;

		// Resolve accountId → userId for all events
		type EventWithUser = (typeof events)[number] & { userId: string };
		const eventsWithUser: EventWithUser[] = [];
		for (const event of events) {
			const { data: account } = await db()
				.from("accounts")
				.select("user_id")
				.eq("id", event.accountId)
				.maybeSingle();
			if (!account) continue;
			eventsWithUser.push({ ...event, userId: account.user_id });
		}

		// Group by user+category+status → send ONE notification per group
		const grouped = new Map<string, EventWithUser[]>();
		for (const ev of eventsWithUser) {
			const key = `${ev.userId}:${ev.category}:${ev.status}`;
			const arr = grouped.get(key) || [];
			arr.push(ev);
			grouped.set(key, arr);
		}

		for (const [, batch] of grouped) {
			const first = batch[0];
			const count = batch.length;

			if (first!.status === "regressed") {
				const pctValues = [...new Set(batch.map((e) => e.regressionPct))];
				const pctStr =
					pctValues.length === 1
						? `${pctValues[0]}%`
						: `${Math.min(...pctValues)}-${Math.max(...pctValues)}%`;
				const scope =
					count === 1
						? `Your ${first!.category} metric dipped ${pctStr}`
						: `Your ${first!.category} metric dipped ${pctStr} across ${count} accounts`;

				await createNotification({
					userId: first!.userId,
					type: "quick_win_regressed",
					title: "\u21a9\ufe0f Quick Win Update",
					message: `${scope} this week. Algorithm shifts and seasonal patterns cause fluctuations. Your strategy is still sound \u2014 give it another week.`,
					data: {
						category: first!.category,
						accountCount: count,
						regressionPcts: pctValues,
						recIds: batch.map((e) => e.recId),
					},
				});
			} else if (first!.status === "faded") {
				const msg =
					count === 1
						? `This experiment's impact faded. We've queued a fresh recommendation in ${first!.category}.`
						: `${count} experiments in ${first!.category} have faded. Fresh recommendations queued.`;

				await createNotification({
					userId: first!.userId,
					type: "quick_win_faded",
					title: "\ud83d\udd04 Fresh Recommendation Queued",
					message: msg,
					data: {
						category: first!.category,
						accountCount: count,
						recIds: batch.map((e) => e.recId),
					},
				});

				// Clear deprioritization for each account so new recs can surface
				try {
					const { getRedis } = await import("../redis.js");
					const redis = getRedis();
					for (const ev of batch) {
						await redis.del(`rec:deprioritize:${ev.userId}:${ev.category}`);
						await redis.del(`rec:snooze:${ev.userId}:${ev.category}`);
					}
				} catch (err) {
					logger.debug("non-fatal redis cleanup", { error: String(err) });
				}
			}
		}

		logger.info("[daily-intelligence] Phase 2: regression check complete", {
			detected: regressionsDetected,
			notificationsSent: grouped.size,
		});
	} catch (err) {
		logger.error("[daily-intelligence] Phase 2: regression check failed", {
			error: String(err),
		});
	}

	// 2b. Result reminder nudges
	try {
		remindersSent = await checkResultReminders();
		logger.info("[daily-intelligence] Phase 2: result reminders sent", {
			count: remindersSent,
		});
	} catch (err) {
		logger.error("[daily-intelligence] Phase 2: result reminders failed", {
			error: String(err),
		});
	}

	logger.info("[daily-intelligence] Phase 2: quickwin-monitor complete", {
		regressionsDetected,
		remindersSent,
	});
	return {
		status: "success",
		durationMs: Date.now() - phaseStart,
		detail: { regressionsDetected, remindersSent },
	};
}

// ============================================================================
// Phase 3: Discover Refresh (no-op stub — saved_searches tables dropped)
// ============================================================================

export async function phaseDiscoverRefresh(): Promise<PhaseResult> {
	return {
		status: "skipped",
		durationMs: 0,
		detail: { reason: "saved_searches_tables_dropped" },
	};
}

// ============================================================================
// Phase 3 (formerly 4): Competitor Snapshots (Threads API calls, heaviest)
// ============================================================================

interface Competitor {
	id: string;
	user_id: string;
	username: string;
	threads_user_id: string | null;
	last_synced_at: string | null;
}

interface ProfileLookupResult {
	username: string;
	name?: string | undefined;
	profile_picture_url?: string | undefined;
	biography?: string | undefined;
	is_verified?: boolean | undefined;
	follower_count?: number | undefined;
	likes_count?: number | undefined;
	quotes_count?: number | undefined;
	replies_count?: number | undefined;
	reposts_count?: number | undefined;
	views_count?: number | undefined;
	error?: { message: string; code?: number | undefined } | undefined;
}

interface PoolToken {
	accountId: string;
	token: string;
}

/**
 * Build a global token pool from ALL accounts in the system.
 * Sorted by last_synced_at DESC so healthiest tokens come first.
 * Any valid token can look up any public profile — no per-user restriction needed.
 */
async function getGlobalTokenPool(): Promise<PoolToken[]> {
	const now = new Date().toISOString();
	const { data: accounts } = await getSupabase()
		.from("accounts")
		.select(
			"id, threads_access_token_encrypted, last_synced_at, token_expires_at",
		)
		.not("threads_access_token_encrypted", "is", null)
		.eq("is_active", true)
		.eq("needs_reauth", false)
		.or(`token_expires_at.is.null,token_expires_at.gt.${now}`)
		.order("last_synced_at", { ascending: false, nullsFirst: false });

	if (!accounts?.length) {
		logger.error(
			"[daily-intelligence] Phase 4: no accounts with valid tokens in pool",
		);
		return [];
	}

	const pool: PoolToken[] = [];
	let decryptionFailures = 0;

	for (const account of accounts) {
		try {
			const token = decrypt(account.threads_access_token_encrypted);
			pool.push({ accountId: account.id, token });
		} catch {
			decryptionFailures++;
		}
	}

	if (decryptionFailures > 0) {
		logger.warn("[daily-intelligence] Phase 4: token pool diagnostics", {
			accountsQueried: accounts.length,
			decryptionFailures,
			poolSize: pool.length,
		});
	}

	if (pool.length === 0) {
		logger.error(
			"[daily-intelligence] Phase 4: all token decryptions failed, pool is empty",
		);
	}

	return pool;
}

/**
 * Fetch a competitor profile, rotating through the token pool on 401s.
 * Returns the result plus the updated pool index so the caller can
 * keep using the working token for subsequent requests.
 */
async function fetchWithTokenPool(
	pool: PoolToken[],
	poolIndex: number,
	competitorId: string,
	username: string,
): Promise<{
	profile: ProfileLookupResult | null;
	rateLimited?: boolean | undefined;
	tokenExpired?: boolean | undefined;
	newPoolIndex: number;
}> {
	let idx = poolIndex;

	while (idx < pool.length) {
		const result = await fetchCompetitorProfile(
			competitorId,
			username,
			pool[idx]!.token,
		);

		if (result.profile) {
			// Success — return with current index
			return { ...result, tokenExpired: false, newPoolIndex: idx };
		}

		// Check if this was a 401/expired (not a competitor-specific error like private/deleted)
		// If the competitor itself is the issue (private, deleted), don't rotate tokens
		if (result.tokenAuth === false) {
			logger.warn("[daily-intelligence] Phase 4: token expired, rotating", {
				accountId: pool[idx]!.accountId,
				poolIndex: idx,
				poolSize: pool.length,
			});
			idx++;
			continue; // Try next token
		}

		// Non-auth failure (competitor is private, deleted, rate limited, etc.)
		return { ...result, tokenExpired: false, newPoolIndex: idx };
	}

	// Entire pool exhausted
	logger.error("[daily-intelligence] Phase 4: all tokens in pool exhausted");
	return { profile: null, tokenExpired: true, newPoolIndex: idx };
}

async function fetchCompetitorProfile(
	competitorId: string,
	username: string,
	accessToken: string,
): Promise<{
	profile: ProfileLookupResult | null;
	rateLimited?: boolean | undefined;
	tokenAuth?: boolean | undefined;
}> {
	try {
		const url = `https://graph.threads.net/v1.0/profile_lookup?username=${encodeURIComponent(username)}`;
		const response = await fetch(url, {
			headers: { Authorization: `Bearer ${accessToken}` },
			signal: AbortSignal.timeout(10000),
		});

		if (!response.ok) {
			const errorBody = await response.text().catch(() => "");
			// HTTP 401 is canonical auth failure; otherwise classify the parsed
			// Meta error envelope so transient 500s (code=1 OAuthException) don't
			// trigger token rotation. `response.status === 190` was a bug — 190 is
			// a Meta JSON code, never an HTTP status, so that branch was dead.
			let parsedMetaError: Record<string, unknown> | null = null;
			try {
				const parsed = JSON.parse(errorBody);
				if (parsed && typeof parsed === "object" && parsed.error) {
					parsedMetaError = parsed.error as Record<string, unknown>;
				}
			} catch {
				// not JSON — fall through to message-only classification.
			}
			const isAuthError =
				response.status === 401 ||
				isMetaAuthError(parsedMetaError !== null ? parsedMetaError : errorBody);
			const accountStatus = detectAccountStatus(response.status, errorBody);

			logger.warn(
				"[daily-intelligence] Phase 4: competitor profile API error",
				{ username, status: response.status, accountStatus },
			);

			// On auth errors, signal token rotation — don't blame the competitor
			if (isAuthError) {
				return { profile: null, rateLimited: false, tokenAuth: false };
			}

			if (accountStatus) {
				await updateCompetitorSyncStatus(competitorId, accountStatus);
			}

			return {
				profile: null,
				rateLimited: accountStatus === "rate_limited",
				tokenAuth: true,
			};
		}

		const data = await response.json();

		if (data.error) {
			const errorMsg = data.error.message || "";
			// Classify against the structured Meta error envelope so transient
			// `code=1, type=OAuthException` (Meta's 500) is NOT marked as auth.
			const isAuthError = isMetaAuthError(
				data.error as Record<string, unknown>,
			);
			const accountStatus = detectAccountStatus(400, errorMsg);

			logger.warn(
				"[daily-intelligence] Phase 4: competitor profile API error",
				{ username, error: errorMsg, accountStatus },
			);

			// Token-level auth error — signal rotation
			if (isAuthError) {
				return { profile: null, rateLimited: false, tokenAuth: false };
			}

			if (accountStatus) {
				await updateCompetitorSyncStatus(competitorId, accountStatus);
			}

			return {
				profile: null,
				rateLimited: accountStatus === "rate_limited",
				tokenAuth: true,
			};
		}

		await updateCompetitorSyncStatus(competitorId, "active");
		return { profile: data as ProfileLookupResult, tokenAuth: true };
	} catch (error) {
		logger.error(
			"[daily-intelligence] Phase 4: competitor profile fetch error",
			{
				username,
				error: error instanceof Error ? error.message : String(error),
			},
		);
		return { profile: null };
	}
}

export async function phaseCompetitorSnapshots(
	startTime: number,
): Promise<PhaseResult> {
	const phaseStart = Date.now();
	logger.info("[daily-intelligence] Phase 4: competitor-snapshots started");

	const SNAPSHOT_RETENTION_DAYS = 90;

	const stats = {
		totalCompetitors: 0,
		refreshed: 0,
		skipped: 0,
		failed: 0,
		snapshotsCreated: 0,
		oldSnapshotsDeleted: 0,
		errors: [] as string[],
	};

	// Get all competitors that need refresh
	const twentyHoursAgo = new Date(
		Date.now() - 20 * 60 * 60 * 1000,
	).toISOString();

	const { data: competitors, error: competitorsError } = (await getSupabase()
		.from("competitors")
		.select("id, user_id, username, threads_user_id, last_synced_at")
		.or(`last_synced_at.is.null,last_synced_at.lt.${twentyHoursAgo}`)
		.order("user_id")) as {
		data: Array<{
			id: string;
			user_id: string;
			username: string;
			threads_user_id: string | null;
			last_synced_at: string | null;
		}> | null;
		error: { message: string } | null;
	};

	if (competitorsError) {
		throw competitorsError;
	}

	if (!competitors || competitors.length === 0) {
		logger.info("[daily-intelligence] Phase 4: no competitors need refresh");
		return {
			status: "success",
			durationMs: Date.now() - phaseStart,
			detail: { totalCompetitors: 0 },
		};
	}

	stats.totalCompetitors = competitors.length;
	logger.info("[daily-intelligence] Phase 4: found competitors to refresh", {
		count: competitors.length,
	});

	const today = new Date().toISOString().split("T")[0]!;

	// Build global token pool — any valid token can look up any public profile
	const pool = await getGlobalTokenPool();

	if (pool.length === 0) {
		logger.error(
			"[daily-intelligence] Phase 4: no tokens available, skipping all competitors",
		);
		stats.skipped = competitors.length;
		return {
			status: "success",
			durationMs: Date.now() - phaseStart,
			detail: {
				totalCompetitors: stats.totalCompetitors,
				skipped: stats.skipped,
			},
		};
	}

	logger.info("[daily-intelligence] Phase 4: token pool ready", {
		poolSize: pool.length,
	});

	let poolIndex = 0;
	let poolExhausted = false;

	// Process all competitors in batches (no per-user grouping needed)
	const batchSize = 5;
	for (let i = 0; i < competitors.length; i += batchSize) {
		if (poolExhausted) {
			stats.skipped += competitors.length - i;
			break;
		}

		// Time budget check mid-batch
		if (!hasTimeBudget(startTime)) {
			logger.warn(
				"[daily-intelligence] Phase 4: time budget exhausted mid-batch",
				{ elapsed: elapsed(startTime) },
			);
			stats.skipped += competitors.length - i;
			break;
		}

		const batch = competitors.slice(i, i + batchSize);

		// Process batch sequentially to share pool index state across requests
		const batchResults: Array<{
			competitor: Competitor;
			profile?: ProfileLookupResult | undefined;
			success: boolean;
			rateLimited?: boolean | undefined;
		}> = [];

		for (const competitor of batch) {
			if (poolExhausted) {
				batchResults.push({ competitor, success: false });
				continue;
			}

			const result = await fetchWithTokenPool(
				pool,
				poolIndex,
				competitor.id,
				competitor.username,
			);

			poolIndex = result.newPoolIndex;

			if (result.tokenExpired) {
				// Entire pool exhausted
				poolExhausted = true;
				batchResults.push({ competitor, success: false });
				continue;
			}

			if (result.profile) {
				batchResults.push({
					competitor,
					profile: result.profile,
					success: true,
					rateLimited: result.rateLimited,
				});
			} else {
				batchResults.push({
					competitor,
					success: false,
					rateLimited: result.rateLimited,
				});
			}
		}

		const batchRateLimited = batchResults.some((r) => r.rateLimited);
		if (batchRateLimited) {
			logger.warn(
				"[daily-intelligence] Phase 4: rate limit detected, adding backoff",
			);
			await new Promise((resolve) => setTimeout(resolve, 5000));
		}

		const competitorUpdates: Record<string, unknown>[] = [];
		const snapshotUpserts: Record<string, unknown>[] = [];

		for (const result of batchResults) {
			if (!result.success || !result.profile) {
				stats.failed++;
				stats.errors.push(
					`@${result.competitor.username}: Failed to fetch profile`,
				);
				continue;
			}

			const { competitor, profile } = result;

			competitorUpdates.push({
				id: competitor.id,
				display_name: profile.name || profile.username,
				avatar_url: profile.profile_picture_url || "",
				bio: profile.biography || "",
				follower_count: profile.follower_count || 0,
				is_verified: profile.is_verified || false,
				likes_count_7d: profile.likes_count || 0,
				quotes_count_7d: profile.quotes_count || 0,
				replies_count_7d: profile.replies_count || 0,
				reposts_count_7d: profile.reposts_count || 0,
				views_count_7d: profile.views_count || 0,
				last_synced_at: new Date().toISOString(),
			});

			snapshotUpserts.push({
				competitor_id: competitor.id,
				snapshot_date: today,
				follower_count: profile.follower_count || 0,
				likes_count_7d: profile.likes_count || 0,
				quotes_count_7d: profile.quotes_count || 0,
				replies_count_7d: profile.replies_count || 0,
				reposts_count_7d: profile.reposts_count || 0,
				views_count_7d: profile.views_count || 0,
			});
		}

		// Batch update competitors
		if (competitorUpdates.length > 0) {
			const { error: updateError } = await getSupabase()
				.from("competitors")
				// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert payload shape mismatch with generated types
				.upsert(competitorUpdates as any, { onConflict: "id" });

			if (updateError) {
				logger.error(
					"[daily-intelligence] Phase 4: batch competitor update error",
					{
						error:
							updateError instanceof Error
								? updateError.message
								: String(updateError),
					},
				);
				stats.failed += competitorUpdates.length;
			} else {
				stats.refreshed += competitorUpdates.length;
			}
		}

		// Batch upsert snapshots
		if (snapshotUpserts.length > 0) {
			const { error: snapshotError } = await getSupabase()
				.from("competitor_snapshots")
				// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert payload shape mismatch with generated types
				.upsert(snapshotUpserts as any, {
					onConflict: "competitor_id,snapshot_date",
				});

			if (snapshotError) {
				logger.error(
					"[daily-intelligence] Phase 4: batch snapshot upsert error",
					{ error: snapshotError.message },
				);
				stats.failed += snapshotUpserts.length;
			} else {
				stats.snapshotsCreated += snapshotUpserts.length;
			}
		}

		// Rate limiting between batches
		if (i + batchSize < competitors.length) {
			await new Promise((resolve) => setTimeout(resolve, 100));
		}
	}

	// IG competitors snapshots
	if (hasTimeBudget(startTime)) {
		const { data: igCompetitors } = (await getSupabase()
			.from("competitors")
			.select(
				"id, user_id, username, follower_count, engagement_rate, avg_likes, avg_comments, media_count",
			)
			.eq("platform", "instagram")
			.or(`last_synced_at.is.null,last_synced_at.lt.${twentyHoursAgo}`)) as {
			data: Array<{
				id: string;
				user_id: string;
				username: string;
				follower_count: number | null;
				engagement_rate: number | null;
				avg_likes: number | null;
				avg_comments: number | null;
				media_count: number | null;
			}> | null;
			error: unknown;
		};

		if (igCompetitors && igCompetitors.length > 0) {
			logger.info("[daily-intelligence] Phase 4: found IG competitors", {
				count: igCompetitors.length,
			});

			const igSnapshotUpserts: Record<string, unknown>[] = [];
			for (const igComp of igCompetitors) {
				igSnapshotUpserts.push({
					competitor_id: igComp.id,
					snapshot_date: today,
					follower_count: igComp.follower_count || 0,
					engagement_rate: igComp.engagement_rate || null,
					avg_likes: igComp.avg_likes || null,
					avg_comments: igComp.avg_comments || null,
					media_count: igComp.media_count || null,
				});
			}

			if (igSnapshotUpserts.length > 0) {
				const { error: igSnapError } = await getSupabase()
					.from("competitor_snapshots")
					// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert payload shape mismatch with generated types
					.upsert(igSnapshotUpserts as any, {
						onConflict: "competitor_id,snapshot_date",
					});

				if (igSnapError) {
					logger.error(
						"[daily-intelligence] Phase 4: IG snapshot upsert error",
						{ error: igSnapError.message },
					);
					stats.failed += igSnapshotUpserts.length;
				} else {
					stats.snapshotsCreated += igSnapshotUpserts.length;
				}
			}

			// Alert detection for IG competitors
			const milestones = [100000, 50000, 10000, 5000, 1000];
			const sevenDaysAgoDate = new Date();
			sevenDaysAgoDate.setDate(sevenDaysAgoDate.getDate() - 7);
			const sevenDaysAgoStr = sevenDaysAgoDate.toISOString().split("T")[0]!;

			const alertInserts: Record<string, unknown>[] = [];

			for (const igComp of igCompetitors) {
				if (!hasTimeBudget(startTime)) break;

				const followers = igComp.follower_count || 0;

				// Follower milestones
				for (const milestone of milestones) {
					if (followers >= milestone) {
						const { data: existing } = (await getSupabase()
							.from("competitor_alerts")
							.select("id")
							.eq("competitor_id", igComp.id)
							.eq("alert_type", "follower_milestone")
							.contains("metadata", { milestone })
							.limit(1)) as {
							data: Array<{ id: string }> | null;
							error: unknown;
						};

						if (!existing || existing.length === 0) {
							const formatted =
								milestone >= 1000 ? `${milestone / 1000}K` : `${milestone}`;
							alertInserts.push({
								user_id: igComp.user_id,
								competitor_id: igComp.id,
								alert_type: "follower_milestone",
								message: `@${igComp.username} reached ${formatted} followers!`,
								metadata: { milestone, currentFollowers: followers },
							});
						}
						break;
					}
				}

				// Growth spike check
				const { data: weekSnap } = (await getSupabase()
					.from("competitor_snapshots")
					.select("follower_count")
					.eq("competitor_id", igComp.id)
					.lte("snapshot_date", sevenDaysAgoStr)
					.order("snapshot_date", { ascending: false })
					.limit(1)) as {
					data: Array<{ follower_count: number }> | null;
					error: unknown;
				};

				if (weekSnap && weekSnap.length > 0 && weekSnap[0]!.follower_count > 0) {
					const prev = weekSnap[0]!.follower_count;
					const growthPct = ((followers - prev) / prev) * 100;
					if (growthPct > 10) {
						const oneDayAgo = new Date(
							Date.now() - 24 * 60 * 60 * 1000,
						).toISOString();
						const { data: existingSpike } = (await getSupabase()
							.from("competitor_alerts")
							.select("id")
							.eq("competitor_id", igComp.id)
							.eq("alert_type", "growth_spike")
							.gte("created_at", oneDayAgo)
							.limit(1)) as {
							data: Array<{ id: string }> | null;
							error: unknown;
						};

						if (!existingSpike || existingSpike.length === 0) {
							alertInserts.push({
								user_id: igComp.user_id,
								competitor_id: igComp.id,
								alert_type: "growth_spike",
								message: `@${igComp.username} grew ${Math.round(growthPct)}% in the last 7 days!`,
								metadata: {
									growthPct: Math.round(growthPct * 100) / 100,
									prevFollowers: prev,
									currentFollowers: followers,
								},
							});
						}
					}
				}
			}

			if (alertInserts.length > 0) {
				const { error: alertError } = await getSupabase()
					.from("competitor_alerts")
					// biome-ignore lint/suspicious/noExplicitAny: Supabase insert payload shape mismatch with generated types
					.insert(alertInserts as any);
				if (alertError) {
					logger.error(
						"[daily-intelligence] Phase 4: competitor alert insert error",
						{ error: alertError.message },
					);
				}
			}
		}
	}

	// Clean up old snapshots
	if (hasTimeBudget(startTime)) {
		const retentionDate = new Date();
		retentionDate.setDate(retentionDate.getDate() - SNAPSHOT_RETENTION_DAYS);
		const retentionDateStr = retentionDate.toISOString().split("T")[0]!;

		const { count: deletedCount, error: deleteError } = (await getSupabase()
			.from("competitor_snapshots")
			.delete({ count: "exact" })
			.lt("snapshot_date", retentionDateStr)) as unknown as {
			count: number | null;
			error: { message: string } | null;
		};

		if (deleteError) {
			logger.error("[daily-intelligence] Phase 4: snapshot cleanup error", {
				error: deleteError.message,
			});
		} else {
			stats.oldSnapshotsDeleted = deletedCount || 0;
		}
	}

	logger.info("[daily-intelligence] Phase 4: competitor-snapshots complete", {
		...stats,
		errors: stats.errors.length,
	});

	return {
		status: "success",
		durationMs: Date.now() - phaseStart,
		detail: {
			totalCompetitors: stats.totalCompetitors,
			refreshed: stats.refreshed,
			skipped: stats.skipped,
			failed: stats.failed,
			snapshotsCreated: stats.snapshotsCreated,
			oldSnapshotsDeleted: stats.oldSnapshotsDeleted,
			errorCount: stats.errors.length,
		},
	};
}

// ============================================================================
// Phase 5: Social Listening Scan (#501 — automated, not just on-demand)
// ============================================================================

async function phaseSocialListeningScan(
	startTime: number,
): Promise<PhaseResult> {
	const phaseStart = Date.now();
	logger.info("[daily-intelligence] Phase 5: social-listening-scan started");

	const stats = {
		alertsProcessed: 0,
		resultsFound: 0,
		errors: 0,
	};

	try {
		// Get all active listening alerts
		const { data: alerts, error: alertsError } = await db()
			.from("listening_alerts")
			.select("id, user_id, workspace_id, keyword, is_active")
			.eq("is_active", true);

		if (alertsError) {
			throw new Error(
				`Failed to fetch listening alerts: ${String(alertsError)}`,
			);
		}

		if (!alerts || alerts.length === 0) {
			logger.info("[daily-intelligence] Phase 5: no active listening alerts");
			return {
				status: "success",
				durationMs: Date.now() - phaseStart,
				detail: { alertsProcessed: 0 },
			};
		}

		logger.info("[daily-intelligence] Phase 5: found active alerts", {
			count: alerts.length,
		});

		// Group alerts by user_id to batch process
		const alertsByUser = new Map<string, typeof alerts>();
		for (const alert of alerts) {
			const uid = alert.user_id as string;
			if (!uid) continue;
			const userAlerts = alertsByUser.get(uid) || [];
			userAlerts.push(alert);
			alertsByUser.set(uid, userAlerts);
		}

		// Process each user's alerts by calling the monitor logic inline
		// (We can't call the API endpoint directly from a cron, so we replicate
		// the core keyword scanning logic from api/listening/monitor.ts)
		const { analyzeSentiment } = await import("../sentiment.js");

		for (const [userId, userAlerts] of alertsByUser) {
			if (!hasTimeBudget(startTime)) {
				logger.warn("[daily-intelligence] Phase 5: time budget exhausted", {
					elapsed: elapsed(startTime),
				});
				break;
			}

			// Get user's account IDs for scoping
			const { data: userAccounts } = await db()
				.from("accounts")
				.select("id")
				.eq("user_id", userId);
			const { data: userIgAccounts } = await db()
				.from("instagram_accounts")
				.select("id")
				.eq("user_id", userId);
			const userAccountIds = (userAccounts || []).map(
				(a: { id: string }) => a.id,
			);
			const userIgAccountIds = (userIgAccounts || []).map(
				(a: { id: string }) => a.id,
			);

			for (const alert of userAlerts) {
				if (!hasTimeBudget(startTime)) break;

				try {
					const keyword = alert.keyword.toLowerCase();
					const escapedKeyword = keyword.replace(/[%_\\]/g, "\\$&");
					let resultCount = 0;

					// Scan ig_comments
					if (userIgAccountIds.length > 0) {
						const { count } = await dbAny()
							.from("ig_comments")
							.select("id", { count: "exact", head: true })
							.in("account_id", userIgAccountIds)
							.ilike("text", `%${escapedKeyword}%`)
							.gte(
								"timestamp",
								new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
							);
						resultCount += count || 0;
					}

					// Scan ig_mentions
					if (userIgAccountIds.length > 0) {
						const { count } = await dbAny()
							.from("ig_mentions")
							.select("id", { count: "exact", head: true })
							.in("account_id", userIgAccountIds)
							.ilike("text", `%${escapedKeyword}%`)
							.gte(
								"timestamp",
								new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
							);
						resultCount += count || 0;
					}

					// Scan threads webhook events
					if (userAccountIds.length > 0) {
						const { count } = await dbAny()
							.from("threads_webhook_events")
							.select("id", { count: "exact", head: true })
							.in("account_id", userAccountIds)
							.ilike("payload", `%${escapedKeyword}%`)
							.gte(
								"created_at",
								new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
							);
						resultCount += count || 0;
					}

					// Store result if matches found
					if (resultCount > 0) {
						const sentiment = analyzeSentiment(keyword);
						await db()
							.from("listening_results")
							.insert({
								alert_id: alert.id,
								user_id: userId,
								workspace_id: alert.workspace_id,
								match_count: resultCount,
								sentiment_score:
									(sentiment as unknown as Record<string, unknown>)?.score ??
									null,
								scanned_at: new Date().toISOString(),
								// biome-ignore lint/suspicious/noExplicitAny: Supabase insert payload shape mismatch with generated types
							} as any);
						stats.resultsFound += resultCount;
					}

					stats.alertsProcessed++;
				} catch (alertErr) {
					logger.warn("[daily-intelligence] Phase 5: alert scan failed", {
						alertId: alert.id,
						error:
							alertErr instanceof Error ? alertErr.message : String(alertErr),
					});
					stats.errors++;
				}
			}
		}

		logger.info(
			"[daily-intelligence] Phase 5: social-listening-scan complete",
			stats,
		);
		return {
			status: "success",
			durationMs: Date.now() - phaseStart,
			detail: stats as unknown as Record<string, unknown>,
		};
	} catch (err) {
		logger.error("[daily-intelligence] Phase 5: social-listening-scan failed", {
			error: err instanceof Error ? err.message : String(err),
		});
		throw err;
	}
}

// ============================================================================
// Main Handler
// ============================================================================

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const supabase = db();

	const lockResult = await withCronLock(
		supabase,
		"daily-intelligence",
		async () => {
			return trackCronRun(supabase, "daily-intelligence", async () => {
				const startTime = Date.now();
				const phases: Record<string, PhaseResult> = {};
				let totalItemsProcessed = 0;

				// Phase 1: Power User Scoring (pure DB, fastest)
				if (hasTimeBudget(startTime)) {
					try {
						phases.powerUserScoring = await phasePowerUserScoring();
						totalItemsProcessed +=
							(phases.powerUserScoring.detail?.usersScored as number) || 0;
					} catch (err) {
						phases.powerUserScoring = {
							status: "error",
							durationMs: Date.now() - startTime,
							error: err instanceof Error ? err.message : String(err),
						};
						logger.error("[daily-intelligence] Phase 1 failed", {
							error: phases.powerUserScoring.error,
						});
					}
				} else {
					phases.powerUserScoring = { status: "skipped", durationMs: 0 };
				}

				// Phase 2: Quick Win Monitor (DB + Redis)
				if (hasTimeBudget(startTime)) {
					try {
						phases.quickwinMonitor = await phaseQuickwinMonitor();
						totalItemsProcessed +=
							(phases.quickwinMonitor.detail?.regressionsDetected as number) ||
							0;
						totalItemsProcessed +=
							(phases.quickwinMonitor.detail?.remindersSent as number) || 0;
					} catch (err) {
						phases.quickwinMonitor = {
							status: "error",
							durationMs: Date.now() - startTime,
							error: err instanceof Error ? err.message : String(err),
						};
						logger.error("[daily-intelligence] Phase 2 failed", {
							error: phases.quickwinMonitor.error,
						});
					}
				} else {
					phases.quickwinMonitor = { status: "skipped", durationMs: 0 };
				}

				// Phase 3: Discover Refresh — removed (saved_searches tables dropped)
				phases.discoverRefresh = { status: "skipped", durationMs: 0 };

				// Phase 4: Competitor Snapshots (external API, heaviest — last)
				if (hasTimeBudget(startTime)) {
					try {
						phases.competitorSnapshots =
							await phaseCompetitorSnapshots(startTime);
						totalItemsProcessed +=
							(phases.competitorSnapshots.detail?.snapshotsCreated as number) ||
							0;
					} catch (err) {
						phases.competitorSnapshots = {
							status: "error",
							durationMs: Date.now() - startTime,
							error: err instanceof Error ? err.message : String(err),
						};
						logger.error("[daily-intelligence] Phase 4 failed", {
							error: phases.competitorSnapshots.error,
						});
						try {
							const { captureServerException } = await import(
								"../sentryServer.js"
							);
							await captureServerException(err, {
								cronJob: "daily-intelligence-competitors",
							});
						} catch {
							/* sentry best-effort */
						}
						alertCronFailure(
							"daily-intelligence-competitors",
							phases.competitorSnapshots.error || "unknown",
						);
					}
				} else {
					phases.competitorSnapshots = { status: "skipped", durationMs: 0 };
				}

				// Phase 5: Social Listening Scan (#501 — automated keyword monitoring)
				if (hasTimeBudget(startTime)) {
					try {
						phases.socialListeningScan =
							await phaseSocialListeningScan(startTime);
						totalItemsProcessed +=
							(phases.socialListeningScan.detail?.alertsProcessed as number) ||
							0;
					} catch (err) {
						phases.socialListeningScan = {
							status: "error",
							durationMs: Date.now() - startTime,
							error: err instanceof Error ? err.message : String(err),
						};
						logger.error("[daily-intelligence] Phase 5 failed", {
							error: phases.socialListeningScan.error,
						});
					}
				} else {
					phases.socialListeningScan = { status: "skipped", durationMs: 0 };
				}

				const totalDurationMs = Date.now() - startTime;
				logger.info("[daily-intelligence] All phases complete", {
					totalDurationMs,
					totalItemsProcessed,
					phases: Object.fromEntries(
						Object.entries(phases).map(([k, v]) => [
							k,
							{ status: v.status, durationMs: v.durationMs },
						]),
					),
				});

				return {
					itemsProcessed: totalItemsProcessed,
					metadata: {
						totalDurationMs,
						phases,
					} as Record<string, unknown>,
				};
			});
		},
	);

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res.status(200).json({ success: true });
}
