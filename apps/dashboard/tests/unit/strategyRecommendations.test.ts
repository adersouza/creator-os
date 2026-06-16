import { describe, expect, it } from "vitest";
import {
	prioritizeStrategyRecommendations,
	type StrategyRecommendation,
} from "../../api/_lib/handlers/auto-post/strategyRecommendations";

function winnerClone(
	id: string,
	sourceText: string,
	overrides: Partial<StrategyRecommendation> = {},
): StrategyRecommendation {
	return {
		id,
		workspace_id: "workspace-1",
		group_id: "group-1",
		account_id: null,
		pattern_type: "winner_clone",
		pattern_value: id,
		recommendation: "increase",
		confidence: 0.8,
		reason: "winner_clone_views_above_100",
		metric_basis: {
			sourcePostId: id,
			sourcePatternId: id,
			performanceBasis: "views_above_100",
			views24h: 300,
			sourceType: "ai",
			sourceText,
		},
		expires_at: "2026-06-20T00:00:00.000Z",
		updated_at: "2026-06-13T00:00:00.000Z",
		...overrides,
		metric_basis: {
			sourcePostId: id,
			sourcePatternId: id,
			performanceBasis: "views_above_100",
			views24h: 300,
			sourceType: "ai",
			sourceText,
			...(overrides.metric_basis ?? {}),
		},
	};
}

describe("strategy recommendation prioritization", () => {
	it("does not let one high-view AI formula winner dominate profile-curiosity clones", () => {
		const formula = winnerClone(
			"formula-1",
			"hot take: the best pre-workout is just black coffee. on god",
			{
				metric_basis: {
					views24h: 1800,
					sourceType: "ai",
				},
			},
		);
		const competitorCuriosity = winnerClone(
			"competitor-1",
			"would you date a girl who's super into astrology and reads your birth chart?",
			{
				metric_basis: {
					views24h: 300,
					sourceType: "competitor_copy",
				},
			},
		);

		const ordered = prioritizeStrategyRecommendations(
			[formula, competitorCuriosity],
			{
				groupId: "group-1",
				now: new Date("2026-06-13T12:00:00.000Z"),
			},
		);

		expect(ordered[0]?.id).toBe("competitor-1");
	});

	it("keeps high-performing AI profile-curiosity winners eligible over weak competitor clones", () => {
		const aiCuriosity = winnerClone(
			"ai-curiosity",
			"would you date a girl who only listens to metal at the gym?",
			{
				metric_basis: {
					views24h: 700,
					sourceType: "ai",
				},
			},
		);
		const weakCompetitor = winnerClone(
			"competitor-weak",
			"drop your favorite gym playlist song",
			{
				confidence: 0.55,
				metric_basis: {
					views24h: 80,
					sourceType: "competitor_copy",
				},
			},
		);

		const ordered = prioritizeStrategyRecommendations(
			[weakCompetitor, aiCuriosity],
			{
				groupId: "group-1",
				now: new Date("2026-06-13T12:00:00.000Z"),
			},
		);

		expect(ordered[0]?.id).toBe("ai-curiosity");
	});
});
