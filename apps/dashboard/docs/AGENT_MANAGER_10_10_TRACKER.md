# Juno33 Agent Manager 10/10 Tracker

Last updated: 2026-05-26

## Purpose

This is the canonical implementation tracker for making Juno33's Codex/operator agent manager production-grade for 200+ Instagram and Threads accounts.

The target system lets Codex and AI operators understand the whole app, propose useful actions, dry-run every risky operation, request exact approval, execute only authorized work, and leave an auditable trail.

Current rating: 9.85/10
Target rating: 10/10

## What Is Left

These are the remaining gaps to move from 9.8/10 toward 10/10. The app is now strong enough for supervised operator workflows and the main practical 200-account agent-manager slices are implemented for v1. The remaining work is real production/staging verification outside local mocks, plus future automation polish that should only be built when operators prove they need it.

### Remaining Future Polish

1. **Approval execution dispatch**
   - Current state: exact approvals now execute typed internal actions plus the highest-value social operations: publish, schedule, reschedule, send reply, retry queue item, trigger queue fill, and resume/clear account cooldown. Execution claims the intent as `dispatching`, runs the existing production handler under the intent idempotency key, consumes successful intents, and marks handler failures as `failed` with a recovery task. Seeded scale E2E now covers the Approval Queue execute path and dispatch-failure recovery copy.
   - Remaining: more niche destructive/write actions only where they create practical operator value.
   - Acceptance: approved intent executes exactly once, writes audit before side effect, consumes the intent when dispatched, and returns a typed result.

2. **Approval edit/diff handoff**
   - Current state: Approval Queue has filters, deep links, exact preview, notes, hash copying, rejection reason templates, JSON payload diffing, edit-and-resubmit, a timeline-style approval history panel, and a structured editor for common publish, schedule, reschedule, reply, and queue-fill payload fields. Revised approvals create a new exact intent with a new payload hash/idempotency key and close the superseded approval/task.
   - Remaining: more specialized field editors for rare action types if operators need them.
   - Acceptance: a reviewer can fix a risky request without leaving the approval workflow.

3. **Full fleet calendar capacity mode**
   - Current state: Calendar portfolio view now shows a week-matched account-day matrix from the authoritative operator `fleetCapacity` snapshot, including scheduled/queued coverage, failed/DLQ recovery, pending approvals, gaps, conflicts, scoped filters, and safe routes to recovery surfaces. Gap and conflict actions now create approval-gated operator intents through dry-run/request-approval instead of executing queue-fill or rebalance directly.
   - Remaining: run the opt-in staging smoke against a real non-production Supabase/Vercel target.
   - Acceptance: a 200-account operator can see where the fleet is under/over-scheduled and safely rebalance.

4. **AI eval and provider coverage**
   - Current state: golden evals, eval snapshots, and Dashboard AI Evals summary exist for canonical provider-router calls. High-value direct Gemini bypasses now record live direct-provider eval snapshots for alt text, vision scoring, media vision, inspiration ideas, and trend post generation. Operator snapshot coverage now reports direct generative covered/total counts, documented non-generative surfaces, uncovered direct surfaces, suite/surface/day trend rows, suite summaries, latest failures, and deterministic threshold flags.
   - Remaining: backfill from older AI action logs if needed, and any newly added direct provider route must either record a snapshot or be documented as deterministic/non-generative.
   - Acceptance: every AI surface has either eval snapshots or an explicit documented reason it is deterministic/non-generative.

5. **Remaining high-risk idempotency and audit coverage**
   - Current state: major publish/schedule/reply/queue paths are guarded. This now also covers queue-fill receiver idempotency, autopilot queue-fill replay idempotency plus outbound guard audit, admin DLQ retry/purge fail-closed idempotency, DLQ retry audit logging, direct Threads post delete/repost idempotency keys, seeded duplicate replay assertions for worker/retry/reply paths, and legacy `services/autoPostService.ts` queue mutators delegated to idempotent API helpers.
   - Remaining: lower-level helper paths only if future code exposes them outside guarded entry points.
   - Acceptance: duplicate requests and worker retries cannot double-post, double-reply, double-fill, or silently bypass audit.

### Other Important Follow-Ups

- Runtime MCP parity tests against the built local and hosted manifests. Status: Verified for source/runtime registration; built-dist deployment smoke remains part of release checks.
- Seeded 200-account E2E/scale testing. Status: Implemented for v1. A dedicated Playwright `scale` project now uses deterministic route-mocked fixtures to verify Dashboard, Calendar portfolio, Approval Queue, Inbox, Reports, Listening row workflow actions, Ops Health drilldown, and large fleet data without mutating Supabase. Staging smoke scaffolding now exists behind `JUNO33_STAGING_SMOKE=1` and refuses production-looking targets; remaining polish is running it against a real staging project.
- Durable listening scan side-rail polish and direct workflow actions for every row. Status: Implemented for v1. Mention, competitor, trend, keyword, competitor watch, and recent scan rows now expose safe Idea, Reply draft, Note, Handled, Snooze, and Ignore actions where applicable, with source-backed state routed through `/api/operator?action=source-workflow`.
- Reports reliability at 200+ accounts. Status: Implemented for v1. Saved report download/email now uses a shared report scope resolver across Threads and Instagram, removes the legacy 50-account cap, honors account/group/platform scope, fails visibly for unsupported mixed-platform PDFs, surfaces latest `report_send_log` delivery failures in the Reports UI, and gives failed rows a real retry delivery action through the existing reports send handler. Remaining polish: richer exception routing into the operator task queue and multi-platform combined PDF output.
- Production Reliability Center. Status: Implemented for v1. `/api/operator?action=snapshot` now exposes `reliabilitySlo`, `metaApiUsage`, `webhookHealth`, and `tokenSlo`; `/api/reliability?action=slo-summary` returns the read-only drilldown used by the new `/reliability` route. The Dashboard Ops Health tile routes to Reliability Center. Scheduling SLO rollups include on-time rate, success rate, drift percentiles, failed posts, QStash/DLQ counts, backlog, and impacted accounts. Meta API usage headers are captured into `meta_api_usage_snapshots` from Instagram and Threads publish/insight paths. Webhook and token sections surface replay/DLQ and reconnect work through existing recovery screens. Remaining proof: run the guarded staging smoke against a real staging target and wire external alerting if operators want Slack/email paging.
- Granular API key scopes, account allowlists, and step-up/MFA for dangerous overrides. Status: API key account allowlists implemented for v1 public API and developer key metadata; step-up/MFA for dangerous overrides still planned.
- Paginated unhealthy accounts table for token/sync/webhook/account issues. Status: Implemented for account-level token, inactive, and stale sync drilldown in Dashboard Ops Health.
- Strategy experiments with sample-size rules, confidence intervals, holdouts, and rollback.
- Generated MCP/OpenAPI docs for Codex and external automation clients. Status: Implemented for v1. Operator manifest and API reference docs now document action fields, risk, approval, idempotency, dry-run, hosted availability, and rollback/compensation metadata; `npm run docs:check-operator` verifies docs stay aligned with the canonical manifest contract.
- Meta compliance re-check before every API version bump, using official Meta docs only.

## Staging Scale Smoke Runbook

Local and CI scale proof remains route-mocked and non-mutating. Live database
proof is intentionally opt-in and must use a non-production Supabase/Vercel
target only.

Required environment:

```text
JUNO33_STAGING_SMOKE=1
JUNO33_STAGING_SEED=1          # optional; omit for dry-run seed preview
STAGING_SUPABASE_URL=...
STAGING_SUPABASE_SERVICE_ROLE_KEY=...
JUNO33_STAGING_APP_URL=...
```

Command:

```bash
npm run smoke:staging-scale
```

The script refuses production-looking URLs/domains and checks operator snapshot,
Calendar portfolio, Approval Queue, Inbox, Reports, Reliability Center, and Dashboard/Ops Health
against the guarded 200-account fixture. Record latency/RLS notes here after a
real staging project is available.

## Status Legend

- Not Started
- Planned
- In Progress
- Blocked
- Done
- Verified

## P0 Must-Do Work

### P0-01 Hosted MCP safety parity
Status: Verified
Why it matters: Hosted `/api/mcp` must enforce the same dry-run, approval, high-risk lock, rate limit, and logging rules as local MCP.
Files to inspect: `api/mcp.ts`, `mcp-server/src/operatorControlPlane.ts`, `mcp-server/src/index.ts`
Implementation notes: Shared operator control-plane wrapper now exists and hosted MCP imports the generated dist version.
Acceptance criteria: Local and hosted MCP share the same tool list and write safety wrapper.
Verification: `tests/unit/mcp-control-plane.test.ts`; `npm run build`; commit `651e5d689`.

### P0-02 Remove committed MCP API key
Status: Verified
Why it matters: MCP keys grant agent access and must never live in git.
Files to inspect: `.mcp.example.json`, `.gitignore`, `scripts/scan-secrets.mjs`
Implementation notes: `.mcp.json` replaced with `.mcp.example.json`; scanner added. Repo-side cleanup is complete. Rotation runbook: revoke the old key in the MCP/API-key admin surface, create a replacement key only in local env/config, never commit `.mcp.json`, then run `npm run scan:secrets`.
Acceptance criteria: No tracked `juno_ak_` secrets; `.mcp.json` ignored/untracked; scanner catches future `juno_ak_` leaks.
Verification: `npm run scan:secrets` passes. External old-key revocation is an admin action outside this repo and should be confirmed separately.

### P0-03 Exact action approval and immutable intents
Status: Verified
Why it matters: Approvals must bind to the exact future action, not a freeform summary.
Files to inspect: `api/operator.ts`, `api/_lib/operatorHandlerRunner.ts`, `api/_lib/handlers/agent/approvals.ts`, `supabase/migrations/20260522090000_operator_control_plane.sql`
Implementation notes: `agent_action_intents` migration and `/api/operator?action=dry-run|request-approval|execute` foundation added. GET quick approval mutation removed. `request_operator_approval` creates an approval bound to the exact intent id, payload hash, content hash, idempotency key, risk, scope, and normalized payload. Approval execution now claims intents as `dispatching` before side effects and uses `operatorHandlerRunner` to run existing publish, schedule, reschedule, reply, retry-dead-letter, queue-fill, and account resume/clear-cooldown handlers under the approved intent idempotency key. Dispatch failures mark the intent `failed`, persist audit, and create an `operator_dispatch_failed` task.
Acceptance criteria: High-risk actions fail closed without matching unexpired approval intent.
Verification: `tests/unit/mcp-control-plane.test.ts`; `tests/unit/operator-approval-api.test.ts`; targeted checks passed.

### P0-04 Durable manager brain
Status: In Progress
Why it matters: Agent decisions need durable goals, plans, decisions, confidence, risk, expected outcome, and actual outcome.
Files to inspect: `supabase/migrations/20260522090000_operator_control_plane.sql`, `api/operator.ts`, `api/_lib/operatorManagerBrain.ts`
Implementation notes: Manager goals/cycles/plans/items/decisions schema added. `/api/operator?action=snapshot` now includes a `managerBrain` object with active goals, active cycles, active plans with nested active plan items, recent decisions, stale or missing evidence warnings, and manager-specific recommended next actions. Stale cycle evidence now flows into top-level snapshot warnings so Codex/UI callers know when not to trust old evidence.
Acceptance criteria: Operator snapshot exposes active plan state and stale evidence warnings.
Verification: `tests/unit/operator-manager-brain.test.ts`; `tests/unit/mcp-control-plane.test.ts`; combined typecheck/lint/compat/secret/build passed.

### P0-05 Unified operator task queue
Status: Verified for v1
Why it matters: A 200-account operator needs one morning queue for approvals, failures, inbox SLAs, listening spikes, stale sync, token issues, and report failures.
Files to inspect: `supabase/migrations/20260522090000_operator_control_plane.sql`, `api/operator.ts`, `src/hooks/useOperatorSnapshot.ts`, `src/components/dashboard-v2/tiles/OperatorTaskQueueTile.tsx`
Implementation notes: `operator_tasks` schema and list/update API foundation added. Operator snapshot now materializes durable tasks for pending approvals, failed publishes, token reauth/expiry, failed/stale sync jobs, failed/dead-letter webhooks, overdue active reports, unread inbox items, recent listening signals, failed/stale cron runs, QStash/dead-letter queue items, and overdue queue-dispatch backlog without reopening resolved/ignored tasks. Dashboard now shows a scoped Morning Queue across all/group/account views with open, done, approval, failed-publish, token, sync, webhook, report, inbox, listening, QStash/DLQ, queue backlog, and cron recovery actions.
Acceptance criteria: Dashboard shows scoped operator queue and all major systems can create tasks.
Verification: Browser smoke passed on `http://127.0.0.1:3000/dashboard` after login; build/typecheck/lint passed in prior slice. QStash/DLQ source checks now live in `tests/unit/operator-ops-health.test.ts` and seeded scale fixtures.

### P0-06 Authoritative audit/action logs
Status: In Progress
Why it matters: `/api/agent/log` should not rely on self-reported action data.
Implementation notes: `operator_action_audit_logs` now stores server-owned audit rows for operator dry-run, request-approval, and execute phases with actor, scope, hashes, approval/intent/idempotency IDs, outcome, request metadata, message, and error. High/critical execute approval advancement requires audit persistence before the intent is marked approved.
Acceptance criteria: Publish/schedule/approval/unpause/retry/queue-fill fail or route to review when audit persistence fails.
Verification: `tests/unit/operator-audit.test.ts`; combined typecheck/lint/compat/secret/build passed. Broader publish/schedule/retry audit enforcement still needs follow-up.

### P0-07 Hierarchical kill switches
Status: In Progress
Why it matters: Pause must block every outbound path, not just detected agent writes.
Implementation notes: `operator_kill_switches` schema and `checkOperatorKillSwitch` helper added for global, workspace, group, account, session, and API-key scopes with action/risk matching and legacy `profiles.agent_paused` compatibility. `/api/operator?action=execute` now fails closed before approving execution when a matching kill switch is active. A shared outbound guard now records required execute-attempt audit rows before high-risk outbound writes and blocks scheduled publish, QStash queue fill, manual queue-fill dispatch, public reply sends, auto-reply sends, Threads cron fallback publishing, Threads thread-chain publishing, cross-reply publishing, and CTA reply publishing when a matching kill switch is active. Scheduled publish treats kill-switch and required-audit failures as non-retryable.
Acceptance criteria: A "stop all outbound now" switch blocks all write paths.
Verification: `tests/unit/outbound-operator-guard.test.ts`; `tests/unit/operatorKillSwitches.test.ts`; `tests/unit/scheduled-post-publish.test.ts`; `tests/unit/queue-fill.test.ts`; `tests/unit/publishThreads.test.ts`; publish path tests; combined typecheck/lint/compat/secret/build passed. Remaining review: lower-level helper paths that might be reachable outside guarded entry points.

### P0-08 Mandatory AI quality gates
Status: In Progress
Why it matters: Judge/filter failures should not silently auto-publish weak or unsafe content.
Implementation notes: Deterministic AI quality gate added with `pass`, `needs_review`, and `block` decisions plus separate quality, brand, novelty, risk, and expected-outcome confidence fields. Autopilot generated posts carry quality-gate metadata; blocked content is rejected before queue insertion; uncertain or competitor-inspired content routes to `needs_review` and avoids QStash auto-dispatch. Operator dry-runs for publish/schedule/reply/post/autopilot-style content run the same gate, returning `422` for blocked content and escalating uncertain content to approval-required risk. Live provider calls that include `actionLog` now persist eval snapshots through the shared provider router, giving composer, inbox, autopilot, and analytics calls a durable prompt/model/output trace when they use the canonical provider path.
Acceptance criteria: Auto-publish requires successful policy/quality gates or explicit approval.
Verification: `tests/unit/aiQualityGate.test.ts`; `tests/unit/scheduleAndInsert.test.ts`; `tests/unit/aiEvalSnapshots.test.ts`; `tests/unit/aiProviders.test.ts`; combined typecheck/lint/compat/secret/build passed. Remaining work: extend direct AI calls that bypass `generateWithProvider` and add historical score UI/reporting.

### P0-09 Persistent triage state
Status: In Progress
Why it matters: Inbox done state, listening handled state, anomalies, and approvals must be durable.
Implementation notes: Inbox done/back-to-attention now writes through `/api/inbox?action=mark-read`, updates source read flags where available, and resolves/reopens the matching `operator_tasks` row for `inbox_attention` by source identity. `useUnifiedInbox` now reads durable `is_read` flags and hydrates the Inbox workflow state from server truth, with localStorage reduced to a fast cache instead of the only completion record. `/api/operator?action=tasks` now supports status transitions by either task id or `source/source_id`, so durable task resolution/ignore/snooze can be driven from source-specific workflow surfaces. Listening competitor/trend handled, ignored, and snoozed states now write through `/api/operator?action=source-workflow` into durable `operator_tasks`, with localStorage kept only as a fast cache. Dashboard anomaly completion uses the same source workflow endpoint and also updates `anomaly_alerts.dismissed_at`, so completed anomalies stop resurfacing in the feed. Mention signals on the Listening page now mark the underlying Inbox item read through `/api/inbox?action=mark-read`.
Acceptance criteria: No core daily workflow relies on localStorage for completion state.
Verification: `tests/unit/inbox-mark-read.test.ts`; `tests/unit/mcp-control-plane.test.ts`; `npm run typecheck` passed.

### P0-10 AI/autopilot eval harness
Status: In Progress
Why it matters: Avoid AI slop by proving commands, generation, and manager decisions stay useful.
Implementation notes: Deterministic golden eval foundation added with 40 operator/content/safety cases covering scope awareness, ask-human behavior, approval gates, useful next actions, no invented numbers, and compliance checks. `ai_eval_snapshots` schema and `recordAIEvalSnapshot` helper now persist prompt, provider/model/version, parameters, candidates, filter results, judge scores, selected output, inserted/scheduled IDs, later performance snapshot, pass/failure state, and regression score. `generateWithProvider` now records live eval snapshots for canonical provider-router calls that carry `actionLog`, including provider fallback metadata, token usage, redacted prompts, redacted selected outputs, and pass/failure state. `recordDirectAIEvalSnapshot` now covers direct provider paths for AI alt text, vision score, media vision, inspiration idea generation, and trend post generation, with redaction, provider/model metadata, and surface coverage reporting. Operator snapshots now aggregate eval history by suite, surface, and day with suite rows, latest failures, and deterministic pass-rate threshold flags.
Acceptance criteria: Golden eval suite runs in CI and tracks regression score.
Verification: `tests/evals/operator-ai-golden-evals.test.ts`; `tests/unit/aiEvalSnapshots.test.ts`; `tests/unit/aiEvalReporting.test.ts`; `tests/unit/aiProviders.test.ts`; `tests/unit/operator-ops-health.test.ts`; combined targeted eval/control-plane tests passed. Remaining work: backfill evals for older AI action logs if needed.

## P1 Important Work

- Operator manifest/action schema exposed to Codex and UI. Status: Verified for v1. Docs and API reference now expose canonical action metadata, including risk, approval, idempotency, dry-run, availability, and rollback fields; `scripts/check-operator-docs.mjs` guards docs/manifest parity.
- End-to-end idempotency for all high-risk writes. Status: In Progress. Publish, schedule, reschedule, bulk group scheduling, reply sends, post delete/repost, high-risk auto-post queue recovery/config actions, queue-fill receiver dispatch, autopilot queue-fill replay, admin DLQ retry/purge, and active auto-post queue/config frontend mutations now require fail-closed idempotency at direct API entrypoints; MCP and touched UI POST calls attach deterministic idempotency keys. Remaining follow-up: lower-level helper paths, legacy `services/autoPostService.ts` cleanup if still referenced, and seeded worker replay assertions.
- Rollback/compensation metadata. Status: Implemented for v1. The canonical operator action manifest now exposes rollback class, optional compensation action, recovery description, approval requirement, and rollback window. High-risk compensation remains descriptive and still routes through dry-run, exact approval, idempotency, kill-switch, and audit gates.
- Runtime MCP parity tests. Status: Verified. The local MCP runtime now registers through the shared control-plane in tests, hosted module paths are asserted from the canonical manifest, write tools prove injected dry-run/approval controls, default dry-run avoids side effects, and every write tool is covered by the operator action manifest.
- Dashboard morning command queue. Status: Verified for v1. Scoped queue tile is implemented; approval, failed publish, token, sync, webhook, report, inbox, listening, QStash/DLQ, queue backlog, and cron task sources feed it.
- Real Approval Queue UI. Status: In Progress. Exact intent/action preview, filters, deep-linked selection, copyable hashes/IDs, reviewer notes, rejection templates, JSON diffing, edit/resubmit handoff, approval history timeline, and structured editors for common post/reply/queue-fill payloads are now shown.
- Ops Health panel. Status: Verified for v1. Operator snapshot now includes `opsHealth` from cron, webhook, queue/DLQ, sync, token, failed-post, scheduled-publish drift, stuck-publish, and account health signals; Dashboard renders a scoped Ops Health tile with recovery routes plus a paginated unhealthy accounts table and links into `/reliability` for SLO, Meta usage, webhook, and token drilldown.
- Fleet capacity calendar. Status: Implemented for v1. Operator snapshot now includes next-7-day and week-selected fleet capacity from scheduled posts and auto-post queue state, plus detailed account-day matrix rows, group summaries, and deterministic recommendations. Dashboard renders the scoped summary tile; Calendar portfolio view renders the full matrix with gap, conflict, approval, failed, DLQ, compose, approval queue, failed-post, and rebalance routes. Seeded 200-account Playwright scale coverage now exercises the portfolio matrix. Remaining polish: field-level queue-fill/rebalance automation behind exact approvals and real staging database seed smoke.
- Server-side inbox aggregation. Status: In Progress. `/api/inbox?action=unified` now carries account/scope/reply metadata for Threads replies/mentions, Instagram comments/mentions, and cached Instagram DMs. `useUnifiedInbox` uses the authenticated server route as the primary path with legacy client aggregation as fallback while schemas settle.
- Durable listening signals. Status: Verified for v1. Listening competitor/trend/recent scan workflow state persists through operator tasks, and Listening rows expose safe idea, reply draft, competitor note, handled, snooze, and ignore actions.
- Reports reliability for 200+ accounts. Status: Implemented for v1. Failed delivery rows can now retry email delivery directly from Reports using the same authenticated send handler that records `report_send_log`.

## P2 Polish And Scale Work

- Export command palette actions as machine-readable operator actions. Status: Planned.
- Granular public API key scopes and account allowlists. Status: Implemented for v1. Developer API keys now support optional `allowed_account_ids`; public API-key middleware enforces requested account IDs against the allowlist, and public accounts/posts endpoints filter fleet results to the allowed accounts. Broader per-action scopes beyond `read`/`write`/`admin`/`mcp` remain future polish.
- Step-up/MFA for dangerous overrides. Status: Planned.
- Paginated unhealthy accounts table. Status: Implemented for v1. Dashboard Ops Health now lists scoped unhealthy accounts with platform, reason, severity, pagination, and account recovery routes. Remaining polish: a dedicated full-screen account-health drilldown with server cursor pagination if the account list grows beyond the current 200-row snapshot cap.
- Strategy experiments and calibrated learning. Status: Planned.
- Multi-platform intelligence for Threads vs Instagram decisions. Status: Planned.
- Docs alignment and generated MCP/OpenAPI docs. Status: Verified for v1. Operator action manifest docs and API reference describe the `/api/operator?action=manifest` contract, manifest fields, and rollback/compensation classes; `npm run docs:check-operator` verifies docs stay aligned with the canonical contract.
- AI eval historical reporting. Status: Implemented for v1. Operator snapshot now includes a 14-day AI eval summary with pass rate, failure count, live/golden coverage flags, direct-provider surface counts, documented non-generative surface count, suite/surface/day trend rows, suite summaries, latest failures, and deterministic threshold flags; Dashboard renders trend bars, suite rows, and failure context in the AI Evals tile. Remaining work: backfill from old action logs if needed.

## Compliance Verification Notes

The research summary included non-official claims about Meta/Instagram/Threads automation and rate behavior. Before hard-coding enforcement rules, verify against current official Meta developer documentation for:

- Instagram Content Publishing API
- Instagram Messaging API and comment/private reply rules
- Threads API publishing/reply approvals
- Branded Content / Paid Partnership publish parameters
- Like Media and Comments API permissions
- Rate limit and platform policy guidance

Status: In Progress. Baseline official-source note added at `docs/META_COMPLIANCE_VERIFICATION_2026.md`. Hard product policy should use official Meta docs only; non-official numeric claims remain advisory until Meta publishes them.

## Implementation Log

- 2026-05-22 — `651e5d689` — Added operator control-plane foundation, hosted/local MCP parity, secret scanner, approval queue page, operator schema, and snapshot/task/action intent API.
- 2026-05-22 — `77f6207e3` — Added exact intent-to-approval request flow, MCP approval request tool, approval-bound operator task creation, and snapshot task materialization for pending approvals and failed publishes.
- 2026-05-22 — `ef8f5f374` — Added dashboard Morning Queue tile, frontend operator snapshot hook, scoped task filtering, dashboard task resolution, and local-dev fallback while `/api/operator` is not deployed behind the Vite proxy.
- 2026-05-22 — `e2b23d772` — Expanded operator task sources to token reauth/expiry, stale/failed sync jobs, failed/dead-letter webhooks, and overdue reports.
- 2026-05-22 — `269ac748e` — Added inbox, listening, and cron health feeders to the operator morning queue.
- 2026-05-22 — `1efabbb80` — Added operator audit and kill-switch helper/schema foundations alongside the Campaign Factory audio audit workflow.
- 2026-05-22 — `d51b232d9` — Hardened operator execute audit persistence, execute kill-switch enforcement coverage, and deterministic AI/operator golden evals.
- 2026-05-22 — `9b6303dc5` — Added outbound operator guard enforcement, mandatory AI quality gates, and durable Inbox task completion state.
- 2026-05-22 — `038970325` — Added durable listening/trend/competitor/anomaly workflow state through the operator source workflow endpoint.
- 2026-05-22 — `038970325` — Added durable manager brain snapshot assembly with active goals/plans/items/decisions, stale evidence warnings, and manager recommendations.
- 2026-05-22 — `038970325` — Added AI eval snapshot persistence for prompt/model/candidate/filter/judge/regression history.
- 2026-05-22 — `c9e3bbccf` — Advanced the remaining-five slice with Approval Queue filters/deep links/exact preview, server-side unified inbox primary path, Dashboard Fleet Capacity and AI Evals tiles, operator snapshot capacity/eval summaries, and official-source Meta compliance baseline.
- 2026-05-22 — `e28c09257` — Added first approved-action dispatchers for `update_operator_task` and `mark_inbox_message_read`, intent consumption for dispatched actions, unsupported-action manual dispatch fallback, and fixed the MCP inbox tool to call `/api/inbox?action=unified`.
- 2026-05-22 — `a0dad5225` — Extended approved-action dispatch to publish, schedule, reschedule, send reply, retry queue item, trigger queue fill, and account resume/clear-cooldown through existing production handlers with dispatching/failed intent states and recovery tasks.
- 2026-05-22 — `a0dad5225` — Added Approval Queue edit-and-resubmit with payload diffing, rejection templates, revised exact intents, superseded approval closure, and replacement approval tasks.
- 2026-05-22 — `8f8ad133c` — Completed Fleet Calendar Capacity v1 with operator snapshot account-day matrix data, group summaries, deterministic recommendations, and Calendar portfolio matrix actions for gaps, conflicts, failed/DLQ items, and pending approvals.
- 2026-05-22 — `1c7f8b0b7` — Added direct-provider AI eval snapshots and coverage reporting for alt text, vision scoring, media vision, inspiration ideas, and trend post generation.
- 2026-05-22 — `eb5e3c323` — Hardened remaining high-risk replay/recovery writes with fail-closed idempotency and audit coverage for queue-fill receiver, autopilot replay, admin DLQ retry/purge, and direct post delete/repost.
- 2026-05-22 — `2782e71f0` — Moved active auto-post queue/config frontend mutations behind the authenticated `/api/auto-post` control plane with idempotency keys, adding guarded add/reorder queue actions.
- 2026-05-24 — `89fc064d4` — Added runtime MCP parity tests for canonical local/hosted module manifests, shared control-plane registration, write-tool dry-run/approval injection, default dry-run side-effect prevention, and operator action manifest coverage.
- 2026-05-24 — `0bd99df58` — Added v1 rollback/compensation metadata to the canonical operator manifest, documented the operator manifest contract, and exposed the operator manifest shape in OpenAPI/API reference docs.
- 2026-05-24 — `8f7fea446` — Added public API key account allowlists across developer key CRUD, API-key middleware enforcement, public accounts/posts filtering, OpenAPI/API docs, and tracker coverage.
- 2026-05-24 — `350c6d4bb` — Added scoped unhealthy account drilldown to Ops Health with backend account health rows, frontend parsing, Dashboard pagination, and recovery routes.
- 2026-05-24 — `24815b367` — Implemented report reliability v1 with shared report scope resolution, no 50-account cap, explicit mixed-platform failures, latest delivery-log hydration, and Reports UI delivery issue surfacing.
- 2026-05-25 — `0006b60b8` — Added seeded 200-account Playwright scale coverage with deterministic fixtures for Dashboard, Calendar portfolio, Approval Queue, Inbox, Reports, Ops Health, and fixture-shape unit guards.
- 2026-05-25 — `fc410f9c7` — Added Reports failed-delivery retry controls that reuse `/api/reports?action=send`, refresh delivery logs, and keep retry failures visible inline.
- 2026-05-25 — `beadc0109` — Added Approval Queue history timeline for exact intent binding, revisions, reviewer decisions, and dispatch status.
- 2026-05-25 — `42489fc3a` — Added structured Approval Queue editors for common publish, schedule, reschedule, reply, and queue-fill payload fields.
- 2026-05-25 — `2d60de71b` — Finished remaining agent-manager v1 slices with Approval Queue execute/remediation E2E, approval-gated Calendar capacity intents, AI eval trend/threshold reporting, and seeded high-risk idempotency replay assertions.
- 2026-05-25 — `6caa09c1b` — Practical 10/10 polish pass: added opt-in staging 200-account smoke scaffolding, Listening row workflow actions, QStash/DLQ Morning Queue feeders, operator docs parity guard, extended seeded scale coverage, and moved tracker rating to 9.8/10 with local checks passed.
- 2026-05-25 — `6d8a50042` — Added scheduled-publish drift telemetry to Ops Health so staging/prod can prove exact-time posting SLOs from real `scheduled_for` vs `published_at` data.
- 2026-05-25 — `7bffd8b41` — Fixed operator P1 scheduling/scope risks: bulk group scheduling now uses publish preflight, exact dispatch failures are visible per row, queue scope separates group/account IDs, media reads/uploads are workspace-scoped, unified inbox aggregation is chunked/cursor-aware, and legacy batch scheduling preserves exact requested time.
- 2026-05-25 — `5c68588bf` — Fixed service drift and scoped queue backfills: nullable account filtering now preserves NULL rows, post-engagement queue updates verify account/post scope before writing, duplicate media service respects workspace boundaries, and compat now blocks retired root service imports.
- 2026-05-25 — `6dd31176a` — Hardened AI evidence and analytics truth: AI post helpers use bounded server-side published-post queries, Copilot responses record live eval snapshots, group/model analytics cursor through larger post sets with explicit limit metadata, docs parity now checks every canonical manifest action, and analytics empty copy reflects selected scope.
- 2026-05-26 — `23794ca70` — Added Production Reliability Center v1: persisted scheduling SLO and Meta usage telemetry tables, `/api/reliability?action=slo-summary`, snapshot `reliabilitySlo`/`metaApiUsage`/`webhookHealth`/`tokenSlo`, Reliability Center UI, Dashboard Ops Health drilldown, Meta header capture, staging-smoke reliability checks, and seeded 200-account reliability coverage.

## Update Workflow

Every implementation commit touching this roadmap should update this doc:

- Move relevant statuses forward.
- Add commit hash after commit.
- Record verification: build, tests, browser smoke, migration check, or audit.
- Split tasks when a follow-up becomes its own implementation unit.
