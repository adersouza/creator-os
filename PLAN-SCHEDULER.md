# PLAN-SCHEDULER — Master Cross-Account Posting Schedule (v3)

Status: IMPLEMENTED AND VERIFIED (2026-07-10). Creator OS PR #378 is open,
mergeable, and green; ThreadsDashboard PR #268 contains Phase 4 and remains a
draft pending #378 plus an unrelated historical migration-replay repair. No
merge, deployment, scheduling activation, publishing, or autoposter activation
was performed.
Scope: cross-account distribution safety, trial-reel intent, posting-time footprint. Human-in-the-loop preserved; autoposter stays OFF.

## Authority decision (settled)

Scheduling authority = **Campaign Factory distribution/assignment state + ThreadsDashboard `campaignSchedule.ts`**. `posting_ledger.py` (reel_factory) is local operator tooling, noncanonical (per `campaign_factory/readiness_report.py` classification). Rules unify INTO campaign_factory; ledger consumes.

Hard constraint (verified, `pyproject.toml` import-linter contracts): `reel_factory` may NOT import `campaign_factory`. Any rule sharing must go through a contract/CLI boundary, not Python imports.

## Phase 0 — Identity metadata reality check (replaces v2's fictional dependency)

Corrections from review:
- PLAN.md lineage work (S1/S6) covers `source_family_id` lineage, NOT perceptual fingerprints.
- `campaign_factory/inventory_perceptual.py` only *copies* perceptual fields from existing metadata; `perceptualClusterId` falls back to the fingerprint, and nothing in the repo *computes* a perceptual fingerprint. A "% populated" audit can pass on vacuous values.

Revised Phase 0:
1. No numeric threshold gate. Ship the Phase 1 fail-closed gate and let its `missing_identity_metadata` blocked-count be the metric; drive it toward zero (Codex Q3 answer: convergence over threshold).
2. Add a real perceptual fingerprint computation step (e.g., frame-sample pHash over rendered output) populating `perceptualFingerprint` at render/export time in reel_factory, carried through lineage. Separate small work item; without it, "perceptual reuse" guards are name-only.
3. `source_family_id` coverage rides on PLAN.md S1/S6 as before.

## Phase 1 — Fail-closed identity gate

Rule: asset with empty `source_family_id` AND empty real perceptual identity is ineligible for multi-account distribution. Conflict reason `missing_identity_metadata`. No raw `content_fingerprint` fallback (re-encodes defeat it; exact-byte dupes already blocked campaign-wide).

Corrections from review — gate must cover EVERY canonical write path, not just one:
1. `distribution.py` `plan_distribution` / assignment path
2. Inventory reservation path (`campaign_factory/inventory_reservations.py`)
3. Ledger→campaign migration bridge (`campaign_factory/reel_ledger_promotion.py`) — writes assignments directly, would bypass a planner-only gate
4. Any CLI/manual assignment entry points (enumerate via grep for writers to `variant_account_usage` / assignment tables before implementation; list them in the PR)
5. Mirror in `posting_ledger.py` `_assignment_conflicts` for operator workflows

"Single-account origin" defined explicitly (schema has no authoritative origin account — verified concern): origin = account of the asset's FIRST persisted assignment; recorded at first assignment time as `origin_account_id` on the asset/plan row. Assets lacking identity metadata may only ever be assigned to their `origin_account_id`.

Surface blocked-asset count in review-queue and readiness report output — operator sees what needs backfill; plan doesn't silently shrink.

Tests: missing identity → conflict on each write path (including promotion bridge); populated identity + no nearby reuse → passes; re-encoded dupe sharing `source_family_id` → blocked cross-account within window; origin-account-only assignment allowed for unidentified assets.

## Phase 2 — Rule unification via contract boundary (not imports)

Correction: reel_factory→campaign_factory Python import forbidden by import-linter. Mechanism (Codex Q1):
1. Cross-account reuse rules (14-day window, `account_group_id` scoping, `reuse_cooldown_days`) become part of `distribution.py` validation — campaign_factory side, plain port from ledger logic.
2. Ledger gets rule decisions via contract, not import: campaign_factory CLI/export emits a **conflict/eligibility report artifact** (new small schema in `packages/pipeline_contracts/schemas/`, e.g. `assignment_eligibility.v1`) that `posting_ledger.py` reads during `create-plan` / `assign-approved-reels`. Ledger keeps operator UX; stops owning rules.
3. Export contract unchanged: `"auto_posting": False` stays.
4. Non-goal: merging `posting_slots` and `distribution_plans` storage.

Exit: conflict parity test — same inputs produce same conflicts from distribution planner and from ledger consuming the eligibility artifact.

## Phase 3 — Trial reels: feed the downstream support that already exists

Corrections from review (verified): ThreadsDashboard already has `api/_lib/instagramTrialReels.ts`; `campaign_draft_payload.v2.schema.json` already exists in `packages/pipeline_contracts/schemas/`; `draftIngest.ts` preserves `metadata` wholesale but ignores unknown top-level fields.

1. Trial intent carried per plan entry as `surface: "trial_reel"` (existing normalized surface) through assignment → draft payload.
2. Transport: put `trial_reel: bool` + `trial_group_id` inside the draft payload's existing metadata channel (`metadata.campaign_factory.*`), NOT as new top-level fields; additive update to `campaign_draft_payload.v2` schema (optional fields) — no v3 bump. Contract test against a captured `draftIngest.ts` fixture proving fields survive ingest and reach the `instagramTrialReels.ts` path.
3. Graduation: manual-approved, idempotent, same-account first. Nightly report ranks trials by 1h/24h metrics (PLAN.md sync). Operator approves; promotion creates a new main-feed plan entry on the SAME account; normal dedup governs any later cross-account rollout. Idempotency key: unique (trial_post_id → promotion_id). No auto-queue.
4. Cadence default: 1 main + 2 trials/day/account via `account_content_requirements`.
5. Exploration policy (original audit step 5) stays separate; trials only feed it data.

## Phase 4 — Footprint reduction lives in ThreadsDashboard (relocated per review)

ThreadsDashboard `campaignSchedule.ts` owns actual scheduled times; building a second timing engine in the ledger duplicates it. Monorepo does NOT implement jitter.

1. ThreadsDashboard side (separate repo, separate small plan): per-account base slot times + real per-account timezones (replace uniform America/New_York 10:00/15:00/20:00 — the actual footprint); deterministic ±20 min jitter seeded (account, date, slot), clamped to local date, respecting `min_gap_hours`; DST via account-local tz → UTC, tested on both US transition dates.
2. Monorepo side: `distribution.py` treats slot times as *preferences*, tolerates downstream time adjustment (no equality assertions on final times in sync-back).
3. Rule-change semantics: adjustments apply only to not-yet-approved items.
4. DROPPED (from v1): Latin-square rotation matrix — 14-day cross-account window dominates; negligible added protection.

## Phase 5 — Promotion tracking hardening: constraints over checks

Motivation: current tracking recomputes fingerprints on read (fallback chains → fail-open bugs like the empty-fingerprint bypass), enforces dedup via per-run in-memory sets (blind to concurrent/historical runs), and encodes state in status strings (implicit state machine, no enforcement). Fixed symptoms in reel_ledger_promotion; this phase removes the class.

1. Fingerprint once, at asset creation: `generated_asset_lineage.v2` carries `content_fingerprint`; promotion *validates* it, never computes it. Missing fingerprint = hard fail, no sha256 fallback chain. Delete fallback code paths from `reel_ledger_promotion.py`.
2. Dedup moves into the store: SQLite table `promotions` with `UNIQUE(content_fingerprint, account_id)` and `UNIQUE(account_id, posting_slot_id)`. Duplicate promotion becomes structurally impossible (IntegrityError → skip + reason), correct across concurrent runs. Cross-account reuse window (`DEFAULT_CROSS_ACCOUNT_REUSE_WINDOW_DAYS`) enforced by indexed query on the same table, not by rescanning ledger rows.
3. Append-only promotion event log: rows (asset_id, content_fingerprint, account_id, posting_slot_id, action, reason, ts). Current state = latest event per key; no mutation of status strings. `PROMOTED_REASON_PREFIX` / `NON_PROMOTABLE_STATUSES` string matching replaced by typed `action` enum. Ledger CSV becomes a derived export, not the source of truth.
4. Migration: backfill event log from existing ledger rows; one-time reconciliation report of rows whose recomputed fingerprint disagrees with lineage v2 (fix or quarantine before cutover). Dual-write window, then flip reads.
5. Tests: uniqueness violated under two concurrent promoters (one wins, one gets typed skip); missing-fingerprint hard-fails; backfill idempotent; derived ledger export byte-stable across re-runs.

Depends on Phase 1 (lineage v2 write path populated). Independent of Phases 3–4.

## Sequencing

Phase 0.2 (perceptual computation) ∥ PLAN.md S1/S6 → Phase 1 → 2 → 3 → 4 (optional, other repo) → 5 (after Phase 1; parallel with 3). Phases 1+3 carry most value; Phase 5 removes the dedup bug class. Each phase: tests + PLAN-REVIEW-LOG.md entry before next.

## Review log

- v1: Codex REJECT — wrong spine (posting_ledger), raw-hash fallback, rotation-matrix theater, trial label conflation.
- v2: Codex REJECT — fictional Phase 0 dependency (no perceptual computation exists; cluster falls back to fingerprint), gate missed write paths (reservations, promotion bridge), Phase 2 import direction forbidden by import-linter, v2 payload schema already exists, `instagramTrialReels.ts` already downstream, jitter belongs in ThreadsDashboard.
- v3 (this doc): all above incorporated; claims re-verified against `pyproject.toml`, `packages/pipeline_contracts/schemas/`, `ThreadsDashboard/api/_lib/instagramTrialReels.ts`, `inventory_perceptual.py`.

## Audit log

- Audit 1 — atomic writes (commits `f6ba0194`, `f0915e69`): all bare `write_text`/`json.dump` writers in campaign_factory, reel_factory, reference_factory migrated to `fileops.atomic_write_text`/`atomic_write_json` (146+ sites); helpers write temp file in same dir + fsync + `os.replace`.
- Audit 2 — broad-except triage, campaign_factory core (commit `ee7afe52`): narrowed subprocess/zlib handlers, added debug logging to previously silent report fallbacks; remaining sites deferred to audit 3.
- Audit 3 — broad-except triage, `app.py` + adapters (no code change): all 70 `app.py` sites are uniform API-boundary translation `except Exception as exc: raise HTTPException(400/404, str(exc)) from exc`, with `except HTTPException: raise` guards where internal 404s pass through; the two `record_event` sites also `fail_pipeline_job` and re-raise. All 16 adapter sites (contentforge 3, threadsdash 13) capture errors into failure events, result error lists, or blocker fields. No silent swallows. Open design note (deferred, API-semantics decision): internal server bugs surface as 400 with `str(exc)` in the body instead of sanitized 500.
- Audit follow-up — dead code/deps (commits `ffce2f76`…`cdcce152`): removed stray root `test_repurposer.py` runner, unused root `httpx` dep and `reel_factory` `einops` extra, stale `caption_banks` swipe-decision/intake-archive snapshots (recoverable via git history); repo-wide ruff I001 import-sort autofix. Deferred item RESOLVED (no action): root `pipeline_contracts/` is an intentional generated compatibility mirror, not a duplicate — `__init__.py` is a shim loading the canonical `packages/pipeline_contracts` package; `schemas/` + `typescript/` are written by `scripts/sync-pipeline-contracts.mjs` and verified by `scripts/check-pipeline-contracts-sync.mjs` (checked: currently in sync) and `scripts/doctor.py` `GENERATED_CONTRACT_PATHS`. Edit only canonical, then `pnpm sync:contracts`. Do NOT delete the root mirror.
## Implemented boundary summary

Campaign Factory owns distribution, assignment eligibility, trial intent, and promotion history. ThreadsDashboard owns exact scheduled times and publishing. Reel Factory's posting ledger remains noncanonical operator UX.

Safety invariants:

- `auto_posting` remains `false`; no implementation in this plan queues or publishes automatically.
- Missing source-family and real perceptual identity is fail-closed to the first persisted `origin_account_id`.
- Cross-account reuse policy is evaluated by Campaign Factory and exported as `campaign_factory.assignment_eligibility.v1`.
- Trial graduation is manual, same-account, idempotent, and creates an unscheduled regular-reel plan.
- Exact schedule times are account-local ThreadsDashboard decisions; Campaign Factory times are preferences.
- Promotion identity comes from generated lineage. Campaign Factory promotion never computes a fallback fingerprint.

Implementation phases:

1. Reel Factory render/export identity: exact SHA-256 plus frame-sampled pHash and source-family lineage.
2. Fail-closed gate at distribution, assignment, reservation, promotion, CLI, and ledger UX boundaries.
3. Shared eligibility contract artifact and parity consumption without cross-package imports.
4. Trial intent, captured ingest proof, manual graduation, 1h/24h ranking, and 1-main/2-trial cadence defaults.
5. ThreadsDashboard per-account timezone/base slots, deterministic plus-or-minus 20 minute jitter, minimum gaps, and DST proof.
6. Constrained promotion store, typed append-only events, idempotent backfill, reconciliation, and read flip.

Production deployment, scheduling activation, publishing, QStash, account health, and autoposter activation are outside this implementation.
