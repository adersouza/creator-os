/**
 * QStash receiver: Fetch engagement metrics for a published post.
 *
 * POST /api/sync/post-engagement
 * Body: { postId, threadsPostId }
 * Auth: QStash signature
 *
 * Called automatically 1h and 24h after publish via dispatchEngagementFetch().
 * Fetches views/likes/replies/reposts from Threads API, writes to posts table
 * via monotonic RPC, and back-populates auto_post_queue if linked.
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import type { AutoposterQueueProvenanceInput } from "../auto-post/performanceFirst.js";
import { logger } from "../../logger.js";
import { calculateEngagementRate } from "../../metricCalculators.js";
import { getSupabase } from "../../supabase.js";

// biome-ignore lint/suspicious/noExplicitAny: posts.metadata untyped JSONB
const db = (): any => getSupabase();

type EngagementQueueRow = AutoposterQueueProvenanceInput & {
	workspace_id?: string | null;
	group_id?: string | null;
	account_id?: string | null;
};

export default async function handler(req: VercelRequest, res: VercelResponse) {
	if (req.method !== "POST") {
		return res.status(405).json({ error: "Method not allowed" });
	}

	// Verify QStash signature
	const { verifyQStashSignature } = await import("../../qstash.js");
	if (!(await verifyQStashSignature(req, res))) return;

	const { postId, threadsPostId } = req.body ?? {};
	if (!postId || !threadsPostId) {
		return res
			.status(200)
			.json({ ok: true, skipped: true, reason: "missing_params" });
	}

	try {
		// Load post + account token
		const { data: post } = await db()
			.from("posts")
			.select(
				"id, user_id, account_id, cross_post_group_id, content, platform, media_type, media_urls, published_at, views_count, replies_count, likes_count, reposts_count, quotes_count, hook_type, topic_label, format_type, emotional_frame, reply_mechanism, content_length_bucket, media_style, posting_hour, prompt_version, template_id, model_provider, source_pattern_id, strategy_recommendation_id, strategy_bucket, auto_post_queue_id, metadata, accounts!inner(threads_access_token_encrypted, username)",
			)
			.eq("id", postId)
			.maybeSingle();

		if (!post?.accounts?.threads_access_token_encrypted) {
			return res
				.status(200)
				.json({ ok: true, skipped: true, reason: "no_token" });
		}

		// Decrypt token
		const { decrypt } = await import("../../encryption.js");
		const token = decrypt(post.accounts.threads_access_token_encrypted);

		// Fetch metrics from Threads API
		const metricsUrl = `https://graph.threads.net/v1.0/${threadsPostId}/insights?metric=views,likes,replies,reposts,quotes,shares`;
		const { withRetry } = await import("../../retryUtils.js");
		const response = await withRetry(
			() =>
				fetch(metricsUrl, {
					headers: { Authorization: `Bearer ${token}` },
					signal: AbortSignal.timeout(10000),
				}),
			{ label: "post-engagement-fetch" },
		);

		if (!response.ok) {
			logger.warn("[post-engagement] API error", {
				postId,
				status: response.status,
			});
			return res
				.status(200)
				.json({ ok: true, skipped: true, reason: "api_error" });
		}

		const result = await response.json();
		const metricsData = result?.data || [];

		// Parse metrics
		const metrics: Record<string, number> = {};
		for (const m of metricsData) {
			if (m?.name && m?.values?.[0]?.value !== undefined) {
				metrics[m.name] = m.values[0].value;
			}
		}

		const views = metrics.views || 0;
		const likes = metrics.likes || 0;
		const replies = metrics.replies || 0;
		const reposts = metrics.reposts || 0;
		const quotes = metrics.quotes || 0;
		const shares = metrics.shares || 0;
		const totalEngagement = likes + replies + reposts + quotes + shares;
		const engagementRate = calculateEngagementRate(
			{ views, likes, replies, reposts, quotes, shares },
			"threads",
		);

		// Update posts table via monotonic RPC
		await db().rpc("update_post_metrics_if_newer", {
			p_post_id: postId,
			p_threads_post_id: threadsPostId,
			p_views_count: views,
			p_likes_count: likes,
			p_replies_count: replies,
			p_reposts_count: reposts,
			p_quotes_count: quotes,
			p_shares_count: shares,
			p_engagement_rate: engagementRate,
			p_total_engagement: totalEngagement,
		});

		const hoursSincePublish = post.published_at
			? Math.round(
					((Date.now() - new Date(post.published_at).getTime()) /
						(1000 * 60 * 60)) *
						100,
				) / 100
			: null;
		const historyRow = {
			post_id: postId,
			account_id: post.account_id,
			platform: "threads",
			hours_since_publish: hoursSincePublish,
			views_count: views,
			likes_count: likes,
			replies_count: replies,
			reposts_count: reposts,
			quotes_count: quotes,
			shares_count: shares,
			engagement_rate: engagementRate,
		};
		try {
			const { error: historyError } = await db()
				.from("post_metric_history")
				.insert(historyRow);
			if (historyError) {
				logger.warn("[post-engagement] Failed to write metric snapshot", {
					postId,
					error:
						historyError instanceof Error
							? historyError.message
							: String(historyError),
				});
			}
		} catch (historyError) {
			logger.warn("[post-engagement] Failed to write metric snapshot", {
				postId,
				error:
					historyError instanceof Error
						? historyError.message
						: String(historyError),
			});
		}

		// Back-populate auto_post_queue if linked
		const metadata = post.metadata || {};
		const autoPostQueueId =
			typeof post.auto_post_queue_id === "string"
				? post.auto_post_queue_id
				: typeof metadata.autoPostQueueId === "string"
				? metadata.autoPostQueueId
				: null;
		let backPopulated = false;
		let queueRow: EngagementQueueRow | null = null;
		let scopedQueueRow: EngagementQueueRow | null = null;
		if (autoPostQueueId) {
			const { data: loadedQueueRow, error: queueLookupError } = await db()
				.from("auto_post_queue")
				.select(
					"id, workspace_id, group_id, account_id, source_type, source_id, source_competitor_id, source_competitor_username, strategy_recommendation_id, strategy_bucket, source_pattern_id, media_style, metadata",
				)
				.eq("id", autoPostQueueId)
				.maybeSingle();
			queueRow = (loadedQueueRow || null) as EngagementQueueRow | null;

			if (queueLookupError) {
				logger.warn("[post-engagement] Failed to verify queue scope", {
					postId,
					autoPostQueueId,
					error:
						queueLookupError instanceof Error
							? queueLookupError.message
							: String(queueLookupError),
				});
			}

			if (!queueRow || queueRow.account_id !== post.account_id) {
				logger.warn(
					"[post-engagement] Skipped queue back-populate for out-of-scope queue link",
					{
						postId,
						postAccountId: post.account_id,
						autoPostQueueId,
						queueAccountId: queueRow?.account_id ?? null,
					},
				);
			} else {
				const matchedQueueRow: EngagementQueueRow = queueRow;
				scopedQueueRow = matchedQueueRow;
				const updateQuery = db()
					.from("auto_post_queue")
					.update({
						views_at_24h: views,
						likes_count: likes,
						replies_count: replies,
						reposts_count: reposts,
						engagement_rate: engagementRate,
						engagement_fetched_at: new Date().toISOString(),
						})
					.eq("id", matchedQueueRow.id);

				const { error: queueUpdateError } = await updateQuery.eq(
					"account_id",
					matchedQueueRow.account_id,
				);
				if (queueUpdateError) {
					logger.warn("[post-engagement] Failed to back-populate queue", {
						postId,
						autoPostQueueId,
						error:
							queueUpdateError instanceof Error
								? queueUpdateError.message
								: String(queueUpdateError),
					});
				} else {
					backPopulated = true;
				}
			}
		}

		try {
			const {
				buildAutoposterPerformanceFacts,
				persistAutoposterPerformanceFacts,
			} = await import("../auto-post/performanceFirst.js");
			const factPost = {
				...post,
				views_count: views,
				likes_count: likes,
				replies_count: replies,
				reposts_count: reposts,
				quotes_count: quotes,
				platform: "threads",
				workspace_id:
					typeof scopedQueueRow?.workspace_id === "string"
						? scopedQueueRow.workspace_id
						: null,
			};
			const accountLookup = new Map();
			if (post.account_id) {
				accountLookup.set(post.account_id, {
					username:
						typeof post.accounts?.username === "string"
							? post.accounts.username
							: null,
					workspace_id:
						typeof scopedQueueRow?.workspace_id === "string"
							? scopedQueueRow.workspace_id
							: null,
				});
			}
			const facts = buildAutoposterPerformanceFacts({
				posts: [factPost],
				historyRows: [historyRow],
				queueRows: scopedQueueRow ? [scopedQueueRow] : [],
				smartLinkAttribution: [],
				accountLookup,
				groupLookup: new Map(),
			});
			await persistAutoposterPerformanceFacts(db(), facts);
		} catch (factError) {
			logger.warn("[post-engagement] Failed to write performance fact", {
				postId,
				error:
					factError instanceof Error ? factError.message : String(factError),
			});
		}

		logger.info("[post-engagement] Metrics updated", {
			postId,
			views,
			likes,
			replies,
			reposts,
			engagementRate: engagementRate.toFixed(2),
			backPopulated,
		});

		return res.status(200).json({ ok: true, views, likes, replies, reposts });
	} catch (err) {
		const errMsg = err instanceof Error ? err.message : String(err);
		logger.error("[post-engagement] Error", { postId, error: errMsg });
		// Report to Sentry so failures are visible in monitoring
		import("../../sentryServer.js")
			.then(({ captureServerException }) =>
				captureServerException(err, { handler: "post-engagement", postId }),
			)
			.catch(() => {});
		return res.status(200).json({ ok: false, error: "Engagement sync failed" });
	}
}
