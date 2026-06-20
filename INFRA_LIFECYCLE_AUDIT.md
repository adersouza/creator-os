# Infra Lifecycle Audit

**Status:** terminal closeout ledger for Creator OS -> ThreadsDashboard seam, Vercel crons/backend, and Supabase schema. No schema or Vercel item is open as of the latest map refresh.

**Boundary:** Creator OS remains the integration/planning repo. ThreadsDashboard remains the production dashboard/runtime repo. There is no dashboard mirror in Creator OS.

## Scorecard

| Domain | Score | Status |
|---|---:|---|
| Cross-repo lifecycle seam | 9.5/10 | Fixed. HTTP ingest, idempotency, remote-media checks, contract validation, retry/read-back, and scheduled metric return leg are landed. |
| Vercel crons | 9.5/10 | Fixed. B1-B5 hardening is landed; publish-worker runtime packaging is production-verified. Reopen only on fresh run-report evidence. |
| Vercel backend | 9.5/10 | Fixed. C1-C6 hardening is landed: retry-eligible failures, manual-publish duration, webhook/container guardrails, token hygiene, Threads taxonomy, CSP fail-closed behavior, and privileged-route scoping. |
| Supabase schema/DB | 9.5/10 | Fixed/accepted. D1/D2/D3/D5/D6 migrations are merged/applied; replay/type hygiene is closed; low-materiality unused-index leftovers are accepted by threshold. |

## Terminal Proof

| Track | Proof |
|---|---|
| Seam idempotency | Partial unique Campaign Factory post-key boundary, stable `X-Idempotency-Key`, duplicate-race noop handling, and export read-back before success. |
| Media boundary | Creator OS pre-POST guard and TD ingest guard reject local/missing media URLs. |
| Contract/schema drift | Generated canonical schemas and `pnpm check:contracts`; TD-local policy checks stay intentionally layered on top. |
| Metric return leg | `post_metric_history.read.v1` plus scheduled Creator OS sync; renamed/missing TD metric columns fail loudly. |
| Vercel cron ownership | B1-B5 closed scheduler overlap, watchdog recovery loops, overdue IG redispatch, reconcile timeout, and budget enforcement. |
| Vercel backend behavior | Cross-reply retry failures return 5xx, manual publish has a 60s function cap, IG webhook fallback hard-rejects, async IG containers expire, token refresh is guarded, media-reuse override is short-lived, Threads publish uses `classifyMetaError()`, and CSP reports fail closed with scrubbed output. |
| Schema replay/types | Live out-of-band tables are backfilled into migrations, generated Supabase types include the live table surface, and repaired inbox tables have GDPR export/delete coverage. |
| RLS/default-deny | Hot tables are RLS-protected; service-role-only creator identity tables and SECURITY DEFINER helper intent are documented. |
| Index hygiene | D1/D2/D3 drops/adds are applied. Remaining zero-scan helper indexes are below the materiality threshold and are documented-kept. |

## Reopen Criteria

Do not open more schema or Vercel hardening work from stale audit text. Reopen only if one of these concrete triggers fires:

- A cron run report shows a fresh missed delivery, duplicate dispatch, unbounded recovery loop, or dead-letter growth without alerting.
- A privileged Vercel route loses account/workspace scoping or reason tagging.
- Vercel logs show a recurrence of `generated-schemas`, `Cannot find module`, `phase_error`, or publish-worker runtime packaging errors.
- Supabase migration replay, generated types, or GDPR export/delete coverage drifts from the live table set.
- An unused-index family is hot-path, on a table with >=10k writes in the audit window, or >=16MB unused bloat.

## Out Of Scope

Operator UX, product surface redesigns, production deployment promotion, unit economics beyond the budget cap, and Creator OS pipeline internals belong to their own ledgers.
