import { describe, expect, it } from "vitest";
import {
	buildIdentityStatementCandidate,
	classifyContentArchetype,
	detectIdentityShapeId,
	validateIdentityStatementCandidate,
} from "@/api/_lib/handlers/auto-post/contentArchetypes";

const dna = {
	id: "dna-1",
	workspace_id: "workspace-1",
	group_id: "group-1",
	account_id: "account-1",
	version: 1,
	status: "active",
	confidence: 0.9,
	archetype: "chaotic_best_friend",
	sub_archetype: "anime_gym_flirt",
	follower_promise: "specific chaotic anime and gym energy",
	identity_summary: "anime gym girl with specific taste",
	backstory_facts: [],
	recurring_motifs: ["playlists"],
	recurring_situations: [],
	signature_beliefs: [],
	primary_topics: ["anime"],
	secondary_topics: ["music"],
	taboo_topics: [],
	signature_phrases: ["based"],
	banned_phrases: [],
	vocabulary_fingerprint: {},
	emoji_policy: "minimal",
	punctuation_habits: {},
	casing_style: "lowercase",
	average_length_min: 20,
	average_length_max: 120,
	emotional_baseline: "playful",
	allowed_mood_range: ["playful", "confident"],
	cta_posture: "soft",
	controversy_level: 2,
	humor_level: 4,
	storytelling_tendency: 2,
	vulnerability_level: 2,
	flirt_level: 2,
	source_summary: {},
	generated_from: "test",
	created_at: "2026-06-05T00:00:00Z",
	updated_at: "2026-06-05T00:00:00Z",
} as const;

describe("content archetypes", () => {
	it("classifies identity statements", () => {
		expect(
			classifyContentArchetype("i'm a 9 but my taste in anime is unhinged. based")
				.archetype,
		).toBe("identity_statement");
	});

	it("classifies recommendation requests", () => {
		expect(
			classifyContentArchetype("drop your top 3 songs for a gym playlist")
				.archetype,
		).toBe("recommendation_request");
	});

	it("classifies generic micro questions as question bait", () => {
		const result = classifyContentArchetype("who's up rn?");
		expect(result.archetype).toBe("question");
		expect(result.isGenericQuestion).toBe(true);
		expect(result.questionSubtype).toBe("generic_question_bait");
	});

	it("classifies performance-backed topical questions separately from generic bait", () => {
		const examples = [
			"what's the one anime everyone needs to watch right now?",
			"would you date a girl who's obsessed with anime lore?",
			"what music are you gatekeeping right now?",
			"the most underrated pre-workout is ________. prove me wrong.",
			"would you date a clingy girl who sends good morning texts?",
			"can you handle a jealous gym girl or no?",
		];

		for (const content of examples) {
			const result = classifyContentArchetype(content);
			expect(result.questionSubtype).toBe("specific_topical_question");
			expect(result.isGenericQuestion).toBe(false);
		}
	});

	it("keeps broad low-context questions in the generic bait lane", () => {
		for (const content of ["r u up?", "anyone else?", "who's awake?"]) {
			const result = classifyContentArchetype(content);
			expect(result.archetype).toBe("question");
			expect(result.questionSubtype).toBe("generic_question_bait");
			expect(result.isGenericQuestion).toBe(true);
		}
	});

	it("detects repeated social phrase shape ids for cooldowns", () => {
		expect(detectIdentityShapeId("asking for a friend who likes anime")).toBe(
			"ASKING_FOR_A_FRIEND",
		);
		expect(detectIdentityShapeId("anybody else rewatch comfort anime at 2am")).toBe(
			"ANYBODY_ELSE_X",
		);
		expect(detectIdentityShapeId("i can talk about gym playlists for hours")).toBe(
			"CAN_TALK_ABOUT_X",
		);
	});

	it("builds and validates a DNA-fit identity statement candidate", () => {
		const candidate = buildIdentityStatementCandidate(dna, "rating_but_trait");
		expect(candidate.content).toContain("anime");
		const result = validateIdentityStatementCandidate({
			content: candidate.content,
			dna,
		});
		expect(result.passed).toBe(true);
	});

	it("rejects sibling phrase collisions for identity statements", () => {
		const result = validateIdentityStatementCandidate({
			content: "i'm a 9 but my anime taste is unhinged. based",
			dna,
			siblingOwnedPhrases: ["based"],
		});
		expect(result.passed).toBe(false);
		expect(result.reasons).toContain("sibling_phrase_collision");
	});
});
