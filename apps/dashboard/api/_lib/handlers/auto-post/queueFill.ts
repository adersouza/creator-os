// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Queue Fill Pipeline — Thin Orchestrator
 *
 * Coordinates the AI-powered autoposter queue fill pipeline.
 * Logic is split across 4 modules:
 *   - timingEngine.ts: scheduling, seasonal multipliers, gap enforcement
 *   - evergreenManager.ts: topic tags, humanizer, templates, evergreen recycling
 *   - pipelineFilters.ts: Phase 1 fast filter + Phase 2 embedding dedup
 *   - scheduleAndInsert.ts: media selection, DB insertion, QStash dispatch
 */

import { getUserAIConfig, resolveProvider } from "../../aiConfig.js";
import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import { classifyCompetitorPattern } from "../competitors/metricQuality.js";
import { resolveConfig } from "./configResolver.js";
import {
	type FilterPattern,
	filterContent,
	isThirstVoice,
	resolveFilterConfig,
} from "./contentFilter.js";
import {
	getTodayInTimezone,
	getUserExtractedStyle,
	isTooSimilar,
} from "./contentSelection.js";
import { getRecentPostContext } from "./dataGathering.js";
import { clearEmbeddingCache } from "./embeddingGate.js";
import {
	insertProvenTemplate,
	recycleEvergreenPosts,
} from "./evergreenManager.js";
import { isAutoposterHardDisabled } from "./killSwitch.js";
import { deriveAutoposterRuntimeMode } from "./controlPlane.js";
import { evaluateCompetitorDirectMicrocopy } from "./microcopyPolicy.js";
import { isLLMJudgeCircuitOpen } from "./llmJudgeCircuitBreaker.js";
import {
	loadAccountDnaContext,
	loadCreatorIdentityContext,
} from "./accountDna.js";
import { loadActiveContentArcContext } from "./contentArcs.js";
import {
	loadRecentVariationPosts,
	runEmbeddingDedupPhase,
	runFastFilterPhase,
	runLLMJudgePhase,
} from "./pipelineFilters.js";
import {
	generateAIPostIdeas,
	type GenerationTargetContext,
} from "./promptBuilder.js";
import {
	buildPublishFingerprint,
	findRecentDuplicateFingerprint,
} from "./publishFingerprint.js";
import { evaluateQueueProvenance } from "./provenanceGate.js";
import {
	type InsertionResult,
	insertCandidatesIntoQueue,
	planAccountSlots,
} from "./scheduleAndInsert.js";
import {
	COMPETITOR_SOURCE_TYPES,
	getDirectCompetitorSlots,
	getRequiredCompetitorSlots,
} from "./sourcePolicy.js";
// Sub-module imports
import {
	rebuildAccountHourPerformanceBuckets,
	loadAccountTimingProfiles,
	type AccountTimingProfile,
} from "./accountTimingPerformance.js";
import {
	calculateAccountAwareNaturalPostTimes,
	calculateNaturalPostTimes,
	countPendingPosts,
	getSeasonalMultiplier,
} from "./timingEngine.js";
import type { AutoPostConfig, TimingInsights, VoiceProfile } from "./types.js";
import {
	loadActiveStrategyRecommendations,
	type StrategyRecommendation,
} from "./strategyRecommendations.js";
import type { RestartWarmupPolicy } from "./restartWarmup.js";

export type { EvergreenResult } from "./evergreenManager.js";
export {
	detectTopicTag,
	humanizePost,
	insertProvenTemplate,
	recycleEvergreenPosts,
} from "./evergreenManager.js";
export type {
	AIIdea,
	DedupPipelineResult,
	FilterPipelineResult,
	FilterSurvivor,
	VariationPost,
} from "./pipelineFilters.js";
export {
	loadRecentVariationPosts,
	runEmbeddingDedupPhase,
	runFastFilterPhase,
	runLLMJudgePhase,
} from "./pipelineFilters.js";
export type { InsertionContext, InsertionResult } from "./scheduleAndInsert.js";
export {
	insertCandidatesIntoQueue,
	nudgeScheduleForFormat,
	planAccountSlots,
} from "./scheduleAndInsert.js";
// Re-export everything for backward compatibility — callers import from queueFill.ts
export {
	calculateAccountAwareNaturalPostTimes,
	calculateNaturalPostTimes,
	countPendingPosts,
	getSeasonalMultiplier,
} from "./timingEngine.js";

const db = () => getSupabaseAny();
const COMPETITOR_MICROCOPY_PROMPT_VERSION = "competitor_microcopy_20260605";
const THREADS_PERFORMANCE_PRIMARY_HOURS = [6, 7, 11, 12, 13];
const THREADS_PERFORMANCE_SECONDARY_HOURS = [20, 23];
const THREADS_MIN_IMAGE_TEST_CHANCE = 5;
const THREADS_MAX_IMAGE_TEST_CHANCE = 15;

export function performanceFirstMediaChance(
	targetPlatform: "threads" | "instagram",
	configuredChance: number,
): number {
	if (targetPlatform !== "threads") return configuredChance;
	const requestedChance =
		configuredChance <= 0 ? THREADS_MIN_IMAGE_TEST_CHANCE : configuredChance;
	return Math.min(requestedChance, THREADS_MAX_IMAGE_TEST_CHANCE);
}

function performanceFirstTimingInsights(
	targetPlatform: "threads" | "instagram",
	insights: TimingInsights,
): TimingInsights {
	if (targetPlatform !== "threads") return insights;
	return {
		...insights,
		bestPostingHours: [
			...new Set([
				...THREADS_PERFORMANCE_PRIMARY_HOURS,
				...(insights.bestPostingHours ?? []),
				...THREADS_PERFORMANCE_SECONDARY_HOURS,
			]),
		],
	};
}

function recommendationMetricBasis(
	recommendation: StrategyRecommendation,
): Record<string, unknown> {
	const basis = recommendation.metric_basis;
	return basis && typeof basis === "object" && !Array.isArray(basis)
		? (basis as Record<string, unknown>)
		: {};
}

function summarizeActiveStrategyRecommendations(
	recommendations: StrategyRecommendation[],
) {
	const byPatternType: Record<string, number> = {};
	for (const recommendation of recommendations) {
		byPatternType[recommendation.pattern_type] =
			(byPatternType[recommendation.pattern_type] ?? 0) + 1;
	}
	const winnerClones = recommendations.filter(
		(recommendation) => recommendation.pattern_type === "winner_clone",
	);
	const confidences = winnerClones
		.map((recommendation) => recommendation.confidence)
		.filter((value) => Number.isFinite(value));
	const cloneFamilies = [
		...new Set(
			winnerClones
				.map((recommendation) => {
					const basis = recommendationMetricBasis(recommendation);
					const family = basis.cloneFamily;
					return typeof family === "string" && family.trim()
						? family.trim()
						: "unknown";
				})
				.filter(Boolean),
		),
	].sort();
	const now = Date.now();
	const expiredCount = winnerClones.filter(
		(recommendation) =>
			recommendation.expires_at &&
			new Date(recommendation.expires_at).getTime() <= now,
	).length;
	return {
		total: recommendations.length,
		byPatternType,
		winnerCloneCount: winnerClones.length,
		winnerCloneFamilies: cloneFamilies,
		winnerCloneRecommendationIds: winnerClones
			.map((recommendation) => recommendation.id)
			.filter((id): id is string => Boolean(id))
			.slice(0, 20),
		winnerCloneConfidenceMin:
			confidences.length > 0 ? Math.min(...confidences) : null,
		winnerCloneConfidenceMax:
			confidences.length > 0 ? Math.max(...confidences) : null,
		winnerCloneExpiredCount: expiredCount,
	};
}

type PlannedAccountSlot = {
	accountId: string;
	roundRobinIndex: number;
	isProbe?: boolean | undefined;
	warmupPolicy?: RestartWarmupPolicy | undefined;
	timezone?: string | undefined;
	activeHoursStart?: number | undefined;
	activeHoursEnd?: number | undefined;
	minIntervalMinutes?: number | undefined;
};

const DIRECT_COMPETITOR_HARD_REJECT_PATTERNS = [
	/\bfree\s+meet\s*up\b/i,
	/\b(single\s+(mom|mommy|mother)|gym\s+mom)\b/i,
	/\btoo\s+old\s*\(\s*200[0-9]\s*\)/i,
	/\bbeautiful\b.*\bprofile pic\b/i,
	/\bwho\s+got\s+candy\s+grapes\b/i,
];

function passesMicrocopyContentGate(
	content: string,
	contentFilterConfig: ReturnType<typeof resolveFilterConfig>,
	avoidWords?: string[],
): boolean {
	const normalized = content.trim();
	if (!normalized) return false;

	for (const pattern of DIRECT_COMPETITOR_HARD_REJECT_PATTERNS) {
		if (pattern.test(normalized)) return false;
	}

	const filterResult = filterContent(
		normalized,
		contentFilterConfig,
		"competitor_direct_microcopy",
		undefined,
		avoidWords,
	);
	return filterResult.passed;
}

async function loadGenerationTargetContexts(input: {
	workspaceId: string;
	groupId?: string | undefined;
	slots: PlannedAccountSlot[];
}): Promise<GenerationTargetContext[]> {
	const uniqueSlots = new Map<string, PlannedAccountSlot>();
	for (const slot of input.slots) {
		if (!uniqueSlots.has(slot.accountId)) uniqueSlots.set(slot.accountId, slot);
	}

	const contextByAccount = new Map<string, GenerationTargetContext>();
	await Promise.all(
		[...uniqueSlots.values()].map(async (slot) => {
			const [dnaContext, creatorIdentity, contentArc] = await Promise.all([
				loadAccountDnaContext({
					workspaceId: input.workspaceId,
					groupId: input.groupId,
					accountId: slot.accountId,
				}),
				loadCreatorIdentityContext({
					workspaceId: input.workspaceId,
					groupId: input.groupId,
					accountId: slot.accountId,
				}),
				loadActiveContentArcContext({
					workspaceId: input.workspaceId,
					groupId: input.groupId,
					accountId: slot.accountId,
				}),
			]);
			contextByAccount.set(slot.accountId, {
				accountId: slot.accountId,
				roundRobinIndex: slot.roundRobinIndex,
				isProbe: slot.isProbe,
				warmupPolicy: slot.warmupPolicy,
				creatorDna: creatorIdentity.creatorDna,
				accountFlavor: creatorIdentity.accountFlavor,
				dna: dnaContext.dna,
				rules: dnaContext.rules,
				siblingRules: dnaContext.siblingRules,
				contentArc,
			});
		}),
	);

	return input.slots
		.map((slot) => contextByAccount.get(slot.accountId))
		.filter((context): context is GenerationTargetContext => !!context);
}

async function loadLearnedTimingProfilesForSlots(input: {
	workspaceId: string;
	groupId?: string | undefined;
	slots: PlannedAccountSlot[];
	targetPlatform: "threads" | "instagram";
	refresh?: boolean | undefined;
}): Promise<Map<string, AccountTimingProfile>> {
	const accountIds = [
		...new Set(input.slots.map((slot) => slot.accountId).filter(Boolean)),
	];
	if (input.targetPlatform !== "threads" || accountIds.length === 0) {
		return new Map();
	}
	if (input.refresh) {
		await rebuildAccountHourPerformanceBuckets({
			workspaceId: input.workspaceId,
			groupId: input.groupId,
			accountIds,
		});
	}
	return loadAccountTimingProfiles({
		workspaceId: input.workspaceId,
		groupId: input.groupId,
		accountIds,
	});
}

async function getOwnerCompetitorIds(
	ownerId: string,
	allowedCompetitorIds?: string[],
): Promise<string[]> {
	let query = db()
		.from("competitors")
		.select("id")
		.eq("user_id", ownerId)
		.or("sync_status.eq.active,sync_status.is.null");

	if (allowedCompetitorIds && allowedCompetitorIds.length > 0) {
		query = query.in("id", allowedCompetitorIds);
	}

	const { data, error } = await query;
	if (error || !data) {
		logger.warn("[queueFill] Failed to load owner competitors", {
			ownerId,
			error: error?.message,
		});
		return [];
	}

	return data.map((row) => row.id).filter(Boolean);
}

async function getLiveQueueSourceMix(
	workspaceId: string,
	groupId?: string,
): Promise<{ queueSize: number; competitorCount: number }> {
	let totalQuery = db()
		.from("auto_post_queue")
		.select("id", { count: "exact", head: true })
		.eq("workspace_id", workspaceId)
		.in("status", ["pending", "queued", "claimed"]);

	if (groupId) {
		totalQuery = totalQuery.eq("group_id", groupId);
	}

	const { count: queueSize, error: totalError } = await totalQuery;
	if (totalError) {
		logger.warn("[queueFill] Failed to load live queue source mix", {
			workspaceId,
			groupId,
			error: totalError.message,
		});
		return { queueSize: 0, competitorCount: 0 };
	}

	let competitorQuery = db()
		.from("auto_post_queue")
		.select("id", { count: "exact", head: true })
		.eq("workspace_id", workspaceId)
		.in("status", ["pending", "queued", "claimed"])
		.in("source_type", Array.from(COMPETITOR_SOURCE_TYPES));

	if (groupId) {
		competitorQuery = competitorQuery.eq("group_id", groupId);
	}

	const { count: competitorCount, error: competitorError } =
		await competitorQuery;
	if (competitorError) {
		logger.warn("[queueFill] Failed to load competitor queue mix", {
			workspaceId,
			groupId,
			error: competitorError.message,
		});
		return {
			queueSize: queueSize ?? 0,
			competitorCount: 0,
		};
	}

	return {
		queueSize: queueSize ?? 0,
		competitorCount: competitorCount ?? 0,
	};
}

// ============================================================================
// Public Entry Point
// ============================================================================

export async function checkAndFillQueueWithAI(
	config: AutoPostConfig,
	workspaceId: string,
	ownerId: string,
	groupId?: string,
): Promise<{ filled: boolean; count: number; reason?: string | undefined }> {
	if (isAutoposterHardDisabled()) {
		logger.warn("AI queue fill: globally hard disabled", {
			workspaceId,
			groupId,
		});
		return { filled: false, count: 0, reason: "autoposter_hard_disabled" };
	}

	const runtimeMode = deriveAutoposterRuntimeMode({
		is_enabled: config.is_enabled !== false,
		group_mode_enabled: config.group_mode_enabled !== false,
		enable_ai_queue_fill: Boolean(config.enable_ai_queue_fill),
		hard_disabled: false,
	});
	if (runtimeMode === "paused" || runtimeMode === "group_mode_disabled") {
		logger.info("AI queue fill: autoposter runtime disabled", {
			workspaceId,
			groupId,
			runtimeMode,
			isEnabled: config.is_enabled,
			groupModeEnabled: config.group_mode_enabled,
			enableAiQueueFill: config.enable_ai_queue_fill,
		});
		return { filled: false, count: 0, reason: runtimeMode };
	}

	logger.info("checkAndFillQueueWithAI", {
		enableAiQueueFill: config.enable_ai_queue_fill,
	});

	if (!config.enable_ai_queue_fill) {
		logger.info("AI queue fill: disabled in config", {
			enableAiQueueFill: config.enable_ai_queue_fill,
		});
		return { filled: false, count: 0, reason: "ai_queue_fill_disabled" };
	}

	// ================================================================
	// Redis lock — prevent concurrent fills for the same group
	// ================================================================
	// biome-ignore lint/suspicious/noExplicitAny: Redis client type varies by environment
	let redis: any = null;
	const lockKey = `ai-fill-lock:${workspaceId}:${groupId ?? "workspace"}`;
	try {
		const { getRedis } = await import("../../redis.js");
		redis = getRedis();
	} catch (err) {
		logger.warn("AI queue fill lock unavailable; skipping fill", {
			workspaceId,
			groupId,
			error: err instanceof Error ? err.message : String(err),
		});
		return { filled: false, count: 0, reason: "lock_unavailable" };
	}
	if (redis) {
		let acquired: unknown;
		try {
			acquired = await redis.set(lockKey, "1", { nx: true, ex: 180 });
		} catch (err) {
			logger.warn("AI queue fill lock acquisition failed; skipping fill", {
				workspaceId,
				groupId,
				error: err instanceof Error ? err.message : String(err),
			});
			return { filled: false, count: 0, reason: "lock_unavailable" };
		}
		if (!acquired) {
			logger.info("AI queue fill already running for group, skipping", {
				workspaceId,
				groupId,
			});
			return { filled: false, count: 0, reason: "concurrent-fill-locked" };
		}
	}

	try {
		const fillStart = Date.now();
		const result = await _checkAndFillQueueWithAIInner(
			config,
			workspaceId,
			ownerId,
			groupId,
		);
		// Log early exits to queue_fill_log (the inner function logs full fills itself)
		if (result.reason && result.count === 0) {
			try {
				await db()
					.from("queue_fill_log")
					.insert({
						workspace_id: workspaceId,
						group_id: groupId ?? null,
						started_at: new Date(fillStart).toISOString(),
						posts_inserted: 0,
						posts_generated: 0,
						posts_rejected: 0,
						duration_ms: Date.now() - fillStart,
						early_exit_reason: result.reason,
					} as Record<string, unknown>);
			} catch {
				/* non-critical */
			}
		}
		if (shouldReleaseDispatchCooldown(result.reason)) {
			await releaseQueueFillDispatchCooldown(workspaceId, groupId, result.reason);
		} else if (shouldShortenDispatchCooldown(result.reason)) {
			await shortenQueueFillDispatchCooldown(workspaceId, groupId, result.reason);
		}
		return result;
	} finally {
		if (redis) {
			try {
				await redis.del(lockKey);
			} catch {
				/* best-effort unlock */
			}
		}
	}
}

function shouldReleaseDispatchCooldown(reason: string | undefined): boolean {
	return reason === "ai_returned_empty";
}

function shouldShortenDispatchCooldown(reason: string | undefined): boolean {
	return reason === "underfilled_queue_still_low";
}

async function releaseQueueFillDispatchCooldown(
	workspaceId: string,
	groupId: string | undefined,
	reason: string | undefined,
): Promise<void> {
	try {
		const { getRedis } = await import("../../redis.js");
		const redis = getRedis();
		const cooldownKey = `queue-fill-cooldown:${workspaceId}:${groupId ?? "workspace"}`;
		await redis.del(cooldownKey);
		logger.warn("Released queue-fill dispatch cooldown after failed fill", {
			workspaceId,
			groupId,
			reason,
		});
	} catch (err) {
		logger.warn("Failed to release queue-fill dispatch cooldown", {
			workspaceId,
			groupId,
			reason,
			error: err instanceof Error ? err.message : String(err),
		});
	}
}

async function shortenQueueFillDispatchCooldown(
	workspaceId: string,
	groupId: string | undefined,
	reason: string | undefined,
): Promise<void> {
	try {
		const { getRedis } = await import("../../redis.js");
		const redis = getRedis();
		const cooldownKey = `queue-fill-cooldown:${workspaceId}:${groupId ?? "workspace"}`;
		await redis.set(cooldownKey, "underfilled", { ex: 60 * 60 });
		logger.warn("Shortened queue-fill dispatch cooldown after underfilled fill", {
			workspaceId,
			groupId,
			reason,
			cooldownSeconds: 60 * 60,
		});
	} catch (err) {
		logger.warn("Failed to shorten queue-fill dispatch cooldown", {
			workspaceId,
			groupId,
			reason,
			error: err instanceof Error ? err.message : String(err),
		});
	}
}

// ============================================================================
// Inner Orchestrator
// ============================================================================

async function _checkAndFillQueueWithAIInner(
	config: AutoPostConfig,
	workspaceId: string,
	ownerId: string,
	groupId?: string,
): Promise<{ filled: boolean; count: number; reason?: string | undefined }> {
	const fillStartTime = Date.now();
	// Trace ID for correlating all logs/rejections/insertions from this fill cycle
	const fillCycleId = `fill-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
	logger.info("AI queue fill starting", { fillCycleId, workspaceId, groupId });

	// Check scheduler version for pool mode
	const { data: wsVersionRow } = await db()
		.from("auto_post_config")
		.select("scheduler_version")
		.eq("workspace_id", workspaceId)
		.maybeSingle();
	const schedulerVersion: number = wsVersionRow?.scheduler_version ?? 1;

	// ── Step 0: Resolve all config sources once (group, voice, strategy, AI, overrides) ──
	const resolved = await resolveConfig(config, workspaceId, ownerId, groupId);
	const groupConfig = resolved.groupTimingConfig;

	if (await isLLMJudgeCircuitOpen(workspaceId, groupId)) {
		logger.warn("AI queue fill blocked: LLM judge circuit is open", {
			workspaceId,
			groupId,
			reason: "llm_judge_skip_rate",
		});
		return { filled: false, count: 0, reason: "llm_judge_circuit_open" };
	}

	// ── Step 1: Calculate batch size ──
	const basePostsPerFill = config.ai_posts_per_fill ?? 2;
	let postsPerFill: number;

	if (groupId) {
		const accountCount = resolved.groupAccountIds.length || 1;
		const perDay = (groupConfig?.posts_per_account_per_day as number) ?? 1;
		// For groups consuming >= 2 posts/account/day, generate 1.5 days of content
		// to prevent queue drain between 4h fill windows.
		// e.g. 3 accounts * 2/day = 6/day → 6 * 1.5 = 9 posts per fill
		const consumptionMultiplier = perDay >= 2 ? 1.5 : 1;
		const dailyNeed = Math.min(
			30,
			Math.max(
				basePostsPerFill,
				Math.ceil(accountCount * perDay * 2 * consumptionMultiplier),
			),
		);
		postsPerFill = dailyNeed;
	} else {
		postsPerFill = basePostsPerFill;
	}

	// Seasonal + weekend volume modifiers
	const seasonalMultiplier = getSeasonalMultiplier();
	postsPerFill = Math.max(1, Math.round(postsPerFill * seasonalMultiplier));

	const configTz =
		groupConfig?.timezone ??
		config.posting_times?.timezone ??
		"America/New_York";
	let currentDayOfWeek: number;
	try {
		const dayName = new Date()
			.toLocaleDateString("en-US", {
				weekday: "long",
				timeZone: configTz || "UTC",
			})
			.toLowerCase();
		currentDayOfWeek =
			dayName === "saturday" ? 6 : dayName === "sunday" ? 0 : -1;
	} catch {
		const d = new Date();
		currentDayOfWeek = d.getUTCDay();
	}
	if (currentDayOfWeek === 0 || currentDayOfWeek === 6) {
		postsPerFill = Math.max(1, Math.round(postsPerFill * 0.6));
		logger.info("Weekend volume reduction applied (40%)", {
			dayOfWeek: currentDayOfWeek,
			adjustedPostsPerFill: postsPerFill,
		});
	}

	// Cross-platform performance monitoring (for "both" platform workspaces)
	// Logs which platform is outperforming and by how much.
	// Future: auto-adjust volume split based on performance gap.
	if (config.platform === "both" || config.platform === "instagram") {
		try {
			const { logCrossPlatformInsight } = await import(
				"./crossPlatformMonitor.js"
			);
			await logCrossPlatformInsight(workspaceId, ownerId);
		} catch {
			/* non-critical */
		}
	}

	// ── Step 2: Daily limit check ──
	const dailyLimit = config.ai_daily_generation_limit ?? 3000;
	const configTimezone =
		groupConfig?.timezone ?? config.posting_times?.timezone;
	const today = getTodayInTimezone(configTimezone);
	const dateChanged = config.ai_last_generation_date !== today;

	const roughGenerationsToday = dateChanged
		? 0
		: (config.ai_generations_today ?? 0);

	const pendingCount = await countPendingPosts(workspaceId, groupId);
	// Threshold must cover at least 1 full day of consumption so fills trigger
	// before the queue drains. Groups with 3 accounts * 2/day = 6 need threshold ≥ 6.
	const groupAccountCount = resolved.groupAccountIds.length || 1;
	const groupPerDay = (groupConfig?.posts_per_account_per_day as number) ?? 1;
	const effectiveThreshold = Math.max(
		config.ai_queue_min_threshold ?? 3,
		Math.floor(postsPerFill / 2),
		groupAccountCount * groupPerDay, // ensure threshold covers at least 1 full day
	);

	if (pendingCount >= effectiveThreshold) {
		logger.info("AI queue fill: pending count above threshold", {
			pendingCount,
			effectiveThreshold,
			postsPerFill,
			workspaceId,
			groupId,
		});
		return { filled: false, count: 0, reason: "pending_above_threshold" };
	}

	logger.info("AI batch fill: generating full day's content", {
		groupId,
		postsPerFill,
		pendingCount,
		effectiveThreshold,
	});

	const targetPlatform = resolved.targetPlatform;

	// ── Step 3: Voice profile + content strategy (from resolved config) + filter config ──
	let contentFilterConfig = resolveFilterConfig(
		(config as unknown as Record<string, unknown>).content_filter_patterns as
			| FilterPattern[]
			| null,
		(config as unknown as Record<string, unknown>).content_filter_max_length as
			| number
			| null,
		(config as unknown as Record<string, unknown>).content_filter_max_emojis as
			| number
			| null,
		(config as unknown as Record<string, unknown>).content_filter_min_length as
			| number
			| null,
	);

	type ContentStrategy = {
		pillars?: string[] | undefined;
		topics_to_avoid?: string[] | undefined;
		cta_rotation?: string[] | undefined;
		tone_notes?: string | undefined;
		weekly_target?: number | undefined;
		competitor_ids?: string[] | undefined;
		data_driven_insights?: Record<string, unknown> | undefined;
		peak_windows?: Array<{ day: string; hour: number }> | undefined;
	};
	const voiceProfile: VoiceProfile | null = resolved.voiceProfile;
	const contentStrategy: ContentStrategy | null =
		resolved.contentStrategy as ContentStrategy | null;
	const resolvedGroupName = resolved.groupName;
	const accountIds: string[] = resolved.groupAccountIds;
	const schedulingInsights: TimingInsights = {
		bestPostingHours:
			(contentStrategy?.data_driven_insights?.best_posting_hours as
				| number[]
				| undefined) ?? [],
		peakWindows: contentStrategy?.peak_windows ?? [],
		timezone:
			groupConfig?.timezone ??
			config.posting_times?.timezone ??
			"America/New_York",
		activeHoursStart: groupConfig?.active_hours_start ?? 0,
		activeHoursEnd: groupConfig?.active_hours_end ?? 24,
	};
	const performanceTimingInsights = performanceFirstTimingInsights(
		targetPlatform,
		schedulingInsights,
	);

	// Rebuild content filter with thirst niche mode if needed
	if (isThirstVoice(voiceProfile?.voice_profile ?? null)) {
		contentFilterConfig = resolveFilterConfig(
			(config as unknown as Record<string, unknown>).content_filter_patterns as
				| FilterPattern[]
				| null,
			(config as unknown as Record<string, unknown>)
				.content_filter_max_length as number | null,
			(config as unknown as Record<string, unknown>)
				.content_filter_max_emojis as number | null,
			(config as unknown as Record<string, unknown>)
				.content_filter_min_length as number | null,
			"thirst",
		);
	}

	// ── Step 4: Direct competitor microcopy lane (small, account-scoped quota) ──
	// This path does not need an AI key or generation quota. It only allows short,
	// generic social shorthand after DNA, duplicate, sibling, recency, and source
	// overuse checks. Low-confidence candidates are skipped for AI rewrite.
	const insertDirectCompetitorPosts = async (
		slotsAvailable: number,
	): Promise<number> => {
		const ownerCompetitorIds = await getOwnerCompetitorIds(
			ownerId,
			contentStrategy?.competitor_ids,
		);
		const liveQueueMix = await getLiveQueueSourceMix(workspaceId, groupId);
		const policyDrivenCompSlots = getDirectCompetitorSlots(slotsAvailable);
		const queueRequiredCompSlots = getRequiredCompetitorSlots({
			currentQueueSize: liveQueueMix.queueSize,
			currentCompetitorCount: liveQueueMix.competitorCount,
			slotsAvailable,
		});
		const directCompSlots = policyDrivenCompSlots;
		let inserted = 0;
		if (
			directCompSlots <= 0 ||
			!groupId ||
			ownerCompetitorIds.length === 0 ||
			accountIds.length === 0
		) {
			if (groupId && directCompSlots > 0) {
				logger.warn(
					"[queueFill] No eligible inputs for competitor microcopy insert",
					{
						groupId,
						ownerId,
						directCompSlots,
						accountCount: accountIds.length,
					},
				);
			}
			return 0;
		}

		try {
			const { data: compPosts } = await db()
				.from("competitor_top_posts")
				.select(
					"id, content, competitor_id, competitor_username, hook_type, topic_label, format_type, emotional_frame, reply_mechanism, content_length_bucket, media_style, scraped_at",
				)
				.in("competitor_id", ownerCompetitorIds)
				.not("content", "is", null)
				.gt("content", "")
				.gte(
					"published_at",
					new Date(Date.now() - 14 * 86_400_000).toISOString(),
				)
				.order("scraped_at", { ascending: false, nullsFirst: false })
				.limit(200);

			if (!compPosts || compPosts.length === 0) return 0;

			const eligible = (
				compPosts as Array<{
					id: string;
					content: string;
					competitor_id: string | null;
					competitor_username: string | null;
					hook_type?: string | null;
					topic_label?: string | null;
					format_type?: string | null;
					emotional_frame?: string | null;
					reply_mechanism?: string | null;
					content_length_bucket?: string | null;
					media_style?: string | null;
				}>
			)
				.filter(
					(p) =>
						p.content.trim().split(/\s+/).filter(Boolean).length <= 12 ||
						p.content.trim().length <= 60,
				)
				.filter(
					(p) =>
						!/snap[: ]/i.test(p.content) &&
						!/@\w/.test(p.content) &&
						!/telegram/i.test(p.content),
				)
				.filter((p) =>
					passesMicrocopyContentGate(
						p.content,
						contentFilterConfig,
						voiceProfile?.avoid_words,
					),
				);

			const { data: existingContent } = await db()
				.from("auto_post_queue")
				.select("content")
				.eq("workspace_id", workspaceId)
				.in("status", ["pending", "queued", "published"])
				.gte("created_at", new Date(Date.now() - 7 * 86_400_000).toISOString());

			const existingNormalized = (existingContent ?? [])
				.map((r: { content: string }) => r.content)
				.filter((value): value is string => !!value);
			const existingSet = new Set(
				existingNormalized.map((value) => value.toLowerCase().trim()),
			);
			const fresh = eligible.filter((p) => {
				const normalized = p.content.toLowerCase().trim();
				if (existingSet.has(normalized)) return false;
				return !isTooSimilar(p.content, existingNormalized, 0.52);
			});

			const compCount = new Map<string, number>();
			const patternCount = new Map<string, number>();
			const maxPerComp = Math.max(
				1,
				Math.ceil(directCompSlots / Math.min(ownerCompetitorIds.length, 10)),
			);
			const batchContentSet = new Set<string>();
			const capped = fresh
				.sort(() => Math.random() - 0.5)
				.filter((p) => {
					const cid = p.competitor_id || "unknown";
					const cnt = compCount.get(cid) || 0;
					if (cnt >= maxPerComp) return false;
					const patternKey = `${p.hook_type || "unknown"}:${p.topic_label || "uncategorized"}`;
					const patternCnt = patternCount.get(patternKey) || 0;
					if (patternCnt >= 2 && directCompSlots > 4) return false;
					const norm = p.content.toLowerCase().trim();
					if (batchContentSet.has(norm)) return false;
					compCount.set(cid, cnt + 1);
					patternCount.set(patternKey, patternCnt + 1);
					batchContentSet.add(norm);
					return true;
				});
			const shuffled = capped.slice(0, directCompSlots * 4);
			const microcopyPlan = await planAccountSlots(
				groupId,
				workspaceId,
				ownerId,
				directCompSlots,
				resolved,
			);
			const microcopySlots = microcopyPlan.slots.slice(0, directCompSlots);
			const warmupBlockedMicrocopy = microcopySlots.filter(
				(slot) => slot.warmupPolicy && !slot.warmupPolicy.directMicrocopyAllowed,
			).length;
			const warmupEligibleMicrocopySlots = microcopySlots.filter(
				(slot) => !slot.warmupPolicy || slot.warmupPolicy.directMicrocopyAllowed,
			);
			if (microcopySlots.length === 0) {
				logger.warn("[queueFill] Competitor microcopy skipped: no account slots", {
					groupId,
					workspaceId,
					directCompSlots,
				});
				return 0;
			}
			if (warmupBlockedMicrocopy > 0) {
				logger.info("[queueFill] Competitor microcopy reduced during restart warm-up", {
					groupId,
					workspaceId,
					warmupBlockedMicrocopy,
				});
			}
			const targetContexts = await loadGenerationTargetContexts({
				workspaceId,
				groupId,
				slots: warmupEligibleMicrocopySlots,
			});
			const directTimingProfiles = await loadLearnedTimingProfilesForSlots({
				workspaceId,
				groupId,
				slots: warmupEligibleMicrocopySlots,
				targetPlatform,
			});
			const directScheduledTimes = calculateAccountAwareNaturalPostTimes({
				plannedSlots: warmupEligibleMicrocopySlots,
				config,
				groupId,
				groupAccountCount: accountIds.length,
				insights: performanceTimingInsights,
				platform: targetPlatform === "instagram" ? "instagram" : "threads",
				accountProfiles: directTimingProfiles,
			});

			let candidateIndex = 0;
			for (
				let i = 0;
				i < warmupEligibleMicrocopySlots.length && candidateIndex < shuffled.length;
				i++
			) {
				const scheduledSelection = directScheduledTimes[i];
				const scheduledFor =
					scheduledSelection?.scheduledFor || new Date().toISOString();
				const sourcePost = shuffled[candidateIndex++]!;
				const slot = warmupEligibleMicrocopySlots[i]!;
				const targetContext =
					targetContexts.find((context) => context.accountId === slot.accountId) ??
					null;
				const attribution = classifyCompetitorPattern({
					content: sourcePost.content,
					topicTag: sourcePost.topic_label,
					mediaType: sourcePost.media_style === "text_only" ? "TEXT" : "IMAGE",
					publishedAt: scheduledFor,
				});
				const fingerprint = buildPublishFingerprint({
					workspaceId,
					accountId: slot.accountId,
					platform: targetPlatform === "instagram" ? "instagram" : "threads",
					content: sourcePost.content,
					mediaUrls: null,
				});
				const duplicateMatch = await findRecentDuplicateFingerprint({
					workspaceId,
					accountId: slot.accountId,
					platform: targetPlatform === "instagram" ? "instagram" : "threads",
					normalizedTextHash: fingerprint.normalizedTextHash,
					mediaFingerprint: fingerprint.mediaFingerprint,
					duplicateWindowHours: 24,
				});
				const oneDayAgo = new Date(Date.now() - 86_400_000).toISOString();
				const sevenDaysAgo = new Date(
					Date.now() - 7 * 86_400_000,
				).toISOString();
				const { count: recentAccountMicrocopy } = await db()
					.from("auto_post_queue")
					.select("id", { count: "exact", head: true })
					.eq("workspace_id", workspaceId)
					.eq("account_id", slot.accountId)
					.eq("source_type", "competitor_direct_microcopy")
					.gte("created_at", oneDayAgo);
				const { count: recentSourceMicrocopy } = await db()
					.from("auto_post_queue")
					.select("id", { count: "exact", head: true })
					.eq("workspace_id", workspaceId)
					.eq("source_type", "competitor_direct_microcopy")
					.eq("source_competitor_id", sourcePost.competitor_id)
					.gte("created_at", sevenDaysAgo);
				const { data: previousAccountRows } = await db()
					.from("auto_post_queue")
					.select("source_type")
					.eq("workspace_id", workspaceId)
					.eq("account_id", slot.accountId)
					.order("created_at", { ascending: false })
					.limit(1);
				const wasBackToBack =
					(previousAccountRows as Array<{ source_type?: string | null }> | null)
						?.[0]?.source_type === "competitor_direct_microcopy";
				const microcopyDecision = evaluateCompetitorDirectMicrocopy({
					content: sourcePost.content,
					dna: targetContext?.dna ?? null,
					rules: targetContext?.rules ?? [],
					siblingRules: targetContext?.siblingRules ?? [],
					attribution: {
						hook_type: sourcePost.hook_type || attribution.hook_type,
						topic_label: sourcePost.topic_label || attribution.topic_label,
						format_type: "competitor_direct_microcopy",
						emotional_frame:
							sourcePost.emotional_frame || attribution.emotional_frame,
						reply_mechanism:
							sourcePost.reply_mechanism || attribution.reply_mechanism,
						content_length_bucket:
							sourcePost.content_length_bucket ||
							attribution.content_length_bucket,
						media_style: sourcePost.media_style || attribution.media_style,
					},
					duplicateMatch: !!duplicateMatch,
					usedRecently: (recentAccountMicrocopy ?? 0) > 0,
					sourceOverused: (recentSourceMicrocopy ?? 0) >= 3,
					quotaAvailable: inserted < directCompSlots,
					wasBackToBack,
				});
				if (microcopyDecision.decision !== "queue") {
					if (microcopyDecision.decision === "rewrite") {
						logger.info(
							"[queueFill] Competitor microcopy routed to AI rewrite",
							{
								groupId,
								accountId: slot.accountId,
								sourcePostId: sourcePost.id,
								confidence: microcopyDecision.confidence,
								reasons: microcopyDecision.reasons,
							},
						);
					}
					i -= 1;
					continue;
				}
				const provenanceCheck = evaluateQueueProvenance({
					source_type: "competitor_direct_microcopy",
					source_competitor_id: sourcePost.competitor_id,
					content_fingerprint: fingerprint.normalizedTextHash,
					publish_fingerprint: fingerprint.publishFingerprint,
					source_id: sourcePost.id,
					metadata: {
						quality_gate: {
							decision: "pass",
							reason: "policy:competitor_direct_microcopy",
						},
					},
				});
				const { error: insertErr } = await db()
					.from("auto_post_queue")
					.insert({
						workspace_id: workspaceId,
						group_id: groupId,
						account_id: slot.accountId,
						content: sourcePost.content,
						source_content: sourcePost.content,
						status: "pending",
						pool_status: "available",
						scheduled_for: scheduledFor,
						platform: targetPlatform === "instagram" ? "instagram" : "threads",
						source_type: "competitor_direct_microcopy",
						source_competitor_id: sourcePost.competitor_id,
						source_competitor_username: sourcePost.competitor_username,
						normalized_text_hash: fingerprint.normalizedTextHash,
						media_fingerprint: fingerprint.mediaFingerprint,
						publish_fingerprint: fingerprint.publishFingerprint,
						duplicate_window_hours: fingerprint.duplicateWindowHours,
						content_fingerprint: fingerprint.normalizedTextHash,
						source_id: sourcePost.id,
						source_pattern_id: "competitor_direct_microcopy",
						hook_type: sourcePost.hook_type || attribution.hook_type,
						topic_label: sourcePost.topic_label || attribution.topic_label,
						format_type: "competitor_direct_microcopy",
						emotional_frame:
							sourcePost.emotional_frame || attribution.emotional_frame,
						reply_mechanism:
							sourcePost.reply_mechanism || attribution.reply_mechanism,
						content_length_bucket:
							sourcePost.content_length_bucket ||
							attribution.content_length_bucket,
						media_style: sourcePost.media_style || attribution.media_style,
						posting_hour: attribution.posting_hour,
						prompt_version: COMPETITOR_MICROCOPY_PROMPT_VERSION,
						model_provider: null,
						template_id: null,
						provenance_status: provenanceCheck.status,
						provenance_error:
							provenanceCheck.reasons.length > 0
								? provenanceCheck.reasons.join(",")
								: null,
						metadata: {
							pattern_type: "competitor_direct_microcopy",
							source_competitor_post_id: sourcePost.id,
							source_competitor_id: sourcePost.competitor_id,
							source_competitor_username: sourcePost.competitor_username,
							direct_copy_reason: microcopyDecision.directCopyReason,
							microcopy_confidence: microcopyDecision.confidence,
							microcopy_reasons: microcopyDecision.reasons,
							timing: scheduledSelection?.timing ?? null,
							quality_gate: {
								decision: "pass",
								reason: "policy:competitor_direct_microcopy",
							},
							dna: {
								decision: microcopyDecision.dnaDecision.decision,
								reasons: microcopyDecision.dnaDecision.reasons,
							},
						},
					});
				if (!insertErr) inserted++;
			}
			logger.info("[queueFill] Competitor direct microcopy inserted", {
				groupId,
				inserted,
				eligible: fresh.length,
				liveQueueSize: liveQueueMix.queueSize,
				liveCompetitorCount: liveQueueMix.competitorCount,
				policyDrivenCompSlots,
				queueRequiredCompSlots,
			});
		} catch (compErr) {
			logger.warn(
				"[queueFill] Competitor microcopy insert failed (non-blocking)",
				{
					error: compErr instanceof Error ? compErr.message : String(compErr),
				},
			);
		}
		return inserted;
	};

	const directInserted = await insertDirectCompetitorPosts(postsPerFill);

	if (roughGenerationsToday >= dailyLimit) {
		logger.info("AI queue fill: daily limit reached", {
			generationsToday: roughGenerationsToday,
			dailyLimit,
			directInserted,
		});
		return directInserted > 0
			? {
					filled: true,
					count: directInserted,
					reason: "direct_competitor_only_daily_limit",
				}
			: { filled: false, count: 0, reason: "daily_limit_reached" };
	}

	// ── Step 5: Resolve AI provider ──
	const workspaceProvider = (config as unknown as Record<string, unknown>)
		.ai_provider as string | undefined;
	let aiConfig = resolveProvider(await getUserAIConfig(ownerId), {
		workspaceProvider,
	});

	if (!aiConfig?.apiKey) {
		logger.warn("AI queue fill: no API key found", { ownerId, directInserted });
		return directInserted > 0
			? {
					filled: true,
					count: directInserted,
					reason: "direct_competitor_only_no_api_key",
				}
			: { filled: false, count: 0, reason: "no_api_key" };
	}

	// Validate key health (cached in Redis, fail-open)
	const { isKeyHealthy } = await import("../../aiConfig.js");
	if (!(await isKeyHealthy(aiConfig, ownerId))) {
		logger.warn("AI queue fill: key failed health check", {
			ownerId,
			provider: aiConfig.provider,
			directInserted,
		});
		return directInserted > 0
			? {
					filled: true,
					count: directInserted,
					reason: "direct_competitor_only_key_unhealthy",
				}
			: { filled: false, count: 0, reason: "key_unhealthy" };
	}

	// Per-persona failure routing — check recent reject rate
	if (groupId && aiConfig.provider === "gemini") {
		try {
			const { data: recentStats } = await db()
				.from("auto_post_queue")
				.select("status")
				.eq("workspace_id", workspaceId)
				.eq("group_id", groupId)
				.in("status", [
					"pending",
					"queued",
					"published",
					"needs_review",
					"rejected",
				])
				.gte(
					"created_at",
					new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
				)
				.limit(50);

			if (recentStats && recentStats.length >= 10) {
				const rejectCount = recentStats.filter(
					(r) => r.status === "rejected",
				).length;
				const rejectRate = rejectCount / recentStats.length;

				if (rejectRate > 0.6) {
					logger.info(
						"Model escalation: high reject rate, upgrading to flash",
						{
							groupId,
							rejectRate: `${Math.round(rejectRate * 100)}%`,
							recentTotal: recentStats.length,
							previousModel: aiConfig.model || "gemini-2.5-flash",
						},
					);
					aiConfig = { ...aiConfig, model: "gemini-2.5-flash" };
				}
			}
		} catch {
			// Non-blocking — failure routing is best-effort
		}
	}

	const aiSlotReservation = Math.max(0, postsPerFill - directInserted);
	if (aiSlotReservation <= 0) {
		return { filled: directInserted > 0, count: directInserted };
	}

	// ── Step 6: Reserve generation slots atomically ──
	const { data: slotsGranted } = await db().rpc("increment_ai_generations", {
		p_workspace_id: workspaceId,
		p_count: aiSlotReservation,
		p_today: today,
		p_reset: dateChanged,
		p_limit: dailyLimit,
	});

	const canGenerate = slotsGranted ?? 0;
	if (canGenerate <= 0) {
		logger.info("AI queue fill: daily limit reached (atomic check)", {
			dailyLimit,
			directInserted,
		});
		return directInserted > 0
			? {
					filled: true,
					count: directInserted,
					reason: "direct_competitor_only_daily_limit",
				}
			: { filled: false, count: 0, reason: "daily_limit_reached" };
	}

	logger.info("AI queue fill: reserved slots, preparing generation", {
		ownerId,
		provider: aiConfig.provider,
		model: aiConfig.model,
		groupId,
		pendingCount,
		slotsReserved: canGenerate,
		directInserted,
	});

	// ── Step 7: Proven templates + Evergreen recycling ──
	const directQueueBypassAllowed = targetPlatform === "instagram";
	const templateInsertCount = directQueueBypassAllowed
		? await insertProvenTemplate(workspaceId, groupId, canGenerate, {
				config,
				accountCount: accountIds.length,
				insights: performanceTimingInsights,
				platform: "instagram",
			})
		: 0;

	let evergreenInsertCount = 0;
	if (groupId && directQueueBypassAllowed) {
		const evResult = await recycleEvergreenPosts(
			workspaceId,
			groupId,
			canGenerate,
			targetPlatform,
			{
				config,
				accountCount: accountIds.length,
				insights: performanceTimingInsights,
			},
		);
		evergreenInsertCount = evResult.insertCount;
	}

	// Remaining slots go to AI generation
	const aiSlots = Math.max(
		0,
		canGenerate - templateInsertCount - evergreenInsertCount,
	);

	// ── Step 7: Gather context for AI generation ──
	const extractedStyle = await getUserExtractedStyle(ownerId);

	// Flop recovery check — read from account_autoposter_state DB table
	let forceProvenTypes = false;
	if (groupId) {
		try {
			const { getGroupAccountStates } = await import("./accountState.js");
			const states = await getGroupAccountStates(groupId);
			forceProvenTypes = states.some((s) => s.flop_proven_remaining > 0);
			if (forceProvenTypes) {
				logger.info(
					"[queueFill] Flop recovery active — forcing proven content types",
					{ groupId, workspaceId },
				);
			}
		} catch {
			// Fail-open
		}
	}

	// Fetch top/bottom performing posts for AI context
	let topPerformers: Array<{ content: string; velocity: number }> = [];
	let worstPerformers: Array<{ content: string; velocity: number }> = [];
	try {
		const contentOverhaulDate = "2026-03-20T00:00:00Z";
		const threeDaysAgo = new Date(Date.now() - 3 * 86_400_000).toISOString();
		const performerCutoff =
			contentOverhaulDate > threeDaysAgo ? contentOverhaulDate : threeDaysAgo;

		let scoredTop: Array<{ content: string; velocity: number }> = [];
		let scoredAll: Array<{ content: string; velocity: number }> = [];

		if (accountIds.length > 0) {
			const { data: postsData } = await (
				db() as ReturnType<typeof getSupabaseAny>
			)
				.from("posts")
				.select(
					"id, content, views_count, likes_count, replies_count, published_at, account_id",
				)
				.in("account_id", accountIds)
				.eq("status", "published")
				.not("content", "is", null)
				.gte("published_at", performerCutoff)
				.order("published_at", { ascending: false })
				.limit(150);

			if (postsData && postsData.length >= 3) {
				const postIds = postsData.map((p) => p.id);
				const { data: historyData } = await (
					db() as ReturnType<typeof getSupabaseAny>
				)
					.from("post_metric_history")
					.select(
						"post_id, views_count, likes_count, replies_count, hours_since_publish",
					)
					.in("post_id", postIds)
					.gte("hours_since_publish", 20)
					.lte("hours_since_publish", 28)
					.order("hours_since_publish", { ascending: false });

				const velocityMap = new Map<
					string,
					{ views: number; likes: number; replies: number }
				>();
				if (historyData) {
					for (const h of historyData) {
						if (!velocityMap.has(h.post_id)) {
							velocityMap.set(h.post_id, {
								views: (h.views_count as number) || 0,
								likes: (h.likes_count as number) || 0,
								replies: (h.replies_count as number) || 0,
							});
						}
					}
				}

				scoredAll = postsData
					.filter((p) => p.content && (p.content as string).trim().length > 0)
					.map((p) => {
						const hist = velocityMap.get(p.id);
						const velocity = hist
							? hist.views + hist.replies * 5
							: (p.views_count as number) || 0;
						return { content: p.content as string, velocity };
					})
					.sort((a, b) => b.velocity - a.velocity);

				scoredTop = scoredAll.filter((p) => p.velocity > 0);
			}
		}

		// Fallback: auto_post_queue
		if (scoredTop.length < 10) {
			const threeDaysAgoFallback = new Date(
				Date.now() - 3 * 86_400_000,
			).toISOString();
			const query = (db() as ReturnType<typeof getSupabaseAny>)
				.from("auto_post_queue")
				.select("content, views_at_24h, engagement_rate, posted_at")
				.eq("workspace_id", workspaceId)
				.eq("status", "published")
				.not("content", "is", null)
				.gte("posted_at", threeDaysAgoFallback);

			if (groupId) {
				query.eq("group_id", groupId);
			}

			const { data: recentPublished } = await query;

			if (recentPublished && recentPublished.length > 0) {
				const queueScored = recentPublished
					.filter(
						(p: Record<string, unknown>) =>
							p.content &&
							typeof p.content === "string" &&
							(p.content as string).trim().length > 0,
					)
					.map((p: Record<string, unknown>) => ({
						content: p.content as string,
						velocity:
							(p.views_at_24h as number) > 0
								? (p.views_at_24h as number)
								: ((p.engagement_rate as number) || 0) * 100,
					}))
					.sort((a, b) => b.velocity - a.velocity);

				const existingPrefixes = new Set(
					scoredAll.map((p) => p.content.substring(0, 50)),
				);
				for (const qs of queueScored) {
					if (!existingPrefixes.has(qs.content.substring(0, 50))) {
						scoredAll.push(qs);
						if (qs.velocity > 0) scoredTop.push(qs);
					}
				}
				scoredTop.sort((a, b) => b.velocity - a.velocity);
				scoredAll.sort((a, b) => b.velocity - a.velocity);
			}
		}

		// Topic-balanced top 10 winners
		if (scoredTop.length >= 3) {
			const topicDetectorsPerf: Record<string, RegExp> = {
				gym: /\b(deadlift|squat|bench|workout|lift|gym|cardio|leg\s*day|PR|gains|protein|pre[- ]?workout|rest\s*day)\b/i,
				gaming:
					/\b(game|gaming|fortnite|valorant|raid|squad|controller|lobby|fps|console)\b/i,
				dating:
					/\b(date|dating|boyfriend|girlfriend|cuddle|kiss|flirt|crush|situationship|talking\s*stage|ex)\b/i,
				latenight:
					/\b(sleep|awake|insomnia|night\s*owl|3\s*am|2\s*am|can't\s*sleep|up\s*late|who'?s\s*up)\b/i,
			};
			const detectTopicPerf = (text: string): string => {
				for (const [topic, regex] of Object.entries(topicDetectorsPerf)) {
					if (regex.test(text)) return topic;
				}
				return "other";
			};

			const topicCounts: Record<string, number> = {};
			const balanced: typeof scoredTop = [];
			for (const post of scoredTop) {
				if (balanced.length >= 10) break;
				const topic = detectTopicPerf(post.content);
				const count = topicCounts[topic] || 0;
				const maxForTopic = topic === "gym" ? 1 : 2;
				if (count < maxForTopic) {
					balanced.push(post);
					topicCounts[topic] = count + 1;
				}
			}
			if (balanced.length < 10) {
				for (const post of scoredTop) {
					if (balanced.length >= 10) break;
					if (!balanced.includes(post)) balanced.push(post);
				}
			}
			topPerformers = balanced;
		}
		if (scoredAll.length >= 5) {
			worstPerformers = scoredAll.slice(-5).reverse();
		}
	} catch (perfErr) {
		logger.warn("Failed to fetch performance context for AI fill", {
			error: perfErr instanceof Error ? perfErr.message : String(perfErr),
		});
	}

	// Media attachment chance + timing config (from resolved config)
	const slotMediaChance = performanceFirstMediaChance(
		targetPlatform,
		resolved.slotMediaChance,
	);
	const groupTimingConfig = groupConfig;

	const aiSlotsAdjusted = aiSlots;
	let planResult: {
		slots: Array<{
			accountId: string;
			roundRobinIndex: number;
			isProbe?: boolean | undefined;
			warmupPolicy?: RestartWarmupPolicy | undefined;
			timezone?: string | undefined;
			activeHoursStart?: number | undefined;
			activeHoursEnd?: number | undefined;
			minIntervalMinutes?: number | undefined;
		}>;
		skipped: Array<{ account_id: string; username: string; reason: string }>;
		totalAccounts: number;
		eligibleCount: number;
	} = { slots: [], skipped: [], totalAccounts: 0, eligibleCount: 0 };
	let generationTargets: GenerationTargetContext[] = [];
	let accountTimingProfiles = new Map<string, AccountTimingProfile>();
	if (groupId && aiSlotsAdjusted > 0) {
		planResult = await planAccountSlots(
			groupId,
			workspaceId,
			ownerId,
			Math.max(1, Math.ceil(aiSlotsAdjusted * 2.5)),
			resolved,
		);
		accountTimingProfiles = await loadLearnedTimingProfilesForSlots({
			workspaceId,
			groupId,
			slots: planResult.slots,
			targetPlatform,
			refresh: true,
		});
		if (schedulerVersion < 3) {
			generationTargets = await loadGenerationTargetContexts({
				workspaceId,
				groupId,
				slots: planResult.slots,
			});
		}
		logger.info("[queueFill] Loaded account-first generation context", {
			workspaceId,
			groupId,
			targetCount: generationTargets.length,
			targetsWithDna: generationTargets.filter((target) => !!target.dna).length,
			targetsWithArc: generationTargets.filter((target) => !!target.contentArc)
				.length,
			targetsWithLearnedTiming: [...accountTimingProfiles.values()].filter(
				(profile) => profile.fallbackSource === "account_learned",
			).length,
		});
	}

	// ── Step 8: AI Generation (remix half) ──
	logger.info("Starting AI generation", {
		aiSlots: aiSlotsAdjusted,
		directInserted,
		groupId,
		provider: aiConfig.provider,
		model: aiConfig.model,
	});

	let ideas: Awaited<ReturnType<typeof generateAIPostIdeas>> = [];
	let strategyRecommendations: Awaited<
		ReturnType<typeof loadActiveStrategyRecommendations>
	> = [];
	let strategyRecommendationSummary = summarizeActiveStrategyRecommendations([]);
	if (aiSlotsAdjusted > 0) {
		strategyRecommendations = await loadActiveStrategyRecommendations({
			workspaceId,
			groupId,
			accountIds,
		});
		strategyRecommendationSummary =
			summarizeActiveStrategyRecommendations(strategyRecommendations);
		logger.info("[queueFill] Loaded active strategy recommendations", {
			fillCycleId,
			workspaceId,
			groupId: groupId ?? null,
			accountScopeCount: accountIds.length,
			...strategyRecommendationSummary,
		});
		const overgenFactor = 2.5;
		ideas = await generateAIPostIdeas(
			ownerId,
			Math.max(1, aiSlotsAdjusted) * overgenFactor,
			voiceProfile,
			aiConfig.apiKey,
			extractedStyle,
			config.ai_style_guidelines,
			workspaceId,
			{
				provider: aiConfig.provider,
				model: aiConfig.model,
				baseUrl: aiConfig.baseUrl,
				targetPlatform,
				contentStrategy,
				topPerformers,
				worstPerformers,
				groupAccountIds: accountIds,
				forceProvenTypes,
				strategyRecommendations,
				generationTargets,
			},
		);
	}

	logger.info("AI generation returned", {
		ideaCount: ideas.length,
		aiSlots: aiSlotsAdjusted,
		groupId,
	});

	if (aiSlotsAdjusted > 0 && ideas.length === 0) {
		logger.warn("AI generation returned 0 ideas", {
			workspaceId,
			groupId,
			provider: aiConfig.provider,
		});

		// Notify once per group per hour (Redis dedup)
		try {
			const deduKey = `ai-fail-notif:${groupId ?? workspaceId}`;
			let shouldNotify = true;
			try {
				const { getRedis } = await import("../../redis.js");
				const redis = getRedis();
				const sent = await redis.set(deduKey, "1", { nx: true, ex: 3600 });
				shouldNotify = !!sent;
			} catch {
				/* Redis down — notify anyway */
			}

			if (shouldNotify) {
				const groupLabel = resolvedGroupName || groupId || "unknown";
				const { data: workspace } = await db()
					.from("workspaces")
					.select("owner_id")
					.eq("id", workspaceId)
					.maybeSingle();
				if (workspace?.owner_id) {
					await db()
						.from("notifications")
						.insert({
							user_id: workspace.owner_id,
							type: "queue_low",
							title: `AI generation failed — ${groupLabel}`,
							message: `Queue fill returned 0 posts for ${groupLabel}. Provider: ${aiConfig.provider}. Will retry next cycle.`,
							read: false,
							data: { workspaceId, groupId },
						});
				}
			}
		} catch {
			/* notification non-critical */
		}

		return { filled: false, count: 0, reason: "ai_returned_empty" };
	}

	const expandedIdeas = ideas;

	const scheduledTimes = calculateNaturalPostTimes(
		expandedIdeas.length,
		config,
		groupId,
		accountIds.length,
		performanceTimingInsights,
		targetPlatform === "instagram" ? "instagram" : "threads",
	);

	const maxInserts = aiSlotsAdjusted;

	// ── Step 10: Pipeline filters ──
	const recentPostContents = await getRecentPostContext(workspaceId);
	const topicKeywords: string[] = [
		...(((contentStrategy as Record<string, unknown> | null)
			?.pillars as string[]) || []),
		...(voiceProfile?.focus_topics || []),
	].filter(Boolean);

	const recentVariationPosts = await loadRecentVariationPosts(workspaceId);

	// Phase 1: Fast filter
	const phase1 = await runFastFilterPhase(
		expandedIdeas,
		scheduledTimes,
		maxInserts,
		contentFilterConfig,
		recentVariationPosts,
		workspaceId,
		groupId,
		fillStartTime,
		voiceProfile?.avoid_words,
	);

	// Phase 1.5: Optional LLM judge (off by default; enabled per group via
	// auto_post_group_config.llm_judge_enabled). When enabled, provider errors
	// fail closed inside runLLMJudgePhase so a degraded judge cannot silently
	// pass candidates.
	const judgeRequested = groupConfig?.llm_judge_enabled === true;
	const phase1Judged = judgeRequested
		? await runLLMJudgePhase(
				phase1.survivors,
				{
					enabled: true,
					apiKey: aiConfig.apiKey,
					provider: aiConfig.provider,
					minScore: groupConfig?.llm_judge_min_score ?? 3.0,
					model: aiConfig.model,
					voiceProfileHint: voiceProfile?.voice_profile,
					costAttribution: {
						userId: ownerId,
						source: aiConfig.source ?? "user",
					},
					accountIds: resolved.groupAccountIds,
				},
				workspaceId,
				groupId,
			)
		: { survivors: phase1.survivors, rejectedCount: 0, rejectionReasons: {} };

	// Phase 2: Embedding dedup + Phase 3: Insert
	// Wrapped in try/finally to ensure embedding cache is cleared even on crash
	// (module-scoped Map in serverless leaks across warm invocations otherwise)
	let phase2: Awaited<ReturnType<typeof runEmbeddingDedupPhase>>;
	let insertResult: InsertionResult = {
		insertedCount: 0,
		failedCount: 0,
		rejectedCount: 0,
		rejectionReasons: {},
		insertedContents: [],
		errors: [],
	};
	let totalRejected = 0;
	let allRejectionReasons: Record<string, number> = {};
	try {
		phase2 = await runEmbeddingDedupPhase(
			phase1Judged.survivors,
			maxInserts,
			recentPostContents,
			aiConfig.apiKey,
			workspaceId,
			groupId,
			fillStartTime,
		);

		const plannedSlotsForInsert: PlannedAccountSlot[] = [];
		if (groupId) {
			phase2.candidates.forEach((candidate, index) => {
				const idea =
					candidate.idea ??
					(candidate as unknown as {
						targetAccountId?: string;
						targetRoundRobinIndex?: number;
						targetIsProbe?: boolean;
					});
				const targetAccountId = idea.targetAccountId;
				const originalSlot =
					(targetAccountId
						? planResult.slots.find(
								(slot) => slot.accountId === targetAccountId,
							)
						: null) ?? planResult.slots[index];
				if (!targetAccountId && !originalSlot) return;
				const slot: PlannedAccountSlot = {
					accountId: targetAccountId ?? originalSlot!.accountId,
					roundRobinIndex:
						idea.targetRoundRobinIndex ?? originalSlot?.roundRobinIndex ?? index,
				};
				const isProbe = idea.targetIsProbe ?? originalSlot?.isProbe;
				if (isProbe !== undefined) slot.isProbe = isProbe;
				if (originalSlot?.warmupPolicy) {
					slot.warmupPolicy = originalSlot.warmupPolicy;
				}
				if (originalSlot?.timezone) slot.timezone = originalSlot.timezone;
				if (originalSlot?.activeHoursStart !== undefined) {
					slot.activeHoursStart = originalSlot.activeHoursStart;
				}
				if (originalSlot?.activeHoursEnd !== undefined) {
					slot.activeHoursEnd = originalSlot.activeHoursEnd;
				}
				if (originalSlot?.minIntervalMinutes !== undefined) {
					slot.minIntervalMinutes = originalSlot.minIntervalMinutes;
				}
				plannedSlotsForInsert.push(slot);
			});
		}

		if (
			targetPlatform === "threads" &&
			plannedSlotsForInsert.length > 0 &&
			phase2.candidates.length > 0
		) {
			const accountAwareTimes = calculateAccountAwareNaturalPostTimes({
				plannedSlots: plannedSlotsForInsert.slice(0, phase2.candidates.length),
				config,
				groupId,
				groupAccountCount: accountIds.length,
				insights: performanceTimingInsights,
				platform: "threads",
				accountProfiles: accountTimingProfiles,
			});
			phase2.candidates = phase2.candidates.map((candidate, index) => {
				const selection = accountAwareTimes[index];
				if (!selection) return candidate;
				return {
					...candidate,
					scheduledFor: selection.scheduledFor,
					timing: selection.timing,
				};
			});
			logger.info("[queueFill] Applied account-aware learned timing", {
				workspaceId,
				groupId,
				candidates: phase2.candidates.length,
				accountLearned: accountAwareTimes.filter(
					(selection) =>
						selection.timing.timingReason === "account_proven_hour" ||
						selection.timing.timingReason === "account_exploration_hour",
				).length,
				warmupPrimary: accountAwareTimes.filter(
					(selection) => selection.timing.timingReason === "warmup_primary_hour",
				).length,
			});
		}

		insertResult = await insertCandidatesIntoQueue(
			phase2.candidates,
			plannedSlotsForInsert,
			{
				workspaceId,
				groupId,
				ownerId,
				targetPlatform,
				config,
				voiceProfile,
				aiConfig,
				slotMediaChance,
				resolvedGroupName,
				maxInserts,
				fillStartTime,
				fillCycleId,
				timezone: groupTimingConfig?.timezone,
				mediaGroupId: groupTimingConfig?.media_group_id,
				schedulerVersion,
				strategyRecommendations,
			},
		);

		// ── Step 12: Summary + cleanup ──
		totalRejected =
			phase1.rejectedCount +
			phase1Judged.rejectedCount +
			phase2.rejectedCount +
			insertResult.rejectedCount;
		allRejectionReasons = {
			...phase1.rejectionReasons,
			...phase1Judged.rejectionReasons,
			...phase2.rejectionReasons,
			...insertResult.rejectionReasons,
		};

		if (totalRejected > 0) {
			logger.warn("AI queue fill rejection summary", {
				fillCycleId,
				workspaceId,
				groupId,
				totalGenerated: expandedIdeas.length,
				inserted: insertResult.insertedCount,
				failed: insertResult.failedCount,
				rejected: totalRejected,
				rejectionRate: `${Math.round((totalRejected / expandedIdeas.length) * 100)}%`,
				rejectionReasons: allRejectionReasons,
				topicKeywordsUsed:
					topicKeywords.length > 0 ? topicKeywords.slice(0, 10) : "none",
			});
		}

		// Log DB write failures if any occurred
		if (insertResult.failedCount > 0) {
			logger.error("AI queue fill had DB write failures", {
				workspaceId,
				groupId,
				inserted: insertResult.insertedCount,
				failed: insertResult.failedCount,
				errors: insertResult.errors.slice(0, 5),
			});
		}
	} finally {
		clearEmbeddingCache();
	}

	// Release unused reserved slots. Direct competitor copies do not reserve AI
	// quota, while proven templates and evergreen recycling consume reserved slots.
	const usedReservedSlots =
		insertResult.insertedCount + templateInsertCount + evergreenInsertCount;
	const unused = Math.max(0, canGenerate - usedReservedSlots);
	if (unused > 0) {
		await db().rpc("increment_ai_generations", {
			p_workspace_id: workspaceId,
			p_count: -unused,
			p_today: today,
			p_reset: false,
		});
	}

	const totalInserted = directInserted + usedReservedSlots;
	if (totalInserted > 0) {
		logger.info("Added posts to queue", {
			directCopied: directInserted,
			aiGenerated: insertResult.insertedCount,
			templates: templateInsertCount,
			evergreenRecycled: evergreenInsertCount,
			slotsReserved: canGenerate,
			slotsReleased: unused,
		});
	}

	// ── Step 13: Queue fill explain log ──
	const fillDuration = Date.now() - fillStartTime;
	try {
		// Build account summary
		const skippedByReason: Record<string, number> = {};
		for (const s of planResult.skipped) {
			skippedByReason[s.reason] = (skippedByReason[s.reason] ?? 0) + 1;
		}

		await db()
			.from("queue_fill_log")
			.insert({
				workspace_id: workspaceId,
				group_id: groupId ?? null,
				started_at: new Date(fillStartTime).toISOString(),
				posts_inserted: totalInserted,
				posts_generated: expandedIdeas.length,
				posts_rejected: totalRejected,
				rejection_summary: allRejectionReasons,
				account_summary: {
					eligible: planResult.eligibleCount,
					total: planResult.totalAccounts,
					skipped: skippedByReason,
				},
				strategy_summary: strategyRecommendationSummary,
				skip_details: planResult.skipped.slice(0, 100),
				duration_ms: fillDuration,
			} as Record<string, unknown>);
	} catch (logErr) {
		logger.warn("Failed to write queue_fill_log", {
			error: logErr instanceof Error ? logErr.message : String(logErr),
		});
	}

	return {
		filled: totalInserted > 0,
		count: totalInserted,
		...(totalInserted > 0 && pendingCount + totalInserted < effectiveThreshold
			? { reason: "underfilled_queue_still_low" }
			: {}),
		...(aiSlotsAdjusted > 0
			? { strategyRecommendations: strategyRecommendationSummary }
			: {}),
	};
}
