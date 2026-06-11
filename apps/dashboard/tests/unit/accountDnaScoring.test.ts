import { describe, expect, it } from "vitest";
import {
	buildCreatorDnaBackfillFromAccountDna,
	evaluateAccountDna,
	normalizeDnaPhrase,
	type AccountFlavorProfile,
	type AccountDnaProfile,
	type AccountDnaRule,
	type CreatorDnaProfile,
} from "../../api/_lib/handlers/auto-post/accountDna.js";
import { detectIdentityShapeId } from "../../api/_lib/handlers/auto-post/contentArchetypes.js";

const baseDna: AccountDnaProfile = {
	id: "11111111-1111-4111-8111-111111111111",
	account_id: "acc-1",
	workspace_id: "ws-1",
	group_id: "grp-1",
	version: 1,
	status: "active",
	confidence: 0.86,
	archetype: "soft_gfe",
	sub_archetype: "late_night_overthinker",
	follower_promise: "late-night comfort for people who miss being wanted",
	identity_summary:
		"soft, lonely, warm account that talks like a late-night text thread",
	backstory_facts: [],
	recurring_motifs: ["2am", "playlist", "miss you"],
	recurring_situations: ["can't sleep", "phone lighting up the room"],
	signature_beliefs: ["people just want to feel chosen"],
	primary_topics: ["dating", "loneliness", "crushes"],
	secondary_topics: ["music", "night"],
	taboo_topics: ["gym"],
	signature_phrases: ["miss you", "come here"],
	banned_phrases: ["gg", "leg day"],
	vocabulary_fingerprint: {
		signature_words: ["soft", "miss", "text", "night"],
		avoid_words: ["gg", "protein"],
	},
	emoji_policy: "none",
	punctuation_habits: { prefers_ellipsis: true, question_ratio: "low" },
	casing_style: "lowercase",
	average_length_min: 20,
	average_length_max: 120,
	emotional_baseline: "vulnerable",
	allowed_mood_range: ["vulnerable", "warm", "reflective"],
	cta_posture: "soft",
	controversy_level: 1,
	humor_level: 1,
	storytelling_tendency: 3,
	vulnerability_level: 5,
	flirt_level: 3,
};

const siblingRules: AccountDnaRule[] = [
	{
		id: "rule-1",
		rule_type: "owned_phrase",
		rule_value: "gg",
		action: "block",
		severity: "critical",
		weight: 1,
		account_id: "acc-2",
	},
];

const creatorDna: CreatorDnaProfile = {
	id: "creator-lola",
	workspace_id: "ws-1",
	group_id: "grp-1",
	version: 1,
	status: "active",
	confidence: 0.9,
	creator_key: "lola_mains",
	creator_name: "Lola",
	archetype: "lola_mains",
	follower_promise: "playful late-night anime and gym girl energy",
	identity_summary:
		"Lola sounds playful, flirty, anime-aware, gym-adjacent, and casually chaotic.",
	core_topics: ["anime", "gym", "dating"],
	core_motifs: ["late night", "playlist", "anime taste"],
	signature_beliefs: ["being a little unhinged is part of the charm"],
	shared_voice_traits: ["casual", "low punctuation", "playful self-awareness"],
	allowed_moods: ["playful", "flirty", "reflective"],
	shared_phrase_bank: ["unhinged", "late night"],
	taboo_topics: ["finance"],
};

const accountFlavor: AccountFlavorProfile = {
	id: "flavor-1",
	workspace_id: "ws-1",
	group_id: "grp-1",
	account_id: "acc-1",
	creator_dna_id: "creator-lola",
	status: "active",
	flavor_name: "anime-heavy",
	topic_emphasis: ["anime"],
	motif_emphasis: ["anime taste", "late night"],
	format_emphasis: ["identity_statement"],
	archetype_bias: ["identity_statement", "recommendation_request"],
	phrase_cooldowns: ["i'm a 9 but"],
	flavor_notes: "Lean heavier into anime than the main account.",
};

describe("account DNA scoring", () => {
	it("normalizes phrases for cross-account collision checks", () => {
		expect(normalizeDnaPhrase(" GG!!  ")).toBe("gg");
		expect(normalizeDnaPhrase("come   here...")).toBe("come here");
	});

	it("passes a post that fits the active account DNA", () => {
		const result = evaluateAccountDna({
			content: "i miss having someone to text at 2am when the playlist gets too quiet",
			dna: baseDna,
			rules: [],
			siblingRules,
			attribution: {
				hook_type: "personal_statement",
				topic_label: "dating",
				format_type: "text_post",
				emotional_frame: "vulnerable",
				reply_mechanism: "none",
				content_length_bucket: "short",
				media_style: "text_only",
			},
		});

		expect(result.decision).toBe("pass");
		expect(result.dna_fit_score).toBeGreaterThanOrEqual(78);
		expect(result.voice_fit_score).toBeGreaterThanOrEqual(70);
		expect(result.genericness_score).toBeLessThan(50);
	});

	it("routes high-performing but off-DNA posts to review instead of accepting them", () => {
		const result = evaluateAccountDna({
			content: "gg leg day made me feel like a different breed",
			dna: baseDna,
			rules: [],
			siblingRules,
			predictedViralScore: 94,
			attribution: {
				hook_type: "short_statement",
				topic_label: "gym",
				format_type: "text_post",
				emotional_frame: "confident",
				reply_mechanism: "none",
				content_length_bucket: "short",
				media_style: "text_only",
			},
		});

		expect(result.decision).toBe("needs_review");
		expect(result.reasons).toContain("high_performance_low_dna_fit");
		expect(result.topic_fit_score).toBeLessThanOrEqual(35);
		expect(result.sibling_collision_score).toBeLessThan(75);
	});

	it("regenerates generic low-context question bait without treating it as creator collision", () => {
		const result = evaluateAccountDna({
			content: "be honest would you date me",
			dna: baseDna,
			rules: [],
			siblingRules: [
				{
					id: "rule-2",
					rule_type: "owned_phrase",
					rule_value: "be honest",
					action: "block",
					severity: "critical",
					weight: 1,
					account_id: "acc-3",
				},
			],
			attribution: {
				hook_type: "question",
				topic_label: "uncategorized",
				format_type: "question_post",
				emotional_frame: "inviting",
				reply_mechanism: "direct_prompt",
				content_length_bucket: "micro",
				media_style: "text_only",
			},
		});

		expect(result.decision).toBe("regenerate");
		expect(result.reasons).not.toContain("high_sibling_collision");
		expect(result.reasons).not.toContain("cross_creator_collision");
		expect(result.genericness_score).toBeGreaterThanOrEqual(50);
	});

	it("does not penalize same-creator voice by default", () => {
		const result = evaluateAccountDna({
			content: "i'm a 9 but my taste in anime is unhinged",
			dna: baseDna,
			rules: [],
			siblingRules: [
				{
					id: "rule-lola",
					rule_type: "owned_phrase",
					rule_value: "unhinged",
					action: "boost",
					severity: "medium",
					weight: 1,
					account_id: "lola-sibling",
					scope: "same_creator",
				},
			],
			creatorDna,
			accountFlavor,
			recentSiblingRepetitions: [],
			crossCreatorPhrases: [],
			attribution: {
				hook_type: "personal_statement",
				topic_label: "anime",
				format_type: "text_post",
				emotional_frame: "playful",
				reply_mechanism: "none",
				content_length_bucket: "short",
				media_style: "text_only",
			},
		});

		expect(result.decision).toBe("pass");
		expect(result.reasons).not.toContain("high_sibling_collision");
		expect(result.reasons).not.toContain("cross_creator_collision");
		expect(result.creator_fit_score).toBeGreaterThanOrEqual(70);
		expect(result.account_flavor_score).toBeGreaterThanOrEqual(55);
		expect(result.recent_sibling_repetition_score).toBeLessThan(55);
	});

	it("passes creator-coded topic posts without requiring exact phrase-bank matches", () => {
		const result = evaluateAccountDna({
			content:
				"the energy shift when you put on the perfect workout playlist is everything",
			dna: {
				...baseDna,
				primary_topics: ["gym", "music"],
				secondary_topics: ["anime", "dating"],
				recurring_motifs: ["gym playlist", "workout playlist"],
				taboo_topics: [],
			},
			rules: [],
			siblingRules: [],
			creatorDna,
			accountFlavor: {
				...accountFlavor,
				flavor_name: "gym_music",
				topic_emphasis: ["gym", "music", "playlist"],
				motif_emphasis: ["gym playlist", "workout playlist"],
				archetype_bias: ["observation", "recommendation_request"],
				phrase_cooldowns: [],
			},
			recentSiblingRepetitions: [],
			crossCreatorPhrases: [],
			attribution: {
				hook_type: "observation",
				topic_label: "gym",
				format_type: "text_post",
				emotional_frame: "playful",
				reply_mechanism: "none",
				content_length_bucket: "short",
				media_style: "text_only",
				content_archetype: "observation",
			},
		});

		expect(result.decision).toBe("pass");
		expect(result.creator_fit_score).toBeGreaterThanOrEqual(70);
		expect(result.account_flavor_score).toBeGreaterThanOrEqual(60);
		expect(result.fit_explanation?.creator?.matched_topics.length).toBeGreaterThan(0);
		expect(result.fit_explanation?.creator?.matched_motifs.length).toBeGreaterThan(0);
	});

	it("flags recent exact phrase repetition from a same-creator sibling", () => {
		const result = evaluateAccountDna({
			content: "i'm a 9 but my taste in anime is unhinged",
			dna: baseDna,
			rules: [],
			siblingRules: [],
			creatorDna,
			accountFlavor,
			recentSiblingRepetitions: [
				{
					account_id: "lola-sibling",
					content: "i'm a 9 but my taste in anime is unhinged",
					shape_id: "IM_A_X_BUT_Y",
					created_at: "2026-06-05T00:00:00Z",
				},
			],
			crossCreatorPhrases: [],
			attribution: {
				hook_type: "personal_statement",
				topic_label: "anime",
				format_type: "text_post",
				emotional_frame: "playful",
				reply_mechanism: "none",
				content_length_bucket: "short",
				media_style: "text_only",
			},
		});

		expect(result.decision).toBe("regenerate");
		expect(result.reasons).toContain("recent_phrase_repetition");
		expect(result.reasons).toContain("recent_shape_repetition");
		expect(result.recent_sibling_repetition_score).toBeGreaterThanOrEqual(80);
	});

	it("flags recent same-shape repetition from a same-creator sibling", () => {
		const result = evaluateAccountDna({
			content: "i'm a 9 but my gym playlist is unhinged",
			dna: baseDna,
			rules: [],
			siblingRules: [],
			creatorDna,
			accountFlavor,
			recentSiblingRepetitions: [
				{
					account_id: "lola-sibling",
					content: "i'm a 9 but my anime taste is unhinged",
					shape_id: "IM_A_X_BUT_Y",
					created_at: "2026-06-05T00:00:00Z",
				},
			],
			crossCreatorPhrases: [],
			attribution: {
				hook_type: "personal_statement",
				topic_label: "gym",
				format_type: "text_post",
				emotional_frame: "playful",
				reply_mechanism: "none",
				content_length_bucket: "short",
				media_style: "text_only",
			},
		});

		expect(result.decision).toBe("regenerate");
		expect(result.reasons).toContain("recent_shape_repetition");
		expect(result.recent_sibling_repetition_score).toBeGreaterThanOrEqual(65);
	});

	it("flags cross-creator collapse when a post uses another creator's phrases", () => {
		const result = evaluateAccountDna({
			content: "lola late night anime taste is unhinged",
			dna: baseDna,
			rules: [],
			siblingRules: [],
			creatorDna: {
				...creatorDna,
				id: "creator-larissa",
				creator_key: "larissa_mains",
				creator_name: "Larissa",
				core_topics: ["music", "older men"],
				core_motifs: ["snap", "sunny"],
				shared_phrase_bank: ["older men", "sunny"],
			},
			accountFlavor: { ...accountFlavor, creator_dna_id: "creator-larissa" },
			crossCreatorPhrases: ["lola", "anime taste", "unhinged"],
			recentSiblingRepetitions: [],
			attribution: {
				hook_type: "personal_statement",
				topic_label: "anime",
				format_type: "text_post",
				emotional_frame: "playful",
				reply_mechanism: "none",
				content_length_bucket: "short",
				media_style: "text_only",
			},
		});

		expect(result.decision).toBe("regenerate");
		expect(result.reasons).toContain("cross_creator_collision");
		expect(result.cross_creator_collision_score).toBeGreaterThanOrEqual(75);
	});

	it("detects identity shape ids for cooldowns", () => {
		expect(detectIdentityShapeId("i'm a 9 but my anime taste is unhinged")).toBe(
			"IM_A_X_BUT_Y",
		);
		expect(detectIdentityShapeId("drop your top 3 songs for gym")).toBe(
			"DROP_YOUR_TOP_3_X",
		);
		expect(detectIdentityShapeId("lowkey just wanna stay up")).toBe(
			"LOWKEY_JUST_WANNA_X",
		);
	});

	it("backfills one creator DNA plus account flavors from active account DNA rows", () => {
		const result = buildCreatorDnaBackfillFromAccountDna({
			workspaceId: "ws-1",
			groupId: "grp-1",
			groupName: "Lola — Mains",
			accountDnaRows: [
				{
					...baseDna,
					id: "dna-lola-1",
					account_id: "lola-main",
					archetype: "lola_mains",
					follower_promise: "playful anime and gym girl",
					primary_topics: ["anime", "gym"],
					recurring_motifs: ["late night", "anime taste"],
					signature_phrases: ["unhinged"],
				},
				{
					...baseDna,
					id: "dna-lola-2",
					account_id: "lola-gym",
					archetype: "lola_mains",
					follower_promise: "playful anime and gym girl",
					primary_topics: ["gym", "music"],
					recurring_motifs: ["gym playlist"],
					signature_phrases: ["based"],
				},
			],
		});

		expect(result.creatorDna.creator_key).toBe("lola_mains");
		expect(result.creatorDna.core_topics).toEqual(
			expect.arrayContaining(["anime", "gym"]),
		);
		expect(result.accountFlavors).toHaveLength(2);
		expect(result.accountFlavors[0]).toMatchObject({
			account_id: "lola-main",
			creator_dna_id: result.creatorDna.id,
		});
	});

	it("passes unscored when no active DNA is available", () => {
		const result = evaluateAccountDna({
			content: "anything can still be generated before dna backfill",
			dna: null,
			rules: [],
			siblingRules: [],
			attribution: {
				hook_type: "statement",
				topic_label: "uncategorized",
				format_type: "text_post",
				emotional_frame: "neutral",
				reply_mechanism: "none",
				content_length_bucket: "short",
				media_style: "text_only",
			},
		});

		expect(result.decision).toBe("pass_unscored");
		expect(result.dna_fit_score).toBeNull();
	});
});
