/**
 * Sentry init — optional, opt-in via VITE_SENTRY_DSN.
 *
 * PII scrubbing is the whole point: Juno33 ships user emails, social
 * handles, and Meta access tokens in memory, and none of those belong in
 * a crash report. The `beforeSend` hook strips them at the edge so we
 * never rely on downstream redaction configs.
 */

import type { ErrorEvent as SentryErrorEvent, EventHint } from '@sentry/react';

const SENSITIVE_KEY_PATTERN = /token|secret|password|authorization|session|apikey|api_key|cookie/i;
const BEARER_PATTERN = /Bearer\s+[A-Za-z0-9._-]+/gi;
const EMAIL_PATTERN = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;

function redactString(value: string): string {
  return value
    .replace(BEARER_PATTERN, 'Bearer [REDACTED]')
    .replace(EMAIL_PATTERN, '[email-redacted]');
}

function redactUnknown(value: unknown, depth = 0): unknown {
  if (depth > 4) return '[truncated]';
  if (typeof value === 'string') return redactString(value);
  if (Array.isArray(value)) return value.map((v) => redactUnknown(v, depth + 1));
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (SENSITIVE_KEY_PATTERN.test(k)) {
        out[k] = '[REDACTED]';
      } else {
        out[k] = redactUnknown(v, depth + 1);
      }
    }
    return out;
  }
  return value;
}

function scrubEvent(event: SentryErrorEvent, _hint: EventHint): SentryErrorEvent | null {
  if (isViteHmrNoise(event)) return null;

  // User: keep only stable id, drop email/ip/username.
  if (event.user) {
    const { id } = event.user;
    if (id) event.user = { id };
    else delete event.user;
  }

  // Request: redact query + headers that tend to leak auth.
  if (event.request) {
    if (event.request.query_string) {
      event.request.query_string =
        typeof event.request.query_string === 'string'
          ? redactString(event.request.query_string)
          : event.request.query_string;
    }
    if (event.request.headers) {
      event.request.headers = redactUnknown(event.request.headers) as typeof event.request.headers;
    }
    if (event.request.cookies) delete event.request.cookies;
    if (event.request.data) {
      event.request.data = redactUnknown(event.request.data) as typeof event.request.data;
    }
  }

  // Breadcrumbs: scrub message + data of every breadcrumb.
  if (event.breadcrumbs) {
    event.breadcrumbs = event.breadcrumbs.map((crumb) => ({
      ...crumb,
      ...(crumb.message ? { message: redactString(crumb.message) } : {}),
      ...(crumb.data ? { data: redactUnknown(crumb.data) as typeof crumb.data } : {}),
    }));
  }

  // Extra + contexts: bulk redact.
  if (event.extra) {
    event.extra = redactUnknown(event.extra) as typeof event.extra;
  }
  if (event.contexts) {
    event.contexts = redactUnknown(event.contexts) as typeof event.contexts;
  }

  // Exception messages often embed captured strings.
  if (event.exception?.values) {
    event.exception.values = event.exception.values.map((ex) => ({
      ...ex,
      ...(ex.value ? { value: redactString(ex.value) } : {}),
    }));
  }

  return event;
}

function isViteHmrNoise(event: SentryErrorEvent): boolean {
  const values = event.exception?.values ?? [];
  const text = [
    event.message,
    ...values.map((value) => value.value),
    ...values.flatMap((value) =>
      (value.stacktrace?.frames ?? []).flatMap((frame) => [
        frame.filename,
        frame.abs_path,
        frame.module,
      ]),
    ),
  ]
    .filter(Boolean)
    .join('\n');

  return (
    text.includes('/@vite/client') ||
    text.includes('@vite/client') ||
    /send was called before connect/i.test(text) ||
    /Failed to fetch dynamically imported module: http:\/\/(?:127\.0\.0\.1|localhost):\d+/i.test(text)
  );
}

let sentryModule: {
  init: typeof import('@sentry/react').init;
  captureException: typeof import('@sentry/react').captureException;
  captureMessage: typeof import('@sentry/react').captureMessage;
  addBreadcrumb: typeof import('@sentry/react').addBreadcrumb;
} | null = null;

export async function initSentry() {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return;

  // Dynamic import keeps @sentry/react out of the critical-path chunk when
  // the DSN is unset (most dev environments). Destructure the named exports
  // at the await site — Rollup can tree-shake unused Sentry integrations
  // this way, but NOT through a `Sentry.X` namespace-access pattern.
  const {
    init,
    addBreadcrumb: sentryAddBreadcrumb,
    captureException: sentryCaptureException,
    captureMessage: sentryCaptureMessage,
    inboundFiltersIntegration,
    functionToStringIntegration,
    linkedErrorsIntegration,
    globalHandlersIntegration,
  } = await import('@sentry/react');
  sentryModule = {
    init,
    captureException: sentryCaptureException,
    captureMessage: sentryCaptureMessage,
    addBreadcrumb: sentryAddBreadcrumb,
  };

  // Explicit, minimal integration set. `defaultIntegrations: false` drops
  // BrowserTracing, Replay, BrowserProfiling, and the rest of the default
  // bundle — they ship Web-Vitals tracing + session replay that we don't
  // use (sampling is zeroed) and add ~40-60kB gzip / 100kB+ raw to the chunk.
  // Keep the four small integrations that crash reporting actually needs.
  const integrations = [
    inboundFiltersIntegration(),
    functionToStringIntegration(),
    linkedErrorsIntegration(),
    globalHandlersIntegration(),
  ];

  init({
    dsn,
    environment: import.meta.env.MODE,
    release: import.meta.env.VITE_VERCEL_GIT_COMMIT_SHA ?? 'dev',
    defaultIntegrations: false,
    integrations,
    // Performance + replay off by default — they ship load-bearing PII and
    // the cost/value hasn't been agreed yet. Flip these on deliberately.
    tracesSampleRate: 0,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    sendDefaultPii: false,
    // Drop noisy browser errors that aren't actionable.
    // - supabase-js `navigator.locks` races are benign under StrictMode /
    //   fast auth-state cycling; the library itself recovers (see
    //   services/supabase.ts unhandledrejection suppressor). No signal to
    //   Sentry — they'd just page on-call for something that self-heals.
    ignoreErrors: [
      'ResizeObserver loop completed with undelivered notifications.',
      'ResizeObserver loop limit exceeded',
      'Non-Error promise rejection captured',
      'send was called before connect',
      'Lock was stolen by another request',
      /was released because another request stole it/,
      /Lock broken by another request with the 'steal' option/,
      /lock:sb-[A-Za-z0-9-]+-auth-token/,
    ],
    beforeSend: scrubEvent,
    beforeBreadcrumb(crumb) {
      // Auth-related breadcrumbs leak session tokens in their data payloads
      // — drop them entirely rather than try to redact inline.
      if (crumb.category === 'auth') return null;
      return crumb;
    },
  });
}

/**
 * Report an error to Sentry if it's been initialized. No-op otherwise —
 * callers (notably ErrorBoundary) should not need to know whether a DSN is
 * set, and errors caught pre-init simply don't get reported.
 */
export function captureException(
  error: unknown,
  contexts?: Record<string, Record<string, unknown>>,
  extra?: Record<string, unknown>,
): void {
  if (!sentryModule) return;
  if (!contexts && !extra) {
    sentryModule.captureException(error);
    return;
  }
  const captureContext: {
    contexts?: Record<string, Record<string, unknown>>;
    extra?: Record<string, unknown>;
  } = {};
  if (contexts) captureContext.contexts = contexts;
  if (extra) captureContext.extra = extra;
  sentryModule.captureException(error, captureContext);
}

export function captureMessage(
  message: string,
  options?: {
    level?: 'fatal' | 'error' | 'warning' | 'log' | 'info' | 'debug' | undefined;
    extra?: Record<string, unknown> | undefined;
    contexts?: Record<string, Record<string, unknown>> | undefined;
  },
): void {
  if (!sentryModule) return;
  if (!options) {
    sentryModule.captureMessage(message);
    return;
  }
  const captureContext: {
    level?: 'fatal' | 'error' | 'warning' | 'log' | 'info' | 'debug';
    extra?: Record<string, unknown>;
    contexts?: Record<string, Record<string, unknown>>;
  } = {};
  if (options.level) captureContext.level = options.level;
  if (options.extra) captureContext.extra = options.extra;
  if (options.contexts) captureContext.contexts = options.contexts;
  sentryModule.captureMessage(message, captureContext);
}

export function addBreadcrumb(crumb: {
  category?: string | undefined;
  message?: string | undefined;
  level?: 'fatal' | 'error' | 'warning' | 'log' | 'info' | 'debug' | undefined;
  data?: Record<string, unknown> | undefined;
}): void {
  if (!sentryModule) return;
  const breadcrumb: {
    category?: string;
    message?: string;
    level?: 'fatal' | 'error' | 'warning' | 'log' | 'info' | 'debug';
    data?: Record<string, unknown>;
  } = {};
  if (crumb.category) breadcrumb.category = crumb.category;
  if (crumb.message) breadcrumb.message = crumb.message;
  if (crumb.level) breadcrumb.level = crumb.level;
  if (crumb.data) breadcrumb.data = crumb.data;
  sentryModule.addBreadcrumb(breadcrumb);
}
