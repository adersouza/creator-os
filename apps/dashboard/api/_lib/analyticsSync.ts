// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Analytics Sync — Per-account refresh logic extracted from analytics-refresh.ts
 *
 * Provides refreshThreadsAccountAnalytics() and refreshInstagramAccountAnalytics()
 * with a syncType parameter ("full" | "metrics") to control which sections run.
 *
 * "metrics" — post metrics + account stats only (lightweight, for QStash fan-out)
 * "full"    — everything including demographics, viral calibration, content classification, etc.
 */

import { detectAnomalies } from "./anomalyDetector.js";
import { detectEvents } from "./creatorEventDetector.js";
import { invalidateDashboard } from "./dashboardCache.js";
import { decrypt } from "./encryption.js";
import { logger } from "./logger.js";
import { calculateEngagementRate } from "./metricCalculators.js";
import { checkMilestones } from "./milestoneChecker.js";
import type { Platform } from "./platform.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "./privilegedDb.js";
import { getRedis } from "./redis.js";
import { withRetry } from "./retryUtils.js";
import { computeActualPerformancePercentile } from "./viralScoreCalibration.js";

const db = () => getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.analyticsSync);

// ============================================================================
// Performance Configuration
// ============================================================================
export const POST_BATCH_SIZE = 25;
export const DELAY_BETWEEN_BATCHES = 100;

import { FETCH_TIMEOUT_MS } from "./timing.js";

export { FETCH_TIMEOUT_MS as FETCH_TIMEOUT } from "./timing.js";

const FETCH_TIMEOUT = FETCH_TIMEOUT_MS;

// ============================================================================
// Types
// ============================================================================
export interface SyncResult {
	success: boolean;
	postsUpdated: number;
	skipped?: boolean | undefined;
	error?: string | undefined;
}

/** Shape of an account row passed into refreshThreadsAccountAnalytics */
interface ThreadsAccountRow {
	id: string;
	username: string;
	threads_user_id: string;
	threads_access_token_encrypted: string;
	last_synced_at?: string | null | undefined;
	last_milestone_celebrated?: number | null | undefined;
}

/** Shape of an instagram_account row passed into refreshInstagramAccountAnalytics */
interface IGAccountRow {
	id: string;
	username: string;
	instagram_user_id: string;
	instagram_access_token_encrypted: string;
	login_type?: string | undefined;
	last_synced_at?: string | null | undefined;
	follower_count?: number | null | undefined;
	last_milestone_celebrated?: number | null | undefined;
}

/** A metric item from the Threads API data array */
interface ThreadsMetricItem {
	name: string;
	total_value?: { value: number } | undefined;
	values?: Array<{ value: number }> | undefined;
	link_total_values?:
		| Array<{ value: number; link_url?: string | undefined }>
		| undefined;
}

/** Post row returned from DB select for analytics sync */
interface PostRow {
	id: string;
	threads_post_id?: string | null | undefined;
	instagram_post_id?: string | null | undefined;
	ig_media_type?: string | null | undefined;
	content_surface?: string | null | undefined;
	published_at?: string | null | undefined;
}

/** Post dates row returned from DB for metric history */
interface PostDateRow {
	id: string;
	published_at?: string | null | undefined;
	account_id?: string | null | undefined;
	instagram_account_id?: string | null | undefined;
}

/** Post sums row returned from DB for total calculations */
interface PostSumRow {
	views_count?: number | null | undefined;
	likes_count?: number | null | undefined;
	replies_count?: number | null | undefined;
	reposts_count?: number | null | undefined;
	quotes_count?: number | null | undefined;
	shares_count?: number | null | undefined;
}

/** Carousel child result from getCarouselChildInsights */
interface CarouselChild {
	id: string;
	position: number;
	mediaType?: string | undefined;
	mediaUrl?: string | undefined;
	metrics: {
		impressions: number;
		reach: number;
		likes: number;
		comments: number;
		shares: number;
		saved: number;
	};
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
// Fetch with Timeout and Rate Limit Logging
// ============================================================================
export async function fetchWithTimeout(
	url: string,
	options: RequestInit = {},
	timeoutMs: number = FETCH_TIMEOUT,
	context?: string,
): Promise<Response> {
	const controller = new AbortController();
	const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

	try {
		const response = await withRetry(
			() =>
				fetch(url, {
					...options,
					signal: controller.signal,
				}),
			{ label: context ?? `analyticsSync:${url.split("?")[0]}` },
		);

		// Log rate limits for monitoring
		if (response.status === 429) {
			const retryAfter = response.headers.get("retry-after") || "unknown";
			logger.warn("Rate limited (429) during analytics refresh", {
				context,
				retryAfter,
				url: url.split("?")[0],
			});
		}

		return response;
	} finally {
		clearTimeout(timeoutId);
	}
}

// ============================================================================
// Fetch Post Insights (Threads)
// ============================================================================
export async function fetchPostInsights(
	postId: string,
	token: string,
): Promise<PostInsights | null> {
	try {
		const insightsUrl = `https://graph.threads.net/v1.0/${postId}/insights?metric=views,likes,replies,reposts,quotes,shares`;
		const response = await fetchWithTimeout(
			insightsUrl,
			{ headers: { Authorization: `Bearer ${token}` } },
			FETCH_TIMEOUT,
			`post:${postId}`,
		);
		const data = await response.json();

		if (!response.ok || data.error) {
			const errCode = data.error?.code;
			const errSubcode = data.error?.error_subcode;
			if (errCode === 100 && (errSubcode === 33 || errSubcode === 2018001)) {
				return { notFound: true } as unknown as PostInsights;
			}
			return null;
		}

		const insights: PostInsights = {
			views: 0,
			likes: 0,
			replies: 0,
			reposts: 0,
			quotes: 0,
			shares: 0,
			clicks: 0,
		};

		if (data.data) {
			data.data.forEach((metric: ThreadsMetricItem) => {
				const name = metric.name;
				const value =
					metric.total_value?.value ??
					metric.values?.[metric.values.length - 1]?.value ??
					0;
				if (name in insights) {
					insights[name as keyof PostInsights] = value;
				}
			});
		}

		return insights;
	} catch (err) {
		logger.warn("[analyticsSync] Failed to fetch post insights", {
			postId,
			error: String(err),
		});
		return null;
	}
}

// ============================================================================
// Threads Account Analytics Refresh
// ============================================================================
export async function refreshThreadsAccountAnalytics(
	account: ThreadsAccountRow,
	syncType: "full" | "metrics" | "recent",
	options: { force?: boolean | undefined } = {},
): Promise<SyncResult> {
	try {
		// Freshness check: "recent" = 25 min, others = 4 hours. Bypassed when force=true.
		if (!options.force) {
			const freshnessMs =
				syncType === "recent" ? 25 * 60 * 1000 : 4 * 60 * 60 * 1000;
			if (account.last_synced_at) {
				const lastSynced = new Date(account.last_synced_at).getTime();
				if (lastSynced > Date.now() - freshnessMs) {
					logger.info("Skipping account (fresh)", {
						username: account.username,
						lastSynced: account.last_synced_at,
					});
					return { success: true, postsUpdated: 0, skipped: true };
				}
			}
		}

		if (!account.threads_access_token_encrypted) {
			logger.warn("[analyticsSync] Skipping Threads account — no token", {
				accountId: account.id,
				username: account.username,
			});
			return { success: true, postsUpdated: 0, skipped: true };
		}
		const token = decrypt(account.threads_access_token_encrypted);
		const threadsUserId = account.threads_user_id;

		// Fetch follower count + clicks - preserve existing on failure
		let followersCount: number | null = null;
		let totalClicks: number | null = null;
		try {
			const insightsUrl = `https://graph.threads.net/v1.0/${threadsUserId}/threads_insights?metric=clicks,followers_count`;
			const insightsResponse = await fetchWithTimeout(
				insightsUrl,
				{ headers: { Authorization: `Bearer ${token}` } },
				FETCH_TIMEOUT,
				`followers:${account.username}`,
			);
			if (!insightsResponse.ok) {
				logger.warn("Follower/clicks insights fetch failed", {
					status: insightsResponse.status,
					accountId: account.id,
				});
				// Don't overwrite existing data with error response
			} else {
				const insightsData = await insightsResponse.json();

				if (insightsData.data) {
					const followerMetric = insightsData.data.find(
						(m: ThreadsMetricItem) => m.name === "followers_count",
					);
					if (followerMetric) {
						const value =
							followerMetric.total_value?.value ??
							followerMetric.values?.[followerMetric.values.length - 1]?.value;
						if (typeof value === "number" && value > 0) {
							followersCount = value;
						}
					}

					// clicks uses link_total_values format (array of {value, link_url})
					const clicksMetric = insightsData.data.find(
						(m: ThreadsMetricItem) => m.name === "clicks",
					);
					if (clicksMetric) {
						if (Array.isArray(clicksMetric.link_total_values)) {
							totalClicks = clicksMetric.link_total_values.reduce(
								(sum: number, entry: { value?: number | undefined }) =>
									sum + (entry.value || 0),
								0,
							);
							// Persist per-link breakdown — sum loses the URLs.
							const linkRows = clicksMetric.link_total_values
								.filter(
									(e: {
										link_url?: string | undefined;
										value?: number | undefined;
									}) => e.link_url && (e.value || 0) > 0,
								)
								.map(
									(e: {
										link_url?: string | undefined;
										value?: number | undefined;
									}) => ({
										account_id: account.id,
										link_url: e.link_url as string,
										clicks: e.value || 0,
									}),
								);
							if (linkRows.length > 0) {
								const { error: linkErr } = await db()
									.from("threads_link_click_breakdown")
									.upsert(linkRows, {
										onConflict: "account_id,fetched_date,link_url",
									});
								if (linkErr) {
									logger.warn(
										"[analyticsSync] threads_link_click_breakdown upsert failed",
										{ error: linkErr.message },
									);
								}
							}
						} else if (clicksMetric.total_value?.value != null) {
							totalClicks = clicksMetric.total_value.value;
						}
					}
				}
			}
		} catch (err) {
			logger.warn(
				"[analyticsSync] Failed to fetch Threads account insights (followers/clicks)",
				{ error: String(err) },
			);
			// Preserve existing value on failure
		}

		// Fetch views broken down by source (home / profile / search / activity /
		// ig / fb) — Threads API added this in July 2025. Time window = 24h so
		// each day's row is a daily snapshot, not a cumulative lifetime (the
		// user-insights endpoint's since/until default is 2 days per Threads API
		// docs §13.2, so we narrow it to one). Preserve existing value on failure
		// (null sentinel keeps yesterday's row intact via COALESCE in the RPC).
		//
		// Response shape is under-documented for the `breakdown=source` param —
		// we parse both known shapes:
		//   (a) follower_demographics-style:
		//       data[0].total_value.breakdowns[0].results[].dimension_values + value
		//   (b) time_series-style: data[0].values[].breakdowns[].dimension_values
		//       + value, one `values` entry per bucket end_time
		let threadsViewsBySource: Record<string, number> | null = null;
		try {
			const nowSec = Math.floor(Date.now() / 1000);
			const since = nowSec - 24 * 60 * 60;
			const viewsUrl =
				`https://graph.threads.net/v1.0/${threadsUserId}/threads_insights` +
				`?metric=views&breakdown=source&since=${since}&until=${nowSec}`;
			const viewsResponse = await fetchWithTimeout(
				viewsUrl,
				{ headers: { Authorization: `Bearer ${token}` } },
				FETCH_TIMEOUT,
				`views-by-source:${account.username}`,
			);
			if (!viewsResponse.ok) {
				logger.warn("Threads views-by-source fetch failed", {
					status: viewsResponse.status,
					accountId: account.id,
				});
			} else {
				const viewsData = await viewsResponse.json();
				const metric = (viewsData?.data ?? []).find(
					(m: ThreadsMetricItem) => m.name === "views",
				) as
					| {
							total_value?:
								| {
										breakdowns?:
											| {
													results?:
														| {
																dimension_values?: string[] | undefined;
																value?: number | undefined;
														  }[]
														| undefined;
											  }[]
											| undefined;
								  }
								| undefined;
							values?:
								| {
										value?: number | undefined;
										breakdowns?:
											| {
													dimension_values?: string[] | undefined;
													value?: number | undefined;
											  }[]
											| undefined;
								  }[]
								| undefined;
					  }
					| undefined;

				const acc: Record<string, number> = {};
				const accumulate = (
					key: string | undefined,
					val: number | undefined,
				) => {
					if (!key || typeof val !== "number" || !Number.isFinite(val)) return;
					const k = key.toLowerCase();
					acc[k] = (acc[k] ?? 0) + val;
				};

				// Shape (a): total_value.breakdowns[0].results
				const totalValueRows = metric?.total_value?.breakdowns?.[0]?.results;
				if (totalValueRows && totalValueRows.length > 0) {
					for (const row of totalValueRows) {
						accumulate(row.dimension_values?.[0], row.value);
					}
				}
				// Shape (b): values[].breakdowns[].dimension_values — aggregate across
				// all time buckets in the since/until window.
				if (Object.keys(acc).length === 0 && metric?.values) {
					for (const entry of metric.values) {
						if (entry.breakdowns) {
							for (const bd of entry.breakdowns) {
								accumulate(bd.dimension_values?.[0], bd.value);
							}
						}
					}
				}

				if (Object.keys(acc).length > 0) {
					threadsViewsBySource = acc;
				} else {
					logger.info(
						"[analyticsSync] Threads views-by-source returned no rows — API may not have emitted a breakdown",
						{ accountId: account.id },
					);
				}
			}
		} catch (err) {
			logger.warn("[analyticsSync] Failed to fetch Threads views-by-source", {
				accountId: account.id,
				error: String(err),
			});
		}

		// Smart post filtering: tier by age for efficient API usage
		// Posts >14 days have stable metrics — skip to reduce API calls
		const now = new Date();
		const sevenDaysAgo = new Date(
			now.getTime() - 7 * 24 * 60 * 60 * 1000,
		).toISOString();
		const fourteenDaysAgo = new Date(
			now.getTime() - 14 * 24 * 60 * 60 * 1000,
		).toISOString();

		// Tier 1: Posts from last 7 days — always fetch (still accumulating engagement)
		const { data: recentPosts, error: recentError } = await db()
			.from("posts")
			.select("id, threads_post_id")
			.eq("account_id", account.id)
			.eq("status", "published")
			.not("threads_post_id", "is", null)
			.gte("published_at", sevenDaysAgo)
			.order("published_at", { ascending: false })
			.limit(50);

		let olderPosts: PostRow[] | null = null;
		let olderError: { message?: string | undefined } | null = null;

		// "recent" syncType: only Tier 1 posts (skip older tiers entirely)
		if (syncType !== "recent") {
			// Tier 2: Posts from 7-14 days ago — sample most-recent 20 (engagement slowing)
			const olderResult = await db()
				.from("posts")
				.select("id, threads_post_id")
				.eq("account_id", account.id)
				.eq("status", "published")
				.not("threads_post_id", "is", null)
				.lt("published_at", sevenDaysAgo)
				.gte("published_at", fourteenDaysAgo)
				.order("published_at", { ascending: false })
				.limit(20);
			olderPosts = olderResult.data;
			olderError = olderResult.error;
		}

		// Posts > 14 days old are skipped (engagement stabilized)
		const posts = [...(recentPosts || []), ...(olderPosts || [])];
		const postsError = recentError || olderError;

		if (postsError || !posts) {
			logger.warn("[sync] Failed to fetch posts for metrics refresh", {
				accountId: account.id,
				error: postsError?.message,
			});
			return {
				success: false,
				postsUpdated: 0,
				error: "Failed to fetch posts",
			};
		}

		if (posts.length === 0) {
			logger.info("[sync] No posts found for metrics refresh", {
				accountId: account.id,
				syncType,
			});
		}

		let postsUpdated = 0;
		let totalViews = 0;
		let totalLikes = 0;
		let totalReplies = 0;
		let totalReposts = 0;
		let totalShares = 0;

		// Fetch insights for each post in batches
		for (let i = 0; i < posts.length; i += POST_BATCH_SIZE) {
			const batch = posts.slice(i, i + POST_BATCH_SIZE);

			const batchSettled = await Promise.allSettled(
				batch.map(async (post: PostRow) => {
					const insights = await fetchPostInsights(
						post.threads_post_id as string,
						token,
					);
					if (insights) {
						return { postId: post.id, insights };
					}
					return null;
				}),
			);

			// Collect updates for batch processing
			const postUpdates: Array<{
				id: string;
				views_count: number;
				likes_count: number;
				replies_count: number;
				reposts_count: number;
				quotes_count: number;
				shares_count: number;
				engagement_rate: number;
				updated_at: string;
			}> = [];
			const deletedPostIds: string[] = [];

			for (const settled of batchSettled) {
				const result = settled.status === "fulfilled" ? settled.value : null;
				if (result) {
					if (
						(result.insights as unknown as { notFound?: boolean | undefined })
							?.notFound
					) {
						deletedPostIds.push(result.postId);
						continue;
					}
					const { postId, insights } = result;

					const engagementRate = calculateEngagementRate(
						{
							views: insights.views,
							likes: insights.likes,
							replies: insights.replies,
							reposts: insights.reposts,
							shares: insights.shares,
						},
						"threads",
					);

					postUpdates.push({
						id: postId,
						views_count: insights.views,
						likes_count: insights.likes,
						replies_count: insights.replies,
						reposts_count: insights.reposts,
						quotes_count: insights.quotes,
						shares_count: insights.shares,
						engagement_rate: engagementRate,
						updated_at: new Date().toISOString(),
					});

					totalViews += insights.views;
					totalLikes += insights.likes;
					totalReplies += insights.replies;
					totalReposts += insights.reposts;
					totalShares += insights.shares;
					postsUpdated++;
				}
			}

			// Mark posts deleted on Meta as 'deleted' locally
			if (deletedPostIds.length > 0) {
				const { error: delErr } = await db()
					.from("posts")
					.update({ status: "deleted", updated_at: new Date().toISOString() })
					.in("id", deletedPostIds);
				if (delErr) {
					logger.warn("[sync] Failed to mark deleted Threads posts", {
						error: delErr.message,
						count: deletedPostIds.length,
					});
				} else {
					logger.info(
						"[sync] Marked Threads posts as deleted (gone from Meta)",
						{ count: deletedPostIds.length, ids: deletedPostIds },
					);
				}
			}

			// Batch update all post metrics (update-only, not upsert, to avoid NOT NULL violations)
			if (postUpdates.length > 0) {
				const updatePromises = postUpdates.map((pu) => {
					const { id, ...fields } = pu;
					return db().from("posts").update(fields).eq("id", id);
				});
				const updateResults = await Promise.allSettled(updatePromises);
				const updateErrors = updateResults.filter(
					(r) =>
						r.status === "rejected" ||
						(r.status === "fulfilled" && r.value.error),
				);
				if (updateErrors.length > 0) {
					const errorDetails = updateErrors.slice(0, 3).map((r) => {
						if (r.status === "rejected") return String(r.reason);
						if (r.status === "fulfilled" && r.value.error)
							return r.value.error.message;
						return "unknown";
					});
					logger.error("[sync] Threads posts update failed", {
						errorCount: updateErrors.length,
						count: postUpdates.length,
						errors: errorDetails,
					});
				}
			}

			// Insert post_metric_history snapshots for content decay tracking
			if (postUpdates.length > 0) {
				try {
					// Fetch published_at for these posts to calculate hours_since_publish
					const postIds = postUpdates.map((p) => p.id);
					const { data: postDates } = (await db()
						.from("posts")
						.select("id, published_at, account_id, media_type")
						.in("id", postIds)) as {
						data: PostDateRow[] | null;
						error: unknown;
					};

					const publishedAtMap = new Map<
						string,
						{ published_at: string; account_id: string }
					>();
					if (postDates) {
						for (const p of postDates) {
							publishedAtMap.set(p.id, {
								published_at: p.published_at as string,
								account_id: p.account_id as string,
							});
						}
					}

					const historyRows = postUpdates.map((p) => {
						const info = publishedAtMap.get(p.id);
						const hoursSincePublish = info?.published_at
							? (Date.now() - new Date(info.published_at).getTime()) /
								(1000 * 60 * 60)
							: null;
						return {
							post_id: p.id,
							account_id: info?.account_id || account.id,
							platform: "threads",
							hours_since_publish:
								hoursSincePublish !== null
									? Math.round(hoursSincePublish * 100) / 100
									: null,
							views_count: p.views_count,
							likes_count: p.likes_count,
							replies_count: p.replies_count,
							reposts_count: p.reposts_count,
							quotes_count: p.quotes_count || 0,
							shares_count: p.shares_count,
							engagement_rate: p.engagement_rate,
						};
					});

					if (historyRows.length > 0) {
						await db().from("post_metric_history").insert(historyRows);
					}

					// Retention: delete metric history older than 90 days
					await db()
						.from("post_metric_history")
						.delete()
						.eq("account_id", account.id)
						.lt(
							"created_at",
							new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString(),
						);
				} catch (histErr: unknown) {
					logger.error(
						"post_metric_history insert failed — historical data lost",
						{
							error:
								histErr instanceof Error ? histErr.message : String(histErr),
						},
					);
				}
			}

			// Small delay between post batches
			if (i + POST_BATCH_SIZE < posts.length) {
				await new Promise((resolve) => setTimeout(resolve, 50));
			}
		}

		// ── Viral Score Calibration Feedback Loop ──
		// For posts 48h+ old with a predicted_viral_score, compare predicted vs actual
		if (syncType === "full") {
			try {
				const fortyEightHoursAgo = new Date(
					Date.now() - 48 * 60 * 60 * 1000,
				).toISOString();
				const { data: calibratablePosts } = await db()
					.from("posts")
					.select(
						"id, user_id, predicted_viral_score, views_count, likes_count, replies_count, reposts_count, shares_count, published_at",
					)
					.eq("account_id", account.id)
					.eq("status", "published")
					.not("predicted_viral_score", "is", null)
					.lt("published_at", fortyEightHoursAgo);

				if (calibratablePosts && calibratablePosts.length > 0) {
					// Get user's full post history for percentile computation
					const userId = calibratablePosts[0]!.user_id;
					const { data: allUserPosts } = await db()
						.from("posts")
						.select(
							"views_count, likes_count, replies_count, reposts_count, shares_count",
						)
						.eq("account_id", account.id)
						.eq("status", "published")
						.not("views_count", "is", null)
						.order("published_at", { ascending: false })
						.limit(5000);

					if (allUserPosts && allUserPosts.length >= 5) {
						// Check which posts already have calibration entries
						const postIds = calibratablePosts.map((p) => p.id);
						const { data: existingCalibrations } = await db()
							.from("viral_score_calibration")
							.select("post_id")
							.in("post_id", postIds);
						const existingSet = new Set(
							(existingCalibrations || []).map((c) => c.post_id),
						);

						const newCalibrations = calibratablePosts
							.filter((p) => !existingSet.has(p.id))
							.map((p) => {
								const actual = computeActualPerformancePercentile(
									p,
									allUserPosts,
								);
								return {
									user_id: userId,
									post_id: p.id,
									predicted: p.predicted_viral_score!,
									actual,
								};
							});

						if (newCalibrations.length > 0) {
							await db()
								.from("viral_score_calibration")
								.insert(newCalibrations);
							logger.info("Viral score calibration entries created", {
								count: newCalibrations.length,
								username: account.username,
							});
						}
					}
				}
			} catch (calErr: unknown) {
				logger.warn("Viral score calibration failed (non-fatal)", {
					username: account.username,
					error: calErr instanceof Error ? calErr.message : String(calErr),
				});
			}
		}

		// Update account stats - only include followers_count if we got a valid value
		const accountUpdate: Record<string, unknown> = {
			last_synced_at: new Date().toISOString(),
			updated_at: new Date().toISOString(),
		};
		if (followersCount !== null) {
			accountUpdate.followers_count = followersCount;
		}
		await db().from("accounts").update(accountUpdate).eq("id", account.id);

		// Fetch and store Threads demographics
		if (syncType === "full") {
			try {
				const { getThreadsDemographics } = await import("./threadsApi.js");
				const demoResult = await getThreadsDemographics(
					account.threads_access_token_encrypted,
					threadsUserId,
				);
				if (demoResult.success && demoResult.breakdowns) {
					for (const bd of demoResult.breakdowns) {
						const total = bd.values.reduce((s, v) => s + v.count, 0);
						const rows = bd.values.map((v) => ({
							account_id: account.id,
							platform: "threads" as const,
							audience_type: "followers" as const,
							breakdown_type: bd.breakdown_type,
							breakdown_value: v.value,
							count: v.count,
							percentage: total > 0 ? (v.count / total) * 100 : 0,
						}));
						if (rows.length > 0) {
							await db().from("audience_demographics").upsert(rows, {
								onConflict:
									"account_id,platform,audience_type,breakdown_type,breakdown_value,fetched_date",
							});
						}
					}
					logger.info("Threads demographics stored", {
						username: account.username,
					});
				}
			} catch (demoErr: unknown) {
				logger.warn("Threads demographics failed (non-fatal)", {
					username: account.username,
					error: demoErr instanceof Error ? demoErr.message : String(demoErr),
				});
			}
		}

		// Store daily analytics snapshot
		// Analytics dates are always UTC (toISOString). This is intentional — all
		// aggregations use UTC boundaries to avoid timezone-dependent drift.
		const todayKey = new Date().toISOString().split("T")[0]!;

		// Sum totals from ALL published posts in DB (not just current sync batch)
		// This ensures total_views reflects the full account, not just tiered fetch
		let dbTotalViews = totalViews;
		let dbTotalLikes = totalLikes;
		let dbTotalReplies = totalReplies;
		let dbTotalReposts = totalReposts;
		let dbTotalQuotes = 0;
		let dbTotalShares = totalShares;
		let publishedCount = posts.length;
		try {
			// Sum ALL published posts in DB — lifetime totals, consistent with "latest"
			// aggregation semantics in metricRegistry.ts and with the IG sync path.
			// Older posts have stale metrics but that error is small; a 14-day window
			// caused severe undercount by ignoring all engagement on older posts.
			const sumsResult = await db()
				.from("posts")
				.select(
					"views_count, likes_count, replies_count, reposts_count, quotes_count, shares_count",
				)
				.eq("account_id", account.id)
				.eq("platform", "threads")
				.eq("status", "published");
			const sums = sumsResult.data as PostSumRow[] | null;
			if (sumsResult.error) {
				logger.warn("Threads post sums query error", {
					accountId: account.id,
					error: String(sumsResult.error),
				});
			}
			if (sums && sums.length > 0) {
				publishedCount = sums.length;
				dbTotalViews = 0;
				dbTotalLikes = 0;
				dbTotalReplies = 0;
				dbTotalReposts = 0;
				dbTotalQuotes = 0;
				dbTotalShares = 0;
				for (const p of sums) {
					dbTotalViews += p.views_count || 0;
					dbTotalLikes += p.likes_count || 0;
					dbTotalReplies += p.replies_count || 0;
					dbTotalReposts += p.reposts_count || 0;
					dbTotalQuotes += p.quotes_count || 0;
					dbTotalShares += p.shares_count || 0;
				}
			}
		} catch (sumErr) {
			logger.warn(
				"Failed to sum post totals from DB, using sync batch totals",
				{
					accountId: account.id,
					error: String(sumErr),
				},
			);
		}

		const engagementRate = calculateEngagementRate(
			{
				views: dbTotalViews,
				likes: dbTotalLikes,
				replies: dbTotalReplies,
				reposts: dbTotalReposts,
				shares: dbTotalShares,
			},
			"threads",
		);

		// Build analytics data - only include followers if we got a valid value
		const analyticsData: Record<string, unknown> = {
			account_id: account.id,
			date: todayKey,
			total_views: dbTotalViews,
			total_likes: dbTotalLikes,
			total_replies: dbTotalReplies,
			total_reposts: dbTotalReposts,
			total_quotes: dbTotalQuotes,
			total_shares: dbTotalShares,
			posts_count: publishedCount,
			engagement_rate: engagementRate,
		};

		if (totalClicks !== null) {
			analyticsData.total_clicks = totalClicks;
		}

		if (threadsViewsBySource) {
			analyticsData.threads_views_by_source = threadsViewsBySource;
		}

		// Only calculate and store follower data if we got a valid count
		if (followersCount !== null) {
			analyticsData.followers_count = followersCount;

			// Calculate follower growth from previous day's data
			let followerGrowth = 0;
			try {
				// Get yesterday's date
				const yesterday = new Date();
				yesterday.setDate(yesterday.getDate() - 1);
				const yesterdayKey = yesterday.toISOString().split("T")[0]!;

				// Fetch previous day's follower count
				const { data: previousData } = await db()
					.from("account_analytics")
					.select("followers_count")
					.eq("account_id", account.id)
					.eq("date", yesterdayKey)
					.maybeSingle();

				if (previousData?.followers_count) {
					followerGrowth = followersCount - previousData.followers_count;
				} else {
					// No previous data - try to get the most recent historical entry
					const { data: latestData } = await db()
						.from("account_analytics")
						.select("followers_count, date")
						.eq("account_id", account.id)
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
					"[analyticsSync] Failed to calculate Threads follower growth",
					{ error: String(err) },
				);
				// No historical data - first time tracking, growth is 0
			}
			analyticsData.follower_growth = followerGrowth;
		}

		// High-water mark guard: engagement metrics can only increase organically.
		// Multiple syncs per day can regress values due to partial post refresh.
		// Fetch today's existing row (if any) and ensure we never write lower values.
		try {
			const { data: existingRow } = await db()
				.from("account_analytics")
				.select(
					"total_views, total_likes, total_replies, total_reposts, total_quotes, total_shares, total_clicks",
				)
				.eq("account_id", account.id)
				.eq("date", todayKey)
				.maybeSingle();
			if (existingRow) {
				const guard = (col: string) => {
					const existing =
						(existingRow as Record<string, number | null>)[col] ?? 0;
					const incoming = (analyticsData[col] as number) ?? 0;
					if (incoming < existing) {
						analyticsData[col] = existing;
					}
				};
				guard("total_views");
				guard("total_likes");
				guard("total_replies");
				guard("total_reposts");
				guard("total_quotes");
				guard("total_shares");
				guard("total_clicks");
			}
		} catch (_hwmErr) {
			// Non-fatal — write the data as-is if guard query fails
		}

		// Atomic upsert: account_analytics + account_metrics_history in one transaction
		// biome-ignore lint/suspicious/noExplicitAny: RPC not in generated types
		const { error: rpcError } = await (db() as any).rpc(
			"upsert_account_analytics_atomic",
			{
				p_analytics: analyticsData,
				p_metrics_history: {
					account_id: account.id,
					platform: "threads",
					date: todayKey,
					followers_count: (analyticsData.followers_count as number) ?? 0,
					total_views: dbTotalViews,
					total_likes: dbTotalLikes,
					total_replies: dbTotalReplies,
					total_reposts: dbTotalReposts,
					total_shares: dbTotalShares,
					engagement_rate: engagementRate,
					posts_count: publishedCount,
				},
			},
		);
		if (rpcError) {
			logger.warn(
				"Atomic analytics upsert failed, falling back to direct upsert",
				{
					accountId: account.id,
					error: rpcError.message ?? JSON.stringify(rpcError),
				},
			);
			// Fallback: direct upsert (non-atomic, but better than losing data)
			await db()
				.from("account_analytics")
				.upsert(analyticsData as Record<string, unknown>, {
					onConflict: "account_id,date",
				});
			await db()
				.from("account_metrics_history")
				.upsert(
					{
						account_id: account.id,
						platform: "threads",
						date: todayKey,
						followers_count: (analyticsData.followers_count as number) ?? 0,
						total_views: dbTotalViews,
						total_likes: dbTotalLikes,
						total_replies: dbTotalReplies,
						total_reposts: dbTotalReposts,
						total_shares: dbTotalShares,
						engagement_rate: engagementRate,
						posts_count: publishedCount,
					} as Record<string, unknown>,
					{ onConflict: "account_id,date" },
				);
		}

		return { success: true, postsUpdated };
	} catch (error: unknown) {
		const message = error instanceof Error ? error.message : String(error);
		logger.error("Analytics refresh error for account", {
			username: account.username,
			error: message,
		});
		return { success: false, postsUpdated: 0, error: message };
	}
}

// ============================================================================
// Instagram Account Analytics Refresh
// ============================================================================
export async function refreshInstagramAccountAnalytics(
	account: IGAccountRow,
	syncType: "full" | "metrics",
	options: { force?: boolean | undefined } = {},
): Promise<SyncResult> {
	try {
		// Skip if recently synced (within 4 hours). Bypassed when force=true.
		if (!options.force && account.last_synced_at) {
			const lastSynced = new Date(account.last_synced_at).getTime();
			const fourHoursAgo = Date.now() - 4 * 60 * 60 * 1000;
			if (lastSynced > fourHoursAgo) {
				logger.info("Skipping IG account (fresh)", {
					username: account.username,
					lastSynced: account.last_synced_at,
				});
				return { success: true, postsUpdated: 0, skipped: true };
			}
		}

		// Early exit: skip IG sync entirely if no token available
		if (!account.instagram_access_token_encrypted) {
			logger.warn("Skipping IG sync — no access token", {
				username: account.username,
				accountId: account.id,
			});
			return { success: true, postsUpdated: 0, skipped: true };
		}

		const {
			getInstagramPostMetrics,
			getInstagramStoryMetrics,
			getInstagramAccountInsights,
		} = await import("./instagramApi.js");
		const loginType = account.login_type || "facebook";

		// Smart post filtering: tier by age for efficient API usage
		// Posts >14 days have stable metrics — only fetch recent posts
		const now = new Date();
		const sevenDaysAgo = new Date(
			now.getTime() - 7 * 24 * 60 * 60 * 1000,
		).toISOString();
		const fourteenDaysAgo = new Date(
			now.getTime() - 14 * 24 * 60 * 60 * 1000,
		).toISOString();

		// Tier 1: Posts from last 7 days — always fetch
		const { data: recentPosts, error: recentError } = await db()
			.from("posts")
			.select("id, instagram_post_id, ig_media_type, content_surface")
			.eq("instagram_account_id", account.id)
			.eq("status", "published")
			.eq("platform", "instagram")
			.not("instagram_post_id", "is", null)
			.gte("published_at", sevenDaysAgo)
			.order("published_at", { ascending: false })
			.limit(50);

		// Tier 2: Posts from 7-14 days ago — sample max 10 (engagement slowing)
		const { data: olderPosts, error: olderError } = await db()
			.from("posts")
			.select("id, instagram_post_id, ig_media_type, content_surface")
			.eq("instagram_account_id", account.id)
			.eq("status", "published")
			.eq("platform", "instagram")
			.not("instagram_post_id", "is", null)
			.lt("published_at", sevenDaysAgo)
			.gte("published_at", fourteenDaysAgo)
			.order("published_at", { ascending: false })
			.limit(10);

		const posts = [...(recentPosts || []), ...(olderPosts || [])];
		const postsError = recentError || olderError;

		if (postsError || !posts) {
			return {
				success: false,
				postsUpdated: 0,
				error: "Failed to fetch Instagram posts",
			};
		}

		let postsUpdated = 0;

		// Split posts into stories (individual calls) and regular posts (batch API)
		// Stories expire after 24h on Meta — skip expired ones to avoid code 100 errors
		const twentyFourHoursAgoMs = now.getTime() - 24 * 60 * 60 * 1000;
		const storyPosts = posts.filter(
			(p: PostRow) =>
				p.ig_media_type === "STORIES" &&
				p.published_at &&
				new Date(p.published_at).getTime() > twentyFourHoursAgoMs,
		);
		const regularPosts = posts.filter(
			(p: PostRow) => p.ig_media_type !== "STORIES",
		);

		// ── Stories: individual calls (batch API doesn't support story insights) ──
		for (let i = 0; i < storyPosts.length; i += POST_BATCH_SIZE) {
			const chunk = storyPosts.slice(i, i + POST_BATCH_SIZE);
			const storyResults = await Promise.allSettled(
				chunk.map(async (post: PostRow) => {
					const result = await getInstagramStoryMetrics(
						account.instagram_access_token_encrypted,
						post.instagram_post_id as string,
						loginType,
					);
					if (result.success && result.metrics) {
						return { postId: post.id, storyMetrics: result.metrics };
					}
					return null;
				}),
			);

			const storyUpdates: Array<Record<string, unknown>> = [];
			for (const settled of storyResults) {
				if (settled.status === "rejected") continue;
				const result = settled.value;
				if (!result) continue;
				storyUpdates.push({
					id: result.postId,
					ig_views: result.storyMetrics.views,
					ig_impressions: result.storyMetrics.views, // backwards compat
					ig_reach: result.storyMetrics.reach,
					ig_story_exits: result.storyMetrics.exits,
					ig_story_replies: result.storyMetrics.replies,
					ig_story_taps_forward: result.storyMetrics.taps_forward,
					ig_story_taps_back: result.storyMetrics.taps_back,
					ig_follows_count: result.storyMetrics.follows ?? 0,
					ig_profile_visits: result.storyMetrics.profile_visits ?? 0,
					ig_post_profile_activity:
						result.storyMetrics.profile_activity ?? null,
					updated_at: new Date().toISOString(),
				});
				postsUpdated++;
			}
			if (storyUpdates.length > 0) {
				// UPDATE only — never INSERT. These are existing posts from our DB query.
				// Upsert was incorrectly INSERTing when id didn't match, failing on NOT NULL user_id.
				for (const su of storyUpdates) {
					const { id: storyId, ...metrics } = su;
					const { error: storyErr } = await db()
						.from("posts")
						.update(metrics)
						.eq("id", storyId as string);
					if (storyErr) {
						logger.error("[sync] IG story update failed", {
							error: storyErr.message,
							postId: storyId,
						});
					}
				}
			}
		}

		// ── Regular posts: parallel individual calls ──
		// Batch API requires Facebook Login tokens (graph.facebook.com).
		// Instagram Business Login accounts don't support it, so we skip batch
		// entirely and use parallel individual calls for all login types.
		const CHUNK_SIZE = 20;
		for (let i = 0; i < regularPosts.length; i += CHUNK_SIZE) {
			const chunk = regularPosts.slice(i, i + CHUNK_SIZE);

			const postUpdates: Array<Record<string, unknown>> = [];
			const deletedPostIds: string[] = [];

			const results = await Promise.allSettled(
				chunk.map((post) =>
					getInstagramPostMetrics(
						account.instagram_access_token_encrypted,
						post.instagram_post_id as string,
						loginType,
						post.ig_media_type || undefined,
						post.content_surface || undefined,
					).then((result) => ({ post, result })),
				),
			);
			for (const settled of results) {
				if (settled.status === "rejected") continue;
				const { post, result } = settled.value;
				if (
					(result as unknown as { notFound?: boolean | undefined }).notFound
				) {
					deletedPostIds.push(post.id);
					continue;
				}
				if (result.success && result.metrics) {
					const m = result.metrics;
					const engagementRate = calculateEngagementRate(
						{
							likes: m.likes,
							comments: m.comments,
							shares: m.shares,
							saves: m.saved,
							reach: m.reach,
							impressions: m.views,
						},
						"instagram",
					);
					postUpdates.push({
						id: post.id,
						ig_views: m.views,
						ig_impressions: m.views, // backwards compat
						ig_reach: m.reach,
						likes_count: m.likes,
						ig_comment_count: m.comments,
						ig_shares: m.shares,
						ig_saved: m.saved,
						ig_reposts: m.reposts,
						ig_skip_rate: m.reels_skip_rate,
						ig_facebook_views: m.facebook_views,
						ig_crossposted_views: m.crossposted_views,
						ig_reels_avg_watch_time: m.ig_reels_avg_watch_time,
						ig_reels_video_view_total_time: m.ig_reels_video_view_total_time,
						ig_clips_replays_count: m.clips_replays_count,
						ig_reels_aggregated_all_plays_count:
							m.ig_reels_aggregated_all_plays_count,
						ig_follows_count: m.follows ?? 0,
						ig_post_profile_activity: m.profileActivity ?? null,
						// Derived from the profile_activity action_type breakdown in
						// getInstagramPostMetrics. Drives ProfileVisitsTile +
						// account_analytics.ig_profile_views rollup (analyticsSync :1856).
						ig_profile_visits: m.profile_visits ?? 0,
						engagement_rate: engagementRate,
						updated_at: new Date().toISOString(),
					});
					postsUpdated++;
				}
			}

			// Mark posts deleted on Meta as 'deleted' locally
			if (deletedPostIds.length > 0) {
				const { error: delErr } = await db()
					.from("posts")
					.update({ status: "deleted", updated_at: new Date().toISOString() })
					.in("id", deletedPostIds);
				if (delErr) {
					logger.warn("[sync] Failed to mark deleted IG posts", {
						error: delErr.message,
						count: deletedPostIds.length,
					});
				} else {
					logger.info("[sync] Marked IG posts as deleted (gone from Meta)", {
						count: deletedPostIds.length,
						ids: deletedPostIds,
					});
				}
			}

			// Batch update all post metrics (update-only, not upsert, to avoid NOT NULL violations)
			if (postUpdates.length > 0) {
				const updatePromises = postUpdates.map((pu) => {
					const { id, ...fields } = pu;
					return db()
						.from("posts")
						.update(fields)
						.eq("id", id as string);
				});
				const updateResults = await Promise.allSettled(updatePromises);
				const updateErrors = updateResults.filter(
					(r) =>
						r.status === "rejected" ||
						(r.status === "fulfilled" && r.value.error),
				);
				if (updateErrors.length > 0) {
					logger.error("[sync] IG posts update failed", {
						errorCount: updateErrors.length,
						count: postUpdates.length,
					});
				}

				// Insert post_metric_history snapshots for IG content decay tracking
				try {
					const igPostIds = postUpdates.map((p) => p.id as string);
					const { data: igPostDates } = (await db()
						.from("posts")
						.select("id, published_at, instagram_account_id")
						.in("id", igPostIds)) as unknown as {
						data: PostDateRow[] | null;
						error: unknown;
					};

					const igPublishedAtMap = new Map<
						string,
						{ published_at: string; account_id: string }
					>();
					if (igPostDates) {
						for (const p of igPostDates) {
							igPublishedAtMap.set(p.id, {
								published_at: p.published_at as string,
								account_id: (p.instagram_account_id || account.id) as string,
							});
						}
					}

					const igHistoryRows = postUpdates.map((p) => {
						const info = igPublishedAtMap.get(p.id as string);
						const hoursSincePublish = info?.published_at
							? (Date.now() - new Date(info.published_at).getTime()) /
								(1000 * 60 * 60)
							: null;
						return {
							post_id: p.id,
							account_id: info?.account_id || account.id,
							platform: "instagram",
							hours_since_publish:
								hoursSincePublish !== null
									? Math.round(hoursSincePublish * 100) / 100
									: null,
							views_count: p.ig_impressions || 0,
							likes_count: p.likes_count || 0,
							replies_count: p.ig_comment_count || 0,
							shares_count: p.ig_shares || 0,
							saves_count: p.ig_saved || 0,
							reach: p.ig_reach || 0,
							reposts_count: 0,
							quotes_count: 0,
							engagement_rate: p.engagement_rate,
						};
					});

					if (igHistoryRows.length > 0) {
						await db()
							.from("post_metric_history")
							// biome-ignore lint/suspicious/noExplicitAny: Supabase insert typed payload
							.insert(igHistoryRows as any);
					}

					// Retention: delete metric history older than 90 days
					await db()
						.from("post_metric_history")
						.delete()
						.eq("account_id", account.id)
						.lt(
							"created_at",
							new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString(),
						);
				} catch (igHistErr: unknown) {
					logger.error(
						"IG post_metric_history insert failed — historical data lost",
						{
							error:
								igHistErr instanceof Error
									? igHistErr.message
									: String(igHistErr),
						},
					);
				}
			}

			// Small delay between API batches
			if (i + CHUNK_SIZE < regularPosts.length) {
				await new Promise((resolve) => setTimeout(resolve, 50));
			}
		}

		// ========================================================================
		// Fetch account-level insights (reach, followers, engagement, etc.)
		// ========================================================================
		let igFollowersCount: number | null = null;
		const todayKey = new Date().toISOString().split("T")[0]!;
		const igAnalyticsData: Record<string, unknown> = {
			account_id: account.id,
			date: todayKey,
			posts_count: posts.length, // overwritten by full count from igPostSums query below
		};

		try {
			// Skip insights API call for accounts already known to lack permissions
			const noInsightsKey = `ig-no-insights:${account.id}`;
			const noInsightsFlag = await getRedis()
				.get(noInsightsKey)
				.catch(() => null);

			if (noInsightsFlag) {
				logger.debug("Skipping IG insights (permissions previously missing)", {
					username: account.username,
				});
				// Still preserve last-known follower count
				if ((account.follower_count ?? 0) > 0) {
					igFollowersCount = account.follower_count ?? null;
					igAnalyticsData.followers_count = account.follower_count ?? 0;
				}
			} else if (!account.instagram_access_token_encrypted) {
				logger.warn("IG insights skipped — no token", {
					username: account.username,
					accountId: account.id,
				});
			} else {
				const insightsResult = await getInstagramAccountInsights(
					account.instagram_access_token_encrypted,
					account.instagram_user_id,
					"day",
					loginType,
				);

				if (insightsResult.success && insightsResult.insights) {
					const ins = insightsResult.insights;
					const missing = new Set(insightsResult.missingMetrics ?? []);

					// IG account-level API only provides reach + total_interactions (not likes/replies/shares separately).
					// Only write fields that were actually returned — never overwrite historical data with API zeros.
					igAnalyticsData.total_reach = ins.reach;
					igAnalyticsData.ig_reach = ins.reach;
					if (!missing.has("views") && ins.views > 0) {
						igAnalyticsData.total_views = ins.views;
					}

					if (!missing.has("total_interactions")) {
						igAnalyticsData.ig_total_interactions = ins.totalInteractions;
						igAnalyticsData.total_reposts = ins.reposts;
					}
					if (!missing.has("accounts_engaged")) {
						igAnalyticsData.ig_accounts_engaged = ins.accountsEngaged;
					}
					if (!missing.has("profile_links_taps")) {
						igAnalyticsData.ig_profile_views = ins.profileViews;
						igAnalyticsData.ig_website_clicks =
							ins.websiteClicks || ins.profileLinksTaps;
					}
					if (!missing.has("views") && ins.views > 0) {
						igAnalyticsData.ig_impressions = ins.views;
					} else if (!missing.has("impressions") && ins.impressions > 0) {
						igAnalyticsData.ig_impressions = ins.impressions;
					}
					if (ins.newFollows !== undefined) {
						igAnalyticsData.ig_new_follows = ins.newFollows;
					}
					if (ins.unfollows !== undefined) {
						igAnalyticsData.ig_unfollows = ins.unfollows;
					}
					if (ins.contentTypeBreakdown) {
						igAnalyticsData.ig_content_type_breakdown =
							ins.contentTypeBreakdown;
					}

					// Followers: use API value if available, fall back to profile node, then cached DB value
					if (!missing.has("follower_count") && ins.followerCount > 0) {
						igFollowersCount = ins.followerCount;
						igAnalyticsData.followers_count = ins.followerCount;
					} else if (missing.has("follower_count")) {
						// Insights API omitted follower_count (<100 followers or permission issue).
						// Fall back to the profile node which always exposes followers_count.
						const { getIgFollowerCount } = await import("./instagramApi.js");
						const profileCount = await getIgFollowerCount(
							account.instagram_access_token_encrypted,
							account.instagram_user_id,
							loginType,
						);
						if (profileCount !== null && profileCount > 0) {
							igFollowersCount = profileCount;
							igAnalyticsData.followers_count = profileCount;
							logger.debug("IG follower_count from profile node fallback", {
								username: account.username,
								followers: profileCount,
							});
						} else if ((account.follower_count ?? 0) > 0) {
							igFollowersCount = account.follower_count ?? null;
							igAnalyticsData.followers_count = account.follower_count ?? 0;
						}
					} else if ((account.follower_count ?? 0) > 0) {
						igFollowersCount = account.follower_count ?? null;
						igAnalyticsData.followers_count = account.follower_count ?? 0;
					}

					// Engagement rate only when both sides of the equation were returned
					if (ins.reach > 0 && !missing.has("total_interactions")) {
						igAnalyticsData.engagement_rate =
							(ins.totalInteractions / ins.reach) * 100;
					}

					// Store reach breakdown if available. Absolute follower/non-follower
					// counts (captured by insights.ts from breakdown=follower_type) unlock
					// the stacked-area chart; the pct alone only supports a trendline.
					const insExtended = ins as typeof ins & {
						nonFollowerReachPct?: number | undefined;
						followerReach?: number | undefined;
						nonFollowerReach?: number | undefined;
					};
					if (insExtended.nonFollowerReachPct !== undefined) {
						igAnalyticsData.ig_non_follower_reach_pct =
							insExtended.nonFollowerReachPct;
					}
					if (insExtended.followerReach !== undefined) {
						igAnalyticsData.ig_follower_reach = insExtended.followerReach;
					}
					if (insExtended.nonFollowerReach !== undefined) {
						igAnalyticsData.ig_non_follower_reach =
							insExtended.nonFollowerReach;
					}

					logger.info("IG account insights fetched", {
						username: account.username,
						reach: ins.reach,
						followers: igAnalyticsData.followers_count ?? ins.followerCount,
						engaged: ins.accountsEngaged,
						interactions: ins.totalInteractions,
						partial: insightsResult.partial ?? false,
					});

					// Cache permission-missing state for 24 hours to avoid redundant API calls
					if (insightsResult.partial && missing.has("accounts_engaged")) {
						await getRedis()
							.set(noInsightsKey, "1", { ex: 86400 })
							.catch((error) => {
								logger.warn(
									"[analyticsSync] Failed to cache missing insights state",
									{
										accountId: account.id,
										username: account.username,
										error: String(error),
									},
								);
							});
						logger.warn("IG account flagged: insights permissions missing", {
							username: account.username,
							missingMetrics: insightsResult.missingMetrics,
						});
					}
				} else {
					logger.warn("IG account insights unavailable", {
						username: account.username,
						error: insightsResult.error,
					});
					// Cache hard auth failures (401/token errors) for 24h to stop retrying every cycle
					const { isDefinitiveOAuthError } = await import("./retryUtils.js");
					if (
						insightsResult.error &&
						(isDefinitiveOAuthError(insightsResult.error) ||
							insightsResult.error.includes("not a confirmed user"))
					) {
						await getRedis()
							.set(noInsightsKey, "1", { ex: 86400 })
							.catch((error) => {
								logger.warn(
									"[analyticsSync] Failed to cache definitive insights auth failure",
									{
										accountId: account.id,
										username: account.username,
										error: String(error),
									},
								);
							});
						logger.warn(
							"IG account flagged: token invalid or unconfirmed user",
							{
								username: account.username,
							},
						);
					}
					// Preserve last-known follower count on API failure
					if ((account.follower_count ?? 0) > 0) {
						igFollowersCount = account.follower_count ?? null;
						igAnalyticsData.followers_count = account.follower_count ?? 0;
					}
				}
			}
		} catch (insightsErr: unknown) {
			logger.warn("IG account insights failed (non-fatal)", {
				username: account.username,
				error:
					insightsErr instanceof Error
						? insightsErr.message
						: String(insightsErr),
			});
		}

		// Fetch demographics, online followers, and tagged media in parallel
		if (syncType === "full") {
			await Promise.allSettled([
				// Demographics
				(async () => {
					try {
						const { getInstagramDemographics } = await import(
							"./instagramApi.js"
						);
						const demoResult = await getInstagramDemographics(
							account.instagram_access_token_encrypted,
							account.instagram_user_id,
							loginType,
						);
						if (demoResult.success && demoResult.breakdowns) {
							for (const bd of demoResult.breakdowns) {
								const total = bd.values.reduce((s, v) => s + v.count, 0);
								const rows = bd.values.map((v) => ({
									account_id: account.id,
									instagram_account_id: account.id,
									platform: "instagram" as const,
									audience_type: "followers" as const,
									breakdown_type: bd.breakdown_type,
									breakdown_value: v.value,
									count: v.count,
									percentage: total > 0 ? (v.count / total) * 100 : 0,
								}));
								if (rows.length > 0) {
									await db().from("audience_demographics").upsert(rows, {
										onConflict:
											"account_id,platform,audience_type,breakdown_type,breakdown_value,fetched_date",
									});
								}
							}
							logger.info("IG demographics stored", {
								username: account.username,
							});
						}
						// engaged_audience_demographics — same shape, audience_type='engaged'
						if (demoResult.success && demoResult.engagedBreakdowns) {
							for (const bd of demoResult.engagedBreakdowns) {
								const total = bd.values.reduce((s, v) => s + v.count, 0);
								const rows = bd.values.map((v) => ({
									account_id: account.id,
									instagram_account_id: account.id,
									platform: "instagram" as const,
									audience_type: "engaged" as const,
									breakdown_type: bd.breakdown_type,
									breakdown_value: v.value,
									count: v.count,
									percentage: total > 0 ? (v.count / total) * 100 : 0,
								}));
								if (rows.length > 0) {
									await db().from("audience_demographics").upsert(rows, {
										onConflict:
											"account_id,platform,audience_type,breakdown_type,breakdown_value,fetched_date",
									});
								}
							}
							logger.info("IG engaged demographics stored", {
								username: account.username,
							});
						}
					} catch (demoErr: unknown) {
						logger.warn("IG demographics failed (non-fatal)", {
							username: account.username,
							error:
								demoErr instanceof Error ? demoErr.message : String(demoErr),
						});
					}
				})(),
				// Online followers
				(async () => {
					try {
						const { getOnlineFollowers } = await import("./instagramApi.js");
						const onlineResult = await getOnlineFollowers(
							account.instagram_access_token_encrypted,
							account.instagram_user_id,
							loginType,
						);
						if (onlineResult.success && onlineResult.data) {
							igAnalyticsData.ig_online_followers = onlineResult.data;
							logger.info("IG online followers fetched", {
								username: account.username,
							});
						}
					} catch (onlineErr: unknown) {
						logger.warn("IG online followers failed (non-fatal)", {
							username: account.username,
							error:
								onlineErr instanceof Error
									? onlineErr.message
									: String(onlineErr),
						});
					}
				})(),
				// Tagged media
				(async () => {
					try {
						const { getTaggedMedia } = await import("./instagramApi.js");
						const taggedResult = await getTaggedMedia(
							account.instagram_access_token_encrypted,
							account.instagram_user_id,
							loginType,
						);
						if (taggedResult.success && taggedResult.media) {
							igAnalyticsData.ig_tagged_media_count = taggedResult.media.length;
						}
					} catch (taggedErr: unknown) {
						logger.warn("IG tagged media count failed (non-fatal)", {
							username: account.username,
							error:
								taggedErr instanceof Error
									? taggedErr.message
									: String(taggedErr),
						});
					}
				})(),
			]);
		}

		// Sync carousel child insights for CAROUSEL_ALBUM posts
		if (syncType === "full") {
			try {
				const { getCarouselChildInsights } = await import("./instagramApi.js");
				const carouselPosts = posts.filter(
					(p: PostRow) =>
						p.ig_media_type === "CAROUSEL_ALBUM" && p.instagram_post_id,
				);

				for (const cp of carouselPosts.slice(0, 10)) {
					const childResult = await getCarouselChildInsights(
						account.instagram_access_token_encrypted,
						cp.instagram_post_id as string,
						loginType,
					);
					if (
						childResult.success &&
						childResult.children &&
						childResult.children.length > 0
					) {
						const rows = childResult.children.map((c: CarouselChild) => ({
							post_id: cp.id,
							child_media_id: c.id,
							position: c.position,
							media_type: c.mediaType,
							media_url: c.mediaUrl,
							impressions: c.metrics.impressions,
							reach: c.metrics.reach,
							likes: c.metrics.likes,
							comments: c.metrics.comments,
							shares: c.metrics.shares,
							saved: c.metrics.saved,
							fetched_at: new Date().toISOString(),
						}));
						await db().from("ig_carousel_insights").upsert(rows, {
							onConflict: "post_id,child_media_id",
						});
					}
					// Small delay between carousel fetches
					await new Promise((resolve) => setTimeout(resolve, 100));
				}
				logger.info("IG carousel insights synced", {
					username: account.username,
					count: carouselPosts.length,
				});
			} catch (carouselErr: unknown) {
				logger.warn("IG carousel insights failed (non-fatal)", {
					username: account.username,
					error:
						carouselErr instanceof Error
							? carouselErr.message
							: String(carouselErr),
				});
			}
		}

		// Auto-classify: REMOVED from sync path — was burning hundreds of Gemini
		// calls per sync cycle (20 posts × N accounts × every 15 min).
		// Content classification now only runs in daily analytics-pipeline.

		// Calculate follower growth if we have a follower count
		if (igFollowersCount !== null) {
			try {
				const yesterday = new Date();
				yesterday.setDate(yesterday.getDate() - 1);
				const yesterdayKey = yesterday.toISOString().split("T")[0]!;

				const { data: previousData } = await db()
					.from("account_analytics")
					.select("followers_count")
					.eq("account_id", account.id)
					.eq("date", yesterdayKey)
					.maybeSingle();

				if (previousData?.followers_count) {
					igAnalyticsData.follower_growth =
						igFollowersCount - previousData.followers_count;
				} else {
					const { data: latestData } = await db()
						.from("account_analytics")
						.select("followers_count, date")
						.eq("account_id", account.id)
						.lt("date", todayKey)
						.order("date", { ascending: false })
						.limit(1)
						.maybeSingle();

					if (latestData?.followers_count) {
						igAnalyticsData.follower_growth =
							igFollowersCount - latestData.followers_count;
					} else {
						igAnalyticsData.follower_growth = 0;
					}
				}
			} catch (err) {
				logger.warn("[analyticsSync] Failed to calculate IG follower growth", {
					error: String(err),
				});
				igAnalyticsData.follower_growth = 0;
			}
		}

		// Sum post-level totals from ALL published IG posts in DB
		// (same pattern as Threads path — ensures total_likes, total_replies, total_saves, total_shares
		// are written to account_analytics so getAnalyticsStats() can aggregate them)
		try {
			const igSumsResult = await db()
				.from("posts")
				.select(
					"likes_count, ig_comment_count, ig_saved, ig_shares, ig_impressions, ig_reach, ig_profile_visits, ig_follows_count",
				)
				.eq("instagram_account_id", account.id)
				.eq("platform", "instagram")
				.eq("status", "published");
			const igPostSums = igSumsResult.data as Array<{
				likes_count?: number | null | undefined;
				ig_comment_count?: number | null | undefined;
				ig_saved?: number | null | undefined;
				ig_shares?: number | null | undefined;
				ig_impressions?: number | null | undefined;
				ig_reach?: number | null | undefined;
				ig_profile_visits?: number | null | undefined;
				ig_follows_count?: number | null | undefined;
			}> | null;
			if (igSumsResult.error) {
				logger.warn("IG post sums query error", {
					accountId: account.id,
					error: String(igSumsResult.error),
				});
			}
			if (igPostSums && igPostSums.length > 0) {
				igAnalyticsData.posts_count = igPostSums.length;
				let sumLikes = 0;
				let sumReplies = 0;
				let sumSaves = 0;
				let sumShares = 0;
				let sumViews = 0;
				let sumReach = 0;
				let sumProfileVisits = 0;
				let sumFollows = 0;
				for (const p of igPostSums) {
					sumLikes += p.likes_count || 0;
					sumReplies += p.ig_comment_count || 0;
					sumSaves += p.ig_saved || 0;
					sumShares += p.ig_shares || 0;
					sumViews += p.ig_impressions || 0;
					sumReach += p.ig_reach || 0;
					sumProfileVisits += p.ig_profile_visits || 0;
					sumFollows += p.ig_follows_count || 0;
				}
				igAnalyticsData.total_likes = sumLikes;
				igAnalyticsData.total_replies = sumReplies;
				igAnalyticsData.total_saves = sumSaves;
				igAnalyticsData.total_shares = sumShares;
				if (((igAnalyticsData.total_views as number | undefined) ?? 0) <= 0) {
					igAnalyticsData.total_views = sumViews;
				}
				if (
					((igAnalyticsData.ig_impressions as number | undefined) ?? 0) <= 0
				) {
					igAnalyticsData.ig_impressions = sumViews;
				}
				if (((igAnalyticsData.total_reach as number | undefined) ?? 0) <= 0) {
					igAnalyticsData.total_reach = sumReach;
				}
				if (((igAnalyticsData.ig_reach as number | undefined) ?? 0) <= 0) {
					igAnalyticsData.ig_reach = sumReach;
				}
				if (
					((igAnalyticsData.ig_profile_views as number | undefined) ?? 0) <= 0
				) {
					igAnalyticsData.ig_profile_views = sumProfileVisits;
				}
				if (
					((igAnalyticsData.ig_new_follows as number | undefined) ?? 0) <= 0
				) {
					igAnalyticsData.ig_new_follows = sumFollows;
				}
			}
		} catch (igSumErr) {
			logger.warn(
				"Failed to sum IG post totals from DB, post-level metrics may be missing",
				{ accountId: account.id, error: String(igSumErr) },
			);
		}

		// Guard: instagram_accounts use UUID IDs but account_analytics FK points to accounts (TEXT).
		// If the IG account doesn't exist in the accounts table, skip analytics upsert.
		const { data: accountExists } = await db()
			.from("accounts")
			.select("id")
			.eq("id", account.id)
			.maybeSingle();
		if (!accountExists) {
			logger.info(
				"IG analytics skipped — account not in accounts table (UUID/TEXT mismatch)",
				{
					accountId: account.id,
					username: account.username,
				},
			);
			return {
				success: false,
				postsUpdated: 0,
				error: "Account not in accounts table",
			};
		}

		// Atomic upsert: account_analytics + account_metrics_history in one transaction
		// biome-ignore lint/suspicious/noExplicitAny: RPC not in generated types
		const { error: igRpcError } = await (db() as any).rpc(
			"upsert_account_analytics_atomic",
			{
				p_analytics: igAnalyticsData,
				p_metrics_history: {
					account_id: account.id,
					platform: "instagram",
					date: todayKey,
					followers_count: (igAnalyticsData.followers_count as number) ?? 0,
					total_views: (igAnalyticsData.total_views as number) ?? 0,
					total_likes: (igAnalyticsData.total_likes as number) ?? 0,
					total_replies: (igAnalyticsData.total_replies as number) ?? 0,
					total_reposts: (igAnalyticsData.total_reposts as number) ?? 0,
					total_shares: (igAnalyticsData.total_shares as number) ?? 0,
					engagement_rate: (igAnalyticsData.engagement_rate as number) ?? 0,
					posts_count: (igAnalyticsData.posts_count as number) ?? 0,
				},
			},
		);
		if (igRpcError) {
			logger.warn(
				"Atomic IG analytics upsert failed, falling back to direct upsert",
				{
					accountId: account.id,
					error: igRpcError.message ?? JSON.stringify(igRpcError),
				},
			);
			// Fallback: direct upsert (non-atomic, but better than losing data)
			await db()
				.from("account_analytics")
				.upsert(igAnalyticsData as Record<string, unknown>, {
					onConflict: "account_id,date",
				});
			await db()
				.from("account_metrics_history")
				.upsert(
					{
						account_id: account.id,
						platform: "instagram",
						date: todayKey,
						followers_count: (igAnalyticsData.followers_count as number) ?? 0,
						total_views: (igAnalyticsData.total_views as number) ?? 0,
						total_likes: (igAnalyticsData.total_likes as number) ?? 0,
						total_replies: (igAnalyticsData.total_replies as number) ?? 0,
						total_reposts: (igAnalyticsData.total_reposts as number) ?? 0,
						total_shares: (igAnalyticsData.total_shares as number) ?? 0,
						engagement_rate: (igAnalyticsData.engagement_rate as number) ?? 0,
						posts_count: (igAnalyticsData.posts_count as number) ?? 0,
					} as Record<string, unknown>,
					{ onConflict: "account_id,date" },
				);
		}

		// Update account's last_synced_at (and followers if available)
		const igAccountUpdate: Record<string, unknown> = {
			last_synced_at: new Date().toISOString(),
			updated_at: new Date().toISOString(),
		};
		if (igFollowersCount !== null) {
			// instagram_accounts uses follower_count (singular) — not followers_count
			igAccountUpdate.follower_count = igFollowersCount;
		}
		await db()
			.from("instagram_accounts")
			.update(igAccountUpdate)
			.eq("id", account.id);

		// ── Story Metric Archival ──
		// Stories expire after 24h; archive final metrics for stories between 20-24h old
		if (syncType === "full") {
			try {
				const archiveNow = Date.now();
				const twentyHoursAgo = new Date(
					archiveNow - 20 * 60 * 60 * 1000,
				).toISOString();
				const twentyFourHoursAgo = new Date(
					archiveNow - 24 * 60 * 60 * 1000,
				).toISOString();

				const { data: expiringStories } = await db()
					.from("posts")
					.select("id, instagram_post_id")
					.eq("instagram_account_id", account.id)
					.eq("platform", "instagram")
					.eq("ig_media_type", "STORIES")
					.eq("status", "published")
					.or(`metrics_archived.is.null,metrics_archived.eq.false`)
					.lt("published_at", twentyHoursAgo)
					.gt("published_at", twentyFourHoursAgo)
					.not("instagram_post_id", "is", null);

				if (expiringStories && expiringStories.length > 0) {
					logger.info("Archiving expiring story metrics", {
						count: expiringStories.length,
						username: account.username,
					});
					const archiveLoginType = account.login_type || "facebook";
					const { getInstagramStoryMetrics: getStoryMetricsArchive } =
						await import("./instagramApi.js");

					for (const story of expiringStories) {
						try {
							const result = await getStoryMetricsArchive(
								account.instagram_access_token_encrypted,
								story.instagram_post_id as string,
								archiveLoginType,
							);
							if (result.success && result.metrics) {
								await db()
									.from("posts")
									.update({
										ig_impressions: result.metrics.views,
										ig_reach: result.metrics.reach,
										ig_story_exits: result.metrics.exits,
										ig_story_replies: result.metrics.replies,
										ig_story_taps_forward: result.metrics.taps_forward,
										ig_story_taps_back: result.metrics.taps_back,
										ig_follows_count: result.metrics.follows ?? 0,
										ig_profile_visits: result.metrics.profile_visits ?? 0,
										ig_post_profile_activity:
											result.metrics.profile_activity ?? null,
										metrics_archived: true,
										updated_at: new Date().toISOString(),
									})
									.eq("id", story.id);
								logger.info("Archived story metrics", { storyId: story.id });
							}
						} catch (storyErr: unknown) {
							logger.warn("Failed to archive story metrics", {
								storyId: story.id,
								error:
									storyErr instanceof Error
										? storyErr.message
										: String(storyErr),
							});
						}
					}
				}
			} catch (archiveErr: unknown) {
				logger.warn("Story archival sweep failed (non-fatal)", {
					error:
						archiveErr instanceof Error
							? archiveErr.message
							: String(archiveErr),
				});
			}
		}

		// Flush aggregated partial-insights alert (one Discord message per sync run)
		const { flushPartialInsightsAlert } = await import("./alerting.js");
		await flushPartialInsightsAlert();

		return { success: true, postsUpdated };
	} catch (error: unknown) {
		const message = error instanceof Error ? error.message : String(error);
		logger.error("Analytics refresh error for IG account", {
			username: account.username,
			error: message,
		});
		return { success: false, postsUpdated: 0, error: message };
	}
}

// ============================================================================
// Post-Sync Tasks (dashboard invalidation, anomaly detection, milestones, events)
// ============================================================================
/**
 * Run post-sync tasks after a successful account analytics refresh.
 * Bundles: invalidateDashboard, detectAnomalies, checkMilestones, detectEvents.
 * All operations are non-fatal — failures are logged but do not throw.
 */
export async function runPostSyncTasks(
	accountId: string,
	userId: string,
	platform: Platform,
	followersCount: number | null,
	lastMilestoneCelebrated: number | null,
): Promise<void> {
	// Invalidate dashboard cache so next load gets fresh data
	invalidateDashboard(accountId).catch((error) => {
		logger.warn("[analyticsSync] Dashboard invalidation failed", {
			accountId,
			userId,
			error: String(error),
		});
	});

	// Run anomaly detection (non-fatal)
	try {
		await detectAnomalies(accountId, platform, userId);
	} catch (adErr) {
		logger.warn(`Anomaly detection failed for ${platform} account`, {
			accountId,
			error: String(adErr),
		});
	}

	// Milestone check (non-fatal)
	try {
		if (followersCount) {
			await checkMilestones(
				accountId,
				platform,
				followersCount,
				lastMilestoneCelebrated ?? 0,
				userId,
			);
		}
	} catch (msErr) {
		logger.warn(`Milestone check failed for ${platform} account`, {
			accountId,
			error: String(msErr),
		});
	}

	// Creator event detection (non-fatal, fire-and-forget) — Threads only in original code
	if (platform === "threads") {
		try {
			const { data: recentPosts } = await db()
				.from("posts")
				.select(
					"id, content, media_type, published_at, views_count, likes_count, replies_count, reposts_count, shares_count, engagement_rate",
				)
				.eq("account_id", accountId)
				.eq("status", "published")
				.order("published_at", { ascending: false })
				.limit(30);

			const { data: analytics } = await db()
				.from("account_analytics")
				.select(
					"date, followers_count, follower_growth, total_views, engagement_rate",
				)
				.eq("account_id", accountId)
				.order("date", { ascending: false })
				.limit(30);

			if (recentPosts && analytics) {
				detectEvents(accountId, userId, recentPosts, analytics).catch(
					(error) => {
						logger.warn("[analyticsSync] Creator event detection failed", {
							accountId,
							userId,
							error: String(error),
						});
					},
				);
			}
		} catch (evtErr) {
			logger.warn("Creator event detection setup failed", {
				accountId,
				error: String(evtErr),
			});
		}
	}
}
