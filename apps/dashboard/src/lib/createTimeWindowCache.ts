/**
 * createTimeWindowCache — generic time-windowed key-value cache factory.
 *
 * Extracted from useDashboardStore (1-minute TTL) and useAnalyticsCacheStore
 * (30-minute TTL) which share identical get/set/clear logic differing only
 * in default max age.
 *
 * Usage:
 *   const cache = createTimeWindowCache<MyData>(60_000);
 *   cache.set("key", data);
 *   const hit = cache.get("key"); // null if expired
 *   const raw = cache.peek("key"); // ignores TTL
 */

interface CacheEntry<T> {
	data: T;
	fetchedAt: number;
}

export interface TimeWindowCache<T> {
	/** Get a cached value. Returns null if missing or expired. */
	get: (key: string, maxAge?: number) => T | null;
	/** Store a value with the current timestamp. */
	set: (key: string, data: T) => void;
	/** Clear all entries. */
	clear: () => void;
	/** Get a value ignoring TTL (returns null only if missing). */
	peek: (key: string) => T | null;
	/** Delete entries matching a key prefix. */
	clearByPrefix: (prefix: string) => void;
	/** Get the raw entries map (for store serialization). */
	getEntries: () => Record<string, CacheEntry<T>>;
	/** Replace all entries (for store hydration). */
	setEntries: (entries: Record<string, CacheEntry<T>>) => void;
}

export function createTimeWindowCache<T = unknown>(
	defaultMaxAge = 60_000,
): TimeWindowCache<T> {
	let entries: Record<string, CacheEntry<T>> = {};

	return {
		get(key: string, maxAge = defaultMaxAge): T | null {
			const entry = entries[key];
			if (!entry) return null;
			if (Date.now() - entry.fetchedAt > maxAge) return null;
			return entry.data;
		},

		set(key: string, data: T): void {
			entries = { ...entries, [key]: { data, fetchedAt: Date.now() } };
		},

		clear(): void {
			entries = {};
		},

		peek(key: string): T | null {
			return entries[key]?.data ?? null;
		},

		clearByPrefix(prefix: string): void {
			const filtered: Record<string, CacheEntry<T>> = {};
			for (const [k, v] of Object.entries(entries)) {
				if (!k.startsWith(prefix)) filtered[k] = v;
			}
			entries = filtered;
		},

		getEntries(): Record<string, CacheEntry<T>> {
			return entries;
		},

		setEntries(newEntries: Record<string, CacheEntry<T>>): void {
			entries = newEntries;
		},
	};
}
