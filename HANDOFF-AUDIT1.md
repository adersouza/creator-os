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

### 2a. Merge decisions for PLAN-SCHEDULER v3 PRs (operator's button)
- [Creator OS #378](https://github.com/adersouza/creator-os/pull/378):
  verified 7/7 checks green. Merge order: **#378 first**, then rerun
  [ThreadsDashboard #268](https://github.com/adersouza/ThreadsDashboard/pull/268)
  checks and undraft. Merging is an operator decision; nothing is merged,
  deployed, scheduled, or activated yet (autoposting off, trial graduation
  manual).

### 2b. Pre-existing migration-replay failure blocking #268
- #268 has two red checks: the contract-compare-vs-main job (self-heals once
  #378 merges) and `Clean migration replay on preview branch`, which is a
  **pre-existing unchanged Supabase migration failure** — it will NOT
  self-heal when #378 lands. Needs its own fix in the ThreadsDashboard repo
  before #268 can be undrafted.

### 2c. Graphify refresh blocked — no LLM API key configured
- Codex's PLAN-SCHEDULER v3 run could not complete the Graphify refresh
  because no LLM API key is configured on this machine. Repository
  architecture gates passed independently. Operator must set the key, then
  rerun the refresh.

### 2. Real-provider / credentialed runs
- The repaired proof scripts (`caption_outcome_e2e_proof.py`, smoke scripts,
  root `test_integration.py`) validate against fakes/local SQLite. Runs against
  real Supabase/provider backends need operator-held credentials and should be
  kicked off manually.

## Needs the ThreadsDashboard repo (separate repo)

### 3. PLAN-SCHEDULER Phase 4 — footprint reduction (relocated per review)
- **STATUS UPDATE: delivered pending merge.** ThreadsDashboard PR #268
  (draft) implements this — account-local scheduling, deterministic ±20 min
  jitter, min gaps, DST handling, trial-intent transport. Remains open until
  Creator OS #378 merges and the item-2b migration failure is fixed. Original
  spec kept below for verification against the PR.
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

## Needs Codex (in-flight work — deliberately not touched)

### 6. 19 failing contentforge similarity/calibration tests (pre-existing)
- Observed in the follow-up fix session (commit `6005f1a6`); NOT caused by
  that commit — its diff (`monorepo-ci.yml`, `test/tool-availability.js`,
  `campaign_factory/db.py`) touches none of the failing code paths.
- Failing area was last changed by the Campaign Factory gating PRs
  (#79, #81, `c3ab1cff`) that Codex is actively iterating on, so it was left
  alone per "don't interrupt codex".
- Representative failures (`pnpm --filter contentforge test`):
  - `campaign-factory-calibration.test.js:116` —
    `good/campaign_factory_avconvert_render.mp4 overallVerdict` is `'fail'`,
    test expects `'warn'`.
  - `campaign-factory-report.test.js:80` — expects 0 missing-media entries,
    gets 8. Smells like fixture drift rather than logic.
  - `similarity-route.test.js` — multiple: upload-ready FFmpeg render fails
    instead of warning (line 219), hook-watchability blocking flag false
    (line 359), reference-match variation meter false (line 442), forced-OCR
    advisory-only, Apple Vision → Tesseract fallback, legacy-FFmpeg-metadata
    warn path, compression-review warn path.
- Full failure list: 19 total; pattern is verdicts coming back one severity
  harsher than tests expect (`fail` vs `warn`, blocking vs advisory) plus
  missing/renamed fixture media. Codex should reconcile the gating verdict
  matrix with the test expectations (or update fixtures) in one pass.

### 7. Follow-up session status (for context, all committed as `6005f1a6`)
- Fixed: tool-availability probe (`-version` **or** `--version`, so tesseract
  isn't misreported missing); `campaign_factory/db.py` SQLite hardening
  (timeout=30, busy_timeout=30000, WAL — matches
  `reel_factory.sqlite_utils.connect_sqlite`); CI now filters on
  `scripts/**` and runs `pipeline-contracts-ts` tests.
- Verified green before commit: campaign_factory Python suite (699 passed),
  pipeline-contracts-ts (21 passed). Only the item-6 contentforge failures
  remain red.

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
