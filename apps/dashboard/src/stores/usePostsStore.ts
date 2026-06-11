/**
 * usePostsStore — Zustand store for posts data.
 *
 * Persists posts data across page navigations so the posts page doesn't
 * re-fetch and show a loading skeleton every time you leave and come back.
 *
 * The usePostsData hook reads from and writes to this store.
 */

import { create } from "zustand";
import type { ThreadPost } from "@/types/index";

interface PostsState {
	/** All fetched posts (raw, before client-side filtering) */
	posts: ThreadPost[];
	/** Total post count from server (for pagination) */
	totalPosts: number;
	/** Timestamp of last successful fetch */
	lastFetchedAt: number | null;
	/** Whether initial fetch has ever completed */
	hasData: boolean;
	/** The account+page+platform key that produced the cached posts */
	cacheKey: string | null;
	/**
	 * Incremented whenever a post is created, updated, scheduled, or deleted
	 * from anywhere in the app. usePostsData subscribes to this so the posts
	 * list stays fresh regardless of which component triggered the mutation.
	 */
	mutatedAt: number;

	// Actions
	setPosts: (posts: ThreadPost[], total: number, cacheKey: string) => void;
	updatePost: (id: string, updates: Partial<ThreadPost>) => void;
	removePost: (id: string) => void;
	clear: () => void;
	/** Call after any successful post write to invalidate the posts cache. */
	markMutated: () => void;
}

export const usePostsStore = create<PostsState>((set) => ({
	posts: [],
	totalPosts: 0,
	lastFetchedAt: null,
	hasData: false,
	cacheKey: null,
	mutatedAt: 0,

	setPosts: (posts, total, cacheKey) =>
		set({
			posts,
			totalPosts: total,
			lastFetchedAt: Date.now(),
			hasData: true,
			cacheKey,
		}),

	updatePost: (id, updates) =>
		set((state) => ({
			posts: state.posts.map((p) =>
				p.id === id ? ({ ...p, ...updates } as ThreadPost) : p,
			),
		})),

	removePost: (id) =>
		set((state) => ({
			posts: state.posts.filter((p) => p.id !== id),
			totalPosts: Math.max(0, state.totalPosts - 1),
		})),

	clear: () =>
		set({
			posts: [],
			totalPosts: 0,
			lastFetchedAt: null,
			hasData: false,
			cacheKey: null,
		}),

	markMutated: () =>
		set({
			mutatedAt: Date.now(),
			hasData: false,
			cacheKey: null,
		}),
}));
