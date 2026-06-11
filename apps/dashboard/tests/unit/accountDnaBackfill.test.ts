import { describe, expect, it } from "vitest";
import {
	buildAccountDnaBackfillForAccount,
	buildAccountDnaOpsSummary,
} from "../../api/_lib/handlers/auto-post/accountDna.js";

describe("account DNA backfill", () => {
	it("builds an active DNA profile with examples and enforceable phrase rules", () => {
		const result = buildAccountDnaBackfillForAccount({
			workspaceId: "ws-1",
			groupId: "grp-1",
			account: {
				id: "acc-1",
				username: "softtexts",
				display_name: "Soft Texts",
				bio: "late night dating thoughts",
			},
			group: {
				name: "Dating",
				voice_profile: {
					archetype: "soft_gfe",
					follower_promise: "late-night comfort for people who miss being wanted",
					taboo_topics: ["gym", "crypto"],
					signature_phrases: ["come here"],
				},
				content_strategy: {
					primary_topics: ["dating", "loneliness"],
					secondary_topics: ["music"],
				},
			},
			posts: [
				{
					id: "post-1",
					content: "i miss having someone to text at 2am when the playlist gets quiet",
					views_count: 1800,
					replies_count: 22,
					likes_count: 120,
					topic_label: "dating",
					emotional_frame: "vulnerable",
					hook_type: "personal_statement",
				},
				{
					id: "post-2",
					content: "come here, i found a song that sounds exactly like missing you",
					views_count: 1200,
					replies_count: 14,
					likes_count: 80,
					topic_label: "music",
					emotional_frame: "warm",
					hook_type: "confession",
				},
				{
					id: "post-3",
					content: "leg day protein update",
					views_count: 30,
					replies_count: 0,
					likes_count: 1,
					topic_label: "gym",
					emotional_frame: "confident",
					hook_type: "statement",
				},
			],
		});

		expect(result.dna.status).toBe("active");
		expect(result.dna.confidence).toBeGreaterThanOrEqual(0.65);
		expect(result.dna.archetype).toBe("soft_gfe");
		expect(result.dna.primary_topics).toContain("dating");
		expect(result.dna.secondary_topics).toContain("music");
		expect(result.dna.taboo_topics).toContain("gym");
		expect(result.dna.signature_phrases).toContain("come here");
		expect(result.examples.some((example) => example.example_type === "canonical")).toBe(true);
		expect(result.examples.some((example) => example.example_type === "anti_example")).toBe(true);
		expect(result.rules).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					rule_type: "owned_phrase",
					rule_value: "come here",
					action: "boost",
				}),
				expect.objectContaining({
					rule_type: "topic_ban",
					rule_value: "gym",
					action: "review",
				}),
			]),
		);
	});

	it("keeps low-signal accounts in draft until there is enough identity evidence", () => {
		const result = buildAccountDnaBackfillForAccount({
			workspaceId: "ws-1",
			groupId: "grp-1",
			account: {
				id: "acc-2",
				username: "newaccount",
				display_name: "New Account",
				bio: null,
			},
			group: {
				name: "General",
				voice_profile: {},
				content_strategy: {},
			},
			posts: [],
		});

		expect(result.dna.status).toBe("draft");
		expect(result.dna.confidence).toBeLessThan(0.65);
		expect(result.examples).toHaveLength(0);
		expect(result.dna.follower_promise).toContain("follow");
	});
});

describe("account DNA ops summary", () => {
	it("summarizes profile coverage and review pressure for the operator card", () => {
		const summary = buildAccountDnaOpsSummary({
			accountIds: ["acc-1", "acc-2", "acc-3"],
			profiles: [
				{
					id: "dna-1",
					account_id: "acc-1",
					status: "active",
					confidence: 0.88,
					archetype: "soft_gfe",
					sub_archetype: "late_night",
					follower_promise: "late-night comfort",
					signature_phrases: ["come here"],
					primary_topics: ["dating"],
					taboo_topics: ["gym"],
				},
				{
					id: "dna-2",
					account_id: "acc-2",
					status: "draft",
					confidence: 0.52,
					archetype: "chaotic_best_friend",
					sub_archetype: null,
					follower_promise: "funny dating chaos",
					signature_phrases: [],
					primary_topics: ["dating"],
					taboo_topics: [],
				},
			],
			metrics: [
				{
					account_id: "acc-1",
					uniqueness_score: 82,
					sibling_collision_score: 21,
					genericness_score: 29,
					drift_score: 14,
					decision: "healthy",
					reason: null,
					computed_at: "2026-06-05T00:00:00Z",
				},
			],
			reviewItems: [
				{
					id: "q-1",
					account_id: "acc-2",
					group_id: "grp-1",
					content: "be honest would you date me",
					dna_fit_score: 42,
					uniqueness_score: 50,
					sibling_collision_score: 78,
					genericness_score: 72,
					dna_decision: "regenerate",
					dna_reasons: ["high_sibling_collision", "high_genericness"],
					created_at: "2026-06-05T00:00:00Z",
				},
			],
		});

		expect(summary.totalAutoposterAccounts).toBe(3);
		expect(summary.activeProfiles).toBe(1);
		expect(summary.draftProfiles).toBe(1);
		expect(summary.missingProfiles).toBe(1);
		expect(summary.reviewQueueCount).toBe(1);
		expect(summary.avgUniquenessScore).toBe(82);
		expect(summary.profiles[0]).toMatchObject({
			account_id: "acc-1",
			status: "active",
			uniqueness_score: 82,
		});
	});
});
