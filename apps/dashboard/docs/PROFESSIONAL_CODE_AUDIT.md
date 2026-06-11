# Juno33 Professional Code Standards Audit

Last updated: May 25, 2026

Scope: evidence-based local audit of the current Juno33 codebase. This pass did not make product fixes, refactors, or formatting changes. It only created this audit document.

## Implementation Status

The audit backlog was implemented after this document was written. Keep the
findings below as the original evidence trail, but use this status section for
current state.

Fixed in follow-up commits:

- `7bffd8b41` — Bulk group scheduling now reuses shared publish preflight, enforces the server schedule window, reports exact-time dispatch failures per row, separates auto-post queue group/account scope, workspace-scopes media reads/uploads, chunks/cursors unified inbox aggregation, and preserves exact scheduled time in the legacy batch helper.
- `5c68588bf` — Duplicate service drift was reduced with null-safe account filtering, scoped post-engagement queue backfills, workspace-aware legacy media service behavior, and a compat guard against retired root service imports.
- `6dd31176a` — AI evidence and analytics truth were hardened with bounded server-side published-post queries, live Copilot eval snapshots, cursor-backed group/model analytics post reads with explicit limit metadata, exhaustive operator manifest docs parity, and more scope-aware analytics copy.
- `6836538fb` — P3 guardrails were added: touched API analytics routes use the local Zod shim, new direct API Zod imports are blocked against a baseline, stale legacy comments were converted to deprecation/tracker notes, and the staging-scale smoke runbook was recorded.

Current status:

- P0: none found.
- P1: fixed in code and covered by targeted tests/build.
- P2: fixed where practical locally; real staging-scale database verification remains a manual follow-up because staging Supabase/Vercel env vars are not configured in this workspace.
- P3: guardrails/docs are in place; remaining work is future cleanup as files naturally change.

Latest verification after fixes:

- `npm run typecheck`
- `npm run lint`
- `npm run compat:check`
- `npm run docs:check-operator`
- `npm run scan:secrets`
- targeted Vitest suite: 7 files, 122 tests
- `npm run test:e2e:scale`: 6 passed
- `npm run build`

## Executive Summary

Current professional code posture: **8.6/10**.

Juno33 is in strong shape around the highest-risk operator flows. The publish/schedule control plane, exact approvals, idempotency tests, operator snapshot, Ops Health, seeded 200-account E2E coverage, secret scanning, production readiness scripts, and build pipeline are all materially better than a normal early SaaS codebase.

No P0 production-blocking issue was found in this audit. The main risks are not “the app is broken”; they are codebase maturity risks: duplicate legacy service trees drifting from the active implementations, a few workspace-scoping gaps, legacy scheduling helpers that no longer match the exact-time standard, and AI/analytics paths that can still overfetch at 200-account scale.

Strongest areas:

- Operator control plane: exact approval, dry-run, audit, idempotency, kill-switch, and seeded scale tests are present and verified.
- Scheduling/publishing reliability: the current production path has preflight, queue fallback, retry/DLQ, drift telemetry, cron checks, and build-time coverage.
- Security baseline: secret scan, production readiness audit, security audit, Supabase readiness audit, and operator docs parity all passed.
- Frontend operator surfaces: dashboard, calendar portfolio, approval queue, inbox, listening, and reports have route-mocked 200-account E2E coverage.

Riskiest areas:

- Bulk group scheduling does not yet match the hardened single-post schedule path.
- Duplicate `services/` and `src/services/` implementations can drift and reintroduce old bugs.
- Media library rows are still inserted/read by `user_id` without workspace scoping.
- Legacy batch scheduling helper silently changes scheduled times for multi-account scheduled posts if it is still called.
- Unified inbox aggregation still uses large source fetches and in-memory pagination.
- Several AI helper paths read all posts with `"ALL"` and then filter in memory, which is not the right shape for 200-account command workflows.
- Route-mocked scale tests are strong, but the opt-in staging smoke still needs a real staging Supabase configuration before this can be called production-proven at fleet scale.

## Verification Results

All requested non-mutating verification commands that were run in this audit passed:

| Command | Result | Notes |
| --- | --- | --- |
| `npm run scan:secrets` | Passed | No scanner hits. |
| `npm run audit:prod` | Passed | Reported production wiring audit passed with 24 cron routes and 26 env docs. |
| `npm run audit:security` | Passed | API security surface audit passed. |
| `npm run audit:supabase` | Passed | Supabase readiness audit passed with 21 tables and 4 buckets. |
| `npm run compat:check` | Passed | Lazy imports/routes resolved. |
| `npm run typecheck` | Passed | Exited successfully. |
| `npm run lint` | Passed | Checked 1400 files; no fixes applied. |
| `npm run docs:check-operator` | Passed | Operator docs/manifest check passed. |
| `npx vitest run tests/unit/operator-approval-api.test.ts tests/unit/operator-ops-health.test.ts tests/unit/outbound-operator-guard.test.ts` | Passed | 3 files, 16 tests. |
| `npm run test:e2e:scale` | Passed | 6 seeded 200-account Playwright tests. |
| `npm run build` | Passed | MCP server build, Vite production build, and service worker build completed. |

## P0 Findings

No P0 findings were proven in this pass.

## P1 Findings

### 1. Bulk Group Scheduling Does Not Reuse Full Publish/Schedule Preflight

Severity: P1

Reference:

- `api/_lib/handlers/posts/bulkScheduleGroups.ts:246-252`
- `api/_lib/handlers/posts/bulkScheduleGroups.ts:471-476`
- `api/_lib/handlers/posts/schedule.ts:311`

Evidence:

The bulk group scheduler validates basic ownership and whether `scheduledFor` is a future date. It stores optional publishing metadata, but the file does not call `runPublishPreflight`. The normal schedule handler does call the shared publish preflight path before inserting the scheduled post.

Why it matters:

Bulk scheduling is exactly where 200-account operators will depend on the system most. If the bulk path accepts posts that the normal schedule path would reject, bad Reels, Trial Reels, branded-content fields, inaccessible media URLs, caption/platform issues, token health problems, or account-state failures can enter the queue and fail later at publish time.

Recommended fix:

Run the same `runPublishPreflight` path used by `handleSchedule` for each bulk-generated post before insert. Return per-row validation failures with actionable copy so one bad group/account does not hide the status of the rest of the batch.

Verification needed:

- Unit/API tests where bulk group schedule rejects the same invalid payloads as normal schedule.
- Fixture covering Reel/Trial Reel, partnership fields, media URL accessibility, caption limits, token health, and inactive account state.
- Browser test showing per-row bulk schedule failures are readable.

Confidence: proven.

### 2. Bulk Group Scheduling Can Silently Fall Back From Exact-Time Dispatch

Severity: P1

Reference:

- `api/_lib/handlers/posts/bulkScheduleGroups.ts:551-559`
- `api/_lib/handlers/posts/schedule.ts:723-744`

Evidence:

The bulk group scheduler attempts `dispatchPostPublish(newPostId, scheduledDate)`, but catches and ignores failures as non-critical cron fallback. The normal schedule path treats missing QStash dispatch as a 503 and saves the post back as a draft with an explicit error.

Why it matters:

The current exact-time standard is “QStash first, cron as fallback,” but bulk scheduling should not silently downgrade exact-time guarantees for a 200-account batch. Operators need to know which posts are exact-dispatch scheduled and which need attention.

Recommended fix:

Make QStash dispatch status explicit per row. Either fail/draft affected rows when exact dispatch is unavailable, or return `exactDispatchScheduled: false` with a recovery task and visible operator warning.

Verification needed:

- Unit test simulating QStash dispatch failure in bulk schedule.
- API response assertion for per-row exact-dispatch status.
- Morning Queue/Ops Health task creation for affected bulk rows.

Confidence: proven.

### 3. Auto-Post Queue Writes And Reads Confuse Group And Account Scope

Severity: P1

Reference:

- `api/_lib/handlers/auto-post/route/queueHandlers.ts:181-190`
- `supabase/schema.sql:514-520`
- `src/services/autoPost/queue.ts:43-54`
- `services/autoPostService.ts:748-758`

Evidence:

Manual queue insertion writes both `group_id: groupId` and `account_id: groupId`. The schema comment says `account_id` is nullable and assigned at post time. Queue reads then map `groupId: row.account_id || undefined` in both modular and legacy services.

Why it matters:

Queue rows can carry a group ID in an account ID column, then expose that same value as `groupId`. That can confuse account-scoped queue health, media selection, capacity recommendations, and recovery logic. For fleet operators, wrong scope is worse than a missing recommendation because it can send work to the wrong account/group workflow.

Recommended fix:

Separate `accountId` and `groupId` in the queue item type and row mapping. Insert `account_id` only when a real account is selected; otherwise leave it null. Add a cleanup or compatibility guard for existing rows where `account_id` contains a group ID.

Verification needed:

- Unit test for manual queue insertion with group-only, account-only, and mixed fixtures.
- Unit test for `getAutoQueue()` row mapping.
- Calendar portfolio queue-fill dry-run test proving the intent scope matches the displayed group/account.

Confidence: proven.

### 4. Media Library Is Not Workspace-Scoped

Severity: P1

Reference:

- `src/services/mediaService.ts:115-120`
- `src/services/mediaService.ts:377-389`
- `services/mediaService.ts:279-291`

Evidence:

- `getAllMedia()` selects media by `user_id` only, with no workspace filter.
- `recordMediaUpload()` inserts `workspace_id: null`.
- The root `services/mediaService.ts` duplicate has the same `workspace_id: null` behavior.

Why it matters:

Juno33 is a multi-account and workspace-oriented social ops app. A media library that is only user-scoped can blur assets across workspaces, groups, or clients. This is especially risky for 200-account operators because wrong-client media is an operator trust failure even if RLS prevents cross-user leakage.

Recommended fix:

Thread workspace ID through upload, library reads, random media selection, assignment, and Composer/content-library upload surfaces. Make new media rows workspace-scoped, keep a migration/backfill plan for legacy `workspace_id IS NULL`, and update tests to prove workspace A cannot see workspace B media for the same user.

Verification needed:

- Unit tests for upload/read filtering by workspace.
- Browser smoke for Content Library and Composer media picker under two workspace contexts.
- Supabase RLS/policy check for `media.workspace_id`.

Confidence: proven.

### 5. Unified Inbox Aggregation Will Strain At 200 Accounts

Severity: P1

Reference:

- `api/_lib/handlers/inbox/unified.ts:79-90`
- `api/_lib/handlers/inbox/unified.ts:141-149`
- `api/_lib/handlers/inbox/unified.ts:436-444`

Evidence:

The unified inbox handler fetches account/post context, uses a potentially large `.in("post_id", postIds)` query for replies, then globally sorts and paginates messages in memory.

Why it matters:

At 200 accounts, a large `postIds` list can hit query/URL limits or slow inbox loads. In-memory pagination also means each source can be partially fetched before global sorting, which can make the returned page inaccurate under high volume.

Recommended fix:

Move toward durable/server-side inbox rows or cursor-per-source aggregation. Avoid giant `.in()` lists by materializing inbound conversation references, querying by account/source, or using an RPC that handles filtering/pagination in Postgres.

Verification needed:

- Seeded fixture test with thousands of posts/comments across 200 accounts.
- Query latency notes from staging-scale smoke.
- Cursor correctness test where a high-volume source does not starve another source.

Confidence: proven code shape, likely scale impact.

### 6. Legacy Batch Scheduling Helper Can Mutate Exact Scheduled Times

Severity: P1 if still reachable from active workflows; P2 if confirmed legacy-only.

Reference:

- `services/dataService.ts:303-336`

Evidence:

`batchCreatePosts()` staggers scheduled posts by `index * 3` minutes:

- Scheduled/Draft posts are created in a multi-account batch.
- For `PostStatus.SCHEDULED`, every account after index 0 gets a later `scheduledDate`.

Why it matters:

Recent scheduling work moved the app toward a 2026-grade exact-time standard: schedule preflight, QStash exact dispatch, cron fallback, idempotency, drift telemetry, and user-visible schedule truth. This legacy helper violates that standard if any UI or service path still calls it, because a user scheduling 200 accounts for 9:00 AM could silently create 9:00, 9:03, 9:06, etc.

Recommended fix:

Confirm whether `batchCreatePosts()` is active. If active, remove silent staggering for scheduled posts and rely on queue dispatch/rate-limit controls. If inactive, delete or quarantine it behind a legacy-only guard so future imports cannot bypass the modern schedule API.

Verification needed:

- Static import guard proving new UI/API code cannot call the legacy helper.
- Unit test proving multi-account scheduled posts preserve the exact requested time.
- E2E Composer schedule test with multiple accounts.

Confidence: likely.

## P2 Findings

### 7. Duplicate Service Trees Are Drifting

Severity: P2

Reference:

- `services/api/accounts.ts:395-397`
- `src/services/api/accounts.ts:403-405`
- `services/autoPostService.ts`
- `src/services/autoPost/*`

Evidence:

The active `src/services/api/accounts.ts` uses `neqOrNull(query, "status", "suspended")`, which preserves rows where `status` is NULL. The root `services/api/accounts.ts` duplicate still uses `.neq("status", "suspended")`, which drops NULL rows in Supabase/PostgREST semantics.

The auto-post implementation also exists in both a large legacy file and modular `src/services/autoPost/*` files, and both currently share queue scope mapping concerns.

Why it matters:

Duplicate service trees create “fixed in one place, broken in another” risk. Even if the root service is mostly legacy today, tests and server-side AI helpers still import from `services/` in places. A future import can bypass newer null-safe, idempotent, or scoped code without looking suspicious.

Recommended fix:

Pick one canonical service tree per domain. Add import guards or lint rules that prevent new code from importing retired services. For files that must remain during migration, add narrow parity tests around known-risk helpers: nullable account status, queue mapping, media workspace scoping, and idempotent mutations.

Verification needed:

- Static import guard for retired service modules.
- Tests proving root and src behavior match where both must exist.
- Removal plan for unused legacy services.

Confidence: proven drift, likely future risk.

### 8. AI Helper Paths Overfetch Posts With `"ALL"`

Severity: P2

Reference:

- `services/ai/voice.ts:138-148`
- `services/ai/competitor.ts:274-284`
- `services/ai/growth.ts:793-799`
- `services/dataService.ts:1288-1294`

Evidence:

Several AI helpers call `dataService.getPosts("ALL")` and then filter in memory for style extraction, competitor/style matching, best-time analysis, and group stats.

Why it matters:

The command/agent system needs fast, scoped, evidence-backed answers. Pulling all posts and filtering client/service-side is tolerable for small workspaces but becomes slow, expensive, and noisy at 200 accounts. It also risks mixing scope when the user is asking about a selected group or individual account.

Recommended fix:

Replace `"ALL"` post pulls in AI helpers with scoped aggregate endpoints or query helpers that accept account/group/workspace scope, date range, status, and limit. Prefer operator snapshot summaries for command answers, and fetch raw posts only when the user asks for examples.

Verification needed:

- Unit tests for AI scope awareness across all/group/account.
- Performance test or fixture-backed regression proving helpers do not fetch unbounded posts.
- Golden eval prompts that require the command system to admit when scoped evidence is missing.

Confidence: proven code shape, likely scale impact.

### 9. Streamed Copilot Path Does Not Appear To Record The Same Eval Snapshot Trail

Severity: P2

Reference:

- `api/_lib/handlers/ai/copilot.ts:481-515`
- `api/_lib/handlers/ai/copilot.ts:529-534`

Evidence:

The streamed Gemini path tracks token cost, stores extracted memory, caches the response, sends the SSE completion, and returns. The non-stream path continues through `generateWithProvider(...)`, where provider calls are wired through the normal provider/action-log path.

Why it matters:

The command surface is one of the most important agent-manager entry points. If streamed usage is not captured in the same eval/action-log trail, quality trends, hallucination analysis, and operator usefulness metrics can undercount real command usage.

Recommended fix:

After streamed completion, record the same eval snapshot/action metadata that non-stream provider calls record: prompt/model/provider/version, data used, candidate text, confidence/judge summary where available, and surface.

Verification needed:

- Unit test for streamed Copilot response creating an eval/action snapshot.
- Dashboard AI eval trend fixture that includes streamed and non-stream command usage.

Confidence: likely based on current control flow.

### 10. Analytics Queries Have Hard Row Caps That Can Undercount Large Groups

Severity: P2

Reference:

- `api/_lib/handlers/analytics-sub/group-analytics.ts:128-148`
- `api/_lib/handlers/analytics-sub/model-comparison.ts:138-158`

Evidence:

Group analytics limits each platform query to 500 rows. Model comparison limits each platform query to 2000 rows.

Why it matters:

For high-volume 200-account workspaces, these caps can silently undercount posts in a selected group or date window. Analytics widgets may look clean while being based on only the latest slice of data.

Recommended fix:

Use aggregate SQL/RPC for totals and distributions, or cursor through all rows by account/date when raw posts are required. Expose `sampled` or `limited` metadata if a hard cap remains.

Verification needed:

- Unit/API test with more than 500 group posts and more than 2000 model comparison posts.
- Widget copy/metadata that surfaces sampling if full aggregation is not available.

Confidence: likely.

### 11. Post-Engagement Sync Updates Queue Rows By Metadata ID Only

Severity: P2

Reference:

- `api/_lib/handlers/sync/post-engagement.ts:116-129`

Evidence:

When `post.metadata.autoPostQueueId` is present, the QStash-signed post-engagement sync updates `auto_post_queue` with `.eq("id", metadata.autoPostQueueId)` only.

Why it matters:

This is not externally exposed in the normal way because the route is QStash-signed, but corrupted or stale metadata could update the wrong queue row. Queue health and engagement feedback loops are more trustworthy when updates are constrained by workspace/account/post ownership context too.

Recommended fix:

Add owner-derived constraints to the queue update, such as `workspace_id`, `account_id`, `group_id`, or linked `post_id`, depending on the available row contract.

Verification needed:

- Unit test where a mismatched queue ID does not update.
- Audit log or warning when metadata points to a row outside the expected scope.

Confidence: likely.

### 12. Operator Docs Parity Guard Is Representative, Not Exhaustive

Severity: P2

Reference:

- `scripts/check-operator-docs.mjs:44-54`

Evidence:

The script checks required phrases and a representative action list: `publish_post`, `schedule_post`, `reschedule_post`, `send_reply`, `trigger_queue_fill`, and `override_account_state`.

Why it matters:

The canonical manifest can grow faster than the docs. A new high-risk hosted write action could be added without being reflected in generated operator documentation if it is not in the representative list.

Recommended fix:

Generate docs directly from the canonical manifest or require every hosted/high-risk/write action to appear in `docs/OPERATOR_ACTION_MANIFEST.md` and `docs/API_REFERENCE.md`.

Verification needed:

- Static test comparing every manifest action to documented action sections.
- Snapshot test for generated operator docs.

Confidence: proven.

### 13. Staging-Scale Proof Exists As Scaffolding, Not As Completed Environment Verification

Severity: P2

Reference:

- `scripts/staging-scale-smoke.ts`
- `package.json` script `smoke:staging-scale`
- `e2e/scale-200.spec.ts`

Evidence:

The route-mocked 200-account E2E suite passes and is safe for local/CI. The opt-in staging smoke exists, but no staging Supabase environment was configured during this audit, so live staging verification was not run.

Why it matters:

Route-mocked scale tests prove UI/data-flow behavior. They do not prove real database latency, RLS shape, indexes, storage policies, QStash delivery, or webhook backlog behavior under a seeded staging workspace.

Recommended fix:

Provision a non-production Supabase/Vercel staging target and run the guarded staging smoke periodically. Keep production mutation blocked by the existing staging flag and URL guard.

Verification needed:

- Successful `JUNO33_STAGING_SMOKE=1 npm run smoke:staging-scale` against staging env only.
- Snapshot, Calendar portfolio, Approval Queue, Inbox, Reports, and Ops Health smoke on seeded staging data.
- Query latency notes for dashboard/operator snapshot under 200-account seed.

Confidence: proven verification gap.

## P3 Findings

### 14. Legacy Comments And API Names Still Reflect Older Architecture

Severity: P3

Reference:

- `services/dataService.ts:303-304`
- `src/services/mediaService.ts:379`
- `services/mediaService.ts:281`

Evidence:

Comments like “PORTED FROM OLD REPO” and TODOs about future workspace context remain in files that are still near active code paths.

Why it matters:

This is not a production bug by itself, but stale comments make it harder to tell which paths are authoritative. That slows audits and increases the chance that future work patches the wrong implementation.

Recommended fix:

As part of the duplicate-service cleanup, either delete legacy-only code or mark it with an explicit `@deprecated` comment and a replacement module path. Turn TODOs with real product risk into tracker items or tests.

Verification needed:

- Import guard for deprecated modules.
- Tracker entries for any retained TODO with operator risk.

Confidence: proven.

### 15. API Zod Import Convention Is Not Fully Enforced

Severity: P3

Reference:

- `api/auth/disconnect.ts:20`
- `api/_lib/handlers/posts/bulkScheduleGroups.ts:28`
- `api/_lib/zodCompat.ts:12-26`

Evidence:

Project guidance says API routes should import from the local compatibility layer, but direct `zod` imports still exist in API files. The compatibility file itself explains the shim exists to smooth API runtime/schema differences.

Why it matters:

Current typecheck and build pass, so this is not an immediate bug. The risk is future Vercel/runtime regression or inconsistent schema behavior as API routes evolve.

Recommended fix:

Add a compat lint rule for runtime API schemas or migrate direct API route imports to the shim where appropriate. Exempt the compatibility module itself and any build-time-only scripts.

Verification needed:

- `npm run compat:check` catches new direct API route imports if the convention remains required.
- Build passes after any migration.

Confidence: proven convention drift.

## Do Not Fix

- Do not replace the current QStash + cron fallback publishing architecture just because a queue abstraction could be “cleaner.” The current shape is defensible and verified.
- Do not add MFA/step-up gates as a top priority right now. It is useful later, but it is not the practical bottleneck for day-to-day operator safety.
- Do not rewrite every service into one grand abstraction. Fix the concrete duplicate-service drift first.
- Do not churn analytics/dashboard visuals unless a widget is misleading, unscoped, broken, or materially slow.
- Do not encode Meta policy claims from secondary research unless they have been verified against official Meta docs.

## Implementation Batches

### Batch 1: Highest-Risk Quick Wins

1. Make bulk group scheduling use the same preflight and exact-dispatch failure behavior as normal scheduling.
2. Fix auto-post queue write/read scope mapping so account ID and group ID are distinct.
3. Fix media workspace scoping for upload, read, assignment, and random media selection.
4. Harden unified inbox aggregation with server-side cursor/source pagination.
5. Confirm whether `batchCreatePosts()` is reachable; remove or harden it so scheduled posts keep exact user-selected times.

### Batch 2: Reliability And Data Truth

1. Consolidate duplicate `services/` and `src/services/` implementations or add import guards around retired modules.
2. Add parity tests for nullable Supabase filters, media workspace filtering, and queue scope mapping.
3. Add Composer/Calendar regression tests for multi-account exact scheduled time preservation.
4. Constrain post-engagement queue updates by workspace/account/post scope.

### Batch 3: Scale And AI Hardening

1. Replace AI `getPosts("ALL")` helpers with scoped aggregate queries.
2. Add streamed Copilot eval/action snapshots.
3. Replace large analytics row caps with aggregate/cursor-backed queries or visible sampling metadata.
4. Make operator docs parity exhaustive against the canonical manifest.
5. Add performance assertions around operator snapshot and AI command context at 200-account fixture size.
6. Expand golden evals for scope-aware commands and “missing evidence” behavior.

### Batch 4: Production Verification Polish

1. Configure a guarded staging Supabase/Vercel environment.
2. Run the staging-scale smoke against seeded non-production data.
3. Record staging latency and RLS verification notes in the agent-manager tracker.
