/// <reference lib="webworker" />
/**
 * Juno33 service worker — injectManifest entry.
 *
 * Three concerns:
 *   1. Push notification + OS notification click
 *   2. Lightweight Workbox precache bookkeeping for the current build
 *   3. Offline navigation fallback to /offline.html
 *
 * The real stale-cache protection lives in /sw-version-check.js, which now
 * runs before the app bootstraps and force-clears old registrations/caches on
 * version bumps. We keep Workbox here minimal so injectManifest can build.
 */
import { ExpirationPlugin } from 'workbox-expiration';
import { cleanupOutdatedCaches, precacheAndRoute } from 'workbox-precaching';
import { NavigationRoute, registerRoute } from 'workbox-routing';
import { CacheFirst, NetworkOnly, StaleWhileRevalidate } from 'workbox-strategies';

declare const self: ServiceWorkerGlobalScope & {
  __WB_MANIFEST: Array<{ url: string; revision: string | null }>;
};

precacheAndRoute(self.__WB_MANIFEST);
cleanupOutdatedCaches();

// Offline navigation fallback — try the network with a 3s budget, otherwise
// serve the precached /offline.html. Without this, the precached offline page
// was dead code: navigation requests went to the network, hung, and the user
// got the browser's default offline screen instead of our branded fallback.
registerRoute(
  new NavigationRoute(
    new NetworkOnly({
      networkTimeoutSeconds: 3,
      plugins: [
        {
          handlerDidError: async () =>
            (await caches.match('/offline.html')) ?? Response.error(),
        },
      ],
    }),
  ),
);

// ─── Runtime caching ──────────────────────────────────────────────
// API responses set their own Cache-Control (e.g. avatar proxy ships
// `public, max-age=3600`), but the browser ignores that for SW-controlled
// requests unless we explicitly cache. CacheFirst with a 50-entry / 1-day
// cap covers the avatar/media proxy without holding stale frames forever.
registerRoute(
  ({ url }) =>
    url.pathname.startsWith('/api/avatar') ||
    url.pathname === '/api/competitor-avatar' ||
    url.pathname === '/api/media-proxy',
  new CacheFirst({
    cacheName: 'avatar-cache-v1',
    plugins: [
      new ExpirationPlugin({
        maxEntries: 100,
        maxAgeSeconds: 60 * 60, // 1h — Meta CDN URLs rotate; don't hold longer
        purgeOnQuotaError: true,
      }),
    ],
  }),
);

// Google fonts CDN — StaleWhileRevalidate so first paint uses cache + bg
// refresh keeps things current.
registerRoute(
  ({ url }) =>
    url.origin === 'https://fonts.googleapis.com' ||
    url.origin === 'https://fonts.gstatic.com',
  new StaleWhileRevalidate({
    cacheName: 'gfonts-v1',
    plugins: [
      new ExpirationPlugin({
        maxEntries: 30,
        maxAgeSeconds: 60 * 60 * 24 * 30, // 30d
        purgeOnQuotaError: true,
      }),
    ],
  }),
);

// ─── Existing push + notification handlers ─────────────────────────

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

interface PushPayload {
  title?: string | undefined;
  body?: string | undefined;
  icon?: string | undefined;
  badge?: string | undefined;
  tag?: string | undefined;
  data?: { url?: string | undefined } | undefined;
  requireInteraction?: boolean | undefined;
}

self.addEventListener('push', (event) => {
  let payload: PushPayload = {};
  try {
    payload = event.data ? (event.data.json() as PushPayload) : {};
  } catch {
    payload = { title: 'Juno33', body: event.data ? event.data.text() : '' };
  }

  const title = payload.title || 'Juno33';
  const options: NotificationOptions = {
    body: payload.body || '',
    icon: payload.icon || '/icon-192.png',
    badge: payload.badge || '/favicon.svg',
    tag: payload.tag,
    data: payload.data || { url: '/' },
    requireInteraction: payload.requireInteraction || false,
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const data = event.notification.data as { url?: string | undefined } | undefined;
  const targetUrl = data?.url || '/';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ('focus' in client) {
          client.focus();
          if ('navigate' in client && targetUrl !== '/') {
            return client.navigate(targetUrl).catch(() => null);
          }
          return null;
        }
      }
      if (self.clients.openWindow) {
        return self.clients.openWindow(targetUrl);
      }
      return null;
    }),
  );
});
