import type { FilterResult } from "./contentFilter.js";
import { resolveFilterConfig, filterContent } from "./contentFilter.js";
import { scoreContent, type ContentScore } from "./contentScorer.js";

export type AIQualityGateDecision = "pass" | "needs_review" | "block";

export interface AIQualityConfidenceFields {
	qualityConfidence: number;
	brandConfidence: number;
	noveltyConfidence: number;
	riskConfidence: number;
	expectedOutcomeConfidence: number;
}

export interface AIQualityGateResult {
	decision: AIQualityGateDecision;
	reason: string;
	lane?: "standard" | "performance_backed_clone" | undefined;
	laneReason?: string | undefined;
	performanceEvidence?: AIQualityGatePerformanceEvidence | undefined;
	confidences: AIQualityConfidenceFields;
	flags: string[];
	score: {
		replyTrigger: number;
		emotionalWarmth: number;
		overall: number;
		rejectReason: string | null;
	};
}

export interface AIQualityGatePerformanceEvidence {
	sourcePatternId?: string | null | undefined;
	winnerPatternId?: string | null | undefined;
	strategyRecommendationId?: string | null | undefined;
	cloneFamily?: string | null | undefined;
	patternType?: string | null | undefined;
	strategyBucket?: string | null | undefined;
	confidence?: number | null | undefined;
	performanceBasis?: string | null | undefined;
	isGenericBait?: boolean | null | undefined;
	isDirectLongCopy?: boolean | null | undefined;
	isProfileDeadEnd?: boolean | null | undefined;
	isFrameMismatch?: boolean | null | undefined;
	sourceHasTaxonomyLeak?: boolean | null | undefined;
	frameAlignmentScore?: number | null | undefined;
}

export interface EvaluateAIQualityGateInput {
	content: string;
	sourceType?: "ai" | "winner_clone" | "competitor_copy" | "competitor_direct" | "competitor_direct_microcopy" | "manual" | string;
	sourceContent?: string | null;
	sourceCompetitorId?: string | null;
	viralScore?: number | null;
	filterResult?: FilterResult | null;
	contentScore?: ContentScore | null;
	avoidWords?: string[];
	performanceEvidence?: AIQualityGatePerformanceEvidence | null | undefined;
}

function clampConfidence(value: number): number {
	if (!Number.isFinite(value)) return 0;
	return Math.max(0, Math.min(1, Math.round(value * 100) / 100));
}

function confidenceFromViralScore(viralScore: number | null | undefined): number {
	if (typeof viralScore !== "number" || !Number.isFinite(viralScore)) return 0.55;
	return clampConfidence(viralScore / 100);
}

function flagsFromFilter(filterResult: FilterResult | null): string[] {
	return (filterResult?.flags ?? []).map((flag) => `${flag.pattern}:${flag.severity}`);
}

function hasMediumOrHighFilterFlag(filterResult: FilterResult | null): boolean {
	return (filterResult?.flags ?? []).some(
		(flag) => flag.severity === "medium" || flag.severity === "high",
	);
}

function parseFlag(flag: string): { pattern: string; severity: string } {
	const idx = flag.lastIndexOf(":");
	if (idx <= 0) return { pattern: flag, severity: "unknown" };
	return {
		pattern: flag.slice(0, idx),
		severity: flag.slice(idx + 1),
	};
}

function isHarmlessStyleFlag(flag: string): boolean {
	const parsed = parseFlag(flag);
	if (parsed.severity === "low") return true;
	if (parsed.severity !== "medium") return false;
	return (
		parsed.pattern === "ai-complex-vocabulary" ||
		parsed.pattern === "structural-semicolon" ||
		parsed.pattern === "structural-em-dash" ||
		parsed.pattern === "structural-multi-paragraph"
	);
}

function hasHighRiskFlag(flags: string[]): boolean {
	return flags.some((flag) => {
		const parsed = parseFlag(flag);
		if (parsed.severity === "high") return true;
		return !isHarmlessStyleFlag(flag);
	});
}

function hasPerformanceEvidence(
	evidence: AIQualityGatePerformanceEvidence | null | undefined,
): boolean {
	if (!evidence) return false;
	return Boolean(
		evidence.patternType === "winner_clone" ||
			evidence.strategyBucket === "proven" ||
			evidence.winnerPatternId ||
			evidence.cloneFamily ||
			evidence.performanceBasis,
	);
}

function sourceAllowsPerformanceLane(sourceType: string): boolean {
	return [
		"ai",
		"winner_clone",
		"competitor_copy",
		"competitor_direct_microcopy",
	].includes(sourceType);
}

export function applyPerformanceBackedQualityGateLane(
	result: AIQualityGateResult,
	input: Pick<
		EvaluateAIQualityGateInput,
		"sourceType" | "sourceContent" | "sourceCompetitorId" | "viralScore" | "performanceEvidence"
	>,
): AIQualityGateResult {
	const sourceType = input.sourceType ?? "ai";
	const evidence = input.performanceEvidence ?? null;
	if (result.decision !== "needs_review") return result;
	if (!sourceAllowsPerformanceLane(sourceType)) return result;
	if (!hasPerformanceEvidence(evidence)) return result;
	if (evidence?.isGenericBait) return result;
	if (evidence?.isDirectLongCopy) return result;
	if (evidence?.isProfileDeadEnd) return result;
	if (evidence?.isFrameMismatch) return result;
	if (evidence?.sourceHasTaxonomyLeak) return result;
	if (hasHighRiskFlag(result.flags)) return result;
	if (
		![
			"policy:competitor_inspired_content",
			"confidence:uncertain_content",
			"filter:soft_flags",
		].includes(result.reason)
	) {
		return result;
	}
	const viralConfidence = confidenceFromViralScore(input.viralScore);
	const evidenceConfidence =
		typeof evidence?.confidence === "number" && Number.isFinite(evidence.confidence)
			? clampConfidence(evidence.confidence)
			: 0;
	const hasStrongEvidence =
		viralConfidence >= 0.85 ||
		evidenceConfidence >= 0.7 ||
		evidence?.strategyBucket === "proven" ||
		evidence?.patternType === "winner_clone";
	if (!hasStrongEvidence) return result;

	return {
		...result,
		decision: "pass",
		reason: "winner_clone_performance_evidence",
		lane: "performance_backed_clone",
		laneReason: "winner_clone_performance_evidence",
		performanceEvidence: {
			sourcePatternId: evidence?.sourcePatternId ?? null,
			winnerPatternId: evidence?.winnerPatternId ?? null,
			strategyRecommendationId: evidence?.strategyRecommendationId ?? null,
			cloneFamily: evidence?.cloneFamily ?? null,
			patternType: evidence?.patternType ?? null,
			strategyBucket: evidence?.strategyBucket ?? null,
			confidence: evidenceConfidence || null,
			performanceBasis: evidence?.performanceBasis ?? null,
			isGenericBait: Boolean(evidence?.isGenericBait),
			isDirectLongCopy: Boolean(evidence?.isDirectLongCopy),
			isProfileDeadEnd: Boolean(evidence?.isProfileDeadEnd),
			isFrameMismatch: Boolean(evidence?.isFrameMismatch),
			sourceHasTaxonomyLeak: Boolean(evidence?.sourceHasTaxonomyLeak),
			frameAlignmentScore:
				typeof evidence?.frameAlignmentScore === "number"
					? evidence.frameAlignmentScore
					: null,
		},
	};
}

export function evaluateAIQualityGate(
	input: EvaluateAIQualityGateInput,
): AIQualityGateResult {
	const sourceType = input.sourceType ?? "ai";
	const sourceContent = input.sourceContent ?? null;
	const filterResult =
		input.filterResult ??
		filterContent(
			input.content,
			resolveFilterConfig(null, null, null),
			sourceType,
			undefined,
			input.avoidWords,
		);
	const score = input.contentScore ?? scoreContent(input.content, sourceContent);
	const flags = flagsFromFilter(filterResult);
	const viralConfidence = confidenceFromViralScore(input.viralScore);
	const qualityConfidence = clampConfidence(score.overall / 5);
	const brandConfidence = clampConfidence(
		filterResult.passed ? (hasMediumOrHighFilterFlag(filterResult) ? 0.55 : 0.86) : 0.08,
	);
	const noveltyConfidence = clampConfidence(
		sourceContent || input.sourceCompetitorId
			? score.rejectReason?.startsWith("originality_")
				? 0.15
				: 0.68
			: 0.84,
	);
	const riskConfidence = clampConfidence(
		filterResult.passed ? (flags.length > 0 ? 0.58 : 0.9) : 0.05,
	);
	const expectedOutcomeConfidence = clampConfidence(
		viralConfidence * 0.7 + qualityConfidence * 0.3,
	);
	const confidences = {
		qualityConfidence,
		brandConfidence,
		noveltyConfidence,
		riskConfidence,
		expectedOutcomeConfidence,
	};

	if (!filterResult.passed) {
		return {
			decision: "block",
			reason: `filter:${filterResult.reason ?? "failed"}`,
			confidences,
			flags,
			score: {
				replyTrigger: score.replyTrigger,
				emotionalWarmth: score.emotionalWarmth,
				overall: score.overall,
				rejectReason: score.rejectReason ?? null,
			},
		};
	}

	if (!score.passed) {
		const rejectReason = score.rejectReason ?? "low_score";
		const decision = rejectReason.startsWith("originality_") ? "block" : "needs_review";
		return applyPerformanceBackedQualityGateLane({
			decision,
			reason: `scorer:${rejectReason}`,
			confidences,
			flags,
			score: {
				replyTrigger: score.replyTrigger,
				emotionalWarmth: score.emotionalWarmth,
				overall: score.overall,
				rejectReason,
			},
		}, input);
	}

	if (hasMediumOrHighFilterFlag(filterResult)) {
		return applyPerformanceBackedQualityGateLane({
			decision: "needs_review",
			reason: "filter:soft_flags",
			confidences,
			flags,
			score: {
				replyTrigger: score.replyTrigger,
				emotionalWarmth: score.emotionalWarmth,
				overall: score.overall,
				rejectReason: null,
			},
		}, input);
	}

	if (input.sourceCompetitorId || sourceContent) {
		return applyPerformanceBackedQualityGateLane({
			decision: "needs_review",
			reason: "policy:competitor_inspired_content",
			confidences,
			flags,
			score: {
				replyTrigger: score.replyTrigger,
				emotionalWarmth: score.emotionalWarmth,
				overall: score.overall,
				rejectReason: null,
			},
		}, input);
	}

	if (score.overall < 2.2 || score.replyTrigger <= 1 || viralConfidence < 0.7) {
		return applyPerformanceBackedQualityGateLane({
			decision: "needs_review",
			reason: "confidence:uncertain_content",
			confidences,
			flags,
			score: {
				replyTrigger: score.replyTrigger,
				emotionalWarmth: score.emotionalWarmth,
				overall: score.overall,
				rejectReason: null,
			},
		}, input);
	}

	return {
		decision: "pass",
		reason: "quality_gate_passed",
		confidences,
		flags,
		score: {
			replyTrigger: score.replyTrigger,
			emotionalWarmth: score.emotionalWarmth,
			overall: score.overall,
			rejectReason: null,
		},
	};
}
