/**
 * Batch-prefetch post reflections to avoid N individual API calls.
 * Parent list components call this once with all postIds, then
 * PostReflection components read from the cache via getReflection().
 */
import { useEffect, useRef } from "react";
import { supabase } from "@/services/supabase";

interface ReflectionEntry {
	reflected: boolean;
	metExpectations: boolean | null;
}

// Module-level cache shared across components
const cache = new Map<string, ReflectionEntry>();
const pending = new Set<string>();

/** Clear cached reflections on sign-out to prevent stale data across user sessions */
export function resetReflectionCache() {
	cache.clear();
	pending.clear();
}

export function getReflection(postId: string): ReflectionEntry | undefined {
	return cache.get(postId);
}

export function useReflectionBatch(postIds: string[]) {
	const fetched = useRef(false);

	useEffect(() => {
		if (!postIds.length || fetched.current) return;

		// Only fetch IDs we haven't cached or aren't pending
		const uncached = postIds.filter((id) => !cache.has(id) && !pending.has(id));
		if (!uncached.length) return;

		fetched.current = true;
		for (const id of uncached) pending.add(id);

		let cancelled = false;
		(async () => {
			try {
				const {
					data: { session },
				} = await supabase.auth.getSession();
				if (cancelled || !session?.access_token) return;

				// Batch in chunks of 100
				for (let i = 0; i < uncached.length; i += 100) {
					if (cancelled) break;
					const chunk = uncached.slice(i, i + 100);
					const res = await fetch(
						`/api/posts?action=reflection&postIds=${chunk.join(",")}`,
						{ headers: { Authorization: `Bearer ${session.access_token}` } },
					);
					if (cancelled) break;
					if (!res.ok) continue;
					const json = await res.json();
					const batch = json.data?.batch;
					if (batch) {
						for (const [id, entry] of Object.entries(batch)) {
							cache.set(id, entry as ReflectionEntry);
						}
					}
				}
			} catch {
				// Non-critical — individual components fall back to their own fetch
			} finally {
				for (const id of uncached) pending.delete(id);
			}
		})();
		return () => {
			cancelled = true;
		};
	}, [postIds]);
}
