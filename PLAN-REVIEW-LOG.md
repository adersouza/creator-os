# PLAN-SCHEDULER Review Log

## Phase 0 — Render/export identity

- Added real frame-sampled pHash and exact byte fingerprint generation in Reel Factory.
- Render lineage is now emitted for every completed render; approved export enriches legacy lineage before export.
- Source-family identity is carried from reference/learning lineage when present.
- Added deterministic image pHash and lineage carry-forward tests.

## Phase 1 — Fail-closed assignment eligibility

- Added one Campaign Factory evaluator and persisted `origin_account_id`.
- Gated `distribution_plans`, `asset_account_assignments`, `asset_inventory_reservations`, and Reel-ledger promotion writes.
- Mirrored missing-identity/origin behavior in Reel Factory posting-ledger UX.
- Added readiness/review blocked counts and explicit `missing_identity_metadata` reasons.

## Phase 2 — Contract and parity

- Added canonical `campaign_factory.assignment_eligibility.v1` schema, example, Python validator, CLI artifact export, and Reel Factory artifact consumption.
- Artifact retains `auto_posting: false` and exposes all decision inputs/matches.
- No Reel Factory import of Campaign Factory was introduced.

## Phase 3 — Trial intent and graduation

- Added `trial_group_id` across distribution, draft metadata, and handoff manifest.
- Added manual same-account idempotent graduation with unique `trial_post_id` mapping and no scheduled time.
- Added 1-hour/24-hour observation storage and nightly ranking report command.
- Added `main_reels_per_day=1` and `trial_reels_per_day=2` defaults in `account_content_requirements`.

## Phase 4 — ThreadsDashboard timing ownership

- Implemented in the isolated ThreadsDashboard branch `codex/plan-scheduler-v3`.
- Account-local timezones and configurable/derived base slots replace global New York timing.
- Deterministic jitter is bounded to plus or minus 20 minutes, stays on the local date, and respects account minimum gaps.
- Spring-forward and fall-back tests cover `America/New_York`; schedule-approved drafts remain timing-locked.

## Phase 5 — Promotion truth

- Added constrained `promotions` and typed append-only `promotion_events` tables.
- Promotion validates lineage fingerprint and removed file-hash fallback computation.
- Added idempotent legacy backfill, fingerprint reconciliation, stable CSV output, constrained identity authority, and latest-event status reads.
- Added concurrent unique-constraint proof with exactly one winner.

## Second audit — locked-plan closure

- Removed the remaining trial-graduation fallback to `rendered_assets.content_hash`; graduation now requires the lineage-v2 `contentFingerprint` before creating a regular plan or promotion.
- Made assignment eligibility evaluation side-effect-free and persist `origin_account_id` only after the assignment, reservation, distribution plan, or promotion bridge write succeeds.
- Made the Campaign Factory eligibility artifact authoritative when Reel Factory receives it; the local rule mirror is now compatibility fallback only. Added allowed and blocked parity tests.
- Added `account_group_id` to promotion state, indexed the exact identity/window lookup on the promotion store, and stopped rescanning campaign ledger rows for cross-account reuse.
- Expanded typed promotion events with rendered asset, fingerprint, account, slot, and reason identity columns. Current status is the latest event for the exact identity key.
- Converted live uniqueness races into savepoint-backed typed skips and typed rejection events instead of transaction-wide failures.
- Made legacy backfill quarantine duplicate identities with a typed rejection and stable report row instead of raising `IntegrityError`.

## Verification and landing

- Creator OS `make verify` passes against the isolated ThreadsDashboard consumer: contracts, Ruff, formatting, mypy, architecture, artifact checks, both Next builds, 185 JavaScript/TypeScript tests, and 1,457 Python tests. The existing ContentForge lint baseline remains 23 warnings and 0 errors; 17 media-tool tests remain intentionally skipped when Tesseract is unavailable.
- Campaign Factory passes 702 tests, including fail-closed eligibility, promotion idempotency, migration quarantine, reconciliation, and the exactly-one-winner concurrency proof. Reel Factory passes all 574 tests with the optional vision/AI dependencies installed.
- ThreadsDashboard passes 5,195 tests (1 skipped, 3 todo), typecheck, Biome lint, compatibility checks, contract parity, migration replay lint, and its production build/bundle budgets.
- Unblocked the existing Tailwind 4 build mismatch in both Creator OS Next apps by switching their PostCSS integration to `@tailwindcss/postcss`.
- Landing is isolated to `codex/plan-scheduler-v3`; no merge or deployment is performed by this plan.
- No production deployment or autoposter state change is authorized by this plan.
