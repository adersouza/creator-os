/**
 * Tests for server-side content filter (auto-post queue gate).
 *
 * Validates that banned patterns, structural checks, length limits,
 * and emoji limits correctly reject content before it enters the
 * auto_post_queue.
 */

import { describe, expect, it } from "vitest";
import {
	type FilterConfig,
	filterContent,
	isThirstVoice,
	resolveFilterConfig,
} from "../../api/_lib/handlers/auto-post/contentFilter";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function defaultConfig(): FilterConfig {
	return resolveFilterConfig(null, null, null);
}

// ---------------------------------------------------------------------------
// Default pattern tests
// ---------------------------------------------------------------------------

describe("contentFilter", () => {
	describe("default banned patterns", () => {
		const cfg = defaultConfig();

		// Only patterns still in DEFAULT_PATTERNS (ai-abstract, ai-cliche, etc.)
		const shouldReject: [string, string][] = [
			["She's radiating confidence in this photo", "ai-cliche"],
			["That magnetic force is truly wild today", "ai-cliche"],
			["She's magnetic and draws people in easily", "ai-cliche"],
			["Pure passion drives me forward each day", "ai-abstract"],
			["pure energy today is unmatched right now", "ai-abstract"],
			["pure bliss in this moment right now", "ai-abstract"],
			["Just living my best life out here today", "ai-cliche"],
		];

		for (const [text, expectedReason] of shouldReject) {
			it(`rejects: "${text.slice(0, 40)}..." (${expectedReason})`, () => {
				const result = filterContent(text, cfg);
				expect(result.passed).toBe(false);
				expect(result.reason).toBe(expectedReason);
			});
		}

		// These patterns were removed from DEFAULT_PATTERNS (filter simplified)
		const shouldPass = [
			"ngl you looked good in that last pic",
			"would you date someone taller than you",
			"that fit goes crazy not gonna lie",
			"thinking about you at 2am again",
			"be honest... do you text first or wait",
			"That sunset was unreal and so beautiful",
			"Hit 10k followers today on my account",
			"inner fire is overrated here for sure",
			"straight fire content dropping today now",
			"What's meant for you will always find way",
			"Don't chase trends just be yourself here",
			"vibe shift happening in this room today",
			"Time to manifest greatness in my life",
			"Main character energy today is real for sure",
		];

		for (const text of shouldPass) {
			it(`passes: "${text.slice(0, 40)}..."`, () => {
				const result = filterContent(text, cfg);
				expect(result.passed).toBe(true);
			});
		}
	});

	describe("expanded quality blacklist", () => {
		const cfg = defaultConfig();

		// Hallucinated pets/scenarios
		it("rejects hallucinated pet content", () => {
			expect(filterContent("my cat just did the funniest thing today", cfg).passed).toBe(false);
			expect(filterContent("my dog is being extra clingy right now", cfg).passed).toBe(false);
			expect(filterContent("watching my furbaby play is everything", cfg).passed).toBe(false);
			expect(filterContent("dust bunnies everywhere in my apartment", cfg).passed).toBe(false);
		});

		// Office/persona — caught by safety blacklist (WRONG_PERSONA_TERMS)
		it("rejects office/meeting content via safety blacklist", () => {
			expect(filterContent("taking meeting notes while scrolling threads", cfg).passed).toBe(false);
			expect(filterContent("ditching your work persona after 5 pm hits", cfg).passed).toBe(false);
		});

		// 3rd person self-reference — caught by safety blacklist (WRONG_PERSONA_TERMS)
		it("rejects 3rd person persona references", () => {
			expect(filterContent("is he really enough for lola tho lets see", cfg).passed).toBe(false);
			expect(filterContent("not fun enough for larissa sorry sweetie", cfg).passed).toBe(false);
		});

		// AI cliche patterns still in DEFAULT_PATTERNS
		it("catches heartwarming as ai-cliche", () => {
			expect(filterContent("the most heartwarming story ever right now", cfg).passed).toBe(false);
		});
	});

	describe("structural pattern checks", () => {
		const cfg = defaultConfig();

		it("rejects numbered list format", () => {
			const result = filterContent("1. first thing you should do is smile", cfg);
			expect(result.passed).toBe(false);
			expect(result.reason).toBe("structural-numbered-list");
		});

		it("rejects AI category labels", () => {
			const result = filterContent("Reach Post 1: check out this hot take", cfg);
			expect(result.passed).toBe(false);
			expect(result.reason).toBe("structural-category-label");
		});

		it("rejects leaked autoposter taxonomy labels", () => {
			const leakedLabels = [
				"specific topical question: what's your go-to sad girl anthem??",
				"recommendation request: best chill anime after a long day?",
				"identity statement: i'm a 9 but my anime taste is unhinged",
				"observation winner: wearing a crop top to the gym is not a crime",
				"anime_dateability_question: would you date a girl who loves anime lore",
				"single_cook_clean_identity: i'm single and i can cook",
				"clone family: headset cute validation",
			];

			for (const text of leakedLabels) {
				const result = filterContent(text, cfg);
				expect(result.passed).toBe(false);
				expect(result.reason).toBe("structural-taxonomy-label");
			}
		});

		it("rejects mechanical formula prefixes from generated content", () => {
			const formulaPosts = [
				"hot take: protein bars are overrated. trust",
				"unpopular opinion: cardio is fake. on god",
				"opinion: pre-workout should taste like candy",
				"confession: i still listen to my middle school playlist",
				"asking for a friend: is it weird if i still have a night light?",
			];

			for (const text of formulaPosts) {
				const result = filterContent(text, cfg);
				expect(result.passed).toBe(false);
				expect(result.reason).toBe("structural-formula-prefix");
			}
		});

		it("allows non-label uses of hot take and confession wording", () => {
			expect(filterContent("my hot take is that gym dates are underrated", cfg).passed).toBe(true);
			expect(filterContent("i have a confession about my gym crush", cfg).passed).toBe(true);
		});

		it("rejects stacked slogan endings while allowing occasional persona slang", () => {
			const stacked = filterContent("protein coffee is superior trust fr no cap", cfg);
			expect(stacked.passed).toBe(false);
			expect(stacked.reason).toBe("structural-stacked-slang-ending");

			expect(filterContent("would you date a girl who lifts heavy? no cap", cfg).passed).toBe(true);
		});

		it("rejects AI preamble", () => {
			const r1 = filterContent("here is a great post for your account", cfg);
			expect(r1.passed).toBe(false);
			expect(r1.reason).toBe("structural-ai-preamble");

			const r2 = filterContent("here's what i think about this topic", cfg);
			expect(r2.passed).toBe(false);
			expect(r2.reason).toBe("structural-ai-preamble");
		});

		it("allows single paragraph break (humanize adds this)", () => {
			const result = filterContent("first line here\n\nsecond line here", cfg);
			expect(result.passed).toBe(true);
		});

		it("rejects 2+ paragraph breaks (multi-paragraph AI artifact)", () => {
			const result = filterContent("first paragraph\n\nsecond paragraph\n\nthird paragraph", cfg);
			expect(result.passed).toBe(false);
			expect(result.reason).toBe("structural-multi-paragraph");
		});

		it("rejects posts starting with quotes", () => {
			const result = filterContent('"this is what she said" is overused', cfg);
			expect(result.passed).toBe(false);
			expect(result.reason).toBe("structural-quoted-output");
		});

		it("rejects markdown artifacts", () => {
			const result = filterContent("this is **bold** and should not be here", cfg);
			expect(result.passed).toBe(false);
			expect(result.reason).toBe("structural-markdown");
		});
	});

	describe("length limits", () => {
		it("rejects posts over maxLength (default 500)", () => {
			const cfg = defaultConfig();
			const longText = "a".repeat(501);
			const result = filterContent(longText, cfg);
			expect(result.passed).toBe(false);
			expect(result.reason).toBe("too-long");
		});

		it("passes posts at exactly maxLength", () => {
			const cfg = defaultConfig();
			const text = "a".repeat(80); // default max is now 80 (aligned with prompt)
			const result = filterContent(text, cfg);
			expect(result.passed).toBe(true);
		});

		it("respects custom maxLength from DB", () => {
			const cfg = resolveFilterConfig(null, 200, null);
			const at200 = "a".repeat(200);
			const at201 = "a".repeat(201);
			expect(filterContent(at200, cfg).passed).toBe(true);
			expect(filterContent(at201, cfg).passed).toBe(false);
		});

		it("rejects posts under minLength", () => {
			const cfg = defaultConfig();
			const result = filterContent("hi", cfg);
			// Min length is now 5 (ultra-short hooks allowed). "hi" = 2 chars, still under.
			expect(result.passed).toBe(false);
			expect(result.reason).toBe("too-short");
		});

		it("passes ultra-short hooks at new min of 5", () => {
			const cfg = defaultConfig();
			expect(filterContent("hi 💕", cfg).passed).toBe(true);
			expect(filterContent("you like?", cfg).passed).toBe(true);
		});
	});

	describe("emoji limit", () => {
		it("rejects posts with 4+ emojis (default max 3)", () => {
			const cfg = defaultConfig();
			const result = filterContent("Wow this is fire 🔥🔥🔥🔥", cfg);
			expect(result.passed).toBe(false);
			expect(result.reason).toBe("too-many-emojis");
		});

		it("passes posts with 3 emojis at default max", () => {
			const cfg = defaultConfig();
			const result = filterContent("Chilling at the park today 🔥✨🌊", cfg);
			expect(result.passed).toBe(true);
		});

		it("passes posts with 2 emojis", () => {
			const cfg = defaultConfig();
			const result = filterContent("Chilling at the park today 🔥✨", cfg);
			expect(result.passed).toBe(true);
		});

		it("passes posts with 0 emojis", () => {
			const cfg = defaultConfig();
			const result = filterContent("No emojis here at all today", cfg);
			expect(result.passed).toBe(true);
		});

		it("respects custom maxEmojis", () => {
			const cfg = resolveFilterConfig(null, null, 5);
			const result = filterContent("These five are allowed right 🔥🔥🔥🔥🔥", cfg);
			expect(result.passed).toBe(true);

			const result6 = filterContent("But six is too many for sure 🔥🔥🔥🔥🔥🔥", cfg);
			expect(result6.passed).toBe(false);
		});
	});

	describe("empty content", () => {
		it("rejects empty string", () => {
			const cfg = defaultConfig();
			expect(filterContent("", cfg).passed).toBe(false);
			expect(filterContent("", cfg).reason).toBe("empty-content");
		});

		it("rejects whitespace-only", () => {
			const cfg = defaultConfig();
			expect(filterContent("   ", cfg).passed).toBe(false);
		});
	});

	describe("custom patterns from DB", () => {
		it("uses DB patterns when provided (additive with defaults)", () => {
			const cfg = resolveFilterConfig(
				[{ pattern: "\\bfoo\\b", label: "no-foo" }],
				null,
				null,
			);
			expect(filterContent("This has foo in it and more text here", cfg).passed).toBe(false);
			expect(filterContent("This has foo in it and more text here", cfg).reason).toBe("no-foo");
			// DB patterns are ADDITIVE — default patterns still apply
			expect(filterContent("pure energy today is real for sure", cfg).passed).toBe(false);
		});

		it("uses only defaults when DB patterns is empty array", () => {
			const cfg = resolveFilterConfig([], null, null);
			// "radiating" is in DEFAULT_PATTERNS as ai-cliche
			expect(filterContent("she is radiating confidence right now", cfg).passed).toBe(false);
		});

		it("skips invalid regex without crashing", () => {
			const cfg = resolveFilterConfig(
				[{ pattern: "[invalid(", label: "bad-regex" }],
				null,
				null,
			);
			const result = filterContent("anything at all works fine here", cfg);
			expect(result.passed).toBe(true);
		});
	});

	describe("real-world garbage caught by safety blacklist or DEFAULT_PATTERNS", () => {
		const cfg = defaultConfig();

		// Items caught by WRONG_PERSONA_TERMS (safety blacklist) or DEFAULT_PATTERNS
		const realGarbage: string[] = [
			"my cat's dust bunny adventures were great",  // "dust bunn" → ai-hallucination
			"the best meeting notes are no notes at all",  // "meeting notes" → corporate
			"my dog is being extra today not gonna lie",  // "my dog" → safety-blacklist
		];

		for (const text of realGarbage) {
			it(`catches: "${text.slice(0, 45)}..."`, () => {
				const result = filterContent(text, cfg);
				expect(result.passed).toBe(false);
			});
		}
	});

	describe("thirst niche mode", () => {
		function thirstConfig(): FilterConfig {
			return resolveFilterConfig(null, null, null, undefined, "thirst");
		}

		const thirstTermsThatShouldPass: string[] = [
			"feeling horny on a tuesday night honestly",
			"stoners unite we love a good vibe here",
			"wet for you and i dont care who knows",
			"420 friendly only please and thank you",
		];

		for (const text of thirstTermsThatShouldPass) {
			it(`thirst mode allows: "${text.slice(0, 40)}..."`, () => {
				const cfg = thirstConfig();
				const result = filterContent(text, cfg);
				expect(result.passed).toBe(true);
			});
		}

		const hardBanTermsThatStillBlock: [string, string][] = [
			["send nudes right now babe please ok ok", "nudes"],
			["pussy is overrated honestly who cares", "pussy"],
			["that dick pic was something else for real", "dick"],
			["make me cum tonight please babe lets go", "cum"],
			["just turned 18 and ready for it all now", "just turned 18"],
		];

		for (const [text, term] of hardBanTermsThatStillBlock) {
			it(`thirst mode still blocks hard ban: "${text.slice(0, 40)}..." (${term})`, () => {
				const cfg = thirstConfig();
				const result = filterContent(text, cfg);
				expect(result.passed).toBe(false);
				expect(result.reason).toBe("safety-blacklist");
			});
		}

		it("default mode still blocks thirst-allow terms", () => {
			const cfg = resolveFilterConfig(null, null, null);
			expect(filterContent("feeling horny on a tuesday night honestly", cfg).passed).toBe(false);
			expect(filterContent("check my onlyfans link in bio for more", cfg).passed).toBe(false);
			expect(filterContent("stoners unite we love a good vibe here", cfg).passed).toBe(false);
			expect(filterContent("wet for you and i dont care who knows", cfg).passed).toBe(false);
			expect(filterContent("420 friendly only please and thank you", cfg).passed).toBe(false);
		});
	});

	describe("isThirstVoice helper", () => {
		it("returns true for thirst-related voice profiles", () => {
			expect(isThirstVoice("thirst-trap-dating")).toBe(true);
			expect(isThirstVoice("Sexy Flirty Vibes")).toBe(true);
			expect(isThirstVoice("spicy-content-creator")).toBe(true);
			expect(isThirstVoice("GFE persona")).toBe(true);
			expect(isThirstVoice("OnlyFans promo")).toBe(true);
			expect(isThirstVoice("seductive-innuendo")).toBe(true);
		});

		it("returns false for non-thirst voice profiles", () => {
			expect(isThirstVoice("fitness-motivation")).toBe(false);
			expect(isThirstVoice("tech-news")).toBe(false);
			expect(isThirstVoice("casual-lifestyle")).toBe(false);
		});

		it("returns false for null/undefined", () => {
			expect(isThirstVoice(null)).toBe(false);
			expect(isThirstVoice(undefined)).toBe(false);
			expect(isThirstVoice("")).toBe(false);
		});
	});
});
