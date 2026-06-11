// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Analytics Pipeline Cron Job (Consolidated) - Orchestrator
 *
 * Phase 1:   Fan-out analytics refresh to QStash (all accounts, staggered)
 * Phase 2:   Analytics Postprocess (DB aggregations — runs inline)
 * Phase 2.5: Cohort aggregation (anonymized peer benchmarks, kill-switched)
 * Phase 3:   Share of Voice snapshots (daily SoV metrics)
 * Phase 4:   Content classification (classify unclassified posts, max 50/run)
 *
 * Previously Phase 1 processed all accounts inline, which exceeded the 300s
 * maxDuration as account count grew past ~250. Now Phase 1 delegates to the
 * existing cohort-based QStash dispatch (dispatchAnalyticsSync) which gives
 * each account its own 60s Vercel budget. Phase 2 postprocess still runs
 * inline since it's just DB aggregations (~5-10s).
 */

import type { VercelRequest, VercelResponse } from "@vercel/node";
import { alertCronFailure } from "../_lib/alerting.js";
import { runPhase2_5_CohortAggregation } from "../_lib/analytics/cohortAggregation.js";
import { runPhase2_AnalyticsPostprocess } from "../_lib/analytics/postProcess.js";
import { trackCronRun, withCronLock } from "../_lib/cronUtils.js";
import { logger } from "../_lib/logger.js";
import {
	getPrivilegedSupabaseAny,
	PRIVILEGED_DB_REASONS,
} from "../_lib/privilegedDb.js";
import { getRedis } from "../_lib/redis.js";

export const config = { maxDuration: 300 };
const db = () =>
	getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.analyticsPipeline);

// ============================================================================
// Phase 1: Fan out analytics refresh via QStash
// ============================================================================
async function runPhase1_AnalyticsDispatch(): Promise<number> {
	logger.info("Phase 1: Dispatching analytics refresh via QStash");
	const { dispatchAnalyticsSync } = await import(
		"../_lib/analyticsDispatch.js"
	);

	// Full sync: dispatch ALL accounts regardless of staleness for the daily 2 AM run.
	// fullSync: true skips the analytics-pipeline:active self-blocking check and
	// removes stale thresholds so every account gets a QStash message.
	const dispatched = await dispatchAnalyticsSync({ fullSync: true });
	logger.info("Phase 1: Dispatched accounts to QStash", { dispatched });

	// Set the active flag so sync-orchestrator's Phase 0 doesn't also dispatch
	// while QStash is still processing our fan-out. TTL covers the staggered delivery
	// window (~2s per account × dispatched accounts, capped at 30 min).
	const redis = getRedis();
	const activeTtl = Math.min(Math.max(dispatched * 2, 120), 1800);
	await redis
		.set("analytics-pipeline:active", "1", { ex: activeTtl })
		.catch(() => {});

	return dispatched;
}

// ============================================================================
// Handler
// ============================================================================
export default async function handler(req: VercelRequest, res: VercelResponse) {
	const { verifyCronAuth } = await import("../_lib/apiResponse.js");
	if (!verifyCronAuth(req, res)) return;

	const supabase = db();
	const pipelineStartTime = Date.now();

	const lockResult = await withCronLock(
		supabase,
		"analytics-pipeline",
		async () => {
			return trackCronRun(supabase, "analytics-pipeline", async () => {
				let totalItemsProcessed = 0;
				const phasesCompleted: string[] = [];
				// Captured failures + skip reasons surface back to the caller in
				// metadata.phaseDiagnostics so cron_runs has a debuggable record
				// without requiring Sentry access. Without this, a silent Phase 1
				// skip (Meta health gate or thrown exception) is invisible from
				// the DB — see commit history for the 20:50 UTC "no dispatch"
				// incident on 2026-04-30.
				const phaseDiagnostics: Record<string, unknown> = {};

				// Phase 1: Fan out to QStash — each account gets its own 60s budget.
				// This replaces the old inline batch loop that timed out at 300s
				// once account count exceeded ~250.
				try {
					// Pre-flight: Meta API health check (circuit breaker)
					const { isMetaApiHealthy } = await import("../_lib/metaApiHealth.js");
					const [threadsHealthy, igHealthy] = await Promise.all([
						isMetaApiHealthy("threads"),
						isMetaApiHealthy("instagram"),
					]);
					phaseDiagnostics.health = { threads: threadsHealthy, ig: igHealthy };
					if (!threadsHealthy) {
						logger.warn(
							"[analytics-pipeline] Phase 1: Threads API unhealthy — skipping Threads dispatch",
						);
					}
					if (!igHealthy) {
						logger.warn(
							"[analytics-pipeline] Phase 1: Instagram API unhealthy — skipping Instagram dispatch",
						);
					}
					if (!threadsHealthy && !igHealthy) {
						logger.warn(
							"[analytics-pipeline] Phase 1: Both platforms unhealthy — skipping dispatch entirely",
						);
						phaseDiagnostics.dispatchSkipped = "both-platforms-unhealthy";
					} else {
						const dispatched = await runPhase1_AnalyticsDispatch();
						totalItemsProcessed += dispatched;
						phasesCompleted.push("analytics-dispatch");
						phaseDiagnostics.dispatched = dispatched;
					}
				} catch (err: unknown) {
					const errMsg = err instanceof Error ? err.message : String(err);
					logger.error("Phase 1 (dispatch) failed", { error: errMsg });
					phaseDiagnostics.dispatchError = errMsg;
					try {
						const { captureServerException } = await import(
							"../_lib/sentryServer.js"
						);
						await captureServerException(err, {
							cronJob: "analytics-pipeline",
							phase: "analytics-dispatch",
						});
					} catch {
						/* sentry best-effort */
					}
					alertCronFailure(
						"analytics-pipeline",
						`Phase 1 dispatch failed: ${errMsg}`,
						Date.now() - pipelineStartTime,
					);
				}

				// Phase 2: Postprocess — DB aggregations (group analytics, daily
				// summaries, best posting times, insights). Runs inline (~5-10s).
				// Note: QStash workers from Phase 1 may still be processing, but
				// postprocess reads whatever data is currently in the DB — it will
				// pick up freshly synced data from the 15-min sync-orchestrator cycle.
				try {
					const phase2Items =
						await runPhase2_AnalyticsPostprocess(pipelineStartTime);
					totalItemsProcessed += phase2Items;
					phasesCompleted.push("analytics-postprocess");
				} catch (err: unknown) {
					const errMsg = err instanceof Error ? err.message : String(err);
					logger.error("Phase 2 failed", { error: errMsg });
					try {
						const { captureServerException } = await import(
							"../_lib/sentryServer.js"
						);
						await captureServerException(err, {
							cronJob: "analytics-pipeline",
							phase: "analytics-postprocess",
						});
					} catch {
						/* sentry best-effort */
					}
					alertCronFailure(
						"analytics-pipeline",
						`Phase 2 failed: ${errMsg}`,
						Date.now() - pipelineStartTime,
					);
				}

				// Phase 2.5: Cohort aggregation — anonymized peer benchmarks.
				// Kill-switched via COHORT_AGGREGATION_ENABLED; the helper no-ops
				// when the flag is unset. Non-critical (read handler returns the
				// suppressed state for every request if this never runs).
				try {
					const cohortRows =
						await runPhase2_5_CohortAggregation(pipelineStartTime);
					phaseDiagnostics.cohortAggregation = {
						rowsWritten: cohortRows,
						enabled: process.env.COHORT_AGGREGATION_ENABLED === "1",
					};
					if (cohortRows > 0) {
						totalItemsProcessed += cohortRows;
						phasesCompleted.push("cohort-aggregation");
					}
				} catch (err: unknown) {
					phaseDiagnostics.cohortAggregation = {
						error: err instanceof Error ? err.message : String(err),
						enabled: process.env.COHORT_AGGREGATION_ENABLED === "1",
					};
					logger.warn("Phase 2.5 cohort aggregation failed", {
						error: err instanceof Error ? err.message : String(err),
					});
				}

				// Phase 3: Share of Voice snapshots — record daily SoV metrics
				try {
					const sovCount = await runPhase3_SoVSnapshots(pipelineStartTime);
					if (sovCount > 0) {
						totalItemsProcessed += sovCount;
						phasesCompleted.push("sov-snapshots");
					}
				} catch (err: unknown) {
					// SoV is non-critical — log but don't alert
					logger.warn("Phase 3 SoV snapshots failed", {
						error: err instanceof Error ? err.message : String(err),
					});
				}

				// Phase 4: Content classification — classify unclassified published posts
				// Runs once daily here instead of every 15-min sync to limit Gemini spend.
				try {
					const classified =
						await runPhase4_ContentClassification(pipelineStartTime);
					if (classified > 0) {
						totalItemsProcessed += classified;
						phasesCompleted.push("content-classification");
					}
				} catch (err: unknown) {
					// Non-critical — log but don't alert
					logger.warn("Phase 4 content classification failed", {
						error: err instanceof Error ? err.message : String(err),
					});
				}

				return {
					itemsProcessed: totalItemsProcessed,
					metadata: {
						phasesCompleted,
						durationMs: Date.now() - pipelineStartTime,
						phaseDiagnostics,
					},
				};
			});
		},
		305,
	);

	return res.status(200).json({ success: !lockResult.skipped });
}

/**
 * Phase 3: Record daily Share of Voice snapshots.
 * For each user with competitors, compute engagement/follower shares and write to share_of_voice_history.
 */
async function runPhase3_SoVSnapshots(globalStart: number): Promise<number> {
	// Time-budget check: skip if <15s remaining
	if (Date.now() - globalStart > 285_000) return 0;

	const db = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.analyticsPipeline,
	);
	const today = new Date().toISOString().split("T")[0]!;

	// Get distinct user+account combos that have competitors
	const { data: competitorUsers } = await db
		.from("competitors")
		.select("user_id, id")
		.eq("sync_status", "active")
		.limit(200);

	if (!competitorUsers || competitorUsers.length === 0) return 0;

	// Group by user_id
	const userIds = [
		...new Set(competitorUsers.map((c: { user_id: string }) => c.user_id)),
	];
	let recorded = 0;

	for (const userId of userIds) {
		try {
			// Get user's accounts
			const { data: accounts } = await db
				.from("accounts")
				.select("id, followers_count")
				.eq("user_id", userId)
				.eq("is_active", true)
				.limit(10);
			if (!accounts || accounts.length === 0) continue;

			// Get user's recent engagement (7 days)
			const cutoff = new Date();
			cutoff.setDate(cutoff.getDate() - 7);
			const accountIds = accounts.map((a: { id: string }) => a.id);
			const { data: userPosts } = await db
				.from("posts")
				.select("likes_count, replies_count, reposts_count")
				.in("account_id", accountIds)
				.eq("status", "published")
				.gte("published_at", cutoff.toISOString())
				.limit(200);

			const userEngagement = (userPosts || []).reduce(
				(
					s: number,
					p: {
						likes_count?: number | undefined;
						replies_count?: number | undefined;
						reposts_count?: number | undefined;
					},
				) =>
					s +
					(p.likes_count || 0) +
					(p.replies_count || 0) +
					(p.reposts_count || 0),
				0,
			);
			const userFollowers = accounts.reduce(
				(s: number, a: { followers_count?: number | undefined }) =>
					s + (a.followers_count || 0),
				0,
			);

			// Get competitor engagement
			const { data: compSnapshots } = await db
				.from("competitor_snapshots")
				.select("competitor_id, followers, engagement_rate")
				.eq("user_id", userId)
				.gte("recorded_at", cutoff.toISOString());

			const compEngagement = (compSnapshots || []).reduce(
				(s: number, c: { engagement_rate?: number | undefined; followers?: number | undefined }) =>
					s + ((c.engagement_rate || 0) * (c.followers || 0)) / 100,
				0,
			);
			const compFollowers = (compSnapshots || []).reduce(
				(s: number, c: { followers?: number | undefined }) => s + (c.followers || 0),
				0,
			);

			const totalEngagement = userEngagement + compEngagement;
			const totalFollowers = userFollowers + compFollowers;

			if (totalEngagement === 0 && totalFollowers === 0) continue;

			const engShare =
				totalEngagement > 0 ? (userEngagement / totalEngagement) * 100 : 0;
			const follShare =
				totalFollowers > 0 ? (userFollowers / totalFollowers) * 100 : 0;

			// Upsert SoV snapshot
			await db.from("share_of_voice_history").upsert(
				{
					user_id: userId,
					account_id: accountIds[0],
					date: today,
					engagement_share: Math.round(engShare * 100) / 100,
					follower_share: Math.round(follShare * 100) / 100,
					content_volume_share: null,
				},
				{ onConflict: "user_id,account_id,date" },
			);
			recorded++;
		} catch {
			// Non-critical — skip this user
		}
	}

	return recorded;
}

/**
 * Phase 4: Classify unclassified published posts into content categories.
 * Runs once daily (in this 2 AM cron) to limit Gemini API spend.
 * - 5 posts per account max
 * - 50 total classifications per run
 */
async function runPhase4_ContentClassification(
	globalStart: number,
): Promise<number> {
	// Time-budget check: skip if <30s remaining
	if (Date.now() - globalStart > 270_000) return 0;

	const apiKey = process.env.GEMINI_API_KEY;
	if (!apiKey) {
		logger.warn(
			"[analytics-pipeline] Phase 4: GEMINI_API_KEY not set — skipping",
		);
		return 0;
	}

	const { classifyPost } = await import("../_lib/contentClassifier.js");
	const { classifyHook } = await import("../_lib/hookClassifier.js");
	const supabase = getPrivilegedSupabaseAny(
		PRIVILEGED_DB_REASONS.analyticsPipeline,
	);

	// Two batches per phase 4 run, both capped per-account to 5 to stay polite
	// across the fleet:
	//   1. content_category — Gemini-backed when ambiguous, expensive
	//   2. hook_class — rule-first, cheap, classifies the OPENING LINE
	// We co-iterate them on the same per-account budget so a single account
	// can't hog the whole 50-row run with one feature.
	const { data: posts, error } = await supabase
		.from("posts")
		.select(
			"id, user_id, content, media_type, platform, account_id, content_category, hook_class",
		)
		.eq("status", "published")
		.or("content_category.is.null,hook_class.is.null")
		.order("published_at", { ascending: false })
		.limit(400);

	if (error || !posts || posts.length === 0) return 0;

	// Enforce 5-per-account limit on the union of unclassified work.
	const accountCounts = new Map<string, number>();
	const toClassify: typeof posts = [];
	for (const post of posts) {
		if (toClassify.length >= 50) break;
		const count = accountCounts.get(post.account_id) || 0;
		if (count >= 5) continue;
		accountCounts.set(post.account_id, count + 1);
		toClassify.push(post);
	}

	let classified = 0;
	let hooksClassified = 0;

	for (const post of toClassify) {
		if (Date.now() - globalStart > 280_000) break;

		const caption = post.content || "";
		const platform = post.platform || "threads";
		const mediaType = post.media_type || "TEXT";

		const update: Record<string, string | number | null> = {};

		// Content category — only when missing.
		if (!post.content_category) {
			try {
				const hashtags = caption.match(/#\w+/g) || [];
				const result = await classifyPost(
					apiKey,
					caption,
					mediaType,
					hashtags,
					platform,
					post.user_id,
				);
				update.content_category = result.primary;
				update.content_category_confidence = result.confidence;
				classified++;
			} catch (err: unknown) {
				logger.warn(
					"[analytics-pipeline] Phase 4: content classification failed",
					{
						postId: post.id,
						error: err instanceof Error ? err.message : String(err),
					},
				);
			}
		}

		// Hook class — only when missing. Rule-first, very cheap; falls
		// through to Gemini only on genuinely ambiguous openers.
		if (!post.hook_class) {
			try {
				const hookResult = await classifyHook(apiKey, caption, post.user_id);
				update.hook_class = hookResult.hookClass;
				update.hook_class_confidence = hookResult.confidence;
				update.hook_classified_at = new Date().toISOString();
				hooksClassified++;
			} catch (err: unknown) {
				logger.warn(
					"[analytics-pipeline] Phase 4: hook classification failed",
					{
						postId: post.id,
						error: err instanceof Error ? err.message : String(err),
					},
				);
			}
		}

		if (Object.keys(update).length > 0) {
			await supabase
				.from("posts")
				.update(update)
				.eq("id", post.id);
		}
	}

	if (classified > 0 || hooksClassified > 0) {
		logger.info("[analytics-pipeline] Phase 4: classified posts", {
			contentClassified: classified,
			hookClassified: hooksClassified,
			total: toClassify.length,
			accounts: accountCounts.size,
		});
	}

	return classified + hooksClassified;
}
