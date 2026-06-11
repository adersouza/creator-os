# Product Features

## Notifications
- **Discord only**: `api/_lib/deliverNotification.ts` fires Discord alerts for 8 critical types via `alerting.ts`. Push + email delivery removed (2026-04-01).
- AI generation failure notifications deduped 1/hr/group via Redis.

## Social Listening
- `listening_alerts` + `listening_results` tables (workspace-scoped)
- `POST /api/listening/monitor` scans comments/mentions/webhooks for keyword matches
- Sentiment analysis via `api/_lib/sentiment.js`

## Billing
- Stripe webhooks handle `payment_failed` → `past_due` status + email alert
- `enforceAccountLimits()` deactivates excess accounts on downgrade (includes add-on capacity validation)
- `stripe_processed_events` table for webhook idempotency (72h cleanup)
- Periodic subscription status poll (daily cron) catches missed webhooks — prevents users staying on paid tier if `payment_failed` event is lost

## GDPR/CCPA
- `DELETE /api/user/delete` — cascading 27+ tables, Meta token revocation, requires email confirmation. Includes listening_alerts, rss_feeds, trend_forecasts, unified_links, inbox_assignments
- `GET /api/user/export` — JSON export of 40+ tables

## Scheduled Reports (weekly)
- `api/cron/weekly-reports.ts` — Monday 8AM UTC, pulls subscribers, builds PDF via `api/_lib/reportBuilder.ts`, delivers via email (Resend) and/or Slack webhook.
- Gating: email present + opted-in → email send; `slack_webhook_url` starts with `https://hooks.slack.com/` → Slack send. Either success counts.
- Slack format: `api/_lib/slackNotifier.ts` Block Kit with headline KPI grid + top post + context footer.
