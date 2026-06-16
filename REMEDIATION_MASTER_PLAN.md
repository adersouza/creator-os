# Creator OS — Remediation Master Plan

**Date:** 2026-06-16
**Owner:** Emerson
**Executor:** Codex
**Companions:** `AUDIT_2026-06-16.md` (backend/pipeline), `FRONTEND_AUDIT_2026-06-16.md` (UI), `MONOREPO_MIGRATION_MASTER_PLAN.md` (long-term structure).

This is the single execution plan to (a) close every still-open item from the two audits, (b) get the already-built fixes into the **live** runtime, and (c) permanently fix the monorepo↔split drift that has been making fixes read "done" while production stayed unpatched. It is written so Codex can execute workstream by workstream without guessing.

---

## 0. Read this first — the rule that prevents the recurring bug

The whole project has two copies of most code: the **split repos** (`/Users/aderdesouza/Developer/{reel_factory,campaign_factory,contentforge,ThreadsDashboard,reference_factory,pipeline_contracts}`) and the **monorepo** (`creator-os/{apps,python_packages,packages}`). Editing the wrong copy is what caused "fixed in monorepo, live system unpatched."

**Source-of-truth model (authoritative for this plan):**

| Project | Source of truth | Runtime | Monorepo role |
|---|---|---|---|
| ThreadsDashboard / Juno33 | **standalone `ThreadsDashboard` repo** | itself (Vercel, juno33.com) | `apps/dashboard` = **read-only mirror** for contract tests; never hand-edited, never deployed |
| reel_factory | split `reel_factory` repo (live) | standalone folder | `python_packages/reel_factory` = read-only mirror |
| campaign_factory | split `campaign_factory` repo (live) | standalone folder | `python_packages/campaign_factory` = read-only mirror |
| contentforge | split `contentforge` repo (live) | standalone folder | `apps/contentforge` = read-only mirror |
| reference_factory | split `reference_factory` repo | standalone folder | `python_packages/reference_factory` = read-only mirror |
| pipeline_contracts | **monorepo `packages/pipeline_contracts`** (canonical, per migration plan Phase 1) | consumed everywhere | split copies mirror FROM monorepo (opposite direction) |

**Non-negotiable:** until the sync+parity gate (WS1) exists, **runtime fixes land in the split repos**, and the monorepo mirrors are regenerated — never hand-edited. `pipeline_contracts` is the only thing canonical in the monorepo today.

---

## 1. Current state (verified 2026-06-16)

**creator-os `main` = `c1b7025`** — contains PR #15 (audit trust boundaries) + merged autoposter hardening.

**Already done + verified (monorepo):** #4 byte-identical render (account-scoped seed + production guard), #4 ledger cross-account cooldown, #7 identity verification (InsightFace, embeddings loaded, `.venv` caveat), #3 Higgsfield cost preflight, ContentForge job durability (p-queue + atomic writes), visual/identity proof propagation, hook honesty, autoposter hardening (gatePassToken publish-time revalidation, publish-time discoverability re-check, llmJudge fail-closed + provider router, conservative approval default, hard-block duplicate fingerprints, cross-account media-reuse block).

**Built but NOT live / NOT merged:**
- Autoposter hardening is on creator-os `main` but the **live ThreadsDashboard repo** has it only on branch `codex/autoposter-hardening` (`9ba87e8a8`) — **not merged to TD main → not protecting the running product.**
- Frontend cleanup: branch `codex/frontend-cleanup` (4 commits, Radix standardized + route-shell extraction) — **not merged.** A `codex/frontend-cleanup-rebased` also exists (reconcile).
- Tooling hardening: branch `codex/tooling-hardening` (4 commits) — **not merged.**

**WS2 port — UPDATE (verified 2026-06-16, later pass):**
- campaign_factory caption-fallback removal + inventory reservation + ingest routing: ✅ **committed** `f2e43b8` (caption=0, inventory in `db.py`, raw write now gated behind `CAMPAIGN_FACTORY_ENABLE_LEGACY_SUPABASE_WRITES=1`, `383 passed`, working tree clean). **On a branch — NOT yet merged to campaign_factory `main`.**
- reel_factory `review_truth.py`: ✅ **committed** `a87f8ea` (durable SQLite review, `maybe`, reviewer identity, undo, folder regen, integrity check, GUI wired; `307 passed`). **On a branch — NOT yet merged to reel_factory `main`.**
- plan amendment: ✅ on creator-os `main` (`a7ed42a`).
- TD `draftIngest.ts` routing: ❌ **still missing** — BLOCKED behind the dirty `codex/autoposter-hardening` worktree in the live TD repo (6 dirty files, uncommitted mid-flight autoposter/UI work). TD cannot move until that worktree is committed or stashed.

**Open / unported (live split repos lack these):**
- Merge `f2e43b8` (campaign_factory) and `a87f8ea` (reel_factory) to each split repo's `main` — committed but not live.
- TD `draftIngest.ts` routing — missing (blocked, see above).
- Deprecation cleanup: `six_pack`/`grid-crop`/`grok-4` still reachable (5 hits in `generate_assets.py`, 8 in `reel_gui.py`).
- Metadata normalization not mandatory on render path.
- QC fail-closed not enforced on every handoff path.
- Repo maturity: gitleaks NOT in CI; PROOF.json theater (4 files) present; split repos pytest-only (no lint/typecheck); tracked screenshots; 740 MB `.git`.
- **No mirror sync + no parity CI gate** → drift can recur.

**Owner-only (not code):** secret incident (rotate keys, re-encrypt OAuth tokens, purge git history, invalidate clones); scale proof (50/100/200 load + QStash-outage/reconciliation-drain); account-graph concentration certification.

---

## 2. Global constraints (apply to every workstream)

1. **No behavior change to scheduling, publishing, account-health, QStash, metrics sync, or production inventory** except where a task explicitly fixes a named gate.
2. **Verify, don't claim.** Every "done" must cite a passing command (test + grep). Report true git state: branch vs main, committed vs dirty, monorepo vs split. Do not say "done" for a monorepo-only change that the live split repo lacks.
3. **Respect source-of-truth (§0).** Runtime fixes → split repos. Mirrors are generated, never hand-edited.
4. **Per-repo gates pass before commit:** Python `uv run pytest <repo>/tests`; TD `pnpm --filter juno33 typecheck`+`test`+`npm run compat:check`; monorepo `pnpm check:contracts`+`check:arch`+`check:artifacts`; all `git diff --check`. Run `graphify update .` after touching a repo.
5. **Commit in small, single-purpose slices.** Never mix a runtime fix with mirror housekeeping or UI rebuild.
6. **Branch per workstream**, off the correct repo's `main`. Report SHAs.
7. **Stop and ask the owner** for the decisions in §11 before implementing the dependent task. Do not invent thresholds/budgets.
8. **Never commit** runtime data (media, models, DBs, uploads, node_modules, build output) — per `MONOREPO_MIGRATION_MASTER_PLAN.md` gitignore policy.

---

## 3. Sequencing (dependency order)

```
WS1 (sync + parity gate)  ─┐   keystone — do FIRST so all later work can't drift
WS2 (split-repo port)     ─┼─► WS3 (remaining backend items, in split repos)
WS4 (autoposter → live TD)─┘
WS5 (frontend merge + P2)   ── independent, can run in parallel
WS6 (repo maturity / CI)    ── independent, can run in parallel
WS7 (scale proof)           ── owner/operational, after WS1–WS4 stable
WS8 (secret incident)       ── owner, anytime (highest real-world urgency)
```

Rationale: WS1 first means every subsequent change is drift-proof. WS2/WS3/WS4 then land in the live runtime under that protection. WS5/WS6 are independent. WS7/WS8 are owner-driven.

---

## Progress tracker (updated 2026-06-16)

| WS | Status | Note |
|---|---|---|
| WS0 plan amendment | ✅ done | creator-os `main` `a7ed42a` |
| WS1 sync + parity gate | ❌ not started | **keystone — highest priority, zero prod risk** |
| WS2 split port | 🟡 in progress | campaign_factory `f2e43b8` + reel_factory `a87f8ea` committed (branch, need merge to split `main`); TD draftIngest blocked |
| WS3 remaining backend | ❌ not started | metadata mandatory, QC fail-closed, ingest routing live, identity pin, deprecation |
| WS4 autoposter → live TD | ⏸ blocked | on creator-os main; live TD merge stuck behind dirty TD worktree |
| WS5 frontend | 🟡 branch only | `codex/frontend-cleanup` unmerged; P2 pending |
| WS6 repo maturity | ❌ not started | gitleaks CI, PROOF.json, artifacts, git size |
| WS7 scale proof | ❌ owner/ops | — |
| WS8 secret incident | ❌ owner | P0 real-world |

**Current blocker:** the live ThreadsDashboard repo has an uncommitted mid-flight `codex/autoposter-hardening` worktree. It blocks BOTH WS4 (autoposter→live) and the TD half of WS2 (draftIngest). Commit or stash that worktree before TD can move.

---

## 4. WS1 — Permanent drift fix: mirror sync + parity CI gate (KEYSTONE)

**Goal:** make split↔monorepo drift impossible — a CI gate that FAILS when any monorepo mirror differs from its source split repo or was hand-edited.

**Repo:** `creator-os`, branch `codex/mirror-parity-gate`.

**Tasks:**
1. `mirror-sources.json` (repo root): one entry per mirror — `{ mirrorPath, sourceRepoPath, sourceCommit (pinned SHA), include[], exclude[] }`. Mirrors: `apps/dashboard`←`ThreadsDashboard`, `apps/contentforge`←`contentforge`, `python_packages/reel_factory`←`reel_factory`, `python_packages/campaign_factory`←`campaign_factory`, `python_packages/reference_factory`←`reference_factory`. **Exclude pipeline_contracts** (canonical in monorepo, opposite direction). `exclude[]` must drop all runtime/data: `node_modules/ .venv/ .next/ dist/ build/ **/output/ **/uploads/ **/campaigns/ **/models/ **/00_source_videos/ **/02_processed/ *.sqlite* *.db *.mp4 *.mov __pycache__/ .git/`.
2. `scripts/sync/mirror-sync.mjs`: read each source tree **at the pinned SHA** (`git archive`/work-tree of that commit, not the live working tree), copy include−exclude set into `mirrorPath` deterministically (stable order, normalized EOL), write `mirrorPath/MIRROR_PROVENANCE.json` (`sourceRepo`, `sourceCommit`, file count) + a generated-file banner. `--update` bumps each `sourceCommit` to that repo's current `main` HEAD.
3. `scripts/sync/check-mirror-parity.mjs`: re-run sync into a temp dir from pinned SHAs, diff vs committed mirror; ANY diff → exit non-zero, print offending paths. (One diff catches both stale-mirror drift and hand-edits.)
4. Wire `check:mirror-parity` into `package.json` and as a **required** monorepo CI gate.
5. Auth: split repos may be private (TD is). Read from local path when present, else clone via documented `MIRROR_SYNC_TOKEN`. Document in `scripts/sync/README.md`.

**Acceptance (prove each):** (a) hand-edit a file under `apps/dashboard` → `check:mirror-parity` FAILS naming it; (b) advance a split repo + `mirror-sync --update` → mirror updates, parity PASSES; (c) no runtime/data file appears in any mirror; (d) `packages/pipeline_contracts` untouched; (e) gate is a required CI check. **P0.**

**Note for later:** when a project is eventually promoted to monorepo-runtime (migration plan Phase 6), invert that one mirror entry's direction. reel/campaign/contentforge are eligible later; **TD never** (it stays standalone per the amended plan).

---

## 5. WS2 — Port the built fixes into the LIVE split repos

**Goal:** the running system actually gets the fixes already merged into the monorepo. Reference impl = creator-os `main`.

**campaign_factory** (branch `codex/audit-port`, off `main`):
- Commit the dirty caption-fallback removal: `adapters/threadsdash.py` — `instagram_post_caption` no longer falls back to `draft.get("content")`; block `instagram_post_caption_missing` for non-Story surfaces.
- Commit the inventory reservation: `asset_inventory_reservations`, transactional claim (`SELECT … FOR UPDATE`/advisory lock), `reserved`+`net` (net = ready − reserved), TTL release, readiness-on-net. (TTL = **owner decision §11**.)
- Acceptance: `grep 'draft.get("content")'` in IG-caption context = 0; concurrent-claim race test passes; readiness uses net; `uv run pytest campaign_factory/tests` green. **P0.**

**reel_factory** (branch `codex/audit-port`): add `review_truth.py` mirroring monorepo + commit the approval-gate producer (durable SQLite/server review: `maybe`, reviewer identity, decision-history, undo, resume, manifest-derived `approved/` view). Acceptance: decisions survive browser-clear/other machine; `maybe`≠rejected; producer in git; tests green. **P1.**

**ThreadsDashboard** (branch `codex/audit-port`, off TD `main`): add `draftIngest.ts` matching monorepo — deterministic (non-regex) auth parse (CodeQL-high fix), explicit-IG-caption enforcement, surface + visual-QC + identity blocks. Acceptance: bad envelope rejected; no regex in auth parse; `pnpm --filter juno33 typecheck`+`test`+`compat:check` green. **P1.**

---

## 6. WS3 — Remaining backend audit items (land in split repos, mirror follows)

1. **#5 ingest boundary — route CF through the validated endpoint.** CF currently still does raw service-role writes (`_insert_draft_post`). Route all production draft writes through the validated `draftIngest` path; keep raw write only behind an explicit local-test flag. Acceptance: bad envelope rejected at the live boundary; raw path unreachable in prod config. **P1.**
2. **Metadata normalization mandatory.** Wire `media_metadata.py` as a required post-render step in `reel_pipeline.py` (not optional). Acceptance: every produced mp4 has encoder/handler tags stripped; a test asserts it. **P1.**
3. **QC fail-closed everywhere.** Missing/unavailable visual QC OR identity verification must hard-block all production readiness/handoff paths (`campaign_factory core.py:~21280-21282`), not just the ingest endpoint. AI visual QC unavailability = blocking on prod path. Acceptance: a missing-QC asset cannot pass readiness. **P1.**
4. **Identity runtime pin.** Production render path must run under the `.venv` that has `insightface` (system python reports `unavailable`). Add a startup check that fails loudly if the provider is unavailable in production mode. Acceptance: prod render with no provider aborts, not silently passes. **P1.**
5. **#10 deprecation cleanup.** Guard `six_pack`/`grid-crop`/`grok-4` in `generate_assets.py` (5 hits) + `reel_gui.py` (8 hits) behind a flag that raises on call, or delete. Acceptance: deprecated paths unreachable without explicit override. **P2.**

---

## 7. WS4 — Autoposter hardening to LIVE ThreadsDashboard

**Goal:** the autoposter fixes already on creator-os `main` (and TD branch `codex/autoposter-hardening` `9ba87e8a8`) reach the live product.

- Reconcile the stray TD autoposter branches (`codex/autoposter-content-performance-fix`, `-content-quality-hotfix`) against `codex/autoposter-hardening` — confirm no conflicting/abandoned work.
- After review, merge `codex/autoposter-hardening` → TD `main`. Verify gatePassToken publish-time revalidation, publish-time discoverability re-check, llmJudge fail-closed + provider router, conservative approval default, hard-block duplicate fingerprints, cross-account media-reuse block are all present on `main`.
- Acceptance: TD `main` contains `gatePassToken.ts` + `discoverabilitySafety.ts` publish-time call; `pnpm --filter juno33 test` green on `main`; report merge SHA. **P0 (live safety).** Proven-account bar = **owner decision §11**.

---

## 8. WS5 — Frontend (merge + finish)

- Reconcile `codex/frontend-cleanup` vs `codex/frontend-cleanup-rebased`; keep one, merge to TD/monorepo per source-of-truth (TD frontend = TD repo).
- Confirm landed: Radix standardized on unified `radix-ui`; route-shell extraction for Composer/Autopilot. Run a **bundle analysis** and confirm heavy pages chunk-split as intended (the audit's open verification).
- **P2 cleanup:** document + enforce the `ui/` vs `shadcn/` boundary (compat:check rule rejecting raw `shadcn/` imports in routes); registry-add review workflow; converge Zod to a single major; verify `lucide-react` provenance.
- Acceptance: per `FRONTEND_AUDIT_2026-06-16.md` fix list; typecheck + tests + compat:check green; bundle evidence attached. **P2.**

---

## 9. WS6 — Repo maturity / CI hardening

1. **Wire gitleaks into CI** (`creator-os/.gitleaks.toml` exists, unused) with a `juno_ak_` rule; add to the security workflow as a gate. **P1.**
2. **Add lint + typecheck** to the pytest-only split Python repos (`reel_factory`, `campaign_factory`, `reference_factory`). **P2.**
3. **Delete PROOF.json theater** (4 files incl. `CAPTION_OUTCOME_TRACKING_V1_PROOF.json`, `CLOSED_LOOP_PROOF.json`) or convert to real tests. **P2.**
4. **Untrack artifacts:** `ThreadsDashboard/output/` screenshots; shrink the 740 MB `.git` (history rewrite — coordinate with the secret-incident purge in WS8 to do one rewrite, not two). **P2.**
5. Confirm Trivy/CodeQL/Scorecard/Dependency-Review gates are wired on the public repos. **P2.**

---

## 10. WS7 / WS8 — Owner-driven (flag, don't auto-execute)

**WS7 — Scale proof (operational):** before approving 50/100/200 accounts, run live-shaped load tests + a QStash-outage and reconciliation-drain proof. The 50 gate is `publishability_pass` throughput, NOT inventory (audit risk #9). Not a code change — schedule it. **P1 (operational).**

**WS8 — Secret incident (owner, highest real-world urgency):** in provider consoles — rotate every key in the leaked `.env.production` (`sk_live_`, `SUPABASE_SERVICE_ROLE_KEY`, `ENCRYPTION_KEY`, `CRON_SECRET`, Meta/Threads/IG); re-encrypt stored OAuth tokens (ENCRYPTION_KEY changed); remove `TD_API_KEY` from tracked `.mcp.json`; purge `.env.production` from git history (`git-filter-repo`, commits `a5c6dcf39`, `c42e8bfb9`) + force-push + invalidate clones. **Order: rotate FIRST, then purge** (purging before rotating leaves the leaked keys valid). Coordinate the history rewrite with WS6.4. **P0 (real-world).** Codex cannot do the console steps; it can prepare the filter-repo script + the `.mcp.json` removal.

---

## 11. Owner decisions — RESOLVED (2026-06-16)

All four answered. No open questions block execution.

1. **Inventory reservation TTL** (WS2 campaign_factory) — **7 days.** An unused reservation auto-releases after 7 days; readiness counts net = ready − active-reservations.
2. **Proven-account bar** (WS4 autoposter conservative default) — **accept Codex default:** a new account stays in `needs_review` until it has **12 posts of history AND (avg ≥50 views/24h OR ≥8% of posts cleared 100 views)**, then graduates to auto-publish. Explicit opted-in thresholds preserve existing behavior.
3. **Higgsfield budget** (cost preflight, already built) — **cap = current plan balance; hard-stop as balance approaches zero; never overspend the existing plan / no auto-topup.** Set `HIGGSFIELD_DAILY_BUDGET_USD` and `HIGGSFIELD_MIN_BALANCE_USD` to values that drain only the current plan balance and stop before exhausting it; `HIGGSFIELD_RUN_MAX_ASSETS` conservative. (Owner can fetch exact live balance to set the numbers; preflight reads balance and blocks below the floor.) Budget governs only paid image/video generation — it does NOT constrain this remediation (code/CI burns no generation credits).
4. **reel/campaign/contentforge long-term home** — **Option A now** (stay split; monorepo = referee/mirror). These three are **eligible for later monorepo-runtime unification** (migration plan Phase 6) once parity is proven — owner is open to it. **ThreadsDashboard is permanently standalone and never unified.** When a tool is later promoted, invert its WS1 mirror entry direction (split→monorepo becomes monorepo-as-runtime); TD's mirror entry is never inverted.

---

## 12. Definition of done

The remediation is complete when all are true:

```json
{
  "mirrorSyncAndParityGateLive": false,
  "splitReposPorted_caption_inventory_reviewTruth_draftIngest": false,
  "autoposterHardeningOnLiveTDMain": false,
  "ingestBoundaryEnforcedLive": false,
  "metadataNormalizationMandatory": false,
  "qcFailClosedEverywhere": false,
  "identityProviderPinnedInProd": false,
  "deprecatedPathsGuardedOrDeleted": false,
  "frontendMergedAndP2Done": false,
  "gitleaksInCI": false,
  "proofJsonTheaterRemoved": false,
  "scaleProofCompleted_ownerOperational": false,
  "secretIncidentClosed_ownerConsole": false,
  "noSchedulingOrPublishingBehaviorChanged": true
}
```

Flip each to `true` only with a cited passing command. Do not mark the suite closed while any runtime fix is monorepo-only and the live split repo lacks it.

---

## 13. How Codex should report per workstream

For each: branch + SHAs; exact test commands run + counts; grep evidence for acceptance; explicit monorepo-vs-live status; any owner decision hit; anything that couldn't be safely matched between split and monorepo. No "done" without the receipt.
