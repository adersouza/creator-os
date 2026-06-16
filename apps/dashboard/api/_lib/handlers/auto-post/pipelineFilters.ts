// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Pipeline Filters — content quality gates and dedup pipeline
 *
 * Extracted from queueFill.ts. Handles:
 * - Phase 1: Fast filter (regex + variation gate + content scoring)
 * - Phase 2: Embedding dedup (semantic similarity + cross-group diversity)
 * - Intra-batch variation tracking
 */

import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import { type FilterConfig, filterAndLog } from "./contentFilter.js";
import { scoreContent } from "./contentScorer.js";
import { checkSemanticDedup } from "./embeddingGate.js";
import {
	type JudgeBatchOptions,
	type JudgeVerdict,
	judgeBatch,
} from "./llmJudge.js";
import { recordLLMJudgeSkips } from "./llmJudgeCircuitBreaker.js";
import { runPrefilter } from "./prefilterGate.js";
import {
	evaluateAIQualityGate,
	type AIQualityGateResult,
} from "./qualityGate.js";
import { classifyContentArchetype } from "./contentArchetypes.js";
import {
	isHighValueProfileCuriosityContent,
	isProfileCuriosityDeadEndContent,
} from "./performanceFirst.js";

const db = () => getSupabaseAny();

// ============================================================================
// Types
// ============================================================================

export interface AIIdea {
	content: string;
	viralScore?: number | undefined;
	promptVersion?: string | undefined;
	templateId?: string | undefined;
	modelProvider?: string | undefined;
	sourceContent?: string | null | undefined;
	sourcePatternId?: string | null | undefined;
	strategyRecommendationId?: string | null | undefined;
	strategyRecommendationPatternType?: string | null | undefined;
	strategyRecommendationConfidence?: number | undefined;
	cloneFamily?: string | null | undefined;
	winnerClone?: boolean | undefined;
	contentType?: string | null | undefined;
	sourceCompetitorId?: string | null | undefined;
	sourceCompetitorUsername?: string | null | undefined;
	targetAccountId?: string | undefined;
	targetRoundRobinIndex?: number | undefined;
	targetIsProbe?: boolean | undefined;
	qualityGate?: AIQualityGateResult | undefined;
	/**
	 * W3 router flag: mark this idea as hero/tone-critical so it routes to
	 * Claude Haiku 4.5 instead of the xAI/Gemini path. Defaults to false.
	 * Criteria for setting this is still TBD — see project_w3_model_router
	 * memory for the decision log.
	 */
	isHeroPost?: boolean | undefined;
}

export interface FilterSurvivor {
	idea: AIIdea;
	index: number;
	scheduledFor: string;
	timing?:
		| {
				selectedHour: number;
				timingReason: string;
				confidence: number;
				fallbackSource: string;
				sampleSize: number;
		  }
		| undefined;
}

export interface FilterPipelineResult {
	survivors: FilterSurvivor[];
	rejectedCount: number;
	rejectionReasons: Record<string, number>;
}

export interface DedupPipelineResult {
	candidates: FilterSurvivor[];
	rejectedCount: number;
	rejectionReasons: Record<string, number>;
}

// ============================================================================
// Variation Tracking State
// ============================================================================

export interface VariationPost {
	content: string;
	charLen: number;
	openingWord: string;
	contentType: string | null;
}

function normalizeGeneratedContent(content: string): string {
	let normalized = content.trim();

	// Remove wrapper artifacts instead of throwing away otherwise-usable ideas.
	normalized = normalized
		.replace(/^["'`]+|["'`]+$/g, "")
		.replace(/^\*\*(.*?)\*\*$/s, "$1")
		.replace(/^__(.*?)__$/s, "$1")
		.replace(/[\u2013\u2014]/g, "-")
		.replace(/\s+/g, " ")
		.trim();

	// If the model leaks an internal bucket/report label, salvage the user-facing
	// post body before the structural filter sees it. Human-facing prefixes such
	// as "opinion:" and "confession:" intentionally remain allowed.
	normalized = normalized
		.replace(
			/^(?:specific\s+topical\s+question|recommendation\s+request|observation\s+winner|identity\s+statement|identity_statement|anime_dateability_question|anime_must_watch_question|single_cook_clean_identity|headset_cute_validation|gym_crop_top_identity|music_gatekeeping_question|age_pretty_validation|rating_but_niche_unhinged|clone\s+family)\s*:\s*/i,
			"",
		)
		.trim();

	// Threads one-liners generally read better without a terminal period.
	if (
		/[a-z]{3,}\.$/i.test(normalized) &&
		!/\.\.\.$/.test(normalized) &&
		!/[!?]$/.test(normalized)
	) {
		normalized = normalized.slice(0, -1).trimEnd();
	}

	return normalized;
}

/**
 * Load recent variation posts from the queue for post-to-post variation checks.
 */
export async function loadRecentVariationPosts(
	workspaceId: string,
): Promise<VariationPost[]> {
	const posts: VariationPost[] = [];
	try {
		const { data: recentPosts } = await db()
			.from("auto_post_queue")
			.select("content, content_type")
			.eq("workspace_id", workspaceId)
			.in("status", ["pending", "published", "queued"])
			.order("created_at", { ascending: false })
			.limit(5);
		if (recentPosts) {
			for (const p of recentPosts) {
				const c = (p.content as string) || "";
				posts.push({
					content: c,
					charLen: c.length,
					openingWord: c.split(/\s+/)[0]?.toLowerCase() || "",
					contentType: (p.content_type as string) || null,
				});
			}
		}
	} catch {
		/* non-critical */
	}
	return posts;
}

// ============================================================================
// Phase 1: Fast Filter + Intra-batch Dedup
// ============================================================================

/**
 * Run Phase 1 filtering: regex content filter, variation gate, content scoring.
 * Collects candidates that survive before spending API calls on embedding scoring.
 */
export async function runFastFilterPhase(
	expandedIdeas: AIIdea[],
	scheduledTimes: string[],
	maxInserts: number,
	contentFilterConfig: FilterConfig,
	recentVariationPosts: VariationPost[],
	workspaceId: string,
	groupId: string | undefined,
	fillStartTime: number,
	avoidWords?: string[],
): Promise<FilterPipelineResult> {
	const filterSurvivors: FilterSurvivor[] = [];
	let rejectedCount = 0;
	const rejectionReasons: Record<string, number> = {};

	for (let i = 0; i < expandedIdeas.length; i++) {
		// Cap: stop collecting once we have enough candidates for embedding dedup.
		if (filterSurvivors.length >= maxInserts * 2) break;

		// Budget guard: stop processing if we've used 100s of the 120s budget
		if (Date.now() - fillStartTime > 100_000) {
			logger.warn("Fill budget exceeded 100s, stopping post processing", {
				processedSoFar: i,
				insertedCount: 0,
				rejectedCount,
				elapsed: Date.now() - fillStartTime,
			});
			break;
		}

		const idea = expandedIdeas[i];
		const scheduledFor = scheduledTimes[i] || new Date().toISOString();
		idea!.content = normalizeGeneratedContent(idea!.content);
		const archetypeDecision = classifyContentArchetype(idea!.content);
		idea!.contentType = idea!.contentType || archetypeDecision.archetype;

		// Hard length gate — AI-generated essays (150+ chars) get 0 views
		if (idea!.content.length > 150) {
			rejectedCount++;
			rejectionReasons.too_long = (rejectionReasons.too_long || 0) + 1;
			continue;
		}

		// Content filter gate — reject before wasting API calls
		const filterResult = filterAndLog(
			idea!.content,
			"ai",
			contentFilterConfig,
			{
				workspaceId,
				groupId,
			},
			undefined,
			avoidWords,
		);
		if (!filterResult.passed) {
			rejectedCount++;
			const reason = filterResult.reason || "unknown";
			rejectionReasons[reason] = (rejectionReasons[reason] || 0) + 1;
			// Store rejected post for auto-feed into future system instructions
			try {
				await db()
					.from("auto_post_queue")
					.insert({
						workspace_id: workspaceId,
						content: idea!.content,
						status: "rejected",
						rejection_reason: `${reason}${filterResult.matchedText ? `: ${filterResult.matchedText}` : ""}`,
						source_type: "ai",
						scheduled_for: new Date().toISOString(),
						...(groupId ? { group_id: groupId } : {}),
					});
			} catch {
				// Non-blocking — rejection tracking is best-effort
			}
			continue;
		}

		// Post-to-post variation gate (Voice Profile Engineering S3.7)
		{
			const newLen = idea!.content.length;
			const newOpening = idea!.content.split(/\s+/)[0]?.toLowerCase() || "";
			const newType = idea!.contentType || null;
			const variationFail: string | null = null;

			// Intentional disable, 2026-05-07: backend-reliability-gaps.md notes these checks are too noisy; semantic dedup remains the active variation guard.
			// Check 1: DISABLED — char count similarity was rejecting 20+ posts per fill.
			// Short casual posts (50-90 chars) naturally cluster in a narrow length range.
			// ±3 chars caught 79vs82, 75vs77, 80vs81 — different content, similar length by chance.
			// Opening word + content type checks are sufficient variation enforcement.
			// if (recentVariationPosts.length > 0) { ... }

			// Check 2: DISABLED — opening word repeat was killing ~25% of posts.
			// "i" is the most natural opener for personal content. This is a threads farm,
			// whatever works works. Semantic dedup handles actual duplicates.
			// if (!variationFail && newOpening && recentVariationPosts.length > 0) {
			// 	if (recentVariationPosts[0].openingWord === newOpening) {
			// 		variationFail = `opening_word_repeat:${newOpening}`;
			// 	}
			// }

			// Check 3: DISABLED — format_repeat was the #1 post killer.
			// Even at 5/6, question-format posts (natural for dating/GFE niche)
			// accounted for 97% of variation rejections. The opening_word_repeat
			// check (prev-1) provides basic monotony protection, and embedding
			// dedup (Phase 2) enforces semantic diversity across published posts.
			// Generating 20 posts then killing 5+ for being "too many questions"
			// in a question-driven niche is counterproductive.

			if (variationFail) {
				rejectedCount++;
				rejectionReasons[`variation:${variationFail}`] =
					(rejectionReasons[`variation:${variationFail}`] || 0) + 1;
				continue;
			}

			// Track this post for subsequent variation checks within the batch
			recentVariationPosts.unshift({
				content: idea!.content,
				charLen: newLen,
				openingWord: newOpening,
				contentType: newType,
			});
			if (recentVariationPosts.length > 5) recentVariationPosts.pop();
		}

		// Content quality scorer — reply trigger + warmth + originality
		const score = scoreContent(idea!.content, idea!.sourceContent || null);
		const qualityGate = evaluateAIQualityGate({
			content: idea!.content,
			sourceType: idea!.sourceCompetitorId ? "competitor_copy" : "ai",
			sourceContent: idea!.sourceContent || null,
			sourceCompetitorId: idea!.sourceCompetitorId || null,
			viralScore: idea!.viralScore ?? null,
			filterResult,
			contentScore: score,
			...(avoidWords ? { avoidWords } : {}),
		});
		idea!.qualityGate = qualityGate;

		if (qualityGate.decision === "block") {
			rejectedCount++;
			const reason = qualityGate.reason;
			rejectionReasons[reason] = (rejectionReasons[reason] || 0) + 1;
			try {
				await db()
					.from("auto_post_queue")
					.insert({
						workspace_id: workspaceId,
						content: idea!.content,
						status: "rejected",
						rejection_reason: `${reason} (reply=${score.replyTrigger}, warmth=${score.emotionalWarmth})`,
						source_type: "ai",
						scheduled_for: new Date().toISOString(),
						metadata: {
							quality_gate: qualityGate,
						},
						...(groupId ? { group_id: groupId } : {}),
					});
			} catch {
				// Non-blocking
			}
			continue;
		}

		filterSurvivors.push({ idea: idea!, index: i, scheduledFor });
	}

	return { survivors: filterSurvivors, rejectedCount, rejectionReasons };
}

// ============================================================================
// Phase 1.5: Optional LLM Judge
// ============================================================================

export interface LLMJudgePhaseConfig {
	enabled: boolean;
	apiKey: string;
	minScore: number;
	provider?: string | undefined;
	model?: string | undefined;
	voiceProfileHint?: string | undefined;
	/** When set, judge attributes token cost to this user. */
	costAttribution?:
		| {
				userId: string;
				source: "user" | "env_fallback";
		  }
		| undefined;
	accountIds?: string[] | undefined;
}

/**
 * Run the optional LLM judge between fast filter and embedding dedup. The
 * judge scores phase-1 survivors on five dimensions in a single provider call.
 * Posts below threshold (or vetoed on safety) move to `auto_post_queue` with
 * `status='rejected'`; passing posts get their judge result stamped onto
 * `metadata.judge` so a future eval harness can replay decisions.
 *
 * Fail-closed when enabled: any judge skip/error is rejected. Disabled judge
 * still skips this phase cleanly before reaching this function.
 */
export async function runLLMJudgePhase(
	filterSurvivors: FilterSurvivor[],
	judgeConfig: LLMJudgePhaseConfig,
	workspaceId: string,
	groupId: string | undefined,
): Promise<FilterPipelineResult> {
	if (!judgeConfig.enabled || filterSurvivors.length === 0) {
		return {
			survivors: filterSurvivors,
			rejectedCount: 0,
			rejectionReasons: {},
		};
	}

	const candidates = filterSurvivors.map((s, i) => ({
		index: i,
		content: s.idea.content,
	}));

	const judgeOpts: JudgeBatchOptions = {
		apiKey: judgeConfig.apiKey,
		provider: judgeConfig.provider,
		model: judgeConfig.model,
		minScore: judgeConfig.minScore,
		voiceProfileHint: judgeConfig.voiceProfileHint,
		costAttribution: judgeConfig.costAttribution,
		workspaceId,
		groupId,
	};

	const verdicts = await judgeBatch(candidates, judgeOpts);

	const survivors: FilterSurvivor[] = [];
	let rejectedCount = 0;
	let skippedCount = 0;
	const skippedReasons: Record<string, number> = {};
	const rejectionReasons: Record<string, number> = {};

	const dbClient = db();

	for (let i = 0; i < filterSurvivors.length; i++) {
		const survivor = filterSurvivors[i];
		const verdict = verdicts[i] as JudgeVerdict | undefined;

		// Missing or skipped while enabled → reject (fail-closed).
		if (!verdict || "skipped" in verdict) {
			skippedCount++;
			const reason =
				verdict && "skipped" in verdict ? verdict.reason : "missing_verdict";
			skippedReasons[reason] = (skippedReasons[reason] ?? 0) + 1;
			rejectedCount++;
			const rejectReason = `judge:${reason}`;
			rejectionReasons[rejectReason] =
				(rejectionReasons[rejectReason] || 0) + 1;
			try {
				await dbClient.from("auto_post_queue").insert({
					workspace_id: workspaceId,
					content: survivor!.idea.content,
					status: "rejected",
					rejection_reason: `${rejectReason} (fail_closed=true)`,
					source_type: "ai",
					scheduled_for: new Date().toISOString(),
					metadata: {
						judge: {
							skipped: true,
							reason,
							fail_closed: true,
						},
					},
					...(groupId ? { group_id: groupId } : {}),
				});
			} catch (err) {
				logger.debug(
					"[pipelineFilters] Judge fail-closed rejection insert failed (non-blocking)",
					{
						error: err instanceof Error ? err.message : String(err),
					},
				);
			}
			continue;
		}

		// Discriminated union narrowing: at this point verdict has `passed: boolean`.
		if (verdict.passed === true) {
			// Stamp judge result onto idea metadata so insertCandidates can
			// persist it on the queue row. The auto_post_queue.metadata
			// column is JSONB — `judge` is a stable namespace for this
			// feature so future eval tooling can replay decisions.
			(
				survivor!.idea as AIIdea & { judgeResult?: JudgeVerdict | undefined }
			).judgeResult = verdict;
			survivors.push(survivor!);
			continue;
		}

		// Failed verdict — has rejectReason / score / dimensions.
		const failed = verdict;
		rejectedCount++;
		const reason = `judge:${failed.rejectReason}`;
		rejectionReasons[reason] = (rejectionReasons[reason] || 0) + 1;

		try {
			await dbClient.from("auto_post_queue").insert({
				workspace_id: workspaceId,
				content: survivor!.idea.content,
				status: "rejected",
				rejection_reason: `${reason} (score=${failed.score})`,
				source_type: "ai",
				scheduled_for: new Date().toISOString(),
				metadata: {
					judge: {
						score: failed.score,
						dimensions: failed.dimensions,
						rationale: failed.rationale ?? null,
					},
				},
				...(groupId ? { group_id: groupId } : {}),
			});
		} catch (err) {
			logger.debug(
				"[pipelineFilters] Judge-rejection insert failed (non-blocking)",
				{
					error: err instanceof Error ? err.message : String(err),
				},
			);
		}
	}

	logger.info("[pipelineFilters] LLM judge phase complete", {
		input: filterSurvivors.length,
		passed: survivors.length,
		rejected: rejectedCount,
		skipped: skippedCount,
		threshold: judgeConfig.minScore,
		workspaceId,
		groupId,
	});

	if (skippedCount > 0) {
		await recordLLMJudgeSkips({
			workspaceId,
			groupId,
			accountIds: judgeConfig.accountIds,
			total: filterSurvivors.length,
			skipped: skippedCount,
			error: Object.entries(skippedReasons)
				.map(([reason, count]) => `${reason}:${count}`)
				.join(","),
		});
	}

	return { survivors, rejectedCount, rejectionReasons };
}

// ============================================================================
// Phase 2: Embedding Dedup
// ============================================================================

const DEDUP_CONCURRENCY = 3;

/**
 * Run Phase 2 dedup: semantic similarity + cross-group diversity checks.
 * Runs in batches to limit concurrent API calls.
 */
export async function runEmbeddingDedupPhase(
	filterSurvivors: FilterSurvivor[],
	maxInserts: number,
	recentPostContents: { recentContents: string[] },
	aiApiKey: string,
	workspaceId: string,
	groupId: string | undefined,
	fillStartTime: number,
): Promise<DedupPipelineResult> {
	const dedupedCandidates: FilterSurvivor[] = [];
	let rejectedCount = 0;
	const rejectionReasons: Record<string, number> = {};

	for (
		let batch = 0;
		batch < filterSurvivors.length;
		batch += DEDUP_CONCURRENCY
	) {
		// Budget guard for dedup phase
		if (Date.now() - fillStartTime > 100_000) {
			logger.warn("Fill budget exceeded 100s during dedup phase", {
				dedupedSoFar: dedupedCandidates.length,
				elapsed: Date.now() - fillStartTime,
			});
			break;
		}
		// Stop if we already have enough passing candidates
		if (dedupedCandidates.length >= maxInserts) break;

		const chunk = filterSurvivors.slice(batch, batch + DEDUP_CONCURRENCY);
		const results = await Promise.all(
			chunk.map(async (candidate) => {
				// Prefilter: banned phrases + pg_trgm near-duplicate check.
				// Cheap — runs BEFORE embedding API so trivial rejects don't
				// pay for a Gemini round-trip. Fail-open on errors.
				const prefilterResult = await runPrefilter(
					candidate.idea.content,
					workspaceId,
					isHighValueProfileCuriosityContent(candidate.idea.content) &&
						!isProfileCuriosityDeadEndContent(candidate.idea.content)
						? { trigramThreshold: 0.86 }
						: {},
				);
				if (!prefilterResult.passed) {
					return {
						candidate,
						rejected: true,
						reason: `prefilter:${prefilterResult.reason ?? "unknown"}`,
						rejectionDetail: `prefilter:${prefilterResult.reason ?? "unknown"}`,
					} as const;
				}

				// Semantic dedup — catches "same idea, different words" that trigram overlap misses.
				if (recentPostContents.recentContents.length >= 5) {
					const dedupResult = await checkSemanticDedup(
						candidate.idea.content,
						recentPostContents.recentContents,
						aiApiKey,
					);
					if (!dedupResult.passed) {
						return {
							candidate,
							rejected: true,
							reason: `semantic-dedup:${dedupResult.reason}`,
							rejectionDetail: `semantic-dedup:${dedupResult.reason} (sim=${dedupResult.maxSimilarity.toFixed(3)})`,
						} as const;
					}
				}

				// Cross-group diversity — DISABLED: this is a threads farm,
				// same content across groups is the strategy (recycling works).
				// Semantic dedup within the same group still runs above.

				return { candidate, rejected: false } as const;
			}),
		);

		// Process results — track rejections and collect survivors
		for (const result of results) {
			if (result.rejected) {
				const reason = result.reason;
				logger.info("Dedup phase rejected content", {
					contentPreview: result.candidate.idea.content.substring(0, 60),
					reason,
					workspaceId,
					groupId,
				});
				rejectedCount++;
				rejectionReasons[reason] = (rejectionReasons[reason] || 0) + 1;
				try {
					await db()
						.from("auto_post_queue")
						.insert({
							workspace_id: workspaceId,
							content: result.candidate.idea.content,
							status: "rejected",
							rejection_reason: result.rejectionDetail || reason,
							source_type: "ai",
							scheduled_for: new Date().toISOString(),
							...(groupId ? { group_id: groupId } : {}),
						});
				} catch {
					// Non-blocking — rejection tracking is best-effort
				}
			} else {
				dedupedCandidates.push(result.candidate);
			}
		}
	}

	return { candidates: dedupedCandidates, rejectedCount, rejectionReasons };
}
