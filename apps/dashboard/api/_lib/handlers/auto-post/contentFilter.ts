// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Content Filter for Auto-Post Queue
 *
 * Hard gate that runs AFTER AI generation but BEFORE queue insertion.
 * Three layers:
 *   1. Structural checks (length, emoji, AI artifacts)
 *   2. Safety blacklist (ban-risk + wrong persona)
 *   3. DB-configurable patterns (runtime-updateable)
 *
 * Philosophy: only block content that would get accounts BANNED or is
 * clearly wrong-persona. The AI prompt handles tone/quality — the filter
 * catches what prompts can't prevent (hallucinations, explicit, artifacts).
 */

import { logger } from "../../logger.js";
import { validateDiscoverabilitySafeContent } from "../../discoverabilitySafety.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface FilterPattern {
	pattern: string;
	label: string;
}

export interface FilterConfig {
	patterns: FilterPattern[];
	minLength: number;
	maxLength: number;
	maxEmojis: number;
	nicheMode?: "default" | "thirst" | undefined;
}

export interface FilterFlag {
	pattern: string;
	severity: "low" | "medium" | "high";
	message: string;
}

export interface FilterResult {
	passed: boolean;
	reason?: string | undefined;
	matchedText?: string | undefined;
	flags?: FilterFlag[] | undefined;
}

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

// DEFAULT_PATTERNS — only genuine AI artifacts and hallucinations.
// Casual slang, gym terms, motivational phrases are NORMAL for this niche.
// Safety blacklist (explicit content) is enforced separately below.
const DEFAULT_PATTERNS: FilterPattern[] = [
	// AI corporate speak — never appears in real casual posts
	{ pattern: "pure (passion|energy|bliss|magic)", label: "ai-abstract" },
	{ pattern: "living my best life", label: "ai-cliche" },
	{ pattern: "\\bradiating\\b", label: "ai-cliche" },
	{ pattern: "\\bmagnetic\\b", label: "ai-cliche" },
	{ pattern: "\\bheartwarming\\b", label: "ai-cliche" },
	// AI hallucinated scenarios (Gemini invents activities that don't match the niche)
	{ pattern: "dust bunn", label: "ai-hallucination" },
	{ pattern: "sand sculptures?\\b", label: "ai-hallucination" },
	// LinkedIn/corporate tone
	{ pattern: "work persona", label: "corporate" },
	{ pattern: "meeting notes", label: "corporate" },
];
const DEFAULT_MIN_LENGTH = 5; // Ultra-short hooks like "hi 💕" (5 chars) must pass
const DEFAULT_MAX_LENGTH = 500;
const DEFAULT_MAX_EMOJIS = 3; // Hard limit — heavy emoji use is an AI artifact signal

const SHORT_PROFILE_CURIOSITY_HOOKS = [
	/^am i (pretty|cute|your type)\??$/i,
	/^do (you|u) think i'?m (pretty|cute)\??$/i,
	/^do i seem (approachable|cute|pretty)\??$/i,
	/^still cute\??$/i,
	/^am i still cute\??$/i,
	/^would you date me\??$/i,
];

function isShortProfileCuriosityHook(content: string): boolean {
	const normalized = content
		.trim()
		.toLowerCase()
		.replace(/[’]/g, "'")
		.replace(/\s+/g, " ");
	return SHORT_PROFILE_CURIOSITY_HOOKS.some((pattern) =>
		pattern.test(normalized),
	);
}

// ---------------------------------------------------------------------------
// Emoji counting
// ---------------------------------------------------------------------------

const EMOJI_RE_SEGMENT = /\p{Extended_Pictographic}/u;

export function countEmojis(text: string): number {
	const segmenter = new Intl.Segmenter("en", { granularity: "grapheme" });
	let count = 0;
	for (const { segment } of segmenter.segment(text)) {
		if (EMOJI_RE_SEGMENT.test(segment)) count++;
	}
	return count;
}

// ---------------------------------------------------------------------------
// Category 1: BAN RISK — explicit, age, drugs (instant account kill)
// ---------------------------------------------------------------------------

// Always blocked regardless of niche (explicit porn, age emphasis, censored variants)
const HARD_BAN_TERMS = [
	"pussy",
	"dick",
	"cock",
	"cum",
	"orgasm",
	"blowjob",
	"blow job",
	"handjob",
	"hand job",
	"titties",
	"tits",
	"boobs",
	"fuck me",
	"fucked",
	"fucking",
	"f\\*ck",
	"wet pussy",
	"dripping",
	"moaning",
	"ride me",
	"ride it",
	"sit on it",
	"sit on my",
	"suck my",
	"suck it",
	"lick my",
	"lick it",
	"bend over",
	"on your knees",
	"spread",
	"hard for you",
	"so hard rn",
	"make me cum",
	"inside me",
	"deep inside",
	"fill me",
	"send nudes",
	"post nudes",
	"leak(ed)? nudes",
	"my nudes",
	"your nudes",
	"ur nudes",
	"her nudes",
	"his nudes",
	"their nudes",
	"share nudes",
	"nude pic",
	"naked pic",
	"sex tape",
	"sextape",
	"porn",
	"for daddy",
	"come to daddy",
	"my ass",
	"eat my ass",
	"taste my",
	"pounding",
	"pound me",
	"pound it",
	"make me wet",
	"strip for",
	"stripping",
	"get on top",
	"climb on",
	"touch yourself",
	"touching myself",
	"\\bclit\\b",
	"\\brailed\\b",
	"gym sex",
	"deep n hard",
	"deep and hard",
	"on.?my.?knees",
	"on.?ur.?knees",
	"on.?your.?knees",
	"naked pic",
	"get naked",
	"\\bsex\\b",
	"u up daddy",
	"yes daddy",
	"notice me daddy",
	"make you scream",
	"forget your name",
	"push it in",
	"take me right now",
	"take me rn",
	// Censored explicit variants — REMOVED: text spoilers are intentional engagement bait
	// Age emphasis in dating context — child safety violation
	"just turned 18",
	"officially 18",
	"legal age",
	"big 1-8",
	"i.m 18.*(can|but|and)",
	"i know i.m 18",
	"eighteen and",
	"just hit 18",
	"i.m 18 now",
	"turned 18",
	"too young for (you|u)",
	"am i too young",
	"still 18",
	"im 18 (haha|lol|rn|tbh|fr|ngl)",
	"18.?yo.?daddy",
	"18.?yo.?daddies",
	"dream of 18",
	"boys 18",
	"girls 18",
	"birthday.*snap",
	"bday.*snap",
];

// Blocked in default mode, allowed in thirst niche mode
const THIRST_ALLOW_TERMS = [
	"horny",
	"so wet",
	"wet for",
	"hookup",
	"hook up",
	"onlyfans",
	"only fans",
	"fansly",
	"stoners?",
	"\\bweed\\b",
	"\\b420\\b",
	"\\bblunt\\b",
	"\\bhigh af\\b",
];

// Combined union — preserves backward compatibility for any external references
const BAN_RISK_TERMS = [...HARD_BAN_TERMS, ...THIRST_ALLOW_TERMS];

// ---------------------------------------------------------------------------
// Category 2: WRONG PERSONA — hallucinations, off-brand facts
// ---------------------------------------------------------------------------

const WRONG_PERSONA_TERMS = [
	// Hallucinated pets — block pet ownership claims, not passing references
	"furbaby",
	"fur baby",
	"my dog",
	"my pet",
	"my kitten",
	// "my pup" / "my puppy" — REMOVED: used as innuendo text spoilers, not literal pet claims
	"need a pet",
	"my cat is",
	"my cat just",
	"my cat won",
	// Wrong persona facts — 18-21yo girls, NOT single moms or 30+
	"single mom",
	"single mother",
	"single parent",
	"gym mom",
	"\\b3[0-9]\\s+and\\b",
	// 3rd person self-reference
	"enough for lola",
	"enough for larissa",
	"enough for stacey",
	// Office/work — personas don't have office jobs
	"meeting notes",
	"corporate",
	"quarterly",
	"presentation",
	"9.?to.?5",
	"my boss",
	"my office",
	"work deadline",
	"project deadline",
	"conference call",
	"overtime",
	"salary",
	"promotion",
	"night shift",
	"on the clock",
	// Platform meta — personas don't reference the platform
	"posted a new reel",
	"new video.*dropped",
	"boycotting threads",
	"my first post",
	"my first thread",
	"first post here",
	"hello world",
	"starting this account",
	// Vacation/travel — off-brand
	"\\bon vacation\\b",
	"pack.*bags.*guess",
	"suitcase.*guess",
];

// ---------------------------------------------------------------------------
// Category 3: AI ARTIFACTS — bot tells, fake handles, comment-style
// ---------------------------------------------------------------------------

const AI_ARTIFACT_TERMS = [
	// Bot/meta-awareness
	"bot farm",
	"bots already",
	"seeing bots",
	"these bots",
	"fake profiles",
	"bots arrived",
	"bots r already",
	// App meta-awareness
	"lost on this app",
	"how do I use",
	"figuring out this.*app",
	"digital rabbit hole",
	"cant stop scrolling",
	"stop scrolling",
	// External platform handles — never promote other platforms
	"\\btelegram\\b",
	"\\bwhatsapp\\b",
	// Fake snap handles — Gemini hallucinates usernames
	"snap:\\s*\\w+",
	"snap is \\w+",
	"snap.* @\\w+",
	"my snap(?:chat)?\\s*(?:is|:|=)\\s*\\w{3,}",
	"on snap(?:chat)?\\s*(?:is|:|=|@)\\s*\\w{3,}",
	"add me on snap(?:chat)?\\s+\\w{3,}",
	// Unfilled placeholders
	"\\[your",
	// Comment-style (sounds like replying to someone, not posting)
	"wow you look",
	"follow me back",
	"follow back",
	"nice pic",
	"nice photo",
	"great pic",
	"are u a model",
	"are you a model",
	"ur dp",
	"your dp",
	// Photo meta-talk (text post talking about sharing photos)
	"dropping.*photo",
	"pic dump",
	"new shots.*wanna see",
	"drop a photo",
	"can i see a pic",
	// Wrong temporal context — only block full holiday phrases, not passing references
	"valentine.s day",
	"\\bvday\\b",
	"happy new year",
	"new year.*resolution",
	"merry christmas",
	"happy christmas",
	// Starter pack loop
	"starter pack",
];

// ---------------------------------------------------------------------------
// Build combined regex
// ---------------------------------------------------------------------------

function buildBlacklist(groups: string[][]): RegExp {
	const allTerms = groups.flat().join("|");
	return new RegExp(`\\b(${allTerms})\\b`, "i");
}

const SAFETY_BLACKLIST_DEFAULT = buildBlacklist([
	BAN_RISK_TERMS,
	WRONG_PERSONA_TERMS,
	AI_ARTIFACT_TERMS,
]);
const SAFETY_BLACKLIST_THIRST = buildBlacklist([
	HARD_BAN_TERMS,
	WRONG_PERSONA_TERMS,
	AI_ARTIFACT_TERMS,
]);

// ---------------------------------------------------------------------------
// Structural pattern checks — catches AI output artifacts
// ---------------------------------------------------------------------------

const TAXONOMY_LABEL_PATTERNS: RegExp[] = [
	/(?:^|\n)\s*(specific\s+topical\s+question|recommendation\s+request|identity\s+statement|authority\s+flex|mini\s+story|generic\s+question|clone\s+family|winner\s+family|(?:observation|question|vulnerability|confession|recommendation\s+request|specific\s+topical\s+question|hot\s+take)\s+winner)\s*:/i,
	/(?:^|\n)\s*(anime_must_watch_question|anime_dateability_question|age_pretty_validation|single_cook_clean_identity|rating_but_niche_unhinged|gym_fill_blank|gym_crop_top_identity|music_gatekeeping_question|headset_cute_validation|specific_topical_question_winner|identity_statement_winner|recommendation_request_winner|observation_winner|question_winner|hot_take_winner|confession_winner|vulnerability_winner|mini_story_winner|authority_flex_winner)\s*:/i,
];

export function detectTaxonomyLabelLeak(
	content: string,
): { reason: string; matchedText: string } | null {
	for (const regex of TAXONOMY_LABEL_PATTERNS) {
		const match = content.match(regex);
		if (match) {
			return {
				reason: "structural-taxonomy-label",
				matchedText: match[0],
			};
		}
	}
	return null;
}

const STRUCTURAL_PATTERNS: { regex: RegExp; reason: string }[] = [
	{ regex: /^\d+\.\s/, reason: "structural-numbered-list" },
	{
		regex: /^(Reach|Conversion|Punch)\s*(Post|1|2|3)/i,
		reason: "structural-category-label",
	},
	{
		regex:
			/^\s*(?:hot\s+take|unpopular\s+opinion|opinion|confession|asking\s+for\s+(?:a\s+)?friend)\s*:/i,
		reason: "structural-formula-prefix",
	},
	...TAXONOMY_LABEL_PATTERNS.map((regex) => ({
		regex,
		reason: "structural-taxonomy-label",
	})),
	{ regex: /^(here|here'?s)\s/i, reason: "structural-ai-preamble" },
	{ regex: /\n\n[\s\S]*\n\n/, reason: "structural-multi-paragraph" },
	{ regex: /^["']/, reason: "structural-quoted-output" },
	// Only match actual markdown (bold, links, headers) — NOT plain underscores
	// which are used in fill-in-blank format ("the most underrated ___ is ___")
	{ regex: /\*\*|\[.*\]\(.*\)|^#+\s/, reason: "structural-markdown" },
	{ regex: /\+\d{8,}/, reason: "structural-phone-number" },
	{ regex: /\d{3}[-.\s]?\d{3}[-.\s]?\d{4}/, reason: "structural-phone-number" },
	{
		regex: /^(h{2,}m{2,}|ugh+|meh+|bleh+|oof+|bruh+)\W*$/i,
		reason: "structural-filler-only",
	},
	// Reply Engagement Strategy S6: Meta penalizes hollow engagement bait
	// Patterns require imperative framing (start of sentence or after punctuation)
	{
		regex:
			/(?:^|[.!?]\s*)(like if you|share if you|tag \d+ friends?|repost if|like and comment)\b/i,
		reason: "structural-engagement-bait",
	},
	{
		regex: /\b(follow for follow|f4f|like for like|l4l)\b/i,
		reason: "structural-engagement-bait",
	},
	// Voice Profile Engineering S3.3: em-dashes are "ChatGPT dash" — instant AI fingerprint
	{ regex: /\u2014|\u2013/, reason: "structural-em-dash" },
	// Voice Profile Engineering S3.3: terminal period — DISABLED 2026-04-06.
	// Was rejecting ~50% of posts. Casual slang ("tuff.", "deadass.", "bruh.") is normal
	// on Threads/IG. Other filters (complexity, em-dashes) catch actual AI artifacts.
	// { regex: /[a-zA-Z]{4,}\.\s*$/, reason: "structural-terminal-period" },
	// Voice Profile Engineering S3.3: semicolons never appear in casual social media
	{ regex: /;/, reason: "structural-semicolon" },
];

const SLOGAN_ENDINGS = [
	"that's tuff",
	"no cap",
	"on god",
	"fr fr",
	"deadass",
	"lowkey",
	"trust",
	"bruh",
	"based",
	"sheesh",
	"haha",
	"tbh",
	"ngl",
	"lol",
	"rn",
	"fr",
];

function normalizeSlangTail(content: string): string {
	return content
		.toLowerCase()
		.replace(/[’]/g, "'")
		.replace(/[^a-z0-9'\s]/g, " ")
		.replace(/\s+/g, " ")
		.trim();
}

function stackedSloganEnding(content: string): string | null {
	let tail = normalizeSlangTail(content);
	const matches: string[] = [];
	let matched = true;
	while (matched && tail.length > 0) {
		matched = false;
		for (const phrase of SLOGAN_ENDINGS) {
			if (tail === phrase || tail.endsWith(` ${phrase}`)) {
				matches.push(phrase);
				tail =
					tail === phrase
						? ""
						: tail.slice(0, tail.length - phrase.length).trimEnd();
				matched = true;
				break;
			}
		}
	}
	const unique = new Set(matches);
	if (matches.length >= 3 || unique.size < matches.length) {
		return matches.reverse().join(" ");
	}
	return null;
}

// ---------------------------------------------------------------------------
// ReDoS protection
// ---------------------------------------------------------------------------

function isSafeRegex(pattern: string): boolean {
	if (pattern.length > 500) return false;
	if (/(\+\+|\*\+|\+\*|\{\d+,\}\+|\*\*|\(\?[^)]*\)\+)/.test(pattern))
		return false;
	return true;
}

// ---------------------------------------------------------------------------
// Syllable complexity gate
// ---------------------------------------------------------------------------

/**
 * Count syllables in a word by counting vowel groups.
 * Not linguistically perfect but good enough for detecting AI verbosity.
 */
export function countSyllables(word: string): number {
	const w = word.toLowerCase().replace(/[^a-z]/g, "");
	if (w.length <= 2) return 1;
	// Count vowel groups
	const vowelGroups = w.match(/[aeiouy]+/g);
	if (!vowelGroups) return 1;
	let count = vowelGroups.length;
	// Silent trailing e
	if (w.endsWith("e") && count > 1) count--;
	// -le at end counts as syllable (e.g. "comfortable")
	if (w.endsWith("le") && w.length > 2 && !/[aeiouy]/.test(w[w.length - 3]!))
		count++;
	return Math.max(1, count);
}

/** Common 4+ syllable words real people actually use (not AI-tells) */
const COMPLEX_WORD_WHITELIST = new Set([
	// Original 25
	"everybody",
	"whatever",
	"especially",
	"literally",
	"apparently",
	"unfortunately",
	"automatically",
	"relationship",
	"anniversary",
	"personality",
	"entertainment",
	"information",
	"beautiful",
	"absolutely",
	"everything",
	"understand",
	"appreciate",
	"comfortable",
	"imagination",
	"ridiculous",
	"incredible",
	"university",
	"opportunity",
	"immediately",
	"alternative",
	// Everyday
	"experience",
	"communication",
	"available",
	"community",
	"emergency",
	"ordinary",
	"discovery",
	"ability",
	"activity",
	"delivery",
	"evaluation",
	"economy",
	"majority",
	"territory",
	"necessary",
	"interesting",
	"obviously",
	"seriously",
	"definitely",
	"basically",
	"eventually",
	"originally",
	"particular",
	"situation",
	"temporary",
	// Social / relationship
	"ceremony",
	"congratulations",
	"individual",
	"emotional",
	"generation",
	"celebration",
	"conversation",
	"unforgettable",
	"vulnerability",
	"insecurity",
	"jealousy",
	"compatibility",
	// Technology / internet
	"notification",
	"application",
	"photography",
	"technology",
	"accessories",
	"operating",
	"security",
	"documentary",
	"repository",
	"algorithm",
	// Food / lifestyle
	"avocado",
	"pepperoni",
	"guacamole",
	"cauliflower",
	"watermelon",
	"refrigerator",
	"cafeteria",
	"vegetarian",
	// Education / work
	"education",
	"professional",
	"organization",
	"examination",
	"vocabulary",
	"laboratory",
	"elementary",
	// Places / general
	"california",
	"material",
	"memorial",
	"category",
	"disability",
	"directory",
	"voluntary",
	"popularity",
	"reality",
	"anxiety",
	"creativity",
	"curiosity",
	"electricity",
	"identity",
	"infinity",
	"priority",
	"possibility",
	"responsibility",
]);

/**
 * Check if content contains AI-typical complex vocabulary.
 * Counts ALL 4+ syllable words not in the whitelist.
 * 1-2 flagged → medium severity (soft flag)
 * 3+ flagged → high severity (hard reject in filterContent)
 */
function checkSyllableComplexity(content: string): FilterFlag | null {
	const words = content
		.replace(/[^a-zA-Z\s'-]/g, "")
		.split(/\s+/)
		.filter(Boolean);
	const flagged: string[] = [];
	for (const word of words) {
		const clean = word.toLowerCase().replace(/[^a-z]/g, "");
		if (clean.length < 4) continue;
		if (COMPLEX_WORD_WHITELIST.has(clean)) continue;
		if (countSyllables(clean) >= 4) {
			flagged.push(clean);
		}
	}
	if (flagged.length === 0) return null;
	const severity = flagged.length >= 3 ? "high" : "medium";
	return {
		pattern: "ai-complex-vocabulary",
		severity,
		message: `${flagged.length} complex word(s): "${flagged.slice(0, 3).join('", "')}"${flagged.length > 3 ? ` (+${flagged.length - 3} more)` : ""} — possible AI-generated text`,
	};
}

// ---------------------------------------------------------------------------
// Burstiness enforcement (consecutive length check)
// ---------------------------------------------------------------------------

/**
 * Check if the new post's character count is within 20% of both recent posts.
 * If all 3 have similar length, flag as repetitive.
 */
function checkRepetitiveLength(
	content: string,
	recentPosts: string[],
): FilterFlag | null {
	if (recentPosts.length < 2) return null;
	const newLen = content.length;
	const len1 = recentPosts[0]!.length;
	const len2 = recentPosts[1]!.length;
	// Check if newLen is within 20% of both recent posts
	const within20Pct = (a: number, b: number) => {
		if (b === 0) return a === 0;
		return Math.abs(a - b) / b <= 0.2;
	};
	if (within20Pct(newLen, len1) && within20Pct(newLen, len2)) {
		return {
			pattern: "repetitive-length",
			severity: "low",
			message: "3 consecutive posts with similar length",
		};
	}
	return null;
}

// ---------------------------------------------------------------------------
// Config resolver
// ---------------------------------------------------------------------------

export function resolveFilterConfig(
	dbPatterns: FilterPattern[] | null | undefined,
	dbMaxLength: number | null | undefined,
	dbMaxEmojis: number | null | undefined,
	dbMinLength?: number | null | undefined,
	nicheMode?: "default" | "thirst",
): FilterConfig {
	return {
		// DB patterns are ADDITIVE — supplement defaults, not replace them.
		// Safety blacklist is enforced separately and can never be overridden.
		patterns:
			Array.isArray(dbPatterns) && dbPatterns.length > 0
				? [...DEFAULT_PATTERNS, ...dbPatterns]
				: DEFAULT_PATTERNS,
		minLength:
			typeof dbMinLength === "number" ? dbMinLength : DEFAULT_MIN_LENGTH,
		maxLength:
			typeof dbMaxLength === "number" ? dbMaxLength : DEFAULT_MAX_LENGTH,
		maxEmojis:
			typeof dbMaxEmojis === "number" ? dbMaxEmojis : DEFAULT_MAX_EMOJIS,
		nicheMode: nicheMode ?? "default",
	};
}

// ---------------------------------------------------------------------------
// Core filter
// ---------------------------------------------------------------------------

export function filterContent(
	content: string,
	config: FilterConfig,
	sourceType?: string,
	recentPosts?: string[],
	avoidWords?: string[],
): FilterResult {
	if (!content || content.trim().length === 0) {
		return { passed: false, reason: "empty-content" };
	}

	const isManualPost = sourceType === "manual";
	const isCompetitorPost =
		sourceType === "competitor_direct" || sourceType === "competitor_copy";

	// Competitor posts skip structural/emoji/pattern checks but MUST still hit
	// the safety blacklist — a competitor could post explicit content that would
	// get our accounts banned if we copy it verbatim.

	if (!isManualPost && !isCompetitorPost) {
		if (
			content.trim().length < config.minLength &&
			!isShortProfileCuriosityHook(content)
		) {
			return {
				passed: false,
				reason: "too-short",
				matchedText: `${content.trim().length} chars (min ${config.minLength})`,
			};
		}
		if (content.length > config.maxLength) {
			return {
				passed: false,
				reason: "too-long",
				matchedText: `${content.length} chars (max ${config.maxLength})`,
			};
		}
		const emojiCount = countEmojis(content);
		if (emojiCount > config.maxEmojis) {
			return {
				passed: false,
				reason: "too-many-emojis",
				matchedText: `${emojiCount} emojis (max ${config.maxEmojis})`,
			};
		}
	}

	// Structural checks (skip for manual posts)
	if (!isManualPost) {
		for (const { regex, reason } of STRUCTURAL_PATTERNS) {
			const match = content.match(regex);
			if (match) return { passed: false, reason, matchedText: match[0] };
		}
		const slangStack = stackedSloganEnding(content);
		if (slangStack) {
			return {
				passed: false,
				reason: "structural-stacked-slang-ending",
				matchedText: slangStack,
			};
		}
	}

	// Safety blacklist — applies to ALL content (manual, AI, competitor)
	const blacklist =
		config.nicheMode === "thirst"
			? SAFETY_BLACKLIST_THIRST
			: SAFETY_BLACKLIST_DEFAULT;
	const safetyMatch = content.match(blacklist);
	if (safetyMatch) {
		return {
			passed: false,
			reason: "safety-blacklist",
			matchedText: safetyMatch[0],
		};
	}
	if (!isManualPost) {
		const discoverability = validateDiscoverabilitySafeContent(content);
		if (!discoverability.discoverabilitySafe) {
			return {
				passed: false,
				reason: discoverability.blockedReason,
				matchedText: discoverability.blockedTerms[0]?.matchedText,
			};
		}
	}

	// Voice profile avoid_words — hard reject on match (applies to AI + competitor)
	if (!isManualPost && avoidWords && avoidWords.length > 0) {
		const lower = content.toLowerCase();
		for (const word of avoidWords) {
			if (word && lower.includes(word.toLowerCase())) {
				return { passed: false, reason: "avoid-word", matchedText: word };
			}
		}
	}

	// DB-configurable patterns (skip for manual posts)
	if (!isManualPost) {
		for (const { pattern, label } of config.patterns) {
			try {
				if (!isSafeRegex(pattern)) continue;
				const re = new RegExp(pattern, "i");
				const match = content.match(re);
				if (match)
					return { passed: false, reason: label, matchedText: match[0] };
			} catch {
				logger.warn("Invalid content filter regex", { pattern, label });
			}
		}
	}

	// --- Soft flags (non-blocking) ---
	const flags: FilterFlag[] = [];

	// Syllable complexity gate (skip for manual posts)
	// 3+ complex words → hard reject; 1-2 → soft flag
	if (!isManualPost) {
		const complexFlag = checkSyllableComplexity(content);
		if (complexFlag) {
			if (complexFlag.severity === "high") {
				return {
					passed: false,
					reason: "ai-complex-vocabulary-overload",
					matchedText: complexFlag.message,
				};
			}
			flags.push(complexFlag);
		}
	}

	// Burstiness enforcement — consecutive length check (skip for manual posts)
	if (!isManualPost && recentPosts && recentPosts.length >= 2) {
		const lengthFlag = checkRepetitiveLength(content, recentPosts);
		if (lengthFlag) flags.push(lengthFlag);
	}

	return { passed: true, ...(flags.length > 0 ? { flags } : {}) };
}

// ---------------------------------------------------------------------------
// Batch filter with logging
// ---------------------------------------------------------------------------

export function filterAndLog(
	content: string,
	sourceType: string,
	config: FilterConfig,
	context: { workspaceId: string; groupId?: string | undefined },
	recentPosts?: string[],
	avoidWords?: string[],
): FilterResult {
	const result = filterContent(
		content,
		config,
		sourceType,
		recentPosts,
		avoidWords,
	);

	if (!result.passed) {
		logger.info("Content filter rejected", {
			reason: result.reason,
			matchedText: result.matchedText,
			sourceType,
			contentPreview: content.substring(0, 80),
			workspaceId: context.workspaceId,
			groupId: context.groupId,
		});
	}

	if (result.flags && result.flags.length > 0) {
		logger.info("Content filter flags", {
			flags: result.flags.map((f) => `${f.pattern}:${f.severity}`),
			sourceType,
			contentPreview: content.substring(0, 80),
			workspaceId: context.workspaceId,
			groupId: context.groupId,
		});
	}

	return result;
}

// ---------------------------------------------------------------------------
// Niche detection helper
// ---------------------------------------------------------------------------

export function isThirstVoice(voiceProfileStr?: string | null): boolean {
	if (!voiceProfileStr) return false;
	const v = voiceProfileStr.toLowerCase();
	return (
		v.includes("thirst") ||
		v.includes("dating") ||
		v.includes("sexy") ||
		v.includes("flirt") ||
		v.includes("spicy") ||
		v.includes("gfe") ||
		v.includes("onlyfans") ||
		v.includes("seduct") ||
		v.includes("innuendo")
	);
}
