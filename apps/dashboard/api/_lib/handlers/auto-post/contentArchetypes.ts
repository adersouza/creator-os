import type { AccountDnaProfile } from "./accountDna.js";

export type ContentArchetype =
	| "identity_statement"
	| "confession"
	| "opinion"
	| "observation"
	| "authority_flex"
	| "vulnerability"
	| "recommendation_request"
	| "mini_story"
	| "hot_take"
	| "question";

export type QuestionSubtype =
	| "specific_topical_question"
	| "generic_question_bait"
	| "generic_question";

export interface ContentArchetypeDecision {
	archetype: ContentArchetype;
	confidence: number;
	reason: string;
	isGenericQuestion: boolean;
	questionSubtype: QuestionSubtype | null;
}

export type IdentityShapeId =
	| "IM_A_X_BUT_Y"
	| "ASKING_FOR_A_FRIEND"
	| "ANYBODY_ELSE_X"
	| "CAN_TALK_ABOUT_X"
	| "DROP_YOUR_TOP_3_X"
	| "MY_TOXIC_TRAIT_IS_X"
	| "I_NEED_SOMEONE_WHO_X"
	| "PEOPLE_THINK_X_BUT_Y"
	| "I_LOVE_X_BUT_Y"
	| "LOWKEY_JUST_WANNA_X"
	| "LATE_NIGHT_X";

export const TARGET_ARCHETYPE_DISTRIBUTION: Record<ContentArchetype, number> = {
	identity_statement: 25,
	confession: 15,
	opinion: 8,
	hot_take: 7,
	recommendation_request: 10,
	observation: 10,
	vulnerability: 0,
	mini_story: 0,
	authority_flex: 3,
	question: 22,
};

export const TARGET_QUESTION_SUBTYPE_DISTRIBUTION: Record<QuestionSubtype, number> = {
	specific_topical_question: 20,
	generic_question_bait: 0,
	generic_question: 2,
};

const GENERIC_QUESTION_PATTERNS = [
	/\b(who'?s up|who'?s awake|still up|r u up|wyd rn|wyd)\b/i,
	/\b(would you|do you|are you|am i)\b.{0,18}\?*$/i,
	/\b(if the world was ending|what would u do|what would you do)\b/i,
	/\b(be honest)\b.{0,24}\?*$/i,
	/^\s*(anyone|anybody)\s+else\s*\??\s*$/i,
];

const TOPICAL_QUESTION_PATTERNS = [
	/\b(anime|manga|cartoon|animated movie|show|movie|watch|lore)\b/i,
	/\b(gym|pre-?workout|protein|playlist|leg day|pr|workout)\b/i,
	/\b(music|song|songs|playlist|gatekeep|gatekeeping|artist)\b/i,
	/\b(gaming|gamer|valorant|minecraft|roblox|fortnite|r6|rainbow six|headset|lobby)\b/i,
	/\b(date|dating|crush|single|boyfriend|girlfriend|older men|pretty|cute|age|hot|sexy|flirty|clingy|needy|jealous|kiss|cuddle|late night text|good morning text|handle)\b/i,
	/\b(must watch|underrated|overrated|top \d+|prove me wrong|fill in|_______|____)\b/i,
	/\b(recommend|recs?|suggest|drop your|what'?s the one|which one)\b/i,
];

export function isGenericQuestionBait(content: string): boolean {
	const text = content.trim();
	if (!text) return false;
	if (TOPICAL_QUESTION_PATTERNS.some((pattern) => pattern.test(text))) {
		return false;
	}
	return GENERIC_QUESTION_PATTERNS.some((pattern) => pattern.test(text));
}

export function classifyQuestionSubtype(content: string): QuestionSubtype | null {
	const text = content.trim();
	const lower = text.toLowerCase();
	const hasQuestionForm =
		text.includes("?") ||
		/\b(would you|do you|are you|who|what|which|how|where|when|am i|prove me wrong)\b/i.test(
			lower,
		);
	if (!hasQuestionForm) return null;
	if (isGenericQuestionBait(text)) return "generic_question_bait";
	if (TOPICAL_QUESTION_PATTERNS.some((pattern) => pattern.test(text))) {
		return "specific_topical_question";
	}
	if (/\b(i|me|my|girl|girls|you)\b/i.test(lower) && /\b(anime|gym|music|game|date|cute|pretty|watch|song|hot|sexy|flirty|clingy|needy|jealous|kiss|cuddle)\b/i.test(lower)) {
		return "specific_topical_question";
	}
	return "generic_question";
}

export function detectIdentityShapeId(
	content: string | null | undefined,
): IdentityShapeId | null {
	const text = (content || "").trim().toLowerCase();
	if (!text) return null;
	if (/\b(i'?m|i am)\s+(a\s+\d+|an?\s+\w+|single)\b.+\bbut\b/i.test(text))
		return "IM_A_X_BUT_Y";
	if (/\basking\s+for\s+(a\s+)?friend\b/i.test(text))
		return "ASKING_FOR_A_FRIEND";
	if (/\b(anybody|anyone)\s+else\b/i.test(text)) return "ANYBODY_ELSE_X";
	if (/\b(can|could)\s+talk\s+about\b/i.test(text))
		return "CAN_TALK_ABOUT_X";
	if (/\bdrop\s+your\s+top\s+3\b/i.test(text)) return "DROP_YOUR_TOP_3_X";
	if (/\bmy\s+toxic\s+trait\s+is\b/i.test(text))
		return "MY_TOXIC_TRAIT_IS_X";
	if (/\bi\s+need\s+someone\s+who\b/i.test(text))
		return "I_NEED_SOMEONE_WHO_X";
	if (/\bpeople\s+think\b.+\bbut\b/i.test(text))
		return "PEOPLE_THINK_X_BUT_Y";
	if (/\bi\s+love\b.+\bbut\b/i.test(text)) return "I_LOVE_X_BUT_Y";
	if (/\blowkey\s+just\s+wanna\b/i.test(text))
		return "LOWKEY_JUST_WANNA_X";
	if (/\blate\s+night\b/i.test(text)) return "LATE_NIGHT_X";
	return null;
}

export function classifyContentArchetype(
	content: string | null | undefined,
): ContentArchetypeDecision {
	const text = (content || "").trim();
	const lower = text.toLowerCase();
	const wordCount = text.split(/\s+/).filter(Boolean).length;
	const genericQuestion = isGenericQuestionBait(text);

	if (
		/\b(i'?m|i am)\s+(a\s+\d+|single|not|the kind|just|someone|that girl|a girl)\b/i.test(
			text,
		) ||
		/\b(my taste in|my type is|people think .* about me|i'?m .* but)\b/i.test(
			lower,
		)
	) {
		return {
			archetype: "identity_statement",
			confidence: 0.9,
			reason: "self_identity_claim",
			isGenericQuestion: false,
			questionSubtype: null,
		};
	}

	if (/\b(drop|recommend|recs?|suggest|playlist|watch tonight|top \d+)\b/i.test(lower)) {
		const questionSubtype = classifyQuestionSubtype(text);
		return {
			archetype: "recommendation_request",
			confidence: 0.86,
			reason: "specific_recommendation_request",
			isGenericQuestion: genericQuestion,
			questionSubtype,
		};
	}

	if (/\b(i can tell|i know|trust me|i called it|i was right|i can cook|i can spot|i can guess)\b/i.test(lower)) {
		return {
			archetype: "authority_flex",
			confidence: 0.78,
			reason: "capability_or_authority_claim",
			isGenericQuestion: false,
			questionSubtype: null,
		};
	}

	if (/\b(lonely|cry|makes you cry|sad|hurt|anxious|scared|under my blanket|ramble|vulnerable|healing)\b/i.test(lower)) {
		const questionSubtype = classifyQuestionSubtype(text);
		return {
			archetype: "vulnerability",
			confidence: 0.8,
			reason: "vulnerable_emotional_frame",
			isGenericQuestion: genericQuestion,
			questionSubtype,
		};
	}

	if (/\b(confession|i admit|not gonna lie|ngl|tbh|i still|i secretly|i can'?t stop|i wish|i miss|i need|i want)\b/i.test(lower)) {
		const questionSubtype = classifyQuestionSubtype(text);
		return {
			archetype: "confession",
			confidence: 0.76,
			reason: "personal_confessional_marker",
			isGenericQuestion: genericQuestion,
			questionSubtype,
		};
	}

	if (/\b(hot take|controversial|red flag|toxic|should be illegal|normalize|unpopular opinion)\b/i.test(lower)) {
		const questionSubtype = classifyQuestionSubtype(text);
		return {
			archetype: "hot_take",
			confidence: 0.82,
			reason: "explicit_hot_take_marker",
			isGenericQuestion: genericQuestion,
			questionSubtype,
		};
	}

	if (/\b(i think|i believe|i hate|i love|is overrated|is underrated|not sorry|better than|worse than)\b/i.test(lower)) {
		const questionSubtype = classifyQuestionSubtype(text);
		return {
			archetype: "opinion",
			confidence: 0.72,
			reason: "opinion_or_preference_claim",
			isGenericQuestion: genericQuestion,
			questionSubtype,
		};
	}

	if (
		wordCount > 12 &&
		/\b(today|yesterday|last night|this morning|one time|when i|my friend|my ex|my crush|in class|at the gym|at \d)\b/i.test(
			lower,
		)
	) {
		return {
			archetype: "mini_story",
			confidence: 0.7,
			reason: "specific_personal_scene",
			isGenericQuestion: genericQuestion,
			questionSubtype: classifyQuestionSubtype(text),
		};
	}

	const trailingQuestionSubtype = classifyQuestionSubtype(text);
	if (
		trailingQuestionSubtype ||
		text.includes("?") ||
		/\b(would you|do you|are you|who|what|which|how|where|when|am i)\b/i.test(
			lower,
		)
	) {
		const questionSubtype = trailingQuestionSubtype || "generic_question";
		return {
			archetype: "question",
			confidence:
				questionSubtype === "specific_topical_question"
					? 0.82
					: genericQuestion
						? 0.88
						: 0.62,
			reason:
				questionSubtype === "specific_topical_question"
					? "specific_topical_question"
					: genericQuestion
						? "generic_question_bait"
						: "generic_question_form",
			isGenericQuestion: genericQuestion,
			questionSubtype,
		};
	}

	return {
		archetype: "observation",
		confidence: 0.58,
		reason: "default_statement_observation",
		isGenericQuestion: false,
		questionSubtype: null,
	};
}

export function recommendedArchetypesForDna(
	dna?: AccountDnaProfile | null,
): ContentArchetype[] {
	if (!dna) {
		return [
			"identity_statement",
			"confession",
			"recommendation_request",
			"vulnerability",
			"observation",
		];
	}

	const out: ContentArchetype[] = [];
	const archetype = `${dna.archetype} ${dna.sub_archetype || ""}`.toLowerCase();
	const hasSoftIdentity =
		archetype.includes("soft") ||
		archetype.includes("gfe") ||
		dna.vulnerability_level >= 3 ||
		dna.flirt_level >= 3;
	const hasEdge =
		dna.humor_level >= 3 ||
		dna.controversy_level >= 3 ||
		archetype.includes("chaotic");
	const hasAuthority = dna.storytelling_tendency >= 3 || archetype.includes("authority");
	const hasTopicWorld =
		(dna.primary_topics?.length ?? 0) > 0 || (dna.recurring_motifs?.length ?? 0) > 0;

	if (hasSoftIdentity) out.push("confession", "vulnerability", "identity_statement");
	if (hasEdge) out.push("hot_take", "opinion", "observation");
	if (hasAuthority) out.push("authority_flex", "mini_story");
	if (hasTopicWorld) out.push("identity_statement", "recommendation_request");

	const fallback: ContentArchetype[] = ["identity_statement", "observation"];
	return [...new Set(out.length > 0 ? out : fallback)];
}

export function formatArchetypeDistributionForPrompt(
	dna?: AccountDnaProfile | null,
): string {
	const dnaPreferred = recommendedArchetypesForDna(dna);
	const distribution = Object.entries(TARGET_ARCHETYPE_DISTRIBUTION)
		.filter(([, value]) => value > 0)
		.map(([key, value]) => `- ${key}: ${value}%`)
		.join("\n");
	return `== CONTENT ARCHETYPE MIX (PRIMARY CONTENT SHAPE) ==
Choose the archetype before writing the post. This is a batch quota, not a post-hoc label. Prefer identity, specificity, and measured winner shapes. Specific topical questions are allowed because they have won in our data; generic question bait is still blocked.

TARGET MIX:
${distribution}
- specific_topical_question: ${TARGET_QUESTION_SUBTYPE_DISTRIBUTION.specific_topical_question}% of the batch, counted inside question-shaped content
- generic_question_bait: 0-${TARGET_QUESTION_SUBTYPE_DISTRIBUTION.generic_question}% maximum

DNA-PREFERRED ARCHETYPES FOR THIS TARGET:
${dnaPreferred.map((value) => `- ${value}`).join("\n")}

GOOD SHAPE: identity/personality claim -> specific topic -> natural reply opening.
BAD SHAPE: generic question -> forced reply bait.

Allowed question shape: specific topical question with anime, gym, music, gaming, dating, validation, or fill-in-the-blank context.
Blocked question shape: micro "up rn" bait, standalone "anyone else", broad hypotheticals, or unsupported date-me questions.`;
}

export type IdentityStatementTemplateFamily =
	| "rating_but_trait"
	| "single_but_standard"
	| "love_topic_but_trait"
	| "people_think_but_truth"
	| "topic_personality_test"
	| "tiny_confession"
	| "weird_habit"
	| "recurring_preference"
	| "social_observation"
	| "contradiction"
	| "personal_rule"
	| "irrational_belief"
	| "guilty_pleasure"
	| "mini_anecdote";

export interface IdentityStatementCandidate {
	content: string;
	templateFamily: IdentityStatementTemplateFamily;
	dnaMotif: string;
}

export interface IdentityStatementValidation {
	passed: boolean;
	reasons: string[];
	archetype: "identity_statement";
}

function pickFirst(values: string[] | undefined, fallback: string): string {
	return (values ?? []).find((value) => value.trim().length > 0) || fallback;
}

export function buildIdentityStatementCandidate(
	dna?: AccountDnaProfile | null,
	family: IdentityStatementTemplateFamily = "rating_but_trait",
): IdentityStatementCandidate {
	const topic = pickFirst(dna?.primary_topics, "anime").toLowerCase();
	const motif = pickFirst(dna?.recurring_motifs, topic).toLowerCase();
	const phrase = pickFirst(dna?.signature_phrases, "based").toLowerCase();
	const trait =
		dna?.humor_level && dna.humor_level >= 3
			? "unhinged"
			: dna?.vulnerability_level && dna.vulnerability_level >= 3
				? "too sentimental"
				: "weirdly specific";

	const byFamily: Record<IdentityStatementTemplateFamily, string> = {
		rating_but_trait: `i'm a 9 but my ${topic} taste is ${trait}. ${phrase}`,
		single_but_standard: `i'm single. i don't need drama. i can ${motif}`,
		love_topic_but_trait: `i love ${topic} but my taste is ${trait}`,
		people_think_but_truth: `people think i'm quiet but my ${topic} opinions are loud`,
		topic_personality_test: `my ${topic} taste is basically a personality test`,
		tiny_confession: `tiny confession: ${motif} fixes my mood too fast`,
		weird_habit: `my weird habit is ranking people by their ${topic} taste`,
		recurring_preference: `i always trust someone with good ${topic} taste first`,
		social_observation: `${topic} people flirt like they are hiding a playlist`,
		contradiction: `i act normal until someone mentions ${topic}`,
		personal_rule: `personal rule: never ignore a ${motif} person`,
		irrational_belief: `i irrationally believe ${topic} taste says everything`,
		guilty_pleasure: `guilty pleasure: judging ${topic} opinions too hard`,
		mini_anecdote: `last night ${motif} made me forget i was supposed to sleep`,
	};

	return {
		content: byFamily[family],
		templateFamily: family,
		dnaMotif: motif,
	};
}

export function validateIdentityStatementCandidate(input: {
	content: string;
	dna?: AccountDnaProfile | null | undefined;
	recentOpeners?: string[] | undefined;
	siblingOwnedPhrases?: string[] | undefined;
}): IdentityStatementValidation {
	const reasons: string[] = [];
	const content = input.content.trim();
	const lower = content.toLowerCase();
	const decision = classifyContentArchetype(content);
	if (decision.archetype !== "identity_statement") {
		reasons.push("not_identity_statement");
	}
	if (isGenericQuestionBait(content)) reasons.push("generic_question_bait");
	if (!/\b(but|single|people think|my .* taste|i love)\b/i.test(content)) {
		reasons.push("missing_identity_tension");
	}
	const dnaTerms = [
		...(input.dna?.primary_topics ?? []),
		...(input.dna?.recurring_motifs ?? []),
		...(input.dna?.signature_phrases ?? []),
	]
		.map((value) => value.toLowerCase())
		.filter(Boolean);
	if (dnaTerms.length > 0 && !dnaTerms.some((term) => lower.includes(term))) {
		reasons.push("missing_dna_topic_or_motif");
	}
	const opener = lower.split(/\s+/).slice(0, 3).join(" ");
	if ((input.recentOpeners ?? []).map((value) => value.toLowerCase()).includes(opener)) {
		reasons.push("recent_opener_collision");
	}
	for (const phrase of input.siblingOwnedPhrases ?? []) {
		if (phrase && lower.includes(phrase.toLowerCase())) {
			reasons.push("sibling_phrase_collision");
			break;
		}
	}
	return {
		passed: reasons.length === 0,
		reasons,
		archetype: "identity_statement",
	};
}
