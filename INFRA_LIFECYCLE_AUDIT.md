# Infra & Cross-Repo Lifecycle Audit — Creator OS ⇄ ThreadsDashboard

**Audience:** Codex + owner. **Date:** 2026-06-18. **Type:** read-only audit (no code changed).
**Scope (exactly four targets, by owner request):** (1) the end-to-end cross-repo content lifecycle "seam", (2) the 26 Vercel crons, (3) the Vercel serverless backend, (4) the Supabase schema/DB. Nothing else — no operator-UX, no economics.

**Sources:** `origin/main` on both repos (creator-os `/Users/aderdesouza/Developer/creator-os`, ThreadsDashboard `/Users/aderdesouza/Developer/ThreadsDashboard`), plus the **live** TD Supabase project `apsrvwxfoomhtswlhczo` (`threadsdashboard`, us-west-2) read through the Supabase MCP. Findings tagged **[HIGH]** (money / safety / silent data loss / security / perf-at-scale), **[MED]** (drift / no-next-step / latent), **[LOW]** (polish). `[verify]` = real code path but the failure mode needs one more trace to confirm exploitability.

This audit was produced by four parallel read-only passes (seam, crons, backend, schema) and then **reconciled against the live database** — several findings were corrected by direct SQL (noted inline). The reconciliations are the most load-bearing part; read them.

**Provenance (confidence is not uniform — read this).** The **seam** and **schema** findings were independently verified against live code / the live DB (the partial-uniques, the missing `campaign_factory_post_key` unique, the index counts, the media-hydration gating, the export-success path are all confirmed). The **crons** and **backend** findings are agent-reported from code reads, of which the load-bearing ones were spot-verified: `posts.ts`-absent-from-`vercel.json` (confirmed), `cross-reply-publish` 200-on-catch (confirmed — but it *also* reports to Sentry, so the issue is no-QStash-retry, not invisibility; downgraded to MED below). Items tagged `[verify]` are real code paths whose exploitability needs one more trace before they're actioned as HIGH.

**Execution update (2026-06-19):** TD infra hardening PRs #131–#179 are merged to TD `main`; there are no open TD infra PRs at refresh time. TD #159 synced the pipeline-contract snapshot after creator-os A5 changed the generated contract surface, and TD #177 fixed runtime-safe pipeline-contract imports for Vercel/serverless packaging. D3 unused-index pruning is continuing as bounded TD PRs, not a single broad migration: merged batches now cover TD #147 (`campaign_factory_*`), TD #152 (`scheduler_decisions`), TD #153 (`meta_api_usage_snapshots`), TD #154 (`competitor_top_posts`), TD #155 (`account_dna*`), TD #156 (`ai_eval_snapshots`), TD #157 (`operator_action_audit_logs`), TD #158 (`audit_logs`), TD #160 (`autoposter_post_performance_facts`), TD #161 (`ai_action_log`), TD #162 (`autoposter_account_hour_performance`), TD #163 (`account_autoposter_state`), TD #164 (`instagram_metric_availability_events`), TD #165 (`post_originality_signals` hash GIN indexes), TD #166 (`publish_attempts` queue-item, claim-token, and Threads-post-id indexes), TD #167 (`media` partial helper indexes), TD #168 (`mentions` unread helper indexes), TD #169 (`post_templates` recent-usage helper index), TD #170 (`proof_runs` helper indexes), TD #171 (`creator_identity_shape_usage` helper indexes), TD #172 (`data_deletion_requests` duplicate confirmation-code helper index), TD #173 (`post_tags` user helper index), TD #174 (`auto_self_replies` scope helper indexes), TD #175 (`auto_cross_replies` scope helper indexes), TD #176 (`sent_replies` redundant account-only helper index), TD #178 (`share_of_voice_history` redundant account/date helper index), and TD #179 (`account_uniqueness_metrics` speculative latest/group helper indexes). The D3 finding remains open until the broader unused-index backlog is pruned or explicitly deferred, but these table-family batches should not be duplicated.

---

## Scorecard (current → target 9–10)

| # | Domain | Now | Ceiling-on-fix | What caps it today |
|---|--------|-----|----------------|--------------------|
| 1 | **Cross-repo lifecycle seam** ⭐ | **6.5** | 9.5 | No idempotency key on the boundary; media-URL hydration only on the dead legacy path; failed write can read as success; backward sync manual + uncontracted. All cheap to close. |
| 2 | **Vercel crons (26)** | **7.5** | 9.5 | Strong self-healing + lock hygiene already. Caps: publish-worker/scheduler */5 overlap on v2+, no max-recovery-count, overdue-IG dead-ends to draft, reconcile-daily timeout risk, no hard budget cap. |
| 3 | **Vercel backend (~130 routes)** | **7.0** | 9.5 | Good auth + error taxonomy. Caps: cross-reply 200-masking, manual-publish timeout gap, IG-webhook fallback `[verify]`, IG-container TTL `[verify]`, stale-token retention, override-token TTL. |
| 4 | **Supabase schema/DB (206 tables)** | **7.0** | 9.5 | Tenant isolation + hot-path indexing already correct. Caps: `posts`/`post_metric_history` over-indexing (write-amp), 29 unindexed FKs, 195 unused indexes, posts lease semantics in flux, 6 out-of-band tables. |

**System infra average: ~7.0/10.** None of the four needs an architecture change to reach 9–10 — every cap is a bounded, low-risk fix (a unique index, a header, a `maxDuration`, an index diet, a schedule). The detailed path is `INFRA_HARDENING_PROMPT.md`.

---

## The spine — how content actually moves (this is the map that didn't exist)

```
 CREATOR-OS (Python, campaign_factory)                 THREADSDASHBOARD (Vercel + Supabase)
 ────────────────────────────────────                 ────────────────────────────────────
 export_threadsdash()                                   api/campaign-factory/drafts/ingest.ts
   build_draft_payloads()  ── media.url = None            handleCampaignFactoryDraftIngest()
   validate_..._strict()  (Python, schema only)             validateCampaignFactoryDraftIngest()  (TS, schema + 10 extra checks)
        │                                                    writeCampaignFactoryDraftIngest()
        │  HTTP POST  ─────────────────────────────────▶        selectExistingPost(campaign_factory_post_key)
        │  X-Campaign-Factory-Ingest-Secret  (30s, no retry)     insert/update  ──▶  posts  table
        │                                                              │
        │  (legacy, gated off: _legacy_supabase_writes_enabled())     │  publish_locks + cron publish-worker/scheduler
        └─ _write_supabase() ── direct Supabase REST + storage         │  → Meta Graph API (IG/Threads)
                                                                       ▼
 sync_performance_snapshots()  ◀──── reads raw columns ────── post_metric_history  (483K rows of metrics)
   (manual CLI / app call — NOT scheduled)                    analytics-pipeline / reconcile-daily crons
        │
        └─ merges into local performance_snapshots → learning loop (F v2, ranking)
```

**Three sentences:** Forward, creator-os builds draft payloads and **HTTP-POSTs them (secret-authed) to a TD ingest endpoint that lands them in the `posts` table** — a clean HTTP boundary, with an older direct-Supabase-write path still present but gated off. Backward, TD accumulates per-post metrics in `post_metric_history`, and creator-os **pulls them via a manual command** into its learning loop. The loop is architecturally closed but **operationally manual on the return leg, and the forward leg's idempotency/media guarantees are softer than they look.**

---

## Section 1 — Cross-repo lifecycle seam ⭐ (the highest-value target)

**[HIGH] HTTP ingest path never hydrates media URLs — assumes media is already remote.**
`adapters/threadsdash.py`: `build_draft_payloads()` emits `media.url = None` (≈:82). The only code that uploads media to storage and fills the URL — `_hydrate_surface_media_items_for_uploaded_media()` — is called **only inside `_write_supabase()` (the legacy path, lines 1087/1112), never on the HTTP branch (`_post_threadsdash_draft_ingest`, :556).** TD's `draftIngest.ts::mediaUrls()` tries to recover URLs from `draft.mediaItems` / `manifest.mediaItems[].url`, so this is **safe iff the render step uploaded media to remote storage before handoff.** If a manifest reaches the boundary with local paths, the post inserts with empty `media_urls` and fails only at async publish. **Action:** assert non-null remote media URLs at the boundary on both sides (creator-os pre-POST validation + TD ingest rejecting media-less drafts), instead of relying on the legacy path's hydration that no longer runs.

**[HIGH] A 2xx-with-empty-`postIds` response is recorded as a successful export.**
Verified: a hard HTTP error from the ingest POST *is* caught (`except Exception` → `record_event(status="failure")` + `fail_pipeline_job`), so outright failures are handled. The real gap is narrower and confirmed in code: the `threadsdash_exports` INSERT writes `status="exported"` and `record_event(status="success")` **whenever `post_ids` resolves to `[]`** — i.e. if TD returns 2xx but `postIds` is empty/partial (validated-but-not-written), `post_ids = supabase_post_ids or dashboard_post_ids = []` and the export still reads as success, with no reconciliation confirming the draft became a post. **Action:** treat empty-`postIds`-on-2xx as a retriable failure (not "exported"); add a read-back (count posts by `campaign_factory_post_key` / export id) before marking exported.

**[MED — downgraded from HIGH after live-DB check] Duplicate-post race on `campaign_factory_post_key` is latent, partially guarded.**
The handler does select-then-write on `campaign_factory_post_key` with **no DB UNIQUE on that column** (verified: zero indexes/constraints reference it), so concurrent/retried POSTs *can* race. **But** live `posts` carries two partial-unique indexes the migration grep missed (verified via `pg_indexes`):
- `posts_campaign_distribution_plan_active_uniq` UNIQUE(`user_id`,`campaign_factory_distribution_plan_id`) WHERE active incl. `draft`
- `posts_campaign_asset_account_time_active_uniq` UNIQUE(`user_id`,`instagram_account_id`,`campaign_factory_asset_id`,`scheduled_for`) WHERE active

These block the *visible* duplicate whenever a plan-id or (account+asset+scheduled_for) is populated. **Current prod: 0 duplicate keys.** Residual gap: drafts lacking both guard tuples are unprotected, and a poisoned key still trips `.maybeSingle()` (draftIngest.ts:679). **Action (cheap, closes it fully):** add `CREATE UNIQUE INDEX CONCURRENTLY` on `campaign_factory_post_key` (partial, non-null) + send an `X-Idempotency-Key` header so retries are first-class, not best-effort.

**[MED] Forward contract is enforced by two hand-rolled validators that can drift.**
Creator-os validates the payload against the Python schema (`validate_threadsdash_draft_payload_strict`, structure only); TD re-validates with **10+ imperative checks that are not in the shared JSON schema** (handoff-manifest-v2, visual_qc, identity_verification, schedule_safe, caption presence — draftIngest.ts:382–524). The schema is vendored in 5+ copies across both repos. A field can pass one side and be silently unenforced on the other. **This is the same hand-rolled-validator drift that `TRACK9_RIGOR_PROMPT.md` PR-1 (contract codegen) targets — the seam is the strongest argument for doing it.**

**[MED] Backward metric sync reads raw columns with no contract + is manual.**
`_select_threadsdash_post_metric_history()` selects `views_count, likes_count, …` straight off TD's `post_metric_history` (no schema check) — a TD column rename = silent NULL import into the learning loop. And the sync is a **manual `campaign-factory sync-performance` CLI / app call, not a cron** — if forgotten or creator-os is down, metrics accumulate in TD and never reach the learning DB, with no alert. **Action:** validate the read shape against a versioned `post_metric_history` contract; schedule the sync (or have a TD cron push `performance_sync.v1` rather than creator-os pull). The `performance_sync.v1` schema today is output-only and isn't validated even on write.

**[LOW] Secret rotation is well-built on TD, single-valued on creator-os.**
TD accepts CURRENT/PREVIOUS/EXTRA + comma-list secrets with timing-safe compare (draftIngest.ts:299–330) — proper rollover. Creator-os sends one configured secret, so a rotation still needs both sides updated in the same window. Fine; just document the order.

**[LOW] No retry/backoff on the POST.** `urlopen(timeout=30)`, no retries/circuit-breaker — transient TD slowness = hard export failure. Pair with the idempotency key above so a retry is safe to add.

---

## Section 2 — The 26 Vercel crons

**Posting critical-path chain (this is the spine of the autoposter):**
`scheduler */5` (v2+ workspaces: pick pending → dispatch to QStash) → `publish-worker */5` (publish scheduled + reconcile stranded) → QStash delay → `auto-post-publish` endpoint (**atomic claim** via `claim_auto_post_queue_item_for_publish` RPC: schedule_nonce + conditional status→publishing) → `reconcile-daily 03:30` (close webhook orphans) → `autoposter-watchdog 15,45` + `autoposter-doctor :25` (detect/repair) + `health-monitor */4h`.

**[HIGH→mitigated] `publish-worker` and `scheduler` both run */5 on v2+ workspaces.**
`publish-worker` loads `scheduler_version` but **never filters `>=2`** (publish-worker.ts:224), while `dawn-planner` and `account-state-evaluator` *do* (`(version??1)<2`). So on v2+ workspaces the same item can be fetched by both within one 5-min window. **The atomic claim RPC blocks any double-publish** — but the duplicate fetch/dispatch is wasted work and noisy. **Action:** filter publish-worker Phases 3–4 to `scheduler_version<2`, matching the other migrated crons.

**[MED] Watchdog auto-recovery has no max-recovery-count.**
Watchdog resets stuck items (queued/scheduled >30m, or publishing >10m) back to `pending` and reopens the pool (autoposter-watchdog.ts:1053/1685); publishing-stuck items get 3 retries then `deadLetterQueueItems()`. But the >30m-scheduled recovery has **no attempt ceiling** — a permanently-bad item can loop recover→fail→recover, re-alerting on a 2–30h dedup TTL. **Action:** cap recoveries per item, dead-letter on exhaustion (mirror the publishing-stuck path).

**[MED] `campaign-schedule-recovery` dead-ends overdue IG posts into `draft`.**
Every 5 min it finds IG campaign-factory posts >5m overdue with no publish attempt and **resets them to `draft` for manual retry — no auto-redispatch.** High-volume campaigns with a dispatch hiccup silently pile up in draft. **Action:** redispatch to the scheduler queue, or alert on draft-backlog growth.

**[MED] `reconcile-daily` is a known timeout risk.** TTL was bumped 120→310s after a 28% timeout rate (cronUtils.ts:44); it still scans up to 200 accounts × 25 posts against Meta APIs and can graze the 300s ceiling at scale. **Action:** paginate across runs / shard by account hash.

**[MED] No hard budget cap — cost crons are alert-only.** `cost-digest` (daily) warns at ≥75% of `AI_DAILY_SPEND_LIMIT_USD` via Discord; `monthly-kpi` reports only. **Nothing pauses spend.** (In-scope because it's a cron + DB concern; flagging, not expanding.) **Action:** optional enforced cap that flips a workspace to paused at 100%.

**[LOW / positive] Concurrency hygiene is good.** All 26 crons have handlers + `vercel.json` function entries + `LOCK_TTL_MAP` entries; every lock TTL exceeds its `maxDuration`, so no run overlaps itself. Watchdog (8 checks) + doctor (10 invariant checks) + health-monitor + reconcile form a real self-healing layer. Orphaned-run cleanup (>360s `running` → `failed`) is defensive-correct.

**[LOW] Watchdog + doctor still process v2+ workspaces** the scheduler is meant to own — operational noise, not double-repair (doctor is alert-only). Clarify ownership post-migration.

---

## Section 3 — Vercel serverless backend

**Shape:** ~130 deployable routes (excluding `api/_lib/**`), explicit `vercel.json` function config for ~47 critical paths (publish/cron/webhooks); the rest take the ~10–15s platform default. Routes lazy-import from the `api/_lib/handlers/**` pattern; no glob dispatcher; function count well under Vercel limits. **Auth:** `withAuth()` (Bearer→user) for user routes; `CRON_SECRET`/QStash-signature for crons; HMAC-SHA256 (`META_APP_SECRET`) for webhooks. **DB:** all routes use the **service-role** client (`getSupabase()`, RLS bypassed) gated only by a `PRIVILEGED_DB_REASONS` enum (review friction, not a technical gate) — DB-layer RLS is the real tenant guard (see §4). **Errors:** centralized `classifyMetaError()` taxonomy (transient/rate_limit/window_cap/auth/permanent/media).

**[MED — downgraded from HIGH after verification] `cross-reply-publish.ts` returns `200` on unhandled error — suppresses QStash retry (but not visibility).**
Line 63 returns `status(200).json({ok:true, error})` in the catch, so QStash sees success and **never retries or dead-letters** a failed reply. **Verified correction:** the same catch block *does* `captureServerException` to Sentry first, so failures are **observable** — the issue is missing retry/dead-letter, not invisibility (the agent's original "unobserved" framing was wrong). Engagement surface, lower blast radius. **Action:** return 5xx on retry-eligible errors so QStash retries; keep the Sentry report.

**[HIGH] Manual publish (`posts.ts` → `handlePublish` → `orchestrateIGPublish()`) is synchronous with no `maxDuration` entry.**
`posts.ts` is absent from `vercel.json` functions, so it runs at the ~10–15s default while calling Meta media endpoints synchronously. A slow Meta call times out mid-publish → post left claimed-but-unpublished. **Action:** add `maxDuration: 60` (autoposter path already gets 300s) or move manual publish to the async container/queue path.

**[HIGH][verify] Instagram webhook fallback-body branch may not reject before HMAC.**
`api/instagram/webhook.ts:136–150` accepts a pre-parsed `req.body` when the raw stream is missing, logs the security warning, but the trace past :150 needs confirmation that it **rejects** rather than HMAC-verifying re-serialized bytes (which would false-negative). If it proceeds, a forged event could slip in. **Action:** trace to the reject; make fallback-body a hard 4xx.

**[MED] Async IG container has no visible TTL → can orphan.**
Threads publish reaches `deadLetterQueueItem()` on permanent failure; IG queues a container for async polling (`publishInstagram.ts:1164`) set to `IN_PROGRESS`. If the container never completes (token revoked mid-flight), no TTL/abandon logic was seen. **Action [verify]:** confirm `ig-container-publisher` abandons containers >24h and dead-letters them.

**[MED] Stale encrypted OAuth tokens aren't hard-deleted on refresh.** Lazy v1→v2 re-encryption (`encryption.ts`) stores the new blob but doesn't invalidate the old → a stale-but-valid token lingers in old rows/snapshots. **Action:** delete prior encrypted blob on successful refresh; audit read access to `instagram_access_token_encrypted`.

**[MED] Cross-account media-reuse override token lacks visible TTL/single-use.** `handlePublish` honors `crossAccountMediaReuseOverrideToken` to bypass reuse guards with no observed expiry/usage cap. **Action:** make it single-use or <5-min TTL. (Safety-relevant — this is a guard-bypass on the distinctness side.)

**[LOW] Threads publish doesn't use `classifyMetaError()`** — ad-hoc string matching in `publishThreads.ts` while IG uses the taxonomy. Unify. **[LOW]** CSP report endpoint rate-limits fail-**open** and `scrubSensitive()` patterns look incomplete. **[LOW]** DLQ is swept by an ad-hoc cron, not a platform DLQ — fine, but confirm its alert threshold.

---

## Section 4 — Supabase schema / DB (live: `apsrvwxfoomhtswlhczo`)

**Orientation:** **206 public tables, 100% RLS-enabled (zero RLS-off tables).** Two state machines:
- **`posts.status`**: `draft→scheduled→publishing→published|failed|deleted` (live: 6535 published / 961 failed / 240 deleted / 1 scheduled). **No `dead_letter` status and no row-level claim/lease** — idempotency rides on the separate `publish_locks` table (account mutex) + `publish_fingerprint` + unique `posts_threads_post_id_unique`.
- **`auto_post_queue.status`** (the autoposter engine): `queued→publishing→published|needs_review|rejected|cancelled|dead_letter`, **with** proper lease columns `claim_token, claim_expires_at, claimed_at, retry_count, next_retry_at, last_error`.

**5 hottest tables:** `post_metric_history` (483K rows, 637K inserts), `posts` (7.7K rows but **795K updates**, 59 indexes), `auto_post_queue` (4.9K rows, 70K updates), `account_analytics`, `account_metrics_history`.

**[HIGH] `posts` is massively over-indexed for its write rate.** 59 indexes on a 7.7K-row / **795K-update** table; index 26MB vs table 12MB. The Supabase perf advisor flags **11 never-scanned indexes** (`idx_posts_publish_fingerprint`, `..._recent`, `idx_posts_ig_notify_due`, `idx_posts_approved_by`, `idx_posts_draft_folder_id`, `idx_posts_autoposter_pattern_account`, `..._group`, `idx_posts_strategy_outcome`, `posts_content_surface_idx`, `posts_active_arc_idx`, `idx_posts_campaign_variant_family_account`). Every update maintains all 59 and defeats HOT-update. **Dropping the 11 is pure win** — biggest single perf lever in the DB.

**[HIGH] `post_metric_history` index bloat + duplicate indexes.** 238MB index vs 110MB table on a 483K-row append-only table; near-duplicate pairs (`pmh_post_hours` vs `idx_pmh_post_hours …INCLUDE`, `idx_post_metric_history_post` vs `idx_pmh_post_snapshot_covering`), and `…_snapshot_at_brin` has zero scans. Each redundant index is paid on every insert at the DB's highest insert volume. **Action:** dedupe to one covering index per access pattern.

**[MED — premise DISPROVEN, recorded honestly] There is NO missing index on the publish/scheduler hot path.** The expected "`(status, scheduled_at, account)` seq-scan-at-scale" risk does **not** exist: `idx_posts_scheduled (status,scheduled_for) WHERE status='scheduled'`, `idx_posts_user_status_scheduled_for`, and the `auto_post_queue` claim/retry indexes all cover it; live working sets are tiny (1 scheduled post). The real perf risk is the inverse — over-indexing (above).

**[MED] 29 unindexed foreign keys** (advisor) incl. hot-path `posts.arc_beat_id/dna_id`, `auto_post_queue.arc_beat_id/dna_id`, `publish_attempts.group_id/user_id`, and the whole `manager_*` family — seq-scans on cascade/join. **[MED] 195 unused indexes across 110 tables** — systemic "index-everything" residue from 20+ index-tuning migrations with no prune cycle. Treat HIGH-1/HIGH-2 + these as one cleanup. **Current D3 batches:** TD #147 covers `campaign_factory_*`; TD #152 covers zero-scan `scheduler_decisions` account/run indexes while preserving active retention/recent-window indexes; TD #153 covers the zero-scan `meta_api_usage_snapshots(account_id, captured_at)` index while preserving the active user-window Reliability Center index; TD #154 covers zero-scan `competitor_top_posts` pattern/enrichment indexes while preserving active competitor, engagement, recent-window, pattern, metric-quality, unique, and primary-key indexes; TD #155 covers zero-scan `account_dna*` voice-embedding, creator-DNA, example, and account-rule indexes while preserving active workspace/group, active-account, rule-scope, primary-key, and creator-DNA table indexes; TD #156 covers zero-scan `ai_eval_snapshots` prompt-hash and user-suite indexes while preserving the active scope index and primary key; TD #157 covers zero-scan `operator_action_audit_logs` user-created, intent, phase/outcome, and scope indexes while preserving the primary key and insert/select-id audit behavior; TD #158 covers the zero-scan reconciled `audit_logs(user_id)` index while preserving the primary key, audit inserts, cleanup RPC, export coverage, and user-deletion cascade behavior; TD #160 covers zero-scan `autoposter_post_performance_facts` posting-hour, question-subtype, clone-family, and quality-gate-lane indexes while preserving the active primary key, account, group, workspace/published, and pattern read paths; TD #161 covers zero-scan `ai_action_log` account/provider indexes while preserving the primary key, active surface index, and user-scoped GDPR export/deletion index; TD #162 covers the zero-scan `autoposter_account_hour_performance` confidence index while preserving the active primary key and workspace/group/account weighted-score timing index; TD #163 covers the zero-scan `account_autoposter_state` blocked-until and group-health indexes while preserving the active primary key, group, status, workspace, and restart-warmup indexes; TD #164 covers the zero-scan `instagram_metric_availability_events(missing_metrics)` GIN index while preserving the primary key plus account/media/post/user synced indexes; TD #165 covers the zero-scan `post_originality_signals` media/perceptual hash GIN indexes while preserving the active `post_id` key and scoped duplicate-safety paths; TD #166 covers zero-scan `publish_attempts` queue-item, claim-token, and Threads-post-id indexes while preserving active account/result/workspace reporting indexes, the primary key, and the unique queue-attempt path; TD #167 covers zero-scan `media` user/group, user/folder, account-assignment, and spotlight helper indexes while preserving active user/last-used, workspace, group, folder, user, primary-key, and storage-path unique paths; TD #168 covers zero-scan `mentions` unread helper indexes while preserving active user lookup, account lookup, unique Threads post upsert, and primary-key paths; TD #169 covers the zero-scan `post_templates` recent-usage helper index while preserving the primary key, active user lookup, account-group lookup, and workspace/FK support indexes; TD #170 covers zero-scan `proof_runs` user/asset, user/status, and distribution-plan helper indexes while preserving the primary key and D2 FK support indexes; TD #171 covers zero-scan `creator_identity_shape_usage` recent-shape helper indexes while preserving the primary key and D2 FK support index; TD #172 covers the zero-scan duplicate `data_deletion_requests(confirmation_code)` helper index while preserving the unique confirmation-code constraint and privacy workflow helper indexes; TD #173 covers the zero-scan `post_tags(user_id)` helper index while preserving active post lookup, composite user/tag lookup, primary key, and post/tag/user uniqueness paths; TD #174 covers zero-scan `auto_self_replies(account_id)` and `(workspace_id)` helper indexes while preserving active pending/post paths, user/group paths, primary key, and post/reply uniqueness; TD #175 covers zero-scan `auto_cross_replies(parent_reply_id)` and `(workspace_id)` helper indexes while preserving active pending/user/group paths, primary key, and target/replier/chain uniqueness; TD #176 covers the zero-scan redundant `sent_replies(account_id)` helper index while preserving the covering `(account_id, created_at DESC)` rate-limit index and `user_id` FK/export index; TD #178 covers the zero-scan redundant `share_of_voice_history(account_id, date)` helper index while preserving the active unique `(user_id, account_id, date)` upsert index and primary key; TD #179 covers the zero-scan `account_uniqueness_metrics` speculative latest/group helper indexes while preserving the primary key and check constraints.

**[MED] `posts` publish path has no row-level lease and is in active flux.** `next_retry_at` was added to `posts` **today** (`20260618064358_add_posts_next_retry_at`); idempotency leans entirely on `publish_locks` + fingerprint. Valid two-mechanism design but unsettled this week. **Action:** confirm the worker takes `publish_locks` before *every* send and that `next_retry_at` is wired to a cron. (Ties directly to the seam idempotency story in §1 and the autoposter AP-tier work.)

**[LOW / positive] Tenant isolation is enforced at the DB layer, not app-only.** Sampled policies: `posts` `auth.uid()::text = user_id`; `accounts` same + `aal2_or_no_mfa()`; `auto_post_queue` via `workspace_members`; `post_metric_history` via account-ownership subquery. No `USING(true)`, no anon grants on hot tables. (Caveat: 4 `SECURITY DEFINER` workspace-helper functions are `authenticated`-executable — verify they can't probe other tenants' workspace IDs.)

**[LOW] Schema reproducibility gaps.** 6 tables exist live but are **never `CREATE`d in any origin/main migration** (`agent_notes`, `inbox_ai_buckets`, `inbox_conversation_state`, `inbox_saved_views`, `notifications`, `revenue_snapshots`) — created out-of-band, so a clean replay wouldn't produce them. Types file (`src/types/supabase.ts`, 205 keys) is one behind live (206) — missing `autoposter_control_events`. Ledger shows 290 applied vs 499 repo files (explained by the `…core_schema_baseline_for_branch_replay` squash). **Action:** backfill the 6 tables into migrations + regenerate types so repo = live truth.

**[LOW] DLQ is modeled as state+columns, not a table** (`ig_webhook_events.dead_letter*` for webhooks, `auto_post_queue.status='dead_letter'` for posts) despite a `…_dead_letter_queue` migration *name*. Architecturally fine; noted so the name isn't mistaken for a table. **[LOW] 3 RLS-enabled-no-policy tables** (`account_flavor`, `creator_dna`, `creator_identity_shape_usage`) are default-deny + service-role-read — confirm intent.

---

## Consolidated top actions (cross-cutting, prioritized)

1. **Close the seam idempotency gap (cheap, high-value).** `CREATE UNIQUE INDEX CONCURRENTLY` on `posts.campaign_factory_post_key` (partial, non-null) + `X-Idempotency-Key` header + treat empty-`postIds`/HTTP-error as one retriable state with a reconciliation read. Fixes §1 HIGH-2(now-MED) + HIGH-3 together and makes a POST retry safe to add. *(Latent today: 0 dupes — do it before volume grows.)*
2. **Boundary-assert media URLs** on both sides so the dead legacy-hydration path stops being load-bearing (§1 HIGH-1).
3. **Index diet on `posts` + `post_metric_history`** — drop the 11 unused + dedupe the metric-history pairs. Single biggest DB perf/write-amp win (§4 HIGH-1/2). Continue D3 separately as table-family batches; TD #147/#152/#153/#154/#155/#156/#157/#158/#160/#161/#162/#163/#164/#165/#166/#167/#168/#169/#170/#171/#172/#173/#174/#175/#176/#178/#179 are already merged and should not be duplicated.
4. **Return 5xx from `cross-reply-publish` + add `maxDuration:60` to `posts.ts`** (§3 HIGH) — and trace the IG-webhook fallback reject (§3 HIGH[verify]).
5. **Make the backward metric sync first-class** — schedule it (or TD-push `performance_sync.v1`) + validate the read shape (§1 MED). The loop is only as smart as its slowest-closing leg.
6. **Filter `publish-worker` Phases 3–4 to `scheduler_version<2`** + cap watchdog recoveries (§2).
7. **Contract codegen (TRACK9 PR-1) is the durable fix for §1's validator drift** — the seam is the strongest case for it.

## What this audit does NOT cover (honest scope)

Exactly the four targets. Not covered by request: operator-UX legibility, unit economics/cost modeling beyond the budget-cap note, the creator-os pipeline internals (covered by `INTELLIGENCE_AUDIT.md` + `TRACK9_RIGOR_PROMPT.md`), and TD product surfaces outside the posting/learning critical path. Two findings are `[verify]` (IG-webhook fallback, IG-container TTL) — real code paths whose exploitability needs one more trace before they're actioned as HIGH. Nothing here proposes evasion/CIB behavior; every safety-adjacent item (media-reuse override TTL, distinctness guards) is detect-and-respect hardening.
