# Cron Jobs

All scheduled jobs are declared in `vercel.json`, authenticated with `CRON_SECRET`, protected by `withCronLock`, and recorded in `cron_runs` through `trackCronRun`.

Operational guardrails:

- `api/_lib/cronUtils.ts` owns the explicit lock TTL for every scheduled cron.
- `api/cron/health-monitor.ts` freshness-checks every scheduled cron.
- `api/qstash-failure.ts` records exhausted QStash messages for scheduled posts, auto-post queue items, and export jobs.
- `tests/unit/cron-manifest.test.ts` fails when a new Vercel cron is added without lock and freshness coverage.

| Job | Schedule | Max Duration | Purpose |
| --- | --- | ---: | --- |
| `webhook-processor` | `*/2 * * * *` | 120s | Processes queued Threads/Instagram webhook events and outgoing webhook deliveries. |
| `publish-worker` | `*/5 * * * *` | 180s | Scheduled-post cron fallback, Instagram container publishing, auto-post queue reconciliation, and queue-fill safety net. |
| `sync-orchestrator` | `2,17,32,47 * * * *` | 180s | Dispatches account and analytics sync phases. |
| `analytics-pipeline` | `0 2 * * *` | 300s | Runs daily analytics refresh and derived metric pipeline. |
| `daily-orchestrator` | `0 1 * * *` | 300s | Daily maintenance, token/account hygiene, retention, and account enforcement phases. |
| `health-monitor` | `0 */4 * * *` | 300s | Cron freshness, infra connectivity, deploy impact, backlog, token, and canary checks. |
| `six-hour-pipeline` | `0 */6 * * *` | 300s | Six-hour competitor, evergreen, trend, and health snapshot phases. |
| `weekly-reports` | `0 8 * * 1` | 300s | Weekly report and scheduled report delivery. |
| `cost-digest` | `0 8 * * *` | 120s | Daily AI/provider cost digest. |
| `monthly-kpi` | `0 8 1 * *` | 300s | Monthly KPI rollups and admin reporting. |
| `trend-scanner` | `0 */2 * * *` | 300s | Trend discovery and scanning. |
| `auto-learning` | `0 6 * * *` | 300s | Learns from recent outcomes and updates auto-post intelligence. |
| `autoposter-watchdog` | `15,45 * * * *` | 300s | Watches auto-post health, queue state, and stuck conditions. |
| `daily-orchestrator-late` | `30 1 * * *` | 300s | Late daily repair/recovery phases that run after the main daily orchestrator. |
| `auto-reply-worker` | `*/15 * * * *` | 120s | Harvests comments and publishes eligible generated replies. |
| `inbox-suggestions` | `*/5 * * * *` | 120s | Generates and refreshes unified inbox reply suggestions. |
| `reply-farming-worker` | `*/30 * * * *` | 120s | Runs configured reply-growth workflows for eligible groups. |
| `dawn-planner` | `5 */4 * * *` | 300s | Plans queue fill and future auto-post schedules. |
| `account-state-evaluator` | `*/15 * * * *` | 120s | Evaluates account state, throttles, and eligibility flags. |
| `cta-reply-worker` | `10,40 * * * *` | 120s | Publishes delayed CTA replies for eligible high-performing posts. |
| `scheduler` | `*/5 * * * *` | 180s | Runs v2/v3 account-group scheduler loops. |
| `reconcile-daily` | `30 3 * * *` | 300s | Daily reconciliation and data consistency checks. |
| `overnight-brief` | `55 1 * * *` | 300s | Builds overnight intelligence summaries. |
| `originality-capture` | `17 3 * * *` | 300s | Backfills originality fingerprints and media hash signals. |
