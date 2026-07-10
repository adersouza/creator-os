# HANDOFF-AUDIT1 — items that need the operator or another repo

Produced at the end of the audit-1 repair session (tasks: reel_factory
`save_config` fix, Tailwind 4 PostCSS repair, rotted-script repair,
architecture-guard hardening, stale-doc cleanup). Everything fixable inside
this monorepo was fixed in-session; the items below cannot be completed here.

## Needs the operator (this machine / accounts)

### 1. Install a dependency-cruiser-supported Node version (blocks `check:all`)
- Symptom: `pnpm check:arch:ts` (dependency-cruiser 18) hard-errors on the
  installed Node **25.9.0**: supported ranges are `^22||^24||>=26`.
- Blast radius: `pnpm check:arch`, `pnpm check:all`, and the positive control
  in `scripts/test-architecture-guards.sh` all fail on this machine. The TS
  architecture boundary has effectively **never been checked locally** here —
  the old guard test "passed" only because the tool crashed (fixed this
  session: the script now runs clean-tree positive controls and asserts the
  failure log names the injected fixture, so tool crashes fail loudly).
- Action: install node@24 (e.g. `brew install node@24` and put it first on
  PATH, or add a version manager + `.nvmrc`), then run
  `pnpm check:arch:ts` and `bash scripts/test-architecture-guards.sh` to
  confirm all three legs pass. Consider committing an `engines`/`.nvmrc` pin
  so this is caught at install time.
- Verified this session: both Python guard legs work end-to-end (clean tree
  passes; injected fixtures rejected with
  `pipeline_contracts must not import campaign_factory` and
  `reel_factory must not import campaign_factory`). Only the TS leg is blocked.

### 2. Real-provider / credentialed runs
- The repaired proof scripts (`caption_outcome_e2e_proof.py`, smoke scripts,
  root `test_integration.py`) validate against fakes/local SQLite. Runs against
  real Supabase/provider backends need operator-held credentials and should be
  kicked off manually.

## Needs the ThreadsDashboard repo (separate repo)

### 3. PLAN-SCHEDULER Phase 4 — footprint reduction (relocated per review)
- Per `PLAN-SCHEDULER.md` ("Phase 4 — Footprint reduction lives in
  ThreadsDashboard"): per-account base slot times + real per-account timezones
  (replacing uniform America/New_York 10:00/15:00/20:00), deterministic
  ±20 min jitter seeded by (account, date, slot), clamped to local date,
  respecting `min_gap_hours`, DST via account-local tz → UTC with tests on
  both US transition dates.
- Monorepo side is already tolerant: `distribution.py` treats slot times as
  preferences and sync-back makes no equality assertions on final times.

### 4. Contract-change re-verification against the live consumer
- Creator OS intentionally has no committed `apps/dashboard` source mirror
  (`CREATOR_OS_SYSTEM_MAP.md` — do not restore it). Any change to
  `packages/pipeline_contracts` schemas is only verified here via the
  generated mirror + sync checks; the ThreadsDashboard consumer must be
  re-verified in its own repo after schema changes made this session.

## Needs the split reel_factory repo (or a rewrite)

### 5. `audio_library_import.py` was never migrated
- `docs/audio_pool_strategy.md` documented
  `python_packages/reel_factory/audio_library_import.py`; the file does not
  exist in this monorepo and has no git history here. Either migrate it from
  the split reel_factory repo or rewrite it.
- Interim workaround (doc annotated in-place): drop the MP3 into
  `python_packages/reel_factory/03_audio_library/` with a JSON proof sidecar
  matching the existing entries (title, artist, source, license, license URL,
  page URL, tags).

## Intentional non-issues (checked, do not "fix")
- `apps/dashboard` mention in `CREATOR_OS_SYSTEM_MAP.md` is a deliberate
  negative reference.
- `orchestrator.toml` / `orchestrator_ticks/` under
  `python_packages/reel_factory/project_data/` are runtime-created; docs
  describe creation, not existing files.
- Root `pipeline_contracts/` is a generated compatibility mirror (see
  PLAN-SCHEDULER audit log) — edit canonical `packages/pipeline_contracts`
  and run `pnpm sync:contracts`; do not delete the mirror.
- `docs/archive/**` stale paths are archived history, left as-is.
