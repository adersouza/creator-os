# Dashboard Sentry Verification

Sentry is already the Dashboard error-reporting layer. This checklist verifies
configuration before runtime promotion; it does not add OpenTelemetry or change
serverless instrumentation.

## Current Client Release

`apps/dashboard/config/sentry.ts` sets the browser release as:

```text
juno33@<VITE_APP_VERSION or 0.0.0-dev>
```

Production builds must set a stable `VITE_APP_VERSION` value that matches the
deployed artifact or commit SHA. Do not rely on `0.0.0-dev` for production
debugging.

## Required Environment Variables

Client/runtime:

- `VITE_SENTRY_DSN`
- `VITE_APP_VERSION`
- `VITE_ENABLE_SENTRY` only when explicitly enabling Sentry in development

Source-map upload, if enabled by the deployment system:

- `SENTRY_AUTH_TOKEN`
- `SENTRY_ORG`
- `SENTRY_PROJECT`
- release value matching `juno33@<VITE_APP_VERSION>`

Do not place source-map upload tokens in preview jobs that do not build or
upload production artifacts.

## Tunnel And Project

`apps/dashboard/config/sentry.ts` leaves `tunnel` commented by default. If a
Sentry tunnel is later enabled, document:

- the route path;
- the allowed CSP `connect-src` host/path;
- the Sentry project receiving tunneled events;
- the rollback path if the tunnel breaks client reporting.

## Promotion Gate

Before Dashboard runtime promotion from the monorepo:

1. Confirm `VITE_APP_VERSION` is set in preview/staging/prod builds.
2. Confirm Sentry receives one non-production test event for the exact release.
3. Confirm source maps are uploaded for that release, or document why source-map
   upload is intentionally deferred.
4. Confirm no production Supabase, QStash, Instagram, or publish credentials are
   exposed to Sentry CI/source-map upload jobs.
