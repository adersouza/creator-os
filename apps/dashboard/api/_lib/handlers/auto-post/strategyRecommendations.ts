import { logger } from "../../logger.js";
import { getSupabaseAny } from "../../supabase.js";
import { escapeForPrompt } from "../../promptUtils.js";
import { profileCuriosityPriorityScore } from "./performanceFirst.js";

export type StrategyRecommendationAction =
	| "increase"
	| "decrease"
	| "test"
	| "avoid";

export interface StrategyRecommendation {
	id?: string | undefined;
	workspace_id: string;
	group_id?: string | null | undefined;
	account_id?: string | null | undefined;
	pattern_type: string;
	pattern_value: string;
	recommendation: StrategyRecommendationAction;
	confidence: number;
	reason: string;
	metric_basis: Record<string, unknown>;
	expires_at: string;
	updated_at?: string | null | undefined;
}

export type StrategyBucket = "proven" | "exploration" | "weird" | "none";

export interface RankedPattern {
	key: string;
	count?: number | undefined;
	avg?: number | undefined;
	total?: number | undefined;
	gapPct?: number | undefined;
	competitorPct?: number | undefined;
	ourPct?: number | undefined;
}

export interface StrategyInput {
	workspaceId: string;
	groupId?: string | null | undefined;
	accountId?: string | null | undefined;
	days: number;
	now?: Date | undefined;
	best: {
		archetypesBy1hReplies?: RankedPattern[] | undefined;
		archetypesBy24hViews?: RankedPattern[] | undefined;
		hookTypesBy1hReplies?: RankedPattern[] | undefined;
		hookTypesBy24hViews?: RankedPattern[] | undefined;
		topicsBy24hViews?: RankedPattern[] | undefined;
		formatsBy24hViews?: RankedPattern[] | undefined;
		postingHoursBy24hViews?: RankedPattern[] | undefined;
	};
	worstRecurringPatterns?: RankedPattern[] | undefined;
	competitorPatternsWeUnderuse?: {
		archetypes?: RankedPattern[] | undefined;
		hooks?: RankedPattern[] | undefined;
		topics?: RankedPattern[] | undefined;
		formats?: RankedPattern[] | undefined;
	} | undefined;
	competitorPatternsWeOveruse?: {
		archetypes?: RankedPattern[] | undefined;
		hooks?: RankedPattern[] | undefined;
		topics?: RankedPattern[] | undefined;
		formats?: RankedPattern[] | undefined;
	} | undefined;
}

const db = () => getSupabaseAny();

function confidenceFromPattern(pattern: RankedPattern, base: number): number {
	const countBoost = Math.min(0.2, Math.max(0, (pattern.count || 0) / 50));
	const avgBoost = Math.min(0.15, Math.max(0, (pattern.avg || 0) / 1000));
	const gapBoost = Math.min(0.15, Math.max(0, Math.abs(pattern.gapPct || 0) / 100));
	return Math.round(Math.min(0.95, base + countBoost + avgBoost + gapBoost) * 100) / 100;
}

function pushRecommendation(
	rows: StrategyRecommendation[],
	input: StrategyInput,
	patternType: string,
	pattern: RankedPattern,
	recommendation: StrategyRecommendationAction,
	reason: string,
	baseConfidence: number,
	expiresAt: string,
) {
	if (!pattern.key || pattern.key === "unknown") return;
	rows.push({
		workspace_id: input.workspaceId,
		group_id: input.groupId || null,
		account_id: input.accountId || null,
		pattern_type: patternType,
		pattern_value: pattern.key,
		recommendation,
		confidence: confidenceFromPattern(pattern, baseConfidence),
		reason,
		metric_basis: {
			days: input.days,
			count: pattern.count ?? null,
			avg: pattern.avg ?? null,
			total: pattern.total ?? null,
			gapPct: pattern.gapPct ?? null,
			competitorPct: pattern.competitorPct ?? null,
			ourPct: pattern.ourPct ?? null,
		},
		expires_at: expiresAt,
	});
}

export function buildStrategyRecommendations(
	input: StrategyInput,
): StrategyRecommendation[] {
	const now = input.now || new Date();
	const expiresAt = new Date(now.getTime() + 7 * 86_400_000).toISOString();
	const rows: StrategyRecommendation[] = [];

	for (const pattern of (input.best.archetypesBy1hReplies || []).slice(0, 3)) {
		pushRecommendation(
			rows,
			input,
			"content_archetype",
			pattern,
			"increase",
			"content_archetype_drives_1h_replies",
			0.66,
			expiresAt,
		);
	}
	for (const pattern of (input.best.archetypesBy24hViews || []).slice(0, 3)) {
		pushRecommendation(
			rows,
			input,
			"content_archetype",
			pattern,
			"increase",
			"content_archetype_drives_24h_views",
			0.68,
			expiresAt,
		);
	}
	for (const pattern of (input.best.hookTypesBy1hReplies || []).slice(0, 3)) {
		pushRecommendation(
			rows,
			input,
			"hook_type",
			pattern,
			"increase",
			"strong_1h_reply_response",
			0.62,
			expiresAt,
		);
	}
	for (const pattern of (input.best.hookTypesBy24hViews || []).slice(0, 3)) {
		pushRecommendation(
			rows,
			input,
			"hook_type",
			pattern,
			"increase",
			"strong_24h_view_response",
			0.64,
			expiresAt,
		);
	}
	for (const pattern of (input.best.topicsBy24hViews || []).slice(0, 4)) {
		pushRecommendation(
			rows,
			input,
			"topic_label",
			pattern,
			"increase",
			"topic_outperforms_on_24h_views",
			0.58,
			expiresAt,
		);
	}
	for (const pattern of (input.best.formatsBy24hViews || []).slice(0, 3)) {
		pushRecommendation(
			rows,
			input,
			"format_type",
			pattern,
			"increase",
			"format_outperforms_on_24h_views",
			0.58,
			expiresAt,
		);
	}
	for (const pattern of (input.best.postingHoursBy24hViews || []).slice(0, 3)) {
		pushRecommendation(
			rows,
			input,
			"posting_hour",
			pattern,
			"increase",
			"posting_hour_outperforms_on_24h_views",
			0.55,
			expiresAt,
		);
	}

	for (const pattern of (input.worstRecurringPatterns || []).slice(0, 4)) {
		pushRecommendation(
			rows,
			input,
			"hook_type",
			pattern,
			pattern.avg === 0 ? "avoid" : "decrease",
			"recurring_pattern_underperforms",
			0.6,
			expiresAt,
		);
	}

	for (const pattern of (input.competitorPatternsWeUnderuse?.hooks || []).slice(0, 3)) {
		pushRecommendation(
			rows,
			input,
			"hook_type",
			pattern,
			"test",
			"competitor_corpus_pattern_underused_by_us",
			0.48,
			expiresAt,
		);
	}
	for (const pattern of (input.competitorPatternsWeUnderuse?.archetypes || []).slice(0, 3)) {
		pushRecommendation(
			rows,
			input,
			"content_archetype",
			pattern,
			"test",
			"competitor_corpus_archetype_underused_by_us",
			0.5,
			expiresAt,
		);
	}
	for (const pattern of (input.competitorPatternsWeUnderuse?.topics || []).slice(0, 3)) {
		pushRecommendation(
			rows,
			input,
			"topic_label",
			pattern,
			"test",
			"competitor_corpus_topic_underused_by_us",
			0.45,
			expiresAt,
		);
	}
	for (const pattern of (input.competitorPatternsWeUnderuse?.formats || []).slice(0, 2)) {
		pushRecommendation(
			rows,
			input,
			"format_type",
			pattern,
			"test",
			"competitor_corpus_format_underused_by_us",
			0.45,
			expiresAt,
		);
	}

	for (const pattern of (input.competitorPatternsWeOveruse?.hooks || []).slice(0, 3)) {
		pushRecommendation(
			rows,
			input,
			"hook_type",
			pattern,
			"decrease",
			"pattern_overused_versus_competitor_corpus",
			0.42,
			expiresAt,
		);
	}
	for (const pattern of (input.competitorPatternsWeOveruse?.archetypes || []).slice(0, 3)) {
		pushRecommendation(
			rows,
			input,
			"content_archetype",
			pattern,
			"decrease",
			"content_archetype_overused_versus_competitor_corpus",
			0.48,
			expiresAt,
		);
	}

	const byKey = new Map<string, StrategyRecommendation>();
	for (const row of rows) {
		const key = `${row.pattern_type}:${row.pattern_value}:${row.recommendation}`;
		const existing = byKey.get(key);
		if (!existing || row.confidence > existing.confidence) byKey.set(key, row);
	}
	return [...byKey.values()].sort((a, b) => b.confidence - a.confidence);
}

export function activeStrategyRecommendations(
	recommendations: StrategyRecommendation[],
	now = new Date(),
	minConfidence = 0.35,
): StrategyRecommendation[] {
	return recommendations
		.filter((rec) => new Date(rec.expires_at).getTime() > now.getTime())
		.filter((rec) => rec.confidence >= minConfidence)
		.sort((a, b) => b.confidence - a.confidence);
}

function recommendationScopeRank(
	recommendation: StrategyRecommendation,
	groupId?: string | null | undefined,
	accountIds?: string[] | undefined,
): number {
	if (recommendation.account_id && accountIds?.includes(recommendation.account_id))
		return 3;
	if (groupId && recommendation.group_id === groupId) return 2;
	if (!groupId && !recommendation.account_id) return 1;
	if (!recommendation.account_id && !recommendation.group_id) return 1;
	return 0;
}

function recommendationFreshnessRank(
	recommendation: StrategyRecommendation,
	now: Date,
): number {
	if (!recommendation.updated_at) return 0;
	const ageMs = now.getTime() - new Date(recommendation.updated_at).getTime();
	if (!Number.isFinite(ageMs) || ageMs < 0) return 0;
	if (ageMs <= 24 * 60 * 60 * 1000) return 2;
	if (ageMs <= 72 * 60 * 60 * 1000) return 1;
	return 0;
}

function recommendationPatternRank(recommendation: StrategyRecommendation): number {
	if (recommendation.pattern_type === "winner_clone") return 2;
	if (recommendation.recommendation === "increase") return 1;
	return 0;
}

function recommendationHasPerformanceEvidence(
	recommendation: StrategyRecommendation,
): boolean {
	const basis = recommendation.metric_basis ?? {};
	return Boolean(
		(basis.sourcePostId || basis.sourcePatternId) &&
			basis.performanceBasis &&
			(Number(basis.views24h) > 0 || Number(basis.replies1h) > 0),
	);
}

function recommendationIsCompetitorBacked(
	recommendation: StrategyRecommendation,
): boolean {
	const sourceType = String(recommendation.metric_basis?.sourceType ?? "");
	return (
		(sourceType === "competitor_copy" ||
			sourceType === "competitor_direct" ||
			sourceType === "competitor_direct_microcopy") &&
		recommendationHasPerformanceEvidence(recommendation)
	);
}

function recommendationPerformanceRank(
	recommendation: StrategyRecommendation,
): number {
	const basis = recommendation.metric_basis ?? {};
	const views24h = Number(basis.views24h) || 0;
	const replies1h = Number(basis.replies1h) || 0;
	const sourceText =
		typeof basis.sourceText === "string" ? basis.sourceText : "";
	const profileCuriosityScore = profileCuriosityPriorityScore(sourceText);
	const evidenceBonus = recommendationHasPerformanceEvidence(recommendation)
		? 10
		: 0;
	const competitorBonus =
		recommendation.pattern_type === "winner_clone" &&
		recommendationIsCompetitorBacked(recommendation)
			? 8
			: 0;
	return (
		recommendation.confidence * 100 +
		Math.min(25, views24h / 12) +
		Math.min(10, replies1h * 2) +
		profileCuriosityScore +
		evidenceBonus +
		competitorBonus
	);
}

export function prioritizeStrategyRecommendations(
	recommendations: StrategyRecommendation[],
	options: {
		groupId?: string | null | undefined;
		accountIds?: string[] | undefined;
		now?: Date | undefined;
		minConfidence?: number | undefined;
	} = {},
): StrategyRecommendation[] {
	const now = options.now || new Date();
	return activeStrategyRecommendations(
		recommendations,
		now,
		options.minConfidence ?? 0.35,
	).sort((a, b) => {
		const scopeDelta =
			recommendationScopeRank(b, options.groupId, options.accountIds) -
			recommendationScopeRank(a, options.groupId, options.accountIds);
		if (scopeDelta !== 0) return scopeDelta;

		const patternDelta =
			recommendationPatternRank(b) - recommendationPatternRank(a);
		if (patternDelta !== 0) return patternDelta;

		const freshnessDelta =
			recommendationFreshnessRank(b, now) - recommendationFreshnessRank(a, now);
		if (freshnessDelta !== 0) return freshnessDelta;

		const performanceDelta =
			recommendationPerformanceRank(b) - recommendationPerformanceRank(a);
		if (performanceDelta !== 0) return performanceDelta;

		return b.confidence - a.confidence;
	});
}

export function generationMixFromRecommendations(
	recommendations: StrategyRecommendation[],
	now = new Date(),
) {
	const active = prioritizeStrategyRecommendations(recommendations, { now });
	const provenWinners = active.filter(
		(rec) =>
			(rec.pattern_type === "winner_clone" ||
				rec.recommendation === "increase") &&
			rec.confidence >= 0.55,
	);
	const exploration = active.filter(
		(rec) =>
			(rec.pattern_type === "source_type" &&
				rec.pattern_value.includes("competitor")) ||
			rec.recommendation === "test" ||
			(rec.recommendation === "increase" &&
				rec.pattern_type !== "winner_clone" &&
				rec.confidence < 0.55),
	);
	const reduce = active.filter(
		(rec) => rec.recommendation === "decrease" || rec.recommendation === "avoid",
	);
	return {
		provenWinners,
		exploration,
		reduce,
		randomnessShare: 0.1,
		provenShare: 0.7,
		explorationShare: 0.2,
	};
}

export function bucketForRecommendation(
	recommendation?: StrategyRecommendation | null,
): StrategyBucket {
	if (!recommendation) return "none";
	if (
		recommendation.recommendation === "increase" &&
		recommendation.confidence >= 0.55
	) {
		return "proven";
	}
	if (
		recommendation.recommendation === "test" ||
		recommendation.recommendation === "increase"
	) {
		return "exploration";
	}
	return "none";
}

export function matchStrategyRecommendation(
	attribution: {
		hook_type?: string | null | undefined;
		topic_label?: string | null | undefined;
		format_type?: string | null | undefined;
		emotional_frame?: string | null | undefined;
		reply_mechanism?: string | null | undefined;
		content_length_bucket?: string | null | undefined;
		media_style?: string | null | undefined;
		posting_hour?: number | null | undefined;
		content_archetype?: string | null | undefined;
	},
	recommendations: StrategyRecommendation[],
): { recommendation: StrategyRecommendation | null; bucket: StrategyBucket } {
	const active = prioritizeStrategyRecommendations(recommendations);
	const candidates = active
		.filter((rec) => rec.recommendation === "increase" || rec.recommendation === "test")
		.filter((rec) => {
			const value = attribution[rec.pattern_type as keyof typeof attribution];
			return String(value ?? "") === rec.pattern_value;
		})
		.sort((a, b) => b.confidence - a.confidence);
	const recommendation = candidates[0] || null;
	const bucket = recommendation
		? bucketForRecommendation(recommendation)
		: active.length > 0
			? "weird"
			: "none";
	return { recommendation, bucket };
}

export interface RecommendationOutcomePost {
	strategy_recommendation_id?: string | null | undefined;
	viewsAt24h: number;
}

export function evaluateRecommendationOutcomes(
	posts: RecommendationOutcomePost[],
	baselineViewsAt24h: number,
	now = new Date(),
	minSamples = 3,
) {
	const byRecommendation = new Map<
		string,
		{ sampleCount: number; belowBaselineCount: number; avgViewsAt24h: number }
	>();
	for (const post of posts) {
		if (!post.strategy_recommendation_id) continue;
		const current = byRecommendation.get(post.strategy_recommendation_id) || {
			sampleCount: 0,
			belowBaselineCount: 0,
			avgViewsAt24h: 0,
		};
		current.sampleCount++;
		current.avgViewsAt24h += post.viewsAt24h;
		if (post.viewsAt24h < baselineViewsAt24h) current.belowBaselineCount++;
		byRecommendation.set(post.strategy_recommendation_id, current);
	}

	return [...byRecommendation.entries()]
		.map(([id, outcome]) => ({
			id,
			sampleCount: outcome.sampleCount,
			belowBaselineCount: outcome.belowBaselineCount,
			avgViewsAt24h:
				Math.round((outcome.avgViewsAt24h / Math.max(1, outcome.sampleCount)) * 100) /
				100,
			shouldExpire:
				outcome.sampleCount >= minSamples &&
				outcome.belowBaselineCount >= minSamples,
			evaluatedAt: now.toISOString(),
		}))
		.filter((outcome) => outcome.sampleCount > 0);
}

export function formatStrategyRecommendationsForPrompt(
	recommendations: StrategyRecommendation[],
	now = new Date(),
): string {
	const mix = generationMixFromRecommendations(recommendations, now);
	if (
		mix.provenWinners.length === 0 &&
		mix.exploration.length === 0 &&
		mix.reduce.length === 0
	) {
		return "";
	}

	const line = (rec: StrategyRecommendation) => {
		if (rec.pattern_type !== "winner_clone") {
			return `- ${rec.recommendation} ${rec.pattern_type}=${escapeForPrompt(rec.pattern_value)} (confidence ${Math.round(rec.confidence * 100)}%; ${escapeForPrompt(rec.reason)})`;
		}
		const basis = rec.metric_basis || {};
		const sourceText = String(basis.sourceText || rec.pattern_value);
		const cloneFamily = String(basis.cloneFamily || "unknown");
		const frame = String(basis.profileCuriosityFrame || "unknown");
		const mechanism = String(basis.curiosityMechanism || "unknown");
		const clonePrompt = String(basis.clonePrompt || "");
		return `- clone winner "${escapeForPrompt(sourceText)}" (confidence ${Math.round(rec.confidence * 100)}%; ${escapeForPrompt(rec.reason)}; cloneFamily=${escapeForPrompt(cloneFamily)}; frame=${escapeForPrompt(frame)}; mechanism=${escapeForPrompt(mechanism)}; MUST preserve this frame/mechanism, not just the topic.${clonePrompt ? ` ${escapeForPrompt(clonePrompt)}` : ""})`;
	};

	return `\n== PERFORMANCE-FIRST AUTOPUBLISHER STRATEGY ==\nOptimize for measured 24h views first, then post-attributable clicks and revenue when available. Creator fit is a soft validation signal; do not reject a high-upside pattern just because sibling accounts sound similar.\n\nGENERATION MIX FOR THIS BATCH:\n- 70% proven winners / winner clones: generate variations from our measured winning posts and high-view patterns.\n- 20% exploration / competitor-direct market patterns: use direct or competitor-style patterns when allowed and performance-backed.\n- 10% weird/off-pattern human randomness: try new shapes, but keep them specific and measurable.\n\nPROVEN WINNERS / CLONE TARGETS:\n${mix.provenWinners.slice(0, 10).map(line).join("\n") || "- none"}\n\nMARKET / DIRECT TESTS:\n${mix.exploration.slice(0, 8).map(line).join("\n") || "- none"}\n\nPATTERNS OR ACCOUNTS TO REDUCE:\n${mix.reduce.slice(0, 8).map(line).join("\n") || "- none"}\n`;
}

export async function loadActiveStrategyRecommendations(params: {
	workspaceId: string;
	groupId?: string | null | undefined;
	accountIds?: string[] | undefined;
	limit?: number | undefined;
}): Promise<StrategyRecommendation[]> {
	try {
		let query = db()
			.from("autoposter_strategy_recommendations")
			.select(
				"id, workspace_id, group_id, account_id, pattern_type, pattern_value, recommendation, confidence, reason, metric_basis, expires_at, updated_at",
			)
			.eq("workspace_id", params.workspaceId)
			.gt("expires_at", new Date().toISOString())
			.gte("confidence", 0.35)
			.order("confidence", { ascending: false })
			.limit(Math.max(params.limit ?? 40, 120));
		if (params.groupId) {
			query = query.or(`group_id.eq.${params.groupId},group_id.is.null`);
		}
		const { data, error } = await query;
		if (error) throw error;
		const rows = ((data || []) as StrategyRecommendation[]).filter((row) => {
			if (!row.account_id) return true;
			return !!params.accountIds?.includes(row.account_id);
		});
		return prioritizeStrategyRecommendations(rows, {
			groupId: params.groupId,
			accountIds: params.accountIds,
		}).slice(0, params.limit ?? 40);
	} catch (err) {
		logger.warn("[strategyRecommendations] Failed to load active recommendations", {
			workspaceId: params.workspaceId,
			groupId: params.groupId,
			error: err instanceof Error ? err.message : String(err),
		});
		return [];
	}
}

export async function replaceStrategyRecommendations(
	_scope: {
		workspaceId: string;
		groupId?: string | null | undefined;
		accountId?: string | null | undefined;
	},
	recommendations: StrategyRecommendation[],
): Promise<void> {
	if (recommendations.length === 0) return;
	const client = db();
	for (const recommendation of recommendations) {
		let existingQuery = client
			.from("autoposter_strategy_recommendations")
			.select("id")
			.eq("workspace_id", recommendation.workspace_id)
			.eq("pattern_type", recommendation.pattern_type)
			.eq("pattern_value", recommendation.pattern_value)
			.eq("recommendation", recommendation.recommendation)
			.limit(1);
		existingQuery = recommendation.group_id
			? existingQuery.eq("group_id", recommendation.group_id)
			: existingQuery.is("group_id", null);
		existingQuery = recommendation.account_id
			? existingQuery.eq("account_id", recommendation.account_id)
			: existingQuery.is("account_id", null);
		const { data: existing, error: lookupError } = await existingQuery.maybeSingle();
		if (lookupError) throw lookupError;
		if (existing?.id) {
			const { error } = await client
				.from("autoposter_strategy_recommendations")
				.update({
					confidence: recommendation.confidence,
					reason: recommendation.reason,
					metric_basis: recommendation.metric_basis,
					expires_at: recommendation.expires_at,
				})
				.eq("id", existing.id);
			if (error) throw error;
		} else {
			const { error } = await client
				.from("autoposter_strategy_recommendations")
				.insert(recommendation);
			if (error) throw error;
		}
	}
}

export async function expireUnderperformingRecommendations(
	outcomes: Array<{
		id: string;
		sampleCount: number;
		belowBaselineCount: number;
		avgViewsAt24h: number;
		shouldExpire: boolean;
		evaluatedAt: string;
	}>,
): Promise<void> {
	const expiring = outcomes.filter((outcome) => outcome.shouldExpire);
	if (expiring.length === 0) return;
	const client = db();
	for (const outcome of expiring) {
		const { error } = await client
			.from("autoposter_strategy_recommendations")
			.update({
				expires_at: outcome.evaluatedAt,
				confidence: 0.1,
				outcome_sample_count: outcome.sampleCount,
				below_baseline_count: outcome.belowBaselineCount,
				last_outcome_checked_at: outcome.evaluatedAt,
				downgraded_at: outcome.evaluatedAt,
				expired_early_at: outcome.evaluatedAt,
				metric_basis: {
					autoExpired: true,
					reason: "below_baseline_repeatedly",
					sampleCount: outcome.sampleCount,
					belowBaselineCount: outcome.belowBaselineCount,
					avgViewsAt24h: outcome.avgViewsAt24h,
					evaluatedAt: outcome.evaluatedAt,
				},
			})
			.eq("id", outcome.id);
		if (error) {
			logger.warn("[strategyRecommendations] Failed to expire recommendation", {
				recommendationId: outcome.id,
				error: error.message,
			});
		}
	}
}
