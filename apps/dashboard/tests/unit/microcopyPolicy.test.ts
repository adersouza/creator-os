import { describe, expect, it } from "vitest";
import {
	evaluateCompetitorDirectMicrocopy,
	type MicrocopyPolicyInput,
} from "../../api/_lib/handlers/auto-post/microcopyPolicy.js";
import type {
	AccountDnaProfile,
	AccountDnaRule,
} from "../../api/_lib/handlers/auto-post/accountDna.js";

const dna: AccountDnaProfile = {
	id: "dna-1",
	workspace_id: "ws-1",
	group_id: "grp-1",
	account_id: "acc-1",
	version: 1,
	status: "active",
	confidence: 0.9,
	archetype: "late_night_romantic",
	follower_promise: "late night attention and soft flirty posts",
	identity_summary: "short late-night social shorthand",
	backstory_facts: [],
	recurring_motifs: ["awake", "crush", "attention", "miss me"],
	recurring_situations: [],
	signature_beliefs: [],
	primary_topics: ["dating", "night"],
	secondary_topics: ["music"],
	taboo_topics: ["brands"],
	signature_phrases: ["miss me", "still up"],
	banned_phrases: ["follow for more"],
	vocabulary_fingerprint: {
		signature_words: ["miss", "awake", "crush", "attention"],
	},
	emoji_policy: "minimal",
	punctuation_habits: {},
	casing_style: "lowercase",
	average_length_min: 4,
	average_length_max: 80,
	emotional_baseline: "neutral",
	allowed_mood_range: ["neutral", "vulnerable", "inviting"],
	cta_posture: "soft",
	controversy_level: 1,
	humor_level: 2,
	storytelling_tendency: 1,
	vulnerability_level: 3,
	flirt_level: 3,
};

function input(
	content: string,
	overrides: Partial<MicrocopyPolicyInput> = {},
): MicrocopyPolicyInput {
	return {
		content,
		dna,
		rules: [],
		siblingRules: [],
		attribution: {
			hook_type: content.includes("?") ? "question" : "statement",
			topic_label: "dating",
			format_type: "text_post",
			emotional_frame: "neutral",
			reply_mechanism: content.includes("?") ? "direct_prompt" : "none",
			content_length_bucket: "micro",
			media_style: "text_only",
		},
		quotaAvailable: true,
		...overrides,
	};
}

describe("competitor direct microcopy policy", () => {
	it("allows very short generic DNA-fitting microcopy", () => {
		const result = evaluateCompetitorDirectMicrocopy(input("r u up?"));

		expect(result.decision).toBe("queue");
		expect(result.confidence).toBeGreaterThanOrEqual(0.72);
		expect(result.directCopyReason).toBe("generic_dna_fit_microcopy");
	});

	it("allows useful relaxed-threshold microcopy", () => {
		const result = evaluateCompetitorDirectMicrocopy(
			input("i miss having a crush"),
		);

		expect(result.decision).toBe("queue");
	});

	it("blocks long competitor posts from direct copy", () => {
		const result = evaluateCompetitorDirectMicrocopy(
			input(
				"i went to that one specific party last friday and everyone kept asking about the same old story again",
			),
		);

		expect(result.decision).toBe("block");
		expect(result.reasons).toContain("too_long_for_microcopy");
	});

	it("blocks named or specific competitor details", () => {
		const result = evaluateCompetitorDirectMicrocopy(
			input("meet me in miami on friday"),
		);

		expect(result.decision).toBe("block");
		expect(result.reasons).toContain("specific_or_named_details");
	});

	it("blocks duplicate fingerprint repeats", () => {
		const result = evaluateCompetitorDirectMicrocopy(
			input("still up?", { duplicateMatch: true }),
		);

		expect(result.decision).toBe("block");
		expect(result.reasons).toContain("duplicate_fingerprint");
	});

	it("blocks sibling-owned phrase collisions", () => {
		const siblingRules: AccountDnaRule[] = [
			{
				id: "rule-1",
				account_id: "acc-2",
				rule_type: "owned_phrase",
				rule_value: "still up",
				action: "block",
				severity: "critical",
				weight: 1,
			},
		];

		const result = evaluateCompetitorDirectMicrocopy(
			input("still up?", { siblingRules }),
		);

		expect(result.decision).toBe("block");
		expect(result.reasons).toContain("sibling_phrase_collision");
	});

	it("uses rewrite instead of review for low-confidence microcopy", () => {
		const result = evaluateCompetitorDirectMicrocopy(input("hello there"));

		expect(result.decision).toBe("rewrite");
		expect(result.directCopyReason).toBe("low_confidence_microcopy_rewrite");
	});
});
