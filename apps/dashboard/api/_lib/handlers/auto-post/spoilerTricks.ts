// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * Spoiler Tricks — Threads engagement feature
 *
 * Uses Threads' native spoiler text feature to hide single letters,
 * creating double-meaning posts. E.g., "can you luck me" with spoiler
 * on "l" → readers see "can you ▓uck me" → tap reveals it's "luck".
 *
 * The actual text is always innocent — passes all content filters.
 * The visual trick creates intrigue and drives taps (engagement).
 */

import { logger } from "../../logger.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Stored in auto_post_queue.text_spoilers JSONB */
export interface SpoilerWordMeta {
	word: string; // The innocent word in the post (e.g., "luck")
	charOffset: number; // Offset within the word to hide (e.g., 0 for "l")
	charLength: number; // Length of hidden chars (e.g., 1)
}

/** Threads API spoiler entity */
export interface SpoilerEntity {
	entity_type: "SPOILER";
	offset: number;
	length: number;
}

// ---------------------------------------------------------------------------
// Spoiler word map — innocent words that look explicit when letter is hidden
// ---------------------------------------------------------------------------

export interface SpoilerWord {
	word: string; // The clean word
	charOffset: number; // Which char(s) to hide (within the word)
	charLength: number; // How many chars to hide
	impliedWord: string; // What readers think they see
	templates: string[]; // Natural sentence templates ({{WORD}} = placeholder)
}

export const SPOILER_WORDS: SpoilerWord[] = [
	// _uck family → "fuck"
	{
		word: "luck",
		charOffset: 0,
		charLength: 1,
		impliedWord: "fuck",
		templates: [
			"can you luck me tonight",
			"wanna get lucky?",
			"out of luck again",
			"need some luck rn",
			"feeling lucky?",
			"wish me luck babe",
			"all out of luck",
			"test ur luck?",
		],
	},
	{
		word: "duck",
		charOffset: 0,
		charLength: 1,
		impliedWord: "fuck",
		templates: [
			"what the duck",
			"oh duck me",
			"duck it lets go",
			"duck around n find out",
			"ducking done with today",
		],
	},
	{
		word: "buck",
		charOffset: 0,
		charLength: 1,
		impliedWord: "fuck",
		templates: ["dont give a buck", "zero bucks given", "buck it im going out"],
	},
	{
		word: "truck",
		charOffset: 0,
		charLength: 2,
		impliedWord: "fuck",
		templates: ["truck yeah", "what the truck"],
	},
	{
		word: "tuck",
		charOffset: 0,
		charLength: 1,
		impliedWord: "fuck",
		templates: [
			"tuck me in?",
			"come tuck me in tonight",
			"someone tuck me in 🥺",
		],
	},
	// _itch family → "bitch"
	{
		word: "witch",
		charOffset: 0,
		charLength: 1,
		impliedWord: "bitch",
		templates: [
			"im such a witch",
			"witch vibes only",
			"call me a witch idc",
			"witch mode activated",
		],
	},
	{
		word: "switch",
		charOffset: 0,
		charLength: 2,
		impliedWord: "bitch",
		templates: ["ready to switch up", "watch me switch"],
	},
	// _ass family → "ass"
	{
		word: "bass",
		charOffset: 0,
		charLength: 1,
		impliedWord: "ass",
		templates: [
			"that bass tho",
			"nice bass",
			"love me some bass",
			"all about that bass",
		],
	},
	{
		word: "class",
		charOffset: 0,
		charLength: 2,
		impliedWord: "ass",
		templates: [
			"no class today",
			"skipping class again",
			"class is boring ngl",
		],
	},
	{
		word: "glass",
		charOffset: 0,
		charLength: 2,
		impliedWord: "ass",
		templates: ["raise ur glass", "glass half full babe"],
	},
	// _hit family → "shit"
	{
		word: "shirt",
		charOffset: 0,
		charLength: 2,
		impliedWord: "hit",
		templates: ["nice shirt btw", "steal ur shirt?", "ur shirt or mine"],
	},
	// _ussy family → suggestive
	{
		word: "fussy",
		charOffset: 0,
		charLength: 1,
		impliedWord: "pussy",
		templates: ["dont be fussy", "im not fussy promise", "so fussy tonight"],
	},
];

// ---------------------------------------------------------------------------
// Curiosity-Gap Spoiler Words — hide entire relatable words to drive taps
// ---------------------------------------------------------------------------

export interface CuriosityWord {
	word: string; // The word to fully hide
	templates: string[]; // Natural sentence templates ({{WORD}} = placeholder)
}

export const CURIOSITY_WORDS: CuriosityWord[] = [
	{
		word: "single",
		templates: [
			"so tired of being single .",
			"being single is not it rn",
			"single era hits different at night",
			"still single btw",
			"another day being single 😭",
		],
	},
	{
		word: "lonely",
		templates: [
			"feeling lonely tonight ngl",
			"why am i always lonely",
			"lonely but too picky to settle",
			"lonely era is getting old",
		],
	},
	{
		word: "taken",
		templates: [
			"still not taken btw",
			"everyone i like is taken 💔",
			"imagine being taken rn couldn't be me",
		],
	},
	{
		word: "happy",
		templates: [
			"trying so hard to be happy",
			"just wanna be happy is that too much",
			"fake happy is exhausting",
			"genuinely happy rn wow",
		],
	},
	{
		word: "love",
		templates: [
			"i just want love bro",
			"is love even real anymore",
			"looking for love in all the wrong places",
			"love is so confusing",
		],
	},
	{
		word: "toxic",
		templates: [
			"im kinda toxic ngl",
			"attracted to toxic people again",
			"my toxic trait is overthinking everything",
			"toxic but self aware 💅",
		],
	},
	{
		word: "obsessed",
		templates: [
			"currently obsessed 👀",
			"im lowkey obsessed",
			"why am i so obsessed",
			"obsessed with this rn",
		],
	},
	{
		word: "jealous",
		templates: [
			"trying not to be jealous rn",
			"a little jealous ngl",
			"jealous of everyone in a relationship",
		],
	},
	{
		word: "scared",
		templates: [
			"too scared to text first",
			"scared of catching feelings again",
			"lowkey scared of commitment",
		],
	},
	{
		word: "crying",
		templates: [
			"not me crying over this",
			"literally crying at 2am again",
			"crying but make it cute",
		],
	},
];

const CURIOSITY_CHANCE = 0.15; // 15% of AI posts get a curiosity-gap spoiler

/**
 * Decide whether this post slot should get a curiosity-gap spoiler.
 * Returns a random CuriosityWord if yes, null if no.
 */
export function maybeCuriositySpoiler(): CuriosityWord | null {
	if (Math.random() > CURIOSITY_CHANCE) return null;
	return CURIOSITY_WORDS[Math.floor(Math.random() * CURIOSITY_WORDS.length)]!;
}

/**
 * Build an AI prompt instruction for a curiosity-gap spoiler post.
 * The entire word will be hidden behind a spoiler tag.
 */
export function buildCuriosityPromptInstruction(cw: CuriosityWord): string {
	const example = cw.templates[Math.floor(Math.random() * cw.templates.length)];
	return `CURIOSITY SPOILER: Include the word "${cw.word}" in the post. Example: "${example}". The word "${cw.word}" will be FULLY hidden behind a spoiler tag on Threads — readers see a blurred block and MUST tap to reveal it. This creates a curiosity gap that drives massive engagement. Keep the post natural and relatable.`;
}

/**
 * Find the curiosity word in final text and generate a SPOILER entity
 * that hides the entire word.
 */
export function resolveCuriositySpoilerEntities(
	finalText: string,
	word: string,
): SpoilerEntity[] | null {
	const lowerText = finalText.toLowerCase();
	const wordIndex = lowerText.indexOf(word.toLowerCase());

	if (wordIndex < 0) {
		logger.info("Curiosity word not found in final text, skipping", {
			word,
			textPreview: finalText.substring(0, 60),
		});
		return null;
	}

	return [
		{
			entity_type: "SPOILER",
			offset: wordIndex,
			length: word.length,
		},
	];
}

/**
 * Detect any naturally occurring curiosity words in post content.
 * Returns the word if found, null otherwise.
 */
export function detectNaturalCuriositySpoiler(content: string): string | null {
	const lower = content.toLowerCase();
	for (const cw of CURIOSITY_WORDS) {
		const idx = lower.indexOf(cw.word);
		if (idx >= 0) {
			const before = idx > 0 ? lower[idx - 1] : " ";
			const after =
				idx + cw.word.length < lower.length ? lower[idx + cw.word.length] : " ";
			if (/\W/.test(before!) && /\W/.test(after!)) {
				return cw.word;
			}
		}
	}
	return null;
}

// ---------------------------------------------------------------------------
// Chance to generate a double-meaning spoiler post (10-15% of AI posts)
// ---------------------------------------------------------------------------

const SPOILER_CHANCE = 0.12; // 12% of AI-generated posts

/**
 * Decide whether this post slot should attempt a spoiler trick.
 * Returns a random SpoilerWord if yes, null if no.
 */
export function maybeSpoilerPost(): SpoilerWord | null {
	if (Math.random() > SPOILER_CHANCE) return null;
	return SPOILER_WORDS[Math.floor(Math.random() * SPOILER_WORDS.length)]!;
}

/**
 * Pick a random template from a SpoilerWord for the AI prompt.
 */
export function getSpoilerTemplate(sw: SpoilerWord): string {
	return sw.templates[Math.floor(Math.random() * sw.templates.length)]!;
}

/**
 * After AI generation + humanization, find the spoiler word in the final text
 * and generate the SpoilerEntity for the Threads API.
 *
 * Returns null if the word was removed/modified during text transformations.
 */
export function resolveSpoilerEntities(
	finalText: string,
	meta: SpoilerWordMeta,
): SpoilerEntity[] | null {
	const lowerText = finalText.toLowerCase();
	const wordIndex = lowerText.indexOf(meta.word.toLowerCase());

	if (wordIndex < 0) {
		logger.info("Spoiler word not found in final text, skipping spoiler", {
			word: meta.word,
			textPreview: finalText.substring(0, 60),
		});
		return null;
	}

	return [
		{
			entity_type: "SPOILER",
			offset: wordIndex + meta.charOffset,
			length: meta.charLength,
		},
	];
}

/**
 * Build an AI prompt instruction for generating a post that uses the spoiler word.
 * This gets appended to the normal prompt for ~12% of posts.
 */
export function buildSpoilerPromptInstruction(sw: SpoilerWord): string {
	const example = getSpoilerTemplate(sw);
	return `SPOILER TRICK: For this post, naturally include the word "${sw.word}" in the text. Example: "${example}". The word "${sw.word}" will have a single letter hidden as a spoiler on Threads — this creates a playful double-meaning that drives engagement (taps to reveal). Keep the post sounding natural. The text itself must be clean/innocent.`;
}

/**
 * Scan an AI-generated post for any naturally occurring spoiler words.
 * If found, return the spoiler metadata. If not, return null.
 */
export function detectNaturalSpoiler(content: string): SpoilerWordMeta | null {
	const lower = content.toLowerCase();
	for (const sw of SPOILER_WORDS) {
		const idx = lower.indexOf(sw.word);
		if (idx >= 0) {
			// Verify it's a whole word (not part of another word)
			const before = idx > 0 ? lower[idx - 1] : " ";
			const after =
				idx + sw.word.length < lower.length ? lower[idx + sw.word.length] : " ";
			if (/\W/.test(before!) && /\W/.test(after!)) {
				return {
					word: sw.word,
					charOffset: sw.charOffset,
					charLength: sw.charLength,
				};
			}
		}
	}
	return null;
}

/**
 * Auto-detect spoiler words in any post content and return Threads SPOILER entities.
 * This is the universal entry point — works for manually scheduled posts, immediate
 * publishes, and auto-poster posts. No manual setup required.
 *
 * Returns null if no spoiler words are found in the content.
 */
export function autoDetectSpoilerEntities(
	content: string,
): SpoilerEntity[] | null {
	const meta = detectNaturalSpoiler(content);
	if (!meta) return null;
	return resolveSpoilerEntities(content, meta);
}

/**
 * For a generated post that doesn't naturally contain a spoiler word,
 * attempt to replace one template with a random spoiler template.
 * Returns new content + metadata, or null if replacement doesn't fit.
 */
export function injectSpoilerPost(): {
	content: string;
	meta: SpoilerWordMeta;
} {
	const sw = SPOILER_WORDS[Math.floor(Math.random() * SPOILER_WORDS.length)];
	const template = getSpoilerTemplate(sw!);
	return {
		content: template,
		meta: {
			word: sw!.word,
			charOffset: sw!.charOffset,
			charLength: sw!.charLength,
		},
	};
}
