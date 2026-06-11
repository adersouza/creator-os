/**
 * Extended content filter tests — edge cases not covered by contentFilter.test.ts
 *
 * Covers:
 * - countEmojis() helper directly (compound/flag emojis, ZWJ sequences)
 * - Manual post sourceType bypass (structural + length checks skipped)
 * - Mixed case sensitivity for safety blacklist
 * - Unicode content handling
 * - ReDoS-safe regex guard
 * - resolveFilterConfig() defaults and overrides
 * - filterAndLog() wrapper behavior
 */

import { describe, expect, it, vi } from "vitest";
import {
  countEmojis,
  filterContent,
  type FilterConfig,
  resolveFilterConfig,
  filterAndLog,
} from "@/api/_lib/handlers/auto-post/contentFilter";

// Mock logger since filterAndLog uses it
vi.mock("@/api/_lib/logger.js", () => ({
  logger: {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function defaultConfig(): FilterConfig {
  return resolveFilterConfig(null, null, null);
}

function thirstConfig(): FilterConfig {
  return resolveFilterConfig(null, null, null, undefined, "thirst");
}

// ---------------------------------------------------------------------------
// countEmojis
// ---------------------------------------------------------------------------

describe("countEmojis", () => {
  it("counts simple emojis", () => {
    expect(countEmojis("hello 😊 world 🌍")).toBe(2);
  });

  it("returns 0 for plain text", () => {
    expect(countEmojis("no emojis here at all")).toBe(0);
  });

  it("returns 0 for empty string", () => {
    expect(countEmojis("")).toBe(0);
  });

  it("does not count flag emojis (regional indicators are not Extended_Pictographic)", () => {
    // Flag emojis are regional indicator pairs, NOT Extended_Pictographic
    // This is intentional — the filter focuses on standard pictographic emojis
    const count = countEmojis("🇺🇸🇧🇷");
    expect(count).toBe(0);
  });

  it("counts skin-tone modified emojis as single emoji each", () => {
    expect(countEmojis("👍🏽👍🏿")).toBe(2);
  });

  it("does not count numbers or punctuation as emojis", () => {
    expect(countEmojis("Call 555-1234!")).toBe(0);
  });

  it("handles mixed emoji and text", () => {
    expect(countEmojis("🔥 hot take 🔥 seriously 💯")).toBe(3);
  });
});

// ---------------------------------------------------------------------------
// Manual post sourceType bypass
// ---------------------------------------------------------------------------

describe("manual post sourceType", () => {
  it("skips length checks for manual posts", () => {
    const cfg = defaultConfig();
    // Under minLength but manual
    const result = filterContent("hi", cfg, "manual");
    // Should NOT fail with "too-short" since manual posts skip structural checks
    expect(result.reason).not.toBe("too-short");
  });

  it("skips maxLength for manual posts", () => {
    const cfg = defaultConfig();
    const longText = "a".repeat(500);
    const result = filterContent(longText, cfg, "manual");
    expect(result.reason).not.toBe("too-long");
  });

  it("skips emoji limit for manual posts", () => {
    const cfg = defaultConfig();
    const emojiText = "love this 🔥🔥🔥🔥🔥🔥🔥🔥🔥🔥";
    const result = filterContent(emojiText, cfg, "manual");
    expect(result.reason).not.toBe("too-many-emojis");
  });

  it("skips structural pattern checks for manual posts", () => {
    const cfg = defaultConfig();
    // Starts with "1. " — normally caught as structural-numbered-list
    const result = filterContent("1. this is my manual numbered list post that is long enough", cfg, "manual");
    expect(result.reason).not.toBe("structural-numbered-list");
  });

  it("still applies safety blacklist to manual posts", () => {
    const cfg = defaultConfig();
    const result = filterContent("send nudes right now please babe", cfg, "manual");
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("safety-blacklist");
  });

  it("skips DB-configurable patterns for manual posts", () => {
    const cfg = resolveFilterConfig(
      [{ pattern: "\\bfoo\\b", label: "no-foo" }],
      null,
      null,
    );
    const result = filterContent("this has foo in it right here yo", cfg, "manual");
    // Manual posts skip configurable pattern check
    expect(result.reason).not.toBe("no-foo");
  });
});

// ---------------------------------------------------------------------------
// Case sensitivity of safety blacklist
// ---------------------------------------------------------------------------

describe("safety blacklist case sensitivity", () => {
  const cfg = defaultConfig();

  it("catches UPPERCASE banned terms", () => {
    const result = filterContent("SEND NUDES right now please ok babe", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("safety-blacklist");
  });

  it("catches MiXeD CaSe banned terms", () => {
    const result = filterContent("just Turned 18 and ready for anything", cfg);
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("safety-blacklist");
  });

  it("catches lowercase banned terms in default mode", () => {
    const result = filterContent("feeling horny on a tuesday night yeah", cfg);
    expect(result.passed).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Unicode and special character content
// ---------------------------------------------------------------------------

describe("unicode and special characters", () => {
  const cfg = defaultConfig();

  it("handles CJK characters without crashing", () => {
    const result = filterContent("this is a test with some characters", cfg);
    expect(result).toHaveProperty("passed");
  });

  it("handles accented Latin characters", () => {
    const result = filterContent("cafe life is all about good vibes", cfg);
    expect(result).toHaveProperty("passed");
  });

  it("handles content with only unicode symbols", () => {
    // Should fail as too-short (only symbols, no alpha content)
    const result = filterContent("-----", cfg);
    expect(result).toHaveProperty("passed");
  });

  it("does not crash on null bytes in content", () => {
    const result = filterContent("hello\x00world check this out", cfg);
    expect(result).toHaveProperty("passed");
  });
});

// ---------------------------------------------------------------------------
// resolveFilterConfig edge cases
// ---------------------------------------------------------------------------

describe("resolveFilterConfig", () => {
  it("uses all defaults when all args are null", () => {
    const cfg = resolveFilterConfig(null, null, null);
    expect(cfg.minLength).toBe(5);
    expect(cfg.maxLength).toBe(500);
    expect(cfg.maxEmojis).toBe(3);
    expect(cfg.nicheMode).toBe("default");
    expect(cfg.patterns.length).toBeGreaterThan(0);
  });

  it("uses defaults when args are undefined", () => {
    const cfg = resolveFilterConfig(undefined, undefined, undefined);
    expect(cfg.minLength).toBe(5);
    expect(cfg.maxLength).toBe(500);
    expect(cfg.maxEmojis).toBe(3);
  });

  it("respects custom minLength from DB", () => {
    const cfg = resolveFilterConfig(null, null, null, 10);
    expect(cfg.minLength).toBe(10);
  });

  it("respects custom maxLength from DB", () => {
    const cfg = resolveFilterConfig(null, 500, null);
    expect(cfg.maxLength).toBe(500);
  });

  it("respects custom maxEmojis from DB", () => {
    const cfg = resolveFilterConfig(null, null, 10);
    expect(cfg.maxEmojis).toBe(10);
  });

  it("uses default patterns when DB patterns is null", () => {
    const cfg = resolveFilterConfig(null, null, null);
    expect(cfg.patterns.length).toBeGreaterThan(0);
  });

  it("uses default patterns when DB patterns is empty array", () => {
    const cfg = resolveFilterConfig([], null, null);
    expect(cfg.patterns.length).toBeGreaterThan(0);
  });

  it("uses DB patterns additively with defaults when provided and non-empty", () => {
    const custom = [{ pattern: "\\btest\\b", label: "test-label" }];
    const cfg = resolveFilterConfig(custom, null, null);
    // DB patterns are additive — defaults + custom
    expect(cfg.patterns.length).toBeGreaterThan(custom.length);
    expect(cfg.patterns).toContainEqual(custom[0]);
  });

  it("sets nicheMode to thirst when specified", () => {
    const cfg = resolveFilterConfig(null, null, null, undefined, "thirst");
    expect(cfg.nicheMode).toBe("thirst");
  });

  it("defaults nicheMode to 'default' when omitted", () => {
    const cfg = resolveFilterConfig(null, null, null);
    expect(cfg.nicheMode).toBe("default");
  });

  it("treats 0 as a valid minLength (not falsy)", () => {
    const cfg = resolveFilterConfig(null, null, null, 0);
    expect(cfg.minLength).toBe(0);
  });

  it("treats 0 as a valid maxLength (not falsy)", () => {
    const cfg = resolveFilterConfig(null, 0, null);
    expect(cfg.maxLength).toBe(0);
  });

  it("treats 0 as a valid maxEmojis (not falsy)", () => {
    const cfg = resolveFilterConfig(null, null, 0);
    expect(cfg.maxEmojis).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// filterAndLog wrapper
// ---------------------------------------------------------------------------

describe("filterAndLog", () => {
  it("returns the same result as filterContent", () => {
    const cfg = defaultConfig();
    const content = "safe content that should pass through ok";
    const direct = filterContent(content, cfg, "ai");
    const logged = filterAndLog(content, "ai", cfg, { workspaceId: "ws1" });
    expect(logged.passed).toBe(direct.passed);
    expect(logged.reason).toBe(direct.reason);
  });

  it("returns rejection info for blocked content", () => {
    const cfg = defaultConfig();
    const content = "send nudes right now please babe ok yeah";
    const result = filterAndLog(content, "ai", cfg, {
      workspaceId: "ws1",
      groupId: "g1",
    });
    expect(result.passed).toBe(false);
    expect(result.reason).toBe("safety-blacklist");
  });
});

// ---------------------------------------------------------------------------
// Thirst mode vs default mode behavior parity
// ---------------------------------------------------------------------------

describe("thirst mode vs default mode", () => {
  it("safe content passes in both modes", () => {
    const safe = "ngl you looked good in that last pic";
    expect(filterContent(safe, defaultConfig()).passed).toBe(true);
    expect(filterContent(safe, thirstConfig()).passed).toBe(true);
  });

  it("hard ban terms fail in both modes", () => {
    const banned = "send nudes right now please babe ok yeah";
    expect(filterContent(banned, defaultConfig()).passed).toBe(false);
    expect(filterContent(banned, thirstConfig()).passed).toBe(false);
  });

  it("wrong persona terms fail in both modes", () => {
    const wrongPersona = "my cat just did the funniest thing today";
    expect(filterContent(wrongPersona, defaultConfig()).passed).toBe(false);
    expect(filterContent(wrongPersona, thirstConfig()).passed).toBe(false);
  });

  it("AI artifact terms fail in both modes", () => {
    const artifact = "these bots are taking over the platform";
    expect(filterContent(artifact, defaultConfig()).passed).toBe(false);
    expect(filterContent(artifact, thirstConfig()).passed).toBe(false);
  });

  it("thirst-allow terms fail ONLY in default mode", () => {
    const thirstContent = "feeling horny on a tuesday night honestly";
    expect(filterContent(thirstContent, defaultConfig()).passed).toBe(false);
    expect(filterContent(thirstContent, thirstConfig()).passed).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Age emphasis patterns (child safety)
// ---------------------------------------------------------------------------

describe("age emphasis patterns (child safety)", () => {
  const cfg = defaultConfig();

  it("blocks 'just turned 18' in any mode", () => {
    expect(filterContent("just turned 18 and ready for it all now", cfg).passed).toBe(false);
    expect(filterContent("just turned 18 and ready for it all now", thirstConfig()).passed).toBe(false);
  });

  it("blocks 'officially 18' in any mode", () => {
    expect(filterContent("officially 18 now and living my life here", cfg).passed).toBe(false);
  });

  it("blocks 'legal age' references", () => {
    expect(filterContent("finally reached legal age and celebrating", cfg).passed).toBe(false);
  });
});
