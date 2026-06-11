import { onCLS, onINP, onLCP, onTTFB, onFCP, type Metric } from 'web-vitals';
import { captureMessage } from './sentry';
import { trackClientEvent } from '@/services/clientTelemetry';

const HIGH_INP_MS = 500;

/**
 * Report Core Web Vitals (LCP, CLS, INP, TTFB, FCP) to our analytics
 * pipeline for real-user monitoring. 2026 Google ranking signals use INP
 * (not FID), so we prioritize it in the dashboard we build.
 *
 * Gated by the same consent flow as every other analytics event — if the
 * operator hasn't consented, nothing leaves the browser.
 */
export function initWebVitals(): void {
  const report = (metric: Metric) => {
    const routeTelemetry = window.__JUNO_ROUTE_TELEMETRY__;
    const payload = {
      name: metric.name,
      value: metric.value,
      rating: metric.rating,
      delta: metric.delta,
      id: metric.id,
      navigationType: metric.navigationType,
      route: `${window.location.pathname}${window.location.search}`,
      viewportClass: getViewportClass(),
      connectionType: getConnectionType(),
      appVersion: import.meta.env.VITE_VERCEL_GIT_COMMIT_SHA ?? 'dev',
      cacheWarningCount: routeTelemetry?.warnings.length ?? 0,
      queryCacheSizeKb: routeTelemetry?.queries.estimatedCacheKb ?? 0,
    };
    trackClientEvent('web_vitals', payload);
    if (metric.name === 'INP' && metric.value >= HIGH_INP_MS) {
      trackClientEvent('web_vitals', {
        type: 'high_inp',
        ...payload,
      });
      captureMessage('High INP detected', {
        level: 'warning',
        extra: payload,
      });
    }
  };

  onCLS(report);
  onINP(report);
  onLCP(report);
  onTTFB(report);
  onFCP(report);
}

function getViewportClass() {
  const width = window.innerWidth;
  if (width < 640) return 'mobile';
  if (width < 1024) return 'tablet';
  return 'desktop';
}

function getConnectionType() {
  const connection = navigator as Navigator & {
    connection?: { effectiveType?: string | undefined; type?: string | undefined } | undefined;
  };
  return connection.connection?.effectiveType || connection.connection?.type || 'unknown';
}
