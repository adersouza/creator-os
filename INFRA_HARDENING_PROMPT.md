# Infra Hardening Prompt — take the seam + crons + backend + schema to 9–10

**Audience:** Codex + owner. **Source of findings:** `INFRA_LIFECYCLE_AUDIT.md` (read it first — every PR below cites a finding there). **Goal:** lift the four infra domains from ~7.0 to 9–10 with bounded, low-risk PRs. No architecture changes are required — these are guard-rails, indexes, and schedules.

**Two repos:**
- **creator-os** (`main` protected; feature branch → PR; CI: contracts/architecture/hygiene/secret-scan/scorecard/CodeQL/python/javascript/sbom; `pnpm check:contracts` green after any schema change).
- **ThreadsDashboard** (`main`; feature branch → PR; never push `main`; each PR adds the test that proves it).

**Non-negotiables (carry from the existing tracks):**
- One logical change per PR; each adds the test/migration that proves it.
- **As each track lands, flip the matching finding in `infra_lifecycle_map.html`** (its own standalone dashboard — same flip-the-roadmap contract as `creator_os_map.html`/`autoposter_map.html`, but a separate file). Each finding card carries its track ID (A1…D6). Otherwise the map goes stale on the first merge.
- Quality/safety floor only goes **up**. The media-reuse override TTL and distinctness guards are *detect-and-respect* hardening — never weaken them.
- DB changes: `CREATE INDEX CONCURRENTLY` / `CREATE UNIQUE INDEX CONCURRENTLY` only (no table locks on prod); additive migrations; regenerate `src/types/supabase.ts`.
- Schema-shape changes that cross the repo boundary → new **versioned** contract, `pnpm check:contracts` green.
- The two `[verify]` findings (IG-webhook fallback, IG-container TTL) must be **traced and confirmed before** their fix PR — if already safe, the PR is just a regression test + comment.

---

## Current execution notes (2026-06-19)

- **Current TD infra PR ledger, refreshed from GitHub on 2026-06-19:**
  - MERGED to TD `main`: TD #131 A1 idempotent ingest, #132 A3 media ingest boundary, #133 C1 cross-reply retry, #134 C2 posts max duration, #135 D1 posts index diet, #136 D1 post-metric-history index diet, #137 C3 IG webhook fallback rejection, #138 C4 IG container TTL, #139 C5 media reuse override token, #140 C5 token refresh hygiene, #141 C6 Threads error taxonomy, #142 B1 publish-worker v2 filter, #143 B2 watchdog recovery cap, #144 B3 overdue IG redispatch, #145 B4 reconcile-daily cursor, #146 D2 FK indexes, #147 D3 campaign-factory indexes, #148 D4 posts lease retry, #149 D6 default-deny RLS docs, #150 B5 AI spend cap pause, #151 D5 replay missing live tables, #152 D3 scheduler indexes, #153 D3 meta usage index, #154 D3 competitor indexes, #155 D3 account-DNA indexes, #156 D3 AI eval indexes, #157 D3 operator audit indexes, #158 D3 audit log index, #159 pipeline-contract snapshot sync, #160 D3 autoposter performance facts indexes, #161 D3 ai_action_log indexes, #162 D3 autoposter account-hour performance index, #163 D3 account-autoposter-state indexes, #164 D3 Instagram metric availability index, #165 D3 post originality hash indexes, #166 D3 publish attempts indexes, #167 D3 media indexes, #168 D3 mentions indexes, #169 D3 post-template recent-usage index, #170 D3 proof-runs helper indexes, #171 D3 creator identity shape usage helper indexes, #172 D3 data deletion request duplicate index, #173 D3 post-tags user helper index, #174 D3 auto-self-replies scope helper indexes, #175 D3 auto-cross-replies scope helper indexes, #176 D3 sent-replies redundant account index, #177 pipeline-contract runtime import packaging, #178 D3 share-of-voice history index, #179 D3 account uniqueness metric indexes, and #180 D3 winner pattern clone-family index.
  - OPEN TD infra PRs at refresh time: none.
  - Vercel preview `PENDING`/`UNSTABLE` on merged PRs was not treated as a code failure by itself; local gates were run before merge.
- **D3 is in progress, not complete.** Do not duplicate the table-family batches already opened:
  - TD #147: `campaign_factory_*` zero-scan index batch.
  - TD #152: `scheduler_decisions` zero-scan account/run indexes; preserves the active `created_at`, BRIN retention, workspace, and group indexes.
  - TD #153: `meta_api_usage_snapshots` zero-scan account/captured index; preserves the active user/captured Reliability Center index.
  - TD #154: `competitor_top_posts` zero-scan pattern/enrichment indexes; preserves active competitor, engagement, recent-window, pattern, metric-quality, unique, and primary-key indexes.
  - TD #155: `account_dna*` zero-scan voice-embedding, creator-DNA, example, and account-rule indexes; preserves active workspace/group, active-account, rule-scope, primary-key, and creator-DNA table indexes.
  - TD #156: `ai_eval_snapshots` zero-scan prompt-hash and user-suite indexes; preserves the active scope index and primary key.
  - TD #157: `operator_action_audit_logs` zero-scan user-created, intent, phase/outcome, and scope indexes; preserves the primary key and insert/select-id audit behavior.
  - TD #158: `audit_logs` zero-scan reconciled `user_id` index; preserves the primary key, audit inserts, cleanup RPC, export coverage, and user-deletion cascade behavior.
  - TD #160: `autoposter_post_performance_facts` zero-scan posting-hour, question-subtype, clone-family, and quality-gate-lane indexes; preserves the active primary key, account, group, workspace/published, and pattern read paths.
  - TD #161: `ai_action_log` zero-scan account/provider indexes; preserves the primary key, active surface index, and user-scoped GDPR export/deletion index.
  - TD #162: `autoposter_account_hour_performance` zero-scan confidence index; preserves the active primary key and workspace/group/account weighted-score timing index.
  - TD #163: `account_autoposter_state` zero-scan blocked-until and group-health indexes; preserves the active primary key, group, status, workspace, and restart-warmup indexes.
  - TD #164: `instagram_metric_availability_events` zero-scan `missing_metrics` GIN index; preserves the primary key plus account/media/post/user synced indexes for ownership, FK, and time-window paths.
  - TD #165: `post_originality_signals` zero-scan media/perceptual hash GIN indexes; preserves the active `post_id` key, primary key, user/recent duplicate-safety path, and account/Instagram-account paths.
  - TD #166: `publish_attempts` zero-scan queue-item, claim-token, and Threads-post-id indexes; preserves active account/result/workspace reporting indexes, the primary key, and the unique queue-attempt path.
  - TD #167: `media` zero-scan user/group, user/folder, account-assignment, and spotlight helper indexes; preserves active user/last-used, workspace, group, folder, user, primary-key, and storage-path unique paths.
  - TD #168: `mentions` zero-scan unread helper indexes; preserves active user lookup, account lookup, unique Threads post upsert, and primary-key paths.
  - TD #169: `post_templates` zero-scan recent-usage helper index; preserves primary key, active user lookup, account-group lookup, and workspace/FK support indexes.
  - TD #170: `proof_runs` zero-scan user/asset, user/status, and distribution-plan helper indexes; preserves primary key and D2 FK support indexes for `threadsdash_draft_id` / `threadsdash_post_id`.
  - TD #171: `creator_identity_shape_usage` zero-scan recent-shape helper indexes; preserves primary key and D2 FK support index for `creator_dna_id`.
  - TD #172: `data_deletion_requests` zero-scan duplicate `confirmation_code` helper index; preserves the unique confirmation-code constraint index and privacy workflow helper indexes.
  - TD #173: `post_tags` zero-scan `user_id` helper index; preserves active `post_id` lookup, composite `user_id/tag_name` lookup, primary key, and post/tag/user uniqueness constraint.
  - TD #174: `auto_self_replies` zero-scan `account_id` and `workspace_id` helper indexes; preserves active pending/post paths, user/group paths, primary key, and post/reply uniqueness.
  - TD #175: `auto_cross_replies` zero-scan `parent_reply_id` and `workspace_id` helper indexes; preserves active pending/user/group paths, primary key, and target/replier/chain uniqueness.
  - TD #176: `sent_replies` zero-scan redundant `account_id` helper index; preserves the covering `(account_id, created_at DESC)` rate-limit index plus the `user_id` FK/export index.
  - TD #178: `share_of_voice_history` zero-scan redundant `(account_id, date)` helper index; preserves the active unique `(user_id, account_id, date)` upsert index plus the primary key.
  - TD #179: `account_uniqueness_metrics` zero-scan speculative latest/group helper indexes; preserves the primary key and check constraints.
  - TD #180: `autoposter_winner_patterns` zero-scan clone-family helper index; preserves the active workspace/group/confidence index, source unique upsert/lookup index, primary key, and `source_post_id` FK.
- Continue D3 one table family per PR, gated on live `pg_stat_user_indexes.idx_scan = 0` over the stated stats window and a code-path check proving the dropped index is not the active access path.
- Keep `infra_lifecycle_map.html` in sync with each new D3 batch; the map should say batched/in-progress until the broader unused-index backlog is actually closed.

---

## Track A — Cross-repo seam (6.5 → 9.5). The ⭐ priority; mostly TD, one creator-os PR. Do A1 first.

**A1 — Make the boundary idempotent (closes AUDIT §1 HIGH-3 + the downgraded HIGH-2).**
- TD migration: `CREATE UNIQUE INDEX CONCURRENTLY` on `posts (campaign_factory_post_key) WHERE campaign_factory_post_key IS NOT NULL`. (Live check: 0 current duplicates, so this builds clean.)
- TD `draftIngest.ts`: catch the unique-violation and treat it as the "already ingested" branch (return the existing post id, action `"noop"`), not a 500.
- creator-os `threadsdash.py`: send an `X-Idempotency-Key` header (the `campaign_factory_post_key` or export id); TD short-circuits on a key it has already written.
- Tests: concurrent double-POST inserts exactly one row; retried POST returns the same id.

**A2 — Reconcile the export, kill the silent success (AUDIT §1 HIGH-3).**
- creator-os: after `_post_threadsdash_draft_ingest`, treat **empty `postIds` on 2xx** the same as an HTTP error — a retriable failure, not "exported". Before marking the export done, read back post count by key and assert it crossed.
- Add a retry-with-backoff around the POST (now safe because A1 made it idempotent); replace the bare `urlopen(timeout=30)` with bounded retries.
- Test: simulate TD validate-pass/write-fail → export is marked failed, not exported.

**A3 — Assert media URLs at the boundary (AUDIT §1 HIGH-1).**
- creator-os: pre-POST validation rejects any draft whose media items lack a resolved **remote** URL (the legacy `_write_supabase` hydration no longer runs on the HTTP path — stop depending on it).
- TD `draftIngest.ts`: reject (4xx) a draft that would insert with empty `media_urls`.
- Test: a draft with `media.url = None` and no remote manifest URL is rejected on both sides.

**A4 — Schedule + contract the backward metric sync (AUDIT §1 MED).**
- Either schedule `campaign-factory sync-performance` (cron/queue) **or** add a TD cron that pushes `performance_sync.v1` — pick one owner for the return leg.
- Version a `post_metric_history.read.v1` contract and validate the read shape in `_select_threadsdash_post_metric_history` so a TD column rename fails loudly, not as silent NULLs.
- Validate `performance_sync.v1` on **write** in production code (today only tests do).
- Test: renamed/absent source column → hard error; scheduled run closes the loop without manual call.

**A5 — Codegen the seam validators (AUDIT §1 MED; same as TRACK9 PR-1).**
- Generate the Python + TS draft-ingest validators from the canonical schema; fold TD's 10 hand-rolled checks (handoff-manifest-v2, visual_qc, identity_verification, schedule_safe, caption) into the schema where they're structural, or document them as a named TD-only policy layer.
- CI byte-sync check across the 5+ vendored schema copies. **This is the durable fix for seam drift** — if TRACK9 PR-1 lands first, this PR is just the seam-specific wiring.

---

## Track B — Crons (7.5 → 9.5). All TD. Independent, parallelizable.

**B1 — Stop the publish-worker/scheduler overlap (AUDIT §2 HIGH→mitigated).** Filter publish-worker Phases 3–4 to `scheduler_version < 2`, matching `dawn-planner`/`account-state-evaluator`. Test: a v2+ workspace item is dispatched by scheduler only.

**B2 — Cap watchdog recoveries (AUDIT §2 MED).** Add a recovery-attempt ceiling to the >30m-scheduled reset path; dead-letter on exhaustion (mirror the publishing-stuck 3-retry path). Test: an item that fails N recoveries lands in `dead_letter`, stops re-alerting.

**B3 — Redispatch overdue IG instead of dead-ending to draft (AUDIT §2 MED).** `campaign-schedule-recovery` re-queues to the scheduler (or emits a draft-backlog alert) rather than silently resetting to `draft`. Test: an overdue IG post is re-dispatched, not stranded.

**B4 — De-risk `reconcile-daily` timeout (AUDIT §2 MED).** Paginate/shard the per-account Meta scan across runs (cursor in a table) so a single run stays well under 300s at 200+ accounts. Test: a 500-account fixture completes within budget across runs.

**B5 — Optional enforced budget cap (AUDIT §2 MED).** Promote `cost-digest` from alert-only to an enforced ceiling that pauses a workspace at 100% of `AI_DAILY_SPEND_LIMIT_USD` (owner-gated flag). Test: spend at cap flips the pause flag.

---

## Track C — Vercel backend (7.0 → 9.5). All TD.

**C1 — `cross-reply-publish` returns 5xx on retry-eligible errors (AUDIT §3 MED).** Replace the catch-all `200` with proper status so QStash retries/dead-letters; **keep the existing Sentry capture** (failures are already visible there — this is purely about restoring retry). Test: a thrown transient error yields 5xx; a permanent error dead-letters.

**C2 — Bound the manual-publish path (AUDIT §3 HIGH).** Add `maxDuration: 60` for `posts.ts` in `vercel.json` (or route manual publish through the async container path). Test: a slow-Meta simulation doesn't truncate mid-publish.

**C3 — [verify-then-fix] IG-webhook fallback body (AUDIT §3 HIGH[verify]).** Trace past `webhook.ts:150`; if the fallback branch can reach HMAC verify on re-serialized bytes, make it a hard 4xx reject. Test: a fallback-body request is rejected, not verified.

**C4 — [verify-then-fix] IG-container TTL (AUDIT §3 MED[verify]).** Confirm `ig-container-publisher` abandons containers older than ~24h and dead-letters them; add the TTL if missing. Test: a stale `IN_PROGRESS` container transitions to dead_letter.

**C5 — Token hygiene + override TTL (AUDIT §3 MED).** Hard-delete the prior encrypted token blob on successful refresh; make `crossAccountMediaReuseOverrideToken` single-use or <5-min TTL. Tests: refreshed token leaves no stale blob; an expired/used override token is rejected. *(Safety-relevant: the override is a distinctness-guard bypass — keep it tight.)*

**C6 — Unify Threads error handling on `classifyMetaError()` (AUDIT §3 LOW).** Replace ad-hoc string-matching in `publishThreads.ts`. Test: known Threads errors classify into the same taxonomy IG uses.

---

## Track D — Supabase schema/DB (7.0 → 9.5). All TD. D1 is the biggest single perf win.

**D1 — Index diet on the two hottest tables (AUDIT §4 HIGH-1/2).** `DROP INDEX CONCURRENTLY` the 11 never-scanned `posts` indexes + dedupe the `post_metric_history` near-duplicate pairs (keep one covering index per access pattern). Verify each is unused via `pg_stat_user_indexes` before dropping; one PR per table with before/after index-count + write-amp note. Test/proof: advisor `unused_index` count drops; publish-path EXPLAIN unchanged.

**D2 — Add the 29 unindexed FK indexes (AUDIT §4 MED).** `CREATE INDEX CONCURRENTLY` on the FK columns the advisor flagged (prioritize hot-path `posts`/`auto_post_queue`/`publish_attempts`; skip truly-dead `manager_*` if those tables are being retired). Proof: advisor `unindexed_foreign_keys` clears.

**D3 — Prune the 195 unused indexes outside the hot tables (AUDIT §4 MED).** Batched `DROP INDEX CONCURRENTLY`, one PR per table-family, each gated on `idx_scan = 0` over a stated window. This is the systemic "index-everything" cleanup; do it after D1. **Status:** merged batches cover `campaign_factory_*` (TD #147), `scheduler_decisions` (TD #152), `meta_api_usage_snapshots` (TD #153), `competitor_top_posts` (TD #154), `account_dna*` (TD #155), `ai_eval_snapshots` (TD #156), `operator_action_audit_logs` (TD #157), `audit_logs` (TD #158), `autoposter_post_performance_facts` (TD #160), `ai_action_log` (TD #161), `autoposter_account_hour_performance` (TD #162), `account_autoposter_state` (TD #163), `instagram_metric_availability_events` (TD #164), `post_originality_signals` hash GIN indexes (TD #165), `publish_attempts` zero-scan indexes (TD #166), `media` zero-scan helper indexes (TD #167), `mentions` unread helper indexes (TD #168), `post_templates` recent-usage index (TD #169), `proof_runs` helper indexes (TD #170), `creator_identity_shape_usage` helper indexes (TD #171), `data_deletion_requests` duplicate confirmation-code helper index (TD #172), `post_tags` user helper index (TD #173), `auto_self_replies` scope helper indexes (TD #174), `auto_cross_replies` scope helper indexes (TD #175), `sent_replies` redundant account-only helper index (TD #176), `share_of_voice_history` redundant account/date helper index (TD #178), `account_uniqueness_metrics` speculative latest/group helper indexes (TD #179), and `autoposter_winner_patterns` clone-family helper index (TD #180); continue with the next live-zero-scan table family rather than rebasing these into one oversized PR.

**D4 — Settle the `posts` lease semantics (AUDIT §4 MED, ties to §1).** Confirm the publish worker takes `publish_locks` before *every* send and wire the day-old `next_retry_at` into a cron; document the two-mechanism (`publish_locks` + fingerprint) idempotency contract so it isn't re-litigated. Test: concurrent sends for one post serialize on the lock; `next_retry_at` drives a retry.

**D5 — Make repo = live truth (AUDIT §4 LOW).** Add `CREATE TABLE` migrations for the 6 out-of-band tables (`agent_notes`, `inbox_ai_buckets`, `inbox_conversation_state`, `inbox_saved_views`, `notifications`, `revenue_snapshots`) and regenerate `src/types/supabase.ts` (currently one behind: missing `autoposter_control_events`). Proof: a clean migration replay reproduces all 206 tables; types key-count matches live.

**D6 — Confirm the 3 RLS-no-policy tables are intentional (AUDIT §4 LOW).** `account_flavor`, `creator_dna`, `creator_identity_shape_usage` — add explicit service-role-only comments or policies so default-deny is a decision, not an accident. Verify the 4 `SECURITY DEFINER` workspace helpers can't probe foreign tenants.

---

## Suggested order (for the owner)

1. **Track A (seam) first** — it's the ⭐ target and A1+A2 are a few hours that remove the only silent-data-loss paths in the system.
2. **D1 in parallel** — biggest DB perf win, fully independent, pure deletion of unused indexes.
3. **C1/C2** — small, high-value backend safety.
4. **B1–B3** — cron correctness.
5. Everything else (A4/A5, C3–C6, B4/B5, D2–D6) is parallelizable cleanup; the two `[verify]` items gate their own fixes.

## Ceilings these PRs do NOT remove (honest)

- **Meta-API latency/variance** — C2/C4 handle *timeout and orphaning*, not Meta being slow; that's external.
- **Schema width on `posts` (~180 columns)** — the index diet cuts write-amp, but the denormalized column count is a deeper refactor not in scope here.
- **The backward loop is only as fresh as its schedule** — A4 closes the manual gap, but learning quality still trails posting volume × time (same calendar ceiling `INTELLIGENCE_AUDIT.md` already states).
