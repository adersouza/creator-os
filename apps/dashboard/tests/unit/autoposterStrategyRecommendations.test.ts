import { describe, expect, it } from "vitest";
import {
	activeStrategyRecommendations,
	buildStrategyRecommendations,
	evaluateRecommendationOutcomes,
	formatStrategyRecommendationsForPrompt,
	generationMixFromRecommendations,
	matchStrategyRecommendation,
	prioritizeStrategyRecommendations,
	type StrategyRecommendation,
} from "../../api/_lib/handlers/auto-post/strategyRecommendations";

const now = new Date("2026-06-05T12:00:00.000Z");

function rec(
	overrides: Partial<StrategyRecommendation>,
): StrategyRecommendation {
	return {
		workspace_id: "workspace-1",
		id: "00000000-0000-0000-0000-000000000001",
		group_id: "group-1",
		account_id: null,
		pattern_type: "hook_type",
		pattern_value: "confession",
		recommendation: "increase",
		confidence: 0.7,
		reason: "test",
		metric_basis: {},
		expires_at: "2099-01-01T00:00:00.000Z",
		...overrides,
	};
}

describe("autoposter strategy recommendations", () => {
	it("turns winning hooks into increase recommendations", () => {
		const rows = buildStrategyRecommendations({
			workspaceId: "workspace-1",
			groupId: "group-1",
			days: 30,
			now,
			best: {
				hookTypesBy1hReplies: [{ key: "confession", count: 8, avg: 4 }],
				hookTypesBy24hViews: [{ key: "confession", count: 8, avg: 900 }],
			},
		});

		expect(rows).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					pattern_type: "hook_type",
					pattern_value: "confession",
					recommendation: "increase",
				}),
			]),
		);
		expect(rows.find((row) => row.pattern_value === "confession")?.confidence)
			.toBeGreaterThanOrEqual(0.6);
	});

	it("turns recurring losing patterns into decrease or avoid recommendations", () => {
		const rows = buildStrategyRecommendations({
			workspaceId: "workspace-1",
			groupId: "group-1",
			days: 30,
			now,
			best: {},
			worstRecurringPatterns: [{ key: "direct_question", count: 10, avg: 0 }],
		});

		expect(rows).toContainEqual(
			expect.objectContaining({
				pattern_type: "hook_type",
				pattern_value: "direct_question",
				recommendation: "avoid",
			}),
		);
	});

	it("ignores expired recommendations", () => {
		const active = activeStrategyRecommendations(
			[
				rec({ pattern_value: "confession" }),
				rec({
					pattern_value: "expired_hot_take",
					expires_at: new Date(now.getTime() - 1000).toISOString(),
				}),
			],
			now,
		);

		expect(active.map((row) => row.pattern_value)).toEqual(["confession"]);
	});

	it("keeps low-confidence recommendations out of the proven winner bucket", () => {
		const mix = generationMixFromRecommendations(
			[
				rec({ pattern_value: "confession", confidence: 0.8 }),
				rec({
					pattern_value: "maybe_weird",
					recommendation: "increase",
					confidence: 0.42,
				}),
			],
			now,
		);

		expect(mix.provenWinners.map((row) => row.pattern_value)).toEqual([
			"confession",
		]);
		expect(mix.exploration.map((row) => row.pattern_value)).toContain(
			"maybe_weird",
		);
	});

	it("keeps exploration and weird randomness in the generation prompt", () => {
		const prompt = formatStrategyRecommendationsForPrompt(
			[
				rec({ pattern_value: "confession", confidence: 0.8 }),
				rec({
					pattern_value: "mini_story",
					pattern_type: "format_type",
					recommendation: "test",
					confidence: 0.5,
				}),
			],
			now,
		);

		expect(prompt).toContain("70% proven winners");
		expect(prompt).toContain("20% exploration");
		expect(prompt).toContain("10% weird/off-pattern human randomness");
		expect(prompt).toContain("test format_type=mini_story");
	});

	it("renders winner clone frame and mechanism into the generation prompt", () => {
		const prompt = formatStrategyRecommendationsForPrompt(
			[
				rec({
					pattern_type: "winner_clone",
					pattern_value: "post-1",
					confidence: 0.82,
					reason: "winner_clone_views_above_100",
					metric_basis: {
						sourceText:
							"need someone to talk to rn. check my profile if you're actually free rn",
						cloneFamily: "direct_profile_invitation",
						profileCuriosityFrame: "direct_profile_curiosity",
						curiosityMechanism: "direct_profile_invitation",
					},
				}),
			],
			now,
		);

		expect(prompt).toContain("cloneFamily=direct_profile_invitation");
		expect(prompt).toContain("frame=direct_profile_curiosity");
		expect(prompt).toContain("mechanism=direct_profile_invitation");
		expect(prompt).toContain("MUST preserve this frame/mechanism");
	});

	it("matches final post attribution to a proven recommendation", () => {
		const match = matchStrategyRecommendation(
			{ hook_type: "confession", topic_label: "dating" },
			[rec({ pattern_type: "hook_type", pattern_value: "confession" })],
		);

		expect(match.bucket).toBe("proven");
		expect(match.recommendation?.id).toBe(
			"00000000-0000-0000-0000-000000000001",
		);
	});

	it("classifies unmatched posts as weird when active recommendations exist", () => {
		const match = matchStrategyRecommendation(
			{ hook_type: "observation" },
			[rec({ pattern_type: "hook_type", pattern_value: "confession" })],
		);

		expect(match.bucket).toBe("weird");
		expect(match.recommendation).toBeNull();
	});

	it("prioritizes fresh group-scoped winner clones over older global clones with slightly higher confidence", () => {
		const prioritized = prioritizeStrategyRecommendations(
			[
				rec({
					id: "old-global",
					group_id: null,
					pattern_type: "winner_clone",
					pattern_value: "old-global-pattern",
					confidence: 0.8,
					updated_at: "2026-06-06T10:49:00.000Z",
					metric_basis: { cloneFamily: "old_global" },
				}),
				rec({
					id: "fresh-group",
					group_id: "group-1",
					pattern_type: "winner_clone",
					pattern_value: "fresh-group-pattern",
					confidence: 0.79,
					updated_at: "2026-06-08T10:39:00.000Z",
					metric_basis: { cloneFamily: "fresh_group" },
				}),
			],
			{
				groupId: "group-1",
				now: new Date("2026-06-08T12:00:00.000Z"),
			},
		);

		expect(prioritized.map((row) => row.id)).toEqual([
			"fresh-group",
			"old-global",
		]);
	});

	it("prioritizes competitor-backed winner clones over AI clones when scope is equal", () => {
		const prioritized = prioritizeStrategyRecommendations(
			[
				rec({
					id: "ai-clone",
					pattern_type: "winner_clone",
					pattern_value: "ai-pattern",
					confidence: 0.8,
					updated_at: "2026-06-08T10:39:00.000Z",
					metric_basis: {
						cloneFamily: "generic",
						sourceType: "ai",
						sourcePostId: "ai-post",
						sourcePatternId: "ai-post",
						performanceBasis: "views_above_100",
						views24h: 110,
					},
				}),
				rec({
					id: "competitor-clone",
					pattern_type: "winner_clone",
					pattern_value: "competitor-pattern",
					confidence: 0.79,
					updated_at: "2026-06-08T10:39:00.000Z",
					metric_basis: {
						cloneFamily: "crop_top_gym",
						sourceType: "competitor_copy",
						sourcePostId: "competitor-post",
						sourcePatternId: "competitor-post",
						performanceBasis: "views_above_100",
						views24h: 130,
					},
				}),
			],
			{
				groupId: "group-1",
				now: new Date("2026-06-08T12:00:00.000Z"),
			},
		);

		expect(prioritized.map((row) => row.id)).toEqual([
			"competitor-clone",
			"ai-clone",
		]);
	});

	it("lets stronger AI winner evidence outrank weaker competitor evidence", () => {
		const prioritized = prioritizeStrategyRecommendations(
			[
				rec({
					id: "strong-ai-clone",
					pattern_type: "winner_clone",
					pattern_value: "ai-pattern",
					confidence: 0.9,
					updated_at: "2026-06-08T10:39:00.000Z",
					metric_basis: {
						cloneFamily: "ai-hot-take",
						sourceType: "ai",
						sourcePostId: "ai-post",
						sourcePatternId: "ai-post",
						performanceBasis: "views_above_100",
						views24h: 360,
					},
				}),
				rec({
					id: "weak-competitor-clone",
					pattern_type: "winner_clone",
					pattern_value: "competitor-pattern",
					confidence: 0.55,
					updated_at: "2026-06-08T10:39:00.000Z",
					metric_basis: {
						cloneFamily: "crop_top_gym",
						sourceType: "competitor_copy",
						sourcePostId: "competitor-post",
						sourcePatternId: "competitor-post",
						performanceBasis: "views_above_100",
						views24h: 101,
					},
				}),
			],
			{
				groupId: "group-1",
				now: new Date("2026-06-08T12:00:00.000Z"),
			},
		);

		expect(prioritized.map((row) => row.id)).toEqual([
			"strong-ai-clone",
			"weak-competitor-clone",
		]);
	});

	it("prioritizes profile-curiosity winner clones over generic topical clones", () => {
		const prioritized = prioritizeStrategyRecommendations(
			[
				rec({
					id: "generic-topic-clone",
					pattern_type: "winner_clone",
					pattern_value: "generic-topic-pattern",
					confidence: 0.88,
					updated_at: "2026-06-08T10:39:00.000Z",
					metric_basis: {
						cloneFamily: "specific_topical_question_winner",
						sourceType: "ai",
						sourcePostId: "generic-post",
						sourcePatternId: "generic-post",
						performanceBasis: "views_above_100",
						views24h: 220,
						sourceText:
							"what's your comfort anime for when you're feeling down? tbh",
					},
				}),
				rec({
					id: "dating-curiosity-clone",
					pattern_type: "winner_clone",
					pattern_value: "dating-pattern",
					confidence: 0.8,
					updated_at: "2026-06-08T10:39:00.000Z",
					metric_basis: {
						cloneFamily: "anime_dateability_question",
						sourceType: "competitor_copy",
						sourcePostId: "dating-post",
						sourcePatternId: "dating-post",
						performanceBasis: "views_above_100",
						views24h: 130,
						sourceText:
							"would you date a girl who's obsessed with anime lore?",
					},
				}),
			],
			{
				groupId: "group-1",
				now: new Date("2026-06-08T12:00:00.000Z"),
			},
		);

		expect(prioritized.map((row) => row.id)).toEqual([
			"dating-curiosity-clone",
			"generic-topic-clone",
		]);
	});

	it("marks recommendations for expiry after repeated below-baseline outcomes", () => {
		const outcomes = evaluateRecommendationOutcomes(
			[
				{ strategy_recommendation_id: "rec-1", viewsAt24h: 10 },
				{ strategy_recommendation_id: "rec-1", viewsAt24h: 12 },
				{ strategy_recommendation_id: "rec-1", viewsAt24h: 8 },
				{ strategy_recommendation_id: "rec-2", viewsAt24h: 100 },
			],
			50,
			now,
		);

		expect(outcomes).toContainEqual(
			expect.objectContaining({
				id: "rec-1",
				sampleCount: 3,
				belowBaselineCount: 3,
				shouldExpire: true,
			}),
		);
		expect(outcomes).toContainEqual(
			expect.objectContaining({
				id: "rec-2",
				shouldExpire: false,
			}),
		);
	});
});
