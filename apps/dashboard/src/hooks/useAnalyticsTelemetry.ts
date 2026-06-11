import { useEffect } from 'react';
import { queryClient } from '@/lib/queryClient';

type AnalyticsTelemetrySnapshot = {
  capturedAt: string;
  routeMs: number;
  resources: {
    total: number;
    api: number;
    analyticsApi: number;
    slow: Array<{
      name: string;
      durationMs: number;
      transferSize: number;
      status: number;
    }>;
  };
  queries: {
    total: number;
    analytics: number;
    fetching: number;
    error: number;
    stale: number;
  };
  memory?: {
          usedMb: number;
          totalMb: number;
          limitMb: number;
        } | undefined;
};

declare global {
  interface Window {
    __JUNO_ANALYTICS_TELEMETRY__?: AnalyticsTelemetrySnapshot | undefined;
  }
}

const ANALYTICS_QUERY_ROOTS = new Set([
  'anomalyFeed',
  'audienceOverlap',
  'audienceTwinMap',
  'bioLinkFunnel',
  'cohortBenchmark',
  'competitorBenchmark',
  'engagerRetention',
  'fleetHealth',
  'fleetMetrics',
  'fleetTotals',
  'followerFlow',
  'hashtagPerformance',
  'hookClassLift',
  'igFormatBreakdown',
  'nonFollowerReach',
  'originalityRisk',
  'qualityByPillar',
  'quoteReplyRatio',
  'replyChainDistribution',
  'storiesFunnel',
  'topicTagLift',
  'viewsBySource',
  'topPosts',
]);

const SLOW_RESOURCE_MS = 800;

export function useAnalyticsTelemetry(enabled: boolean) {
  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return;

    const routeStart = performance.now();
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    const publish = () => {
      const snapshot = collectAnalyticsTelemetry(routeStart);
      window.__JUNO_ANALYTICS_TELEMETRY__ = snapshot;
      try {
        window.localStorage.setItem('juno33.analyticsTelemetry', JSON.stringify(snapshot));
      } catch {
        // Best-effort only. Telemetry must never break the Analytics page.
      }
      window.dispatchEvent(
        new CustomEvent('juno:analytics-telemetry', {
          detail: snapshot,
        }),
      );
    };

    timeoutId = setTimeout(publish, 2200);
    intervalId = setInterval(publish, 10_000);

    return () => {
      if (timeoutId) clearTimeout(timeoutId);
      if (intervalId) clearInterval(intervalId);
    };
  }, [enabled]);
}

function collectAnalyticsTelemetry(routeStart: number): AnalyticsTelemetrySnapshot {
  const resources = performance
    .getEntriesByType('resource')
    .filter((entry): entry is PerformanceResourceTiming => entry instanceof PerformanceResourceTiming);

  const apiResources = resources.filter((entry) => {
    const url = new URL(entry.name, window.location.href);
    return url.pathname.startsWith('/api/');
  });
  const analyticsApiResources = apiResources.filter((entry) => {
    const url = new URL(entry.name, window.location.href);
    return url.pathname === '/api/analytics' || url.searchParams.has('action');
  });

  const slow = apiResources
    .filter((entry) => entry.duration >= SLOW_RESOURCE_MS)
    .sort((a, b) => b.duration - a.duration)
    .slice(0, 12)
    .map((entry) => ({
      name: summarizeResource(entry.name),
      durationMs: Math.round(entry.duration),
      transferSize: entry.transferSize,
      status: entry.responseStatus,
    }));

  const queries = queryClient.getQueryCache().findAll();
  const analyticsQueries = queries.filter((query) => {
    const root = query.queryKey[0];
    return typeof root === 'string' && ANALYTICS_QUERY_ROOTS.has(root);
  });

  return {
    capturedAt: new Date().toISOString(),
    routeMs: Math.round(performance.now() - routeStart),
    resources: {
      total: resources.length,
      api: apiResources.length,
      analyticsApi: analyticsApiResources.length,
      slow,
    },
    queries: {
      total: queries.length,
      analytics: analyticsQueries.length,
      fetching: analyticsQueries.filter((query) => query.state.fetchStatus === 'fetching').length,
      error: analyticsQueries.filter((query) => query.state.status === 'error').length,
      stale: analyticsQueries.filter((query) => query.isStale()).length,
    },
    memory: readMemory(),
  };
}

function readMemory(): AnalyticsTelemetrySnapshot['memory'] {
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

function summarizeResource(name: string) {
  const url = new URL(name, window.location.href);
  const action = url.searchParams.get('action');
  return action ? `${url.pathname}?action=${action}` : `${url.pathname}${url.search}`;
}
