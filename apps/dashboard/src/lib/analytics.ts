/**
 * Thin PostHog wrapper. Loads posthog-js on first consent to avoid
 * shipping it in the main bundle for users who say no. Reads VITE_POSTHOG_KEY.
 *
 * Usage:
 *   await analytics.init();              // no-op unless user consented
 *   analytics.capture('post_published'); // safe even pre-init (buffered)
 */

const CONSENT_KEY = 'juno33-consent-analytics';
type Consent = 'granted' | 'denied' | null;

type Queued =
  | { type: 'capture'; event: string; props?: Record<string, unknown> | undefined }
  | { type: 'identify'; distinctId: string; props?: Record<string, unknown> | undefined }
  | { type: 'setPersonProperties'; props: Record<string, unknown> };

interface Posthog {
  init: (key: string, options?: Record<string, unknown>) => void;
  capture: (event: string, props?: Record<string, unknown>) => void;
  identify: (distinctId: string, props?: Record<string, unknown>) => void;
  people?: { set: (props: Record<string, unknown>) => void } | undefined;
  opt_out_capturing: () => void;
  opt_in_capturing: () => void;
  reset: () => void;
}

let ph: Posthog | null = null;
const queue: Queued[] = [];
let loading: Promise<void> | null = null;
let initialized = false;

function getConsent(): Consent {
  try {
    const v = localStorage.getItem(CONSENT_KEY);
    if (v === 'granted' || v === 'denied') return v;
  } catch {
    /* ignore */
  }
  return null;
}

export function setConsent(value: 'granted' | 'denied'): void {
  try {
    localStorage.setItem(CONSENT_KEY, value);
  } catch {
    /* ignore */
  }
  if (value === 'granted') {
    if (initialized) ph?.opt_in_capturing();
    void initPostHog();
  } else {
    queue.length = 0;
    if (initialized) ph?.opt_out_capturing();
  }
}

export function hasConsent(): boolean {
  return getConsent() === 'granted';
}

export function needsConsentDecision(): boolean {
  return getConsent() === null;
}

async function loadScript(): Promise<void> {
  if (typeof window === 'undefined' || ph) return;
  if (loading) return loading;
  loading = new Promise<void>((resolve, reject) => {
    import('posthog-js')
      .then((module) => {
        const client = (module.default ?? module) as unknown as Posthog;
        ph = client;
        resolve();
      })
      .catch(() => {
        loading = null;
        reject(new Error('PostHog module failed to load'));
      });
  });
  return loading;
}

async function initPostHog(): Promise<void> {
  if (initialized) return;
  if (typeof window === 'undefined') return;
  if (!hasConsent()) return;

  const key = import.meta.env.VITE_POSTHOG_KEY;
  if (!key) return;

  try {
    await loadScript();
    if (initialized) return;
    if (!hasConsent()) {
      queue.length = 0;
      return;
    }
    const client = ph as Posthog | null;
    if (!client) return;
    client.init(key, {
      api_host: 'https://app.posthog.com',
      autocapture: false,
      capture_pageview: false,
      capture_pageleave: true,
      persistence: 'localStorage+cookie',
      person_profiles: 'identified_only',
    });
    initialized = true;
    loading = null;

    // Drain queue
    for (const item of queue.splice(0)) {
      if (item.type === 'capture') {
        client.capture(item.event, item.props);
      } else if (item.type === 'identify') {
        client.identify(item.distinctId, item.props);
      } else {
        client.people?.set(item.props);
      }
    }
  } catch {
    loading = null;
    /* silent — analytics should never throw at callers */
  }
}

export const analytics = {
  async init(): Promise<void> {
    if (hasConsent()) await initPostHog();
  },
  capture(event: string, props?: Record<string, unknown>): void {
    if (!hasConsent()) return;
    if (initialized && ph) {
      ph.capture(event, props);
    } else {
      queue.push({ type: 'capture', event, props });
      void initPostHog();
    }
  },
  identify(distinctId: string, props?: Record<string, unknown>): void {
    if (!hasConsent()) return;
    if (initialized && ph) {
      ph.identify(distinctId, props);
    } else {
      queue.push({ type: 'identify', distinctId, props });
      void initPostHog();
    }
  },
  setPersonProperties(props: Record<string, unknown>): void {
    if (!hasConsent()) return;
    if (initialized && ph) {
      ph.people?.set(props);
    } else {
      queue.push({ type: 'setPersonProperties', props });
      void initPostHog();
    }
  },
  reset(): void {
    ph?.reset();
  },
};
