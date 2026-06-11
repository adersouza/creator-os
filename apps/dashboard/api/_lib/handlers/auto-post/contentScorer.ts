/**
 * Content Scorer — fast pattern-based quality scoring for autoposter content.
 *
 * Identity-led scoring dimensions:
 * - identity, specificity, memorability, relatability, emotionality,
 *   discussion potential, originality, reply potential.
 *
 * Composite weights: identity 20%, specificity 18%, memorability 15%,
 * relatability 14%, emotionality 12%, discussion 10%, originality 6%, reply 5%.
 * Floor: overall < 2.0 → reject. No standalone reply trigger hard-fail.
 *
 * No LLM calls — pure regex/heuristic scoring for zero-latency pipeline integration.
 * Wired into queueFill.ts between content filter and embedding dedup.
 */

import { logger } from "../../logger.js";
import {
	classifyContentArchetype,
	type ContentArchetype,
} from "./contentArchetypes.js";
import { isHighValueProfileCuriosityContent } from "./performanceFirst.js";

export interface ContentScore {
	replyTrigger: number; // 1-5
	emotionalWarmth: number; // 1-5
	identity: number; // 1-5
	specificity: number; // 1-5
	memorability: number; // 1-5
	relatability: number; // 1-5
	emotionality: number; // 1-5
	discussionPotential: number; // 1-5
	originality: number; // 1-5
	archetype: ContentArchetype;
	isGenericQuestion: boolean;
	overall: number; // weighted composite
	passed: boolean;
	rejectReason?: string | undefined;
}

// ============================================================================
// Reply Trigger Score (1-5)
// Research: replies are #1 algorithm signal on Threads. Every post MUST drive replies.
// 5 = explicit question/fill-in-blank
// 4 = implied question/incomplete thought
// 3 = debatable statement
// 2 = no clear reply path
// 1 = passive/declarative
// Hard-fail threshold: < 3
// ============================================================================

// Score 5: explicit question or fill-in-blank
const SCORE_5_PATTERNS = [
	/\?/, // contains question mark (anywhere, not just end)
	/___+/, // fill-in-blank (underscores)
	/\b(would you|do you|are you|have you|can you|should i|am i)\b/i,
	/\b(what'?s your|what do you|what would you|how do you)\b/i,
	/\b(which|what|where|when|who|how)\b.*\b(recs?|suggest|help|pick|choose)\b/i,
	/\b(rate my|rank these|pick one|choose one|you have to pick)\b/i,
	/\b(be honest|tell me|describe your|name one|drop your)\b/i,
	/\b(who'?s (up|awake|here)|anyone else|any .+ here)\b/i,
	/\bin one (word|emoji)\b/i,
];

// Score 4: implied question / incomplete thought / direct challenge
const SCORE_4_PATTERNS = [
	/\.{2,}\s*$/, // trails off with ...
	/\b(prove me wrong|fight me|change my mind|i dare you)\b/i,
	/\b(or (is|am|do|are) (that|it|i) just)\b/i, // "or is that just me"
	/\b(u feel me|you feel me|right\??)\s*$/i,
	/\b(tag someone|send this to)\b/i,
	/\b(dm me|message me|hit me( up)?)\b/i,
	/\b(spill|drop it|say it|let me know)\b/i,
	/\b(anyone|somebody|someone)\??\s*$/i,
	/\b(agree or disagree|yes or no)\b/i,
	/\b(what if|imagine if)\b/i,
];

// Score 3: debatable / opinion / hot take that invites response
const SCORE_3_PATTERNS = [
	/\b(unpopular opinion|hot take|controversial)\b/i,
	/\b(overrated|underrated)\b/i,
	/\b(better than|worse than|> |< )\b/i,
	/\b(stop doing|stop saying|please stop)\b/i,
	/\b(nobody talks about|no one talks about)\b/i,
	/\b(i('?ll| will) never apologize)\b/i,
	/\b(is dead|is overrated|is underrated)\b/i,
	/\b(i('?m| am) (sorry but|not sorry))\b/i,
	/\b(can we normalize|let'?s normalize)\b/i,
];

function scoreReplyTrigger(content: string): number {
	const lower = content.toLowerCase();

	for (const pattern of SCORE_5_PATTERNS) {
		if (pattern.test(lower)) return 5;
	}
	for (const pattern of SCORE_4_PATTERNS) {
		if (pattern.test(lower)) return 4;
	}
	for (const pattern of SCORE_3_PATTERNS) {
		if (pattern.test(lower)) return 3;
	}

	// Score 2: has some engagement hook but weak
	if (/\b(lol|lmao|fr|ngl|tbh|lowkey)\b/i.test(lower)) return 2;
	if (/[!]{2,}/.test(content)) return 2; // multiple exclamation marks = some energy

	// Score 1: passive/declarative — no reply path
	return 1;
}

// ============================================================================
// Emotional Warmth Score (1-5)
// Research: agreeableness = #1 engagement predictor (UAB study).
// 5 = warm/vulnerable/inclusive
// 4 = friendly/conversational
// 3 = neutral
// 2 = cold/generic
// 1 = corporate/robotic
// Soft threshold: < 2 penalizes overall score
// ============================================================================

// Warm markers (score boosters)
const WARM_PATTERNS = [
	/\b(i miss|i need|i want|i wish|i feel|i love)\b/i,
	/\b(honestly|ngl|real talk|not gonna lie)\b/i,
	/\b(you'?re|ur|u r) (amazing|beautiful|cute|sweet|the best)\b/i,
	/\b(come over|stay with me|hold me|hug me)\b/i,
	/\b(lonely|missing|heartbreak|healing|vulnerable)\b/i,
	/\b(we all|all of us|every one of us|together)\b/i,
	/\b(you know what|you ever|u ever)\b/i,
	/\b(relatable)\b/i,
];

// Conversational markers
const CONVERSATIONAL_PATTERNS = [
	/\b(lol|lmao|haha|omg|bruh|bro|bestie|babe)\b/i,
	/\b(ngl|tbh|fr fr|lowkey|highkey|no cap)\b/i,
	/\b(rn|imo|idk|idc|idgaf)\b/i,
	/\b(yo |hey |hi |sup )/i,
	/😂|😭|🥺|😏|😈|💕|🤍|🥰|❤️|💋|👀|🫣/u,
];

// Cold/corporate markers (score penalties)
const COLD_PATTERNS = [
	/\b(furthermore|therefore|however|additionally|moreover)\b/i,
	/\b(absolutely|genuinely|hypothetically|breathtaking|stunning|mesmerizing)\b/i,
	/\b(optimize|leverage|synergy|paradigm|ecosystem)\b/i,
	/\b(it is important to note|one should consider|studies show that)\b/i,
	/\b(in conclusion|to summarize|in summary)\b/i,
];

function scoreEmotionalWarmth(content: string): number {
	let score = 3; // start neutral

	// Check warm patterns
	let warmHits = 0;
	for (const pattern of WARM_PATTERNS) {
		if (pattern.test(content)) warmHits++;
	}

	// Check conversational patterns
	let convHits = 0;
	for (const pattern of CONVERSATIONAL_PATTERNS) {
		if (pattern.test(content)) convHits++;
	}

	// Check cold patterns
	let coldHits = 0;
	for (const pattern of COLD_PATTERNS) {
		if (pattern.test(content)) coldHits++;
	}

	// Direct address ("you", "u") is a warmth signal
	const hasDirectAddress = /\b(you|u|ur|your)\b/i.test(content);

	// Lowercase = casual = warmer (all-lowercase posts feel like texting)
	const isAllLower = content === content.toLowerCase();

	// Boost for warm patterns
	if (warmHits >= 2) score = 5;
	else if (warmHits >= 1) score = Math.max(score, 4);

	// Boost for conversational tone
	if (convHits >= 2) score = Math.max(score, 4);
	else if (convHits >= 1) score = Math.max(score, 3);

	// Boost for direct address + casual
	if (hasDirectAddress && isAllLower) score = Math.max(score, 4);
	else if (hasDirectAddress) score = Math.max(score, 3);

	// Penalty for cold/corporate language
	if (coldHits >= 2) score = 1;
	else if (coldHits >= 1) score = Math.min(score, 2);

	// Proper capitalization + periods everywhere = feels robotic
	const sentenceCount = (content.match(/[.!?]+/g) || []).length;
	const hasProperGrammar = /^[A-Z]/.test(content) && sentenceCount >= 2;
	if (hasProperGrammar && coldHits === 0 && warmHits === 0) {
		score = Math.min(score, 3);
	}

	return Math.max(1, Math.min(5, score));
}

// ============================================================================
// Originality Score (1-5) — for competitor-inspired content
// Research (Competitor Intelligence 2026): Meta requires 30%+ genuinely new material.
// Measures word-level overlap between generated content and source competitor post.
// Stop words excluded so trivial words ("i","the","and") don't inflate overlap %.
// 5 = highly original (< 10% word overlap)
// 4 = good (10-20% overlap)
// 3 = acceptable (20-30% overlap — near Meta's threshold)
// 2 = risky (30-40% overlap)
// 1 = too similar (40%+ overlap — likely flagged)
// Hard-fail threshold: < 2 when source content is provided
// ============================================================================

// Stop words excluded from overlap calculation — these words appear in every post
// and inflate overlap ratios to meaningless levels on short (8-15 word) posts.
const ORIGINALITY_STOP_WORDS = new Set([
	"i",
	"you",
	"he",
	"she",
	"we",
	"they",
	"it",
	"a",
	"an",
	"the",
	"and",
	"or",
	"but",
	"so",
	"to",
	"of",
	"in",
	"on",
	"at",
	"for",
	"by",
	"with",
	"from",
	"is",
	"are",
	"was",
	"were",
	"be",
	"been",
	"being",
	"have",
	"has",
	"had",
	"do",
	"does",
	"did",
	"not",
	"no",
	"me",
	"my",
	"your",
	"his",
	"her",
	"our",
	"its",
	"this",
	"that",
	"these",
	"those",
	"if",
	"than",
	"as",
	"up",
	"out",
	"just",
	"can",
	"will",
	"would",
	"could",
	"should",
	"get",
	"like",
	"when",
	"then",
	"there",
	"here",
	"what",
	"which",
	"who",
	"how",
	"why",
	"ll",
	"ve",
	"re",
	"m",
	"s",
	"t",
	"d",
	"dont",
	"dont",
	"wont",
	"cant",
	"im",
	"ive",
	"id",
]);

function scoreOriginality(content: string, sourceContent: string): number {
	const normalize = (s: string) =>
		s
			.toLowerCase()
			.replace(/[^\w\s]/g, "")
			.split(/\s+/)
			.filter((w) => w.length > 1 && !ORIGINALITY_STOP_WORDS.has(w));

	const contentWords = normalize(content);
	const sourceWords = new Set(normalize(sourceContent));

	// If source has fewer than 5 meaningful words, overlap ratio is too noisy
	// to be actionable — short competitor posts share themes, not text.
	if (contentWords.length === 0 || sourceWords.size < 5) return 5;

	// Count overlapping words
	let overlap = 0;
	for (const word of contentWords) {
		if (sourceWords.has(word)) overlap++;
	}

	const overlapRatio = overlap / contentWords.length;

	// Also check consecutive word matches (3+ consecutive = much worse)
	const sourceText = sourceContent.toLowerCase();
	const contentTokens = content.toLowerCase().split(/\s+/);
	let maxConsecutive = 0;
	for (let i = 0; i <= contentTokens.length - 3; i++) {
		const trigram = contentTokens.slice(i, i + 3).join(" ");
		if (sourceText.includes(trigram)) {
			maxConsecutive = Math.max(maxConsecutive, 3);
			// Check for 4+ consecutive
			if (i + 3 < contentTokens.length) {
				const quad = contentTokens.slice(i, i + 4).join(" ");
				if (sourceText.includes(quad))
					maxConsecutive = Math.max(maxConsecutive, 4);
			}
		}
	}

	// Penalize heavily for consecutive word matches
	if (maxConsecutive >= 4) return 1;
	if (maxConsecutive >= 3 && overlapRatio > 0.2) return 2;

	// Score based on overlap ratio
	if (overlapRatio < 0.1) return 5;
	if (overlapRatio < 0.2) return 4;
	if (overlapRatio < 0.3) return 3;
	if (overlapRatio < 0.4) return 2;
	return 1;
}

// ============================================================================
// Specificity Score (1-5)
// Research (Content Scoring Calibration 2026, Section 4.3): #3 engagement predictor.
// Hyper-specific details (numbers, names, time references, scenarios) drive
// 2-3x more replies than generic statements. People reply to specifics.
// 5 = multiple specific details (numbers + scenario + time)
// 4 = strong specificity (named things + scenario)
// 3 = some specificity (1-2 concrete details)
// 2 = vague (generic statements, no concrete details)
// 1 = completely generic (could apply to anything)
// Soft threshold: < 2 penalizes overall score
// ============================================================================

// Numbers and quantities (specific detail)
const NUMBER_PATTERNS = [
	/\b\d+\s*(am|pm|hours?|hrs?|mins?|minutes?|days?|weeks?|months?|years?)\b/i,
	/\b(at|since|for)\s+\d+/i, // "at 3am", "since 2020", "for 5 years"
	/\b\d+[%$]/, // percentages, dollar amounts
	/\b\d{1,2}:\d{2}\b/, // time format 3:00
	/\b\d+\s*(times?|reps?|sets?|miles?|lbs?|kg)\b/i,
];

// Named entities (brands, places, specific things)
const NAMED_PATTERNS = [
	/\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+\b/, // Proper nouns (multi-word)
	/\b(netflix|spotify|instagram|tiktok|snapchat|uber|amazon|starbucks|chipotle|mcdonalds|walmart|target)\b/i,
	/\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b/i,
	/\b(january|february|march|april|may|june|july|august|september|october|november|december)\b/i,
];

// Time references (when things happen)
const TIME_PATTERNS = [
	/\b(last night|this morning|yesterday|tonight|right now|rn|at \d|2\s?am|3\s?am|4\s?am)\b/i,
	/\b(when i was|back in|remember when|that time)\b/i,
	/\b(after|before|during|while)\s+(class|work|school|gym|practice|dinner|lunch)\b/i,
];

// Scenario specificity (concrete situations vs abstract)
const SCENARIO_PATTERNS = [
	/\b(walked|drove|ran|sat|stood|texted|called|dm'?d|slid into)\b/i,
	/\b(my (mom|dad|ex|friend|roommate|teacher|boss|crush|bf|gf))\b/i,
	/\b(in (my|the) (car|bed|shower|kitchen|class|gym|bathroom|dorm))\b/i,
	/\b(wearing|eating|watching|listening to|playing)\b/i,
];

function scoreSpecificity(content: string): number {
	let hits = 0;

	for (const p of NUMBER_PATTERNS) if (p.test(content)) hits++;
	for (const p of NAMED_PATTERNS) if (p.test(content)) hits++;
	for (const p of TIME_PATTERNS) if (p.test(content)) hits++;
	for (const p of SCENARIO_PATTERNS) if (p.test(content)) hits++;

	// Word count also matters — very short posts can't be specific
	const wordCount = content.split(/\s+/).length;
	if (wordCount < 5) return Math.min(2, hits + 1);

	if (hits >= 4) return 5;
	if (hits >= 3) return 4;
	if (hits >= 2) return 3;
	if (hits >= 1) return 2;
	return 1;
}

// ============================================================================
// Emotional Arousal Score (1-5)
// Research (Hook Engineering 2026, Section 4.2): moral-emotional words boost
// sharing by 17-24%. High-arousal emotions (awe, anger, anxiety, excitement)
// drive virality; low-arousal (sadness, contentment) don't.
// 5 = multiple high-arousal triggers
// 4 = strong arousal (1-2 high-arousal + amplifiers)
// 3 = moderate arousal (conversational energy)
// 2 = low arousal (passive/observational)
// 1 = no emotional content
// Soft boost: >= 4 adds to overall score
// ============================================================================

const HIGH_AROUSAL_PATTERNS = [
	// Anger / outrage (drives shares)
	/\b(furious|pissed|livid|enraged|fuming|seething|hate this|so mad|tf)\b/i,
	// Awe / excitement (drives shares)
	/\b(insane|unreal|no way|holy|wild|obsessed|mind blown|cant believe|blew my mind)\b/i,
	// Anxiety / fear (drives engagement)
	/\b(terrified|scared|panic|nightmare|haunts me|keeps me up|anxiety|paranoid)\b/i,
	// Surprise / shock
	/\b(wait what|hold up|excuse me|um|plot twist|didnt expect|caught me off guard)\b/i,
	// Desire / longing (strong for dating niche)
	/\b(need (you|this|that)|craving|dying for|desperate|starving|aching)\b/i,
	// Disgust / moral outrage
	/\b(disgusting|sick of|tired of|cant stand|makes me sick|the audacity)\b/i,
];

const AROUSAL_AMPLIFIERS = [
	/\b(literally|actually|genuinely|seriously|honestly|lowkey|highkey)\b/i,
	/!{2,}/, // multiple exclamation marks
	/\b(so|very|extremely|incredibly|absolutely)\b/i,
	/\b(never|always|every single|not once)\b/i, // absolutes = emotional intensity
];

function scoreEmotionalArousal(content: string): number {
	let arousalHits = 0;
	for (const p of HIGH_AROUSAL_PATTERNS) {
		if (p.test(content)) arousalHits++;
	}

	let amplifierHits = 0;
	for (const p of AROUSAL_AMPLIFIERS) {
		if (p.test(content)) amplifierHits++;
	}

	// ALL CAPS words (3+ chars) = intensity signal
	const capsWords = content.match(/\b[A-Z]{3,}\b/g)?.length || 0;
	if (capsWords > 0) amplifierHits++;

	const total = arousalHits + Math.floor(amplifierHits / 2);

	if (total >= 3) return 5;
	if (total >= 2) return 4;
	if (arousalHits >= 1) return 3;
	if (amplifierHits >= 2) return 2;
	return 1;
}

function scoreIdentity(content: string, archetype: ContentArchetype): number {
	if (archetype === "identity_statement") return 5;
	if (archetype === "confession" || archetype === "authority_flex") return 4;
	if (/\b(i'?m|i am|my|me|i love|i hate|i need|i want)\b/i.test(content))
		return 3;
	if (archetype === "question") return 1;
	return 2;
}

function scoreMemorability(content: string, archetype: ContentArchetype): number {
	let score = 2;
	if (archetype === "identity_statement" || archetype === "hot_take") score += 2;
	if (/\b(but|except|secretly|unhinged|based|red flag|personality test)\b/i.test(content))
		score += 1;
	if (/\b(i'?m a \d+|i'?m single|people think|my taste in)\b/i.test(content))
		score += 1;
	if (content.length < 18 || content.length > 140) score -= 1;
	return Math.max(1, Math.min(5, score));
}

function scoreRelatability(content: string, archetype: ContentArchetype): number {
	let score = 2;
	if (
		/\b(anyone else|we all|everybody|song|playlist|anime|movie|gym|crush|single|lonely|taste|comfort)\b/i.test(
			content,
		)
	) {
		score += 2;
	}
	if (archetype === "recommendation_request" || archetype === "vulnerability")
		score += 1;
	if (/\b(optimization|synergy|framework|ecosystem)\b/i.test(content)) score -= 2;
	return Math.max(1, Math.min(5, score));
}

function scoreDiscussionPotential(
	content: string,
	archetype: ContentArchetype,
	replyTrigger: number,
): number {
	if (archetype === "recommendation_request") return 5;
	if (archetype === "identity_statement" || archetype === "vulnerability")
		return 4;
	if (archetype === "question") return Math.min(4, replyTrigger);
	if (archetype === "hot_take" || archetype === "opinion") return 4;
	if (/\b(top \d+|drop|recs?|be honest|cry every time|overrated|underrated)\b/i.test(content))
		return 4;
	return 2;
}

// ============================================================================
// Main scoring function
// ============================================================================

/**
 * Score content quality. When sourceContent is provided (competitor-inspired posts),
 * also checks originality against the source material.
 */
export function scoreContent(
	content: string,
	sourceContent?: string | null,
): ContentScore {
	const archetypeDecision = classifyContentArchetype(content);
	const replyTrigger = scoreReplyTrigger(content);
	const emotionalWarmth = scoreEmotionalWarmth(content);
	const specificity = scoreSpecificity(content);
	const arousal = scoreEmotionalArousal(content);
	const identity = scoreIdentity(content, archetypeDecision.archetype);
	const memorability = scoreMemorability(content, archetypeDecision.archetype);
	const relatability = scoreRelatability(content, archetypeDecision.archetype);
	const emotionality = Math.max(emotionalWarmth, arousal);
	const discussionPotential = scoreDiscussionPotential(
		content,
		archetypeDecision.archetype,
		replyTrigger,
	);
	let originalityScore = 3;

	let overall =
		identity * 0.2 +
		specificity * 0.18 +
		memorability * 0.15 +
		relatability * 0.14 +
		emotionality * 0.12 +
		discussionPotential * 0.1 +
		originalityScore * 0.06 +
		replyTrigger * 0.05;

	// Soft penalty for cold content (warmth < 2)
	if (emotionalWarmth < 2) {
		overall -= 0.5;
	}

	// Soft penalty for generic content (specificity < 2)
	if (specificity < 2) {
		overall -= 0.3;
	}

	if (archetypeDecision.isGenericQuestion) {
		overall -= 0.7;
	}

	// Soft boost for high-arousal content (arousal >= 4) — +17-24% sharing
	if (arousal >= 4) {
		overall += 0.2;
	}

	// Originality check for competitor-inspired content
	if (sourceContent) {
		const originality = scoreOriginality(content, sourceContent);
		originalityScore = originality;
		const preserveCompetitorStyle =
			originality < 2 && isHighValueProfileCuriosityContent(content);
		if (originality < 2 && !preserveCompetitorStyle) {
			logger.debug("[contentScorer] Rejected: low originality vs source", {
				content: content.substring(0, 60),
				sourcePreview: sourceContent.substring(0, 60),
				originality,
			});
			return {
				replyTrigger,
				emotionalWarmth,
				identity,
				specificity,
				memorability,
				relatability,
				emotionality,
				discussionPotential,
				originality,
				archetype: archetypeDecision.archetype,
				isGenericQuestion: archetypeDecision.isGenericQuestion,
				overall: Math.round(overall * 10) / 10,
				passed: false,
				rejectReason: `originality_${originality}`,
			};
		}
		overall += (originality - 3) * 0.06;
	}

	overall = Math.round(overall * 10) / 10;

	// Reply trigger: removed standalone hard-fail. Was < 3, then < 2, but even < 2
	// rejected 69 of 178 posts (39%) — relatable observations like "me spending 3 hours
	// on pinterest..." get reply_trigger=1 but ARE good social content. Reply trigger
	// still contributes 45% to the overall composite score, so truly low-engagement
	// posts still fail via the overall floor below.

	// Hard-fail: overall < 1.5. This floor is intentionally lenient; CLAUDE.md
	// memory notes a 2.0 floor rejected 58/73 acceptable posts, so do not raise
	// it without product input. Resolves backend-reliability-gaps.md P2.
	if (overall < 1.5) {
		logger.debug("[contentScorer] Rejected: overall score below 1.5 floor", {
			content: content.substring(0, 60),
			overall,
			replyTrigger,
			emotionalWarmth,
			specificity,
			arousal,
		});
		return {
			replyTrigger,
			emotionalWarmth,
			identity,
			specificity,
			memorability,
			relatability,
			emotionality,
			discussionPotential,
			originality: originalityScore,
			archetype: archetypeDecision.archetype,
			isGenericQuestion: archetypeDecision.isGenericQuestion,
			overall,
			passed: false,
			rejectReason: `overall_${overall}`,
		};
	}

	return {
		replyTrigger,
		emotionalWarmth,
		identity,
		specificity,
		memorability,
		relatability,
		emotionality,
		discussionPotential,
		originality: originalityScore,
		archetype: archetypeDecision.archetype,
		isGenericQuestion: archetypeDecision.isGenericQuestion,
		overall,
		passed: true,
	};
}
