// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Shared utilities for competitor handler modules.
 *
 * Contains token access, fallback retry logic,
 * and the fetchAndStorePosts helper used by multiple handlers.
 */

import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { calculateCompetitorEngagementRate } from "../../metricCalculators.js";
import { getRedis } from "../../redis.js";
import { withRetry } from "../../retryUtils.js";
import { getSupabase } from "../../supabase.js";
import {
	classifyCompetitorPattern,
	evaluateCompetitorMetricQuality,
	hasValidCompetitorEngagement,
} from "./metricQuality.js";

// Re-export verifyCompetitorOwnership from the central helpers so competitor
// handlers that already import from "./shared.js" can access it here.
export { verifyCompetitorOwnership } from "../helpers/verifyOwnership.js";

interface AccountTokenRow {
	id?: string | null;
	threads_access_token_encrypted: string | null;
	needs_reauth?: boolean | null;
	is_active?: boolean | null;
	status?: string | null;
	token_expires_at?: string | null;
}

interface CompetitorFailureRow {
	consecutive_failures?: number | null | undefined;
}

interface CompetitorCorpusMetaRow {
	user_id?: string | null | undefined;
	follower_count?: number | null | undefined;
}

interface PostWithScore {
	id: string;
	text?: string | null | undefined;
	like_count?: number | null | undefined;
	reply_count?: number | null | undefined;
	repost_count?: number | null | undefined;
	views?: number | null | undefined;
	media_type?: string | null | undefined;
	permalink?: string | null | undefined;
	timestamp?: string | null | undefined;
	username?: string | null | undefined;
}

interface EngagementRow {
	engagement_score?: number | null | undefined;
	metric_quality?: string | null | undefined;
}

interface IgMediaItem {
	like_count?: number | null | undefined;
	comments_count?: number | null | undefined;
}

// biome-ignore lint/suspicious/noExplicitAny: competitor corpus migrations move faster than generated DB types
export const db = (): any => getSupabase();

// ============================================================================
// Redis Queue Constants & Types
// ============================================================================

export const COMPETITOR_QUEUE_KEY = "competitor-sync-jobs:queue";
export const COMPETITOR_JOB_PREFIX = "competitor-sync-jobs:job:";
export const COMPETITOR_USER_JOB_PREFIX = "competitor-sync-jobs:user:";

export interface CompetitorSyncJob {
	id: string;
	userId: string;
	competitorIds: string[];
	status: "queued" | "processing" | "completed" | "failed";
	createdAt: number;
	progress?: { current: number; total: number } | undefined;
}

// ============================================================================
// Token Helpers
// ============================================================================

export async function getAllAccessTokens(userId: string): Promise<string[]> {
	const { data: accounts } = await db()
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

	if (!accounts?.length) return [];

	const tokens: string[] = [];
	for (const account of accounts as AccountTokenRow[]) {
		if (
			!account.threads_access_token_encrypted ||
			account.needs_reauth ||
			account.is_active === false ||
			account.status !== "active" ||
			(account.token_expires_at &&
				new Date(account.token_expires_at).getTime() <= Date.now())
		) {
			continue;
		}

		try {
			tokens.push(decrypt(account.threads_access_token_encrypted));
		} catch (err) {
			logger.warn("Skipping account with undecryptable Threads token", {
				accountId: account.id,
				error: err instanceof Error ? err.message : String(err),
			});
		}
	}

	return tokens;
}

/** Simple accessor for functions that don't need fallback */
export async function getAccessToken(userId: string): Promise<string | null> {
	const tokens = await getAllAccessTokens(userId);
	return tokens.length > 0 ? tokens[0]! : null;
}

/** Helper to try API call with multiple tokens until one works */
export async function tryWithFallbackTokens<T>(
	tokens: string[],
	apiCall: (
		token: string,
	) => Promise<{ data: T | null; error?: string | undefined }>,
): Promise<{ data: T | null; error?: string | undefined; tokenIndex: number }> {
	for (let i = 0; i < tokens.length; i++) {
		let result: { data: T | null; error?: string | undefined };
		try {
			result = await apiCall(tokens[i]!);
		} catch (err) {
			result = {
				data: null,
				error: err instanceof Error ? err.message : String(err),
			};
		}
		if (result.data && !result.error) {
			return { ...result, tokenIndex: i };
		}
		logger.info("Token failed, trying next", {
			tokenIndex: i + 1,
			totalTokens: tokens.length,
		});
	}
	return { data: null, error: "All account tokens failed", tokenIndex: -1 };
}

// ============================================================================
// Redis Queue Helpers
// ============================================================================

export async function getUserCurrentCompetitorJob(
	userId: string,
): Promise<CompetitorSyncJob | null> {
	const redis = getRedis();
	if (!redis) return null;
	const jobId = await redis.get(`${COMPETITOR_USER_JOB_PREFIX}${userId}`);
	if (!jobId) return null;
	const data = await redis.get(`${COMPETITOR_JOB_PREFIX}${jobId}`);
	if (!data) return null;
	return typeof data === "string"
		? JSON.parse(data)
		: (data as CompetitorSyncJob);
}

export async function queueCompetitorSyncJob(
	userId: string,
	competitorIds: string[],
): Promise<CompetitorSyncJob> {
	const redis = getRedis();
	if (!redis) throw new Error("Redis not configured");

	const jobId = `comp_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
	const job: CompetitorSyncJob = {
		id: jobId,
		userId,
		competitorIds,
		status: "queued",
		createdAt: Date.now(),
		progress: { current: 0, total: competitorIds.length },
	};

	await redis.set(`${COMPETITOR_JOB_PREFIX}${jobId}`, JSON.stringify(job), {
		ex: 3600,
	});
	await redis.set(`${COMPETITOR_USER_JOB_PREFIX}${userId}`, jobId, {
		ex: 3600,
	});
	await redis.lpush(COMPETITOR_QUEUE_KEY, jobId);
	await redis.expire(COMPETITOR_QUEUE_KEY, 86400).catch(() => {});

	return job;
}

// ============================================================================
// Post Fetching Helper
// ============================================================================

// ============================================================================
// Rate Limit & Account Status Helpers
// ============================================================================

export interface FetchResult {
	postsCount: number;
	rateLimited?: boolean | undefined;
	accountStatus?:
		| "active"
		| "private"
		| "deleted"
		| "rate_limited"
		| "error"
		| undefined;
}

/**
 * Detect account status from Meta API error responses.
 * Returns null if the response is successful (not an error).
 */
export function detectAccountStatus(
	statusCode: number,
	errorBody: string,
): "private" | "deleted" | "rate_limited" | "error" | null {
	if (statusCode === 429) return "rate_limited";
	if (statusCode === 404) return "deleted";

	// Meta API error codes
	const lower = errorBody.toLowerCase();
	if (lower.includes("user not found") || lower.includes("does not exist"))
		return "deleted";
	if (lower.includes("not authorized") || lower.includes("private"))
		return "private";
	if (lower.includes("rate limit") || lower.includes("too many"))
		return "rate_limited";
	if (lower.includes("application request limit")) return "rate_limited";

	if (statusCode >= 400) return "error";
	return null;
}

/**
 * Update competitor sync_status and consecutive_failures in the database.
 */
export async function updateCompetitorSyncStatus(
	competitorId: string,
	status: "active" | "private" | "deleted" | "rate_limited" | "error",
): Promise<void> {
	try {
		if (status === "active") {
			await db()
				.from("competitors")
				.update({
					sync_status: "active",
					consecutive_failures: 0,
					last_synced_at: new Date().toISOString(),
				})
				.eq("id", competitorId);
		} else {
			// Increment consecutive_failures
			const { data } = await db()
				.from("competitors")
				.select("consecutive_failures")
				.eq("id", competitorId)
				.maybeSingle();

			const failures =
				((data as CompetitorFailureRow)?.consecutive_failures || 0) + 1;
			await db()
				.from("competitors")
				.update({ sync_status: status, consecutive_failures: failures })
				.eq("id", competitorId);

			logger.warn("Competitor sync status changed", {
				competitorId,
				status,
				consecutiveFailures: failures,
			});
		}
	} catch (e) {
		logger.error("Failed to update competitor sync status", {
			competitorId,
			error: String(e),
		});
	}
}

/** Fetch and store posts for a Threads competitor */
export async function fetchAndStorePosts(
	competitorId: string,
	username: string,
	accessToken: string,
	userId?: string,
): Promise<FetchResult> {
	// Resolve user_id for the new column (defense-in-depth; falls back to
	// the EXISTS-chain RLS if lookup fails).
	let resolvedUserId = userId;
	let followerCountAtScrape: number | null = null;
	if (!resolvedUserId) {
		const { data: comp } = await db()
			.from("competitors")
			.select("user_id, follower_count")
			.eq("id", competitorId)
			.maybeSingle();
		const meta = comp as CompetitorCorpusMetaRow | null;
		resolvedUserId = meta?.user_id ?? undefined;
		followerCountAtScrape = meta?.follower_count ?? null;
	} else {
		const { data: comp } = await db()
			.from("competitors")
			.select("follower_count")
			.eq("id", competitorId)
			.maybeSingle();
		followerCountAtScrape =
			(comp as CompetitorCorpusMetaRow | null)?.follower_count ?? null;
	}

	// Use profile_posts endpoint - gets posts directly from user's profile
	// NOTE: like_count, reply_count, repost_count, views are undocumented on media objects
	// but returned by the API in practice. If they stop working, engagement will default to 0.
	const response = await withRetry(
		() =>
			fetch(
				`https://graph.threads.net/v1.0/profile_posts?username=${encodeURIComponent(username)}&fields=id,text,media_url,media_type,permalink,timestamp,like_count,reply_count,repost_count,views&limit=50`,
				{
					headers: { Authorization: `Bearer ${accessToken}` },
					signal: AbortSignal.timeout(10000),
				},
			),
		{ label: `competitorProfilePosts:${username}` },
	);

	if (!response.ok) {
		const errorBody = await response.text();
		const accountStatus = detectAccountStatus(response.status, errorBody);

		logger.error("profile_posts API error", {
			username,
			status: response.status,
			accountStatus,
			body: errorBody.slice(0, 200),
		});

		if (accountStatus) {
			await updateCompetitorSyncStatus(competitorId, accountStatus);
		}

		if (accountStatus === "rate_limited") {
			return { postsCount: 0, rateLimited: true, accountStatus };
		}

		throw new Error(
			`Threads API returned ${response.status} for @${username}: ${errorBody.slice(0, 200)}`,
		);
	}

	const data = (await response.json()) as {
		data?: PostWithScore[] | undefined;
	};
	const posts: PostWithScore[] = data.data || [];

	logger.info("Fetched posts for competitor", {
		username,
		postCount: posts.length,
	});

	if (posts.length === 0) {
		logger.warn("No posts returned for competitor", {
			username,
			hint: "profile may be private or below 1k followers",
		});
		return { postsCount: 0 };
	}

	// Mark competitor as active on successful fetch
	await updateCompetitorSyncStatus(competitorId, "active");

	const now = new Date().toISOString();

	// Calculate engagement scores and store
	let storedCount = 0;
	for (const post of posts) {
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
			followerCount: followerCountAtScrape,
			mediaType: post.media_type,
			publishedAt: post.timestamp,
			scrapedAt: now,
		});

		const { data: upserted, error } = await db()
			.from("competitor_top_posts")
			.upsert(
				{
					competitor_id: competitorId,
					...(resolvedUserId ? { user_id: resolvedUserId } : {}),
					threads_post_id: post.id,
					content: post.text || "",
					media_type: post.media_type,
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
					scraped_at: now,
					// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert
				} as any,
				{ onConflict: "user_id,threads_post_id" },
			)
			.select("id")
			.maybeSingle();

		if (error) {
			logger.error("Failed to upsert competitor post", {
				postId: post.id,
				username,
				error: error.message,
			});
		} else {
			storedCount++;
			const postId = (upserted as { id?: string | null } | null)?.id ?? null;
			if (postId) {
				const { error: snapshotError } = await db()
					.from("competitor_post_metric_snapshots")
					.insert({
						competitor_post_id: postId,
						competitor_id: competitorId,
						user_id: resolvedUserId,
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
						follower_count_at_scrape: followerCountAtScrape,
						scraped_at: now,
						raw_metrics: {
							source: "profile_posts",
							metric_quality_reason: metricDecision.metric_quality_reason,
						},
					});
				if (snapshotError) {
					logger.warn("Failed to insert competitor metric snapshot", {
						postId: post.id,
						username,
						error: snapshotError.message,
					});
				}
			}
		}
	}

	// Detect viral spikes for newly stored posts
	try {
		const postsWithScores = posts
			.filter((p: PostWithScore) => p.text)
			.map((p: PostWithScore) => {
				const engagementScore =
					(p.like_count || 0) * 1 +
					(p.reply_count || 0) * 3 +
					(p.repost_count || 0) * 2 +
					(p.views || 0) * 0.01;
				const metricDecision = evaluateCompetitorMetricQuality({
					platform: "threads",
					viewCount: p.views,
					likeCount: p.like_count,
					replyCount: p.reply_count,
					repostCount: p.repost_count,
					engagementScore,
					checkedAt: now,
				});
				return {
					threads_post_id: p.id,
					engagement_score: engagementScore,
					metric_quality: metricDecision.metric_quality,
					content: p.text ?? undefined,
				};
			})
			.filter((p) => hasValidCompetitorEngagement(p.metric_quality));

		if (resolvedUserId) {
			await detectViralSpikes(
				competitorId,
				resolvedUserId,
				username,
				postsWithScores,
			);
		}
	} catch (viralErr) {
		logger.warn("Viral spike detection failed (non-blocking)", {
			competitorId,
			error: String(viralErr),
		});
	}

	return { postsCount: storedCount, accountStatus: "active" };
}

// ============================================================================
// Viral Spike Detection
// ============================================================================

const VIRAL_MULTIPLIER = 4.5;
const VIRAL_DEDUP_TTL = 86400; // 24 hours in seconds

/**
 * Detect viral spikes for competitor posts.
 * When a post's engagement score exceeds 4.5x the competitor's 30-day average,
 * create a notification for the user (with Redis dedup to avoid repeat alerts).
 */
export async function detectViralSpikes(
	competitorId: string,
	userId: string,
	competitorUsername: string,
	newPosts: Array<{
		threads_post_id: string;
		engagement_score: number;
		content?: string | undefined;
	}>,
): Promise<void> {
	if (newPosts.length === 0) return;

	// Get 30-day average engagement score (exclude posts from last 24h to avoid self-comparison)
	const thirtyDaysAgo = new Date();
	thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
	const oneDayAgo = new Date();
	oneDayAgo.setDate(oneDayAgo.getDate() - 1);

	const { data: avgData, error: avgError } = await db()
		.from("competitor_top_posts")
		.select("engagement_score, metric_quality")
		.eq("competitor_id", competitorId)
		.in("metric_quality", ["valid_engagement", "scraper_estimated"])
		.gte("published_at", thirtyDaysAgo.toISOString())
		.lte("published_at", oneDayAgo.toISOString());

	if (avgError) {
		logger.warn("Failed to fetch historical engagement for viral detection", {
			competitorId,
			error: avgError.message,
		});
		return;
	}

	if (!avgData || avgData.length < 3) {
		// Not enough historical data to establish a baseline
		return;
	}

	const totalScore = (avgData as EngagementRow[]).reduce(
		(sum: number, p: EngagementRow) => sum + (p.engagement_score || 0),
		0,
	);
	const avgScore = totalScore / avgData.length;

	if (avgScore <= 0) return;

	const viralThreshold = avgScore * VIRAL_MULTIPLIER;

	// Lazy import createNotification to avoid module loading in non-viral paths
	let createNotificationFn:
		| typeof import("../../createNotification.js").createNotification
		| null = null;

	const redis = getRedis();

	for (const post of newPosts) {
		if (post.engagement_score <= viralThreshold) continue;

		// Redis dedup: skip if already alerted for this post
		const dedupKey = `viral-alert:${competitorId}:${post.threads_post_id}`;
		const alreadyAlerted = await redis.get(dedupKey);
		if (alreadyAlerted) continue;

		// Set dedup key first to avoid race conditions
		await redis.set(dedupKey, "1", { ex: VIRAL_DEDUP_TTL });

		// Lazy load createNotification on first use
		if (!createNotificationFn) {
			const mod = await import("../../createNotification.js");
			createNotificationFn = mod.createNotification;
		}

		const snippet = post.content
			? post.content.slice(0, 100) + (post.content.length > 100 ? "..." : "")
			: "No content";
		const multiplier = (post.engagement_score / avgScore).toFixed(1);

		await createNotificationFn({
			userId,
			type: "competitor_viral",
			title: `@${competitorUsername} has a viral post`,
			message: `A post is performing ${multiplier}x above their 30-day average: "${snippet}"`,
			data: {
				competitorId,
				competitorUsername,
				threadsPostId: post.threads_post_id,
				engagementScore: post.engagement_score,
				averageScore: Math.round(avgScore),
				multiplier: parseFloat(multiplier),
			},
		});

		logger.info("Viral spike notification created", {
			competitorId,
			competitorUsername,
			postId: post.threads_post_id,
			score: post.engagement_score,
			avg: Math.round(avgScore),
			multiplier,
		});
	}
}

// ============================================================================
// Instagram Helpers
// ============================================================================

export function calculateIgMetrics(
	media: IgMediaItem[],
	followersCount: number,
) {
	if (!media || media.length === 0) {
		return { avgLikes: 0, avgComments: 0, engagementRate: 0 };
	}
	const totalLikes = media.reduce(
		(sum: number, m: IgMediaItem) => sum + (m.like_count || 0),
		0,
	);
	const totalComments = media.reduce(
		(sum: number, m: IgMediaItem) => sum + (m.comments_count || 0),
		0,
	);
	const count = media.length;
	const avgLikes = Math.round(totalLikes / count);
	const avgComments = Math.round(totalComments / count);
	const engagementRate = calculateCompetitorEngagementRate(
		totalLikes,
		totalComments,
		count,
		followersCount,
	);
	return { avgLikes, avgComments, engagementRate };
}

interface IgAccountCredentials {
	instagram_access_token_encrypted: string | null;
	instagram_user_id: string | null;
	login_type: string | null;
}

export async function getIgAccount(userId: string, accountId: string) {
	const { data: account } = (await db()
		.from("instagram_accounts")
		.select("instagram_access_token_encrypted, instagram_user_id, login_type")
		.eq("id", accountId)
		.eq("user_id", userId)
		.maybeSingle()) as { data: IgAccountCredentials | null; error: unknown };
	return account;
}
