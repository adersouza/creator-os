// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Periodic Sync Cron — consolidated handler running every 6 hours
 *
 * Merges two formerly separate cron jobs into sequential phases:
 *   Phase 1: Social Listening (pure DB keyword search, ~30-60s)
 *   Phase 2: Refresh Competitor Posts (Threads API fetches, ~120-270s)
 *
 * Uses a shared time budget (290s max) so Phase 2 gets whatever remains
 * after Phase 1 completes.
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
import {
	classifyCompetitorPattern,
	evaluateCompetitorMetricQuality,
} from "../handlers/competitors/metricQuality.js";
import { logger } from "../logger.js";
import { isAuthError as isMetaAuthError } from "../metaErrors.js";
import { getSupabase, getSupabaseAny } from "../supabase.js";

// ============================================================================
// Row / API Types
// ============================================================================

interface IgCommentRow {
	id: string;
	text: string;
	username: string;
	timestamp: string;
}

interface IgMentionRow {
	id: string;
	caption: string;
	username: string;
	timestamp: string;
}

interface ThreadsWebhookEventRow {
	id: string;
	payload: { text?: string | undefined; message?: string | undefined; from?: { username?: string | undefined } | undefined };
	created_at: string;
}

interface CompetitorRow {
	id: string;
	username: string;
	user_id: string;
	sync_status: string | null;
	consecutive_failures: number | null;
	last_synced_at: string | null;
}

interface SamplePost {
	id: string;
	text: string;
	author: string;
	timestamp: string;
	source: string;
}

interface PhaseMetadata {
	status: string;
	durationMs?: number | undefined;
	alertsProcessed?: number | undefined;
	competitorsProcessed?: number | undefined;
	totalPostsFetched?: number | undefined;
	errors?: number | undefined;
	rateLimited?: number | undefined;
	skippedInactive?: number | undefined;
	skippedTimeBudget?: boolean | undefined;
	error?: string | undefined;
	reason?: string | undefined;
	remainingMs?: number | undefined;
}

function isUnsupportedCompetitorProfileRequest(errorBody: string): boolean {
	return (
		errorBody.includes('"code":100') &&
		errorBody.toLowerCase().includes("unsupported request - method type: get")
	);
}

interface CronMetadata {
	phases: {
		socialListening?: PhaseMetadata | undefined;
		refreshCompetitorPosts?: PhaseMetadata | undefined;
	};
	totalDurationMs?: number | undefined;
}

// ============================================================================
// Configuration
// ============================================================================

export const config = {
	maxDuration: 300, // 5 minutes max (Vercel limit)
};

const MAX_EXECUTION_TIME = 290_000; // 290s — leave 10s headroom
const JOB_NAME = "periodic-sync";

// Competitor refresh constants
const BATCH_SIZE = 5;
const BATCH_DELAY_MS = 500;
const RATE_LIMIT_BACKOFF_MS = 5_000;
const MAX_COMPETITORS_PER_RUN = 50;
/** Minimum hours between scrapes for the same competitor. 6h cron × 2 = every 12h effective. */
const MIN_SCRAPE_INTERVAL_HOURS = 12;

// ============================================================================
// Global Token Pool (same pattern as daily-intelligence Phase 4)
// ============================================================================

interface PoolToken {
	accountId: string;
	token: string;
}

/**
 * Build a global token pool from ALL accounts in the system.
 * Any valid Threads token can fetch any public profile's posts.
 * Sorted by last_synced_at DESC so healthiest tokens come first.
 *
 * token_expires_at is nullable — accounts from before the column was added
 * or accounts that haven't been refreshed may have NULL. Include them as
 * they may still have valid tokens.
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
		// Diagnostic: check how many accounts exist total to help debug
		const { count } = await getSupabase()
			.from("accounts")
			.select("id", { count: "exact", head: true })
			.not("threads_access_token_encrypted", "is", null)
			.eq("is_active", true);
		logger.error("[periodic-sync] No accounts with valid tokens in pool", {
			totalActiveWithTokens: count ?? 0,
			hint: "Check needs_reauth flags and token_expires_at values",
		});
		return [];
	}

	const pool: PoolToken[] = [];
	let decryptionFailures = 0;
	let nullExpiry = 0;

	for (const account of accounts) {
		if (!account.token_expires_at) nullExpiry++;
		try {
			const token = decrypt(account.threads_access_token_encrypted);
			pool.push({ accountId: account.id, token });
		} catch {
			decryptionFailures++;
		}
	}

	if (decryptionFailures > 0 || nullExpiry > 0) {
		logger.warn("[periodic-sync] Token pool diagnostics", {
			accountsQueried: accounts.length,
			decryptionFailures,
			nullExpiryAccounts: nullExpiry,
			poolSize: pool.length,
		});
	}

	return pool;
}

// ============================================================================
// Phase 1: Social Listening
// ============================================================================

export async function runSocialListening(
	db: ReturnType<typeof getSupabase>,
): Promise<{ alertsProcessed: number; error?: string | undefined }> {
	// Fetch all active alerts
	const { data: alerts, error } = await db
		.from("listening_alerts")
		.select("*")
		.eq("is_active", true);

	if (error || !alerts?.length) {
		return { alertsProcessed: 0 };
	}

	let processed = 0;
	const threadsUserIdsByUser = new Map<string, string[]>();
	const igUserIdsByUser = new Map<string, string[]>();

	// Only search content from the last 7 days
	const cutoffDate = new Date();
	cutoffDate.setDate(cutoffDate.getDate() - 7);
	const cutoffISO = cutoffDate.toISOString();

	for (const alert of alerts) {
		try {
			if (!alert.user_id) {
				logger.warn(
					"[periodic-sync] Skipping listening alert without user_id",
					{
						alertId: alert.id,
					},
				);
				continue;
			}

			let userThreadsUserIds = threadsUserIdsByUser.get(alert.user_id);
			if (!userThreadsUserIds) {
				const { data: userAccounts } = await db
					.from("accounts")
					.select("threads_user_id")
					.eq("user_id", alert.user_id);
				userThreadsUserIds = (userAccounts || [])
					.map((account) => account.threads_user_id)
					.filter(Boolean) as string[];
				threadsUserIdsByUser.set(alert.user_id, userThreadsUserIds);
			}

			let userIgUserIds = igUserIdsByUser.get(alert.user_id);
			if (!userIgUserIds) {
				const { data: userIgAccounts } = await db
					.from("instagram_accounts")
					.select("instagram_user_id")
					.eq("user_id", alert.user_id);
				userIgUserIds = (userIgAccounts || [])
					.map((account) => account.instagram_user_id)
					.filter(Boolean);
				igUserIdsByUser.set(alert.user_id, userIgUserIds);
			}

			const keyword = alert.keyword.toLowerCase();
			const escapedKeyword = keyword.replace(/[%_\\]/g, "\\$&");
			let resultCount = 0;
			const samplePosts: SamplePost[] = [];

			// Search ig_comments (last 7 days)
			const { data: igCommentsRaw } =
				userIgUserIds.length > 0
					? await db
							.from("ig_comments")
							.select("id, text, username, timestamp")
							.in("ig_user_id", userIgUserIds)
							.ilike("text", `%${escapedKeyword}%`)
							.gte("timestamp", cutoffISO)
							.order("timestamp", { ascending: false })
							.limit(20)
					: { data: null };
			const igComments = igCommentsRaw as unknown as IgCommentRow[] | null;

			if (igComments?.length) {
				resultCount += igComments.length;
				samplePosts.push(
					...igComments.slice(0, 3).map((c: IgCommentRow) => ({
						id: c.id,
						text: c.text,
						author: c.username,
						timestamp: c.timestamp,
						source: "ig_comment",
					})),
				);
			}

			// Search ig_mentions (last 7 days)
			const { data: igMentionsRaw } =
				userIgUserIds.length > 0
					? await db
							.from("ig_mentions")
							.select("id, caption, username, timestamp")
							.in("ig_account_id", userIgUserIds)
							.ilike("caption", `%${escapedKeyword}%`)
							.gte("timestamp", cutoffISO)
							.order("timestamp", { ascending: false })
							.limit(10)
					: { data: null };
			const igMentions = igMentionsRaw as unknown as IgMentionRow[] | null;

			if (igMentions?.length) {
				resultCount += igMentions.length;
				samplePosts.push(
					...igMentions.slice(0, 2).map((m: IgMentionRow) => ({
						id: m.id,
						text: m.caption,
						author: m.username,
						timestamp: m.timestamp,
						source: "ig_mention",
					})),
				);
			}

			// Search threads_webhook_events (last 7 days)
			const { data: threadEventsRaw } =
				userThreadsUserIds.length > 0
					? await getSupabaseAny()
							.from("threads_webhook_events")
							.select("id, payload, created_at")
							.eq("processed", true)
							.in("threads_user_id", userThreadsUserIds)
							.gte("created_at", cutoffISO)
							.order("created_at", { ascending: false })
							.limit(50)
					: { data: null };
			const threadEvents = threadEventsRaw as unknown as
				| ThreadsWebhookEventRow[]
				| null;

			const matchingThreads = (threadEvents || []).filter(
				(e: ThreadsWebhookEventRow) => {
					const text = e.payload?.text || e.payload?.message || "";
					return text.toLowerCase().includes(keyword);
				},
			);

			if (matchingThreads.length) {
				resultCount += matchingThreads.length;
				samplePosts.push(
					...matchingThreads.slice(0, 2).map((e: ThreadsWebhookEventRow) => ({
						id: e.id,
						text: e.payload?.text || "",
						author: e.payload?.from?.username || "unknown",
						timestamp: e.created_at,
						source: "threads_event",
					})),
				);
			}

			// Insert result
			const { error: insertErr } = await db.from("listening_results").insert({
				alert_id: alert.id,
				workspace_id: alert.workspace_id,
				keyword: alert.keyword,
				source: "combined",
				result_count: resultCount,
				sentiment_breakdown: { positive: 0, neutral: resultCount, negative: 0 },
				sample_posts: samplePosts.slice(
					0,
					5,
				) as unknown as import("../../../types/supabase.js").Json,
			});
			if (insertErr) {
				logger.error("[periodic-sync] Failed to insert listening_results", {
					alertId: alert.id,
					keyword: alert.keyword,
					error: insertErr.message,
				});
			}

			// Check threshold / spike
			let shouldNotify = false;
			if (
				alert.alert_type === "threshold" &&
				resultCount >= (alert.threshold_value ?? 0)
			) {
				shouldNotify = true;
			} else if (alert.alert_type === "spike") {
				const { data: prevResults } = await db
					.from("listening_results")
					.select("result_count")
					.eq("alert_id", alert.id)
					.order("checked_at", { ascending: false })
					.limit(2);

				if (prevResults && prevResults.length >= 2) {
					const prevCount = prevResults[1]!.result_count || 0;
					if (prevCount > 0 && resultCount >= prevCount * 2) {
						shouldNotify = true;
					}
				}
			}

			if (shouldNotify && alert.user_id) {
				await createNotification({
					userId: alert.user_id,
					type: "listening_alert",
					title: `Listening Alert: "${alert.keyword}"`,
					message: `Found ${resultCount} mentions (${alert.alert_type} trigger)`,
					data: { alertId: alert.id, keyword: alert.keyword, resultCount },
				});

				await db
					.from("listening_alerts")
					.update({ last_triggered_at: new Date().toISOString() })
					.eq("id", alert.id);
			}

			// Update last_checked_at
			await db
				.from("listening_alerts")
				.update({ last_checked_at: new Date().toISOString() })
				.eq("id", alert.id);

			processed++;
		} catch (err) {
			logger.error("[periodic-sync] Social listening alert failed", {
				alertId: alert.id,
				error: String(err),
			});
		}
	}

	return { alertsProcessed: processed };
}

// ============================================================================
// Phase 2: Refresh Competitor Posts
// ============================================================================

async function fetchAndStorePostsForCompetitor(
	competitorId: string,
	username: string,
	accessToken: string,
	userId: string,
): Promise<{
	count: number;
	rateLimited: boolean;
	accountStatus?: string | undefined;
	tokenAuth?: boolean | undefined;
}> {
	const response = await fetch(
		// NOTE: like_count, reply_count, repost_count, views are undocumented on media objects
		// but returned by the API in practice. If they stop working, engagement will default to 0.
		`https://graph.threads.net/v1.0/profile_posts?username=${encodeURIComponent(username)}&fields=id,text,media_url,media_type,permalink,timestamp,like_count,reply_count,repost_count,views,topic_tag&limit=25`,
		{
			headers: { Authorization: `Bearer ${accessToken}` },
			signal: AbortSignal.timeout(10_000),
		},
	);

	if (!response.ok) {
		const errorBody = await response.text().catch(() => "");
		const unsupportedProfileRequest =
			isUnsupportedCompetitorProfileRequest(errorBody);
		// Error 801 = "Follower Count Too Low" — competitor-level, not a token issue
		// Error 100 "Unsupported request - method type: get" behaves like an
		// unsupported/dead profile lookup in this endpoint, not a token issue.
		const isCompetitorLevelError =
			errorBody.includes('"code":801') || unsupportedProfileRequest;
		// HTTP 401 is canonical auth failure; otherwise classify the parsed Meta
		// error envelope so transient 500s (code=1 OAuthException) don't trigger
		// fleet-wide token rotation. Past local helper checked impossible
		// `response.status === 190` (190 is a JSON code, never an HTTP status).
		let parsedMetaError: Record<string, unknown> | null = null;
		try {
			const parsed = JSON.parse(errorBody);
			if (parsed && typeof parsed === "object" && parsed.error) {
				parsedMetaError = parsed.error as Record<string, unknown>;
			}
		} catch {
			// errorBody isn't JSON — fall through to message-only classification.
		}
		const classifierInput =
			parsedMetaError !== null ? parsedMetaError : errorBody;
		const isAuthError =
			!isCompetitorLevelError &&
			(response.status === 401 || isMetaAuthError(classifierInput));
		const accountStatus = unsupportedProfileRequest
			? "deleted"
			: detectAccountStatus(response.status, errorBody);

		if (unsupportedProfileRequest) {
			logger.warn("[periodic-sync] Competitor profile lookup unsupported", {
				username,
				status: response.status,
				accountStatus,
				errorBody: errorBody.slice(0, 200),
			});
		} else {
			logger.error("Failed to fetch competitor posts", {
				username,
				status: response.status,
				accountStatus,
				isAuthError,
				errorBody: errorBody.slice(0, 200),
			});
		}

		// On auth errors, signal token rotation — don't blame the competitor
		if (isAuthError) {
			return {
				count: 0,
				rateLimited: false,
				accountStatus: "error",
				tokenAuth: false,
			};
		}

		if (accountStatus) {
			await updateCompetitorSyncStatus(competitorId, accountStatus);
		}

		return {
			count: 0,
			rateLimited: accountStatus === "rate_limited",
			accountStatus: accountStatus || "error",
			tokenAuth: true,
		};
	}

	const data = await response.json();
	const posts = data.data || [];

	if (posts.length === 0) return { count: 0, rateLimited: false };

	// Mark as active on success
	await updateCompetitorSyncStatus(competitorId, "active");

	const now = new Date().toISOString();
	let storedCount = 0;

	for (const post of posts) {
		if (!post.text) continue;

		const score =
			(post.like_count || 0) * 1 +
			(post.reply_count || 0) * 3 +
			(post.repost_count || 0) * 2 +
			(post.views || 0) * 0.01;
		const metricDecision = evaluateCompetitorMetricQuality({
			platform: "threads",
			viewCount: post.views,
			likeCount: post.like_count,
			replyCount: post.reply_count,
			repostCount: post.repost_count,
			engagementScore: score,
			checkedAt: now,
		});
		const pattern = classifyCompetitorPattern({
			content: post.text,
			topicTag: post.topic_tag,
			mediaType: post.media_type,
			publishedAt: post.timestamp,
			scrapedAt: now,
		});

		const { data: upserted, error } = await getSupabaseAny()
			.from("competitor_top_posts")
			.upsert(
				{
					competitor_id: competitorId,
					threads_post_id: post.id,
					content: post.text,
					media_type: post.media_type,
					media_url: post.media_url || null,
					permalink: post.permalink,
					like_count: post.like_count || 0,
					reply_count: post.reply_count || 0,
					repost_count: post.repost_count || 0,
					view_count: post.views || 0,
					engagement_score: score,
					metric_source: metricDecision.metric_source,
					metric_quality: metricDecision.metric_quality,
					metric_quality_reason: metricDecision.metric_quality_reason,
					last_metric_checked_at: metricDecision.last_metric_checked_at,
					...pattern,
					published_at: post.timestamp,
					competitor_username: post.username || username,
					topic_tag: post.topic_tag || null,
					scraped_at: now,
					user_id: userId,
				},
				{ onConflict: "user_id,threads_post_id" },
			)
			.select("id")
			.maybeSingle();

		if (error) {
			logger.warn("[periodic-sync] Failed to upsert competitor post", {
				competitorId,
				username,
				threadsPostId: post.id,
				error: error.message,
				code: error.code,
			});
		} else {
			storedCount++;
			const postId = (upserted as { id?: string | null } | null)?.id ?? null;
			if (postId) {
				const { error: snapshotError } = await getSupabaseAny()
					.from("competitor_post_metric_snapshots")
					.insert({
						competitor_post_id: postId,
						competitor_id: competitorId,
						user_id: userId,
						threads_post_id: post.id,
						platform: "threads",
						metric_source: metricDecision.metric_source,
						metric_quality: metricDecision.metric_quality,
						last_metric_checked_at: metricDecision.last_metric_checked_at,
						views: post.views || 0,
						likes: post.like_count || 0,
						replies: post.reply_count || 0,
						reposts: post.repost_count || 0,
						engagement_score: score,
						scraped_at: now,
						raw_metrics: {
							source: "periodic_profile_posts",
							metric_quality_reason: metricDecision.metric_quality_reason,
						},
					});
				if (snapshotError) {
					logger.warn("[periodic-sync] Failed to insert metric snapshot", {
						competitorId,
						username,
						threadsPostId: post.id,
						error: snapshotError.message,
					});
				}
			}
		}
	}

	return {
		count: storedCount,
		rateLimited: false,
		accountStatus: "active",
		tokenAuth: true,
	};
}

export async function runRefreshCompetitorPosts(startTime: number): Promise<{
	competitorsProcessed: number;
	totalPostsFetched: number;
	errors: number;
	rateLimited: number;
	skippedInactive: number;
	skippedTimeBudget: boolean;
	error?: string | undefined;
}> {
	const stats = {
		competitorsProcessed: 0,
		totalPostsFetched: 0,
		errors: 0,
		rateLimited: 0,
		skippedInactive: 0,
		skippedTimeBudget: false,
	};

	// Smart rotation: order by last_synced_at ASC (least recently synced first)
	const { data: allCompetitors, error: compError } = await getSupabase()
		.from("competitors")
		.select(
			"id, username, user_id, sync_status, consecutive_failures, last_synced_at",
		)
		.or(
			"sync_status.is.null,sync_status.eq.active,sync_status.eq.error,sync_status.eq.rate_limited",
		)
		.order("last_synced_at", { ascending: true, nullsFirst: true })
		.limit(MAX_COMPETITORS_PER_RUN);

	if (compError) {
		logger.error("Competitor posts query error", { error: String(compError) });
		throw compError;
	}

	if (!allCompetitors || allCompetitors.length === 0) {
		logger.info("No competitors found for post refresh");
		return stats;
	}

	// Filter out competitors with too many consecutive failures
	const eligibleCompetitors = (allCompetitors as CompetitorRow[]).filter(
		(c: CompetitorRow) => {
			if ((c.consecutive_failures || 0) > 10 && c.sync_status === "deleted") {
				stats.skippedInactive++;
				return false;
			}
			// #504: Auto-disable competitors after 15 consecutive failures
			if ((c.consecutive_failures || 0) >= 15) {
				stats.skippedInactive++;
				// Mark as disabled so user sees it in UI
				getSupabaseAny()
					.from("competitors")
					.update({
						sync_status: "disabled",
						updated_at: new Date().toISOString(),
					})
					.eq("id", c.id)
					.then(() => {
						logger.info(
							"[periodic-sync] Auto-disabled competitor after 15 failures",
							{
								competitorId: c.id,
								username: c.username,
								failures: c.consecutive_failures,
							},
						);
					});
				return false;
			}
			// Rate-limited competitors: only retry if last sync was >1 hour ago
			if (c.sync_status === "rate_limited" && c.last_synced_at) {
				const lastSync = new Date(c.last_synced_at).getTime();
				if (Date.now() - lastSync < 60 * 60 * 1000) {
					stats.skippedInactive++;
					return false;
				}
			}
			// Skip if scraped within MIN_SCRAPE_INTERVAL_HOURS (reduces from 6h → 12h effective)
			if (c.last_synced_at) {
				const hoursSince =
					(Date.now() - new Date(c.last_synced_at).getTime()) /
					(60 * 60 * 1000);
				if (hoursSince < MIN_SCRAPE_INTERVAL_HOURS) {
					stats.skippedInactive++;
					return false;
				}
			}
			return true;
		},
	);

	logger.info("Found competitors for post refresh", {
		total: allCompetitors.length,
		eligible: eligibleCompetitors.length,
		skippedInactive: stats.skippedInactive,
	});

	if (eligibleCompetitors.length === 0) {
		return stats;
	}

	// Build global token pool — any valid token can look up any public profile's posts
	const pool = await getGlobalTokenPool();

	if (pool.length === 0) {
		logger.error(
			"[periodic-sync] Phase 2: no tokens available, skipping all competitors",
		);
		stats.errors = eligibleCompetitors.length;
		return stats;
	}

	logger.info("[periodic-sync] Phase 2: token pool ready", {
		poolSize: pool.length,
		competitors: eligibleCompetitors.length,
	});

	let poolIndex = 0;
	let poolExhausted = false;
	let globalRateLimited = false;

	// Process all competitors in batches (no per-user grouping needed with global pool)
	for (let i = 0; i < eligibleCompetitors.length; i += BATCH_SIZE) {
		if (globalRateLimited || poolExhausted) break;

		// Check time budget before each batch
		if (Date.now() - startTime > MAX_EXECUTION_TIME - 20_000) {
			logger.warn("Time budget exhausted for competitor refresh", {
				elapsed: Date.now() - startTime,
				processed: stats.competitorsProcessed,
			});
			stats.skippedTimeBudget = true;
			break;
		}

		const batch = eligibleCompetitors.slice(i, i + BATCH_SIZE);

		// Process batch sequentially to share pool index state across requests
		for (const comp of batch) {
			if (poolExhausted || globalRateLimited) {
				stats.errors++;
				stats.competitorsProcessed++;
				continue;
			}

			let result: {
				count: number;
				rateLimited: boolean;
				accountStatus?: string | undefined;
				tokenAuth?: boolean | undefined;
			} | null = null;
			let succeeded = false;

			// Try with current token, rotate on auth failure
			while (poolIndex < pool.length) {
				try {
					result = await fetchAndStorePostsForCompetitor(
						comp.id,
						comp.username,
						pool[poolIndex]!.token,
						comp.user_id,
					);
				} catch (_error) {
					stats.errors++;
					stats.competitorsProcessed++;
					result = null;
					break;
				}

				if (result.tokenAuth === false) {
					// Token expired/invalid — rotate to next token
					logger.warn("[periodic-sync] Token expired, rotating", {
						accountId: pool[poolIndex]!.accountId,
						poolIndex,
						poolSize: pool.length,
						competitor: comp.username,
					});
					poolIndex++;
					continue; // Try next token
				}

				// Token was fine (success or competitor-specific error)
				succeeded = true;
				break;
			}

			if (poolIndex >= pool.length) {
				poolExhausted = true;
				logger.error("[periodic-sync] All tokens in pool exhausted");
				stats.errors++;
				stats.competitorsProcessed++;
				continue;
			}

			if (!succeeded || !result) {
				stats.competitorsProcessed++;
				continue;
			}

			stats.competitorsProcessed++;
			if (result.rateLimited) {
				stats.rateLimited++;
				if (stats.rateLimited >= 3) {
					logger.warn("Multiple rate limits hit, stopping refresh early");
					globalRateLimited = true;
				}
			} else {
				stats.totalPostsFetched += result.count;
			}
		}

		// Delay between batches
		const delay =
			stats.rateLimited > 0 ? RATE_LIMIT_BACKOFF_MS : BATCH_DELAY_MS;
		if (i + BATCH_SIZE < eligibleCompetitors.length) {
			await new Promise((r) => setTimeout(r, delay));
		}
	}

	logger.info("[periodic-sync] Phase 2: competitor refresh complete", {
		competitorsProcessed: stats.competitorsProcessed,
		totalPostsStored: stats.totalPostsFetched,
		errors: stats.errors,
		rateLimited: stats.rateLimited,
		skippedTimeBudget: stats.skippedTimeBudget,
		poolExhausted,
	});

	return stats;
}

// ============================================================================
// Main Handler
// ============================================================================

export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const supabase = getSupabase();
	const globalStart = Date.now();

	const lockResult = await withCronLock(supabase, JOB_NAME, async () => {
		return trackCronRun(supabase, JOB_NAME, async () => {
			const metadata: CronMetadata = {
				phases: {},
			};

			// ----------------------------------------------------------------
			// Phase 1: Social Listening (pure DB, faster)
			// ----------------------------------------------------------------
			let phase1Result: Awaited<ReturnType<typeof runSocialListening>> | null =
				null;

			try {
				logger.info("[periodic-sync] Phase 1: Social Listening — starting");
				const phase1Start = Date.now();
				phase1Result = await runSocialListening(supabase);
				const phase1Duration = Date.now() - phase1Start;

				metadata.phases.socialListening = {
					status: "completed",
					durationMs: phase1Duration,
					alertsProcessed: phase1Result.alertsProcessed,
				};

				logger.info("[periodic-sync] Phase 1: Social Listening — complete", {
					durationMs: phase1Duration,
					alertsProcessed: phase1Result.alertsProcessed,
				});
			} catch (err) {
				metadata.phases.socialListening = {
					status: "error",
					error: err instanceof Error ? err.message : String(err),
				};
				logger.error("[periodic-sync] Phase 1: Social Listening — failed", {
					error: String(err),
				});
			}

			// ----------------------------------------------------------------
			// Phase 2: Refresh Competitor Posts (external API, heavier)
			// ----------------------------------------------------------------
			let phase2Result: Awaited<
				ReturnType<typeof runRefreshCompetitorPosts>
			> | null = null;

			const elapsedSoFar = Date.now() - globalStart;
			const remainingBudget = MAX_EXECUTION_TIME - elapsedSoFar;

			if (remainingBudget < 30_000) {
				// Less than 30s remaining — skip Phase 2
				metadata.phases.refreshCompetitorPosts = {
					status: "skipped",
					reason: "insufficient_time_budget",
					remainingMs: remainingBudget,
				};
				logger.warn(
					"[periodic-sync] Phase 2: Skipped — insufficient time budget",
					{
						remainingMs: remainingBudget,
					},
				);
			} else {
				try {
					logger.info(
						"[periodic-sync] Phase 2: Refresh Competitor Posts — starting",
						{
							remainingBudgetMs: remainingBudget,
						},
					);
					const phase2Start = Date.now();
					phase2Result = await runRefreshCompetitorPosts(globalStart);
					const phase2Duration = Date.now() - phase2Start;

					metadata.phases.refreshCompetitorPosts = {
						status: "completed",
						durationMs: phase2Duration,
						competitorsProcessed: phase2Result.competitorsProcessed,
						totalPostsFetched: phase2Result.totalPostsFetched,
						errors: phase2Result.errors,
						rateLimited: phase2Result.rateLimited,
						skippedInactive: phase2Result.skippedInactive,
						skippedTimeBudget: phase2Result.skippedTimeBudget,
					};

					logger.info(
						"[periodic-sync] Phase 2: Refresh Competitor Posts — complete",
						{
							durationMs: phase2Duration,
							...phase2Result,
						},
					);
				} catch (err) {
					metadata.phases.refreshCompetitorPosts = {
						status: "error",
						error: err instanceof Error ? err.message : String(err),
					};
					logger.error(
						"[periodic-sync] Phase 2: Refresh Competitor Posts — failed",
						{
							error: String(err),
						},
					);

					try {
						const { captureServerException } = await import(
							"../sentryServer.js"
						);
						await captureServerException(err, {
							cronJob: JOB_NAME,
							phase: "refresh-competitor-posts",
						});
					} catch (sentryErr) {
						logger.warn("[periodic-sync] Sentry capture failed", {
							originalError: err instanceof Error ? err.message : String(err),
							sentryError:
								sentryErr instanceof Error
									? sentryErr.message
									: String(sentryErr),
						});
					}
					alertCronFailure(
						JOB_NAME,
						err instanceof Error ? err.message : String(err),
					);
				}
			}

			metadata.totalDurationMs = Date.now() - globalStart;

			const totalItemsProcessed =
				(phase1Result?.alertsProcessed || 0) +
				(phase2Result?.totalPostsFetched || 0);

			return {
				itemsProcessed: totalItemsProcessed,
				metadata: metadata as unknown as Record<string, unknown>,
			};
		});
	});

	if (lockResult.skipped) {
		return res.status(200).json({ skipped: true });
	}

	return res
		.status(200)
		.json({ ok: true, result: (lockResult as { result: unknown }).result });
}
