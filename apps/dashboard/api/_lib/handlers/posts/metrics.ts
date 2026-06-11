/**
 * Metrics handler — on-demand refresh of Threads post insights.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { apiSuccess } from "../../apiResponse.js";
import { decrypt } from "../../encryption.js";
import { logger } from "../../logger.js";
import { calculateEngagementRate } from "../../metricCalculators.js";
import { withRetry } from "../../retryUtils.js";
import { db, type PostWithAccountsRow } from "./shared.js";

const METRICS_FETCH_TIMEOUT = 8000;

export async function handleRefreshMetrics(
	req: VercelRequest,
	res: VercelResponse,
	userId: string,
) {
	// Fetch published Threads posts that have a threads_post_id but stale/zero metrics
	// Limit to 20 posts per call to stay within API rate limits
	const { postIds, accountId } = req.body || {};

	// Join posts with accounts in a single query to avoid N+1
	let query = db()
		.from("posts")
		.select(
			"id, threads_post_id, account_id, accounts!inner(id, threads_access_token_encrypted)",
		)
		.eq("user_id", userId)
		.eq("status", "published")
		.eq("platform", "threads")
		.not("threads_post_id", "is", null);

	if (accountId) {
		query = query.eq("account_id", accountId);
	}

	if (postIds && Array.isArray(postIds) && postIds.length > 0) {
		query = query.in("id", postIds.slice(0, 20));
	} else {
		// Default: posts with zero views (not yet synced)
		query = query
			.or("views_count.is.null,views_count.eq.0")
			.order("published_at", { ascending: false })
			.limit(20);
	}

	const { data: posts, error: postsError } = await query;
	if (postsError || !posts || posts.length === 0) {
		return apiSuccess(res, { updated: 0, posts: [] });
	}

	// Build token map from the joined account data (no separate query needed)
	const tokenMap = new Map<string, string>();
	for (const post of posts as PostWithAccountsRow[]) {
		const acc = post.accounts;
		if (acc?.threads_access_token_encrypted && !tokenMap.has(acc.id)) {
			try {
				tokenMap.set(acc.id, decrypt(acc.threads_access_token_encrypted));
			} catch (err) {
				logger.debug("Failed to decrypt access token for account", {
					accountId: acc.id,
					error: String(err),
				});
				// skip accounts with bad tokens
			}
		}
	}

	if (tokenMap.size === 0) {
		return apiSuccess(res, { updated: 0, posts: [] });
	}

	const updatedPosts: Array<{
		id: string;
		views: number;
		likes: number;
		replies: number;
		reposts: number;
		quotes: number;
		shares: number;
	}> = [];

	// Fetch metrics in parallel with concurrency limit of 5
	const MAX_CONCURRENT = 5;
	const validPosts = (posts as PostWithAccountsRow[]).filter(
		(p) => tokenMap.get(p.account_id) && p.threads_post_id,
	);

	const fetchMetrics = async (
		post: PostWithAccountsRow,
	): Promise<{ id: string; metrics: Record<string, number> } | null> => {
		const token = tokenMap.get(post.account_id) ?? "";
		try {
			const insightsUrl = `https://graph.threads.net/v1.0/${post.threads_post_id}/insights?metric=views,likes,replies,reposts,quotes,shares`;
			const response = await withRetry(
				() =>
					fetch(insightsUrl, {
						headers: { Authorization: `Bearer ${token}` },
						signal: AbortSignal.timeout(METRICS_FETCH_TIMEOUT),
					}),
				{ label: `postMetrics:${post.threads_post_id}` },
			);

			const data = await response.json();
			if (!response.ok || data.error) return null;

			const metrics: Record<string, number> = {
				views: 0,
				likes: 0,
				replies: 0,
				reposts: 0,
				quotes: 0,
				shares: 0,
			};
			if (data.data) {
				for (const metric of data.data) {
					const name = metric.name;
					const value =
						metric.total_value?.value ??
						metric.values?.[metric.values.length - 1]?.value ??
						0;
					if (name in metrics) {
						metrics[name] = value;
					}
				}
			}
			return { id: post.id, metrics };
		} catch (err) {
			logger.debug("Failed to fetch Threads post insights", {
				postId: post.threads_post_id,
				error: String(err),
			});
			return null;
		}
	};

	// Process in batches of MAX_CONCURRENT
	for (let i = 0; i < validPosts.length; i += MAX_CONCURRENT) {
		const batch = validPosts.slice(i, i + MAX_CONCURRENT);
		const results = await Promise.all(batch.map(fetchMetrics));
		for (const result of results) {
			if (result) {
				updatedPosts.push({
					id: result.id,
					views: result.metrics.views ?? 0,
					likes: result.metrics.likes ?? 0,
					replies: result.metrics.replies ?? 0,
					reposts: result.metrics.reposts ?? 0,
					quotes: result.metrics.quotes ?? 0,
					shares: result.metrics.shares ?? 0,
				});
			}
		}
	}

	// Batch DB update: upsert all metrics in a single call per post using Promise.all
	if (updatedPosts.length > 0) {
		const now = new Date().toISOString();
		await Promise.all(
			updatedPosts.map(async (p) => {
				const engagementRate = calculateEngagementRate(
					{
						views: p.views,
						likes: p.likes,
						replies: p.replies,
						reposts: p.reposts,
						quotes: p.quotes,
						shares: p.shares,
					},
					"threads",
				);
				const { error } = await db()
					.from("posts")
					.update({
						views_count: p.views,
						likes_count: p.likes,
						replies_count: p.replies,
						reposts_count: p.reposts,
						quotes_count: p.quotes,
						shares_count: p.shares,
						engagement_rate: engagementRate,
						updated_at: now,
					})
					.eq("id", p.id);
				if (error) {
					logger.error("[metrics] Failed to update post metrics", {
						postId: p.id,
						error: error.message,
					});
				}
			}),
		);
	}

	return apiSuccess(res, { updated: updatedPosts.length, posts: updatedPosts });
}
