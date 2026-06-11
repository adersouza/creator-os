import type { SupabaseClient } from "@supabase/supabase-js";
import { getSupabaseAny } from "../../supabase.js";
import {
	detectIdentityShapeId,
	type IdentityShapeId,
} from "./contentArchetypes.js";

export type DnaStatus = "draft" | "active" | "retired";
export type EmojiPolicy = "none" | "minimal" | "moderate" | "heavy";
export type CasingStyle = "lowercase" | "sentence" | "mixed" | "chaotic";
export type CtaPosture = "none" | "soft" | "direct" | "teasing" | "salesy";
export type AccountDnaDecision =
	| "pass"
	| "pass_unscored"
	| "regenerate"
	| "needs_review"
	| "block";

export interface AccountDnaProfile {
	id: string;
	workspace_id: string;
	group_id?: string | null | undefined;
	account_id: string;
	version: number;
	status: DnaStatus;
	confidence: number;
	archetype: string;
	sub_archetype?: string | null | undefined;
	follower_promise: string;
	identity_summary: string;
	backstory_facts: string[];
	recurring_motifs: string[];
	recurring_situations: string[];
	signature_beliefs: string[];
	primary_topics: string[];
	secondary_topics: string[];
	taboo_topics: string[];
	signature_phrases: string[];
	banned_phrases: string[];
	vocabulary_fingerprint: {
		signature_words?: string[] | undefined;
		avoid_words?: string[] | undefined;
		filler_words?: string[] | undefined;
		sentence_starters?: string[] | undefined;
	};
	emoji_policy: EmojiPolicy;
	punctuation_habits: Record<string, unknown>;
	casing_style: CasingStyle;
	average_length_min: number;
	average_length_max: number;
	emotional_baseline: string;
	allowed_mood_range: string[];
	cta_posture: CtaPosture;
	controversy_level: number;
	humor_level: number;
	storytelling_tendency: number;
	vulnerability_level: number;
	flirt_level: number;
}

export interface AccountDnaRule {
	id: string;
	account_id: string;
	rule_type: string;
	rule_value: string;
	action: "boost" | "penalize" | "block" | "require" | "review";
	severity: "low" | "medium" | "high" | "critical";
	weight: number;
	scope?: "same_creator" | "cross_creator" | "account" | null | undefined;
	rule_payload?: Record<string, unknown> | null | undefined;
}

export interface CreatorDnaProfile {
	id: string;
	workspace_id: string;
	group_id?: string | null | undefined;
	version: number;
	status: DnaStatus;
	confidence: number;
	creator_key: string;
	creator_name: string;
	archetype: string;
	follower_promise: string;
	identity_summary: string;
	core_topics: string[];
	core_motifs: string[];
	signature_beliefs: string[];
	shared_voice_traits: string[];
	allowed_moods: string[];
	shared_phrase_bank: string[];
	taboo_topics: string[];
}

export interface AccountFlavorProfile {
	id: string;
	workspace_id: string;
	group_id?: string | null | undefined;
	account_id: string;
	creator_dna_id: string;
	status: DnaStatus;
	flavor_name: string;
	topic_emphasis: string[];
	motif_emphasis: string[];
	format_emphasis: string[];
	archetype_bias: string[];
	phrase_cooldowns: string[];
	flavor_notes?: string | null | undefined;
}

export interface RecentSiblingRepetition {
	account_id?: string | null | undefined;
	content: string;
	shape_id?: IdentityShapeId | string | null | undefined;
	created_at?: string | null | undefined;
}

export interface AccountDnaAttribution {
	hook_type?: string | null | undefined;
	topic_label?: string | null | undefined;
	format_type?: string | null | undefined;
	emotional_frame?: string | null | undefined;
	reply_mechanism?: string | null | undefined;
	content_length_bucket?: string | null | undefined;
	media_style?: string | null | undefined;
	content_archetype?: string | null | undefined;
}

export interface AccountDnaEvaluationInput {
	content: string;
	dna: AccountDnaProfile | null;
	rules: AccountDnaRule[];
	siblingRules: AccountDnaRule[];
	attribution: AccountDnaAttribution;
	predictedViralScore?: number | null | undefined;
	creatorDna?: CreatorDnaProfile | null | undefined;
	accountFlavor?: AccountFlavorProfile | null | undefined;
	recentSiblingRepetitions?: RecentSiblingRepetition[] | undefined;
	crossCreatorPhrases?: string[] | undefined;
}

export interface AccountDnaEvaluation {
	dna_id: string | null;
	dna_version: number | null;
	dna_fit_score: number | null;
	voice_fit_score: number | null;
	topic_fit_score: number | null;
	mood_fit_score: number | null;
	uniqueness_score: number | null;
	sibling_collision_score: number | null;
	genericness_score: number | null;
	creator_fit_score?: number | null;
	account_flavor_score?: number | null;
	recent_sibling_repetition_score?: number | null;
	cross_creator_collision_score?: number | null;
	decision: AccountDnaDecision;
	reasons: string[];
	fit_explanation?: AccountDnaFitExplanation | null;
}

export interface AccountDnaFitExplanation {
	creator?:
		| {
				matched_topics: string[];
				matched_motifs: string[];
				matched_voice_traits: string[];
				matched_phrases: string[];
				matched_beliefs: string[];
				matched_archetypes: string[];
				missing_creator_signals: string[];
				penalty_contributors: string[];
		  }
		| null
		| undefined;
	account_flavor?:
		| {
				matched_topics: string[];
				matched_motifs: string[];
				matched_formats: string[];
				matched_archetypes: string[];
				matched_notes: string[];
				penalty_contributors: string[];
		  }
		| null
		| undefined;
}

export interface AccountDnaBackfillPost {
	id?: string | null | undefined;
	content: string;
	views_count?: number | null | undefined;
	replies_count?: number | null | undefined;
	likes_count?: number | null | undefined;
	hook_type?: string | null | undefined;
	topic_label?: string | null | undefined;
	format_type?: string | null | undefined;
	emotional_frame?: string | null | undefined;
	reply_mechanism?: string | null | undefined;
	content_length_bucket?: string | null | undefined;
	media_style?: string | null | undefined;
	published_at?: string | null | undefined;
}

export interface AccountDnaBackfillInput {
	workspaceId: string;
	groupId?: string | null | undefined;
	account: {
		id: string;
		username?: string | null | undefined;
		display_name?: string | null | undefined;
		bio?: string | null | undefined;
		ai_config?: Record<string, unknown> | null | undefined;
	};
	group?:
		| {
				name?: string | null | undefined;
				voice_profile?: Record<string, unknown> | null | undefined;
				content_strategy?: Record<string, unknown> | null | undefined;
		  }
		| null
		| undefined;
	posts: AccountDnaBackfillPost[];
}

export interface AccountDnaBackfillResult {
	dna: Omit<AccountDnaProfile, "id">;
	examples: Array<Record<string, unknown>>;
	rules: Array<Record<string, unknown>>;
}

export interface CreatorDnaBackfillInput {
	workspaceId: string;
	groupId: string;
	groupName?: string | null | undefined;
	accountDnaRows: AccountDnaProfile[];
}

export interface CreatorDnaBackfillResult {
	creatorDna: CreatorDnaProfile;
	accountFlavors: AccountFlavorProfile[];
}

export interface CreatorDnaBackfillRunResult {
	groupsConsidered: number;
	creatorsCreated: number;
	flavorsCreated: number;
	skipped: number;
	failed: number;
	errors: Array<{ group_id: string; error: string }>;
}

export interface AccountDnaOpsSummaryInput {
	accountIds: string[];
	profiles: Array<Record<string, unknown>>;
	metrics: Array<Record<string, unknown>>;
	reviewItems: Array<Record<string, unknown>>;
}

export interface AccountDnaOpsSummary {
	totalAutoposterAccounts: number;
	activeProfiles: number;
	draftProfiles: number;
	missingProfiles: number;
	reviewQueueCount: number;
	avgUniquenessScore: number | null;
	avgGenericnessScore: number | null;
	profiles: Array<Record<string, unknown>>;
	reviewItems: Array<Record<string, unknown>>;
}

const GENERIC_PHRASES = [
	"be honest",
	"would you date me",
	"am i the only one",
	"tell me why",
	"hot take",
	"unpopular opinion",
	"is it just me",
	"lowkey",
	"ngl",
];

const DEFAULT_BANNED_PHRASES = [
	"as an ai",
	"link in bio",
	"follow for more",
	"motivational quote",
];

function jsonObject(value: unknown): Record<string, unknown> {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

function firstString(...values: unknown[]): string | null {
	for (const value of values) {
		if (typeof value === "string" && value.trim()) return value.trim();
	}
	return null;
}

function clampScore(value: number): number {
	if (!Number.isFinite(value)) return 0;
	return Math.max(0, Math.min(100, Math.round(value)));
}

function asStringArray(value: unknown): string[] {
	if (!Array.isArray(value)) return [];
	return value
		.filter((item): item is string => typeof item === "string")
		.map((item) => item.trim())
		.filter(Boolean);
}

function includesAny(normalizedContent: string, values: string[]): boolean {
	return values.some((value) => {
		const normalized = normalizeDnaPhrase(value);
		return normalized.length > 0 && normalizedContent.includes(normalized);
	});
}

function matchedValues(normalizedContent: string, values: string[]): string[] {
	return uniqueStrings(
		values.filter((value) => {
			const normalized = normalizeDnaPhrase(value);
			return normalized.length > 0 && normalizedContent.includes(normalized);
		}),
		12,
	);
}

function countMatches(normalizedContent: string, values: string[]): number {
	return values.reduce((count, value) => {
		const normalized = normalizeDnaPhrase(value);
		return normalized.length > 0 && normalizedContent.includes(normalized)
			? count + 1
			: count;
	}, 0);
}

function textLengthFit(content: string, dna: AccountDnaProfile): number {
	const length = content.length;
	if (length >= dna.average_length_min && length <= dna.average_length_max) {
		return 100;
	}
	const distance =
		length < dna.average_length_min
			? dna.average_length_min - length
			: length - dna.average_length_max;
	return clampScore(100 - distance * 1.5);
}

function casingFit(content: string, dna: AccountDnaProfile): number {
	if (dna.casing_style === "chaotic" || dna.casing_style === "mixed") return 80;
	const letters = content.replace(/[^a-zA-Z]/g, "");
	if (!letters) return 80;
	const lowercaseRatio =
		(letters.match(/[a-z]/g) || []).length / Math.max(1, letters.length);
	if (dna.casing_style === "lowercase") return clampScore(lowercaseRatio * 100);
	return clampScore((1 - Math.abs(lowercaseRatio - 0.8)) * 100);
}

function emojiFit(content: string, dna: AccountDnaProfile): number {
	const emojiCount = Array.from(content).filter((char) =>
		/\p{Extended_Pictographic}/u.test(char),
	).length;
	if (dna.emoji_policy === "none") return emojiCount === 0 ? 100 : 50;
	if (dna.emoji_policy === "minimal") return emojiCount <= 1 ? 100 : 70;
	if (dna.emoji_policy === "moderate") return emojiCount <= 3 ? 95 : 75;
	return emojiCount > 0 ? 95 : 70;
}

function punctuationFit(content: string, dna: AccountDnaProfile): number {
	const prefersEllipsis = dna.punctuation_habits.prefers_ellipsis === true;
	const hasEllipsis = content.includes("...");
	const questionCount = (content.match(/\?/g) || []).length;
	let score = 75;
	if (prefersEllipsis && hasEllipsis) score += 15;
	if (dna.cta_posture === "none" && questionCount > 0) score -= 10;
	if (dna.cta_posture === "soft" && questionCount <= 1) score += 10;
	return clampScore(score);
}

function scoreVoice(
	content: string,
	normalizedContent: string,
	dna: AccountDnaProfile,
	rules: AccountDnaRule[],
	siblingRules: AccountDnaRule[],
): { score: number; bannedHit: boolean; siblingHit: boolean } {
	const signatureWords = asStringArray(
		dna.vocabulary_fingerprint.signature_words,
	);
	const avoidWords = asStringArray(dna.vocabulary_fingerprint.avoid_words);
	const signatureMatches =
		countMatches(normalizedContent, signatureWords) +
		countMatches(normalizedContent, dna.signature_phrases);
	const bannedHit =
		includesAny(normalizedContent, dna.banned_phrases) ||
		includesAny(normalizedContent, avoidWords) ||
		rules.some(
			(rule) =>
				rule.rule_type === "banned_phrase" &&
				normalizeDnaPhrase(rule.rule_value).length > 0 &&
				normalizedContent.includes(normalizeDnaPhrase(rule.rule_value)),
		);
	const siblingHit = siblingRules.some(
		(rule) =>
			rule.scope === "cross_creator" &&
			(rule.rule_type === "owned_phrase" ||
				rule.rule_type === "sibling_avoid" ||
				rule.rule_type === "banned_phrase") &&
			normalizeDnaPhrase(rule.rule_value).length > 0 &&
			normalizedContent.includes(normalizeDnaPhrase(rule.rule_value)),
	);
	const vocabularyMatch = signatureMatches > 0 ? 95 : 65;
	const signaturePhraseAlignment =
		countMatches(normalizedContent, dna.signature_phrases) > 0 ? 100 : 65;
	let score =
		0.25 * vocabularyMatch +
		0.2 * punctuationFit(content, dna) +
		0.15 * casingFit(content, dna) +
		0.15 * textLengthFit(content, dna) +
		0.15 * signaturePhraseAlignment +
		0.1 * 70;
	if (bannedHit) score -= 25;
	if (siblingHit) score -= 25;
	if (emojiFit(content, dna) < 70) score -= 10;
	return { score: clampScore(score), bannedHit, siblingHit };
}

function scoreTopic(
	normalizedContent: string,
	dna: AccountDnaProfile,
	attribution: AccountDnaAttribution,
): { score: number; tabooHit: boolean; motifHit: boolean } {
	const topic = normalizeDnaPhrase(attribution.topic_label || "");
	const tabooHit =
		includesAny(normalizedContent, dna.taboo_topics) ||
		dna.taboo_topics.some((item) => normalizeDnaPhrase(item) === topic);
	const primaryHit =
		dna.primary_topics.some((item) => normalizeDnaPhrase(item) === topic) ||
		includesAny(normalizedContent, dna.primary_topics);
	const secondaryHit =
		dna.secondary_topics.some((item) => normalizeDnaPhrase(item) === topic) ||
		includesAny(normalizedContent, dna.secondary_topics);
	const motifHit = includesAny(normalizedContent, dna.recurring_motifs);
	let score =
		0.45 * (primaryHit ? 100 : 45) +
		0.25 * (secondaryHit ? 90 : 50) +
		0.2 * (topic === "uncategorized" || !topic ? 45 : 70) +
		0.1 * (motifHit ? 100 : 45);
	if (primaryHit) score = Math.max(score, 70);
	if (topic === "uncategorized" || !topic) score = Math.min(score, 65);
	if (tabooHit) score = Math.min(score, 35);
	return { score: clampScore(score), tabooHit, motifHit };
}

function scoreMood(
	dna: AccountDnaProfile,
	attribution: AccountDnaAttribution,
): { score: number; moodAllowed: boolean } {
	const frame = normalizeDnaPhrase(attribution.emotional_frame || "neutral");
	const baseline = normalizeDnaPhrase(dna.emotional_baseline);
	const allowed = dna.allowed_mood_range.map(normalizeDnaPhrase);
	const baselineMatch = frame === baseline;
	const moodAllowed = allowed.length === 0 || allowed.includes(frame);
	let score =
		0.4 * (baselineMatch ? 100 : 55) +
		0.3 * (moodAllowed ? 100 : 25) +
		0.15 * 75 +
		0.15 * 75;
	if (baselineMatch) score += 15;
	if (!moodAllowed) score = Math.min(score, 55);
	return { score: clampScore(score), moodAllowed };
}

function scoreGenericness(
	normalizedContent: string,
	dna: AccountDnaProfile,
	attribution: AccountDnaAttribution,
): number {
	const genericHits = countMatches(normalizedContent, GENERIC_PHRASES);
	const commonPhraseDensity = Math.min(100, genericHits * 35);
	const lowSpecificity =
		countMatches(normalizedContent, [
			...dna.recurring_motifs,
			...dna.signature_phrases,
			...dna.primary_topics,
		]) > 0
			? 10
			: 75;
	const noMotif = includesAny(normalizedContent, dna.recurring_motifs)
		? 10
		: 80;
	const templateSimilarity =
		attribution.hook_type === "question" ||
		attribution.reply_mechanism === "direct_prompt"
			? 70
			: 25;
	const broadTopic =
		!attribution.topic_label || attribution.topic_label === "uncategorized"
			? 85
			: 25;
	return clampScore(
		0.3 * commonPhraseDensity +
			0.2 * lowSpecificity +
			0.2 * noMotif +
			0.15 * templateSimilarity +
			0.15 * broadTopic,
	);
}

function scoreSiblingCollision(
	normalizedContent: string,
	siblingRules: AccountDnaRule[],
): { score: number; collidedPhrases: string[] } {
	const collidedPhrases = siblingRules
		.filter((rule) => {
			const phrase = normalizeDnaPhrase(rule.rule_value);
			return (
				rule.scope === "cross_creator" &&
				phrase.length > 0 &&
				(rule.rule_type === "owned_phrase" ||
					rule.rule_type === "sibling_avoid" ||
					rule.rule_type === "banned_phrase") &&
				normalizedContent.includes(phrase)
			);
		})
		.map((rule) => normalizeDnaPhrase(rule.rule_value));
	const phraseCollision = Math.min(100, collidedPhrases.length * 85);
	return {
		score: clampScore(Math.max(phraseCollision, 20)),
		collidedPhrases,
	};
}

const CREATOR_TOPIC_ALIASES: Record<string, string[]> = {
	anime: ["anime", "manga", "animated", "animation", "movie", "shonen", "weeb"],
	gaming: [
		"gaming",
		"gamer",
		"game",
		"xbox",
		"playstation",
		"pc",
		"controller",
	],
	gym: ["gym", "workout", "fitness", "playlist", "lift", "leg day", "cardio"],
	music: ["music", "song", "songs", "playlist", "album", "artist"],
	dating: [
		"dating",
		"date",
		"dates",
		"boy",
		"boys",
		"guy",
		"guys",
		"men",
		"ex",
		"exes",
		"relationship",
		"crush",
		"single",
	],
	relationship: [
		"relationship",
		"dating",
		"date",
		"boyfriend",
		"girlfriend",
		"crush",
		"single",
		"ex",
		"men",
	],
	late_night: ["late night", "2am", "awake", "sleep", "midnight", "night"],
	flirty: ["flirt", "flirty", "attention", "miss me", "crush", "date"],
	soft: ["soft", "cozy", "miss", "wanted", "comfort", "playlist"],
};

function semanticAliasesFor(values: string[]): string[] {
	const aliases: string[] = [];
	for (const value of values) {
		const normalized = normalizeDnaPhrase(value);
		aliases.push(value);
		for (const [key, terms] of Object.entries(CREATOR_TOPIC_ALIASES)) {
			const normalizedKey = key.replace(/_/g, " ");
			if (
				normalized.includes(normalizedKey) ||
				terms.some((term) => normalized.includes(term))
			) {
				aliases.push(...terms);
			}
		}
	}
	return uniqueStrings(aliases, 40);
}

function matchedSemanticValues(
	normalizedContent: string,
	values: string[],
): string[] {
	return matchedValues(normalizedContent, semanticAliasesFor(values));
}

function voiceTraitMatches(
	normalizedContent: string,
	rawContent: string,
	traits: string[],
	attribution: AccountDnaAttribution,
): string[] {
	const matches: string[] = [];
	const normalizedTraits = traits.map(normalizeDnaPhrase);
	const questionCount = (rawContent.match(/\?/g) || []).length;
	const hasEmoji = /\p{Extended_Pictographic}/u.test(rawContent);
	const letters = rawContent.replace(/[^a-zA-Z]/g, "");
	const lowercaseRatio =
		letters.length > 0
			? (letters.match(/[a-z]/g) || []).length / Math.max(1, letters.length)
			: 1;
	const frame = normalizeDnaPhrase(attribution.emotional_frame || "");
	const archetype = normalizeDnaPhrase(attribution.content_archetype || "");

	for (const trait of normalizedTraits) {
		if (!trait) continue;
		if (normalizedContent.includes(trait)) matches.push(trait);
		if (trait.includes("low punctuation") && questionCount <= 1)
			matches.push("low punctuation");
		if (trait.includes("low emoji") && !hasEmoji) matches.push("low emoji");
		if (trait.includes("casual") && rawContent.length <= 180)
			matches.push("casual short-form");
		if (
			trait.includes("playful") &&
			(frame === "playful" || archetype === "observation")
		)
			matches.push("playful frame");
		if (
			trait.includes("self awareness") &&
			/\bi('| a)?m\b|\bmy\b|\bme\b/.test(normalizedContent)
		)
			matches.push("self-aware first person");
		if (trait.includes("lowercase") && lowercaseRatio > 0.85)
			matches.push("lowercase");
	}
	return uniqueStrings(matches, 8);
}

function archetypeMatches(
	accountFlavor: AccountFlavorProfile | null | undefined,
	attribution: AccountDnaAttribution,
): string[] {
	const archetype = normalizeDnaPhrase(attribution.content_archetype || "");
	const format = normalizeDnaPhrase(attribution.format_type || "");
	return uniqueStrings(
		[
			...(accountFlavor?.archetype_bias ?? []).filter(
				(item) => normalizeDnaPhrase(item) === archetype,
			),
			...(accountFlavor?.format_emphasis ?? []).filter(
				(item) => normalizeDnaPhrase(item) === format,
			),
		],
		8,
	);
}

function effectiveLegacyDnaThreshold(input: {
	creatorFitScore: number | null;
	accountFlavorScore: number | null;
	genericnessScore: number;
}): number {
	if (
		input.creatorFitScore !== null &&
		input.creatorFitScore >= 65 &&
		(input.accountFlavorScore === null || input.accountFlavorScore >= 55) &&
		input.genericnessScore < 70
	) {
		return 45;
	}
	return 65;
}

function scoreCreatorFitDetailed(
	content: string,
	normalizedContent: string,
	creatorDna: CreatorDnaProfile | null | undefined,
	accountFlavor: AccountFlavorProfile | null | undefined,
	attribution: AccountDnaAttribution,
): {
	score: number | null;
	explanation: AccountDnaFitExplanation["creator"] | null;
} {
	if (!creatorDna || creatorDna.status !== "active") {
		return { score: null, explanation: null };
	}
	const topic = normalizeDnaPhrase(attribution.topic_label || "");
	const allowedTopics = [
		...creatorDna.core_topics,
		...(accountFlavor?.topic_emphasis ?? []),
	];
	const allowedMotifs = [
		...creatorDna.core_motifs,
		...(accountFlavor?.motif_emphasis ?? []),
	];
	const allowedPhrases = [
		...creatorDna.shared_phrase_bank,
		...(accountFlavor?.phrase_cooldowns ?? []),
	];
	const matchedTopics = matchedSemanticValues(normalizedContent, allowedTopics);
	const matchedMotifs = matchedSemanticValues(normalizedContent, allowedMotifs);
	const matchedPhrases = matchedValues(normalizedContent, allowedPhrases);
	const matchedBeliefs = matchedValues(
		normalizedContent,
		creatorDna.signature_beliefs,
	);
	const matchedArchetypes = archetypeMatches(accountFlavor, attribution);
	const topicHit =
		matchedTopics.length > 0 ||
		allowedTopics.some((item) => normalizeDnaPhrase(item) === topic);
	const motifHit = matchedMotifs.length > 0;
	const phraseHit = matchedPhrases.length > 0;
	const beliefHit = matchedBeliefs.length > 0;
	const archetypeHit = matchedArchetypes.length > 0;
	const tabooHit = includesAny(normalizedContent, creatorDna.taboo_topics);
	const mood = normalizeDnaPhrase(attribution.emotional_frame || "neutral");
	const moodAllowed =
		creatorDna.allowed_moods.length === 0 ||
		creatorDna.allowed_moods.map(normalizeDnaPhrase).includes(mood);
	const matchedVoiceTraits = voiceTraitMatches(
		normalizedContent,
		content,
		creatorDna.shared_voice_traits,
		attribution,
	);
	const voiceTraitHit = matchedVoiceTraits.length > 0;
	const topicScore = topicHit
		? 100
		: topic && topic !== "uncategorized"
			? 72
			: 58;
	const motifScore = motifHit ? 96 : topicHit ? 74 : 58;
	const voiceScore = voiceTraitHit ? 92 : 72;
	const archetypeScore = archetypeHit ? 94 : 72;
	const moodScore = moodAllowed ? 92 : 48;
	const beliefScore = beliefHit ? 90 : 68;
	const phraseScore = phraseHit ? 92 : 74;
	let score =
		0.32 * topicScore +
		0.18 * motifScore +
		0.16 * voiceScore +
		0.12 * archetypeScore +
		0.1 * moodScore +
		0.07 * beliefScore +
		0.05 * phraseScore;
	const evidenceCount = [
		topicHit,
		motifHit,
		voiceTraitHit,
		archetypeHit,
		beliefHit,
		phraseHit,
	].filter(Boolean).length;
	if (topicHit && (motifHit || archetypeHit || voiceTraitHit)) score += 6;
	if (evidenceCount >= 3) score += 4;
	if (tabooHit) score = Math.min(score, 35);
	const missingCreatorSignals: string[] = [];
	if (!topicHit) missingCreatorSignals.push("topic_cluster");
	if (!motifHit) missingCreatorSignals.push("motif");
	if (!voiceTraitHit) missingCreatorSignals.push("voice_trait");
	if (!archetypeHit) missingCreatorSignals.push("archetype_bias");
	return {
		score: clampScore(score),
		explanation: {
			matched_topics: matchedTopics,
			matched_motifs: matchedMotifs,
			matched_voice_traits: matchedVoiceTraits,
			matched_phrases: matchedPhrases,
			matched_beliefs: matchedBeliefs,
			matched_archetypes: matchedArchetypes,
			missing_creator_signals: missingCreatorSignals,
			penalty_contributors: tabooHit ? ["taboo_topic"] : [],
		},
	};
}

function scoreAccountFlavorFitDetailed(
	normalizedContent: string,
	accountFlavor: AccountFlavorProfile | null | undefined,
	attribution: AccountDnaAttribution,
): {
	score: number | null;
	explanation: AccountDnaFitExplanation["account_flavor"] | null;
} {
	if (!accountFlavor || accountFlavor.status !== "active") {
		return { score: null, explanation: null };
	}
	const topic = normalizeDnaPhrase(attribution.topic_label || "");
	const shape = detectIdentityShapeId(normalizedContent);
	const matchedTopics = matchedSemanticValues(
		normalizedContent,
		accountFlavor.topic_emphasis,
	);
	const matchedMotifs = matchedSemanticValues(
		normalizedContent,
		accountFlavor.motif_emphasis,
	);
	const topicHit =
		matchedTopics.length > 0 ||
		accountFlavor.topic_emphasis.some(
			(item) => normalizeDnaPhrase(item) === topic,
		);
	const motifHit = matchedMotifs.length > 0;
	const matchedFormats = accountFlavor.format_emphasis.filter(
		(item) =>
			normalizeDnaPhrase(item) ===
			normalizeDnaPhrase(attribution.format_type || ""),
	);
	const matchedArchetypes = accountFlavor.archetype_bias.filter(
		(item) =>
			normalizeDnaPhrase(item) ===
			normalizeDnaPhrase(attribution.content_archetype || ""),
	);
	const formatHit = matchedFormats.length > 0 || matchedArchetypes.length > 0;
	const cooldownHit =
		includesAny(normalizedContent, accountFlavor.phrase_cooldowns) ||
		(Boolean(shape) &&
			accountFlavor.phrase_cooldowns.some(
				(item) =>
					normalizeDnaPhrase(item) === normalizeDnaPhrase(String(shape)),
			));
	const matchedNotes = matchedSemanticValues(normalizedContent, [
		accountFlavor.flavor_name,
		accountFlavor.flavor_notes ?? "",
	]);
	let score =
		0.38 * (topicHit ? 100 : topic && topic !== "uncategorized" ? 70 : 56) +
		0.25 * (motifHit ? 96 : topicHit ? 74 : 58) +
		0.25 * (formatHit ? 95 : 68) +
		0.12 *
			(matchedNotes.length > 0 ? 86 : accountFlavor.flavor_notes ? 76 : 65);
	if (cooldownHit) score -= 15;
	return {
		score: clampScore(score),
		explanation: {
			matched_topics: matchedTopics,
			matched_motifs: matchedMotifs,
			matched_formats: matchedFormats,
			matched_archetypes: matchedArchetypes,
			matched_notes: matchedNotes,
			penalty_contributors: cooldownHit ? ["phrase_cooldown"] : [],
		},
	};
}

function scoreRecentSiblingRepetition(
	content: string,
	normalizedContent: string,
	recent: RecentSiblingRepetition[] | undefined,
): {
	score: number;
	exactHit: boolean;
	shapeHit: boolean;
	shapeId: string | null;
} {
	const shapeId = detectIdentityShapeId(content);
	let exactHit = false;
	let shapeHit = false;
	for (const row of recent ?? []) {
		const rowContent = normalizeDnaPhrase(row.content);
		if (!rowContent) continue;
		if (rowContent === normalizedContent) exactHit = true;
		const rowShape = row.shape_id ?? detectIdentityShapeId(row.content);
		if (shapeId && rowShape === shapeId) shapeHit = true;
	}
	return {
		score: exactHit ? 95 : shapeHit ? 72 : 20,
		exactHit,
		shapeHit,
		shapeId,
	};
}

function scoreCrossCreatorCollision(
	normalizedContent: string,
	crossCreatorPhrases: string[] | undefined,
): { score: number; hits: string[] } {
	const hits = uniqueStrings(crossCreatorPhrases ?? [], 40)
		.map(normalizeDnaPhrase)
		.filter(
			(phrase) => phrase.length > 0 && normalizedContent.includes(phrase),
		);
	return {
		score: clampScore(hits.length * 38),
		hits,
	};
}

function ruleFit(
	normalizedContent: string,
	rules: AccountDnaRule[],
): { score: number; hardBlock: boolean; review: boolean } {
	let score = 80;
	let hardBlock = false;
	let review = false;
	for (const rule of rules) {
		const value = normalizeDnaPhrase(rule.rule_value);
		const hit = value.length > 0 && normalizedContent.includes(value);
		if (!hit) continue;
		if (rule.action === "boost") score += 8 * rule.weight;
		if (rule.action === "penalize") score -= 12 * rule.weight;
		if (rule.action === "review") review = true;
		if (rule.action === "block" || rule.severity === "critical")
			hardBlock = true;
	}
	return { score: clampScore(score), hardBlock, review };
}

export function normalizeDnaPhrase(value: string): string {
	return value
		.toLowerCase()
		.replace(/https?:\/\/\S+/g, "")
		.replace(/[^\p{L}\p{N}\s]/gu, " ")
		.replace(/\s+/g, " ")
		.trim();
}

function uniqueStrings(values: unknown[], limit = 8): string[] {
	const seen = new Set<string>();
	const output: string[] = [];
	for (const value of values) {
		if (typeof value !== "string") continue;
		const trimmed = value.trim();
		const key = normalizeDnaPhrase(trimmed);
		if (!key || seen.has(key)) continue;
		seen.add(key);
		output.push(trimmed);
		if (output.length >= limit) break;
	}
	return output;
}

function commonValues(
	values: Array<string | null | undefined>,
	fallback: string[] = [],
	limit = 6,
): string[] {
	const counts = new Map<string, { label: string; count: number }>();
	for (const value of values) {
		if (!value) continue;
		const key = normalizeDnaPhrase(value);
		if (!key || key === "uncategorized" || key === "unknown") continue;
		const current = counts.get(key);
		counts.set(key, {
			label: current?.label ?? value,
			count: (current?.count ?? 0) + 1,
		});
	}
	const ranked = [...counts.values()]
		.sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
		.map((item) => item.label);
	return uniqueStrings([...ranked, ...fallback], limit);
}

const LOW_SIGNAL_DNA_VALUES = new Set([
	"general",
	"uncategorized",
	"unknown",
	"what",
	"who",
	"why",
	"how",
	"you",
	"your",
	"anybody",
	"anyone",
	"else",
	"asking",
	"asking for",
	"be honest",
	"honestly",
	"please",
	"real",
	"girls",
	"girl",
	"women",
	"wanna",
	"favorite",
	"okay",
	"prove",
	"wrong",
	"would",
	"just",
	"talk",
	"think",
	"friends",
	"with",
	"all day",
	"but honestly",
	"choose wisely",
	"someone liked your post",
	"commented on your profile picture",
	"are you ignoring me",
]);

function meaningfulDnaValues(values: unknown[], limit: number): string[] {
	return uniqueStrings(
		values.filter((value): value is string => {
			if (typeof value !== "string") return false;
			const normalized = normalizeDnaPhrase(value);
			if (!normalized || LOW_SIGNAL_DNA_VALUES.has(normalized)) return false;
			if (
				/\b(liked your post|profile picture|commented on|sent you|followed you)\b/.test(
					normalized,
				)
			)
				return false;
			if (
				normalized.length < 4 &&
				!Object.keys(CREATOR_TOPIC_ALIASES).some(
					(key) => normalizeDnaPhrase(key) === normalized,
				)
			)
				return false;
			if (normalized.length > 48) return false;
			if (normalized.split(" ").length > 5) return false;
			return true;
		}),
		limit,
	);
}

function mostCommonValue(
	values: Array<string | null | undefined>,
	fallback: string,
): string {
	const ranked = commonValues(values, [fallback], 1);
	return ranked[0] ?? fallback;
}

function makeStableCreatorId(workspaceId: string, groupId: string): string {
	return `creator_${normalizeDnaPhrase(`${workspaceId}_${groupId}`)
		.replace(/\s+/g, "_")
		.slice(0, 60)}`;
}

function flavorToken(value: string): string {
	return normalizeDnaPhrase(value).replace(/\s+/g, "_");
}

function inferFlavorName(input: {
	accountId: string;
	subArchetype?: string | null | undefined;
	topics: string[];
	motifs: string[];
	vulnerabilityLevel: number;
	flirtLevel: number;
	humorLevel: number;
	storytellingTendency: number;
}): string {
	const haystack = [...input.topics, ...input.motifs, input.subArchetype ?? ""]
		.map(normalizeDnaPhrase)
		.join(" ");
	const tokens: string[] = [];
	if (/\banime|manga|shonen|weeb\b/.test(haystack)) tokens.push("anime");
	if (/\bgaming|gamer|game|xbox|playstation|league|fortnite\b/.test(haystack))
		tokens.push("gaming");
	if (/\bgym|fitness|workout|playlist|music|song\b/.test(haystack))
		tokens.push(tokens.includes("gym") ? "music" : "gym_music");
	if (/\bdating|relationship|crush|men|boyfriend|date\b/.test(haystack))
		tokens.push("relationship");
	if (/\blate night|2am|night|sleep|awake\b/.test(haystack))
		tokens.push("late_night");
	if (
		/\bgfe|soft|lonely|miss|vulnerable\b/.test(haystack) ||
		input.vulnerabilityLevel >= 4
	)
		tokens.push("gfe");
	if (input.flirtLevel >= 4) tokens.push("flirty");
	if (input.humorLevel >= 4) tokens.push("chaotic");
	if (input.storytellingTendency >= 4) tokens.push("story");

	const unique = [...new Set(tokens.map(flavorToken).filter(Boolean))].slice(
		0,
		2,
	);
	if (unique.length > 0) return unique.join("_");
	const topic = input.topics.map(flavorToken).find(Boolean);
	if (topic && topic !== "general") return `${topic}_heavy`;
	return "main_balanced";
}

function creatorArchetypePreferences(rows: AccountDnaProfile[]): string[] {
	const values = rows.flatMap((row) => [
		row.vulnerability_level >= 3 ? "confession" : null,
		row.vulnerability_level >= 4 ? "vulnerability" : null,
		row.flirt_level >= 3 ? "identity_statement" : null,
		row.humor_level >= 3 ? "observation" : null,
		row.controversy_level >= 3 ? "hot_take" : null,
		row.storytelling_tendency >= 3 ? "mini_story" : null,
		"identity_statement",
		"observation",
	]);
	return commonValues(
		values,
		["identity_statement", "observation", "confession"],
		8,
	);
}

function flavorArchetypeBias(row: AccountDnaProfile): string[] {
	return uniqueStrings(
		[
			row.vulnerability_level >= 3 ? "confession" : null,
			row.vulnerability_level >= 4 ? "vulnerability" : null,
			row.flirt_level >= 3 ? "identity_statement" : null,
			row.humor_level >= 3 ? "observation" : null,
			row.controversy_level >= 3 ? "hot_take" : null,
			row.storytelling_tendency >= 3 ? "mini_story" : null,
			"identity_statement",
			"observation",
			"recommendation_request",
		],
		6,
	);
}

function extractCandidatePhrases(posts: AccountDnaBackfillPost[]): string[] {
	const counts = new Map<string, number>();
	for (const post of posts) {
		const words = normalizeDnaPhrase(post.content)
			.split(" ")
			.filter((word) => word.length > 2);
		for (let size = 2; size <= 3; size += 1) {
			for (let index = 0; index <= words.length - size; index += 1) {
				const phrase = words.slice(index, index + size).join(" ");
				if (GENERIC_PHRASES.includes(phrase)) continue;
				counts.set(phrase, (counts.get(phrase) ?? 0) + 1);
			}
		}
	}
	return [...counts.entries()]
		.filter(([, count]) => count > 1)
		.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
		.map(([phrase]) => phrase)
		.slice(0, 6);
}

function postPerformance(post: AccountDnaBackfillPost): number {
	return (
		Number(post.views_count ?? 0) +
		Number(post.replies_count ?? 0) * 30 +
		Number(post.likes_count ?? 0) * 5
	);
}

function inferLevel(
	posts: AccountDnaBackfillPost[],
	matcher: (post: AccountDnaBackfillPost) => boolean,
	defaultValue = 2,
): number {
	if (posts.length === 0) return defaultValue;
	const ratio = posts.filter(matcher).length / posts.length;
	return Math.max(0, Math.min(5, Math.round(ratio * 5)));
}

function median(values: number[]): number | null {
	if (values.length === 0) return null;
	const sorted = [...values].sort((a, b) => a - b);
	const middle = Math.floor(sorted.length / 2);
	if (sorted.length % 2 === 0) {
		const left = sorted[middle - 1] ?? sorted[0] ?? 0;
		const right = sorted[middle] ?? left;
		return (left + right) / 2;
	}
	return sorted[middle] ?? null;
}

function confidenceFromInput(
	input: AccountDnaBackfillInput,
	distinctTopicCount: number,
): number {
	const voiceProfile = jsonObject(input.group?.voice_profile);
	const historicalSampleConfidence = Math.min(1, input.posts.length / 5);
	const styleConsistencyConfidence =
		input.posts.length > 0 &&
		distinctTopicCount <= Math.max(3, input.posts.length / 2)
			? 0.8
			: input.posts.length > 0
				? 0.55
				: 0.2;
	const operatorInputConfidence =
		Object.keys(voiceProfile).length > 0 || input.account.bio ? 0.8 : 0.15;
	const topPerformerAlignment = input.posts.some(
		(post) => postPerformance(post) > 500,
	)
		? 0.8
		: 0.35;
	const siblingDistinctiveness = input.posts.length > 0 ? 0.7 : 0.3;
	return Number(
		(
			0.3 * historicalSampleConfidence +
			0.2 * styleConsistencyConfidence +
			0.2 * operatorInputConfidence +
			0.15 * topPerformerAlignment +
			0.15 * siblingDistinctiveness
		).toFixed(2),
	);
}

export function buildAccountDnaBackfillForAccount(
	input: AccountDnaBackfillInput,
): AccountDnaBackfillResult {
	const voiceProfile = jsonObject(input.group?.voice_profile);
	const contentStrategy = jsonObject(input.group?.content_strategy);
	const sortedPosts = [...input.posts].sort(
		(a, b) => postPerformance(b) - postPerformance(a),
	);
	const primaryTopics = commonValues(
		input.posts.map((post) => post.topic_label),
		[
			...asStringArray(contentStrategy.primary_topics),
			...asStringArray(contentStrategy.focus_topics),
		],
		6,
	);
	const secondaryTopics = commonValues(
		input.posts.map((post) => post.topic_label),
		asStringArray(contentStrategy.secondary_topics),
		8,
	);
	const tabooTopics = uniqueStrings(
		[
			...asStringArray(voiceProfile.taboo_topics),
			...asStringArray(contentStrategy.taboo_topics),
			...asStringArray(contentStrategy.topics_to_avoid),
		],
		10,
	);
	const signaturePhrases = uniqueStrings(
		[
			...asStringArray(voiceProfile.signature_phrases),
			...asStringArray(input.account.ai_config?.signature_phrases),
			...extractCandidatePhrases(input.posts),
		],
		8,
	);
	const moods = commonValues(
		input.posts.map((post) => post.emotional_frame),
		asStringArray(voiceProfile.allowed_mood_range),
		5,
	);
	const lengths = input.posts
		.map((post) => post.content.length)
		.filter((n) => n > 0);
	const medianLength = median(lengths) ?? 90;
	const confidence = confidenceFromInput(
		input,
		primaryTopics.length + secondaryTopics.length,
	);
	const archetype =
		firstString(voiceProfile.archetype, input.account.ai_config?.archetype) ??
		(input.group?.name
			? normalizeDnaPhrase(input.group.name).replace(/\s+/g, "_")
			: "threads_operator");
	const followerPromise =
		firstString(
			voiceProfile.follower_promise,
			contentStrategy.follower_promise,
			input.account.bio,
		) ?? `A reason to follow @${input.account.username ?? input.account.id}.`;
	const emotionalBaseline =
		moods[0] ?? firstString(voiceProfile.emotional_baseline) ?? "neutral";
	const dna: Omit<AccountDnaProfile, "id"> = {
		workspace_id: input.workspaceId,
		group_id: input.groupId ?? null,
		account_id: input.account.id,
		version: 1,
		status: confidence >= 0.65 ? "active" : "draft",
		confidence,
		archetype,
		sub_archetype:
			firstString(voiceProfile.sub_archetype, primaryTopics[0]) ?? null,
		follower_promise: followerPromise,
		identity_summary:
			firstString(voiceProfile.identity_summary) ??
			`${input.account.username ?? input.account.display_name ?? input.account.id} posts ${primaryTopics.slice(0, 3).join(", ") || "account-specific"} material with a ${emotionalBaseline} baseline.`,
		backstory_facts: uniqueStrings(
			asStringArray(voiceProfile.backstory_facts),
			8,
		),
		recurring_motifs: uniqueStrings(
			[
				...asStringArray(voiceProfile.recurring_motifs),
				...primaryTopics,
				...signaturePhrases.slice(0, 3),
			],
			8,
		),
		recurring_situations: uniqueStrings(
			[
				...asStringArray(voiceProfile.recurring_situations),
				...sortedPosts.slice(0, 2).map((post) => post.content.slice(0, 140)),
			],
			6,
		),
		signature_beliefs: uniqueStrings(
			asStringArray(voiceProfile.signature_beliefs),
			8,
		),
		primary_topics: primaryTopics.length > 0 ? primaryTopics : ["general"],
		secondary_topics: secondaryTopics,
		taboo_topics: tabooTopics,
		signature_phrases: signaturePhrases,
		banned_phrases: uniqueStrings(
			[
				...asStringArray(voiceProfile.banned_phrases),
				...DEFAULT_BANNED_PHRASES,
			],
			12,
		),
		vocabulary_fingerprint: {
			signature_words: uniqueStrings(
				[
					...asStringArray(voiceProfile.signature_words),
					...signaturePhrases.flatMap((phrase) => phrase.split(/\s+/)),
				],
				12,
			),
			avoid_words: uniqueStrings(asStringArray(voiceProfile.avoid_words), 12),
			sentence_starters: uniqueStrings(
				input.posts.map((post) =>
					post.content.split(/\s+/).slice(0, 3).join(" "),
				),
				8,
			),
		},
		emoji_policy:
			(firstString(voiceProfile.emoji_policy) as EmojiPolicy | null) ??
			"minimal",
		punctuation_habits: jsonObject(voiceProfile.punctuation_habits),
		casing_style:
			(firstString(voiceProfile.casing_style) as CasingStyle | null) ??
			"lowercase",
		average_length_min: Math.max(12, Math.round(medianLength * 0.55)),
		average_length_max: Math.max(60, Math.round(medianLength * 1.65)),
		emotional_baseline: emotionalBaseline,
		allowed_mood_range: moods.length > 0 ? moods : [emotionalBaseline],
		cta_posture:
			(firstString(voiceProfile.cta_posture) as CtaPosture | null) ?? "soft",
		controversy_level: inferLevel(
			input.posts,
			(post) =>
				post.hook_type === "hot_take" ||
				/hot take|unpopular/i.test(post.content),
			Number(voiceProfile.controversy_level ?? 2),
		),
		humor_level: inferLevel(
			input.posts,
			(post) => /lol|lmao|funny|joke/i.test(post.content),
			Number(voiceProfile.humor_level ?? 2),
		),
		storytelling_tendency: inferLevel(
			input.posts,
			(post) => post.content.length > 120 || post.hook_type === "mini_story",
			Number(voiceProfile.storytelling_tendency ?? 2),
		),
		vulnerability_level: inferLevel(
			input.posts,
			(post) =>
				/vulnerable|lonely|miss|need|hurt/i.test(
					`${post.emotional_frame ?? ""} ${post.content}`,
				),
			Number(voiceProfile.vulnerability_level ?? 2),
		),
		flirt_level: inferLevel(
			input.posts,
			(post) =>
				/flirt|date|crush|kiss|come here/i.test(
					`${post.topic_label ?? ""} ${post.content}`,
				),
			Number(voiceProfile.flirt_level ?? 2),
		),
	};

	const examples = sortedPosts.slice(0, 4).map((post) => ({
		workspace_id: input.workspaceId,
		group_id: input.groupId ?? null,
		account_id: input.account.id,
		source_type:
			postPerformance(post) > 500 ? "top_performer" : "historical_post",
		source_id: post.id ?? null,
		content: post.content,
		example_type: postPerformance(post) > 500 ? "canonical" : "good",
		weight: postPerformance(post) > 500 ? 1.3 : 1,
		hook_type: post.hook_type ?? null,
		topic_label: post.topic_label ?? null,
		format_type: post.format_type ?? null,
		emotional_frame: post.emotional_frame ?? null,
		reply_mechanism: post.reply_mechanism ?? null,
		content_length_bucket: post.content_length_bucket ?? null,
		media_style: post.media_style ?? null,
		reason: "account_dna_backfill",
	}));
	const weakExamples = [...input.posts]
		.sort((a, b) => postPerformance(a) - postPerformance(b))
		.slice(0, Math.min(2, input.posts.length))
		.filter((post) => postPerformance(post) < 100)
		.map((post) => ({
			workspace_id: input.workspaceId,
			group_id: input.groupId ?? null,
			account_id: input.account.id,
			source_type: "historical_post",
			source_id: post.id ?? null,
			content: post.content,
			example_type: "anti_example",
			weight: 0.8,
			hook_type: post.hook_type ?? null,
			topic_label: post.topic_label ?? null,
			format_type: post.format_type ?? null,
			emotional_frame: post.emotional_frame ?? null,
			reply_mechanism: post.reply_mechanism ?? null,
			content_length_bucket: post.content_length_bucket ?? null,
			media_style: post.media_style ?? null,
			reason: "weak_or_off_dna_historical_post",
		}));
	const rules = [
		...signaturePhrases.map((phrase) => ({
			workspace_id: input.workspaceId,
			group_id: input.groupId ?? null,
			account_id: input.account.id,
			rule_type: "owned_phrase",
			rule_value: phrase,
			action: "boost",
			severity: "medium",
			weight: 1,
			reason: "account_dna_backfill_signature_phrase",
		})),
		...dna.banned_phrases.map((phrase) => ({
			workspace_id: input.workspaceId,
			group_id: input.groupId ?? null,
			account_id: input.account.id,
			rule_type: "banned_phrase",
			rule_value: phrase,
			action: "penalize",
			severity: "medium",
			weight: 1,
			reason: "account_dna_backfill_banned_phrase",
		})),
		...tabooTopics.map((topic) => ({
			workspace_id: input.workspaceId,
			group_id: input.groupId ?? null,
			account_id: input.account.id,
			rule_type: "topic_ban",
			rule_value: topic,
			action: "review",
			severity: "high",
			weight: 1,
			reason: "account_dna_backfill_taboo_topic",
		})),
	];

	return {
		dna,
		examples: input.posts.length > 0 ? [...examples, ...weakExamples] : [],
		rules,
	};
}

export function buildCreatorDnaBackfillFromAccountDna(
	input: CreatorDnaBackfillInput,
): CreatorDnaBackfillResult {
	const activeRows = input.accountDnaRows.filter(
		(row) => row.status === "active",
	);
	const rows = activeRows.length > 0 ? activeRows : input.accountDnaRows;
	const creatorId = makeStableCreatorId(input.workspaceId, input.groupId);
	const creatorKey = mostCommonValue(
		rows.map((row) => row.archetype),
		normalizeDnaPhrase(input.groupName ?? input.groupId).replace(/\s+/g, "_") ||
			"creator",
	);
	const creatorName =
		input.groupName?.replace(/\s+[—-]\s+.*/, "").trim() ||
		creatorKey
			.split("_")
			.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
			.join(" ");
	const coreTopics = meaningfulDnaValues(
		commonValues(
			rows.flatMap((row) => [...row.primary_topics, ...row.secondary_topics]),
			["dating", "music"],
			24,
		),
		16,
	);
	const coreMotifs = meaningfulDnaValues(
		commonValues(
			rows.flatMap((row) => [
				...row.recurring_motifs,
				...row.recurring_situations,
				...row.signature_beliefs,
			]),
			coreTopics,
			24,
		),
		16,
	);
	const sharedPhraseBank = meaningfulDnaValues(
		commonValues(
			rows.flatMap((row) => [
				...row.signature_phrases,
				...(row.vocabulary_fingerprint.signature_words ?? []),
				...(row.vocabulary_fingerprint.filler_words ?? []),
			]),
			[],
			30,
		),
		18,
	);
	const allowedMoods = commonValues(
		rows.flatMap((row) => [row.emotional_baseline, ...row.allowed_mood_range]),
		["playful"],
		8,
	);
	const tabooTopics = commonValues(
		rows.flatMap((row) => row.taboo_topics),
		[],
		12,
	);
	const sharedVoiceTraits = meaningfulDnaValues(
		rows.flatMap((row) => [
			row.casing_style,
			row.emoji_policy === "none" || row.emoji_policy === "minimal"
				? "low emoji"
				: `${row.emoji_policy} emoji`,
			row.cta_posture ? `${row.cta_posture} cta` : null,
			row.humor_level >= 3 ? "playful" : null,
			row.flirt_level >= 3 ? "flirty" : null,
			row.vulnerability_level >= 3 ? "vulnerable" : null,
			row.storytelling_tendency >= 3 ? "first-person self-aware" : null,
			"casual short-form",
			"low punctuation",
			...(row.vocabulary_fingerprint.signature_words ?? []),
		]),
		18,
	);
	const signatureBeliefs = commonValues(
		meaningfulDnaValues(
			rows.flatMap((row) => row.signature_beliefs),
			20,
		),
		[],
		12,
	);
	const followerPromise = mostCommonValue(
		rows.map((row) => row.follower_promise),
		`${creatorName} creator identity`,
	);
	const identitySummary = mostCommonValue(
		rows.map((row) => row.identity_summary),
		`${creatorName} posts ${coreTopics.slice(0, 3).join(", ")} with a consistent creator voice.`,
	);

	const creatorDna: CreatorDnaProfile = {
		id: creatorId,
		workspace_id: input.workspaceId,
		group_id: input.groupId,
		version: 1,
		status: rows.some((row) => row.confidence >= 0.65) ? "active" : "draft",
		confidence: Number(
			(
				rows.reduce((sum, row) => sum + Number(row.confidence ?? 0), 0) /
				Math.max(rows.length, 1)
			).toFixed(2),
		),
		creator_key: creatorKey,
		creator_name: creatorName,
		archetype: creatorKey,
		follower_promise: followerPromise,
		identity_summary: identitySummary,
		core_topics: coreTopics,
		core_motifs: coreMotifs,
		signature_beliefs: signatureBeliefs,
		shared_voice_traits: uniqueStrings(
			[...sharedVoiceTraits, ...creatorArchetypePreferences(rows)],
			22,
		),
		allowed_moods: allowedMoods,
		shared_phrase_bank: sharedPhraseBank,
		taboo_topics: tabooTopics,
	};

	const accountFlavors = rows.map((row) => {
		const accountOnlyTopics = row.primary_topics.filter(
			(topic) =>
				!coreTopics
					.slice(0, 3)
					.map(normalizeDnaPhrase)
					.includes(normalizeDnaPhrase(topic)),
		);
		const topicEmphasis = meaningfulDnaValues(
			[
				...accountOnlyTopics,
				...row.primary_topics,
				...row.secondary_topics,
				...(row.vocabulary_fingerprint.signature_words ?? []),
			],
			10,
		);
		const motifEmphasis = meaningfulDnaValues(
			[
				...row.recurring_motifs,
				...row.recurring_situations,
				...row.signature_beliefs,
			],
			10,
		);
		const archetypeBias = flavorArchetypeBias(row);
		return {
			id: `flavor_${normalizeDnaPhrase(row.account_id).replace(/\s+/g, "_")}`,
			workspace_id: input.workspaceId,
			group_id: input.groupId,
			account_id: row.account_id,
			creator_dna_id: creatorId,
			status: row.status,
			flavor_name: inferFlavorName({
				accountId: row.account_id,
				subArchetype: row.sub_archetype,
				topics: topicEmphasis,
				motifs: motifEmphasis,
				vulnerabilityLevel: row.vulnerability_level,
				flirtLevel: row.flirt_level,
				humorLevel: row.humor_level,
				storytellingTendency: row.storytelling_tendency,
			}),
			topic_emphasis: topicEmphasis,
			motif_emphasis: motifEmphasis,
			format_emphasis: uniqueStrings(
				[
					row.storytelling_tendency >= 3 ? "mini_story" : "text_post",
					...archetypeBias,
				],
				4,
			),
			archetype_bias: archetypeBias,
			phrase_cooldowns: meaningfulDnaValues(
				[
					...row.signature_phrases,
					...(row.vocabulary_fingerprint.sentence_starters ?? []),
				],
				10,
			),
			flavor_notes: `${row.account_id} should keep ${creatorName}'s creator voice while emphasizing ${topicEmphasis.slice(0, 4).join(", ") || "balanced topics"} through ${archetypeBias.slice(0, 3).join(", ")} shapes and ${motifEmphasis.slice(0, 3).join(", ") || "shared creator motifs"}.`,
		};
	});

	return { creatorDna, accountFlavors };
}

export async function backfillCreatorDnaV1(input: {
	workspaceId: string;
	groupIds?: string[] | undefined;
	force?: boolean | undefined;
	dryRun?: boolean | undefined;
	client?: SupabaseClient;
}): Promise<CreatorDnaBackfillRunResult> {
	const client = input.client ?? getSupabaseAny();
	const result: CreatorDnaBackfillRunResult = {
		groupsConsidered: 0,
		creatorsCreated: 0,
		flavorsCreated: 0,
		skipped: 0,
		failed: 0,
		errors: [],
	};

	let dnaQuery = client
		.from("account_dna")
		.select("*")
		.eq("workspace_id", input.workspaceId)
		.eq("status", "active")
		.not("group_id", "is", null);
	if (input.groupIds && input.groupIds.length > 0) {
		dnaQuery = dnaQuery.in("group_id", input.groupIds);
	}
	const { data: dnaRows, error: dnaError } = await dnaQuery;
	if (dnaError) throw dnaError;

	const rowsByGroup = new Map<string, AccountDnaProfile[]>();
	for (const row of (dnaRows ?? []) as Array<Record<string, unknown>>) {
		const mapped = mapDnaRow(row);
		if (!mapped.group_id) continue;
		const rows = rowsByGroup.get(mapped.group_id) ?? [];
		rows.push(mapped);
		rowsByGroup.set(mapped.group_id, rows);
	}
	result.groupsConsidered = rowsByGroup.size;
	if (rowsByGroup.size === 0) return result;

	const groupIds = [...rowsByGroup.keys()];
	const { data: groupRows } = await client
		.from("account_groups")
		.select("id, name")
		.in("id", groupIds);
	const groupNameById = new Map(
		((groupRows ?? []) as Array<Record<string, unknown>>).map((row) => [
			String(row.id),
			(row.name as string | null | undefined) ?? String(row.id),
		]),
	);

	for (const [groupId, rows] of rowsByGroup) {
		try {
			const existingQuery = client
				.from("creator_dna")
				.select("id")
				.eq("workspace_id", input.workspaceId)
				.eq("group_id", groupId)
				.eq("status", "active")
				.limit(1)
				.maybeSingle();
			const { data: existingCreator } = await existingQuery;
			if (existingCreator && !input.force) {
				result.skipped += 1;
				continue;
			}
			const built = buildCreatorDnaBackfillFromAccountDna({
				workspaceId: input.workspaceId,
				groupId,
				groupName: groupNameById.get(groupId) ?? null,
				accountDnaRows: rows,
			});
			if (input.dryRun) {
				result.creatorsCreated += 1;
				result.flavorsCreated += built.accountFlavors.length;
				continue;
			}
			if (input.force) {
				await client
					.from("creator_dna")
					.update({ status: "retired", updated_at: new Date().toISOString() })
					.eq("workspace_id", input.workspaceId)
					.eq("group_id", groupId)
					.eq("status", "active");
				await client
					.from("account_flavor")
					.update({ status: "retired", updated_at: new Date().toISOString() })
					.eq("workspace_id", input.workspaceId)
					.eq("group_id", groupId)
					.eq("status", "active");
			}
			const { id: _stableId, ...creatorInsert } = built.creatorDna;
			const { data: insertedCreator, error: creatorError } = await client
				.from("creator_dna")
				.insert({
					...creatorInsert,
					source_summary: {
						account_dna_count: rows.length,
						backfilled_at: new Date().toISOString(),
					},
					generated_from: "account_dna_backfill",
				})
				.select("id")
				.single();
			if (creatorError) throw creatorError;
			const creatorId = String(
				(insertedCreator as Record<string, unknown>).id ?? "",
			);
			result.creatorsCreated += 1;

			for (const flavor of built.accountFlavors) {
				const { id: _flavorStableId, ...flavorInsert } = flavor;
				const sourceDna = rows.find(
					(row) => row.account_id === flavor.account_id,
				);
				const { data: insertedFlavor, error: flavorError } = await client
					.from("account_flavor")
					.insert({
						...flavorInsert,
						creator_dna_id: creatorId,
						source_account_dna_id: sourceDna?.id ?? null,
						source_summary: {
							source_account_dna_version: sourceDna?.version ?? null,
						},
					})
					.select("id")
					.single();
				if (flavorError) throw flavorError;
				const flavorId = String(
					(insertedFlavor as Record<string, unknown>).id ?? "",
				);
				await client
					.from("account_dna")
					.update({
						creator_dna_id: creatorId,
						account_flavor_id: flavorId,
						updated_at: new Date().toISOString(),
					})
					.eq("id", sourceDna?.id ?? "");
				result.flavorsCreated += 1;
			}
		} catch (error) {
			result.failed += 1;
			result.errors.push({ group_id: groupId, error: String(error) });
		}
	}

	return result;
}

export function buildAccountDnaOpsSummary(
	input: AccountDnaOpsSummaryInput,
): AccountDnaOpsSummary {
	const profileByAccount = new Map<string, Record<string, unknown>>();
	for (const profile of input.profiles) {
		const accountId = String(profile.account_id ?? "");
		if (!accountId || profileByAccount.has(accountId)) continue;
		profileByAccount.set(accountId, profile);
	}
	const metricByAccount = new Map<string, Record<string, unknown>>();
	for (const metric of input.metrics) {
		const accountId = String(metric.account_id ?? "");
		if (!accountId || metricByAccount.has(accountId)) continue;
		metricByAccount.set(accountId, metric);
	}
	const profiles = [...profileByAccount.values()].map((profile) => {
		const metric = metricByAccount.get(String(profile.account_id ?? "")) ?? {};
		return {
			...profile,
			uniqueness_score: metric.uniqueness_score ?? null,
			sibling_collision_score: metric.sibling_collision_score ?? null,
			genericness_score: metric.genericness_score ?? null,
			drift_score: metric.drift_score ?? null,
			uniqueness_decision: metric.decision ?? null,
			uniqueness_reason: metric.reason ?? null,
			uniqueness_computed_at: metric.computed_at ?? null,
		} as Record<string, unknown>;
	});
	const activeProfiles = profiles.filter(
		(profile) => profile.status === "active",
	).length;
	const draftProfiles = profiles.filter(
		(profile) => profile.status === "draft",
	).length;
	const metricValues = (key: string) =>
		input.metrics
			.map((metric) => Number(metric[key]))
			.filter((value) => Number.isFinite(value));
	const avg = (values: number[]) =>
		values.length > 0
			? Math.round(
					values.reduce((sum, value) => sum + value, 0) / values.length,
				)
			: null;
	return {
		totalAutoposterAccounts: input.accountIds.length,
		activeProfiles,
		draftProfiles,
		missingProfiles: Math.max(
			0,
			input.accountIds.length - profileByAccount.size,
		),
		reviewQueueCount: input.reviewItems.length,
		avgUniquenessScore: avg(metricValues("uniqueness_score")),
		avgGenericnessScore: avg(metricValues("genericness_score")),
		profiles,
		reviewItems: input.reviewItems,
	};
}

export function evaluateAccountDna(
	input: AccountDnaEvaluationInput,
): AccountDnaEvaluation {
	if (!input.dna || input.dna.status !== "active") {
		return {
			dna_id: null,
			dna_version: null,
			dna_fit_score: null,
			voice_fit_score: null,
			topic_fit_score: null,
			mood_fit_score: null,
			uniqueness_score: null,
			sibling_collision_score: null,
			genericness_score: null,
			creator_fit_score: null,
			account_flavor_score: null,
			recent_sibling_repetition_score: null,
			cross_creator_collision_score: null,
			decision: "pass_unscored",
			reasons: ["no_active_dna"],
		};
	}

	const dna = input.dna;
	const normalizedContent = normalizeDnaPhrase(input.content);
	const voice = scoreVoice(
		input.content,
		normalizedContent,
		dna,
		input.rules,
		input.siblingRules,
	);
	const topic = scoreTopic(normalizedContent, dna, input.attribution);
	const mood = scoreMood(dna, input.attribution);
	const genericnessScore = scoreGenericness(
		normalizedContent,
		dna,
		input.attribution,
	);
	const siblingCollision = scoreSiblingCollision(
		normalizedContent,
		input.siblingRules.filter((rule) => rule.scope !== "same_creator"),
	);
	const creatorFit = scoreCreatorFitDetailed(
		input.content,
		normalizedContent,
		input.creatorDna,
		input.accountFlavor,
		input.attribution,
	);
	const creatorFitScore = creatorFit.score;
	const accountFlavorFit = scoreAccountFlavorFitDetailed(
		normalizedContent,
		input.accountFlavor,
		input.attribution,
	);
	const accountFlavorScore = accountFlavorFit.score;
	const recentSiblingRepetition = scoreRecentSiblingRepetition(
		input.content,
		normalizedContent,
		input.recentSiblingRepetitions,
	);
	const crossCreatorCollision = scoreCrossCreatorCollision(
		normalizedContent,
		input.crossCreatorPhrases,
	);
	const rules = ruleFit(normalizedContent, input.rules);
	const followerPromiseFit = includesAny(normalizedContent, [
		dna.follower_promise,
		...dna.signature_beliefs,
	])
		? 90
		: 65;
	const exampleSimilarityScore = includesAny(normalizedContent, [
		...dna.signature_phrases,
		...dna.recurring_situations,
	])
		? 85
		: 65;
	const lengthStyleFit = textLengthFit(input.content, dna);
	const genericnessPenalty =
		genericnessScore >= 70 ? 12 : genericnessScore >= 50 ? 6 : 0;
	const siblingCollisionPenalty = siblingCollision.score >= 75 ? 8 : 0;
	const dnaFitScore = clampScore(
		0.25 * voice.score +
			0.2 * topic.score +
			0.15 * mood.score +
			0.15 * rules.score +
			0.1 * followerPromiseFit +
			0.1 * exampleSimilarityScore +
			0.05 * lengthStyleFit -
			genericnessPenalty -
			siblingCollisionPenalty,
	);
	const uniquenessScore = clampScore(
		100 -
			0.25 * siblingCollision.score -
			0.2 * genericnessScore -
			(input.attribution.hook_type === "question" ? 8 : 0) +
			(countMatches(normalizedContent, dna.signature_phrases) > 0 ? 8 : 0),
	);
	const reasons: string[] = [];
	const legacyDnaThreshold = effectiveLegacyDnaThreshold({
		creatorFitScore,
		accountFlavorScore,
		genericnessScore,
	});
	if (topic.tabooHit) reasons.push("taboo_topic");
	if (voice.bannedHit) reasons.push("banned_phrase");
	if (voice.siblingHit || siblingCollision.score >= 75)
		reasons.push("cross_creator_collision");
	if (genericnessScore >= 70) reasons.push("high_genericness");
	if (dnaFitScore < legacyDnaThreshold) reasons.push("low_dna_fit");
	if (uniquenessScore < 55) reasons.push("low_uniqueness");
	const creatorFitHardFloor = 65;
	const creatorFitReviewFloor = 60;
	const hasStrongFlavorSupport =
		accountFlavorScore !== null && accountFlavorScore >= 70;
	if (creatorFitScore !== null && creatorFitScore < creatorFitHardFloor)
		reasons.push("low_creator_fit");
	if (accountFlavorScore !== null && accountFlavorScore < 55)
		reasons.push("low_account_flavor_fit");
	if (recentSiblingRepetition.exactHit)
		reasons.push("recent_phrase_repetition");
	if (recentSiblingRepetition.shapeHit) reasons.push("recent_shape_repetition");
	if (crossCreatorCollision.score >= 75)
		reasons.push("cross_creator_collision");
	if (!mood.moodAllowed && (creatorFitScore === null || creatorFitScore < 65)) {
		reasons.push("mood_outside_allowed_range");
	}
	if (rules.review) reasons.push("dna_rule_review");

	let decision: AccountDnaDecision = "pass";
	if (rules.hardBlock || topic.tabooHit || voice.bannedHit) decision = "block";
	if (
		(creatorFitScore !== null &&
			creatorFitScore < creatorFitHardFloor &&
			!(
				creatorFitScore >= creatorFitReviewFloor &&
				hasStrongFlavorSupport &&
				genericnessScore < 60
			)) ||
		(accountFlavorScore !== null && accountFlavorScore < 55) ||
		recentSiblingRepetition.score >= 65 ||
		crossCreatorCollision.score >= 75
	) {
		decision = "regenerate";
	}
	if (
		dnaFitScore < legacyDnaThreshold ||
		uniquenessScore < 45 ||
		genericnessScore >= 70
	) {
		decision = "regenerate";
	}
	if (siblingCollision.score >= 85) decision = "regenerate";
	if (
		(input.predictedViralScore ?? 0) >= 90 &&
		dnaFitScore < legacyDnaThreshold
	) {
		decision = "needs_review";
		reasons.push("high_performance_low_dna_fit");
	} else if (
		dnaFitScore < Math.min(55, legacyDnaThreshold) &&
		decision !== "block" &&
		siblingCollision.score < 75
	) {
		decision = "needs_review";
	}

	return {
		dna_id: dna.id,
		dna_version: dna.version,
		dna_fit_score: dnaFitScore,
		voice_fit_score: voice.score,
		topic_fit_score: topic.score,
		mood_fit_score: mood.score,
		uniqueness_score: uniquenessScore,
		sibling_collision_score: siblingCollision.score,
		genericness_score: genericnessScore,
		creator_fit_score: creatorFitScore,
		account_flavor_score: accountFlavorScore,
		recent_sibling_repetition_score: recentSiblingRepetition.score,
		cross_creator_collision_score: crossCreatorCollision.score,
		decision,
		reasons: [...new Set(reasons)],
		fit_explanation: {
			creator: creatorFit.explanation ?? undefined,
			account_flavor: accountFlavorFit.explanation ?? undefined,
		},
	};
}

function mapDnaRow(row: Record<string, unknown>): AccountDnaProfile {
	return {
		id: String(row.id),
		workspace_id: String(row.workspace_id),
		group_id: (row.group_id as string | null | undefined) ?? null,
		account_id: String(row.account_id),
		version: Number(row.version ?? 1),
		status: (row.status as DnaStatus) ?? "draft",
		confidence: Number(row.confidence ?? 0),
		archetype: String(row.archetype ?? "unknown"),
		sub_archetype: (row.sub_archetype as string | null | undefined) ?? null,
		follower_promise: String(row.follower_promise ?? ""),
		identity_summary: String(row.identity_summary ?? ""),
		backstory_facts: asStringArray(row.backstory_facts),
		recurring_motifs: asStringArray(row.recurring_motifs),
		recurring_situations: asStringArray(row.recurring_situations),
		signature_beliefs: asStringArray(row.signature_beliefs),
		primary_topics: asStringArray(row.primary_topics),
		secondary_topics: asStringArray(row.secondary_topics),
		taboo_topics: asStringArray(row.taboo_topics),
		signature_phrases: asStringArray(row.signature_phrases),
		banned_phrases: asStringArray(row.banned_phrases),
		vocabulary_fingerprint:
			row.vocabulary_fingerprint &&
			typeof row.vocabulary_fingerprint === "object" &&
			!Array.isArray(row.vocabulary_fingerprint)
				? (row.vocabulary_fingerprint as AccountDnaProfile["vocabulary_fingerprint"])
				: {},
		emoji_policy: (row.emoji_policy as EmojiPolicy) ?? "minimal",
		punctuation_habits:
			row.punctuation_habits &&
			typeof row.punctuation_habits === "object" &&
			!Array.isArray(row.punctuation_habits)
				? (row.punctuation_habits as Record<string, unknown>)
				: {},
		casing_style: (row.casing_style as CasingStyle) ?? "lowercase",
		average_length_min: Number(row.average_length_min ?? 20),
		average_length_max: Number(row.average_length_max ?? 140),
		emotional_baseline: String(row.emotional_baseline ?? "neutral"),
		allowed_mood_range: asStringArray(row.allowed_mood_range),
		cta_posture: (row.cta_posture as CtaPosture) ?? "soft",
		controversy_level: Number(row.controversy_level ?? 2),
		humor_level: Number(row.humor_level ?? 2),
		storytelling_tendency: Number(row.storytelling_tendency ?? 2),
		vulnerability_level: Number(row.vulnerability_level ?? 2),
		flirt_level: Number(row.flirt_level ?? 2),
	};
}

function mapCreatorDnaRow(row: Record<string, unknown>): CreatorDnaProfile {
	return {
		id: String(row.id ?? ""),
		workspace_id: String(row.workspace_id ?? ""),
		group_id: (row.group_id as string | null | undefined) ?? null,
		version: Number(row.version ?? 1),
		status: (row.status as DnaStatus | null | undefined) ?? "draft",
		confidence: Number(row.confidence ?? 0),
		creator_key: String(row.creator_key ?? row.archetype ?? ""),
		creator_name: String(row.creator_name ?? row.creator_key ?? "Creator"),
		archetype: String(row.archetype ?? row.creator_key ?? "creator"),
		follower_promise: String(row.follower_promise ?? ""),
		identity_summary: String(row.identity_summary ?? ""),
		core_topics: asStringArray(row.core_topics),
		core_motifs: asStringArray(row.core_motifs),
		signature_beliefs: asStringArray(row.signature_beliefs),
		shared_voice_traits: asStringArray(row.shared_voice_traits),
		allowed_moods: asStringArray(row.allowed_moods),
		shared_phrase_bank: asStringArray(row.shared_phrase_bank),
		taboo_topics: asStringArray(row.taboo_topics),
	};
}

function mapAccountFlavorRow(
	row: Record<string, unknown>,
): AccountFlavorProfile {
	return {
		id: String(row.id ?? ""),
		workspace_id: String(row.workspace_id ?? ""),
		group_id: (row.group_id as string | null | undefined) ?? null,
		account_id: String(row.account_id ?? ""),
		creator_dna_id: String(row.creator_dna_id ?? ""),
		status: (row.status as DnaStatus | null | undefined) ?? "draft",
		flavor_name: String(row.flavor_name ?? "balanced"),
		topic_emphasis: asStringArray(row.topic_emphasis),
		motif_emphasis: asStringArray(row.motif_emphasis),
		format_emphasis: asStringArray(row.format_emphasis),
		archetype_bias: asStringArray(row.archetype_bias),
		phrase_cooldowns: asStringArray(row.phrase_cooldowns),
		flavor_notes: (row.flavor_notes as string | null | undefined) ?? null,
	};
}

function mapRuleRow(row: Record<string, unknown>): AccountDnaRule {
	return {
		id: String(row.id),
		account_id: String(row.account_id),
		rule_type: String(row.rule_type),
		rule_value: String(row.rule_value),
		action: (row.action as AccountDnaRule["action"]) ?? "penalize",
		severity: (row.severity as AccountDnaRule["severity"]) ?? "medium",
		weight: Number(row.weight ?? 1),
		rule_payload:
			row.rule_payload &&
			typeof row.rule_payload === "object" &&
			!Array.isArray(row.rule_payload)
				? (row.rule_payload as Record<string, unknown>)
				: {},
	};
}

export async function loadAccountDnaContext(input: {
	workspaceId: string;
	groupId?: string | null | undefined;
	accountId?: string | null | undefined;
	client?: SupabaseClient;
}): Promise<{
	dna: AccountDnaProfile | null;
	rules: AccountDnaRule[];
	siblingRules: AccountDnaRule[];
}> {
	if (!input.accountId) return { dna: null, rules: [], siblingRules: [] };
	const client = input.client ?? getSupabaseAny();
	try {
		const { data: dnaRow } = await client
			.from("account_dna")
			.select("*")
			.eq("workspace_id", input.workspaceId)
			.eq("account_id", input.accountId)
			.eq("status", "active")
			.order("version", { ascending: false })
			.limit(1)
			.maybeSingle();
		const dna = dnaRow ? mapDnaRow(dnaRow as Record<string, unknown>) : null;
		if (!dna) return { dna: null, rules: [], siblingRules: [] };

		const { data: ownRuleRows } = await client
			.from("account_dna_rules")
			.select("*")
			.eq("dna_id", dna.id)
			.or(`expires_at.is.null,expires_at.gt.${new Date().toISOString()}`);
		const rules = (ownRuleRows || []).map((row: unknown) =>
			mapRuleRow(row as Record<string, unknown>),
		);

		let siblingRulesQuery = client
			.from("account_dna_rules")
			.select("*")
			.eq("workspace_id", input.workspaceId)
			.neq("account_id", input.accountId)
			.in("rule_type", ["owned_phrase", "sibling_avoid", "banned_phrase"])
			.or(`expires_at.is.null,expires_at.gt.${new Date().toISOString()}`);
		if (input.groupId) {
			siblingRulesQuery = siblingRulesQuery.eq("group_id", input.groupId);
		}
		const { data: siblingRuleRows } = await siblingRulesQuery;
		const siblingRules = (siblingRuleRows || []).map((row: unknown) =>
			mapRuleRow(row as Record<string, unknown>),
		);

		return { dna, rules, siblingRules };
	} catch {
		return { dna: null, rules: [], siblingRules: [] };
	}
}

export async function loadCreatorIdentityContext(input: {
	workspaceId: string;
	groupId?: string | null | undefined;
	accountId?: string | null | undefined;
	client?: SupabaseClient;
}): Promise<{
	creatorDna: CreatorDnaProfile | null;
	accountFlavor: AccountFlavorProfile | null;
}> {
	if (!input.groupId || !input.accountId) {
		return { creatorDna: null, accountFlavor: null };
	}
	const client = input.client ?? getSupabaseAny();
	try {
		const { data: creatorRow } = await client
			.from("creator_dna")
			.select("*")
			.eq("workspace_id", input.workspaceId)
			.eq("group_id", input.groupId)
			.eq("status", "active")
			.order("version", { ascending: false })
			.limit(1)
			.maybeSingle();
		const creatorDna = creatorRow
			? mapCreatorDnaRow(creatorRow as Record<string, unknown>)
			: null;
		if (!creatorDna) return { creatorDna: null, accountFlavor: null };

		const { data: flavorRow } = await client
			.from("account_flavor")
			.select("*")
			.eq("workspace_id", input.workspaceId)
			.eq("account_id", input.accountId)
			.eq("creator_dna_id", creatorDna.id)
			.eq("status", "active")
			.order("updated_at", { ascending: false })
			.limit(1)
			.maybeSingle();

		return {
			creatorDna,
			accountFlavor: flavorRow
				? mapAccountFlavorRow(flavorRow as Record<string, unknown>)
				: null,
		};
	} catch {
		return { creatorDna: null, accountFlavor: null };
	}
}

export async function backfillAccountDnaForWorkspace(input: {
	workspaceId: string;
	client?: SupabaseClient;
	force?: boolean | undefined;
	limit?: number | undefined;
	dryRun?: boolean | undefined;
}): Promise<{
	accountsConsidered: number;
	created: number;
	skipped: number;
	failed: number;
	examplesCreated: number;
	rulesCreated: number;
	dryRun: boolean;
	errors: Array<{ account_id: string; error: string }>;
}> {
	const client = input.client ?? getSupabaseAny();
	const force = input.force === true;
	const dryRun = input.dryRun === true;
	const limit = Math.min(Math.max(input.limit ?? 250, 1), 1000);
	const result = {
		accountsConsidered: 0,
		created: 0,
		skipped: 0,
		failed: 0,
		examplesCreated: 0,
		rulesCreated: 0,
		dryRun,
		errors: [] as Array<{ account_id: string; error: string }>,
	};

	const { data: groupConfigs, error: groupConfigError } = await client
		.from("auto_post_group_config")
		.select("group_id, enabled, platform")
		.eq("workspace_id", input.workspaceId)
		.eq("enabled", true)
		.limit(500);
	if (groupConfigError) throw groupConfigError;

	const groupIds = [
		...new Set(
			((groupConfigs ?? []) as Array<Record<string, unknown>>)
				.filter((row) => {
					const platform = String(row.platform ?? "threads");
					return (
						platform === "threads" || platform === "both" || platform === "null"
					);
				})
				.map((row) => String(row.group_id))
				.filter(Boolean),
		),
	];
	if (groupIds.length === 0) return result;

	const { data: groupRows, error: groupsError } = await client
		.from("account_groups")
		.select("id, name, account_ids, voice_profile, content_strategy")
		.in("id", groupIds);
	if (groupsError) throw groupsError;

	const groups = (groupRows ?? []) as Array<Record<string, unknown>>;
	const groupById = new Map(groups.map((group) => [String(group.id), group]));
	const accountToGroup = new Map<string, string>();
	for (const group of groups) {
		for (const accountId of asStringArray(group.account_ids)) {
			if (!accountToGroup.has(accountId))
				accountToGroup.set(accountId, String(group.id));
		}
	}
	const accountIds = [...accountToGroup.keys()].slice(0, limit);
	result.accountsConsidered = accountIds.length;
	if (accountIds.length === 0) return result;

	const { data: existingDnaRows, error: existingError } = await client
		.from("account_dna")
		.select("account_id, status")
		.eq("workspace_id", input.workspaceId)
		.in("account_id", accountIds)
		.eq("status", "active");
	if (existingError) throw existingError;
	const existingActive = new Set(
		((existingDnaRows ?? []) as Array<Record<string, unknown>>).map((row) =>
			String(row.account_id),
		),
	);

	const { data: accountRows, error: accountsError } = await client
		.from("accounts")
		.select("id, username, display_name, bio, ai_config, status, is_active")
		.in("id", accountIds);
	if (accountsError) throw accountsError;
	const accounts = (accountRows ?? []) as Array<Record<string, unknown>>;

	const since = new Date(Date.now() - 180 * 24 * 60 * 60 * 1000).toISOString();
	const { data: postRows, error: postsError } = await client
		.from("posts")
		.select(
			"id, account_id, content, views_count, replies_count, likes_count, hook_type, topic_label, format_type, emotional_frame, reply_mechanism, content_length_bucket, media_style, published_at",
		)
		.in("account_id", accountIds)
		.gte("published_at", since)
		.order("published_at", { ascending: false })
		.limit(Math.min(accountIds.length * 80, 5000));
	if (postsError) throw postsError;

	const postsByAccount = new Map<string, AccountDnaBackfillPost[]>();
	for (const post of (postRows ?? []) as Array<Record<string, unknown>>) {
		const accountId = String(post.account_id ?? "");
		if (!accountId) continue;
		const rows = postsByAccount.get(accountId) ?? [];
		rows.push({
			id: (post.id as string | null | undefined) ?? null,
			content: String(post.content ?? ""),
			views_count: Number(post.views_count ?? 0),
			replies_count: Number(post.replies_count ?? 0),
			likes_count: Number(post.likes_count ?? 0),
			hook_type: (post.hook_type as string | null | undefined) ?? null,
			topic_label: (post.topic_label as string | null | undefined) ?? null,
			format_type: (post.format_type as string | null | undefined) ?? null,
			emotional_frame:
				(post.emotional_frame as string | null | undefined) ?? null,
			reply_mechanism:
				(post.reply_mechanism as string | null | undefined) ?? null,
			content_length_bucket:
				(post.content_length_bucket as string | null | undefined) ?? null,
			media_style: (post.media_style as string | null | undefined) ?? null,
			published_at: (post.published_at as string | null | undefined) ?? null,
		});
		postsByAccount.set(accountId, rows);
	}

	for (const account of accounts) {
		const accountId = String(account.id);
		if (!force && existingActive.has(accountId)) {
			result.skipped += 1;
			continue;
		}
		try {
			const groupId = accountToGroup.get(accountId) ?? null;
			const group = groupId ? groupById.get(groupId) : null;
			const built = buildAccountDnaBackfillForAccount({
				workspaceId: input.workspaceId,
				groupId,
				account: {
					id: accountId,
					username: (account.username as string | null | undefined) ?? null,
					display_name:
						(account.display_name as string | null | undefined) ?? null,
					bio: (account.bio as string | null | undefined) ?? null,
					ai_config: jsonObject(account.ai_config),
				},
				group: group
					? {
							name: (group.name as string | null | undefined) ?? null,
							voice_profile: jsonObject(group.voice_profile),
							content_strategy: jsonObject(group.content_strategy),
						}
					: null,
				posts: postsByAccount.get(accountId) ?? [],
			});
			if (dryRun) {
				result.created += 1;
				result.examplesCreated += built.examples.length;
				result.rulesCreated += built.rules.length;
				continue;
			}
			if (force) {
				await client
					.from("account_dna")
					.update({ status: "retired", updated_at: new Date().toISOString() })
					.eq("workspace_id", input.workspaceId)
					.eq("account_id", accountId)
					.eq("status", "active");
			}
			const { data: insertedDna, error: insertDnaError } = await client
				.from("account_dna")
				.insert({
					...built.dna,
					source_summary: {
						post_count: (postsByAccount.get(accountId) ?? []).length,
						backfilled_at: new Date().toISOString(),
					},
					generated_from: "backfill",
				})
				.select("id")
				.single();
			if (insertDnaError) throw insertDnaError;
			const dnaId = String((insertedDna as Record<string, unknown>).id);
			if (built.examples.length > 0) {
				const { error: exampleError } = await client
					.from("account_dna_examples")
					.insert(built.examples.map((row) => ({ ...row, dna_id: dnaId })));
				if (exampleError) throw exampleError;
				result.examplesCreated += built.examples.length;
			}
			if (built.rules.length > 0) {
				const { error: ruleError } = await client
					.from("account_dna_rules")
					.insert(built.rules.map((row) => ({ ...row, dna_id: dnaId })));
				if (ruleError) throw ruleError;
				result.rulesCreated += built.rules.length;
			}
			result.created += 1;
		} catch (error) {
			result.failed += 1;
			result.errors.push({ account_id: accountId, error: String(error) });
		}
	}

	return result;
}
