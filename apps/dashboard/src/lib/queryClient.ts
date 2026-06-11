import { QueryClient } from '@tanstack/react-query';
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import { get, set, del } from 'idb-keyval';

const QUERY_GC_TIME_MS = 30 * 60_000;
const QUERY_CACHE_MAX_AGE_MS = 30 * 60_000;

// An operator flips between Juno33 and Threads/IG 15–30× a day. With
// refetchOnWindowFocus: true, every return triggered a cascade refetch
// against Supabase — redundant work, since realtime subscriptions and
// the leader-tab indicator already keep the cache honest. Opt in per-query
// when freshness actually matters (Inbox, Calendar today).
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      // Keep query data warm for short tab-hopping sessions without retaining
      // large fleet analytics payloads for an entire workday. The previous
      // 24h default made Safari/iOS prone to "significant memory" reloads on
      // large workspaces because dashboard and analytics payloads stayed live
      // long after their tiles unmounted.
      gcTime: QUERY_GC_TIME_MS,
      refetchOnWindowFocus: false,
      retry: 1,
      throwOnError: (error) => {
        const status =
          (error as { status?: number | undefined }).status ??
          (error as { statusCode?: number | undefined }).statusCode;
        return status === 401 || (typeof status === 'number' && status >= 500);
      },
    },
  },
});

// Query-key roots that persist to IndexedDB across hard refreshes.
// Keep this list intentionally small. Large dashboard/analytics payloads are
// fetched on demand and held in memory only briefly; persisting them caused
// heavy hydration and browser memory pressure on large fleets.
const PERSISTED_QUERY_ROOTS = new Set<string>([
  'connectedAccounts',
  'accountGroups',
  'calendarPosts',
  'agencyBranding',
  // DO NOT persist routing-gate queries here. `onboardingState` and
  // `trialStatus` drive AuthGate / billing redirects — a stale hydrate
  // would bounce users to /welcome or /billing for one render tick
  // before the background refetch lands, even after they've completed
  // onboarding or paid. They must always reflect fresh auth truth,
  // not a persisted snapshot.
]);

export function shouldPersistQuery(queryKey: readonly unknown[]): boolean {
  const root = queryKey[0];
  return typeof root === 'string' && PERSISTED_QUERY_ROOTS.has(root);
}

// IndexedDB-backed persister via idb-keyval (~600B). Async so serialization
// of the cache never blocks the main thread on write — the localStorage
// alternative is synchronous and capped at 5MB per origin.
export const queryPersister = createAsyncStoragePersister({
  storage: {
    getItem: (key) => get<string>(key).then((v) => v ?? null),
    setItem: (key, value) => set(key, value),
    removeItem: (key) => del(key),
  },
  key: 'juno33-query-cache',
  throttleTime: 1000,
});

// Bump on any breaking change to persisted query shapes (column rename,
// RPC payload reshape, key factory refactor). Mismatched cache is silently
// discarded instead of hydrating into stale types.
// v3 — stop hydrating large dashboard/analytics payloads. Existing v2 clients
// may have a 24h persisted dashboard cache, so force one clean discard.
const QUERY_CACHE_BUSTER_MANUAL = 'v3';
const QUERY_CACHE_HASH = import.meta.env.VITE_QUERY_CACHE_HASH || 'dev';

export const QUERY_CACHE_BUSTER = `${QUERY_CACHE_HASH}-${QUERY_CACHE_BUSTER_MANUAL}`;

export { QUERY_CACHE_MAX_AGE_MS };
