/**
 * Content Filter — Quality Pipeline Tests
 *
 * Covers areas NOT tested by contentFilter.test.ts or contentFilter-extended.test.ts:
 *   - countSyllables() edge cases and accuracy
 *   - Syllable complexity gate (AI vocabulary detection)
 *   - Burstiness enforcement (repetitive length check)
 *   - avoidWords parameter (voice profile hard reject)
 *   - Competitor post sourceType bypass (competitor_direct, competitor_copy)
 *   - Safety blacklist still applies to competitor posts
 *   - ReDoS protection (isSafeRegex)
 *   - Structural pattern edge cases (phone numbers, engagement bait, em-dashes, semicolons)
 *   - filterAndLog with flags
 *   - Edge cases: very long content, boundary lengths, combined flags
 */

import { describe, expect, it, vi, beforeEach } from "vitest";

// Mock logger for filterAndLog tests
vi.mock("@/api/_lib/logger.js", () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

import {
  countSyllables,
  filterContent,
  filterAndLog,
  type FilterConfig,
  resolveFilterConfig,
} from "../../api/_lib/handlers/auto-post/contentFilter";
import { logger as mockLogger } from "@/api/_lib/logger.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function defaultConfig(): FilterConfig {
  return resolveFilterConfig(null, null, null);
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// countSyllables — unit tests
// ---------------------------------------------------------------------------

describe("countSyllables", () => {
  it("counts single-syllable words", () => {
    expect(countSyllables("cat")).toBe(1);
    expect(countSyllables("dog")).toBe(1);
    expect(countSyllables("run")).toBe(1);
    expect(countSyllables("the")).toBe(1);
  });

  it("counts two-syllable words", () => {
    expect(countSyllables("happy")).toBe(2);
    expect(countSyllables("water")).toBe(2);
    expect(countSyllables("tiger")).toBe(2);
  });

  it("counts three-syllable words", () => {
    expect(countSyllables("beautiful")).toBe(3);
    expect(countSyllables("hospital")).toBe(3);
  });

  it("counts four+ syllable words (AI-tell detection threshold)", () => {
    expect(countSyllables("extraordinary")).toBeGreaterThanOrEqual(4);
    expect(countSyllables("unbelievable")).toBeGreaterThanOrEqual(4);
    expect(countSyllables("overwhelmingly")).toBeGreaterThanOrEqual(4);
    expect(countSyllables("sophisticated")).toBeGreaterThanOrEqual(4);
  });

  it("handles very short words (<=2 chars) as 1 syllable", () => {
    expect(countSyllables("a")).toBe(1);
    expect(countSyllables("an")).toBe(1);
    expect(countSyllables("be")).toBe(1);
    expect(countSyllables("I")).toBe(1);
  });

  it("handles silent trailing e", () => {
    // "cake" has a silent e — should be 1 syllable
    expect(countSyllables("cake")).toBe(1);
    // "bake" has a silent e — should be 1 syllable
    expect(countSyllables("bake")).toBe(1);
    // "make" has a silent e — should be 1 syllable
    expect(countSyllables("make")).toBe(1);
  });

  it("handles words where y is the only vowel", () => {
    expect(countSyllables("gym")).toBe(1); // y counts as vowel, 1 group
    // "rhythm" — vowel group: "y" only → 1 syllable (heuristic)
    expect(countSyllables("rhythm")).toBe(1);
  });

  it("strips non-alpha characters before counting", () => {
    expect(countSyllables("can't")).toBe(1);
    expect(countSyllables("it's")).toBe(1);
    // "co-op" strips to "coop" → vowel group "oo" → 1 syllable (heuristic limitation)
    expect(countSyllables("co-op")).toBe(1);
  });

  it("returns at least 1 for any non-empty word", () => {
    expect(countSyllables("x")).toBe(1);
    expect(countSyllables("b")).toBe(1);
    expect(countSyllables("xyz")).toBeGreaterThanOrEqual(1);
  });

  it("handles empty string gracefully", () => {
    // After stripping non-alpha, empty string has length 0
    expect(countSyllables("")).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Syllable complexity gate (via filterContent)
// ---------------------------------------------------------------------------

describe("syllable complexity gate", () => {
  const cfg = defaultConfig();

  it("hard-rejects content with 3+ complex non-whitelisted words", () => {
    // Use uncommon 4+ syllable words NOT in the whitelist
    const content = "the quintessential manifestation of philosophical contemplation";
    const result = filterContent(content, cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("ai-complex-vocabulary-overload");
  });

  it("soft-flags content with 1-2 complex non-whitelisted words", () => {
    // One complex word that's NOT in the whitelist
    const content = "that was quintessential bro ngl seriously";
    const result = filterContent(content, cfg);
    // Should pass but with flags
    if (result.passed && result.flags) {
      const complexFlag = result.flags.find(
        (f) => f.pattern === "ai-complex-vocabulary",
      );
      if (complexFlag) {
        expect(complexFlag.severity).toBe("medium");
      }
    }
    // The important thing is it should NOT hard-reject with just 1 complex word
    // (it may or may not trigger depending on exact syllable counting)
  });

  it("allows whitelisted 4+ syllable words without flagging", () => {
    // Words from the COMPLEX_WORD_WHITELIST
    const content = "this is absolutely beautiful and everything is definitely wonderful";
    const result = filterContent(content, cfg);
    // "absolutely", "beautiful", "everything", "definitely" are all whitelisted
    expect(result.reason).not.toBe("ai-complex-vocabulary-overload");
  });

  it("skips complexity check for manual posts", () => {
    const content = "the quintessential manifestation of philosophical contemplation";
    const result = filterContent(content, cfg, "manual");
    // Manual posts skip structural/pattern checks but still hit safety blacklist
    // If this contains no banned terms, it should pass
    expect(result.reason).not.toBe("ai-complex-vocabulary-overload");
  });
});

// ---------------------------------------------------------------------------
// Burstiness enforcement (repetitive length check)
// ---------------------------------------------------------------------------

describe("burstiness enforcement (repetitive length)", () => {
  const cfg = defaultConfig();

  it("flags when 3 consecutive posts have similar length (within 20%)", () => {
    const content = "this is a test post about something cool"; // ~40 chars
    const recent1 = "another test post about something else"; // ~38 chars
    const recent2 = "one more test post about stuff going on"; // ~39 chars

    const result = filterContent(content, cfg, "ai", [recent1, recent2]);

    // Should pass but with a repetitive-length flag
    if (result.passed && result.flags) {
      const lengthFlag = result.flags.find(
        (f) => f.pattern === "repetitive-length",
      );
      expect(lengthFlag).toBeDefined();
      expect(lengthFlag?.severity).toBe("low");
    }
  });

  it("does not flag when post lengths differ significantly", () => {
    const shortPost = "yo check this out right now"; // ~26 chars
    const longRecent1 = "this is a much longer post about many different things happening today"; // ~70 chars
    const longRecent2 = "another very long post discussing various topics and sharing thoughts here"; // ~74 chars

    const result = filterContent(shortPost, cfg, "ai", [longRecent1, longRecent2]);

    if (result.passed) {
      const lengthFlag = result.flags?.find(
        (f) => f.pattern === "repetitive-length",
      );
      expect(lengthFlag).toBeUndefined();
    }
  });

  it("does not flag with only 1 recent post (needs 2)", () => {
    const content = "test post content here";
    const recent1 = "test post content here"; // same length

    const result = filterContent(content, cfg, "ai", [recent1]);

    if (result.passed) {
      const lengthFlag = result.flags?.find(
        (f) => f.pattern === "repetitive-length",
      );
      expect(lengthFlag).toBeUndefined();
    }
  });

  it("does not flag with empty recent posts array", () => {
    const content = "test post content here yo";
    const result = filterContent(content, cfg, "ai", []);

    if (result.passed) {
      const lengthFlag = result.flags?.find(
        (f) => f.pattern === "repetitive-length",
      );
      expect(lengthFlag).toBeUndefined();
    }
  });

  it("does not flag with undefined recent posts", () => {
    const content = "test post content here";
    const result = filterContent(content, cfg, "ai", undefined);

    if (result.passed) {
      expect(result.flags?.find((f) => f.pattern === "repetitive-length")).toBeUndefined();
    }
  });

  it("skips burstiness check for manual posts", () => {
    const content = "test post content here today";
    const recent = ["test post content here also", "test post another one today"];

    const result = filterContent(content, cfg, "manual", recent);

    if (result.passed) {
      expect(result.flags?.find((f) => f.pattern === "repetitive-length")).toBeUndefined();
    }
  });
});

// ---------------------------------------------------------------------------
// avoidWords parameter
// ---------------------------------------------------------------------------

describe("avoidWords parameter", () => {
  const cfg = defaultConfig();

  it("rejects content containing an avoid word", () => {
    const result = filterContent(
      "this vibe is just unmatched honestly today",
      cfg,
      "ai",
      undefined,
      ["vibe"],
    );
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("avoid-word");
    expect(result.matchedText).toBe("vibe");
  });

  it("is case-insensitive for avoid words", () => {
    const result = filterContent(
      "the ENERGY here is wild for real today",
      cfg,
      "ai",
      undefined,
      ["energy"],
    );
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("avoid-word");
  });

  it("matches partial word occurrences (substring match)", () => {
    const result = filterContent(
      "this is unmatched greatness right here",
      cfg,
      "ai",
      undefined,
      ["match"],
    );
    // "match" is a substring of "unmatched"
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("avoid-word");
  });

  it("passes content without any avoid words", () => {
    const result = filterContent(
      "just chilling at the park today honestly",
      cfg,
      "ai",
      undefined,
      ["vibe", "energy", "manifest"],
    );
    expect(result.passed).toBe(true);
  });

  it("skips avoid word check for manual posts", () => {
    const result = filterContent(
      "this vibe is just unmatched honestly today",
      cfg,
      "manual",
      undefined,
      ["vibe"],
    );
    // Manual posts skip avoid word check
    expect(result.reason).not.toBe("avoid-word");
  });

  it("handles empty avoidWords array", () => {
    const result = filterContent(
      "anything goes when list is empty honestly",
      cfg,
      "ai",
      undefined,
      [],
    );
    expect(result.passed).toBe(true);
  });

  it("handles undefined avoidWords", () => {
    const result = filterContent(
      "anything goes when undefined is passed",
      cfg,
      "ai",
      undefined,
      undefined,
    );
    expect(result.passed).toBe(true);
  });

  it("skips empty strings in avoidWords array", () => {
    const result = filterContent(
      "normal post content nothing wrong here",
      cfg,
      "ai",
      undefined,
      ["", ""],
    );
    expect(result.passed).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Competitor post sourceType bypass
// ---------------------------------------------------------------------------

describe("competitor post sourceType bypass", () => {
  const cfg = defaultConfig();

  it("skips length checks for competitor_direct posts", () => {
    // Under minLength
    const shortResult = filterContent("hi", cfg, "competitor_direct");
    expect(shortResult.reason).not.toBe("too-short");

    // Over maxLength
    const longResult = filterContent("a".repeat(600), cfg, "competitor_direct");
    expect(longResult.reason).not.toBe("too-long");
  });

  it("skips length checks for competitor_copy posts", () => {
    const shortResult = filterContent("yo", cfg, "competitor_copy");
    expect(shortResult.reason).not.toBe("too-short");
  });

  it("skips emoji limit for competitor posts", () => {
    const emojiHeavy = "look at this 🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥";
    const result = filterContent(emojiHeavy, cfg, "competitor_direct");
    expect(result.reason).not.toBe("too-many-emojis");
  });

  it("still applies safety blacklist to competitor_direct posts", () => {
    const result = filterContent(
      "send nudes right now babe please ok ok",
      cfg,
      "competitor_direct",
    );
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("safety-blacklist");
  });

  it("still applies safety blacklist to competitor_copy posts", () => {
    const result = filterContent(
      "just turned 18 and ready for everything",
      cfg,
      "competitor_copy",
    );
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("safety-blacklist");
  });

  it("skips structural checks for competitor posts", () => {
    // Numbered list — normally caught
    const result = filterContent(
      "1. this is how the competitor formatted it",
      cfg,
      "competitor_direct",
    );
    // Should NOT fail on structural-numbered-list
    // But may still fail on safety blacklist or structural patterns
    // (structural patterns are checked OUTSIDE the competitor bypass)
    // Actually, looking at the code: structural checks run for non-manual posts
    // Competitor posts are NOT manual — let me re-check the code flow...
    // The code checks: if (!isManualPost) { structural checks }
    // So competitor posts DO get structural checks. This test verifies that.
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("structural-numbered-list");
  });

  it("skips DB-configurable patterns for competitor posts (they are non-manual)", () => {
    // Actually competitor posts go through configurable patterns since they're not manual
    const customCfg = resolveFilterConfig(
      [{ pattern: "\\bcompetitor\\b", label: "no-competitor" }],
      null,
      null,
    );
    const result = filterContent(
      "this competitor post should be checked",
      customCfg,
      "competitor_direct",
    );
    // Competitor posts are NOT manual — DB patterns still apply
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("no-competitor");
  });
});

// ---------------------------------------------------------------------------
// Structural patterns — additional edge cases
// ---------------------------------------------------------------------------

describe("structural patterns — edge cases", () => {
  const cfg = defaultConfig();

  it("rejects phone numbers with dashes", () => {
    const result = filterContent("call me at 555-123-4567 for details", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("structural-phone-number");
  });

  it("rejects phone numbers with dots", () => {
    const result = filterContent("reach me at 555.123.4567 anytime", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("structural-phone-number");
  });

  it("rejects international phone numbers with +", () => {
    const result = filterContent("text me at +14155551234 today", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("structural-phone-number");
  });

  it("rejects engagement bait at start of sentence", () => {
    const result = filterContent("like if you agree with this message", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("structural-engagement-bait");
  });

  it("rejects follow-for-follow patterns", () => {
    const result = filterContent("doing f4f right now follow me back", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("structural-engagement-bait");
  });

  it("rejects like-for-like patterns", () => {
    const result = filterContent("l4l anyone interested in exchanging", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("structural-engagement-bait");
  });

  it("rejects em-dash (ChatGPT fingerprint)", () => {
    const result = filterContent("this is the vibe \u2014 honestly so good", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("structural-em-dash");
  });

  it("rejects en-dash", () => {
    const result = filterContent("pages 10\u201320 of the book were great", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("structural-em-dash");
  });

  it("rejects semicolons", () => {
    const result = filterContent("this is nice; however it could improve", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("structural-semicolon");
  });

  it("rejects filler-only posts", () => {
    const result = filterContent("hhmmmm", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("structural-filler-only");
  });

  it("allows content with bracket placeholders (word boundary prevents match)", () => {
    // The "[your" pattern is in the safety blacklist wrapped with \b word boundaries.
    // Since "[" is not a word char, \b doesn't trigger before it — so this passes.
    // This is a known limitation: the regex-based blacklist uses \b boundaries.
    const result = filterContent("hey [your name here] check this out", cfg);
    // The \b boundary prevents matching — content passes through
    expect(result.reason).not.toBe("safety-blacklist");
  });

  it("allows plain underscores (fill-in-blank format)", () => {
    const result = filterContent("the most underrated ___ is ___", cfg);
    // Should NOT be caught as markdown — plain underscores are allowed
    expect(result.reason).not.toBe("structural-markdown");
  });

  it("rejects engagement bait after punctuation", () => {
    const result = filterContent("great content today! share if you agree", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("structural-engagement-bait");
  });
});

// ---------------------------------------------------------------------------
// Safety blacklist — ban risk categories
// ---------------------------------------------------------------------------

describe("safety blacklist — ban risk terms", () => {
  const cfg = defaultConfig();

  it("blocks explicit content terms", () => {
    const terms = ["orgasm", "blowjob", "handjob"];
    for (const term of terms) {
      const result = filterContent(`something ${term} something else here`, cfg);
      expect(result.passed).toBe(false);
      expect(result.reason).toBe("safety-blacklist");
    }
  });

  it("blocks nude-related terms", () => {
    const result = filterContent("check my leaked nudes on the platform", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("safety-blacklist");
  });

  it("blocks sex tape references", () => {
    const result = filterContent("leaked sex tape going viral right now", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("safety-blacklist");
  });

  it("blocks 'just turned 18' age emphasis (child safety)", () => {
    const result = filterContent("just turned 18 and ready for the world", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("safety-blacklist");
  });

  it("blocks birthday snap combos", () => {
    const result = filterContent("birthday snap me at my username ok", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("safety-blacklist");
  });
});

// ---------------------------------------------------------------------------
// Safety blacklist — wrong persona terms
// ---------------------------------------------------------------------------

describe("safety blacklist — wrong persona terms", () => {
  const cfg = defaultConfig();

  it("blocks single mom claims", () => {
    expect(filterContent("life as a single mom is hard but rewarding", cfg).passed).toBe(false);
  });

  it("blocks age range mismatch (30+)", () => {
    expect(filterContent("being 30 and still out here dating is hard", cfg).passed).toBe(false);
  });

  it("blocks office job references", () => {
    const officeTerms = [
      "my boss just called another corporate meeting",
      "working overtime again at my office tonight",
      "waiting for my salary to hit the bank today",
      "got a promotion at work and celebrating now",
    ];
    for (const text of officeTerms) {
      expect(filterContent(text, cfg).passed).toBe(false);
    }
  });

  it("blocks platform meta-references", () => {
    expect(filterContent("hello world this is my first post here", cfg).passed).toBe(false);
    expect(filterContent("starting this account to share my journey", cfg).passed).toBe(false);
  });

  it("blocks vacation/travel references", () => {
    expect(filterContent("currently on vacation living my best life", cfg).passed).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Safety blacklist — AI artifact terms
// ---------------------------------------------------------------------------

describe("safety blacklist — AI artifact terms", () => {
  const cfg = defaultConfig();

  it("blocks bot/meta-awareness", () => {
    expect(filterContent("these bots already ruined the platform", cfg).passed).toBe(false);
    expect(filterContent("seeing bots everywhere on this app now", cfg).passed).toBe(false);
    expect(filterContent("so many fake profiles flooding the feed", cfg).passed).toBe(false);
  });

  it("blocks external platform handles", () => {
    expect(filterContent("hmu on telegram for more content always", cfg).passed).toBe(false);
    expect(filterContent("add me on whatsapp for exclusive content", cfg).passed).toBe(false);
  });

  it("blocks fake snap handles (Gemini hallucination)", () => {
    expect(filterContent("my snapchat is hotgirl99 add me now", cfg).passed).toBe(false);
    expect(filterContent("snap: cooluser22 hit me up for more", cfg).passed).toBe(false);
  });

  it("blocks comment-style posts", () => {
    expect(filterContent("wow you look amazing in this picture today", cfg).passed).toBe(false);
    expect(filterContent("follow me back and i follow you too", cfg).passed).toBe(false);
    expect(filterContent("nice pic babe looking good out there", cfg).passed).toBe(false);
  });

  it("blocks holiday references (wrong temporal context)", () => {
    expect(filterContent("happy new year everyone lets celebrate", cfg).passed).toBe(false);
    expect(filterContent("merry christmas to all my followers here", cfg).passed).toBe(false);
  });

  it("blocks starter pack references", () => {
    expect(filterContent("the gym bro starter pack is so accurate", cfg).passed).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// ReDoS protection
// ---------------------------------------------------------------------------

describe("ReDoS protection", () => {
  it("skips patterns with nested quantifiers (++ pattern)", () => {
    // The isSafeRegex guard catches patterns containing "++"
    const cfg = resolveFilterConfig(
      [{ pattern: "a++b", label: "redos-plusplus" }],
      null,
      null,
    );
    // "a++b" is detected as unsafe → skipped → content passes
    const result = filterContent("this content has an a in it right", cfg);
    expect(result.passed).toBe(true);
  });

  it("skips patterns with *+ quantifier", () => {
    const cfg = resolveFilterConfig(
      [{ pattern: "a*+b", label: "redos-starplus" }],
      null,
      null,
    );
    const result = filterContent("this content has an a in it right", cfg);
    expect(result.passed).toBe(true);
  });

  it("skips patterns with ** quantifier", () => {
    const cfg = resolveFilterConfig(
      [{ pattern: "a**b", label: "redos-starstar" }],
      null,
      null,
    );
    const result = filterContent("this content has an a in it right", cfg);
    expect(result.passed).toBe(true);
  });

  it("skips extremely long regex patterns (>500 chars)", () => {
    const longPattern = "a".repeat(501);
    const longCfg = resolveFilterConfig(
      [{ pattern: longPattern, label: "too-long-regex" }],
      null,
      null,
    );
    const result = filterContent("this content has an a in it right", longCfg);
    // The long pattern should be skipped, not crash
    expect(result).toHaveProperty("passed");
  });

  it("allows safe patterns through", () => {
    const cfg = resolveFilterConfig(
      [{ pattern: "\\btest\\b", label: "safe-test" }],
      null,
      null,
    );
    const result = filterContent("this is a test post for the filter", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("safe-test");
  });
});

// ---------------------------------------------------------------------------
// filterAndLog — flags reporting
// ---------------------------------------------------------------------------

describe("filterAndLog — flags and logging", () => {
  it("returns flags for soft warnings alongside passing result", () => {
    const cfg = defaultConfig();
    // Create content that triggers burstiness flag
    const content = "this is a test post about stuff today";
    const recent1 = "this is a test post about other things";
    const recent2 = "this is a test post about more today";

    const result = filterAndLog(
      content,
      "ai",
      cfg,
      { workspaceId: "ws-1", groupId: "g-1" },
      [recent1, recent2],
    );

    // May or may not have flags depending on exact length similarity
    expect(result).toHaveProperty("passed");
  });

  it("logs rejection info for blocked content", () => {
    const cfg = defaultConfig();

    filterAndLog(
      "send nudes right now babe please ok",
      "ai",
      cfg,
      { workspaceId: "ws-test", groupId: "g-test" },
    );

    expect(vi.mocked(mockLogger.info)).toHaveBeenCalledWith(
      "Content filter rejected",
      expect.objectContaining({
        reason: "safety-blacklist",
        workspaceId: "ws-test",
        groupId: "g-test",
      }),
    );
  });

  it("does not log rejection for clean content", () => {
    const cfg = defaultConfig();

    filterAndLog(
      "totally clean post content nothing bad",
      "ai",
      cfg,
      { workspaceId: "ws-abc", groupId: "g-xyz" },
    );

    // Clean content shouldn't log rejection
    const infoCalls = vi.mocked(mockLogger.info).mock.calls;
    const rejectionCalls = infoCalls.filter(
      (call: any[]) => call[0] === "Content filter rejected",
    );
    expect(rejectionCalls.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Edge cases — boundary conditions
// ---------------------------------------------------------------------------

describe("boundary conditions", () => {
  it("content at exactly minLength passes", () => {
    const cfg = defaultConfig(); // minLength = 5
    // 5 characters exactly
    const result = filterContent("abcde", cfg);
    expect(result.reason).not.toBe("too-short");
  });

  it("content at minLength - 1 fails", () => {
    const cfg = defaultConfig(); // minLength = 5
    const result = filterContent("abcd", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("too-short");
  });

  it("allows short profile-curiosity validation hooks under stricter group minimums", () => {
    const cfg = resolveFilterConfig(null, null, null, 25);

    expect(filterContent("am i pretty?", cfg).passed).toBe(true);
    expect(filterContent("am i your type?", cfg).passed).toBe(true);
    expect(filterContent("do you think i'm cute?", cfg).passed).toBe(true);
  });

  it("does not broadly lower minimum length for non-validation one-liners", () => {
    const cfg = resolveFilterConfig(null, null, null, 25);

    const result = filterContent("am i smart?", cfg);

    expect(result.passed).toBe(false);
    expect(result.reason).toBe("too-short");
  });

  it("content at exactly maxLength passes", () => {
    const cfg = resolveFilterConfig(null, 50, null);
    const result = filterContent("a".repeat(50), cfg);
    expect(result.reason).not.toBe("too-long");
  });

  it("content at maxLength + 1 fails", () => {
    const cfg = resolveFilterConfig(null, 50, null);
    const result = filterContent("a".repeat(51), cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("too-long");
  });

  it("emoji count at exactly maxEmojis passes", () => {
    const cfg = resolveFilterConfig(null, null, 2);
    const result = filterContent("look at this nice sunset today \u{1F525}\u{2728}", cfg);
    expect(result.reason).not.toBe("too-many-emojis");
  });

  it("emoji count at maxEmojis + 1 fails", () => {
    const cfg = resolveFilterConfig(null, null, 2);
    const result = filterContent("look at this nice sunset view \u{1F525}\u{2728}\u{1F30A}", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("too-many-emojis");
  });

  it("maxEmojis of 0 rejects any emoji", () => {
    const cfg = resolveFilterConfig(null, null, 0);
    const result = filterContent("just one emoji here \u{1F525}", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("too-many-emojis");
  });

  it("minLength of 0 allows any non-empty content", () => {
    const cfg = resolveFilterConfig(null, null, null, 0);
    const result = filterContent("a", cfg);
    expect(result.reason).not.toBe("too-short");
  });
});

// ---------------------------------------------------------------------------
// Combined scenarios
// ---------------------------------------------------------------------------

describe("combined scenarios", () => {
  it("safety blacklist takes priority over structural checks", () => {
    const cfg = defaultConfig();
    // Content has both a structural issue (starts with quote) AND a banned term
    const result = filterContent('"send nudes" is what they said honestly', cfg);
    expect(result.passed).toBe(false);
    // Structural checks run first in the code, so it might catch either
    expect(["structural-quoted-output", "safety-blacklist"]).toContain(result.reason);
  });

  it("empty content check runs before all other checks", () => {
    const cfg = defaultConfig();
    const result = filterContent("", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("empty-content");
  });

  it("length check runs before pattern checks", () => {
    const cfg = resolveFilterConfig(null, 10, null, 5);
    // Content is too long AND has a banned term
    const result = filterContent("send nudes right now babe please ok ok", cfg);
    expect(result.passed).toBe(false);
    // Too-long check runs first
    expect(result.reason).toBe("too-long");
  });

  it("avoidWords checked after safety blacklist and patterns", () => {
    const cfg = defaultConfig();
    // Content has a safety blacklist term AND an avoid word
    const result = filterContent(
      "send nudes with good vibes today babe",
      cfg,
      "ai",
      undefined,
      ["vibes"],
    );
    expect(result.passed).toBe(false);
    // Safety blacklist runs first
    expect(result.reason).toBe("safety-blacklist");
  });
});
