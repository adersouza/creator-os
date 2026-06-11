/**
 * Sentry Configuration - Frontend
 * Production error tracking and performance monitoring
 */

import * as Sentry from "@sentry/react";

/**
 * Initialize Sentry for error tracking and performance monitoring
 * Only runs in production or when explicitly enabled via env var
 */
export function initSentry(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  const environment = import.meta.env.MODE; // 'development' or 'production'
  const appVersion = import.meta.env.VITE_APP_VERSION || "unknown";

  // Don't initialize Sentry in development unless explicitly enabled
  if (environment === "development" && !import.meta.env.VITE_ENABLE_SENTRY) {
    console.log("Sentry disabled in development mode");

    // #478: In dev mode, install global error handlers so uncaught errors
    // are at least visible in the console (since Sentry won't catch them)
    window.addEventListener("error", (event) => {
      console.error("[DEV] Uncaught error:", event.error ?? event.message);
    });
    window.addEventListener("unhandledrejection", (event) => {
      console.error("[DEV] Unhandled promise rejection:", event.reason);
    });

    return;
  }

  // Don't initialize if DSN is not configured
  if (!dsn) {
    console.warn("Sentry DSN not configured, skipping initialization");
    return;
  }

  try {
    Sentry.init({
      dsn,
      environment,
      release: `juno33@${appVersion}`,

      // Tunnel disabled — was causing 429 rate limits that blocked page load
      // tunnel: "/api/sentry-tunnel",

      // Performance monitoring: 10% of transactions
      integrations: [Sentry.browserTracingIntegration()],
      tracePropagationTargets: [
        "localhost",
        /^https:\/\/juno33\.com/,
        /^https:\/\/threadsdashboard.*\.vercel\.app/,
      ],

      // Sample rate for performance monitoring (10% to stay within quota)
      tracesSampleRate: 0.1,

      // Sample rate for error tracking (100% - capture all errors)
      sampleRate: 1.0,

      // Filter out sensitive data before sending to Sentry
      beforeSend(event, _hint) {
        // Filter out errors in development mode (unless explicitly enabled)
        if (
          environment === "development" &&
          !import.meta.env.VITE_ENABLE_SENTRY
        ) {
          return null;
        }

        // Scrub sensitive data from error messages
        if (event.message) {
          event.message = scrubSensitiveData(event.message);
        }

        // Scrub sensitive data from breadcrumbs
        if (event.breadcrumbs) {
          event.breadcrumbs = event.breadcrumbs.map((breadcrumb) => ({
            ...breadcrumb,
            message: breadcrumb.message
              ? scrubSensitiveData(breadcrumb.message)
              : breadcrumb.message,
            data: breadcrumb.data
              ? scrubSensitiveObject(breadcrumb.data)
              : breadcrumb.data,
          }));
        }

        // Scrub sensitive data from request data
        if (event.request?.data) {
          event.request.data = scrubSensitiveObject(event.request.data);
        }

        // Scrub sensitive data from extra context
        if (event.extra) {
          event.extra = scrubSensitiveObject(event.extra);
        }

        return event;
      },

      // Ignore certain errors
      ignoreErrors: [
        // Browser extension errors
        "top.GLOBALS",
        "originalCreateNotification",
        "canvas.contentDocument",
        "MyApp_RemoveAllHighlights",
        "atomicFindClose",
        // Network errors that are expected
        "NetworkError",
        "Failed to fetch",
        "Network request failed",
        // ResizeObserver errors (benign)
        "ResizeObserver loop limit exceeded",
        "ResizeObserver loop completed with undelivered notifications",
        // CSP-blocked eval from browser extensions / bots — not our code
        "unsafe-eval",
        "Refused to evaluate a string as JavaScript",
      ],
    });

    console.log(`Sentry initialized (${environment}) - Release: ${appVersion}`);
  } catch (error) {
    console.error("Failed to initialize Sentry:", error);
  }
}

/**
 * Scrub sensitive data from strings
 * Removes tokens, emails, API keys, passwords
 */
function scrubSensitiveData(text: string): string {
  return text
    .replace(/token[=:]\s*[\w.-]+/gi, "token=[REDACTED]")
    .replace(/accessToken[=:]\s*[\w.-]+/gi, "accessToken=[REDACTED]")
    .replace(/refreshToken[=:]\s*[\w.-]+/gi, "refreshToken=[REDACTED]")
    .replace(/apiKey[=:]\s*[\w.-]+/gi, "apiKey=[REDACTED]")
    .replace(/password[=:]\s*[\w.-]+/gi, "password=[REDACTED]")
    .replace(
      /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g,
      "[EMAIL_REDACTED]",
    )
    .replace(/Bearer\s+[\w.-]+/gi, "Bearer [REDACTED]");
}

/**
 * Scrub sensitive data from objects
 */
function scrubSensitiveObject(obj: any): any {
  if (!obj || typeof obj !== "object") return obj;

  const sensitiveKeys = [
    "token",
    "accessToken",
    "refreshToken",
    "apiKey",
    "password",
    "secret",
    "authorization",
    "cookie",
    "session",
  ];

  const scrubbed: any = Array.isArray(obj) ? [] : {};

  for (const key in obj) {
    if (obj.hasOwnProperty(key)) {
      // Check if key is sensitive
      const isSensitive = sensitiveKeys.some((sensitiveKey) =>
        key.toLowerCase().includes(sensitiveKey.toLowerCase()),
      );

      if (isSensitive) {
        scrubbed[key] = "[REDACTED]";
      } else if (typeof obj[key] === "object" && obj[key] !== null) {
        // Recursively scrub nested objects
        scrubbed[key] = scrubSensitiveObject(obj[key]);
      } else if (typeof obj[key] === "string") {
        // Scrub strings
        scrubbed[key] = scrubSensitiveData(obj[key]);
      } else {
        scrubbed[key] = obj[key];
      }
    }
  }

  return scrubbed;
}

/**
 * Set user context for error tracking
 */
export function setSentryUser(userId: string | null, _email?: string): void {
  if (userId) {
    Sentry.setUser({
      id: userId,
      // Don't send email to avoid PII issues
      // email: email
    });
  } else {
    Sentry.setUser(null);
  }
}

/**
 * Clear user context (on logout)
 */
export function clearSentryUser(): void {
  Sentry.setUser(null);
}

/**
 * Add custom breadcrumb for debugging
 */
export function addSentryBreadcrumb(
  message: string,
  category: string,
  level: Sentry.SeverityLevel = "info",
  data?: Record<string, any>,
): void {
  Sentry.addBreadcrumb({
    message,
    category,
    level,
    data: data ? scrubSensitiveObject(data) : undefined,
  });
}

/**
 * Manually capture an exception
 */
export function captureSentryException(
  error: Error,
  context?: Record<string, any>,
): void {
  Sentry.captureException(error, {
    extra: context ? scrubSensitiveObject(context) : undefined,
  });
}

/**
 * Capture a message
 */
export function captureSentryMessage(
  message: string,
  level: Sentry.SeverityLevel = "info",
): void {
  Sentry.captureMessage(scrubSensitiveData(message), level);
}
