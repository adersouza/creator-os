/**
 * Minimal stale-while-revalidate cache for page-scoped Supabase hooks.
 *
 * Each hook that returns widget-shaped data should instantiate its own cache
 * via `createHookCache<State>()` and:
 *   1. Initialise its `useState` with `cache.get(userKey)` if present — so
 *      navigating back to a page reuses the last payload instead of flashing
 *      empty state while a fresh fetch runs.
 *   2. Gate its background fetch behind `cache.isFresh(userKey)` — if the
 *      cached payload is under FRESH_MS old, skip the refetch entirely. This
 *      is what makes clicking between pages feel instant instead of firing
 *      a Supabase round-trip on every mount. Realtime subscriptions keep
 *      the cache live in the background, so a conservative freshness window
 *      doesn't cause stale UI.
 *   3. Call `cache.set(userKey, nextState)` every time the fetch resolves so
 *      the next mount also gets a warm, timestamped start.
 *
 * Entries are keyed by userKey (email or id) and cleared when the key switches
 * (sign-out or account swap) via `cache.clearOthers(userKey)`.
 */

/** Default freshness window — 30s matches Juno33's SWR cache. */
export const DEFAULT_FRESH_MS = 30_000;

interface CacheEntry<State> {
  value: State;
  updatedAt: number;
}

export interface HookCache<State> {
  get: (userKey: string | null) => State | undefined;
  /** Returns whatever was last written, regardless of userKey. Useful for the
   *  first render after a route re-mount, when `useAuthUser` hasn't hydrated
   *  yet and we'd otherwise miss the warm cache the previous visit populated. */
  getLatest: () => State | undefined;
  /** True if a cache entry exists for `userKey` and is younger than
   *  `freshMs` (default 30s). Hooks should skip their background fetch
   *  when this returns true. */
  isFresh: (userKey: string | null, freshMs?: number) => boolean;
  /** Milliseconds since the entry was last written, or `Infinity` if missing. */
  getAge: (userKey: string | null) => number;
  set: (userKey: string | null, value: State) => void;
  clearOthers: (keepUserKey: string | null) => void;
  clearAll: () => void;
}

export function createHookCache<State>(): HookCache<State> {
  const store = new Map<string, CacheEntry<State>>();
  let lastKey: string | null = null;
  return {
    get: (userKey) => (userKey ? store.get(userKey)?.value : undefined),
    getLatest: () => (lastKey ? store.get(lastKey)?.value : undefined),
    isFresh: (userKey, freshMs = DEFAULT_FRESH_MS) => {
      if (!userKey) return false;
      const entry = store.get(userKey);
      if (!entry) return false;
      return Date.now() - entry.updatedAt < freshMs;
    },
    getAge: (userKey) => {
      if (!userKey) return Infinity;
      const entry = store.get(userKey);
      if (!entry) return Infinity;
      return Date.now() - entry.updatedAt;
    },
    set: (userKey, value) => {
      if (!userKey) return;
      store.set(userKey, { value, updatedAt: Date.now() });
      lastKey = userKey;
    },
    clearOthers: (keepUserKey) => {
      for (const k of Array.from(store.keys())) {
        if (k !== keepUserKey) store.delete(k);
      }
    },
    clearAll: () => {
      store.clear();
      lastKey = null;
    },
  };
}
