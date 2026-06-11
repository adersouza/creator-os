// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Trend Pipeline Scanner / Orchestrator
 *
 * End-to-end pipeline: scan X via Grok, filter/score/dedup (Plan 01 modules),
 * generate on-brand posts via Gemini with voice injection, queue in auto_post_queue
 * for the existing auto-post-worker to publish.
 *
 * Atomic per group -- if one group fails, others still process.
 * Time budget guard prevents cron timeout at 300s limit.
 */

import { isGeminiAvailable } from "../../geminiRetry.js";
import { isGrokAvailable, searchTrends } from "../../grokSearch.js";
import { logger } from "../../logger.js";
import {
	filterTrends,
	getTodayPostCount,
	hasTrendDecayed,
	isAlreadyDiscovered,
	scoreTrendAcceleration,
	shouldScanGroup,
} from "./filterTrends.js";
import { selectFormat } from "./formatWeights.js";
import { generateTrendPost } from "./generator.js";
import type {
	TrendConfig,
	TrendPipelineResult,
	VoiceProfile,
} from "./types.js";

/** Maximum execution time (ms) before bailing -- 270s of 300s limit */
const MAX_EXECUTION_TIME = 270_000;

/**
 * Main entry point called by cron.
 * Iterates all enabled trending_topic_configs, processes each group atomically.
 */
export async function processTrendPipeline(): Promise<number> {
	const startTime = Date.now();

	function hasTimeBudget(): boolean {
		return Date.now() - startTime < MAX_EXECUTION_TIME;
	}

	// Circuit breaker / availability pre-checks
	if (!process.env.XAI_API_KEY) {
		logger.debug("Trend pipeline skipped: XAI_API_KEY not configured");
		return 0;
	}
	if (!isGrokAvailable()) {
		logger.warn("Trend pipeline skipped: Grok circuit open (xAI API failures)");
		return 0;
	}
	if (!isGeminiAvailable()) {
		logger.warn("Trend pipeline skipped: Gemini circuit open");
		return 0;
	}

	const { getSupabaseAny } = await import("../../supabase.js");
	const db = getSupabaseAny();

	// Fetch all enabled configs
	const { data: configs, error } = await db
		.from("trending_topic_config")
		.select("*")
		.eq("enabled", true);

	if (error || !configs?.length) {
		if (error)
			logger.error("Failed to fetch trend configs", { error: String(error) });
		return 0;
	}

	// Sort: never-scanned first, then oldest scan first
	const sorted = (configs as TrendConfig[]).sort((a, b) => {
		if (!a.last_scan_at && !b.last_scan_at) return 0;
		if (!a.last_scan_at) return -1;
		if (!b.last_scan_at) return 1;
		return (
			new Date(a.last_scan_at).getTime() - new Date(b.last_scan_at).getTime()
		);
	});

	let processed = 0;
	for (const config of sorted) {
		if (!hasTimeBudget()) {
			logger.info("Trend pipeline: time budget exhausted", { processed });
			break;
		}

		try {
			await processOneGroup(db, config);
			processed++;
		} catch (err) {
			logger.error("Group processing failed, skipping", {
				groupId: config.account_group_id,
				error: String(err),
			});
		}
	}

	return processed;
}

/**
 * Atomic per-group processing: tier gate, scan frequency, daily cap,
 * search, filter, dedup, generate, queue.
 */
export async function processOneGroup(
	// biome-ignore lint/suspicious/noExplicitAny: Supabase client passed from getSupabaseAny()
	db: any,
	config: TrendConfig,
): Promise<TrendPipelineResult> {
	const result: TrendPipelineResult = {
		groupId: config.account_group_id,
		trendsFound: 0,
		postsQueued: 0,
		skippedReasons: [],
	};

	// Empire tier gate
	const { getUserTier } = await import("../../tierGate.js");
	const tier = await getUserTier(config.user_id);
	if (tier !== "empire") {
		result.skippedReasons.push("not_empire_tier");
		return result;
	}

	// Scan frequency check
	if (!shouldScanGroup(config)) {
		result.skippedReasons.push("too_recent");
		return result;
	}

	// Daily cap check (BEFORE calling Gemini to save API quota)
	const todayCount = await getTodayPostCount(db, config.account_group_id);
	if (todayCount >= config.daily_post_cap) {
		result.skippedReasons.push("daily_cap_reached");
		return result;
	}
	const remainingCap = config.daily_post_cap - todayCount;

	// Search trends via Grok
	const fromDate = new Date(Date.now() - 12 * 60 * 60 * 1000)
		.toISOString()
		.split("T")[0]!; // YYYY-MM-DD
	const rawTrends = await searchTrends(config.keywords, {
		fromDate,
		userId: config.user_id,
	});

	// Filter by relevance score (75+) and blocklist
	const filtered = filterTrends(rawTrends, config.blocklist, 75);
	result.trendsFound = filtered.length;

	if (filtered.length === 0) {
		// Update last_scan_at even if no trends found
		await db
			.from("trending_topic_config")
			.update({ last_scan_at: new Date().toISOString() })
			.eq("id", config.id);
		return result;
	}

	// Dedup against previously discovered trends + decay auto-stop
	const newTrends = [];
	for (const trend of filtered) {
		const alreadyFound = await isAlreadyDiscovered(
			db,
			config.account_group_id,
			trend.topicHash,
		);
		if (alreadyFound) {
			// Trend Prediction 2026 Section 7: auto-stop when trend decayed
			const decayed = await hasTrendDecayed(
				db,
				config.account_group_id,
				trend.topicHash,
			);
			if (decayed) {
				logger.debug(
					"[trend-scanner] Trend decayed past useful window, skipping",
					{
						topic: trend.topic,
						groupId: config.account_group_id,
					},
				);
			}
			continue; // Already discovered (decayed or not)
		}
		newTrends.push(trend);
	}

	// Score trends by acceleration (Trend Prediction 2026, Section 3)
	// Sort by acceleration so high-priority trends get processed first
	const scoredTrends = newTrends
		.map((trend) => {
			const accel = scoreTrendAcceleration(trend.relevanceScore);
			return { ...trend, ...accel };
		})
		.sort((a, b) => b.accelerationScore - a.accelerationScore);

	if (newTrends.length === 0) {
		await db
			.from("trending_topic_config")
			.update({ last_scan_at: new Date().toISOString() })
			.eq("id", config.id);
		return result;
	}

	// Resolve voice profile from account group
	// Note: account_groups does NOT have workspace_id — resolve separately.
	const { data: groupData } = await db
		.from("account_groups")
		.select("name, voice_profile, account_ids")
		.eq("id", config.account_group_id)
		.single();

	if (!groupData) {
		result.skippedReasons.push("no_group");
		return result;
	}

	// Resolve workspace_id from auto_post_group_config (has group_id → workspace_id)
	const { data: groupConfig } = await db
		.from("auto_post_group_config")
		.select("workspace_id")
		.eq("group_id", config.account_group_id)
		.maybeSingle();

	const resolvedWorkspaceId = groupConfig?.workspace_id as string | undefined;
	if (!resolvedWorkspaceId) {
		result.skippedReasons.push("no_workspace");
		return result;
	}

	const voiceProfile = (groupData.voice_profile as VoiceProfile) || null;

	// Get user AI config (Gemini API key)
	const { getUserAIConfig } = await import("../auto-post/contentSelection.js");
	const userAIConfig = await getUserAIConfig(config.user_id);
	if (!userAIConfig) {
		result.skippedReasons.push("no_ai_config");
		return result;
	}

	// Generate and queue posts
	// Trend Prediction 2026 Section 7: max 30% of daily posts from trends (70/30 rule),
	// max 2 trend posts per account per day
	let lastFormat =
		((config.content_preferences as Record<string, unknown>)?.last_format as
			| string
			| undefined) || undefined;
	const maxTrendPosts = Math.min(remainingCap, 2); // Max 2 trend posts per group per scan
	const trendsToProcess = scoredTrends.slice(0, maxTrendPosts);

	for (const trend of trendsToProcess) {
		const format = selectFormat(lastFormat);
		lastFormat = format;

		const generatedContent = await generateTrendPost({
			trend,
			format,
			voiceProfile,
			extractedStyle: null,
			focusTopics: voiceProfile?.focus_topics,
			userAIConfig,
			userId: config.user_id,
		});

		if (!generatedContent) {
			logger.warn("Generation returned null, skipping trend", {
				topic: trend.topic,
				groupId: config.account_group_id,
			});
			continue;
		}

		// Queue for auto-post-worker
		// Trend Prediction 2026 Section 7: speed queue for high-priority trends
		// High priority (acceleration > 2): publish within 1-2h instead of normal batch timing
		const isSpeedQueue = trend.isHighPriority;
		const speedDelay = isSpeedQueue
			? (30 + Math.random() * 90) * 60 * 1000 // 30-120 min for hot trends
			: (2 + Math.random() * 4) * 60 * 60 * 1000; // 2-6h for normal trends
		const trendScheduledFor = new Date(Date.now() + speedDelay).toISOString();
		const queueStatus = "needs_review";
		if (isSpeedQueue) {
			logger.info("[trend-scanner] Speed queue: high-priority trend", {
				topic: trend.topic,
				accelerationScore: trend.accelerationScore,
				trendShape: trend.trendShape,
				scheduledIn: `${Math.round(speedDelay / 60000)}min`,
			});
		}
		const { data: queueInserted, error: queueErr } = await db
			.from("auto_post_queue")
			.insert({
				workspace_id: resolvedWorkspaceId,
				group_id: config.account_group_id,
				content: generatedContent,
				scheduled_for: trendScheduledFor,
				source_type: "trending",
				content_type: format,
				source_content: trend.topic,
				status: queueStatus,
				pool_status: "available",
				metadata: {
					approval: {
						reason: "trend_generated_requires_review",
					},
					trend: {
						topic_hash: trend.topicHash,
						relevance_score: trend.relevanceScore,
						acceleration_score: trend.accelerationScore,
						shape: trend.trendShape,
						speed_queue_candidate: isSpeedQueue,
					},
				},
			})
			.select("id")
			.single();
		if (queueErr) {
			logger.error("[trend-scanner] Failed to insert auto_post_queue", {
				groupId: config.account_group_id,
				topic: trend.topic,
				error: queueErr.message,
			});
			continue;
		}

		if (!queueErr && queueInserted?.id) {
			// Record discovery only after the queue write succeeds so dedupe/daily-cap
			// state reflects work that actually exists.
			const { error: discoveryErr } = await db
				.from("trend_discoveries")
				.insert({
					account_group_id: config.account_group_id,
					user_id: config.user_id,
					topic: trend.topic,
					topic_hash: trend.topicHash,
					context: trend.context,
					relevance_score: trend.relevanceScore,
					status: queueStatus,
					posted_at: trendScheduledFor,
				});
			if (discoveryErr) {
				logger.error("[trend-scanner] Failed to insert trend_discoveries", {
					groupId: config.account_group_id,
					topic: trend.topic,
					error: discoveryErr.message,
				});
			}

			logger.info("[trend-scanner] Trend post queued for review", {
				queueItemId: queueInserted.id,
				groupId: config.account_group_id,
				topic: trend.topic,
			});

			result.postsQueued++;
		}
	}

	// Update last_scan_at and last_format
	await db
		.from("trending_topic_config")
		.update({
			last_scan_at: new Date().toISOString(),
			content_preferences: {
				...(config.content_preferences || {}),
				last_format: lastFormat,
			},
		})
		.eq("id", config.id);

	logger.info("Trend pipeline completed for group", {
		groupId: config.account_group_id,
		trendsFound: result.trendsFound,
		postsQueued: result.postsQueued,
	});

	return result;
}
