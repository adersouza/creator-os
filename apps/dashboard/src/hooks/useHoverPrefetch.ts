import { useCallback } from 'react';

// One-shot per-route prefetch: first hover or focus on a Sidebar nav item
// fires the lazy chunk import so the click-through navigation renders
// synchronously. The `warmHotRoutes()` idle warmup already covers
// Dashboard / Calendar / Accounts / Inbox / Composer; this hook's payoff
// is rarer routes (Analytics / Reports / Autopilot / Content Library /
// Smart Links / Settings / Billing).
//
// Vite dedups the module graph, so if a route was already warmed these
// calls hit the existing module promise and return instantly.

type RouteLoader = () => Promise<unknown>;

const ROUTE_LOADERS: Record<string, RouteLoader> = {
  dashboard: () => import('../pages/Dashboard'),
  analytics: () => import('../pages/Analytics'),
  reports: () => import('../pages/Reports'),
  calendar: () => import('../pages/Calendar'),
  autopilot: () => import('../pages/Autopilot'),
  accounts: () => import('../pages/Accounts'),
  inbox: () => import('../pages/Inbox'),
  'content-library': () => import('../pages/ContentLibrary'),
  links: () => import('../pages/Links'),
  composer: () => import('../pages/Composer'),
  settings: () => import('../pages/Settings'),
  billing: () => import('../pages/Billing'),
};

const prefetched = new Set<string>();

export function useHoverPrefetch(routeId: string): () => void {
  return useCallback(() => {
    if (prefetched.has(routeId)) return;
    const loader = ROUTE_LOADERS[routeId];
    if (!loader) return;
    prefetched.add(routeId);
    void loader().catch(() => {
      prefetched.delete(routeId);
    });
  }, [routeId]);
}
