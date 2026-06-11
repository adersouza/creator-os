import { describe, expect, it, vi } from "vitest";

vi.mock("../../api/_lib/logger.js", () => ({
	logger: { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

import { evaluateAIQualityGate } from "../../api/_lib/handlers/auto-post/qualityGate";

describe("AI quality gate", () => {
	it("blocks unsafe content before queueing or execution", () => {
		const result = evaluateAIQualityGate({
			content: "send nudes right now",
			viralScore: 95,
		});

		expect(result.decision).toBe("block");
		expect(result.reason).toBe("filter:safety-blacklist");
		expect(result.confidences.riskConfidence).toBeLessThan(0.2);
	});

	it("routes uncertain generated content to review", () => {
		const result = evaluateAIQualityGate({
			content: "be honest, would you answer a 2am text from your ex?",
			viralScore: 62,
		});

		expect(result.decision).toBe("needs_review");
		expect(result.reason).toBe("confidence:uncertain_content");
		expect(result.confidences.expectedOutcomeConfidence).toBeLessThan(0.7);
	});

	it("routes competitor-inspired content to review even when original enough", () => {
		const result = evaluateAIQualityGate({
			content: "what if monday mornings came with a refund policy?",
			sourceCompetitorId: "comp-1",
			sourceContent: "productivity tips for founders scaling a company",
			viralScore: 88,
		});

		expect(result.decision).toBe("needs_review");
		expect(result.reason).toBe("policy:competitor_inspired_content");
		expect(result.confidences.noveltyConfidence).toBeGreaterThan(0.5);
	});

	it("passes competitor-inspired winner clones through the performance-backed lane", () => {
		const result = evaluateAIQualityGate({
			content: "i'm a 9 but my taste in anime is unhinged. based",
			sourceCompetitorId: "comp-1",
			sourceContent: "i'm a 9 but my taste in anime is unhinged. based",
			viralScore: 91,
			performanceEvidence: {
				patternType: "winner_clone",
				cloneFamily: "rating_but_niche_unhinged",
				strategyBucket: "proven",
				confidence: 0.82,
			},
		});

		expect(result.decision).toBe("pass");
		expect(result.reason).toBe("winner_clone_performance_evidence");
		expect(result.lane).toBe("performance_backed_clone");
		expect(result.performanceEvidence?.cloneFamily).toBe(
			"rating_but_niche_unhinged",
		);
	});

	it("keeps competitor-inspired non-winners in review", () => {
		const result = evaluateAIQualityGate({
			content: "what if monday mornings came with a refund policy?",
			sourceCompetitorId: "comp-1",
			sourceContent: "productivity tips for founders scaling a company",
			viralScore: 88,
		});

		expect(result.decision).toBe("needs_review");
		expect(result.reason).toBe("policy:competitor_inspired_content");
		expect(result.lane).toBeUndefined();
	});

	it("does not let generic bait use the performance-backed lane", () => {
		const result = evaluateAIQualityGate({
			content: "who's up rn?",
			sourceCompetitorId: "comp-1",
			sourceContent: "who's up rn?",
			viralScore: 95,
			performanceEvidence: {
				patternType: "winner_clone",
				strategyBucket: "proven",
				confidence: 0.9,
				isGenericBait: true,
			},
		});

		expect(result.decision).toBe("needs_review");
		expect(result.lane).toBeUndefined();
	});

	it("does not let frame-mismatched winner clones use the performance-backed lane", () => {
		const result = evaluateAIQualityGate({
			content: "what's the one manga panel that lives rent free in your head?",
			sourceContent:
				"i'm single. i don't need your money. i don't smoke. i'm not a bad person. i can cook",
			viralScore: 92,
			performanceEvidence: {
				patternType: "winner_clone",
				strategyBucket: "proven",
				cloneFamily: "single_cook_clean_identity",
				confidence: 0.9,
				isFrameMismatch: true,
				frameAlignmentScore: -90,
			},
		});

		expect(result.decision).toBe("needs_review");
		expect(result.lane).toBeUndefined();
	});

	it("does not let taxonomy-leaked source winners use the performance-backed lane", () => {
		const result = evaluateAIQualityGate({
			content: "what comfort song is carrying your week?",
			sourceContent: "specific topical question: what's your go-to sad girl anthem??",
			viralScore: 92,
			contentScore: {
				passed: true,
				replyTrigger: 5,
				emotionalWarmth: 4,
				overall: 2.6,
			} as any,
			performanceEvidence: {
				patternType: "winner_clone",
				strategyBucket: "proven",
				cloneFamily: "vulnerability_winner",
				confidence: 0.9,
				sourceHasTaxonomyLeak: true,
			},
		});

		expect(result.decision).toBe("needs_review");
		expect(result.lane).toBeUndefined();
	});

	it("does not let hard filter failures use the performance-backed lane", () => {
		const result = evaluateAIQualityGate({
			content: "send nudes right now",
			viralScore: 99,
			performanceEvidence: {
				patternType: "winner_clone",
				strategyBucket: "proven",
				confidence: 0.9,
			},
		});

		expect(result.decision).toBe("block");
		expect(result.reason).toBe("filter:safety-blacklist");
		expect(result.lane).toBeUndefined();
	});

	it("allows harmless medium style flags for performance-backed clones", () => {
		const result = evaluateAIQualityGate({
			content: "what music are you gatekeeping right now?",
			viralScore: 92,
			filterResult: {
				passed: true,
				flags: [
					{
						pattern: "ai-complex-vocabulary",
						severity: "medium",
						message: "style warning",
					},
				],
			},
			contentScore: {
				passed: true,
				replyTrigger: 5,
				emotionalWarmth: 3,
				overall: 2.6,
			} as any,
			performanceEvidence: {
				patternType: "winner_clone",
				cloneFamily: "music_gatekeeping_question",
				strategyBucket: "proven",
			},
		});

		expect(result.decision).toBe("pass");
		expect(result.lane).toBe("performance_backed_clone");
	});

	it("does not bypass high-risk soft flags", () => {
		const result = evaluateAIQualityGate({
			content: "what music are you gatekeeping right now?",
			viralScore: 92,
			filterResult: {
				passed: true,
				flags: [
					{
						pattern: "safety-blacklist",
						severity: "high",
						message: "risk",
					},
				],
			},
			contentScore: {
				passed: true,
				replyTrigger: 5,
				emotionalWarmth: 3,
				overall: 2.6,
			} as any,
			performanceEvidence: {
				patternType: "winner_clone",
				strategyBucket: "proven",
			},
		});

		expect(result.decision).toBe("needs_review");
		expect(result.reason).toBe("filter:soft_flags");
		expect(result.lane).toBeUndefined();
	});

	it("passes confident, safe, non-competitor content", () => {
		const result = evaluateAIQualityGate({
			content: "be honest, would you answer a 2am text from your ex?",
			viralScore: 86,
		});

		expect(result.decision).toBe("pass");
		expect(result.reason).toBe("quality_gate_passed");
		expect(result.confidences.riskConfidence).toBeGreaterThan(0.8);
		expect(result.confidences.expectedOutcomeConfidence).toBeGreaterThan(0.7);
	});
});
