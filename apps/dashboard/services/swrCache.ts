// biome-ignore-all lint/style/noNonNullAssertion: Existing strict-index and invariant assertions predate this rule promotion; new files are checked at error level.
/**
 * SWR (Stale-While-Revalidate) Cache
 *
 * Pro-level caching pattern used by Vercel/Next.js, TanStack Query, etc.
 *
 * 1. Return stale data INSTANTLY from sessionStorage (0ms perceived load)
 * 2. Revalidate in the background
 * 3. Swap in fresh data when ready (no loading spinner)
 *
 * Also supports prefetching on hover and auth-time warming.
 */

import logger from "@/utils/logger";

// biome-ignore lint/suspicious/noExplicitAny: generic cache entry requires any as default type
interface SWREntry<T = any> {
	data: T;
	timestamp: number;
	key: string;
}

// How long data is considered "fresh" (skip background revalidation)
const FRESH_MS = 30_000; // 30s — if data is <30s old, don't even revalidate
// How long stale data is still usable (show instantly + revalidate behind)
const STALE_MS = 10 * 60_000; // 10 min — after this, must await fresh fetch
// Max entries in sessionStorage to prevent bloat
const MAX_ENTRIES = 50;

class SWRCache {
	private memCache = new Map<string, SWREntry>();
	// biome-ignore lint/suspicious/noExplicitAny: inflight promises carry unknown data types
	private inflight = new Map<string, Promise<any>>();
	// biome-ignore lint/suspicious/noExplicitAny: listeners accept unknown data types
	private listeners = new Map<string, Set<(data: any) => void>>();

	constructor() {
		this.hydrateFromStorage();
	}

	/** Hydrate memory cache from sessionStorage on startup */
	private hydrateFromStorage() {
		try {
			const keys = Object.keys(sessionStorage).filter((k) =>
				k.startsWith("swr:"),
			);
			for (const storageKey of keys) {
				const raw = sessionStorage.getItem(storageKey);
				if (!raw) continue;
				const entry: SWREntry = JSON.parse(raw);
				const age = Date.now() - entry.timestamp;
				if (age < STALE_MS) {
					this.memCache.set(entry.key, entry);
				} else {
					sessionStorage.removeItem(storageKey);
				}
			}
		} catch (e) {
			logger.debug("[SWRCache] sessionStorage hydration failed:", e);
		}
	}

	/** Persist entry to sessionStorage */
	private persist(key: string, entry: SWREntry) {
		try {
			// Evict oldest if at capacity
			const swrKeys = Object.keys(sessionStorage).filter((k) =>
				k.startsWith("swr:"),
			);
			if (swrKeys.length >= MAX_ENTRIES) {
				// Sort by timestamp and evict oldest quarter
				const entries = swrKeys
					.map((sk) => {
						try {
							const e = JSON.parse(sessionStorage.getItem(sk) || "{}");
							return { key: sk, ts: e.timestamp || 0 };
						} catch {
							return { key: sk, ts: 0 };
						}
					})
					.sort((a, b) => a.ts - b.ts);
				const evictCount = Math.max(1, Math.floor(entries.length / 4));
				for (let i = 0; i < evictCount; i++) {
					sessionStorage.removeItem(entries[i]!.key);
				}
			}
			sessionStorage.setItem(`swr:${key}`, JSON.stringify(entry));
		} catch (_e) {
			// Storage still full after eviction — clear all SWR entries
			try {
				for (const k of Object.keys(sessionStorage)) {
					if (k.startsWith("swr:")) sessionStorage.removeItem(k);
				}
				sessionStorage.setItem(`swr:${key}`, JSON.stringify(entry));
			} catch {
				/* truly full — give up silently */
			}
		}
	}

	/**
	 * Core SWR fetch.
	 *
	 * @param key - Cache key
	 * @param fetcher - Async function to get fresh data
	 * @param onUpdate - Called when fresh data arrives (for React setState)
	 * @returns Stale data immediately OR awaits fresh data
	 */
	async get<T>(
		key: string,
		fetcher: () => Promise<T>,
		onUpdate?: (data: T) => void,
	): Promise<T> {
		const cached = this.memCache.get(key);
		const now = Date.now();

		if (cached) {
			const age = now - cached.timestamp;

			// Fresh — return immediately, no revalidation
			if (age < FRESH_MS) {
				return cached.data as T;
			}

			// Stale but usable — return immediately + revalidate background
			if (age < STALE_MS) {
				this.revalidate(key, fetcher, onUpdate);
				return cached.data as T;
			}
		}

		// No cache or expired — must await fresh data
		return this.fetchAndStore(key, fetcher, onUpdate);
	}

	/** Revalidate in background, deduplicating concurrent calls */
	private revalidate<T>(
		key: string,
		fetcher: () => Promise<T>,
		onUpdate?: (data: T) => void,
	) {
		// Deduplicate: if already revalidating this key, reuse the existing promise
		const existing = this.inflight.get(key);
		if (existing) return existing;

		const promise = fetcher()
			.then((data) => {
				this.store(key, data);
				onUpdate?.(data);
				this.notifyListeners(key, data);
				return data;
			})
			.catch((err) => {
				logger.warn(`[SWR] Background revalidation failed for "${key}":`, err);
			})
			.finally(() => {
				this.inflight.delete(key);
			});

		this.inflight.set(key, promise);
		return promise;
	}

	/** Fetch, store, and return */
	private async fetchAndStore<T>(
		key: string,
		fetcher: () => Promise<T>,
		onUpdate?: (data: T) => void,
	): Promise<T> {
		// Deduplicate concurrent fetches for same key
		if (this.inflight.has(key)) {
			return this.inflight.get(key) as Promise<T>;
		}

		const promise = fetcher()
			.then((data) => {
				this.store(key, data);
				onUpdate?.(data);
				return data;
			})
			.finally(() => {
				this.inflight.delete(key);
			});

		this.inflight.set(key, promise);
		return promise;
	}

	/** Store in both memory and sessionStorage */
	store<T>(key: string, data: T) {
		const entry: SWREntry = { data, timestamp: Date.now(), key };
		this.memCache.set(key, entry);
		this.persist(key, entry);
	}

	/** Subscribe to updates for a key (for React components) */
	// biome-ignore lint/suspicious/noExplicitAny: listener accepts unknown cached data
	subscribe(key: string, listener: (data: any) => void): () => void {
		if (!this.listeners.has(key)) this.listeners.set(key, new Set());
		this.listeners.get(key)?.add(listener);
		return () => {
			this.listeners.get(key)?.delete(listener);
		};
	}

	// biome-ignore lint/suspicious/noExplicitAny: notification data type is unknown at cache level
	private notifyListeners(key: string, data: any) {
		this.listeners.get(key)?.forEach((fn) => {
			fn(data);
		});
	}

	/** Prefetch without blocking — fire and forget */
	prefetch<T>(key: string, fetcher: () => Promise<T>) {
		const cached = this.memCache.get(key);
		if (cached && Date.now() - cached.timestamp < FRESH_MS) return; // already fresh
		this.revalidate(key, fetcher);
	}

	/** Invalidate a key (force next get() to fetch fresh) */
	invalidate(key: string) {
		this.memCache.delete(key);
		try {
			sessionStorage.removeItem(`swr:${key}`);
		} catch {
			/* */
		}
	}

	/** Invalidate keys matching a pattern */
	invalidatePattern(pattern: string) {
		const regex = new RegExp(pattern);
		for (const key of this.memCache.keys()) {
			if (regex.test(key)) {
				this.memCache.delete(key);
				try {
					sessionStorage.removeItem(`swr:${key}`);
				} catch {
					/* */
				}
			}
		}
	}

	/** Check if key has any data (stale or fresh) */
	has(key: string): boolean {
		return this.memCache.has(key);
	}

	/** Peek at cached data without triggering revalidation */
	peek<T>(key: string): T | null {
		return (this.memCache.get(key)?.data as T) ?? null;
	}
}

export const swrCache = new SWRCache();

// Key builders
export const SWR_KEYS = {
	accounts: (platform: string) => `accounts:${platform}`,
	analytics: (accountId: string, days: number, platform: string) =>
		`analytics:${accountId}:${days}:${platform}`,
	posts: (accountId: string, platform: string) =>
		`posts:${accountId}:${platform}`,
	stats: (accountId: string, days: number) => `stats:${accountId}:${days}`,
	dashboardStats: (accountId: string, days: number) =>
		`dashboard-stats:${accountId}:${days}`,
	calendar: (accountId: string, platform: string) =>
		`calendar:${accountId}:${platform}`,
	media: (workspaceId: string, folder?: string) =>
		`media:${workspaceId}:${folder ?? "root"}`,
	groups: (workspaceId: string) => `groups:${workspaceId}`,
};
