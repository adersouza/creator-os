import { evaluateAccountDna, type AccountDnaProfile, type AccountDnaRule } from "./accountDna.js";

const NAMED_OR_SPECIFIC_PATTERNS = [
	/@\w+/,
	/https?:\/\//i,
	/\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b/i,
	/\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i,
	/\b(?:new york|los angeles|london|paris|miami|toronto|dubai)\b/i,
	/\b(?:netflix|spotify|tiktok|instagram|threads|snapchat|valorant|fortnite|starbucks)\b/i,
	/\b\d{4}\b/,
];

const GENERIC_MICROCOPY_PATTERNS = [
	/\br u up\b/i,
	/\bu awake\b/i,
	/\bstill up\b/i,
	/\bwyd\b/i,
	/\bbe honest\b/i,
	/\bmiss me\b/i,
	/\bwho'?s awake\b/i,
	/\battention rn\b/i,
	/\bhaving a crush\b/i,
	/\bnot the only one\b/i,
];

export interface MicrocopyPolicyInput {
	content: string;
	dna: AccountDnaProfile | null;
	rules: AccountDnaRule[];
	siblingRules: AccountDnaRule[];
	attribution: {
		hook_type?: string | null | undefined;
		topic_label?: string | null | undefined;
		format_type?: string | null | undefined;
		emotional_frame?: string | null | undefined;
		reply_mechanism?: string | null | undefined;
		content_length_bucket?: string | null | undefined;
		media_style?: string | null | undefined;
	};
	duplicateMatch?: boolean | undefined;
	usedRecently?: boolean | undefined;
	sourceOverused?: boolean | undefined;
	quotaAvailable?: boolean | undefined;
	wasBackToBack?: boolean | undefined;
}

export interface MicrocopyPolicyDecision {
	decision: "queue" | "rewrite" | "block";
	confidence: number;
	reasons: string[];
	directCopyReason: string;
	dnaDecision: ReturnType<typeof evaluateAccountDna>;
}

function normalize(value: string): string {
	return value
		.toLowerCase()
		.replace(/[’']/g, "'")
		.replace(/[^\p{L}\p{N}\s?']/gu, " ")
		.replace(/\s+/g, " ")
		.trim();
}

function wordCount(content: string): number {
	return normalize(content).split(/\s+/).filter(Boolean).length;
}

function isShortMicrocopy(content: string): boolean {
	return wordCount(content) <= 12 || content.trim().length <= 60;
}

function hasSpecificDetails(content: string): boolean {
	return NAMED_OR_SPECIFIC_PATTERNS.some((pattern) => pattern.test(content));
}

function isGenericSocialShorthand(content: string): boolean {
	const normalized = normalize(content);
	if (GENERIC_MICROCOPY_PATTERNS.some((pattern) => pattern.test(normalized))) {
		return true;
	}
	const words = normalized.split(/\s+/).filter(Boolean);
	const tinyWords = words.filter((word) => word.length <= 6).length;
	return words.length > 0 && tinyWords / words.length >= 0.8;
}

function hasKnownMicrocopyPattern(content: string): boolean {
	const normalized = normalize(content);
	return GENERIC_MICROCOPY_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function evaluateCompetitorDirectMicrocopy(
	input: MicrocopyPolicyInput,
): MicrocopyPolicyDecision {
	const reasons: string[] = [];
	const content = input.content.trim();
	const knownPattern = hasKnownMicrocopyPattern(content);
	if (!content) reasons.push("empty_content");
	if (!isShortMicrocopy(content)) reasons.push("too_long_for_microcopy");
	if (!isGenericSocialShorthand(content)) reasons.push("not_generic_social_shorthand");
	if (isGenericSocialShorthand(content) && !knownPattern) {
		reasons.push("low_signal_generic_microcopy");
	}
	if (hasSpecificDetails(content)) reasons.push("specific_or_named_details");
	if (input.duplicateMatch) reasons.push("duplicate_fingerprint");
	if (input.usedRecently) reasons.push("used_recently_by_account");
	if (input.sourceOverused) reasons.push("source_competitor_overused");
	if (input.quotaAvailable === false) reasons.push("microcopy_quota_exhausted");
	if (input.wasBackToBack) reasons.push("back_to_back_microcopy");
	if (
		input.siblingRules.some((rule) => {
			const phrase = normalize(rule.rule_value);
			return (
				phrase.length > 0 &&
				(rule.rule_type === "owned_phrase" ||
					rule.rule_type === "sibling_avoid" ||
					rule.rule_type === "banned_phrase") &&
				normalize(content).includes(phrase)
			);
		})
	) {
		reasons.push("sibling_phrase_collision");
	}

	const dnaDecision = evaluateAccountDna({
		content,
		dna: input.dna,
		rules: input.rules,
		siblingRules: input.siblingRules,
		attribution: input.attribution,
	});
	if (dnaDecision.decision === "block") reasons.push("dna_block");
	if (dnaDecision.decision === "regenerate") reasons.push("dna_regenerate");
	if (dnaDecision.decision === "needs_review") reasons.push("dna_needs_review");
	if ((dnaDecision.sibling_collision_score ?? 0) >= 55) {
		reasons.push("sibling_phrase_collision");
	}

	const hardBlock = reasons.some((reason) =>
		[
			"empty_content",
			"too_long_for_microcopy",
			"specific_or_named_details",
			"duplicate_fingerprint",
			"used_recently_by_account",
			"source_competitor_overused",
			"microcopy_quota_exhausted",
			"back_to_back_microcopy",
			"sibling_phrase_collision",
			"dna_block",
			"dna_regenerate",
		].includes(reason),
	);
	const confidence = Math.max(
		0,
		Math.min(
				1,
			0.35 +
				(knownPattern ? 0.2 : isGenericSocialShorthand(content) ? 0.1 : 0) +
				(isShortMicrocopy(content) ? 0.2 : 0) +
				((dnaDecision.dna_fit_score ?? 70) >= 65 ? 0.2 : 0) +
				((dnaDecision.uniqueness_score ?? 70) >= 60 ? 0.05 : 0) -
				reasons.length * 0.08,
		),
	);

	if (hardBlock) {
		return {
			decision: "block",
			confidence,
			reasons,
			directCopyReason: "blocked_microcopy_policy",
			dnaDecision,
		};
	}

	if (confidence < 0.78 || reasons.length > 0) {
		return {
			decision: "rewrite",
			confidence,
			reasons,
			directCopyReason: "low_confidence_microcopy_rewrite",
			dnaDecision,
		};
	}

	return {
		decision: "queue",
		confidence,
		reasons: [],
		directCopyReason: "generic_dna_fit_microcopy",
		dnaDecision,
	};
}
