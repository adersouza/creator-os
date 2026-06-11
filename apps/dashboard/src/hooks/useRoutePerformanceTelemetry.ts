import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { analytics } from '@/lib/analytics';
import { queryClient, shouldPersistQuery } from '@/lib/queryClient';

type RoutePerformanceSnapshot = {
  capturedAt: string;
  route: string;
  routeMs: number;
  resources: {
    api: number;
    failed: number;
    slow: Array<{
      name: string;
      durationMs: number;
      transferSize: number;
      status: number;
    }>;
  };
  queries: {
    total: number;
    fetching: number;
    error: number;
    stale: number;
    persisted: number;
    estimatedCacheKb: number;
    estimatedPersistedKb: number;
    byRoot: Array<{
      root: string;
      count: number;
      estimatedKb: number;
    }>;
  };
  warnings: string[];
  memory?: {
          usedMb: number;
          totalMb: number;
          limitMb: number;
        } | undefined;
};

declare global {
  interface Window {
    __JUNO_ROUTE_TELEMETRY__?: RoutePerformanceSnapshot | undefined;
  }
}

const SLOW_RESOURCE_MS = 800;
const TELEMETRY_DELAY_MS = 2500;
const MAX_SLOW_RESOURCES = 12;
const MAX_QUERY_ROOTS = 12;
const QUERY_COUNT_WARN = 250;
const CACHE_SIZE_WARN_KB = 4 * 1024;
const MEMORY_USED_RATIO_WARN = 0.7;

export function useRoutePerformanceTelemetry() {
  const location = useLocation();

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const route = `${location.pathname}${location.search}`;
    const startedAt = performance.now();
    const resourceStartIndex = performance.getEntriesByType('resource').length;

    const timeoutId = window.setTimeout(() => {
      const snapshot = collectRoutePerformance(route, startedAt, resourceStartIndex);
      window.__JUNO_ROUTE_TELEMETRY__ = snapshot;
      try {
        window.localStorage.setItem('juno33.routeTelemetry', JSON.stringify(snapshot));
      } catch {
        // Best-effort only. Telemetry must never affect app behavior.
      }
      window.dispatchEvent(new CustomEvent('juno:route-telemetry', { detail: snapshot }));
      analytics.capture('route_performance', snapshot);
      for (const warning of snapshot.warnings) {
        analytics.capture('route_performance_guardrail_warning', {
          warning,
          route: snapshot.route,
          queryCacheSizeKb: snapshot.queries.estimatedCacheKb,
          persistedCacheSizeKb: snapshot.queries.estimatedPersistedKb,
          queryCount: snapshot.queries.total,
          memory: snapshot.memory,
        });
      }
    }, TELEMETRY_DELAY_MS);

    return () => window.clearTimeout(timeoutId);
  }, [location.pathname, location.search]);
}

function collectRoutePerformance(
  route: string,
  startedAt: number,
  resourceStartIndex: number,
): RoutePerformanceSnapshot {
  const resources = performance
    .getEntriesByType('resource')
    .slice(resourceStartIndex)
    .filter((entry): entry is PerformanceResourceTiming => entry instanceof PerformanceResourceTiming);
  const apiResources = resources.filter(isApiResource);
  const failedResources = apiResources.filter((entry) => entry.responseStatus >= 400);
  const slow = apiResources
    .filter((entry) => entry.duration >= SLOW_RESOURCE_MS)
    .sort((a, b) => b.duration - a.duration)
    .slice(0, MAX_SLOW_RESOURCES)
    .map((entry) => ({
      name: summarizeResource(entry.name),
      durationMs: Math.round(entry.duration),
      transferSize: entry.transferSize,
      status: entry.responseStatus,
    }));
  const queries = queryClient.getQueryCache().findAll();
  const queryProfile = profileQueries(queries);
  const memory = readMemory();
  const warnings = buildWarnings(queryProfile, queries.length, memory);

  return {
    capturedAt: new Date().toISOString(),
    route,
    routeMs: Math.round(performance.now() - startedAt),
    resources: {
      api: apiResources.length,
      failed: failedResources.length,
      slow,
    },
    queries: {
      total: queries.length,
      fetching: queries.filter((query) => query.state.fetchStatus === 'fetching').length,
      error: queries.filter((query) => query.state.status === 'error').length,
      stale: queries.filter((query) => query.isStale()).length,
      persisted: queryProfile.persisted,
      estimatedCacheKb: queryProfile.estimatedCacheKb,
      estimatedPersistedKb: queryProfile.estimatedPersistedKb,
      byRoot: queryProfile.byRoot,
    },
    warnings,
    memory,
  };
}

type QueryProfile = {
  persisted: number;
  estimatedCacheKb: number;
  estimatedPersistedKb: number;
  byRoot: RoutePerformanceSnapshot['queries']['byRoot'];
};

type QueryCacheItem = ReturnType<ReturnType<typeof queryClient.getQueryCache>['findAll']>[number];

function profileQueries(
  queries: QueryCacheItem[],
): QueryProfile {
  const roots = new Map<string, { count: number; bytes: number }>();
  let persisted = 0;
  let estimatedBytes = 0;
  let estimatedPersistedBytes = 0;

  for (const query of queries) {
    const queryKey = query.queryKey as readonly unknown[];
    const root = summarizeQueryRoot(queryKey);
    const bytes = estimateJsonBytes(query.state.data);
    const bucket = roots.get(root) ?? { count: 0, bytes: 0 };
    bucket.count += 1;
    bucket.bytes += bytes;
    roots.set(root, bucket);
    estimatedBytes += bytes;
    if (shouldPersistQuery(queryKey)) {
      persisted += 1;
      estimatedPersistedBytes += bytes;
    }
  }

  return {
    persisted,
    estimatedCacheKb: bytesToKb(estimatedBytes),
    estimatedPersistedKb: bytesToKb(estimatedPersistedBytes),
    byRoot: Array.from(roots.entries())
      .map(([root, value]) => ({
        root,
        count: value.count,
        estimatedKb: bytesToKb(value.bytes),
      }))
      .sort((a, b) => b.estimatedKb - a.estimatedKb || b.count - a.count)
      .slice(0, MAX_QUERY_ROOTS),
  };
}

function buildWarnings(
  queryProfile: QueryProfile,
  totalQueries: number,
  memory: RoutePerformanceSnapshot['memory'],
): string[] {
  const warnings: string[] = [];
  if (totalQueries > QUERY_COUNT_WARN) {
    warnings.push(`query_count:${totalQueries}`);
  }
  if (queryProfile.estimatedPersistedKb > CACHE_SIZE_WARN_KB) {
    warnings.push(`persisted_cache_kb:${queryProfile.estimatedPersistedKb}`);
  }
  if (memory && memory.limitMb > 0 && memory.usedMb / memory.limitMb > MEMORY_USED_RATIO_WARN) {
    warnings.push(`heap_used_ratio:${Math.round((memory.usedMb / memory.limitMb) * 100)}pct`);
  }
  return warnings;
}

function summarizeQueryRoot(queryKey: readonly unknown[]) {
  const root = queryKey[0];
  if (typeof root === 'string') return root;
  if (typeof root === 'number' || typeof root === 'boolean') return String(root);
  return 'unknown';
}

function estimateJsonBytes(value: unknown) {
  if (value === undefined) return 0;
  try {
    return new Blob([JSON.stringify(value)]).size;
  } catch {
    return 0;
  }
}

function isApiResource(entry: PerformanceResourceTiming) {
  try {
    const url = new URL(entry.name, window.location.href);
    return url.pathname.startsWith('/api/') || url.hostname.includes('supabase.co');
  } catch {
    return false;
  }
}

function summarizeResource(name: string) {
  const url = new URL(name, window.location.href);
  if (url.hostname.includes('supabase.co')) {
    const select = url.searchParams.get('select');
    return `${url.pathname}${select ? `?select=${select.slice(0, 80)}` : ''}`;
  }
  const action = url.searchParams.get('action');
  return action ? `${url.pathname}?action=${action}` : `${url.pathname}${url.search}`;
}

function readMemory(): RoutePerformanceSnapshot['memory'] {
  const perf = performance as Performance & {
    memory?: {
                usedJSHeapSize: number;
                totalJSHeapSize: number;
                jsHeapSizeLimit: number;
              } | undefined;
  };
  if (!perf.memory) return undefined;
  return {
    usedMb: bytesToMb(perf.memory.usedJSHeapSize),
    totalMb: bytesToMb(perf.memory.totalJSHeapSize),
    limitMb: bytesToMb(perf.memory.jsHeapSizeLimit),
  };
}

function bytesToMb(bytes: number) {
  return Math.round((bytes / 1024 / 1024) * 10) / 10;
}

function bytesToKb(bytes: number) {
  return Math.round((bytes / 1024) * 10) / 10;
}
