import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import App from './App.tsx';
import { ErrorBoundary } from './components/ui/ErrorBoundary';
import { analytics } from './lib/analytics';
import { setLocale } from './lib/locale';
import { initSentry } from './lib/sentry';
import { installHoverSpecular } from './lib/hoverSpecular';
import { installScrollEdge } from './lib/scrollEdge';
import {
  queryClient,
  queryPersister,
  shouldPersistQuery,
  QUERY_CACHE_BUSTER,
  QUERY_CACHE_MAX_AGE_MS,
} from './lib/queryClient';
import { initWebVitals } from './lib/webVitals';
import { supabase } from './services/supabase';
import { STRIPE_PRICES, isLiveStripePrice } from './types/team';
import './index.css';

// Sentry — fires only if VITE_SENTRY_DSN is set. PII scrubbing happens in
// beforeSend (see lib/sentry.ts); no emails, tokens, or cookies leave the
// browser even when crash reports are enabled.
// Deferred to idle so the Sentry chunk (~155kB gzip) doesn't compete with
// critical-path rendering. captureException in ErrorBoundary still awaits
// initialisation, so pre-init errors are queued rather than dropped.
const scheduleSentry = () => void initSentry();
if (typeof window !== 'undefined' && 'requestIdleCallback' in window) {
  (window as Window & { requestIdleCallback: (cb: () => void, opts?: { timeout: number }) => void })
    .requestIdleCallback(scheduleSentry, { timeout: 2000 });
} else {
  setTimeout(scheduleSentry, 1500);
}

// Install the single delegated pointer listener that drives `--mx/--my` on
// `.hover-specular` / `.liquid-hover` elements. No-ops under prefers-reduced-motion.
installHoverSpecular();

// Reactive scroll-edge — writes --scroll-depth onto .scroll-edge so the
// topbar's fade + backdrop-blur scale with scroll position (HIG Materials §
// Scroll edge). No-op under reduced motion.
installScrollEdge();

// Dev-only guard: warn once if Stripe price envs fell back to the live-mode
// defaults baked into STRIPE_PRICES. Prod behaves identically — the defaults
// are the correct live IDs — but this catches misconfigured dev/preview envs
// where someone forgot to set VITE_STRIPE_* before clicking "Upgrade".
if (import.meta.env.DEV) {
  const missing: string[] = [];
  for (const [tier, prices] of Object.entries(STRIPE_PRICES)) {
    if (typeof prices === 'string') {
      if (!isLiveStripePrice(prices)) missing.push(`addon`);
      continue;
    }
    for (const [interval, id] of Object.entries(prices)) {
      if (!isLiveStripePrice(id as string)) missing.push(`${tier}.${interval}`);
    }
  }
  if (missing.length) {
    // biome-ignore lint/suspicious/noConsole: dev-only stripe config check
    console.warn(
      `[stripe] Non-live price IDs detected for: ${missing.join(', ')}. ` +
      `Set VITE_STRIPE_* in .env before attempting checkout.`,
    );
  }
}

// Analytics only fires if consent already exists in localStorage. The in-app
// banner was removed so product analytics stay dormant for new users.
void analytics.init();

// Core Web Vitals (LCP/CLS/INP/TTFB/FCP) → analytics pipeline for real-user
// monitoring. Consent-gated like every other event.
initWebVitals();

// Service worker — required for push notifications + PWA install.
// Silent if the browser doesn't support it (older Safari, etc).
// In dev, aggressively unregister any old production SW that might still be
// controlling localhost; otherwise Chrome can serve stale dist assets over the
// Vite dev server and make route/content verification meaningless.
if ('serviceWorker' in navigator && import.meta.env.DEV) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.getRegistrations()
      .then((registrations) => Promise.all(registrations.map((registration) => registration.unregister())))
      .then(() => {
        if (navigator.serviceWorker.controller) {
          window.location.reload();
        }
      })
      .catch((err) => {
        void err;
      });
  });
} else if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').then(() => {
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        // Don't auto-reload — that silently discards in-flight forms,
        // composer drafts, and unsaved settings. Surface a toast and let
        // the user choose when to reload.
        void import('@/lib/toast').then(({ appToast }) => {
          appToast.info('A new version is available', {
            description: 'Refresh to load the latest build.',
            duration: Infinity,
            action: {
              label: 'Refresh',
              onClick: () => window.location.reload(),
            },
          });
        });
      });
    }).catch((err) => {
      // no-op: prod registration failures are surfaced via Sentry
      void err;
    });
  });
}

// Hydrate locale from Supabase once the session is ready. localStorage is the
// primary source; this call just keeps cross-device settings in sync.
void (async () => {
  try {
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;
    // user_settings is a KV table (setting_key + setting_value), not a columnar
    // row — filter by key and read the JSON value.
    const { data } = await supabase
      .from('user_settings')
      .select('setting_value')
      .eq('user_id', user.id)
      .eq('setting_key', 'locale')
      .maybeSingle();
    const locale = typeof data?.setting_value === 'string' ? data.setting_value : null;
    if (locale) setLocale(locale);
  } catch {
    /* fall back to localStorage or navigator.language */
  }
})();

// Easter egg for operators + devs who crack open the console. Oxblood on
// the cream substrate, one tight line — matches the app register. Skipped
// in dev (noisy) and when reduced-motion / prefers-reduced-transparency
// hints at a very conservative device.
if (!import.meta.env.DEV) {
}

// biome-ignore lint/style/noNonNullAssertion: #root is guaranteed by index.html
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <PersistQueryClientProvider
        client={queryClient}
        persistOptions={{
          persister: queryPersister,
          maxAge: QUERY_CACHE_MAX_AGE_MS,
          buster: QUERY_CACHE_BUSTER,
          dehydrateOptions: {
            shouldDehydrateQuery: ({ queryKey, state }) =>
              state.status === 'success' && shouldPersistQuery(queryKey),
          },
        }}
      >
        <App />
      </PersistQueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
