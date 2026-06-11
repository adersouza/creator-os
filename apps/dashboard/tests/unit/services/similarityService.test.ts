/**
 * Tests for services/similarityService.ts
 *
 * Pure logic tests for feature extraction, similarity calculation,
 * pattern analysis, and post finding. No mocks needed for core functions.
 */

import { describe, it, expect, vi } from "vitest";

vi.mock("@/utils/logger", () => ({
  default: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn(), log: vi.fn() },
}));

import {
  extractFeatures,
  calculateSimilarity,
  findSimilarPosts,
  analyzePatterns,
} from "@/services/similarityService";

// Helper to create a test post
function makePost(overrides: Partial<{
  id: string;
  content: string;
  views: number;
  likes: number;
  replies: number;
  reposts: number;
  shares: number;
  engagementRate: number;
  publishedAt: Date;
  mediaType: "text" | "image" | "video" | "carousel" | "reels";
  permalink: string | null;
}> = {}) {
  return {
    id: "post-1",
    content: "Hello world",
    views: 100,
    likes: 10,
    replies: 5,
    reposts: 2,
    shares: 1,
    engagementRate: 0.18,
    publishedAt: new Date("2026-04-15T10:00:00Z"),
    mediaType: "text" as const,
    permalink: null,
    ...overrides,
  };
}

describe("similarityService", () => {
  // ============================================================
  // extractFeatures
  // ============================================================
  describe("extractFeatures()", () => {
    it("extracts hashtags correctly", () => {
      const post = makePost({ content: "Check this #threads #growth #tips" });
      const features = extractFeatures(post);
      expect(features.hashtags).toEqual(["#threads", "#growth", "#tips"]);
    });

    it("detects questions", () => {
      const post = makePost({ content: "What do you think about this?" });
      const features = extractFeatures(post);
      expect(features.hasQuestion).toBe(true);
    });

    it("detects no question in declarative content", () => {
      const post = makePost({ content: "This is a statement." });
      const features = extractFeatures(post);
      expect(features.hasQuestion).toBe(false);
    });

    it("detects links", () => {
      const post = makePost({ content: "Check out https://example.com" });
      const features = extractFeatures(post);
      expect(features.hasLink).toBe(true);
    });

    it("counts emojis", () => {
      const post = makePost({ content: "Love this! \u{1F600}\u{1F389}" });
      const features = extractFeatures(post);
      expect(features.emojiCount).toBe(2);
    });

    it("calculates content length", () => {
      const post = makePost({ content: "short" });
      const features = extractFeatures(post);
      expect(features.contentLength).toBe(5);
    });

    it("calculates average word length", () => {
      const post = makePost({ content: "hi there friend" });
      const features = extractFeatures(post);
      // "hi" (2) + "there" (5) + "friend" (6) = 13 / 3 = 4.33
      expect(features.avgWordLength).toBeCloseTo(4.33, 1);
    });

    it("counts non-empty lines", () => {
      const post = makePost({ content: "line one\n\nline two\nline three" });
      const features = extractFeatures(post);
      expect(features.lineCount).toBe(3);
    });

    it("extracts posting hour and day", () => {
      const post = makePost({ publishedAt: new Date("2026-04-14T15:30:00Z") });
      const features = extractFeatures(post);
      expect(features.postingHour).toBe(post.publishedAt.getHours());
      expect(features.postingDay).toBe(post.publishedAt.getDay());
    });

    it("handles empty content", () => {
      const post = makePost({ content: "" });
      const features = extractFeatures(post);
      expect(features.hashtags).toEqual([]);
      expect(features.emojiCount).toBe(0);
      expect(features.contentLength).toBe(0);
      expect(features.avgWordLength).toBe(0);
    });
  });

  // ============================================================
  // calculateSimilarity
  // ============================================================
  describe("calculateSimilarity()", () => {
    it("gives 20 points for same media type", () => {
      const a = extractFeatures(makePost({ mediaType: "image" }));
      const b = extractFeatures(makePost({ mediaType: "image" }));
      const { score, reasons } = calculateSimilarity(a, b);
      expect(reasons).toContain("Same media type");
      expect(score).toBeGreaterThanOrEqual(20);
    });

    it("does not give media points for different types", () => {
      const a = extractFeatures(makePost({ mediaType: "text" }));
      const b = extractFeatures(makePost({ mediaType: "video" }));
      // Score should not include "Same media type"
      const { reasons } = calculateSimilarity(a, b);
      expect(reasons).not.toContain("Same media type");
    });

    it("scores content length similarity when within 30%", () => {
      const a = extractFeatures(makePost({ content: "x".repeat(100) }));
      const b = extractFeatures(makePost({ content: "x".repeat(80) }));
      const { reasons } = calculateSimilarity(a, b);
      expect(reasons).toContain("Similar content length");
    });

    it("scores hashtag overlap", () => {
      const a = extractFeatures(makePost({ content: "#growth #threads" }));
      const b = extractFeatures(makePost({ content: "#growth #tips" }));
      const { reasons } = calculateSimilarity(a, b);
      expect(reasons).toContain("1 shared hashtag");
    });

    it("scores same posting hour (10 points)", () => {
      const time = new Date("2026-04-15T14:00:00Z");
      const a = extractFeatures(makePost({ publishedAt: time }));
      const b = extractFeatures(makePost({ publishedAt: time }));
      const { reasons } = calculateSimilarity(a, b);
      expect(reasons).toContain("Posted at same hour");
    });

    it("returns max 3 reasons", () => {
      // Create posts that match on many dimensions
      const post = makePost({
        content: "Hello #test",
        mediaType: "image",
      });
      const a = extractFeatures(post);
      const { reasons } = calculateSimilarity(a, a);
      expect(reasons.length).toBeLessThanOrEqual(3);
    });

    it("returns score 0-100", () => {
      const a = extractFeatures(makePost());
      const b = extractFeatures(makePost({ content: "totally different stuff" }));
      const { score } = calculateSimilarity(a, b);
      expect(score).toBeGreaterThanOrEqual(0);
      expect(score).toBeLessThanOrEqual(100);
    });
  });

  // ============================================================
  // findSimilarPosts
  // ============================================================
  describe("findSimilarPosts()", () => {
    it("excludes the target post from results", () => {
      const target = makePost({ id: "target" });
      const all = [target, makePost({ id: "other" })];

      const results = findSimilarPosts(target, all, 0);

      expect(results.every((r) => r.id !== "target")).toBe(true);
    });

    it("only returns posts above the minimum similarity score", () => {
      const target = makePost({ id: "target", mediaType: "text", content: "hello" });
      const similar = makePost({ id: "sim", mediaType: "text", content: "hello" });
      const different = makePost({
        id: "diff",
        mediaType: "video",
        content: "x".repeat(500),
        publishedAt: new Date("2020-01-01T03:00:00Z"),
      });

      const results = findSimilarPosts(target, [similar, different], 60);

      // The identical post should score high; the different one may or may not pass
      for (const r of results) {
        expect(r.similarityScore).toBeGreaterThanOrEqual(60);
      }
    });

    it("returns at most 5 results", () => {
      const target = makePost({ id: "target" });
      const all = Array.from({ length: 20 }, (_, i) =>
        makePost({ id: `post-${i}` })
      );

      const results = findSimilarPosts(target, all, 0);
      expect(results.length).toBeLessThanOrEqual(5);
    });

    it("sorts by similarity score descending", () => {
      const target = makePost({ id: "target", mediaType: "text", content: "hello" });
      const all = [
        makePost({ id: "a", mediaType: "text", content: "hello" }),
        makePost({ id: "b", mediaType: "video", content: "different" }),
      ];

      const results = findSimilarPosts(target, all, 0);
      for (let i = 1; i < results.length; i++) {
        expect(results[i].similarityScore).toBeLessThanOrEqual(
          results[i - 1].similarityScore
        );
      }
    });

    it("returns empty array when no posts are similar enough", () => {
      const target = makePost({ id: "target", content: "unique" });
      const all = [
        makePost({
          id: "diff",
          content: "x".repeat(500),
          mediaType: "reels",
          publishedAt: new Date("2020-01-01T00:00:00Z"),
        }),
      ];

      const results = findSimilarPosts(target, all, 90);
      expect(results).toEqual([]);
    });
  });

  // ============================================================
  // analyzePatterns
  // ============================================================
  describe("analyzePatterns()", () => {
    it("returns defaults for empty post array", () => {
      const result = analyzePatterns([]);
      expect(result.commonMediaType).toBe("text");
      expect(result.avgContentLength).toBe(0);
      expect(result.commonHashtags).toEqual([]);
      expect(result.avgEngagementRate).toBe(0);
    });

    it("identifies the most common media type", () => {
      const posts = [
        makePost({ mediaType: "image" }),
        makePost({ mediaType: "image" }),
        makePost({ mediaType: "text" }),
      ];

      const result = analyzePatterns(posts);
      expect(result.commonMediaType).toBe("image");
    });

    it("calculates average content length", () => {
      const posts = [
        makePost({ content: "x".repeat(100) }),
        makePost({ content: "x".repeat(200) }),
      ];

      const result = analyzePatterns(posts);
      expect(result.avgContentLength).toBe(150);
    });

    it("finds common hashtags (>= 40% of posts)", () => {
      const posts = [
        makePost({ content: "#growth #threads" }),
        makePost({ content: "#growth #tips" }),
        makePost({ content: "#growth #analytics" }),
      ];

      const result = analyzePatterns(posts);
      // #growth appears in 3/3 = 100%
      expect(result.commonHashtags).toContain("#growth");
    });

    it("calculates question usage rate", () => {
      const posts = [
        makePost({ content: "What's up?" }),
        makePost({ content: "No question here" }),
        makePost({ content: "How are you?" }),
        makePost({ content: "Another statement" }),
      ];

      const result = analyzePatterns(posts);
      expect(result.questionUsageRate).toBe(50);
    });

    it("calculates average engagement rate", () => {
      const posts = [
        makePost({ engagementRate: 0.1 }),
        makePost({ engagementRate: 0.3 }),
      ];

      const result = analyzePatterns(posts);
      expect(result.avgEngagementRate).toBeCloseTo(0.2);
    });
  });
});
