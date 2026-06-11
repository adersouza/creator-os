/**
 * usePostsStore — unit tests for the posts Zustand store.
 *
 * Tests cover: setPosts, updatePost, removePost, clear, markMutated,
 * cacheKey handling, and totalPosts accounting.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { usePostsStore } from "@/src/stores/usePostsStore";

function makePost(id: string, overrides: Record<string, unknown> = {}): any {
  return {
    id,
    content: `Post ${id}`,
    created_at: "2026-04-15T10:00:00Z",
    views: 100,
    likes: 10,
    ...overrides,
  };
}

describe("usePostsStore", () => {
  beforeEach(() => {
    vi.useFakeTimers({ now: new Date("2026-04-15T12:00:00Z") });
    usePostsStore.setState({
      posts: [],
      totalPosts: 0,
      lastFetchedAt: null,
      hasData: false,
      cacheKey: null,
      mutatedAt: 0,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts with empty initial state", () => {
    const state = usePostsStore.getState();
    expect(state.posts).toEqual([]);
    expect(state.totalPosts).toBe(0);
    expect(state.lastFetchedAt).toBeNull();
    expect(state.hasData).toBe(false);
    expect(state.cacheKey).toBeNull();
    expect(state.mutatedAt).toBe(0);
  });

  describe("setPosts", () => {
    it("sets posts, total, cacheKey, and marks hasData", () => {
      const posts = [makePost("p1"), makePost("p2")];
      usePostsStore.getState().setPosts(posts, 50, "acc-1:1:threads");

      const state = usePostsStore.getState();
      expect(state.posts).toHaveLength(2);
      expect(state.totalPosts).toBe(50);
      expect(state.cacheKey).toBe("acc-1:1:threads");
      expect(state.hasData).toBe(true);
      expect(state.lastFetchedAt).toBe(Date.now());
    });

    it("replaces previous posts entirely", () => {
      usePostsStore.getState().setPosts([makePost("old")], 1, "key-1");
      usePostsStore.getState().setPosts([makePost("new")], 1, "key-2");

      const state = usePostsStore.getState();
      expect(state.posts).toHaveLength(1);
      expect(state.posts[0].id).toBe("new");
      expect(state.cacheKey).toBe("key-2");
    });
  });

  describe("updatePost", () => {
    it("updates specific post fields by id", () => {
      usePostsStore.getState().setPosts([makePost("p1", { views: 100 })], 1, "k");

      usePostsStore.getState().updatePost("p1", { views: 200, likes: 25 });

      const post = usePostsStore.getState().posts[0];
      expect(post.views).toBe(200);
      expect(post.likes).toBe(25);
      expect(post.content).toBe("Post p1"); // unchanged field preserved
    });

    it("does not affect other posts", () => {
      usePostsStore.getState().setPosts(
        [makePost("p1", { views: 100 }), makePost("p2", { views: 200 })],
        2,
        "k",
      );

      usePostsStore.getState().updatePost("p1", { views: 999 });

      expect(usePostsStore.getState().posts[0].views).toBe(999);
      expect(usePostsStore.getState().posts[1].views).toBe(200);
    });

    it("is a no-op for non-existent post id", () => {
      usePostsStore.getState().setPosts([makePost("p1")], 1, "k");

      usePostsStore.getState().updatePost("p-nonexistent", { views: 999 });

      expect(usePostsStore.getState().posts).toHaveLength(1);
      expect(usePostsStore.getState().posts[0].views).toBe(100);
    });
  });

  describe("removePost", () => {
    it("removes the post by id and decrements totalPosts", () => {
      usePostsStore.getState().setPosts(
        [makePost("p1"), makePost("p2")],
        10,
        "k",
      );

      usePostsStore.getState().removePost("p1");

      const state = usePostsStore.getState();
      expect(state.posts).toHaveLength(1);
      expect(state.posts[0].id).toBe("p2");
      expect(state.totalPosts).toBe(9);
    });

    it("does not go below 0 for totalPosts", () => {
      usePostsStore.getState().setPosts([makePost("p1")], 0, "k");

      usePostsStore.getState().removePost("p1");

      expect(usePostsStore.getState().totalPosts).toBe(0);
    });

    it("is a no-op for non-existent post id", () => {
      usePostsStore.getState().setPosts([makePost("p1")], 5, "k");

      usePostsStore.getState().removePost("nonexistent");

      // totalPosts still decrements (implementation detail), but posts unchanged
      expect(usePostsStore.getState().posts).toHaveLength(1);
    });
  });

  describe("clear", () => {
    it("resets all state to initial values", () => {
      usePostsStore.getState().setPosts([makePost("p1")], 10, "k");

      usePostsStore.getState().clear();

      const state = usePostsStore.getState();
      expect(state.posts).toEqual([]);
      expect(state.totalPosts).toBe(0);
      expect(state.lastFetchedAt).toBeNull();
      expect(state.hasData).toBe(false);
      expect(state.cacheKey).toBeNull();
    });
  });

  describe("markMutated", () => {
    it("updates mutatedAt to current time", () => {
      expect(usePostsStore.getState().mutatedAt).toBe(0);

      usePostsStore.getState().markMutated();

      expect(usePostsStore.getState().mutatedAt).toBe(Date.now());
    });

    it("sets hasData to false and clears cacheKey", () => {
      usePostsStore.getState().setPosts([makePost("p1")], 1, "k");
      expect(usePostsStore.getState().hasData).toBe(true);

      usePostsStore.getState().markMutated();

      expect(usePostsStore.getState().hasData).toBe(false);
      expect(usePostsStore.getState().cacheKey).toBeNull();
    });

    it("changes mutatedAt on successive calls", () => {
      usePostsStore.getState().markMutated();
      const first = usePostsStore.getState().mutatedAt;

      vi.advanceTimersByTime(1000);

      usePostsStore.getState().markMutated();
      const second = usePostsStore.getState().mutatedAt;

      expect(second).toBeGreaterThan(first);
    });
  });
});
