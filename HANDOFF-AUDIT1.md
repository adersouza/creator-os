# HANDOFF-AUDIT1 — items that need the operator or another repo

Produced at the end of the audit-1 repair session (tasks: reel_factory
`save_config` fix, Tailwind 4 PostCSS repair, rotted-script repair,
architecture-guard hardening, stale-doc cleanup). Everything fixable inside
this monorepo was fixed in-session; the items below cannot be completed here.

## Follow-up resolution (2026-07-10)

All code-level follow-ups are now resolved on `codex/audit1-handoff` or verified
on the existing ThreadsDashboard scheduler branch. The only item that remains
external is a paid/credentialed provider acceptance run: this checkout has no
provider credentials, and `pipeline_smoke.py --real-providers` explicitly exits
because the real-provider path is not implemented. No scheduling, publishing,
or paid-provider action was performed.

Final verification: Creator OS passes 187 JavaScript/TypeScript tests and 1,469
Python tests (including 153/153 ContentForge tests), plus both production builds
and every static/contract/architecture gate. ThreadsDashboard passes 5,195 tests
(1 skipped, 3 todo), typecheck, compatibility/contract parity, Biome lint,
migration lint, production build, and bundle budgets.

## Needs the operator (this machine / accounts)

### 1. Install a dependency-cruiser-supported Node version (blocks `check:all`)

**Resolved:** Homebrew Node 24 is installed; `.nvmrc` and the root `engines`
constraint now reject the unsupported Node 25 line. `check:arch:ts` and the full
architecture positive/negative fixture controls pass under Node 24.
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
  currently mergeable with all required checks green (8 passing, 3
  intentionally skipped). Merge order: **#378 first**, then rerun
  [ThreadsDashboard #268](https://github.com/adersouza/ThreadsDashboard/pull/268)
  checks and undraft. Merging is an operator decision; nothing is merged,
  deployed, scheduled, or activated yet (autoposting off, trial graduation
  manual).

### 2b. Pre-existing migration-replay failure blocking #268
- #268 has two red checks: the contract-compare-vs-main job (self-heals once
  #378 merges) and `Clean migration replay on preview branch`, which is a
  **pre-existing unchanged Supabase migration failure** at
  `20260618221024_drop_unused_posts_indexes.sql`: `DROP INDEX CONCURRENTLY`
  cannot run inside the replay pipeline. It will NOT self-heal when #378 lands
  and needs its own ThreadsDashboard migration repair before #268 can be
  undrafted.

### 2c. Graphify refresh blocked — no LLM API key configured
- Codex's PLAN-SCHEDULER v3 run could not complete the Graphify refresh
  because no LLM API key is configured on this machine. Repository
  architecture gates passed independently. Operator must set the key, then
  rerun the refresh.

### 2. Real-provider / credentialed runs

**External by design:** credential names were checked without exposing values;
none are present. The repository has no implemented real-provider acceptance
path to invoke safely. Local SQLite/fake-provider proof remains the authoritative
non-mutating evidence until that separate acceptance harness exists.
- The repaired proof scripts (`caption_outcome_e2e_proof.py`, smoke scripts,
  root `test_integration.py`) validate against fakes/local SQLite. Runs against
  real Supabase/provider backends need operator-held credentials and should be
  kicked off manually.

## Needs the ThreadsDashboard repo (separate repo)

### 3. PLAN-SCHEDULER Phase 4 — footprint reduction (relocated per review)

**Resolved in ThreadsDashboard:** `codex/plan-scheduler-v3` contains per-account
base slots/timezones, deterministic ±20 minute jitter, local-date clamping,
minimum-gap enforcement, and both 2026 US DST transition tests. Targeted tests,
typecheck, and compatibility checks pass.
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

**Resolved:** ThreadsDashboard `compat:check` passes against the Creator OS
PLAN-SCHEDULER worktree and reports its pipeline-contract snapshot in sync.
- Creator OS intentionally has no committed `apps/dashboard` source mirror
  (`CREATOR_OS_SYSTEM_MAP.md` — do not restore it). Any change to
  `packages/pipeline_contracts` schemas is only verified here via the
  generated mirror + sync checks; the ThreadsDashboard consumer must be
  re-verified in its own repo after schema changes made this session.

## Needs the split reel_factory repo (or a rewrite)

### 5. `audio_library_import.py` was never migrated

**Resolved:** the importer was rewritten in the packaged Reel Factory module
with its documented root compatibility entrypoint. It supports local files and
direct HTTP(S) downloads, validates audio with `ffprobe`, installs atomically,
uses SHA-256 identities, and writes idempotent license/provenance sidecars.
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

**Resolved:** the current reproduction was nine failures. Repairs cover the
workspace Python runtime, declared PDQ dependency, calibrated OCR/noise handling,
honest no-overlay/OCR-unavailable advisory semantics, preserved hard quality
gates, and corrected calibration fixtures. The formerly failing calibration,
report, and similarity route cases now pass.
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

## 8. Audit-coverage gaps (unfixed, no plan section — need owner/decision)

Cross-check of the three audit reports (operational robustness, monorepo,
deletion) against session commits + PLAN-SCHEDULER: ~85% covered. These 7
findings have **no fix, no handoff line, and no plan section** yet:

1. **Performance-sync truncation (audit A4)** — `sync_performance_snapshots`
   fetches one `posts` page with `limit=1000` and no offset/`Content-Range`/
   truncation check (`adapters/threadsdash.py:1318` in current tree; audit
   refs 4157/4674–4699/4702–4730). If more rows exist, the run reports
   success and advances `content_graph_sync_state` on the truncated set —
   silent incomplete learning data. Needs pagination + truncation detection.
2. **Crash recovery / kill -9 (audit A5)** — pipeline jobs commit `running`
   before work (`events.py:199`); hard crash leaves the row running
   permanently (no lease/reclaim/auto-fail). Multiple file-first/DB-second
   sagas orphan files (`threadsdash.py:825/933`, `contentforge.py:314`,
   `reel_execution.py:167`, `asset_import.py:288`). Audit recommended one
   operational-hardening plan section covering crash recovery + API
   pagination + CI gaps — never created.
3. **Legacy Supabase ambiguous POST retry (audit A6)** — check-then-insert
   with plain POST, no idempotency key, 3x retry on timeout/429/5xx
   (`threadsdash.py:1667`, `5628–5641`, `5692–5709`). Gated behind
   `CAMPAIGN_FACTORY_ENABLE_LEGACY_SUPABASE_WRITES=1`, so low likelihood;
   either add an idempotency key or document the flag as unsafe/deprecated.
4. **Assignment/distribution-plan idempotency (audit A1, partial)** —
   Phase 5 constrains *promotion* uniqueness (PLAN-SCHEDULER.md:77), but it
   is unverified that it extends to `asset_account_assignments` and
   `distribution_plans` (no unique asset/account/slot constraint;
   `db.py:621/709`, `campaign_overview.py:292`, `distribution.py:123`;
   `plan_distribution(replace=True)` commits delete separately at
   `distribution.py:382`). Audit proved duplicate rows under rerun. Verify
   Phase 5 scope covers these tables or extend it.
5. **Intersection-masking consumer-contract test (audit B5)** —
   `test_threadsdash_consumer_contracts.py` compared only the schema-set
   intersection, so schemas *missing* from ThreadsDashboard pass silently.
   Session grep was inconclusive on whether this was since fixed — verify,
   and if not, assert required v2 schemas exist in the consumer.
6. **Dead contracts (audit B12)** — `repurposing_plan.v1` has no production
   producer or consumer; `front_generation_plan.v1` has no machine consumer.
   No keep/remove decision recorded. Decide and log in PLAN-SCHEDULER audit
   log.
7. **`local_api_auth.py` triplication (deletion audit #6)** — three
   identical 70-LOC copies (campaign/reel/reference), actively imported by
   all three FastAPI apps. Audit: consolidate only with a packaged shared
   owner + app-level auth tests. Deferral was decided but not documented
   anywhere until now.

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
