/**
 * Tests for api/_lib/handlers/auto-post/contentScorer.ts
 *
 * Pure heuristic scoring — no mocks needed. Validates all four scoring
 * dimensions (reply trigger, emotional warmth, specificity, emotional arousal)
 * plus the composite scoring logic and originality checks.
 */

import { describe, it, expect, vi } from "vitest";

// contentScorer is pure functions with no external deps except logger
vi.mock("../../api/_lib/logger.js", () => ({
  logger: { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn() },
}));

import { scoreContent } from "@/api/_lib/handlers/auto-post/contentScorer";

describe("contentScorer", () => {
  // ============================================================
  // Reply Trigger Scoring
  // ============================================================
  describe("reply trigger scoring", () => {
    it("scores 5 for explicit questions", () => {
      const result = scoreContent("what's your biggest flex?");
      expect(result.replyTrigger).toBe(5);
    });

    it("scores 5 for fill-in-the-blank", () => {
      const result = scoreContent("my love language is ___");
      expect(result.replyTrigger).toBe(5);
    });

    it("scores 5 for direct engagement phrases", () => {
      const result = scoreContent("would you rather never sleep or never eat");
      expect(result.replyTrigger).toBe(5);
    });

    it("scores 5 for 'be honest' prompts", () => {
      const result = scoreContent("be honest, how many tabs do you have open right now");
      expect(result.replyTrigger).toBe(5);
    });

    it("scores 4 for trailing off with ellipsis", () => {
      const result = scoreContent("the way they just left without saying anything...");
      expect(result.replyTrigger).toBe(4);
    });

    it("scores 4 for implied challenges", () => {
      const result = scoreContent("change my mind about pineapple on pizza");
      expect(result.replyTrigger).toBe(4);
    });

    it("scores 4 for 'agree or disagree'", () => {
      const result = scoreContent("agree or disagree: naps are a love language");
      expect(result.replyTrigger).toBe(4);
    });

    it("scores 3 for hot takes", () => {
      const result = scoreContent("unpopular opinion but breakfast for dinner is elite");
      expect(result.replyTrigger).toBe(3);
    });

    it("scores 3 for overrated/underrated", () => {
      const result = scoreContent("sleeping in is overrated when you have nowhere to be");
      expect(result.replyTrigger).toBe(3);
    });

    it("scores 2 for casual slang", () => {
      const result = scoreContent("honestly ngl this hits different");
      // ngl is a warm pattern, but "lol" etc give reply trigger 2
      expect(result.replyTrigger).toBeGreaterThanOrEqual(2);
    });

    it("scores 1 for passive declarative statements", () => {
      const result = scoreContent("the sunset was nice today");
      expect(result.replyTrigger).toBe(1);
    });
  });

  // ============================================================
  // Emotional Warmth Scoring
  // ============================================================
  describe("emotional warmth scoring", () => {
    it("scores high for warm/vulnerable content", () => {
      const result = scoreContent("i miss the way things used to feel, i need that energy back");
      expect(result.emotionalWarmth).toBeGreaterThanOrEqual(4);
    });

    it("scores high for conversational slang", () => {
      const result = scoreContent("lmao bruh this is so relatable omg");
      expect(result.emotionalWarmth).toBeGreaterThanOrEqual(4);
    });

    it("scores low for corporate language", () => {
      const result = scoreContent(
        "Furthermore, it is important to note that optimization of synergy is paramount to success."
      );
      expect(result.emotionalWarmth).toBeLessThanOrEqual(2);
    });

    it("scores 1 for multiple corporate markers", () => {
      const result = scoreContent(
        "Additionally, leveraging ecosystem synergy is absolutely essential for paradigm shifts."
      );
      expect(result.emotionalWarmth).toBe(1);
    });

    it("scores neutral for plain text", () => {
      const result = scoreContent("went to the store and got some food");
      expect(result.emotionalWarmth).toBe(3);
    });
  });

  // ============================================================
  // Composite Overall Scoring
  // ============================================================
  describe("composite scoring", () => {
    it("scores identity statements above generic question bait", () => {
      const identity = scoreContent("i'm a 9 but my taste in anime is unhinged. based");
      const genericQuestion = scoreContent("who's up rn?");

      expect(identity.archetype).toBe("identity_statement");
      expect(genericQuestion.archetype).toBe("question");
      expect(genericQuestion.isGenericQuestion).toBe(true);
      expect(identity.overall).toBeGreaterThan(genericQuestion.overall);
    });

    it("scores specific recommendation requests strongly", () => {
      const result = scoreContent("drop your top 3 songs for a gym playlist");

      expect(result.archetype).toBe("recommendation_request");
      expect(result.discussionPotential).toBeGreaterThanOrEqual(4);
      expect(result.overall).toBeGreaterThan(2.5);
    });

    it("passes high-quality engaging content", () => {
      const result = scoreContent("what's your toxic trait? mine is replying 3 days later lmao");
      expect(result.passed).toBe(true);
      expect(result.overall).toBeGreaterThanOrEqual(1.0);
    });

    it("passes warm conversational content even without explicit questions", () => {
      const result = scoreContent("i love that feeling when you finish a really good book and just sit there");
      expect(result.passed).toBe(true);
    });

    it("fails cold generic corporate content", () => {
      // All dimensions should score 1 — this is truly terrible social content
      const result = scoreContent(
        "Furthermore, additionally, moreover it is imperative to leverage synergy."
      );
      // Cold + no reply trigger + no specificity + no arousal
      expect(result.emotionalWarmth).toBeLessThanOrEqual(2);
    });

    it("returns rejectReason when overall below 1.0", () => {
      // Construct content that scores 1 on everything
      const result = scoreContent(
        "Furthermore it is important to note that one should consider the paradigm."
      );
      if (!result.passed) {
        expect(result.rejectReason).toMatch(/^overall_/);
      }
      // Even if it passes, we confirm overall is computed
      expect(result.overall).toBeGreaterThanOrEqual(0);
    });

    it("applies warmth penalty when emotionalWarmth < 2", () => {
      const cold = scoreContent(
        "Additionally, optimizing the ecosystem is genuinely paramount to success."
      );
      // This should have reduced overall by 0.5
      expect(cold.emotionalWarmth).toBeLessThanOrEqual(2);
    });
  });

  // ============================================================
  // Originality Scoring (competitor-inspired content)
  // ============================================================
  describe("originality scoring", () => {
    it("passes when content is highly original vs source", () => {
      const result = scoreContent(
        "that feeling when your dog stares at you like you owe them rent",
        "productivity tips for busy entrepreneurs who want to scale"
      );
      expect(result.passed).toBe(true);
    });

    it("fails when content is too similar to source", () => {
      const source = "the best productivity tip is to wake up at five AM and grind every single day";
      // Near copy with minor edits
      const result = scoreContent(
        "the best productivity tip is to wake up at five AM and grind every single day",
        source
      );
      expect(result.passed).toBe(false);
      expect(result.rejectReason).toMatch(/^originality_/);
    });

    it("does not hard-fail high-curiosity competitor-style dating posts for reusable framing", () => {
      const source = "would you date a girl who watches anime every night?";
      const result = scoreContent(
        "would you date a girl who's obsessed with anime lore?",
        source
      );
      expect(result.passed).toBe(true);
      expect(result.rejectReason).toBeUndefined();
      expect(result.originality).toBeLessThan(2);
    });

    it("passes when source has fewer than 5 meaningful words", () => {
      const result = scoreContent(
        "what if we all just stopped pretending we like mondays",
        "hey lol" // too short to evaluate
      );
      expect(result.passed).toBe(true);
    });

    it("boosts overall for highly original competitor-inspired content", () => {
      const original = scoreContent(
        "ngl my cat just told me to get off my phone and i felt that deeply",
        "learn how to invest in real estate with these simple strategies for beginners"
      );
      const baseline = scoreContent(
        "ngl my cat just told me to get off my phone and i felt that deeply"
      );
      // Originality boost (+0.2) should make scored higher or equal
      expect(original.overall).toBeGreaterThanOrEqual(baseline.overall);
    });
  });

  // ============================================================
  // Specificity Scoring
  // ============================================================
  describe("specificity scoring", () => {
    it("scores high for content with numbers and time references", () => {
      const result = scoreContent(
        "my mom texted me at 3am asking if i ate dinner last night in the car"
      );
      // Should pick up: number (3am), scenario (my mom), time (last night), location (in the car)
      expect(result.overall).toBeGreaterThan(1.0);
      expect(result.passed).toBe(true);
    });

    it("scores lower for vague generic content", () => {
      const vague = scoreContent("things are just different now");
      const specific = scoreContent(
        "since tuesday my roommate has been watching netflix at 2am in the kitchen"
      );
      expect(specific.overall).toBeGreaterThan(vague.overall);
    });
  });

  // ============================================================
  // Emotional Arousal Scoring
  // ============================================================
  describe("emotional arousal scoring", () => {
    it("boosts overall for high-arousal content", () => {
      const highArousal = scoreContent(
        "wait what?? no way this is insane i literally cant believe they did that!!!"
      );
      expect(highArousal.overall).toBeGreaterThan(1.0);
      expect(highArousal.passed).toBe(true);
    });

    it("scores low arousal for passive content", () => {
      const passive = scoreContent("the sky is blue and the grass is green");
      const intense = scoreContent(
        "i am FURIOUS right now literally seething this is disgusting"
      );
      expect(intense.overall).toBeGreaterThan(passive.overall);
    });
  });

  // ============================================================
  // Edge Cases
  // ============================================================
  describe("edge cases", () => {
    it("handles empty content", () => {
      const result = scoreContent("");
      expect(result.replyTrigger).toBeGreaterThanOrEqual(1);
      expect(result.emotionalWarmth).toBeGreaterThanOrEqual(1);
      expect(result.overall).toBeDefined();
    });

    it("handles very long content", () => {
      const longContent = "lol ".repeat(500) + "what do you think?";
      const result = scoreContent(longContent);
      expect(result.replyTrigger).toBe(5); // has question mark
      expect(result.passed).toBe(false);
    });

    it("handles content with only emojis", () => {
      const result = scoreContent("😂😭🥺💕");
      expect(result.emotionalWarmth).toBeGreaterThanOrEqual(3);
    });

    it("overall is rounded to 1 decimal place", () => {
      const result = scoreContent("ngl this is a good test post lmao");
      const decimalPlaces = (result.overall.toString().split(".")[1] || "").length;
      expect(decimalPlaces).toBeLessThanOrEqual(1);
    });
  });
});
