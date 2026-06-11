// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Schedule & Insert — queue insertion, media selection, QStash dispatch
 *
 * Extracted from queueFill.ts. Handles:
 * - Phase 2.5: Account slot pre-assignment via accountPlanner
 * - Phase 3: Media selection, reply bait suffix, humanization, topic tagging
 * - DB insertion with explicit source provenance preservation
 * - QStash dispatch for scheduled publishing
 */

import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import { classifyCompetitorPattern } from "../competitors/metricQuality.js";
import {
	classifyContentArchetype,
	detectIdentityShapeId,
} from "./contentArchetypes.js";
import { detectTaxonomyLabelLeak } from "./contentFilter.js";
import {
	classifyProfileCuriosityFrame,
	classifyWinnerCloneFamily,
	classifyWinnerCloneFamilyFromContent,
	isProfileCuriosityDeadEndContent,
	winnerCloneFrameAlignmentScore,
} from "./performanceFirst.js";
import {
	evaluateAccountDna,
	loadAccountDnaContext,
	loadCreatorIdentityContext,
	type AccountDnaEvaluation,
	type RecentSiblingRepetition,
} from "./accountDna.js";
import {
	buildContentArcMetadata,
	loadActiveContentArcContext,
} from "./contentArcs.js";
import { humanizePost } from "./evergreenManager.js";
import type { FilterSurvivor } from "./pipelineFilters.js";
import { evaluateQueueProvenance } from "./provenanceGate.js";
import {
	buildPublishFingerprint,
	findRecentDuplicateFingerprint,
} from "./publishFingerprint.js";
import {
	applyPerformanceBackedQualityGateLane,
	type AIQualityGateResult,
} from "./qualityGate.js";
import {
	CLAIMABLE_QUEUE_STATUSES,
	ensureQueueItemScheduleNonce,
	isClaimableQueueStatus,
	rescheduleQueueItemForFutureDispatch,
} from "./queueState.js";
import { DIRECT_COMPETITOR_SHARE } from "./sourcePolicy.js";
import {
	matchStrategyRecommendation,
	type StrategyRecommendation,
} from "./strategyRecommendations.js";
import type { RestartWarmupPolicy } from "./restartWarmup.js";
import type { AutoPostConfig, VoiceProfile } from "./types.js";
import { getRemainingPostingCapacity } from "./warmupCapacity.js";

const db = () => getSupabaseAny();
const APPROVAL_SETTINGS_KEY = "autopilot_preferences";
const DEFAULT_APPROVAL_THRESHOLD = 0;
const RESTART_WARMUP_PRIMARY_HOURS = [6, 7, 11, 12, 13];

export function canPerformanceBackedCloneBypassDnaReview(input: {
	dnaEvaluation: Pick<AccountDnaEvaluation, "decision" | "reasons">;
	qualityGate?: Pick<AIQualityGateResult, "decision" | "lane"> | null;
	winnerCloneFrameMismatch?: boolean;
	winnerCloneSourceTaxonomyLeak?: boolean;
	hasDuplicateMatch?: boolean;
	hasMissingProvenance?: boolean;
}): boolean {
	if (input.qualityGate?.decision !== "pass") return false;
	if (input.qualityGate?.lane !== "performance_backed_clone") return false;
	if (input.winnerCloneFrameMismatch || input.winnerCloneSourceTaxonomyLeak) {
		return false;
	}
	if (input.hasDuplicateMatch || input.hasMissingProvenance) return false;
	if (input.dnaEvaluation.decision !== "regenerate") return false;
	const reasons = input.dnaEvaluation.reasons ?? [];
	return (
		reasons.length > 0 &&
		reasons.every((reason) => reason === "recent_phrase_repetition")
	);
}

function metricBasisFor(
	recommendation: StrategyRecommendation | null | undefined,
): Record<string, unknown> {
	const basis = recommendation?.metric_basis;
	return basis && typeof basis === "object" && !Array.isArray(basis)
		? (basis as Record<string, unknown>)
		: {};
}

function stringBasisValue(
	basis: Record<string, unknown>,
	key: string,
): string | null {
	const value = basis[key];
	return typeof value === "string" && value.trim() ? value.trim() : null;
}

function winnerCloneSourceIds(
	recommendation: StrategyRecommendation,
): Set<string> {
	const basis = metricBasisFor(recommendation);
	return new Set(
		[
			recommendation.pattern_value,
			stringBasisValue(basis, "winnerPatternId"),
			stringBasisValue(basis, "sourcePatternId"),
			stringBasisValue(basis, "sourcePostId"),
		].filter((value): value is string => Boolean(value)),
	);
}

function findWinnerCloneRecommendation(input: {
	recommendations: StrategyRecommendation[];
	sourcePatternId?: string | null | undefined;
	content: string;
	topicLabel?: string | null | undefined;
	contentArchetype?: string | null | undefined;
	questionSubtype?: string | null | undefined;
}): StrategyRecommendation | null {
	const winnerRecs = input.recommendations
		.filter((rec) => rec.pattern_type === "winner_clone")
		.sort((a, b) => b.confidence - a.confidence);
	if (winnerRecs.length === 0) return null;

	if (input.sourcePatternId) {
		const exact = winnerRecs.find((rec) =>
			winnerCloneSourceIds(rec).has(input.sourcePatternId!),
		);
		if (exact) return exact;
	}

	const generatedCloneFamily = classifyWinnerCloneFamily({
		content: input.content,
		topic_label: input.topicLabel || "unknown",
		content_archetype: input.contentArchetype ?? "unknown",
		shape_id: detectIdentityShapeId(input.content),
		question_subtype: input.questionSubtype ?? null,
	});

	return (
		winnerRecs.find((rec) => {
			const basis = metricBasisFor(rec);
			const sourceText = stringBasisValue(basis, "sourceText");
			const cloneFamily = sourceText
				? classifyWinnerCloneFamilyFromContent({
						content: sourceText,
						contentArchetype: stringBasisValue(basis, "contentArchetype"),
						questionSubtype: stringBasisValue(basis, "questionSubtype"),
						shapeId: stringBasisValue(basis, "shapeId"),
					})
				: stringBasisValue(basis, "cloneFamily");
			return cloneFamily === generatedCloneFamily && rec.confidence >= 0.55;
		}) ?? null
	);
}

// ============================================================================
// Types
// ============================================================================

export interface InsertionResult {
	insertedCount: number;
	failedCount: number;
	rejectedCount: number;
	rejectionReasons: Record<string, number>;
	insertedContents: string[];
	errors: Array<{ content: string; error: string }>;
}

export interface InsertionContext {
	workspaceId: string;
	groupId: string | undefined;
	ownerId: string;
	targetPlatform: "threads" | "instagram";
	config: AutoPostConfig;
	voiceProfile?: VoiceProfile | null | undefined;
	aiConfig: {
		provider?: string | undefined;
		apiKey?: string | undefined;
		model?: string | undefined;
	} | null;
	slotMediaChance: number;
	resolvedGroupName: string;
	maxInserts: number;
	fillStartTime: number;
	timezone?: string | undefined;
	/** Override: pull media from this group's library instead of the current group */
	mediaGroupId?: string | null | undefined;
	/** Trace ID for correlating logs across the fill cycle */
	fillCycleId?: string | undefined;
	/** Scheduler version — when >= 3, items insert without account_id (pool mode) */
	schedulerVersion?: number | undefined;
	strategyRecommendations?: StrategyRecommendation[] | undefined;
}

async function loadApprovalThresholdPercent(userId: string): Promise<number> {
	try {
		const { data } = await db()
			.from("user_settings")
			.select("setting_value")
			.eq("user_id", userId)
			.eq("setting_key", APPROVAL_SETTINGS_KEY)
			.maybeSingle();
		const value = (data as { setting_value?: unknown } | null)?.setting_value;
		if (!value || typeof value !== "object" || Array.isArray(value)) {
			return DEFAULT_APPROVAL_THRESHOLD;
		}
		const raw = (value as { threshold?: unknown }).threshold;
		const threshold = typeof raw === "number" ? raw : Number(raw);
		if (!Number.isFinite(threshold)) return DEFAULT_APPROVAL_THRESHOLD;
		return Math.min(99, Math.max(50, Math.round(threshold)));
	} catch (err) {
		logger.warn("[scheduleAndInsert] Failed to load approval threshold", {
			userId,
			error: err instanceof Error ? err.message : String(err),
		});
		return DEFAULT_APPROVAL_THRESHOLD;
	}
}

async function loadRecentSiblingRepetitionContext(input: {
	groupId?: string | undefined;
	accountId?: string | null | undefined;
}): Promise<RecentSiblingRepetition[]> {
	if (!input.groupId || !input.accountId) return [];
	try {
		const since = new Date(Date.now() - 36 * 60 * 60 * 1000).toISOString();
		const [queueResult, postsResult] = await Promise.all([
			db()
				.from("auto_post_queue")
				.select("account_id, content, metadata, created_at")
				.eq("group_id", input.groupId)
				.neq("account_id", input.accountId)
				.gte("created_at", since)
				.order("created_at", { ascending: false })
				.limit(80),
			db()
				.from("posts")
				.select("account_id, content, metadata, published_at")
				.eq("cross_post_group_id", input.groupId)
				.neq("account_id", input.accountId)
				.gte("published_at", since)
				.order("published_at", { ascending: false })
				.limit(80),
		]);
		const rows: RecentSiblingRepetition[] = [];
		for (const row of (queueResult.data ?? []) as Array<
			Record<string, unknown>
		>) {
			const metadata = row.metadata as
				| Record<string, unknown>
				| null
				| undefined;
			const content = String(row.content ?? "");
			rows.push({
				account_id: (row.account_id as string | null | undefined) ?? null,
				content,
				shape_id:
					(metadata?.identity_shape_id as string | null | undefined) ??
					detectIdentityShapeId(content),
				created_at: (row.created_at as string | null | undefined) ?? null,
			});
		}
		for (const row of (postsResult.data ?? []) as Array<
			Record<string, unknown>
		>) {
			const metadata = row.metadata as
				| Record<string, unknown>
				| null
				| undefined;
			const content = String(row.content ?? "");
			rows.push({
				account_id: (row.account_id as string | null | undefined) ?? null,
				content,
				shape_id:
					(metadata?.identity_shape_id as string | null | undefined) ??
					detectIdentityShapeId(content),
				created_at: (row.published_at as string | null | undefined) ?? null,
			});
		}
		return rows.filter((row) => row.content.trim().length > 0);
	} catch (err) {
		logger.warn(
			"[scheduleAndInsert] Failed to load sibling repetition context",
			{
				groupId: input.groupId,
				accountId: input.accountId,
				error: err instanceof Error ? err.message : String(err),
			},
		);
		return [];
	}
}

// ============================================================================
// Format-Specific IG Timing (Research: Reels peak 19-22, images peak 8-11)
// ============================================================================

/**
 * Nudge a scheduled time into the preferred window for the media format.
 * Reels → evenings (19:00-22:00 local), Images → mornings (08:00-11:00 local).
 * Stories → multi-wave (nearest of 11:00, 17:00, 20:00 local).
 * Max shift: ±6 hours. If already in window, no change.
 */
export function nudgeScheduleForFormat(
	scheduledFor: string,
	isVideo: boolean,
	timezone?: string,
	mediaType?: string,
): string {
	if (!timezone) return scheduledFor; // No timezone → skip (zero behavior change)

	// Stories: nudge to nearest wave (11 AM, 5 PM, 8 PM) per Timing Intelligence research
	if (mediaType === "STORIES") {
		try {
			const date = new Date(scheduledFor);
			const localHourStr = date.toLocaleString("en-US", {
				hour: "numeric",
				hour12: false,
				timeZone: timezone,
			});
			const localHour = parseInt(localHourStr, 10);
			if (Number.isNaN(localHour)) return scheduledFor;

			const waves = [11, 17, 20];
			let bestWave = waves[0];
			let bestDist = 24;
			for (const w of waves) {
				const dist = Math.min(
					Math.abs(localHour - w),
					24 - Math.abs(localHour - w),
				);
				if (dist < bestDist) {
					bestDist = dist;
					bestWave = w;
				}
			}
			if (bestDist === 0) return scheduledFor; // already at a wave
			const shiftHours = (bestWave! - localHour + 24) % 24;
			const cappedShift = shiftHours > 12 ? shiftHours - 24 : shiftHours;
			if (Math.abs(cappedShift) > 6) return scheduledFor; // too far, skip
			const jitterMs = Math.floor(Math.random() * 30 * 60 * 1000);
			return new Date(
				date.getTime() + cappedShift * 3600000 + jitterMs,
			).toISOString();
		} catch {
			return scheduledFor;
		}
	}

	const preferredStart = isVideo ? 19 : 8; // Reels: 7 PM, Images: 8 AM
	const preferredEnd = isVideo ? 22 : 11; // Reels: 10 PM, Images: 11 AM

	try {
		const date = new Date(scheduledFor);

		// Get the local hour in the target timezone
		const localHourStr = date.toLocaleString("en-US", {
			hour: "numeric",
			hour12: false,
			timeZone: timezone,
		});
		const localHour = parseInt(localHourStr, 10);
		if (Number.isNaN(localHour) || localHour < 0 || localHour > 23)
			return scheduledFor;

		// Already in the preferred window — no change
		if (localHour >= preferredStart && localHour < preferredEnd) {
			return scheduledFor;
		}

		// Calculate shift to nearest edge of preferred window
		const distToStart = (preferredStart - localHour + 24) % 24;
		const distToEnd = (localHour - preferredEnd + 24) % 24;
		let shiftHours = distToStart <= distToEnd ? distToStart : -distToEnd;

		// Cap at ±6 hours
		if (shiftHours > 6) shiftHours = 6;
		if (shiftHours < -6) shiftHours = -6;

		// Apply shift + random 0-45 min jitter within the window
		const shiftMs = shiftHours * 60 * 60 * 1000;
		const jitterMs = Math.floor(Math.random() * 45 * 60 * 1000);
		const nudged = new Date(date.getTime() + shiftMs + jitterMs);

		return nudged.toISOString();
	} catch {
		return scheduledFor; // Fail-open
	}
}

export function nudgeScheduleToRestartWarmupPrimaryHour(
	scheduledFor: string,
	timezone?: string,
	seed?: string,
): string {
	if (!timezone) return scheduledFor;
	const date = new Date(scheduledFor);
	if (Number.isNaN(date.getTime())) return scheduledFor;
	try {
		const localHour = Number(
			date.toLocaleString("en-US", {
				hour: "numeric",
				hour12: false,
				timeZone: timezone,
			}),
		);
		if (!Number.isFinite(localHour)) return scheduledFor;
		if (RESTART_WARMUP_PRIMARY_HOURS.includes(localHour)) return scheduledFor;
		const seedValue = `${seed ?? ""}:${scheduledFor}`;
		const hash = Math.abs(
			seedValue
				.split("")
				.reduce((sum, char) => ((sum << 5) - sum + char.charCodeAt(0)) | 0, 0),
		);
		const targetHour =
			RESTART_WARMUP_PRIMARY_HOURS[
				hash % RESTART_WARMUP_PRIMARY_HOURS.length
			] ?? 11;
		const forwardShift = (targetHour - localHour + 24) % 24;
		const shiftHours = forwardShift > 12 ? forwardShift - 24 : forwardShift;
		if (Math.abs(shiftHours) > 8) return scheduledFor;
		const jitterMinutes = hash % 48;
		return new Date(
			date.getTime() + shiftHours * 3600000 + jitterMinutes * 60_000,
		).toISOString();
	} catch {
		return scheduledFor;
	}
}

function localHourForSchedule(scheduledFor: string, timezone?: string): number {
	const date = new Date(scheduledFor);
	if (Number.isNaN(date.getTime())) return date.getUTCHours();
	if (!timezone) return date.getUTCHours();
	try {
		const localHour = Number(
			date.toLocaleString("en-US", {
				hour: "numeric",
				hour12: false,
				timeZone: timezone,
			}),
		);
		return Number.isFinite(localHour) && localHour >= 0 && localHour <= 23
			? localHour
			: date.getUTCHours();
	} catch {
		return date.getUTCHours();
	}
}

function localMinuteForSchedule(
	scheduledFor: string,
	timezone?: string,
): number {
	const date = new Date(scheduledFor);
	if (Number.isNaN(date.getTime())) return date.getUTCMinutes();
	if (!timezone) return date.getUTCMinutes();
	try {
		const localMinute = Number(
			date.toLocaleString("en-US", {
				minute: "numeric",
				timeZone: timezone,
			}),
		);
		return Number.isFinite(localMinute) && localMinute >= 0 && localMinute <= 59
			? localMinute
			: date.getUTCMinutes();
	} catch {
		return date.getUTCMinutes();
	}
}

function utcMinuteBounds(date: Date): { start: string; end: string } {
	const start = new Date(date);
	start.setUTCSeconds(0, 0);
	const end = new Date(start.getTime() + 60_000);
	return { start: start.toISOString(), end: end.toISOString() };
}

function deterministicShiftSeconds(seed: string, attempt: number): number {
	let hash = attempt * 2654435761;
	for (let i = 0; i < seed.length; i++) {
		hash = ((hash << 5) - hash + seed.charCodeAt(i)) | 0;
	}
	return 60 + (Math.abs(hash) % 121);
}

async function avoidReadySameMinuteCollision(input: {
	workspaceId: string;
	platform: "threads" | "instagram";
	queueStatus: string;
	scheduledFor: string;
	seed: string;
}): Promise<{
	scheduledFor: string;
	applied: boolean;
	shiftSeconds: number;
	attempts: number;
}> {
	if (input.platform !== "threads" || !isClaimableQueueStatus(input.queueStatus)) {
		return {
			scheduledFor: input.scheduledFor,
			applied: false,
			shiftSeconds: 0,
			attempts: 0,
		};
	}
	let candidate = new Date(input.scheduledFor);
	if (Number.isNaN(candidate.getTime())) {
		return {
			scheduledFor: input.scheduledFor,
			applied: false,
			shiftSeconds: 0,
			attempts: 0,
		};
	}
	let totalShiftSeconds = 0;
	for (let attempt = 0; attempt < 4; attempt++) {
		const bounds = utcMinuteBounds(candidate);
		try {
			const { data, error } = await db()
				.from("auto_post_queue")
				.select("id")
				.eq("workspace_id", input.workspaceId)
				.eq("platform", "threads")
				.in("status", [...CLAIMABLE_QUEUE_STATUSES])
				.gte("scheduled_for", bounds.start)
				.lt("scheduled_for", bounds.end);
			if (!error && (!data || data.length === 0)) {
				return {
					scheduledFor: candidate.toISOString(),
					applied: totalShiftSeconds > 0,
					shiftSeconds: totalShiftSeconds,
					attempts: attempt + 1,
				};
			}
		} catch {
			return {
				scheduledFor: candidate.toISOString(),
				applied: totalShiftSeconds > 0,
				shiftSeconds: totalShiftSeconds,
				attempts: attempt,
			};
		}
		const shiftSeconds = deterministicShiftSeconds(input.seed, attempt);
		totalShiftSeconds += shiftSeconds;
		candidate = new Date(candidate.getTime() + shiftSeconds * 1000);
	}
	return {
		scheduledFor: candidate.toISOString(),
		applied: totalShiftSeconds > 0,
		shiftSeconds: totalShiftSeconds,
		attempts: 4,
	};
}

function queueRowPlannedAccountId(row: Record<string, unknown>): string | null {
	if (typeof row.account_id === "string" && row.account_id) return row.account_id;
	const metadata = row.metadata as Record<string, unknown> | null | undefined;
	const planned = metadata?.planned_account as
		| Record<string, unknown>
		| null
		| undefined;
	const accountId = planned?.accountId;
	return typeof accountId === "string" && accountId ? accountId : null;
}

async function avoidReadyAccountMinIntervalCollision(input: {
	workspaceId: string;
	platform: "threads" | "instagram";
	queueStatus: string;
	scheduledFor: string;
	accountId?: string | null | undefined;
	minIntervalMinutes?: number | null | undefined;
	seed: string;
}): Promise<{
	scheduledFor: string;
	applied: boolean;
	shiftSeconds: number;
	attempts: number;
	conflictCount: number;
}> {
	const minIntervalMinutes = Math.max(0, input.minIntervalMinutes ?? 0);
	if (
		input.platform !== "threads" ||
		!isClaimableQueueStatus(input.queueStatus) ||
		!input.accountId ||
		minIntervalMinutes <= 0
	) {
		return {
			scheduledFor: input.scheduledFor,
			applied: false,
			shiftSeconds: 0,
			attempts: 0,
			conflictCount: 0,
		};
	}

	let candidate = new Date(input.scheduledFor);
	if (Number.isNaN(candidate.getTime())) {
		return {
			scheduledFor: input.scheduledFor,
			applied: false,
			shiftSeconds: 0,
			attempts: 0,
			conflictCount: 0,
		};
	}

	const minIntervalMs = minIntervalMinutes * 60_000;
	let totalShiftSeconds = 0;
	let maxConflictCount = 0;
	for (let attempt = 0; attempt < 4; attempt++) {
		const windowStart = new Date(candidate.getTime() - minIntervalMs);
		const windowEnd = new Date(candidate.getTime() + minIntervalMs);
		try {
			const { data, error } = await db()
				.from("auto_post_queue")
				.select("id, account_id, scheduled_for, metadata")
				.eq("workspace_id", input.workspaceId)
				.eq("platform", "threads")
				.in("status", [...CLAIMABLE_QUEUE_STATUSES])
				.gte("scheduled_for", windowStart.toISOString())
				.lte("scheduled_for", windowEnd.toISOString());
			if (error) {
				return {
					scheduledFor: candidate.toISOString(),
					applied: totalShiftSeconds > 0,
					shiftSeconds: totalShiftSeconds,
					attempts: attempt,
					conflictCount: maxConflictCount,
				};
			}
			const conflicts = ((data ?? []) as Array<Record<string, unknown>>)
				.filter((row) => queueRowPlannedAccountId(row) === input.accountId)
				.map((row) => new Date(String(row.scheduled_for ?? "")))
				.filter((date) => !Number.isNaN(date.getTime()))
				.filter(
					(date) =>
						Math.abs(date.getTime() - candidate.getTime()) < minIntervalMs,
				);
			maxConflictCount = Math.max(maxConflictCount, conflicts.length);
			if (conflicts.length === 0) {
				return {
					scheduledFor: candidate.toISOString(),
					applied: totalShiftSeconds > 0,
					shiftSeconds: totalShiftSeconds,
					attempts: attempt + 1,
					conflictCount: maxConflictCount,
				};
			}
			const latestConflictMs = Math.max(
				...conflicts.map((date) => date.getTime()),
			);
			const shifted = new Date(
				latestConflictMs +
					minIntervalMs +
					deterministicShiftSeconds(input.seed, attempt) * 1000,
			);
			totalShiftSeconds += Math.max(
				0,
				Math.round((shifted.getTime() - candidate.getTime()) / 1000),
			);
			candidate = shifted;
		} catch {
			return {
				scheduledFor: candidate.toISOString(),
				applied: totalShiftSeconds > 0,
				shiftSeconds: totalShiftSeconds,
				attempts: attempt,
				conflictCount: maxConflictCount,
			};
		}
	}

	return {
		scheduledFor: candidate.toISOString(),
		applied: totalShiftSeconds > 0,
		shiftSeconds: totalShiftSeconds,
		attempts: 4,
		conflictCount: maxConflictCount,
	};
}

// ============================================================================
// Account Slot Pre-Assignment (Phase 2.5)
// ============================================================================

export interface PlanAccountSlotsResult {
	slots: Array<{
		accountId: string;
		roundRobinIndex: number;
		isProbe?: boolean | undefined;
		warmupPolicy?: RestartWarmupPolicy | undefined;
	}>;
	skipped: Array<{ account_id: string; username: string; reason: string }>;
	totalAccounts: number;
	eligibleCount: number;
}

export async function planAccountSlots(
	groupId: string,
	workspaceId: string,
	ownerId: string,
	candidateCount: number,
	resolvedConfig?: import("./configResolver.js").ResolvedConfig,
): Promise<PlanAccountSlotsResult> {
	try {
		const { planAccountSlots: planSlots } = await import("./accountPlanner.js");
		return await planSlots(
			groupId,
			workspaceId,
			ownerId,
			candidateCount,
			resolvedConfig,
		);
	} catch (planErr) {
		// Fail-open: if planner fails, items insert without account_id
		// and auto-post-publish.ts falls back to publish-time selection
		logger.warn(
			"Account planner failed, falling back to publish-time selection",
			{
				error: planErr instanceof Error ? planErr.message : String(planErr),
				groupId,
			},
		);
		return { slots: [], skipped: [], totalAccounts: 0, eligibleCount: 0 };
	}
}

// ============================================================================
// Phase 3: Media Selection + Insert + QStash Dispatch
// ============================================================================

/**
 * Insert deduped candidates into the queue with media, humanization, and scheduling.
 */
export async function insertCandidatesIntoQueue(
	dedupedCandidates: FilterSurvivor[],
	plannedSlots: Array<{
		accountId: string;
		roundRobinIndex: number;
		isProbe?: boolean | undefined;
		warmupPolicy?: RestartWarmupPolicy | undefined;
		timezone?: string | undefined;
		activeHoursStart?: number | undefined;
		activeHoursEnd?: number | undefined;
		minIntervalMinutes?: number | undefined;
	}>,
	ctx: InsertionContext,
): Promise<InsertionResult> {
	let insertedCount = 0;
	let failedCount = 0;
	let rejectedCount = 0;
	const rejectionReasons: Record<string, number> = {};
	const insertedContents: string[] = [];
	const errors: Array<{ content: string; error: string }> = [];
	const batchUsedMediaUrls = new Set<string>();
	let slotIndex = 0;

	// Competitor-sourced posts follow the canonical queue policy, not the
	// deprecated workspace knob.
	const competitorCopyRatio = DIRECT_COMPETITOR_SHARE;
	let batchCompetitorCount = 0;
	const maxCompetitorInBatch =
		competitorCopyRatio <= 0
			? 0
			: Math.max(1, Math.floor(ctx.maxInserts * competitorCopyRatio));
	const approvalThreshold = await loadApprovalThresholdPercent(ctx.ownerId);

	// 30-day competitor cap — REMOVED: competitor content is the strategy,
	// not a supplement. The per-competitor cap and intra-batch dedup in
	// queueFill.ts handle diversity. No reason to starve the queue.

	for (const candidate of dedupedCandidates) {
		if (insertedCount >= ctx.maxInserts) break;

		// No more planned slots — stop inserting.
		// Threads pool mode still needs planned-account constraints so warm-up,
		// capacity, and account-window rules can be enforced before publish.
		const isPoolMode = (ctx.schedulerVersion ?? 1) >= 3;
		if (
			ctx.groupId &&
			slotIndex >= plannedSlots.length &&
			(!isPoolMode || ctx.targetPlatform === "threads")
		) {
			logger.info(
				"[scheduleAndInsert] Planned account slots exhausted, stopping insertion",
				{
					groupId: ctx.groupId,
					inserted: insertedCount,
					remainingCandidates: dedupedCandidates.length - insertedCount,
					slotsUsed: slotIndex,
				},
			);
			break;
		}

		// Budget guard
		if (Date.now() - ctx.fillStartTime > 100_000) {
			logger.warn("Fill budget exceeded 100s during insertion phase", {
				insertedCount,
				elapsed: Date.now() - ctx.fillStartTime,
			});
			break;
		}

		const { idea, scheduledFor, timing } = candidate;

		// Advance slot pointer for every candidate considered (not just inserted)
		// so planned account slots stay aligned with candidate iteration order.
		slotIndex++;

		// Probe post override — suppressed accounts get their best historical text content, no media
		const currentSlot = slotIndex - 1; // slotIndex already advanced at top of loop
		const plannedSlot =
			currentSlot < plannedSlots.length ? plannedSlots[currentSlot] : null;
		if (plannedSlot?.isProbe) {
			try {
				const { data: topPost } = await db()
					.from("posts")
					.select("content, views_count")
					.eq("account_id", plannedSlot.accountId)
					.eq("status", "published")
					.not("content", "is", null)
					.gt("views_count", 0)
					.order("views_count", { ascending: false })
					.limit(1);

				if (topPost?.[0]?.content) {
					idea.content = topPost[0].content;
					logger.info(
						"[scheduleAndInsert] Probe post using top historical content",
						{
							accountId: plannedSlot.accountId,
							originalViews: topPost[0].views_count,
							contentPreview: idea.content.substring(0, 40),
						},
					);
				}
			} catch {
				// Fail-open — use the AI content as-is
			}
		}

		// Random media attachment — avoids recently used URLs within this batch
		// Probe posts are always text-only to test if the account can get distribution
		let mediaUrls: string[] | null = null;
		let isVideo = false;
		const isProbePost = plannedSlot?.isProbe === true;
		const warmupPolicy = plannedSlot?.warmupPolicy ?? null;
		const requiresMedia = ctx.targetPlatform === "instagram" && !isProbePost;
		const forceTextOnly =
			ctx.targetPlatform === "threads" && warmupPolicy?.textOnly === true;
		const effectiveMediaChance =
			ctx.targetPlatform === "threads" && warmupPolicy?.mediaChanceCap != null
				? Math.min(ctx.slotMediaChance, warmupPolicy.mediaChanceCap)
				: ctx.slotMediaChance;

		if (
			!isProbePost &&
			!forceTextOnly &&
			(requiresMedia ||
				(effectiveMediaChance > 0 &&
					Math.random() < effectiveMediaChance / 100))
		) {
			try {
				const mediaGroupId = ctx.mediaGroupId || ctx.groupId || "";
				const { data: randomMedia } = await db()
					.from("media")
					.select("url, file_type")
					.eq("user_id", ctx.ownerId)
					.eq("group_id", mediaGroupId)
					.limit(50);
				if (randomMedia && randomMedia.length > 0) {
					// Media Strategy 2026 Section 2: video = 87% less reach on Threads.
					const filtered =
						ctx.targetPlatform !== "instagram"
							? randomMedia.filter(
									(m: { file_type?: string | undefined }) =>
										!(m.file_type || "").startsWith("video"),
								)
							: randomMedia;
					const mediaPool = filtered.length > 0 ? filtered : randomMedia;
					const fresh = mediaPool.filter(
						(m: { url: string }) => !batchUsedMediaUrls.has(m.url),
					);
					const pool = fresh.length > 0 ? fresh : mediaPool;
					const pick = pool[Math.floor(Math.random() * pool.length)];
					mediaUrls = [pick!.url];
					batchUsedMediaUrls.add(pick!.url);
					const ft = (pick!.file_type || "") as string;
					isVideo = ft.startsWith("video");
				}
			} catch {
				// Best-effort — post goes out without media
			}
		}
		// If media is required and not found in library, try AI image generation
		if (requiresMedia && (!mediaUrls || mediaUrls.length === 0)) {
			try {
				const { generateImageForPost, hasImageGenerationCapability } =
					await import("./mediaGeneration.js");
				if (await hasImageGenerationCapability(ctx.ownerId)) {
					const generatedUrl = await generateImageForPost(
						idea.content,
						ctx.ownerId,
						ctx.targetPlatform,
						ctx.voiceProfile,
					);
					if (generatedUrl) {
						mediaUrls = [generatedUrl];
						logger.info("AI-generated image for IG queue item", {
							workspaceId: ctx.workspaceId,
						});
					}
				}
			} catch (err) {
				logger.debug("AI image generation is best-effort", {
					error: String(err),
				});
			}
		}
		if (requiresMedia && (!mediaUrls || mediaUrls.length === 0)) {
			logger.warn("Skipping IG idea because no media was available", {
				workspaceId: ctx.workspaceId,
			});
			rejectedCount++;
			rejectionReasons["no-media-for-ig"] =
				(rejectionReasons["no-media-for-ig"] || 0) + 1;
			continue;
		}

		// Format-specific IG timing: nudge Reels to evening, images to morning
		let adjustedScheduledFor = scheduledFor;
		if (ctx.targetPlatform === "instagram") {
			const fmt = isVideo ? "REELS" : undefined;
			adjustedScheduledFor = nudgeScheduleForFormat(
				scheduledFor,
				isVideo,
				ctx.timezone,
				fmt,
			);
			} else if (warmupPolicy?.primaryHoursOnly) {
				adjustedScheduledFor = nudgeScheduleToRestartWarmupPrimaryHour(
					scheduledFor,
					ctx.timezone,
					plannedSlot?.accountId ??
						`${ctx.groupId ?? ctx.workspaceId}:${currentSlot}`,
				);
			}
			if (plannedSlot?.accountId && warmupPolicy?.allowedPostsPerDay != null) {
				try {
					const capacity = await getRemainingPostingCapacity({
						workspaceId: ctx.workspaceId,
						groupId: ctx.groupId,
						accountId: plannedSlot.accountId,
						timezone: plannedSlot.timezone ?? ctx.timezone,
						now: new Date(adjustedScheduledFor),
						state: {
							restart_warmup_status: warmupPolicy.status,
							restart_warmup_day: warmupPolicy.day,
							restart_warmup_allowed_posts_per_day:
								warmupPolicy.allowedPostsPerDay,
							restart_warmup_reason: warmupPolicy.reason,
						},
					});
					if (capacity.remaining !== null && capacity.remaining <= 0) {
						const reason =
							warmupPolicy.status === "suppressed"
								? "suppressed_cap_zero"
								: warmupPolicy.status === "held"
									? "held_cap_exceeded"
									: "warmup_cap_exceeded";
						logger.info("[scheduleAndInsert] Skipping over-cap warm-up row", {
							workspaceId: ctx.workspaceId,
							groupId: ctx.groupId,
							accountId: plannedSlot.accountId,
							cap: capacity.cap,
							used: capacity.used,
							reason,
						});
						rejectedCount++;
						rejectionReasons[reason] = (rejectionReasons[reason] || 0) + 1;
						continue;
					}
				} catch (err) {
					logger.warn("[scheduleAndInsert] Warm-up capacity check failed", {
						workspaceId: ctx.workspaceId,
						groupId: ctx.groupId,
						accountId: plannedSlot.accountId,
						error: err instanceof Error ? err.message : String(err),
					});
				}
			}

			// Reply bait suffix — 20% of GFE posts get an engagement hook appended
		let preHumanize = idea.content;
		if (idea.contentType === "gfe_bait" && Math.random() < 0.2) {
			const baits = [
				" or is that just me",
				" anyone?",
				" be honest",
				" u feel me?",
				" tell me im wrong",
			];
			const bait = baits[Math.floor(Math.random() * baits.length)];
			if (preHumanize.length + bait!.length < 150) {
				preHumanize = preHumanize.replace(/[.!]?\s*$/, bait!);
			}
		}

		// Humanize — add micro-human tics before insertion
		const finalQueueContent = humanizePost(preHumanize);
		const sourceType = idea.sourceCompetitorId ? "competitor_copy" : "ai";
		const taxonomyLeak = detectTaxonomyLabelLeak(finalQueueContent);
		if (taxonomyLeak) {
			const reason = taxonomyLeak.reason;
			logger.info("[scheduleAndInsert] Skipping post after final content filter", {
				workspaceId: ctx.workspaceId,
				groupId: ctx.groupId,
				reason,
				matchedText: taxonomyLeak.matchedText,
			});
			rejectedCount++;
			rejectionReasons[reason] = (rejectionReasons[reason] || 0) + 1;
			continue;
		}

		// Competitor copy ratio gate
		if (idea.sourceCompetitorId) {
			if (batchCompetitorCount >= maxCompetitorInBatch) {
				logger.debug(
					"[queueFill] Competitor ratio exceeded in batch, skipping",
					{
						batchCompetitorCount,
						maxCompetitorInBatch,
						competitorCopyRatio,
						groupId: ctx.groupId,
					},
				);
				rejectedCount++;
				rejectionReasons["competitor-batch-cap"] =
					(rejectionReasons["competitor-batch-cap"] || 0) + 1;
				continue;
			}
			// 30-day cap removed — competitor content is the strategy
		}

		// Cross-account competitor dedup — max 15 accounts per competitor post in 48h
		// Uses atomic INCR to avoid TOCTOU race between concurrent fills
		if (idea.sourceCompetitorId) {
			try {
				const { getRedis } = await import("../../redis.js");
				const redis = getRedis();
				const competitorDedupKey = `competitor-adapted:${idea.sourceCompetitorId}`;
				const newCount = await redis.incr(competitorDedupKey);
				// Set TTL on first increment
				if (newCount === 1) {
					await redis.expire(competitorDedupKey, 48 * 60 * 60);
				}
				if (newCount > 15) {
					// Already past limit — roll back the increment
					await redis.decr(competitorDedupKey);
					logger.debug(
						"[queueFill] Competitor dedup: max 15 accounts reached",
						{
							competitorId: idea.sourceCompetitorId,
							count: newCount,
						},
					);
					rejectedCount++;
					rejectionReasons["competitor-dedup-15-accounts"] =
						(rejectionReasons["competitor-dedup-15-accounts"] || 0) + 1;
					continue;
				}
			} catch {
				// Fail-open — proceed without dedup check
			}
		}

		// Spoiler tricks — detect spoiler-worthy words in content (Threads only)
		let textSpoilerMeta: {
			word: string;
			charOffset: number;
			charLength: number;
		} | null = null;
		if (ctx.targetPlatform !== "instagram") {
			try {
				const { detectNaturalSpoiler, detectNaturalCuriositySpoiler } =
					await import("./spoilerTricks.js");

				// Try curiosity-gap first (higher engagement), then double-meaning
				const curiosityWord = detectNaturalCuriositySpoiler(finalQueueContent);
				if (curiosityWord) {
					// Full-word spoiler: store word + offset=0 + length=full word
					textSpoilerMeta = {
						word: curiosityWord,
						charOffset: 0,
						charLength: curiosityWord.length,
					};
				} else {
					const doubleMeaning = detectNaturalSpoiler(finalQueueContent);
					if (doubleMeaning) {
						textSpoilerMeta = doubleMeaning;
					}
				}
			} catch {
				// Non-blocking — post without spoiler
			}
		}

		let topicTag: string | null = null;
		if (ctx.targetPlatform !== "instagram") {
			try {
				const { detectTopicTag } = await import("./evergreenManager.js");
				topicTag = detectTopicTag(finalQueueContent);
			} catch {
				// Non-blocking — publish without topic tag if detection fails
			}
		}

		// Pre-assigned account from planner (legacy) or pool mode (v3+)
		// In pool mode, no account_id is assigned — the scheduler claims at dispatch time

		// Build metadata — video flag + LLM judge result when present.
		// The judge result is stamped onto idea.judgeResult by runLLMJudgePhase
		// when the per-group judge is enabled; persisting it on the queue row
		// lets a future eval harness replay decisions against ground-truth
		// labels without a schema change.
		interface PersistedJudge {
			passed: true;
			score: number;
			dimensions: Record<string, number>;
			rationale?: string | undefined;
		}
		const rawJudge = (idea as { judgeResult?: unknown | undefined })
			.judgeResult;
		const judge =
			rawJudge &&
			typeof rawJudge === "object" &&
			(rawJudge as { passed?: unknown | undefined }).passed === true
				? (rawJudge as PersistedJudge)
				: null;
		const judgeMeta = judge
			? {
					judge: {
						score: judge.score,
						dimensions: judge.dimensions,
						rationale: judge.rationale ?? null,
					},
				}
			: undefined;
		const baseMeta = isVideo
			? { is_video: true, media_format: "REELS" }
			: undefined;
		let qualityGate = idea.qualityGate ?? null;
		const qualityGateMeta = qualityGate
			? {
					quality_gate: {
						decision: qualityGate.decision,
						reason: qualityGate.reason,
						confidences: qualityGate.confidences,
						flags: qualityGate.flags,
						score: qualityGate.score,
					},
				}
			: undefined;
		let metadata: Record<string, unknown> | undefined =
			baseMeta || judgeMeta || qualityGateMeta
				? {
						...(baseMeta ?? {}),
						...(judgeMeta ?? {}),
						...(qualityGateMeta ?? {}),
					}
				: undefined;

		const fingerprint = buildPublishFingerprint({
			workspaceId: ctx.workspaceId,
			accountId: plannedSlot?.accountId ?? null,
			platform: ctx.targetPlatform,
			content: finalQueueContent,
			mediaUrls,
		});
		const duplicateMatch = plannedSlot?.accountId
			? await findRecentDuplicateFingerprint({
					workspaceId: ctx.workspaceId,
					accountId: plannedSlot.accountId,
					platform: ctx.targetPlatform,
					normalizedTextHash: fingerprint.normalizedTextHash,
					mediaFingerprint: fingerprint.mediaFingerprint,
					duplicateWindowHours: fingerprint.duplicateWindowHours,
				})
			: null;
		const generationId =
			ctx.fillCycleId ??
			`generated:${ctx.workspaceId}:${fingerprint.normalizedTextHash.slice(0, 16)}`;
		const sourceId =
			idea.sourceCompetitorId ??
			(ctx.groupId ? `group:${ctx.groupId}` : `workspace:${ctx.workspaceId}`);
		const provenanceMeta = {
			provenance: {
				source_type: sourceType,
				source_id: sourceId,
				source_competitor_id: idea.sourceCompetitorId ?? null,
				content_fingerprint: fingerprint.normalizedTextHash,
				publish_fingerprint: fingerprint.publishFingerprint,
				generation_id: generationId,
				quality_gate_result: qualityGate?.decision ?? "not_run",
				judge_result: judge ? "llm_judge_passed" : "quality_gate_backstop",
				quality_gate: qualityGate
					? {
							decision: qualityGate.decision,
							reason: qualityGate.reason,
						}
					: null,
				judge: judge
					? {
							score: judge.score,
							dimensions: judge.dimensions,
						}
					: null,
			},
			content_fingerprint: fingerprint.normalizedTextHash,
			publish_fingerprint: fingerprint.publishFingerprint,
			generation_id: generationId,
			source_id: sourceId,
		};
		metadata = {
			...(metadata ?? {}),
			...provenanceMeta,
		};
		const attribution = classifyCompetitorPattern({
			content: finalQueueContent,
			topicTag,
			mediaType: (mediaUrls ?? []).length > 0 ? "IMAGE" : "TEXT",
			publishedAt: adjustedScheduledFor,
		});
		const archetypeDecision = classifyContentArchetype(finalQueueContent);
		const strategyMatch = matchStrategyRecommendation(
			{
				...attribution,
				content_archetype: archetypeDecision.archetype,
			},
			ctx.strategyRecommendations || [],
		);
		const explicitWinnerCloneRecommendation =
			idea.strategyRecommendationId || idea.cloneFamily || idea.winnerClone
				? ((ctx.strategyRecommendations || []).find((rec) => {
						if (
							idea.strategyRecommendationId &&
							rec.id === idea.strategyRecommendationId
						) {
							return true;
						}
						if (rec.pattern_type !== "winner_clone") return false;
						const basis = metricBasisFor(rec);
						const sourceText = stringBasisValue(basis, "sourceText");
						const cloneFamily = sourceText
							? classifyWinnerCloneFamilyFromContent({
									content: sourceText,
									contentArchetype: stringBasisValue(
										basis,
										"contentArchetype",
									),
									questionSubtype: stringBasisValue(
										basis,
										"questionSubtype",
									),
									shapeId: stringBasisValue(basis, "shapeId"),
								})
							: stringBasisValue(basis, "cloneFamily");
						return Boolean(
							idea.cloneFamily && cloneFamily === idea.cloneFamily,
						);
					}) ?? null)
				: null;
		const sourcePatternWinnerRecommendation = findWinnerCloneRecommendation({
			recommendations: ctx.strategyRecommendations || [],
			sourcePatternId: idea.sourcePatternId,
			content: finalQueueContent,
			topicLabel: attribution.topic_label,
			contentArchetype: archetypeDecision.archetype,
			questionSubtype: archetypeDecision.questionSubtype,
		});
		const performanceRecommendation =
			explicitWinnerCloneRecommendation ||
			strategyMatch.recommendation ||
			sourcePatternWinnerRecommendation ||
			null;
		const performanceBucket = performanceRecommendation
			? "proven"
			: strategyMatch.bucket;
		const strategyMetricBasis = metricBasisFor(performanceRecommendation);
		const effectiveSourcePatternId =
			idea.sourcePatternId ||
			stringBasisValue(strategyMetricBasis, "sourcePatternId") ||
			stringBasisValue(strategyMetricBasis, "sourcePostId") ||
			stringBasisValue(strategyMetricBasis, "winnerPatternId") ||
			(performanceRecommendation?.pattern_type === "winner_clone"
				? performanceRecommendation.pattern_value
				: null);
		const sourceTextForFrame =
			stringBasisValue(strategyMetricBasis, "sourceText") || idea.sourceContent;
		const sourceFrame = sourceTextForFrame
			? classifyProfileCuriosityFrame(sourceTextForFrame)
			: null;
		const sourceTaxonomyLeak = sourceTextForFrame
			? detectTaxonomyLabelLeak(sourceTextForFrame)
			: null;
		const winnerCloneSourceTaxonomyLeak =
			performanceRecommendation?.pattern_type === "winner_clone" &&
			Boolean(sourceTaxonomyLeak);
		const frameAlignmentScore =
			performanceRecommendation?.pattern_type === "winner_clone" &&
			sourceTextForFrame
				? winnerCloneFrameAlignmentScore({
						sourceContent: sourceTextForFrame,
						candidateContent: finalQueueContent,
					})
				: null;
		const winnerCloneFrameMismatch =
			performanceRecommendation?.pattern_type === "winner_clone" &&
			sourceFrame !== null &&
			sourceFrame.profileCuriosityFrame !== "generic_topic" &&
			typeof frameAlignmentScore === "number" &&
			frameAlignmentScore < -25;
		const effectiveCloneFamily = sourceTextForFrame
			? classifyWinnerCloneFamilyFromContent({
					content: sourceTextForFrame,
					contentArchetype: stringBasisValue(
						strategyMetricBasis,
						"contentArchetype",
					),
					questionSubtype: stringBasisValue(
						strategyMetricBasis,
						"questionSubtype",
					),
					shapeId: stringBasisValue(strategyMetricBasis, "shapeId"),
				})
			: stringBasisValue(strategyMetricBasis, "cloneFamily");
		const effectivePerformanceBasis =
			stringBasisValue(strategyMetricBasis, "performanceBasis") ||
			stringBasisValue(strategyMetricBasis, "basis");
		const effectiveWinnerPatternId =
			stringBasisValue(strategyMetricBasis, "winnerPatternId") ||
			stringBasisValue(strategyMetricBasis, "sourcePatternId") ||
			(performanceRecommendation?.pattern_type === "winner_clone"
				? performanceRecommendation.pattern_value
				: null);
		const performanceEvidence = performanceRecommendation
			? {
					sourcePatternId: effectiveSourcePatternId,
					winnerPatternId: effectiveWinnerPatternId,
					strategyRecommendationId: performanceRecommendation.id,
					cloneFamily: effectiveCloneFamily,
					patternType: performanceRecommendation.pattern_type,
					strategyBucket: performanceBucket,
					confidence: performanceRecommendation.confidence,
					performanceBasis: effectivePerformanceBasis,
					isGenericBait: archetypeDecision.isGenericQuestion,
					isDirectLongCopy:
						sourceType === "competitor_copy" &&
						Boolean(idea.sourceContent) &&
						!effectiveCloneFamily &&
						performanceRecommendation.pattern_type !== "winner_clone" &&
						finalQueueContent.length > 60,
					isProfileDeadEnd:
						performanceRecommendation.pattern_type === "winner_clone" &&
						isProfileCuriosityDeadEndContent(finalQueueContent),
					isFrameMismatch: winnerCloneFrameMismatch,
					sourceHasTaxonomyLeak: winnerCloneSourceTaxonomyLeak,
					frameAlignmentScore,
				}
			: null;
		qualityGate = qualityGate
			? applyPerformanceBackedQualityGateLane(qualityGate, {
					sourceType,
					sourceContent: idea.sourceContent || null,
					sourceCompetitorId: idea.sourceCompetitorId || null,
					viralScore: idea.viralScore ?? null,
					performanceEvidence,
				})
			: null;
		const winnerCloneMeta = performanceRecommendation
			? {
					winner_clone_applied:
						performanceRecommendation.pattern_type === "winner_clone",
					winner_clone: {
						source_pattern_id: performanceEvidence?.sourcePatternId ?? null,
						winner_pattern_id: performanceEvidence?.winnerPatternId ?? null,
						strategy_recommendation_id:
							performanceEvidence?.strategyRecommendationId ?? null,
						clone_family: performanceEvidence?.cloneFamily ?? null,
						pattern_type: performanceEvidence?.patternType ?? null,
						strategy_bucket: performanceEvidence?.strategyBucket ?? null,
						confidence: performanceEvidence?.confidence ?? null,
						performance_basis: performanceEvidence?.performanceBasis ?? null,
						profile_curiosity_frame:
							sourceFrame?.profileCuriosityFrame ??
							stringBasisValue(strategyMetricBasis, "profileCuriosityFrame"),
						curiosity_mechanism:
							sourceFrame?.curiosityMechanism ??
							stringBasisValue(strategyMetricBasis, "curiosityMechanism"),
						dating_angle:
							sourceFrame?.datingAngle ??
							(strategyMetricBasis.datingAngle === true),
						validation_angle:
							sourceFrame?.validationAngle ??
							(strategyMetricBasis.validationAngle === true),
						identity_angle:
							sourceFrame?.identityAngle ??
							(strategyMetricBasis.identityAngle === true),
						frame_alignment_score: frameAlignmentScore,
						frame_mismatch: winnerCloneFrameMismatch,
						source_taxonomy_leak: winnerCloneSourceTaxonomyLeak
							? (sourceTaxonomyLeak?.reason ?? null)
							: null,
						source_text: sourceTextForFrame ?? null,
						views_24h:
							typeof strategyMetricBasis.views24h === "number" ||
							typeof strategyMetricBasis.views24h === "string"
								? strategyMetricBasis.views24h
								: null,
					},
					clone_family: performanceEvidence?.cloneFamily ?? null,
				}
			: undefined;
		const qualityGateLaneMeta = qualityGate?.lane
			? {
					quality_gate_lane: qualityGate.lane,
					quality_gate_reason: qualityGate.laneReason ?? qualityGate.reason,
					performance_backed_clone: {
						lane: qualityGate.lane,
						reason: qualityGate.laneReason ?? qualityGate.reason,
						source_pattern_id:
							qualityGate.performanceEvidence?.sourcePatternId ?? null,
						winner_pattern_id:
							qualityGate.performanceEvidence?.winnerPatternId ?? null,
						strategy_recommendation_id:
							qualityGate.performanceEvidence?.strategyRecommendationId ?? null,
						clone_family: qualityGate.performanceEvidence?.cloneFamily ?? null,
						pattern_type: qualityGate.performanceEvidence?.patternType ?? null,
						strategy_bucket:
							qualityGate.performanceEvidence?.strategyBucket ?? null,
						confidence: qualityGate.performanceEvidence?.confidence ?? null,
						performance_basis:
							qualityGate.performanceEvidence?.performanceBasis ?? null,
						predicted_viral_score: idea.viralScore ?? null,
						quality_score: qualityGate.score,
					},
				}
			: undefined;
		metadata = {
			...(metadata ?? {}),
			quality_gate: qualityGate
				? {
						decision: qualityGate.decision,
						reason: qualityGate.reason,
						lane: qualityGate.lane ?? "standard",
						laneReason: qualityGate.laneReason ?? null,
						confidences: qualityGate.confidences,
						flags: qualityGate.flags,
						score: qualityGate.score,
					}
				: null,
			provenance: {
				...((metadata?.provenance as Record<string, unknown> | undefined) ??
					{}),
				quality_gate_result: qualityGate?.decision ?? "not_run",
				quality_gate: qualityGate
					? {
							decision: qualityGate.decision,
							reason: qualityGate.reason,
							lane: qualityGate.lane ?? "standard",
						}
					: null,
			},
			...(winnerCloneMeta ?? {}),
			...(qualityGateLaneMeta ?? {}),
		};
		const provenanceCheck = evaluateQueueProvenance({
			source_type: sourceType,
			source_competitor_id: idea.sourceCompetitorId ?? null,
			content_fingerprint: fingerprint.normalizedTextHash,
			publish_fingerprint: fingerprint.publishFingerprint,
			generation_id: generationId,
			source_id: sourceId,
			metadata,
		});
		const [contentArc, creatorIdentity, recentSiblingRepetitions] =
			await Promise.all([
				loadActiveContentArcContext({
					workspaceId: ctx.workspaceId,
					groupId: ctx.groupId,
					accountId: plannedSlot?.accountId ?? null,
				}),
				loadCreatorIdentityContext({
					workspaceId: ctx.workspaceId,
					groupId: ctx.groupId,
					accountId: plannedSlot?.accountId ?? null,
				}),
				loadRecentSiblingRepetitionContext({
					groupId: ctx.groupId,
					accountId: plannedSlot?.accountId ?? null,
				}),
			]);
		const dnaContext = await loadAccountDnaContext({
			workspaceId: ctx.workspaceId,
			groupId: ctx.groupId,
			accountId: plannedSlot?.accountId ?? null,
		});
		const dnaEvaluation = evaluateAccountDna({
			content: finalQueueContent,
			dna: dnaContext.dna,
			rules: dnaContext.rules,
			siblingRules: dnaContext.siblingRules,
			creatorDna: creatorIdentity.creatorDna,
			accountFlavor: creatorIdentity.accountFlavor,
			recentSiblingRepetitions,
			attribution: {
				...attribution,
				content_archetype: archetypeDecision.archetype,
			},
			predictedViralScore: idea.viralScore ?? null,
		});
		const dnaRequiresReview =
			dnaEvaluation.decision === "needs_review" ||
			dnaEvaluation.decision === "regenerate" ||
			dnaEvaluation.decision === "block";
		const winnerCloneGuardReason = winnerCloneSourceTaxonomyLeak
			? "winner_clone_source_taxonomy_leak"
			: winnerCloneFrameMismatch
				? "winner_clone_frame_mismatch"
				: null;
		const bypassDnaReviewForPerformanceClone =
			canPerformanceBackedCloneBypassDnaReview({
				dnaEvaluation,
				qualityGate,
				winnerCloneFrameMismatch,
				winnerCloneSourceTaxonomyLeak,
				hasDuplicateMatch: Boolean(duplicateMatch),
				hasMissingProvenance: provenanceCheck.decision === "missing",
			});

		const requiresApproval =
			(idea.viralScore ?? 0) < approvalThreshold ||
			qualityGate?.decision === "needs_review" ||
			Boolean(winnerCloneGuardReason) ||
			Boolean(duplicateMatch) ||
			provenanceCheck.decision === "missing" ||
			(dnaRequiresReview && !bypassDnaReviewForPerformanceClone);
		const missingPlannedReadyConstraints =
			ctx.targetPlatform === "threads" &&
			isPoolMode &&
			!plannedSlot &&
			!requiresApproval;
		const finalRequiresApproval =
			requiresApproval || missingPlannedReadyConstraints;
		const queueStatus = finalRequiresApproval ? "needs_review" : "pending";
		const accountMinIntervalGuard =
			await avoidReadyAccountMinIntervalCollision({
				workspaceId: ctx.workspaceId,
				platform: ctx.targetPlatform,
				queueStatus,
				scheduledFor: adjustedScheduledFor,
				accountId: plannedSlot?.accountId ?? null,
				minIntervalMinutes: plannedSlot?.minIntervalMinutes ?? null,
				seed: `${ctx.workspaceId}:${ctx.groupId ?? "workspace"}:${plannedSlot?.accountId ?? "pool"}:${currentSlot}:${finalQueueContent}:account-min-interval`,
			});
		adjustedScheduledFor = accountMinIntervalGuard.scheduledFor;
		const sameMinuteGuard = await avoidReadySameMinuteCollision({
			workspaceId: ctx.workspaceId,
			platform: ctx.targetPlatform,
			queueStatus,
			scheduledFor: adjustedScheduledFor,
			seed: `${ctx.workspaceId}:${ctx.groupId ?? "workspace"}:${plannedSlot?.accountId ?? "pool"}:${currentSlot}:${finalQueueContent}`,
		});
		adjustedScheduledFor = sameMinuteGuard.scheduledFor;
		const approvalMeta = finalRequiresApproval
			? {
					approval: {
						reason: missingPlannedReadyConstraints
							? "missing_planned_account_constraints"
							: duplicateMatch
								? "duplicate_fingerprint_needs_review"
								: provenanceCheck.decision === "missing"
									? "provenance_missing_needs_review"
									: dnaRequiresReview
										? `dna_${dnaEvaluation.decision}`
										: winnerCloneGuardReason
											? winnerCloneGuardReason
										: qualityGate?.decision === "needs_review"
											? qualityGate.reason
											: "below_confidence_threshold",
						score: idea.viralScore ?? null,
						threshold: approvalThreshold,
						quality_gate_decision: qualityGate?.decision ?? null,
						duplicate_queue_item_id: duplicateMatch?.id ?? null,
						provenance_errors: provenanceCheck.reasons,
						dna_reasons: dnaEvaluation.reasons,
					},
				}
			: undefined;
		const dnaMeta = {
			dna: {
				decision: dnaEvaluation.decision,
				reasons: dnaEvaluation.reasons,
				creator_fit_score: dnaEvaluation.creator_fit_score,
				account_flavor_score: dnaEvaluation.account_flavor_score,
				recent_sibling_repetition_score:
					dnaEvaluation.recent_sibling_repetition_score,
				cross_creator_collision_score:
					dnaEvaluation.cross_creator_collision_score,
			},
		};
		const warmupMeta = warmupPolicy
			? {
					restart_warmup: {
						status: warmupPolicy.status,
						day: warmupPolicy.day,
						maxPostsToday: warmupPolicy.allowedPostsPerDay,
						allowed_posts_per_day: warmupPolicy.allowedPostsPerDay,
						reason: warmupPolicy.reason,
						textOnly: warmupPolicy.textOnly,
						text_only: warmupPolicy.textOnly,
						media_chance_cap: warmupPolicy.mediaChanceCap,
						primaryHoursOnly: warmupPolicy.primaryHoursOnly,
						primary_hours_only: warmupPolicy.primaryHoursOnly,
					},
				}
			: undefined;
		const effectiveTimezone = plannedSlot?.timezone ?? ctx.timezone;
		const selectedHour = localHourForSchedule(
			adjustedScheduledFor,
			effectiveTimezone,
		);
		const selectedMinute = localMinuteForSchedule(
			adjustedScheduledFor,
			effectiveTimezone,
		);
		const timingReason =
			timing?.timingReason ??
			(warmupPolicy?.primaryHoursOnly
				? "warmup_primary_hour"
				: "global_fallback_hour");
		const accountWindow =
			plannedSlot?.activeHoursStart !== undefined ||
			plannedSlot?.activeHoursEnd !== undefined
				? {
						start: plannedSlot.activeHoursStart ?? null,
						end: plannedSlot.activeHoursEnd ?? null,
					}
				: null;
		const plannedAccountIds = [
			...new Set(plannedSlots.map((slot) => slot.accountId).filter(Boolean)),
		];
		const timingMeta = {
			timing: {
				reason: timingReason,
				timingReason,
				selectedHour,
				selectedMinute,
				jitterMinutes: sameMinuteGuard.applied
					? Math.round((sameMinuteGuard.shiftSeconds / 60) * 100) / 100
					: 0,
				accountScheduleId: null,
				accountWindow,
				timezone: effectiveTimezone ?? null,
				warmupApplied: Boolean(warmupPolicy),
				confidence: timing?.confidence ?? 0,
				fallbackSource: timing?.fallbackSource ?? "global",
				sampleSize: timing?.sampleSize ?? 0,
				sameMinuteGuardApplied: sameMinuteGuard.applied,
				sameMinuteGuardShiftSeconds: sameMinuteGuard.shiftSeconds,
				accountMinIntervalGuardApplied: accountMinIntervalGuard.applied,
				accountMinIntervalGuardShiftSeconds:
					accountMinIntervalGuard.shiftSeconds,
				accountMinIntervalGuardConflictCount:
					accountMinIntervalGuard.conflictCount,
			},
		};
		const plannedAccountMeta = plannedSlot
			? {
					planned_account: {
						accountId: plannedSlot.accountId,
						candidateAccountIds:
							plannedAccountIds.length > 0
								? plannedAccountIds
								: [plannedSlot.accountId],
						accountWindow,
						minIntervalMinutes: plannedSlot.minIntervalMinutes ?? null,
						timezone: effectiveTimezone ?? null,
						warmupCap: warmupPolicy?.allowedPostsPerDay ?? null,
						timingReason,
					},
				}
			: undefined;
		const archetypeMeta = {
			content_archetype: {
				value: archetypeDecision.archetype,
				confidence: archetypeDecision.confidence,
				reason: archetypeDecision.reason,
				is_generic_question: archetypeDecision.isGenericQuestion,
				question_subtype: archetypeDecision.questionSubtype,
			},
			identity_shape_id: detectIdentityShapeId(finalQueueContent),
			pattern_type:
				archetypeDecision.questionSubtype === "specific_topical_question"
					? "specific_topical_question"
					: archetypeDecision.archetype,
		};
		const contentArcMeta = buildContentArcMetadata(contentArc);
		const finalMetadata =
			metadata ||
			approvalMeta ||
			dnaMeta ||
			archetypeMeta ||
			contentArcMeta ||
			warmupMeta ||
			timingMeta
				? {
						...(metadata ?? {}),
						...dnaMeta,
						...archetypeMeta,
						...(contentArcMeta ?? {}),
						...(warmupMeta ?? {}),
						...(timingMeta ?? {}),
						...(plannedAccountMeta ?? {}),
						...(approvalMeta ?? {}),
					}
				: undefined;

		const insertData: Record<string, unknown> = {
			workspace_id: ctx.workspaceId,
			content: finalQueueContent,
			status: queueStatus,
			scheduled_for: adjustedScheduledFor,
			platform: ctx.targetPlatform,
			predicted_viral_score: idea.viralScore,
			source_type: sourceType,
			source_content: idea.sourceContent || null,
			content_type: idea.contentType || null,
			source_competitor_id: idea.sourceCompetitorId || null,
			source_competitor_username: idea.sourceCompetitorUsername || null,
			media_urls: mediaUrls,
			normalized_text_hash: fingerprint.normalizedTextHash,
			media_fingerprint: fingerprint.mediaFingerprint,
			publish_fingerprint: fingerprint.publishFingerprint,
			duplicate_window_hours: fingerprint.duplicateWindowHours,
			duplicate_of_queue_item_id: duplicateMatch?.id ?? null,
			content_fingerprint: fingerprint.normalizedTextHash,
			generation_id: generationId,
			source_id: sourceId,
			provenance_status: provenanceCheck.status,
			provenance_error:
				provenanceCheck.reasons.length > 0
					? provenanceCheck.reasons.join(",")
					: null,
			ai_provider: ctx.aiConfig?.provider || null,
			model_provider: idea.modelProvider || ctx.aiConfig?.provider || null,
			prompt_version: idea.promptVersion || null,
			template_id: idea.templateId || null,
			source_pattern_id: effectiveSourcePatternId,
			strategy_recommendation_id: performanceRecommendation?.id || null,
			strategy_bucket: performanceBucket,
			active_arc_id: contentArc?.arcId ?? null,
			arc_beat_id: contentArc?.beatId ?? null,
			hook_type: attribution.hook_type,
			topic_label: attribution.topic_label,
			format_type: attribution.format_type,
			emotional_frame: attribution.emotional_frame,
			reply_mechanism: attribution.reply_mechanism,
			content_length_bucket: attribution.content_length_bucket,
			media_style: attribution.media_style,
			posting_hour: attribution.posting_hour,
			dna_id: dnaEvaluation.dna_id,
			dna_version: dnaEvaluation.dna_version,
			dna_fit_score: dnaEvaluation.dna_fit_score,
			voice_fit_score: dnaEvaluation.voice_fit_score,
			topic_fit_score: dnaEvaluation.topic_fit_score,
			mood_fit_score: dnaEvaluation.mood_fit_score,
			uniqueness_score: dnaEvaluation.uniqueness_score,
			sibling_collision_score: dnaEvaluation.sibling_collision_score,
			genericness_score: dnaEvaluation.genericness_score,
			dna_decision: dnaEvaluation.decision,
			dna_reasons: dnaEvaluation.reasons,
			topic_tag: topicTag,
			// Pool mode (v3+): no account_id, set pool_status='available'
			// Legacy (v2): pre-assign account from planner
			...(isPoolMode
				? { pool_status: "available" }
				: plannedSlot
					? { account_id: plannedSlot.accountId }
					: {}),
			...(finalMetadata ? { metadata: finalMetadata } : {}),
			...(textSpoilerMeta ? { text_spoilers: textSpoilerMeta } : {}),
		};
		if (ctx.groupId) insertData.group_id = ctx.groupId;

		try {
			const { data: inserted, error } = await (
				db() as ReturnType<typeof getSupabaseAny>
			)
				.from("auto_post_queue")
				.insert(
					insertData as unknown as Parameters<
						ReturnType<ReturnType<typeof getSupabaseAny>["from"]>["insert"]
					>[0],
				)
				.select("id")
				.single();

			if (!error && inserted?.id) {
				if (plannedSlot?.isProbe) {
					try {
						const { data: probeState } = await db()
							.from("account_autoposter_state")
							.select("probe_posts_remaining")
							.eq("account_id", plannedSlot.accountId)
							.eq("status", "suppressed_probe")
							.maybeSingle();
						const remaining = Math.max(
							0,
							Number(
								(probeState as { probe_posts_remaining?: number } | null)
									?.probe_posts_remaining ?? 1,
							) - 1,
						);
						await db()
							.from("account_autoposter_state")
							.update({
								probe_posts_remaining: remaining,
								updated_at: new Date().toISOString(),
							})
							.eq("account_id", plannedSlot.accountId)
							.eq("status", "suppressed_probe");
					} catch (probeErr) {
						logger.warn(
							"[scheduleAndInsert] Failed to decrement probe counter",
							{
								accountId: plannedSlot.accountId,
								error:
									probeErr instanceof Error
										? probeErr.message
										: String(probeErr),
							},
						);
					}
				}
				insertedCount++;
				if (idea.sourceCompetitorId) batchCompetitorCount++;
				insertedContents.push(idea.content);

				// Dispatch QStash to publish at exact scheduled_for time (group mode only).
				// Low-confidence rows stay in the review queue until explicitly approved.
				if (ctx.groupId && queueStatus === "pending") {
					try {
						const { getQStashClient } = await import("../../qstash.js");
						const { RETRIES, getFailureCallbackUrl, getRequiredAppBaseUrl } =
							await import("../../qstashDefaults.js");
						const { recordInfraEvent } = await import(
							"../../infraTelemetry.js"
						);
						const qstash = getQStashClient();
						const baseUrl = getRequiredAppBaseUrl();
						const scheduleNonce = `auto-post-${inserted.id}-${Math.floor(new Date(adjustedScheduledFor).getTime() / 1000)}`;
						const persistedScheduleNonce = await ensureQueueItemScheduleNonce(
							inserted.id,
							scheduleNonce,
						);

						const scheduledUnix = Math.floor(
							new Date(adjustedScheduledFor).getTime() / 1000,
						);
						const result = await qstash.publishJSON({
							url: `${baseUrl}/api/auto-post-publish`,
							body: {
								queueItemId: inserted.id,
								workspaceId: ctx.workspaceId,
								groupId: ctx.groupId,
								ownerId: ctx.ownerId,
								groupName: ctx.resolvedGroupName,
								...(plannedSlot ? { accountId: plannedSlot.accountId } : {}),
								scheduleNonce: persistedScheduleNonce,
								traceId:
									ctx.fillCycleId ||
									`ap-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
							},
							notBefore: scheduledUnix,
							retries: RETRIES.CRITICAL,
							deduplicationId: persistedScheduleNonce,
							failureCallback: getFailureCallbackUrl(),
						});
						await rescheduleQueueItemForFutureDispatch(inserted.id, {
							accountId: plannedSlot?.accountId ?? null,
							scheduledFor: adjustedScheduledFor,
							scheduleNonce: persistedScheduleNonce,
							qstashMessageId: result.messageId,
						});
						await recordInfraEvent("autopost-fill-dispatch", {
							queueItemId: inserted.id,
							scheduleNonce: persistedScheduleNonce,
							qstashMessageId: result.messageId,
							groupId: ctx.groupId,
							workspaceId: ctx.workspaceId,
							scheduledFor: adjustedScheduledFor,
						});
					} catch (qErr) {
						const { recordInfraEvent } = await import(
							"../../infraTelemetry.js"
						);
						await recordInfraEvent("autopost-fill-dispatch-failed", {
							queueItemId: inserted.id,
							groupId: ctx.groupId,
							workspaceId: ctx.workspaceId,
							error: String(qErr),
						});
						// QStash dispatch is best-effort — cron reconciliation catches misses
						logger.warn("QStash dispatch failed, cron will pick up", {
							error: String(qErr),
							queueItemId: inserted.id,
							workspaceId: ctx.workspaceId,
							scheduledFor,
						});
					}
				}
			} else if (error) {
				failedCount++;
				const errMsg = error instanceof Error ? error.message : String(error);
				errors.push({ content: idea.content.substring(0, 80), error: errMsg });
				logger.error("Failed to insert AI post", { error: errMsg });
			}
		} catch (insertErr) {
			failedCount++;
			const errMsg =
				insertErr instanceof Error ? insertErr.message : String(insertErr);
			errors.push({ content: idea.content.substring(0, 80), error: errMsg });
			logger.error("Unexpected error inserting AI post", { error: errMsg });
		}
	}

	return {
		insertedCount,
		failedCount,
		rejectedCount,
		rejectionReasons,
		insertedContents,
		errors,
	};
}
