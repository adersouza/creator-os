// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Account Sync Module
 *
 * Consolidates Threads and Instagram account sync logic that was duplicated
 * between handleRefresh/syncSingleAccount and handleIgRefresh/syncSingleIgAccount
 * in analytics.ts.
 */

import * as crypto from "node:crypto";
import { decrypt } from "./encryption.js";
import type { IGPostMetrics } from "./instagram/shared.js";
import { logger } from "./logger.js";
import { calculateEngagementRate } from "./metricCalculators.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "./privilegedDb.js";
import { withRetry } from "./retryUtils.js";

const db = () => getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.accountSync);
const lockInstanceId = crypto.randomUUID();

/**
 * Per-account distributed lock using the existing cron_locks infrastructure.
 * Prevents concurrent syncs for the same account (e.g. manual refresh + cron overlap).
 */
async function withAccountLock<T>(
	accountId: string,
	fn: () => Promise<T>,
): Promise<{ skipped: true } | { skipped: false; result: T }> {
	const lockName = `sync:${accountId}`;
	const { data: acquired } = await db().rpc("acquire_cron_lock", {
		p_job_name: lockName,
		p_locked_by: lockInstanceId,
		p_ttl_seconds: 120,
	});

	if (!acquired) {
		logger.warn("Account sync skipped — lock held by another instance", {
			accountId,
		});
		return { skipped: true };
	}

	try {
		const result = await fn();
		return { skipped: false, result };
	} finally {
		try {
			await db().rpc("release_cron_lock", {
				p_job_name: lockName,
				p_locked_by: lockInstanceId,
			});
		} catch {
			// Non-fatal — lock expires naturally after TTL
		}
	}
}

// Lazy import to avoid Vercel module resolution issues
async function storePostMediaLazy(
	mediaUrls: string[],
	userId: string,
	postId: string,
): Promise<string[]> {
	const { storePostMedia } = await import("./mediaStorage.js");
	return storePostMedia(mediaUrls, userId, postId);
}

// ============================================================================
// Types
// ============================================================================

export interface SyncResult {
	success: boolean;
	accountId: string;
	username?: string | undefined;
	suspended?: boolean | undefined;
	reactivated?: boolean | undefined;
	error?: string | undefined;
	data?:
		| {
				followersCount: number;
				postsCount: number;
				engagementRate: number;
				followerGrowth: number;
				syncedPosts: number;
				importedPosts: number;
		  }
		| undefined;
}

interface PostInsights {
	views: number;
	likes: number;
	replies: number;
	reposts: number;
	quotes: number;
	shares: number;
	clicks: number;
}

// ============================================================================
// Shared Helpers
// ============================================================================

async function fetchWithTimeout(
	url: string,
	options: RequestInit = {},
	timeoutMs: number = 10000,
): Promise<Response> {
	const controller = new AbortController();
	const timeout = setTimeout(() => controller.abort(), timeoutMs);

	try {
		const response = await withRetry(() =>
			fetch(url, {
				...options,
				signal: controller.signal,
			}),
		);
		return response;
	} finally {
		clearTimeout(timeout);
	}
}

/**
 * Age-decay: only fetch insights for posts where metrics are likely still changing.
 * Posts older than 14 days have stable metrics — skip to save ~40% of API calls.
 */
function shouldFetchInsights(publishedAt: string | undefined): boolean {
	if (!publishedAt) return true;
	const ageMs = Date.now() - new Date(publishedAt).getTime();
	return ageMs < 14 * 24 * 60 * 60 * 1000;
}

interface ThreadsPost {
	id: string;
	timestamp?: string | undefined;
	text?: string | undefined;
	media_type?: string | undefined;
	media_url?: string | undefined;
	permalink?: string | undefined;
	[key: string]: unknown;
}

// Canonical shape lives in ./instagram/shared.ts — reuse so new fields (follows,
// reels_skip_rate, profileActivity) don't drift.
type IgPostMetrics = IGPostMetrics;

interface ThreadsMetricItem {
	name: string;
	total_value?: { value: number } | undefined;
	values?: Array<{ value: number }> | undefined;
}

interface ThreadsApiError {
	message?: string | undefined;
	code?: number | undefined;
}

interface ThreadsProfileData {
	id?: string | undefined;
	username?: string | undefined;
	threads_profile_picture_url?: string | undefined;
	threads_biography?: string | undefined;
	is_verified?: boolean | undefined;
	error?: ThreadsApiError | undefined;
}

async function fetchInsightsForPosts(
	posts: ThreadsPost[],
	token: string,
): Promise<Map<string, PostInsights>> {
	const insights = new Map<string, PostInsights>();
	const batchSize = 5;

	// Age-decay: skip insights for posts older than 14 days
	const eligiblePosts = posts.filter((p) => shouldFetchInsights(p.timestamp));
	if (eligiblePosts.length < posts.length) {
		logger.info("Age-decay: skipping insights for old posts", {
			total: posts.length,
			eligible: eligiblePosts.length,
			skipped: posts.length - eligiblePosts.length,
		});
	}

	for (let i = 0; i < eligiblePosts.length; i += batchSize) {
		const batch = eligiblePosts.slice(i, i + batchSize);
		const batchPromises = batch.map(async (post) => {
			try {
				const insightsUrl = `https://graph.threads.net/v1.0/${post.id}/insights?metric=views,likes,replies,reposts,quotes,shares`;
				const insightsResponse = await fetchWithTimeout(
					insightsUrl,
					{ headers: { Authorization: `Bearer ${token}` } },
					10000,
				);
				const insightsData = await insightsResponse.json();

				if (!insightsResponse.ok || insightsData.error) return null;

				const postInsights: PostInsights = {
					views: 0,
					likes: 0,
					replies: 0,
					reposts: 0,
					quotes: 0,
					shares: 0,
					clicks: 0,
				};

				if (insightsData.data) {
					insightsData.data.forEach((metric: ThreadsMetricItem) => {
						const name = metric.name;
						const value =
							metric.total_value?.value ??
							metric.values?.[metric.values.length - 1]?.value ??
							0;
						if (name in postInsights) {
							postInsights[name as keyof PostInsights] = value;
						}
					});
				}

				return { postId: post.id, insights: postInsights };
			} catch (err) {
				logger.warn("[accountSync] Failed to fetch Threads post insights", {
					error: String(err),
				});
				return null;
			}
		});

		const batchResults = await Promise.all(batchPromises);
		for (const result of batchResults) {
			if (result) {
				insights.set(result.postId, result.insights);
			}
		}

		// Small delay between batches to avoid rate limiting
		if (i + batchSize < eligiblePosts.length) {
			await new Promise((resolve) => setTimeout(resolve, 50));
		}
	}

	return insights;
}

// Incremental sync: Fetch posts with date-based filtering (since parameter)
async function fetchPostsWithInsights(
	threadsUserId: string,
	token: string,
	lastSyncAt: string | null = null,
	maxPosts: number = 100,
): Promise<{
	posts: ThreadsPost[];
	insights: Map<string, PostInsights>;
	isIncremental: boolean;
}> {
	const posts: ThreadsPost[] = [];
	let insights = new Map<string, PostInsights>();

	let sinceDate: string | null = null;
	if (lastSyncAt) {
		try {
			const date = new Date(lastSyncAt);
			date.setDate(date.getDate() - 1);
			sinceDate = date.toISOString().split("T")[0]!;
		} catch (err) {
			logger.warn(
				"[accountSync] Failed to parse lastSyncAt date for incremental sync",
				{ error: String(err) },
			);
			sinceDate = null;
		}
	}

	const isIncremental = !!sinceDate;

	try {
		let baseUrl = `https://graph.threads.net/v1.0/${threadsUserId}/threads?fields=id,text,timestamp,permalink,media_url,media_type,thumbnail_url,total_votes,gif_url,topic_tag&limit=25`;
		if (sinceDate) {
			baseUrl += `&since=${sinceDate}`;
		}

		const authHeaders = { headers: { Authorization: `Bearer ${token}` } };
		let url = baseUrl;
		let pageCount = 0;
		const maxPages = Math.ceil(maxPosts / 25);

		logger.info("Starting sync", {
			mode: isIncremental ? "incremental" : "full",
			sinceDate,
			threadsUserId,
		});

		while (pageCount < maxPages) {
			const postsResponse = await fetchWithTimeout(url, authHeaders, 15000);
			const postsData = await postsResponse.json();

			if (postsData.error) {
				logger.error("Posts fetch error", {
					code: postsData.error.code,
					type: postsData.error.type,
					message: postsData.error.message,
				});

				// Check if 'since' parameter is not supported
				if (
					postsData.error.message?.includes("since") ||
					postsData.error.code === 100
				) {
					logger.warn(
						"'since' parameter may not be supported, retrying without it",
					);
					if (isIncremental && pageCount === 0) {
						const fallbackUrl = `https://graph.threads.net/v1.0/${threadsUserId}/threads?fields=id,text,timestamp,permalink,media_url,media_type,thumbnail_url,total_votes,gif_url,topic_tag&limit=25`;
						const fallbackResponse = await fetchWithTimeout(
							fallbackUrl,
							authHeaders,
							15000,
						);
						const fallbackData = await fallbackResponse.json();
						if (!fallbackData.error && fallbackData.data) {
							logger.info(
								"Fallback succeeded, 'since' not supported - doing full sync",
							);
							posts.push(...fallbackData.data);
							pageCount++;
							const paging = fallbackData.paging;
							if (paging?.cursors?.after) {
								url = `https://graph.threads.net/v1.0/${threadsUserId}/threads?fields=id,text,timestamp,permalink,media_url,media_type,thumbnail_url,total_votes,gif_url,topic_tag&limit=25&after=${encodeURIComponent(paging.cursors.after)}`;
								continue;
							}
						}
					}
				}
				break;
			}

			if (!postsResponse.ok) {
				logger.error("Posts fetch failed", {
					status: postsResponse.status,
					statusText: postsResponse.statusText,
				});
				break;
			}

			if (!postsData.data) {
				break;
			}

			const pagePosts = postsData.data || [];
			posts.push(...pagePosts);
			pageCount++;

			logger.info("Page fetched", {
				page: pageCount,
				pagePosts: pagePosts.length,
				totalPosts: posts.length,
			});

			const paging = postsData.paging;
			if (paging?.cursors?.after && pagePosts.length > 0) {
				url = `${baseUrl}&after=${encodeURIComponent(paging.cursors.after)}`;
			} else {
				break;
			}

			if (posts.length >= maxPosts) {
				break;
			}
		}

		if (posts.length > 0) {
			logger.info("Fetching insights", { postCount: posts.length });
			insights = await fetchInsightsForPosts(posts, token);
			logger.info("Got insights", { insightsCount: insights.size });
		}
	} catch (error) {
		logger.error("Error in fetchPostsWithInsights", { error: String(error) });
	}

	return { posts, insights, isIncremental };
}

/**
 * Calculate follower growth by comparing to previous analytics data.
 */
async function calculateFollowerGrowth(
	accountId: string,
	followersCount: number,
	todayKey: string,
): Promise<number> {
	let followerGrowth = 0;
	try {
		const yesterday = new Date();
		yesterday.setDate(yesterday.getDate() - 1);
		const yesterdayKey = yesterday.toISOString().split("T")[0]!;

		const { data: previousData } = await db()
			.from("account_analytics")
			.select("followers_count")
			.eq("account_id", accountId)
			.eq("date", yesterdayKey)
			.maybeSingle();

		if (previousData?.followers_count) {
			followerGrowth = followersCount - previousData.followers_count;
		} else {
			const { data: latestData } = await db()
				.from("account_analytics")
				.select("followers_count, date")
				.eq("account_id", accountId)
				.lt("date", todayKey)
				.order("date", { ascending: false })
				.limit(1)
				.maybeSingle();

			if (latestData?.followers_count) {
				followerGrowth = followersCount - latestData.followers_count;
			}
		}
	} catch (err) {
		logger.warn(
			"[accountSync] Failed to calculate follower growth from historical data",
			{ error: String(err) },
		);
		// No historical data
	}
	return followerGrowth;
}

// ============================================================================
// Threads Account Sync
// ============================================================================

export async function syncThreadsAccount(
	accountId: string,
	userId: string,
): Promise<SyncResult> {
	const lockResult = await withAccountLock(accountId, () =>
		_syncThreadsAccountInner(accountId, userId),
	);
	if (lockResult.skipped) {
		return {
			accountId,
			success: false,
			error: "Sync already in progress for this account",
		};
	}
	return (lockResult as { skipped: false; result: SyncResult }).result;
}

async function _syncThreadsAccountInner(
	accountId: string,
	userId: string,
): Promise<SyncResult> {
	try {
		const { data: account, error: accountError } = await db()
			.from("accounts")
			.select(
				"id, username, threads_user_id, threads_access_token_encrypted, status, followers_count, last_synced_at",
			)
			.eq("id", accountId)
			.eq("user_id", userId)
			.maybeSingle();

		if (accountError || !account) {
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

		// Decrypt token
		let token: string;
		try {
			token = decrypt(account.threads_access_token_encrypted);
		} catch (_decryptError: unknown) {
			return {
				accountId,
				username: account.username,
				success: false,
				error:
					"Token decryption failed. You may need to reconnect your Threads account.",
			};
		}

		// Fetch profile - detect suspended accounts
		let profileData: ThreadsProfileData;
		try {
			const profileUrl = `https://graph.threads.net/v1.0/${account.threads_user_id}?fields=id,username,threads_profile_picture_url,threads_biography,is_verified`;
			const profileResponse = await fetchWithTimeout(
				profileUrl,
				{ headers: { Authorization: `Bearer ${token}` } },
				10000,
			);
			profileData = await profileResponse.json();

			if (!profileResponse.ok || profileData.error) {
				const errorMessage = profileData.error?.message || "Unknown error";
				const errorCode = profileData.error?.code;

				// Token expiry (code 190) requires re-auth, not suspension
				const isTokenExpired = errorCode === 190;
				const isSuspended =
					errorCode === 100 ||
					errorCode === 10 ||
					errorMessage.toLowerCase().includes("suspended") ||
					errorMessage.toLowerCase().includes("not found") ||
					(errorMessage.toLowerCase().includes("permission") &&
						errorCode !== 190);

				if (isTokenExpired) {
					logger.warn("Account token expired — needs re-auth", {
						username: account.username,
						errorMessage,
					});

					await db()
						.from("accounts")
						.update({
							status: "needs_reauth",
							needs_reauth: true,
							is_active: false,
							updated_at: new Date().toISOString(),
						})
						.eq("id", accountId);

					return {
						accountId,
						username: account.username,
						success: false,
						error: `Token expired for @${account.username}. Please reconnect your account.`,
					};
				}

				if (isSuspended) {
					logger.warn("Account appears suspended", {
						username: account.username,
						errorMessage,
					});

					await db()
						.from("accounts")
						.update({
							status: "suspended",
							is_active: false,
							updated_at: new Date().toISOString(),
						})
						.eq("id", accountId);

					// Notify user of account suspension
					try {
						await db()
							.from("notifications")
							.insert({
								user_id: userId,
								type: "account_suspended",
								title: "Account suspended",
								message: `Your Threads account @${account.username} appears to be suspended.`,
								read: false,
								data: { accountId },
							});
						const { deliverNotification } = await import(
							"./deliverNotification.js"
						);
						deliverNotification({
							userId,
							type: "account_suspended",
							title: "Account suspended",
							message: `Your Threads account @${account.username} appears to be suspended.`,
							data: { accountId },
						}).catch(() => {});
					} catch {
						/* notification non-critical */
					}

					return {
						accountId,
						username: account.username,
						success: false,
						suspended: true,
						error: `Account @${account.username} appears to be suspended or banned on Threads`,
					};
				}

				return {
					accountId,
					username: account.username,
					success: false,
					error: `Failed to fetch profile: ${errorMessage}`,
				};
			}
		} catch (profileError: unknown) {
			return {
				accountId,
				username: account.username,
				success: false,
				error: `Profile fetch error: ${profileError instanceof Error ? profileError.message : String(profileError)}`,
			};
		}

		// Fetch followers count
		let followersCount = 0;
		try {
			const accountInsightsUrl = `https://graph.threads.net/v1.0/${account.threads_user_id}/threads_insights?metric=followers_count`;
			const accountInsightsResponse = await fetchWithTimeout(
				accountInsightsUrl,
				{ headers: { Authorization: `Bearer ${token}` } },
				10000,
			);
			const accountInsightsData = await accountInsightsResponse.json();

			if (accountInsightsData.data) {
				const followerMetric = accountInsightsData.data.find(
					(m: ThreadsMetricItem) => m.name === "followers_count",
				);
				if (followerMetric) {
					followersCount =
						followerMetric.total_value?.value ??
						followerMetric.values?.[followerMetric.values.length - 1]?.value ??
						0;
				}
			}
		} catch (err) {
			logger.warn("[accountSync] Failed to fetch Threads followers count", {
				error: String(err),
			});
			// Continue without follower count
		}

		// Fetch posts with incremental sync
		logger.info("Account last_synced_at", {
			lastSyncedAt: account.last_synced_at || "never",
		});
		const syncResult = await fetchPostsWithInsights(
			account.threads_user_id,
			token,
			account.last_synced_at || null,
			100,
		);

		const { posts, insights: postInsights, isIncremental } = syncResult;
		logger.info("Sync complete", { postCount: posts.length, isIncremental });

		// Aggregate metrics
		let totalViews = 0,
			totalLikes = 0,
			totalReplies = 0,
			totalReposts = 0,
			totalQuotes = 0,
			totalShares = 0;
		for (const [, metrics] of postInsights) {
			totalViews += metrics.views;
			totalLikes += metrics.likes;
			totalReplies += metrics.replies;
			totalReposts += metrics.reposts;
			totalQuotes += metrics.quotes;
			totalShares += metrics.shares;
		}

		// Update account - also reactivate if previously suspended
		const wasReactivated = account.status === "suspended";
		if (wasReactivated) {
			logger.info("Account reactivated after suspension", {
				username: account.username,
			});
		}

		await db()
			.from("accounts")
			.update({
				username: profileData.username,
				avatar_url: profileData.threads_profile_picture_url || null,
				bio: profileData.threads_biography || "",
				is_verified: profileData.is_verified || false,
				followers_count: followersCount,
				last_synced_at: new Date().toISOString(),
				updated_at: new Date().toISOString(),
				status: "active",
				is_active: true,
				needs_reauth: false,
			})
			.eq("id", accountId);

		// Store daily analytics
		const todayKey = new Date().toISOString().split("T")[0]!;
		const engagementRate = calculateEngagementRate(
			{
				views: totalViews,
				likes: totalLikes,
				replies: totalReplies,
				reposts: totalReposts,
				quotes: totalQuotes,
				shares: totalShares,
			},
			"threads",
		);

		const followerGrowth = await calculateFollowerGrowth(
			accountId,
			followersCount,
			todayKey!,
		);

		await db().from("account_analytics").upsert(
			{
				account_id: accountId,
				date: todayKey,
				followers_count: followersCount,
				total_views: totalViews,
				total_likes: totalLikes,
				total_replies: totalReplies,
				total_reposts: totalReposts,
				total_quotes: totalQuotes,
				total_shares: totalShares,
				posts_count: posts.length,
				engagement_rate: engagementRate,
				follower_growth: followerGrowth,
			},
			{ onConflict: "account_id,date" },
		);

		// Sync posts: Update existing + auto-import new
		const { data: existingPosts } = await db()
			.from("posts")
			.select("id, threads_post_id, media_urls")
			.eq("account_id", accountId)
			.not("threads_post_id", "is", null);

		const existingPostMap = new Map<
			string,
			{ id: string; media_urls: string[] }
		>(
			(existingPosts || []).map(
				(p: {
					id: string;
					threads_post_id: string | null;
					media_urls: string[] | null;
				}) => [
					p.threads_post_id ?? "",
					{ id: p.id, media_urls: p.media_urls || [] },
				],
			),
		);

		let postsUpdated = 0;
		let postsImported = 0;

		// Phase 1a: Identify posts needing media storage and batch-process uploads
		interface MediaTask {
			postId: string;
			urls: string[];
			type: "migrate" | "new";
		}
		const mediaTasks: MediaTask[] = [];

		for (const post of posts) {
			const existingData = existingPostMap.get(post.id);
			if (existingData) {
				const { media_urls: currentMediaUrls } = existingData;
				const hasCdnUrls =
					currentMediaUrls &&
					currentMediaUrls.length > 0 &&
					currentMediaUrls.some(
						(url: string) => url && !url.includes("supabase"),
					);
				if (hasCdnUrls && post.media_url) {
					mediaTasks.push({
						postId: post.id,
						urls: [post.media_url],
						type: "migrate",
					});
				}
			} else if (post.media_url) {
				mediaTasks.push({
					postId: post.id,
					urls: [post.media_url],
					type: "new",
				});
			}
		}

		// Process media uploads in parallel batches of 5
		const MEDIA_BATCH_SIZE = 5;
		const mediaResults = new Map<string, string[]>();

		for (let i = 0; i < mediaTasks.length; i += MEDIA_BATCH_SIZE) {
			const batch = mediaTasks.slice(i, i + MEDIA_BATCH_SIZE);
			const batchResults = await Promise.allSettled(
				batch.map(async (task) => {
					const storedUrls = await storePostMediaLazy(
						task.urls,
						userId,
						task.postId,
					);
					return { postId: task.postId, storedUrls, type: task.type };
				}),
			);
			for (const result of batchResults) {
				if (
					result.status === "fulfilled" &&
					result.value.storedUrls.length > 0
				) {
					const { postId, storedUrls, type } = result.value;
					if (type === "migrate") {
						if (storedUrls[0]!.includes("supabase")) {
							mediaResults.set(postId, storedUrls);
							logger.info("Migrated media for existing post", { postId });
						}
					} else {
						mediaResults.set(postId, storedUrls);
					}
				} else if (result.status === "rejected") {
					logger.warn("Failed to store media for post in batch", {
						error: String(result.reason),
					});
				}
			}
		}

		// Phase 1b: Build updates and upserts using pre-fetched media results
		const pendingUpdates: Array<{ id: string; data: Record<string, unknown> }> =
			[];
		const pendingUpserts: Array<Record<string, unknown>> = [];

		for (const post of posts) {
			const insights = postInsights.get(post.id);
			const postEngagementRate = insights
				? calculateEngagementRate(
						{
							views: insights.views,
							likes: insights.likes,
							replies: insights.replies,
							reposts: insights.reposts,
							quotes: insights.quotes,
							shares: insights.shares,
						},
						"threads",
					)
				: 0;

			const existingData = existingPostMap.get(post.id);

			if (existingData) {
				const { id: existingId } = existingData;
				const updatedMediaUrls = mediaResults.get(post.id);

				if (insights) {
					const updateData: Record<string, unknown> = {
						views_count: insights.views,
						likes_count: insights.likes,
						replies_count: insights.replies,
						reposts_count: insights.reposts,
						quotes_count: insights.quotes,
						shares_count: insights.shares,
						engagement_rate: postEngagementRate,
						permalink: post.permalink || null,
						updated_at: new Date().toISOString(),
					};
					if (updatedMediaUrls) {
						updateData.media_urls = updatedMediaUrls;
					}
					pendingUpdates.push({ id: existingId, data: updateData });
				}
			} else {
				let mediaUrls: string[] = post.media_url ? [post.media_url] : [];
				const storedMedia = mediaResults.get(post.id);
				if (storedMedia && storedMedia.length > 0) {
					mediaUrls = storedMedia;
				}

				const hashtags: string[] = [];
				for (const m of (post.text || "").matchAll(/#(\w+)/g)) {
					hashtags.push(m[1]!);
				}

				pendingUpserts.push({
					user_id: userId,
					account_id: accountId,
					platform: "threads",
					threads_post_id: post.id,
					content: post.text || "",
					media_urls: mediaUrls,
					media_type: (post.media_type || "TEXT").toLowerCase(),
					status: "published",
					published_at: post.timestamp || new Date().toISOString(),
					permalink: post.permalink || null,
					hashtags,
					views_count: insights?.views || 0,
					likes_count: insights?.likes || 0,
					replies_count: insights?.replies || 0,
					reposts_count: insights?.reposts || 0,
					quotes_count: insights?.quotes || 0,
					shares_count: insights?.shares || 0,
					engagement_rate: postEngagementRate,
				});
			}
		}

		// Phase 2: Batch DB writes
		if (pendingUpdates.length > 0) {
			const updateResults = await Promise.allSettled(
				pendingUpdates.map(({ id, data }) =>
					db().from("posts").update(data).eq("id", id),
				),
			);
			postsUpdated = updateResults.filter(
				(r) => r.status === "fulfilled" && !r.value.error,
			).length;
		}

		if (pendingUpserts.length > 0) {
			const postsTable = db().from("posts");
			// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert requires typed row shape
			const upsertQuery = postsTable.upsert(pendingUpserts as any[], {
				onConflict: "user_id,threads_post_id",
				ignoreDuplicates: false,
				count: "exact",
			});
			const { error: batchError, count } = await upsertQuery;
			if (batchError) {
				logger.error("Batch upsert failed, falling back to chunks", {
					error: batchError.message,
				});
				// Fallback: chunked upserts (preserves partial-failure granularity
				// without paying one round-trip per row).
				const FALLBACK_CHUNK_SIZE = 25;
				for (let i = 0; i < pendingUpserts.length; i += FALLBACK_CHUNK_SIZE) {
					const chunk = pendingUpserts.slice(i, i + FALLBACK_CHUNK_SIZE);
					const { error: chunkError, count: chunkCount } = await db()
						.from("posts")
						// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert requires typed row shape
						.upsert(chunk as any[], {
							onConflict: "user_id,threads_post_id",
							ignoreDuplicates: false,
							count: "exact",
						});
					if (chunkError) {
						logger.warn("Fallback chunk failed", {
							chunkStart: i,
							chunkSize: chunk.length,
							error: chunkError.message,
						});
					} else {
						postsImported += chunkCount ?? chunk.length;
					}
				}
			} else {
				postsImported = count ?? pendingUpserts.length;
			}
		}

		logger.info("Posts sync complete", { postsUpdated, postsImported });

		return {
			accountId,
			username: account.username,
			success: true,
			reactivated: wasReactivated,
			data: {
				followersCount,
				postsCount: posts.length,
				engagementRate,
				followerGrowth,
				syncedPosts: postsUpdated,
				importedPosts: postsImported,
			},
		};
	} catch (error: unknown) {
		return {
			accountId,
			success: false,
			error: error instanceof Error ? error.message : String(error),
		};
	}
}

// ============================================================================
// Instagram Account Sync
// ============================================================================

export async function syncInstagramAccount(
	igAccountId: string,
	userId: string,
): Promise<SyncResult> {
	const lockResult = await withAccountLock(igAccountId, () =>
		_syncInstagramAccountInner(igAccountId, userId),
	);
	if (lockResult.skipped) {
		return {
			accountId: igAccountId,
			success: false,
			error: "Sync already in progress for this account",
		};
	}
	return (lockResult as { skipped: false; result: SyncResult }).result;
}

async function _syncInstagramAccountInner(
	igAccountId: string,
	userId: string,
): Promise<SyncResult> {
	try {
		const { data: igAccount, error: igAccountError } = await db()
			.from("instagram_accounts")
			.select(
				"id, instagram_user_id, username, instagram_access_token_encrypted, follower_count, last_synced_at, login_type",
			)
			.eq("id", igAccountId)
			.eq("user_id", userId)
			.maybeSingle();

		if (igAccountError || !igAccount) {
			return {
				accountId: igAccountId,
				success: false,
				error: "Instagram account not found",
			};
		}

		if (
			!igAccount.instagram_access_token_encrypted ||
			!igAccount.instagram_user_id
		) {
			return {
				accountId: igAccountId,
				username: igAccount.username ?? undefined,
				success: false,
				error: "Missing OAuth credentials",
			};
		}

		const encryptedToken = igAccount.instagram_access_token_encrypted;
		const loginType = igAccount.login_type || "instagram";
		logger.info("IG account found", {
			username: igAccount.username ?? undefined,
			loginType,
		});

		// Fetch follower count via account insights
		let followersCount = igAccount.follower_count || 0;
		let followerCountFresh = false; // true only if API returned it (not in missingMetrics)
		try {
			const { getInstagramAccountInsights } = await import("./instagramApi.js");
			const insightsResult = await getInstagramAccountInsights(
				encryptedToken,
				igAccount.instagram_user_id,
				"day",
				loginType,
			);
			if (insightsResult.success && insightsResult.insights) {
				const missing = new Set(insightsResult.missingMetrics ?? []);
				if (
					!missing.has("follower_count") &&
					insightsResult.insights.followerCount > 0
				) {
					followersCount = insightsResult.insights.followerCount;
					followerCountFresh = true;
				}
			} else if (!insightsResult.success && insightsResult.error) {
				// Detect token expiry in insights call — use canonical checker
				const { isDefinitiveOAuthError } = await import("./retryUtils.js");
				if (isDefinitiveOAuthError(insightsResult.error)) {
					logger.warn("IG token expired (insights) — needs re-auth", {
						username: igAccount.username,
						error: insightsResult.error,
					});
					await db()
						.from("instagram_accounts")
						.update({
							status: "needs_reauth",
							needs_reauth: true,
							is_active: false,
							updated_at: new Date().toISOString(),
						})
						.eq("id", igAccountId);
					return {
						accountId: igAccountId,
						username: igAccount.username ?? undefined,
						success: false,
						error: `IG token expired: ${insightsResult.error}`,
					};
				}
			}
		} catch (insightsErr) {
			logger.error("IG account insights error", { error: String(insightsErr) });
		}

		// Fetch user's posts
		const { getUserMedia } = await import("./instagramApi.js");
		const mediaResult = await getUserMedia(
			encryptedToken,
			igAccount.instagram_user_id,
			100,
			loginType,
		);

		if (!mediaResult.success || !mediaResult.media) {
			// Detect token expiry / auth errors and flag for re-auth
			const { isDefinitiveOAuthError: isOAuthErr } = await import(
				"./retryUtils.js"
			);
			if (mediaResult.error && isOAuthErr(mediaResult.error)) {
				logger.warn("IG token expired — needs re-auth", {
					username: igAccount.username,
					error: mediaResult.error,
				});
				await db()
					.from("instagram_accounts")
					.update({
						status: "needs_reauth",
						needs_reauth: true,
						is_active: false,
						updated_at: new Date().toISOString(),
					})
					.eq("id", igAccountId);
			}
			return {
				accountId: igAccountId,
				username: igAccount.username ?? undefined,
				success: false,
				error: `Failed to fetch IG media: ${mediaResult.error}`,
			};
		}

		const media = mediaResult.media;
		logger.info("Fetched IG posts", { count: media.length });

		// Fetch per-post metrics (batched 5 at a time, 50ms delay)
		// Age-decay: skip metrics for posts older than 14 days
		const { getInstagramPostMetrics } = await import("./instagramApi.js");
		const postMetrics = new Map<string, IgPostMetrics>();
		let totalLikes = 0,
			totalComments = 0,
			totalImpressions = 0,
			totalReach = 0,
			totalSaved = 0,
			totalShares = 0;

		const eligibleMedia = media.filter((m) => shouldFetchInsights(m.timestamp));
		if (eligibleMedia.length < media.length) {
			logger.info("IG age-decay: skipping metrics for old posts", {
				total: media.length,
				eligible: eligibleMedia.length,
				skipped: media.length - eligibleMedia.length,
			});
		}

		for (let i = 0; i < eligibleMedia.length; i += 5) {
			const batch = eligibleMedia.slice(i, i + 5);
			const results = await Promise.all(
				batch.map((m) =>
					getInstagramPostMetrics(
						encryptedToken,
						m.id,
						loginType,
						m.media_product_type === "REELS" ? "REELS" : m.media_type,
					),
				),
			);
			results.forEach((result, idx) => {
				if (result.success && result.metrics) {
					postMetrics.set(batch[idx]!.id, result.metrics);
					totalLikes += result.metrics.likes || 0;
					totalComments += result.metrics.comments || 0;
					totalImpressions += result.metrics.impressions || 0;
					totalReach += result.metrics.reach || 0;
					totalSaved += result.metrics.saved || 0;
					totalShares += result.metrics.shares || 0;
				}
			});
			if (i + 5 < eligibleMedia.length) {
				await new Promise((r) => setTimeout(r, 50));
			}
		}

		logger.info("Got IG post metrics", { metricsCount: postMetrics.size });

		// Update IG account row (including profile fields)
		const igAccountUpdate: Record<string, unknown> = {
			last_synced_at: new Date().toISOString(),
			updated_at: new Date().toISOString(),
		};
		if (followerCountFresh) igAccountUpdate.follower_count = followersCount;
		try {
			const igToken = decrypt(encryptedToken);
			const graphBase =
				loginType === "facebook"
					? "https://graph.facebook.com"
					: "https://graph.instagram.com";
			const profileRes = await fetchWithTimeout(
				`${graphBase}/v25.0/${igAccount.instagram_user_id}?fields=username,biography,profile_picture_url,name`,
				{ headers: { Authorization: `Bearer ${igToken}` } },
				10000,
			);
			const profileData = await profileRes.json();
			if (profileRes.ok && !profileData.error) {
				if (profileData.username)
					igAccountUpdate.username = profileData.username;
				if (profileData.biography !== undefined)
					igAccountUpdate.bio = profileData.biography;
				if (profileData.profile_picture_url)
					igAccountUpdate.avatar_url = profileData.profile_picture_url;
				if (profileData.name) igAccountUpdate.display_name = profileData.name;
			}
		} catch (profileErr) {
			logger.warn("[accountSync] IG profile sync failed (non-fatal)", {
				error: String(profileErr),
			});
		}
		await db()
			.from("instagram_accounts")
			.update(igAccountUpdate)
			.eq("id", igAccountId);

		// Store daily analytics snapshot
		const todayKey = new Date().toISOString().split("T")[0]!;
		const engagementRate = calculateEngagementRate(
			{
				reach: totalReach,
				likes: totalLikes,
				comments: totalComments,
				shares: totalShares,
				saves: totalSaved,
				impressions: totalImpressions,
			},
			"instagram",
		);

		const followerGrowth = await calculateFollowerGrowth(
			igAccountId,
			followersCount,
			todayKey!,
		);

		const analyticsPayload = {
			account_id: igAccountId,
			date: todayKey,
			...(followerCountFresh ? { followers_count: followersCount } : {}),
			total_views: totalImpressions,
			total_likes: totalLikes,
			total_replies: totalComments,
			total_reposts: 0,
			total_quotes: 0,
			total_shares: totalShares,
			total_reach: totalReach,
			total_saves: totalSaved,
			ig_reach: totalReach,
			ig_impressions: totalImpressions,
			posts_count: media.length,
			engagement_rate: engagementRate,
			follower_growth: followerGrowth,
		};

		logger.info("Upserting IG account_analytics", {
			accountId: igAccountId,
			date: todayKey,
			followersCount,
			postsCount: media.length,
		});
		const { error: analyticsUpsertError } = await db()
			.from("account_analytics")
			.upsert(analyticsPayload, { onConflict: "account_id,date" });

		if (analyticsUpsertError) {
			logger.error("FAILED to upsert IG account_analytics", {
				error: analyticsUpsertError.message,
			});
		} else {
			logger.info("Successfully stored IG analytics", {
				accountId: igAccountId,
				date: todayKey,
			});
		}

		// Sync posts: Update existing + auto-import new
		const { data: existingPosts } = await db()
			.from("posts")
			.select("id, instagram_post_id, media_urls")
			.eq("instagram_account_id", igAccountId)
			.not("instagram_post_id", "is", null);

		const existingPostMap = new Map<
			string,
			{ id: string; media_urls: string[] }
		>(
			(existingPosts || []).map(
				(p: {
					id: string;
					instagram_post_id: string | null;
					media_urls: string[] | null;
				}) => [
					p.instagram_post_id ?? "",
					{ id: p.id, media_urls: p.media_urls || [] },
				],
			),
		);

		const supabaseDomain = process.env.SUPABASE_URL?.replace("https://", "");
		let postsUpdated = 0;
		let postsImported = 0;

		// Phase 1: Collect updates and imports, handle media migration
		const igPendingUpdates: Array<{
			id: string;
			data: Record<string, unknown>;
		}> = [];
		const igPendingUpserts: Array<Record<string, unknown>> = [];

		for (const item of media) {
			const metrics = postMetrics.get(item.id);
			const aggregateLikes = metrics?.total_likes || metrics?.likes || 0;
			const aggregateComments =
				metrics?.total_comments || metrics?.comments || 0;
			const aggregateViews =
				metrics?.total_views || metrics?.views || metrics?.impressions || 0;
			const postEngagementRate = metrics
				? calculateEngagementRate(
						{
							reach: metrics.reach,
							likes: aggregateLikes,
							comments: aggregateComments,
							shares: metrics.shares,
							saves: metrics.saved,
							impressions: aggregateViews,
						},
						"instagram",
					)
				: 0;

			const existingData = existingPostMap.get(item.id);
			const mediaAudioType =
				typeof item.media_audio_type === "string" && item.media_audio_type
					? item.media_audio_type
					: null;

			if (existingData) {
				if (metrics) {
					igPendingUpdates.push({
						id: existingData.id,
						data: {
							likes_count: aggregateLikes,
							replies_count: aggregateComments,
							views_count: aggregateViews,
							ig_views: aggregateViews,
							ig_impressions: aggregateViews || metrics.impressions || 0,
							ig_reach: metrics.reach || 0,
							ig_saved: metrics.saved || 0,
							ig_shares: metrics.shares || 0,
							ig_reposts: metrics.reposts || 0,
							ig_plays: metrics.plays || 0,
							ig_video_views: metrics.video_views || 0,
							ig_replays: 0,
							ig_skip_rate: metrics.reels_skip_rate || 0,
							ig_follows_count: metrics.follows || 0,
							...(mediaAudioType ? { media_audio_type: mediaAudioType } : {}),
							engagement_rate: postEngagementRate,
							permalink: item.permalink || null,
							updated_at: new Date().toISOString(),
						},
					});
				} else if (mediaAudioType) {
					igPendingUpdates.push({
						id: existingData.id,
						data: {
							media_audio_type: mediaAudioType,
							updated_at: new Date().toISOString(),
						},
					});
				}

				// Migrate CDN URLs to Supabase Storage if needed
				const hasCdnUrls = existingData.media_urls.some(
					(u: string) => u && !u.includes(supabaseDomain || "supabase"),
				);
				if (hasCdnUrls) {
					let freshUrls: string[] = [];
					if (
						item.media_type === "CAROUSEL_ALBUM" &&
						item.children?.data &&
						item.children.data.length > 0
					) {
						freshUrls = item.children.data
							.map((c: { media_url?: string | undefined }) => c.media_url)
							.filter((u): u is string => !!u);
					} else if (item.media_url) {
						freshUrls = [item.media_url];
					}
					if (freshUrls.length > 0) {
						try {
							const storedUrls = await storePostMediaLazy(
								freshUrls,
								userId,
								item.id,
							);
							// Media migration update is separate — must include in pending
							const existing = igPendingUpdates.find(
								(u) => u.id === existingData.id,
							);
							if (existing) {
								existing.data.media_urls = storedUrls;
							} else {
								igPendingUpdates.push({
									id: existingData.id,
									data: { media_urls: storedUrls },
								});
							}
						} catch (e) {
							logger.warn("IG media migration failed", { error: String(e) });
						}
					}
				}
			} else {
				const hashtags: string[] = [];
				for (const m of (item.caption || "").matchAll(/#(\w+)/g)) {
					hashtags.push(m[1]!);
				}

				let mediaUrls: string[] = [];
				if (
					item.media_type === "CAROUSEL_ALBUM" &&
					item.children?.data &&
					item.children.data.length > 0
				) {
					mediaUrls = item.children.data
						.map((child: { media_url?: string | undefined }) => child.media_url)
						.filter((u): u is string => !!u);
				}
				if (mediaUrls.length === 0 && item.media_url) {
					mediaUrls.push(item.media_url);
				}
				if (mediaUrls.length === 0 && item.thumbnail_url) {
					mediaUrls.push(item.thumbnail_url);
				}

				try {
					mediaUrls = await storePostMediaLazy(mediaUrls, userId, item.id);
				} catch (e) {
					logger.warn("IG media storage failed, using CDN URLs", {
						error: String(e),
					});
				}

				// Reels arrive from the Graph API as media_type=VIDEO. Without the
				// media_product_type override, ig_media_type stays "VIDEO" and the
				// per-post insight call (analyticsSync) drops to POST_INSIGHT_METRICS,
				// which has no reels_skip_rate / ig_reels_avg_watch_time. Persisting
				// the resolved bucket as "REELS" routes those rows through
				// REEL_INSIGHT_METRICS on the next analytics tick.
				const resolvedIgMediaType =
					item.media_product_type === "REELS"
						? "REELS"
						: item.media_type || "IMAGE";
				igPendingUpserts.push({
					user_id: userId,
					instagram_account_id: igAccountId,
					instagram_post_id: item.id,
					content: item.caption || "",
					media_urls: mediaUrls,
					media_type: (item.media_type || "IMAGE").toLowerCase(),
					ig_media_type: resolvedIgMediaType,
					media_audio_type: mediaAudioType,
					platform: "instagram",
					status: "published",
					published_at: item.timestamp || new Date().toISOString(),
					permalink: item.permalink || null,
					hashtags,
					likes_count: aggregateLikes,
					replies_count: aggregateComments,
					views_count: aggregateViews,
					ig_views: aggregateViews,
					ig_impressions: aggregateViews || metrics?.impressions || 0,
					ig_reach: metrics?.reach || 0,
					ig_saved: metrics?.saved || 0,
					ig_shares: metrics?.shares || 0,
					ig_reposts: metrics?.reposts || 0,
					ig_plays: metrics?.plays || 0,
					ig_video_views: metrics?.video_views || 0,
					ig_replays: 0,
					ig_skip_rate: metrics?.reels_skip_rate || 0,
					ig_follows_count: metrics?.follows || 0,
					engagement_rate: postEngagementRate,
				});
			}
		}

		// Phase 2: Batch DB writes
		if (igPendingUpdates.length > 0) {
			const updateResults = await Promise.allSettled(
				igPendingUpdates.map(({ id, data }) =>
					db().from("posts").update(data).eq("id", id),
				),
			);
			postsUpdated = updateResults.filter(
				(r) => r.status === "fulfilled" && !r.value.error,
			).length;
		}

		if (igPendingUpserts.length > 0) {
			const igPostsTable = db().from("posts");
			// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert requires typed row shape
			const igUpsertQuery = igPostsTable.upsert(igPendingUpserts as any[], {
				onConflict: "user_id,instagram_post_id",
				ignoreDuplicates: false,
				count: "exact",
			});
			const { error: batchError, count } = await igUpsertQuery;
			if (batchError) {
				logger.error("IG batch upsert failed, falling back to individual", {
					error: batchError.message,
				});
				for (const row of igPendingUpserts) {
					const igPostsTableFallback = db().from("posts");
					const { error: insertError } = await igPostsTableFallback.upsert(
						// biome-ignore lint/suspicious/noExplicitAny: Supabase upsert requires typed row shape
						row as any,
						{
							onConflict: "user_id,instagram_post_id",
							ignoreDuplicates: false,
						},
					);
					if (!insertError) postsImported++;
				}
			} else {
				postsImported = count ?? igPendingUpserts.length;
			}
		}

		logger.info("IG posts sync complete", { postsUpdated, postsImported });

		// Fetch and import active stories
		let storiesImported = 0;
		try {
			const { getInstagramStories } = await import("./instagramApi.js");
			const storiesResult = await getInstagramStories(
				encryptedToken,
				igAccount.instagram_user_id,
				loginType,
			);

			if (
				storiesResult.success &&
				storiesResult.stories &&
				storiesResult.stories.length > 0
			) {
				logger.info("Fetched active stories", {
					count: storiesResult.stories.length,
				});

				const storyIds = storiesResult.stories.map((s: { id: string }) => s.id);
				const { data: existingStories } = await db()
					.from("posts")
					.select("instagram_post_id")
					.eq("instagram_account_id", igAccountId)
					.in("instagram_post_id", storyIds);

				const existingStoryIds = new Set(
					(existingStories || []).map(
						(s: { instagram_post_id: string | null }) =>
							s.instagram_post_id ?? "",
					),
				);

				for (const story of storiesResult.stories) {
					if (existingStoryIds.has(story.id)) continue;

					let storyMediaUrls: string[] = [];
					if (story.media_url) storyMediaUrls.push(story.media_url);
					else if (story.thumbnail_url)
						storyMediaUrls.push(story.thumbnail_url);

					try {
						storyMediaUrls = await storePostMediaLazy(
							storyMediaUrls,
							userId,
							story.id,
						);
					} catch (e) {
						logger.warn("Story media storage failed, using CDN URLs", {
							error: String(e),
						});
					}

					const storyTimestamp = new Date(story.timestamp);
					const expiresAt = new Date(
						storyTimestamp.getTime() + 24 * 60 * 60 * 1000,
					);

					const { error: storyInsertError } = await db()
						.from("posts")
						.insert({
							user_id: userId,
							instagram_account_id: igAccountId,
							instagram_post_id: story.id,
							content: "",
							media_urls: storyMediaUrls,
							media_type: (story.media_type || "IMAGE").toLowerCase(),
							ig_media_type: "STORIES",
							platform: "instagram",
							status: "published",
							published_at: story.timestamp || new Date().toISOString(),
							story_expires_at: expiresAt.toISOString(),
						});

					if (storyInsertError) {
						logger.error("Failed to import story", {
							storyId: story.id,
							error: storyInsertError.message,
						});
					} else {
						storiesImported++;
					}
				}

				logger.info("Imported stories", { storiesImported });
			}
		} catch (storiesErr) {
			logger.warn("Stories fetch/import error", { error: String(storiesErr) });
		}

		logger.info("IG sync done", {
			username: igAccount.username ?? undefined,
			totalPosts: media.length,
			postsUpdated,
			postsImported,
			storiesImported,
			followersCount,
		});

		return {
			accountId: igAccountId,
			username: igAccount.username ?? undefined,
			success: true,
			data: {
				followersCount,
				postsCount: media.length,
				engagementRate,
				followerGrowth,
				syncedPosts: postsUpdated,
				importedPosts: postsImported,
			},
		};
	} catch (error: unknown) {
		return {
			accountId: igAccountId,
			success: false,
			error: error instanceof Error ? error.message : String(error),
		};
	}
}
