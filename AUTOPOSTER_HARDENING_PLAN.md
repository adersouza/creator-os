# Autoposter Hardening Plan — ThreadsDashboard

**Audience:** Codex (autonomous coding agent) + human reviewers.
**Scope:** The auto-posting / scheduling / publishing subsystem in ThreadsDashboard (Juno33).
**Companion:** Visual map in [`autoposter_map.html`](./autoposter_map.html). Every item below cites the file:line shown there.
**Goal:** Fix the 8 risk/gap flags and make the publish path smoother and cleaner — without regressing a pipeline that works today.

---

## ⚠ Read this first — boundary & safety

1. **ThreadsDashboard is external source-of-truth.** Creator OS no longer commits `apps/dashboard/**`. Every fix here lands **upstream in `/Users/aderdesouza/Developer/ThreadsDashboard`**. The file:line anchors below refer to the upstream ThreadsDashboard source; do not recreate or hand-edit a Creator OS dashboard mirror.
2. **The chain works today.** Drafts post end-to-end. These are hardening items (races, fixed thresholds, fire-and-forget paths, a plaintext secret, one unverified gap) — **not breaks**. **No behavior regressions** to the working publish path.
3. **`AGENTS.md` lists Scheduling / Publishing / QStash / Account health / Metrics sync as "do not touch during docs/integration work."** This plan is the **explicit owner instruction** to change them. Therefore each change must be deliberate, behind tests, reversible, and shipped as its own PR — never bundled.
4. **One logical fix per PR.** Conventional Commits. Each PR keeps ThreadsDashboard's own test suite green and adds the negative/race test that proves the fix.
5. **Draft-first stays sacred.** Nothing in here may weaken the rule that nothing auto-publishes without the existing approval + safety gates.

---

## Evidence status — read before executing

This plan was drafted from a read-only exploration agent, then **three of its claims were re-checked against the actual ThreadsDashboard source**. Some hedged inferences turned out to be already-handled. Each item below is tagged:

- **✅ confirmed-from-code** — the defect was verified by reading the cited code. Safe to execute.
- **🔍 inferred** — flagged from reading order, **not** yet confirmed. Each carries a **Step 0: confirm the defect exists** gate. If Step 0 shows it's already handled, close the item — do not refactor working code.

**Already refuted during the re-check (do NOT "fix" these):**
- **Rate-limit race** — `igRateLimit.ts` already does an **atomic** check+increment via the `ig_check_and_increment_rate_limit` RPC (file comment: *"The RPC atomically checks + increments the daily counter"*). No read-modify-write. Nothing to fix.
- **Per-row schedule double-flip** — the status flip is already optimistic-concurrency-safe: `UPDATE posts ... .eq("status","draft").select("id").maybeSingle()` with clean-fail when no row returns (`campaignSchedule.ts:633-642`). This is the reference pattern; **leave it alone**.
- **`posts` RLS missing** — the policy exists: `CREATE POLICY "Users can manage own posts" ON public.posts FOR ALL USING (auth.uid()::text = user_id)` with RLS enabled (`schema.sql:1089,1155`). The residual concern (AP1-4) is only the service-role paths that bypass it.

## ✅ Progress (updated 2026-06-18)

| ID | Item | Status |
|----|------|--------|
| **AP0-1** | Duplicate-schedule race | **✅ Done** — TD: partial unique index `20260618013000` + scoped `23505` mapping. (Review: rate-limit was already atomic; only the cross-row dup needed fixing.) |
| **AP0-2** | Metrics reconciliation | **✅ Done** — TD: bounded reconciliation phase re-dispatches missing 1h/24h windows with stable dedupe. |
| **AP0-3** | Thread-chain preflight | **✅ Done** — TD: per-segment size check before Meta fetch; `threads_chain_segment_too_long`. **Byte-based sizing was reviewed and is CORRECT — do not change it to char count.** It's consistent with the repo's existing Threads byte checks (`THREADS_TEXT_MAX_BYTES`, `publishPost.ts:688`) and matches how Threads counts emoji/URLs (UTF-8 byte length). A char-count "fix" would break consistency and be less accurate. |
| **AP1-1..5, AP2-*** | Robustness / security / cleanliness | ⏳ pending |

All three landed on separate `codex/autoposter-ap0-*` branches in **ThreadsDashboard** (not the deleted mirror). Next pickup = AP1 tier.

---

## Priority summary

| ID | Tier | Status | Item | Risk if unfixed |
|----|------|--------|------|-----------------|
| AP0-1 | Correctness | ✅ confirmed | Cross-row duplicate schedule race (one DB index) | two same-fingerprint drafts both schedule concurrently |
| AP0-2 | Correctness | 🔍 inferred | Metrics fetch fire-and-forget (no reconciliation?) | silent learning-loop data loss |
| AP0-3 | Correctness | 🔍 inferred | Thread-chain splitting assumed, not implemented? | over-limit chains fail at publish |
| AP1-1 | Robustness | ✅ confirmed | Retry thresholds code-baked, no backoff | flapping account burns retries; redeploy to tune |
| AP1-2 | Robustness | ✅ confirmed | Cron phase time-budget starvation | IG containers / queue reconcile starve under load |
| AP1-3 | Security | ✅ confirmed | Ingest secret plaintext, no rotation | one leaked secret = full draft-write access |
| AP1-4 | Security | ✅ confirmed | Service-role paths bypass RLS (P1-1 class) | one missed scope guard = cross-tenant exposure |
| AP1-5 | Robustness | 🔍 inferred | Audio validation spec-only, not vs Meta? | stale audio_id passes preflight, fails at publish |
| AP2-* | Cleanliness | ✅ confirmed | State-machine consolidation, observability, docs | maintainability; transitions hard to audit |

Suggested order: **AP0-1 → AP0-2 → AP0-3 → AP1-1 → AP1-2 → AP1-4 → AP1-3 → AP1-5 → AP2**. Do each 🔍 item's Step 0 before its fix. Correctness/safety first; cleanliness last (easier once the state machine is the single chokepoint).

---

## AP0 — Correctness & safety (do first)

### AP0-1. Close the cross-row duplicate-schedule race (✅ confirmed)
- **Where:** `hasActiveDuplicate` (`campaignSchedule.ts:392-439`) reads up to 100 recent `posts` and returns a duplicate reason; the per-post status flip (`campaignSchedule.ts:633-642`) is **already** atomic (`.eq("status","draft").select("id").maybeSingle()`).
- **What is and isn't a race (verified by reading the code):**
  - The **per-row** flip is safe — two writers racing the *same* draft: only one's `.eq("status","draft")` update returns a row; the other fails cleanly. **Do not touch this.**
  - The **cross-row** duplicate check is *not* guarded: `hasActiveDuplicate` is a read-then-decide. Two *different* drafts with the same `content_fingerprint` + `instagram_account_id` (e.g. a Campaign Factory batch scheduling both at once) can each pass `hasActiveDuplicate` before either is committed, then each flips its own row successfully → both scheduled. The per-row guard can't catch this; they're different rows.
- **Fix — one DB constraint, not an app refactor:** add a **unique partial index** that encodes the active-duplicate rule, so Postgres rejects the second writer atomically:
  `CREATE UNIQUE INDEX ... ON posts (instagram_account_id, campaign_factory_content_fingerprint) WHERE status IN ('scheduled','publishing') AND campaign_factory_content_fingerprint IS NOT NULL;`
  Then handle the unique-violation on the status flip the same way the code already handles a lost race — increment `failedCount`, push a `duplicate_content_fingerprint_account` result, continue. Keep `hasActiveDuplicate` as the friendly pre-check (it still gives nice reasons for the common case); the index is the backstop that closes the window. (Extend with the variant-sibling rule from `hasVariantLineageConflict` if you want that race closed too.)
- **Why this is low-risk:** additive (a new index + one catch branch), does **not** modify the working atomic flip or the already-atomic rate-limit RPC, and is reversible (drop the index).
- **Verify:** a concurrency test firing N parallel schedule calls for the same fingerprint/account → exactly 1 scheduled, N-1 rejected with `duplicate_content_fingerprint_account`. ThreadsDashboard suite green.

### AP0-2. Make metrics sync reconcilable (kill fire-and-forget data loss)
- **Step 0 (confirm the defect):** check whether a backfill already exists before building one. Grep `sync-orchestrator` / `campaign-schedule-recovery` and the metric handlers for any path that finds published posts missing a `post_metric_history` row and re-enqueues. If one exists, this item is **closed** (or shrinks to "make it observable"). Only proceed if no reconciliation is found.
- **Where:** `post-engagement.ts:64` (engagement fetch), `qstashSchedule.ts:119` (1h/6h/24h delayed dispatch).
- **Problem (inferred):** Engagement is fetched via QStash delayed publish at 1h/6h/24h. The exploration agent saw no reconciliation — if all QStash retries for a window fail, that snapshot would **never** be backfilled and the learning loop silently loses data. Confirm in Step 0.
- **Fix:**
  - Add a **reconciliation cron** (or fold into `sync-orchestrator`): find `posts` where `status='published'`, `published_at` older than each window + grace, and **missing** the corresponding `post_metric_history` row, then re-enqueue the fetch.
  - Record per-post per-window fetch state (e.g. `metric_fetch_status` jsonb: `{ "1h":"done","6h":"pending","24h":"missed" }`) so "missed" is queryable, not invisible.
  - Emit a count of reconciled/abandoned snapshots in the cron run report.
- **Verify:** simulate a dropped QStash window (skip the dispatch) → reconciliation cron detects the missing snapshot and backfills it. Assert no published post sits permanently without its 24h snapshot.

### AP0-3. Implement (or hard-gate) Threads chain splitting
- **Step 0 (confirm the defect):** read `publishPost.ts` around `CHAIN_SEPARATOR` (L659) and `threadsApi.ts` `postToThreads`. Confirm whether anything splits/enforces the per-post char limit. If splitting already happens (or preflight already blocks over-limit), close or shrink this item.
- **Where:** `publishPost.ts:659` (`CHAIN_SEPARATOR`).
- **Problem (inferred):** The chain separator exists but the agent saw no explicit split/truncation logic — the code may assume the Threads API auto-splits. If unconfirmed, an over-limit chain can fail at publish time after passing every gate.
- **Fix:** either (a) implement real splitting — break caption on `CHAIN_SEPARATOR`, enforce the Threads per-post character limit per segment, post as a reply chain; or (b) if Threads genuinely auto-splits, **prove it** and add a preflight check (`publishPreflight.ts`) that blocks/ warns when any segment exceeds the limit, so failure surfaces at schedule time, not publish time. Pick (a) if behavior is uncertain.
- **Verify:** a caption with 3 over-limit segments → either posts as a correct N-part chain, or is blocked at preflight with a clear reason. No silent publish-time failure.

---

## AP1 — Robustness & security

### AP1-1. Externalize retry thresholds + add exponential backoff
- **Where:** `publishPost.ts:206` (`escalateSkip`, `MAX_SKIP_RETRIES≈3`), `publishPost.ts:283` (`escalateRateLimit`, `MAX_RATE_LIMIT_RETRIES=12`).
- **Problem:** Thresholds are constants baked in code; the cadence is a fixed 5-min cron with no backoff. A flapping account exhausts retries in ~15 min (skip) regardless of cause, and tuning needs a redeploy.
- **Fix:** move thresholds + base-delay to config/env (per-reason if possible). Add exponential backoff: store `next_retry_at = now + base * 2^attempt (capped)` on the post, and have the worker skip posts whose `next_retry_at` is in the future. Prefer re-dispatching via QStash with the computed delay over waiting for the next flat cron tick.
- **Verify:** a transient-failing post is retried at growing intervals (assert `next_retry_at` grows); thresholds change via config without a code edit.

### AP1-2. Fair scheduling across publish-worker phases
- **Where:** `publish-worker.ts:108-111` (4 phases under a 170s/180s budget).
- **Problem:** Phases run in fixed order under one shared budget. If Phase 1 (scheduled posts) overruns, Phases 2-4 (IG container publish, queue reconcile, queue fill) **silently skip** that cycle — IG containers and the `auto_post_queue` can starve under sustained load.
- **Fix:** track per-phase `last_completed_at`; start each cycle from the most-starved phase (round-robin / aging), or split the phases into separate cron functions with their own budgets so one can't crowd out the rest. Cap per-phase time so no single phase can consume the whole window.
- **Verify:** under a synthetic Phase-1 overload, Phases 2-4 still make progress across consecutive cycles (assert each phase's `last_completed_at` advances within N cycles).

### AP1-3. Ingest-secret rotation + log masking
- **Where:** `draftIngest.ts:229,577` (`CAMPAIGN_FACTORY_INGEST_SECRET`).
- **Problem:** Single plaintext env secret guards all draft writes; no rotation/versioning, no log masking visible.
- **Fix:** accept a **set** of valid secrets (current + previous) so rotation is zero-downtime; compare in constant time; **mask** the secret in any log/error path; document the rotation procedure. (Stretch: move to per-source signed tokens so Campaign Factory's credential is independently revocable.)
- **Verify:** rotating the secret with both old+new configured keeps ingest working; the secret never appears in logs; an invalid secret still 401s.

### AP1-4. Enforce account scoping on every privileged publish query (RLS class)
- **Where:** `publishPost.ts:39` (`getPrivilegedSupabaseAny(PRIVILEGED_DB_REASONS.publishExecution)`), publish-worker + scheduled-post-publish paths.
- **Problem:** The base `posts` RLS policy exists and is correct (`schema.sql:1089,1155`, scoped to `user_id`) — but publish/cron paths deliberately use the RLS-**bypassing** service-role client (justified — server-side, no user session). That makes app-layer account scoping the only guard on those paths. Same class as audit **P1-1**: one missed scope filter = cross-tenant publish/read.
- **Fix:** audit every privileged query in the publish/metrics/schedule paths; confirm each filters by the post's owning `user_id` / `account_id` from the row itself (never from caller-supplied input), and each has a `PRIVILEGED_DB_REASONS` entry. Add **pgTAP negative tests** proving a post for account A can never be published/read under account B's context.
- **Verify:** pgTAP cross-tenant tests fail before the guards, pass after. No privileged query lacks an explicit scope filter.

### AP1-5. Runtime audio validation before publish
- **Step 0 (confirm the defect):** read the audio branch of `publishPreflight.ts`. Confirm validation is contract-only with no Meta lookup. If a runtime check already exists, close this item.
- **Where:** `publishPreflight.ts` (audio spec check), `publishing.ts:20` (`applyInstagramReelsAudioParams`).
- **Problem (inferred):** Reels `audio_id`/`audio_name` appear validated against the contract only — not against Meta. If so, a stale/invalid `audio_id` passes preflight and fails at publish.
- **Fix:** add a lightweight Meta lookup for the `audio_id` at preflight (cache results; fail-soft to "warning + native audio" rather than hard-block if the lookup itself errors, to respect native-audio-first). Surface the result in the readiness summary.
- **Verify:** a known-invalid `audio_id` is flagged at preflight, not at publish; a valid one passes; a Meta-lookup outage degrades to a warning, never a crash.

---

## AP2 — Smoother & cleaner (do last)

### AP2-1. One state machine, one chokepoint
- **Problem:** Status transitions (`draft → scheduled → publishing → published / failed`, plus recovery resets) are spread across `draftIngest.ts`, `campaignSchedule.ts`, `publishPost.ts`, `scheduled-posts.ts`, and recovery crons. Transitions are hard to audit and are exactly where the AP0-1 races live.
- **Fix:** define a single documented transition function (e.g. `transitionPostStatus(postId, from, to, reason)`) that does the guarded conditional update (`WHERE status = $from`) and emits a structured transition log. Route **every** status change through it. This makes AP0-1's atomicity the default and gives one place to reason about the lifecycle. Behavior-preserving; ship incrementally, one call-site per commit.
- **Verify:** no direct `UPDATE posts SET status=...` outside the transition function (add a lint/grep guard); existing suite green per migration.

### AP2-2. Standardize the cron run report
- **Problem:** Cron cycles log ad-hoc; the 4 phases + recovery + sync each report differently.
- **Fix:** every cron emits one structured run report: cycle id, per-phase counts (claimed / published / skipped / failed / reconciled), spend (if any), and starved-phase flags from AP1-2. Persist a short rolling history so drift is queryable.
- **Verify:** each cron cycle produces one parseable report; a dashboard/query can show publish success rate + per-phase health over time.

### AP2-3. Document the two-queue contract
- **Problem:** `posts` scheduled-path and `auto_post_queue` (AI-fill) share the publish worker but are distinct systems; the integration point (`posts.auto_post_queue_id` backref, Phase 3 reconcile) is undocumented.
- **Fix:** a short `docs/` note (upstream) describing both queues, who writes each, how they converge on the worker, and the backref contract. Mirror it into the monorepo `autoposter_map.html` "Cron & Queue" tab note.
- **Verify:** the doc exists and matches the code; a new contributor can tell the two systems apart.

---

## Research-backed additions (2026-06-18 — see `research/06–09`)

### AP1 sharpened — publish-path error/retry/idempotency (research/07)
Replace the code-baked 3/12 retry thresholds with a real taxonomy + dynamic gating:
- **Classify by (code, error_subcode), not HTTP status.** TRANSIENT (1,2,4,17,32,341,368,80001–14,613,9007/2207027, −1/2207001/2207082/2207053) → exp backoff + jitter. WINDOW-CAP (9/2207042) → requeue, query the limit endpoint first. TOKEN (190/463 → refresh+retry once; 190 no-sub/467/460/458/490/refresh-fail → dead-letter re-auth). PERMANENT (100, 9004/2207052, 352/2207026, 10/200–299, 506) → dead-letter with captured `message`/`error_user_msg`/`fbtrace_id`.
- **Back off from `X-Business-Use-Case-Usage.estimated_time_to_regain_access`** (minutes, authoritative); proactively throttle at ~70–80% of call_count/total_time/total_cputime.
- **Dynamic quota gate before publish:** query `content_publishing_limit` (IG, returns 50 or 100) / `threads_publishing_limit` (Threads 250/1000/100/500) — never hard-code; `config.quota_total` is per-account ground truth.
- **Idempotency** (publish is NOT idempotent, no key header): persist creation_id→media_id; never re-publish a creation_id that returned a media_id; on publish timeout GET container status first (if PUBLISHED, record success); dedup store keyed by job id, TTL >24h. creation_id is one-time-use — on ERROR/EXPIRED create a NEW container.
- **Token state machine:** refresh long-lived (60d, IG/Threads; 90d Threads private) before expiry; not-refreshed-within-60d = unrecoverable → re-auth queue.

### AP3 (NEW) — Account-health → auto-backoff (research/08)
**Target:** the autoposter detects a throttled/recommendation-ineligible account from its OWN Insights and pauses + alerts instead of posting into a suppressed account; auto-resumes on recovery. This is the "smart autoposter" loop.
- **Primary signal:** non-follower reach ratio collapse via `GET /{ig-user-id}/insights?metric=reach&breakdown=follow_type` (NON_FOLLOWER/(FOLLOWER+NON_FOLLOWER)). Account-level only (per-post split is in-app).
- **Baseline:** 30-day rolling, **median/MAD** (not mean/std). **Trigger** when ≥2 hold for ≥3 consecutive days/posts: non-follower ratio ≥50% below baseline or <10% absolute; total-reach z < −2.5 (tune); per-post reach down 40–90% uniformly. **Recovery:** both back in band for 5–7 days.
- **Fleet false-alarm suppressor:** a simultaneous fleet-wide drop = IG algo change / platform decay, not per-account throttling — suppress the alert when cross-account-correlated.
- **Gap to accept:** Account Status / recommendation-eligibility has **no API** — detector is inferential; pair with a periodic manual in-app check on trigger. All numeric thresholds are heuristic — recalibrate on observed false-positive rate. Compliant: official Insights only, own authorized accounts, no scraping.

### Cadence guardrail (research/09)
Hard-cap default cadence **well under** the API ceiling (~1–2 posts/day/account, 2–4h spacing, ±15–30min jitter) — Meta's spam trigger is *frequency*, not automation. Never fan **identical** content across accounts in a tight window. Confirms `deriveCadence`'s conservative posture is correct. Feed AP3's throttle signal back into cadence (reduce on warning).

### ⛔ Explicitly out of scope (do NOT build)
Per `research/09`, the source material included account-linkage **evasion** tactics — antidetect browsers, per-account proxy/IP isolation, separate SIMs/emails, activity desync "so it's not obvious one operator runs all accounts," and warming schedules to slip past new-account heuristics. These are **coordinated inauthentic behavior** and are prohibited from this codebase. The system detects-and-respects platform rules and produces genuinely distinct content for legitimately-separate, OAuth-authorized accounts. It does not coordinate-and-hide.

## Definition of done

- AP0-1: parallel schedule/publish/rate-limit tests prove no double-publish and no limit breach.
- AP0-2: no published post can sit permanently without its 24h metric snapshot; reconciliation backfills dropped windows.
- AP0-3: over-limit Threads chains either split correctly or are blocked at preflight — never fail silently at publish.
- AP1-1..5: thresholds configurable with backoff; phases can't starve each other; secret rotates with masking; pgTAP proves cross-tenant isolation in publish paths; invalid audio caught at preflight.
- AP2-*: all status changes route through one guarded transition function; every cron emits a standard run report; the two-queue contract is documented.
- AP1 (sharpened): retry driven by the (code,subcode) taxonomy + `estimated_time_to_regain_access`; publish gated on live quota endpoints; idempotency dedup proven (no double-publish on retry/timeout); token refresh-vs-deadletter state machine.
- AP3: account-health monitor pauses + alerts a throttled account on the multi-signal trigger and auto-resumes on sustained recovery; fleet-correlated drops don't false-alarm.
- No evasion tooling (antidetect/proxy-isolation/identity-delinking/warming-to-evade) anywhere in the codebase.
- All work lands **upstream in ThreadsDashboard**. Creator OS keeps only planning/map artifacts and shared contracts; it does not restore a dashboard mirror. ThreadsDashboard suite green per PR. Draft-first invariant intact.
