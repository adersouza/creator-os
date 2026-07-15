# Creator OS System Map

This is the durable operator map for the Creator OS source monorepo. Keep it
aligned with `AGENTS.md`, `README.md`, `PIPELINE_STATE.md`, and the code. It
describes ownership and evidence; it does not imply deployment or a successful
live run.

## Truth Levels

Creator OS reports four different states. Never collapse them into one:

1. **Implemented locally**: code exists in a checkout and local tests may pass.
2. **Merged to `main`**: GitHub `main` contains the code and exact-SHA CI passed.
3. **Promoted to runtime**: `/Users/aderdesouza/Developer/creator-os-runtime`
   was explicitly updated to a recorded Git SHA.
4. **Proven operationally**: a bounded real run produced the required receipts,
   state transitions, and downstream evidence.

`/Users/aderdesouza/Developer/creator-os` is the source integration checkout.
The runtime checkout is separate and never updates merely because `main`
changes. ThreadsDashboard is a separate product repository and deployment.

## Ownership

| Component | Responsibility | Canonical source | Primary state |
|---|---|---|---|
| Reference Factory | Teaches: intake, review labels, winner patterns, prompt packs, audio recommendations, outcome learning | `python_packages/reference_factory/reference_factory` | `REFERENCE_FACTORY_DB` and `REFERENCE_FACTORY_DATA_ROOT` |
| Reel Factory | Creates: Soul stills, static MP4s, optional motion/Kling, caption placement/rendering, asset lineage | `python_packages/reel_factory/reel_factory` | local media, manifests, render queue, caption banks, lineage sidecars |
| Campaign Factory | Decides: campaign plans, account assignment, inventory/readiness, spend gates, QC requests, draft construction, performance learning | `python_packages/campaign_factory/campaign_factory` | `CAMPAIGN_FACTORY_DB` and campaign artifact directories |
| ContentForge | Judges and blocks: PDQ/SSCD collision checks, sibling distinctness, OCR/safe-zone/readability/watchability and quality evidence | `packages/contentforge` | request-scoped output under ignored local runtime directories |
| Pipeline Contracts | Validates cross-package and cross-repository payloads | `packages/pipeline_contracts/pipeline_contracts` | committed schemas plus generated TypeScript |
| ThreadsDashboard | Receives drafts, owns approval/scheduling/publishing, account data, Supabase product state, analytics and performance history | external `/Users/aderdesouza/Developer/ThreadsDashboard` | Supabase and its deployed services |

`creator_os_core` is limited to genuinely shared authentication, atomic file,
SQLite, vector, media-probe, and global runtime-guard helpers. Package-specific
policy stays with its owning package.

## Active End-to-End Pipeline

```text
reference intake
  -> Reference Factory analysis and operator labels
  -> canonical reference bank / pattern cards / audio recommendations
  -> Campaign Factory creative plan and account assignment
  -> Reel Factory direct Higgsfield Soul still
  -> mandatory free static MP4 for accepted stills
  -> optional motion edit or explicitly approved best-only Kling
  -> Reel Factory caption placement/rendering and lineage
  -> ContentForge headless JSON QC and distinctness verdict
  -> Campaign Factory readiness and pipeline-contract validation
  -> HMAC-signed draft-only export
  -> ThreadsDashboard approval, native-audio proof, schedule and publish
  -> post metric history
  -> performance sync and Campaign/Reel/Reference learning fan-out
```

Campaign Factory is the only campaign control brain. ContentForge returns
evidence and a verdict; it does not decide campaign policy. Creator OS can
create, validate, recommend, and export drafts. ThreadsDashboard is the only
production scheduling and publishing owner.

## Creative Workflow Modes

- `library_reuse`: select approved existing media without provider generation.
- `soul_static`: generate Soul still candidates and a zero-cost static MP4 for
  each accepted still.
- `motion_edit`: create a deterministic local motion edit while retaining the
  static fallback.
- `best_only_kling`: animate only an approved rank-one candidate after a
  separate finite spend approval.
- `reference_video_remix`: analyze an operator-selected short reference video
  as motion structure, create new Soul endpoints, then plan Seedance or Kling.

All modes require human review. None grants publishing authority.

## Operator And Automation Entrypoints On Current Main

### Repository commands

- `make install`, `make reel-models`, `make test`, `make verify`, and
  `make backup-runtime` own setup and verification tasks.
- Root `pnpm` scripts own static gates, contract generation, architecture,
  artifact hygiene, Graphify refresh, secret scanning, and the current
  fixture-backed `doctor`.
- `campaign-factory` is the installed Campaign Factory CLI. It contains the
  campaign preparation, generation-mode, QC/readiness, draft-export, learning,
  and reporting commands.
- `python -m reference_factory.cli` is the Reference Factory CLI.
- Reel Factory currently exposes module commands and a five-command shell
  wrapper under `scripts/run/reel-factory`.
- ContentForge exposes only the bounded stdin/stdout JSON commands
  `similarity` and `variant-pack`; it has no browser or HTTP server.

### Machine automation launchers

- `scripts/run_threadsdash_performance_sync.sh` pins PATH, clears inherited
  Python state, loads machine-local configuration, validates the configured
  campaign/database, then runs performance sync and learning fan-out.
- `scripts/run_learning_cohort_daily.sh` runs the state-mutating daily cohort
  job only after loading the same machine-local configuration.
- `scripts/run_weekly_improvement_digest.sh` runs the weekly readout.
- `scripts/run_campaign_factory.sh` loads the finite provider-credit policy
  before any Campaign Factory generation command.
- `scripts/backup_runtime_state.py` performs SQLite-safe runtime backups and
  excludes credentials.

These launchers are intentionally thin. Real LaunchAgents and machine-local
environment files live outside Git and outside this repository's authority.

## Current Browser And Compatibility Surfaces

- **ContentForge:** already headless. Its old Next.js/product UI is absent.
- **Campaign Factory:** `campaign-factory serve` still mounts a committed local
  browser dashboard and JSON API. No production launcher calls the browser
  dashboard; the static dashboard duplicates ThreadsDashboard product
  ownership. The underlying JSON/repository behavior is separately tested.
- **Reference Factory:** `review-server` serves the manual gold/maybe/ignore
  review workflow and API. This remains an active operator-labeling surface,
  not a publishing/product dashboard.
- **Reel Factory:** committed `static/` browser assets are not mounted by a
  current app. `operator_tools.py` is a large legacy HTTP-shaped compatibility
  surface with no runtime or package caller; its behavior is exercised only by
  compatibility-era tests.
- **Flat Reel Factory modules:** top-level files such as `generate_assets.py`
  and `caption_bank.py` are 13-line import shims for canonical
  `reel_factory.*` modules. Internal imports and tests still use them, so callers
  must be migrated before deletion.
- **Root `pipeline_contracts`:** `pipeline_contracts/__init__.py` is an import
  shim only. It contains no schema mirror.

## Active, Compatibility, And Legacy Generation Code

### Active

- Direct reference-image Higgsfield Soul generation with captured provider
  prompt and lineage.
- Accepted still -> free static MP4.
- Optional local motion edit and explicitly approved Kling/Seedance planning.
- Caption-bank selection, placement scoring, safe-zone checks, and rendering.
- Identity, anatomy, QC, provider-cost preflight, receipts, and failure records.

### Compatibility-required on current main

- `deprecated_generators.py` is actively imported by generation code to fail
  closed when retired generator names are requested.
- FFmpeg-dependent probing, static MP4, caption rendering, motion, and
  ContentForge paths have active callers.
- Some grid/prompt-analysis helpers are still imported by active QC and
  generation modules; they cannot be deleted as a directory-sized guess.
- `learning_fanout.py` is called by the performance-sync launcher.

### Legacy or experimental

Grok/grid prompt flows, Qwen/Ollama/Florence visual-schema extraction, panel
fan-out experiments, and `_grok.json` workflows are not the default path. They
may be deleted only when imports, command entrypoints, tests, and runtime
launchers all prove no active caller. Legacy paths that remain must stay out of
normal operator help and default execution.

## State And Artifact Ownership

- Campaign Factory SQLite: configured by `CAMPAIGN_FACTORY_DB`; never infer a
  runtime database from the source checkout.
- Reference Factory SQLite/data: `REFERENCE_FACTORY_DB` and
  `REFERENCE_FACTORY_DATA_ROOT`.
- Reel Factory state: manifest/render-queue SQLite, local source/rendered media,
  caption banks, identity references, model files, review packages, and lineage
  sidecars.
- Generated evidence: ignored runtime/output directories or explicit committed
  fixtures only.
- Machine configuration: `~/.creator-os/*.env`, LaunchAgent plists, provider
  credentials, and deployment configuration; never committed.
- ThreadsDashboard state: external Supabase/product runtime; read or mutate only
  through explicitly authorized workflows.

Generated media, local databases, logs, model weights, provider receipts,
Graphify output, and temporary evidence are not committed source.

## Contract Source Of Truth

Shared hand-edited schemas live only in:

`packages/pipeline_contracts/pipeline_contracts/schemas`

Generated TypeScript lives at:

`packages/pipeline_contracts/typescript/generated-schemas.ts`

Run `pnpm sync:contracts` after a schema edit and `pnpm check:contracts` before
commit. Never hand-edit generated TypeScript. ThreadsDashboard owns its external
consumer snapshot; Creator OS verifies parity read-only.

## Safety Coverage

- Pipeline Contracts: schema generation, validators, consumer parity, HMAC and
  draft payload shapes.
- Campaign Factory: spend quote/reservation/consumption/cancellation, readiness,
  state transitions, account assignment, poisoned/ambiguous learning rows,
  draft-export gates, provider failures, performance sync, and HMAC handoff.
- Reel Factory: direct-reference lineage, identity/QC, static fallback, caption
  placement, provider-cost preflight, generation failures, and review truth.
- Reference Factory: labeling/ranking, reference intake, outcomes, provider
  readiness, prompt records, audio, and learning exports.
- ContentForge: similarity, detector calibration, QC/readiness, variant packs,
  OCR/safe-zone evidence, FFmpeg safety, and Campaign Factory response parity.
- Integration: cross-pipeline contracts, ContentForge handoff, performance
  learning, backup behavior, architecture rules, and artifact hygiene.

Tests that only prove a compatibility facade delegates to canonical code can be
removed with that facade. Safety, contract, data-integrity, spend, approval,
lineage, failure, and state-transition coverage must remain.
