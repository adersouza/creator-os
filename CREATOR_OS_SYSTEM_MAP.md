# Creator OS System Map

This is the durable source and runtime map. It describes ownership and
available evidence; it does not imply deployment or a successful live run.

## Four Truth Levels

1. **Implemented locally**: code exists in a checkout and local tests may pass.
2. **Merged to `main`**: GitHub `main` contains the exact commit and its required
   CI passed.
3. **Promoted to runtime**: the separate `creator-os-runtime` checkout was
   explicitly updated to a recorded Git SHA.
4. **Proven operationally**: a bounded real run produced receipts, state
   transitions, and downstream evidence.

Never collapse these into “working” or “deployed.” Source, runtime, machine
state, paid providers, and ThreadsDashboard production have separate evidence.

## Ownership And Dependencies

| Component | Responsibility | Canonical source | Depends on | Primary state |
|---|---|---|---|---|
| Reference Factory | intake, human labels, winner patterns, prompt packs, audio recommendations, outcome learning | `python_packages/reference_factory/reference_factory` | Pipeline Contracts and Creator OS Core | `REFERENCE_FACTORY_DB`, `REFERENCE_FACTORY_DATA_ROOT` |
| Reel Factory | Soul stills, free static MP4s, optional motion/Kling, placement/rendering, media lineage | `python_packages/reel_factory/reel_factory` | Pipeline Contracts, Creator OS Core, FFmpeg and optional local models/providers | local media, manifests, queue, caption banks, lineage sidecars |
| Campaign Factory | creative plans, inventory, assignment, readiness, spend gates, QC requests, draft construction, performance ingestion | `python_packages/campaign_factory/campaign_factory` | Reel Factory commands, ContentForge CLI, Pipeline Contracts, Creator OS Core | `CAMPAIGN_FACTORY_DB`, campaign artifact directories |
| ContentForge | PDQ/SSCD collision checks, sibling distinctness, OCR/safe-zone/readability/watchability, media evidence and blocking verdict | `packages/contentforge` | Node, FFmpeg/FFprobe and optional local OCR/fingerprint tools | request-scoped ignored local output |
| Pipeline Contracts | canonical schemas and validators | `packages/pipeline_contracts/pipeline_contracts` | standard validation libraries only | schemas and generated TypeScript |
| Creator OS Core | only shared auth, atomic file operations, SQLite, vectors, media probes, runtime paths, and global runtime guard | `packages/creator_os_core/creator_os_core` | foundational only; never imports factories | no owned business state |
| ThreadsDashboard | product UI, accounts, Supabase, approvals, scheduling, publishing, inbox, analytics, posting infrastructure | external `/Users/aderdesouza/Developer/ThreadsDashboard` | its own services and consumer contract snapshot | Supabase and deployed services |

Dependency direction is inward toward Pipeline Contracts and Creator OS Core.
Reel and Reference do not import Campaign ownership. Campaign may invoke
package-owned Reel/ContentForge commands but remains the only campaign brain.

## Active End-To-End Flow

```text
reference intake
  -> Reference Factory local analysis and operator labels
  -> reference_factory.knowledge_pack.v1 (Gold references, prompt/pattern cards,
     caption/audio patterns, measured provenance)
  -> Campaign Factory creative plan and account assignment
  -> Reel Factory direct Higgsfield Soul still + lineage
  -> mandatory local static MP4 for accepted stills
  -> optional motion edit or explicitly approved best-only Kling
  -> placement.py -> caption_render.py when an overlay has a safe lane
  -> ContentForge headless JSON QC and distinctness verdict
  -> Campaign Factory readiness and pipeline-contract validation
  -> HMAC-signed draft-only ingest request
  -> ThreadsDashboard approval, native-audio proof, scheduling, publishing
  -> post metric history
  -> performance sync
  -> Campaign/Reel/Reference learning fan-out
```

ThreadsDashboard is the only scheduling and publishing owner. Creator OS stops
at validated draft handoff.

## Creative Modes

- `library_reuse`: import an explicit media folder for an explicit model without
  provider generation. Folder and model are required; there is no proactive
  recommendation alias.
- `soul_static`: direct Soul still plus local static MP4.
- `motion_edit`: deterministic local motion while retaining the static fallback.
- `best_only_kling`: paid animation of one separately approved rank-one still.
- `reference_video_remix`: reference motion analysis plus new Soul endpoints,
  followed by an explicitly selected motion provider.

All modes are review-gated and require explicit selection; there is no active
generation default. Soul ID owns identity. Prompt and asset lineage are
retained. Native audio remains an intent, not a burned track.

## QC, Readiness, And Draft Handoff

Campaign Factory invokes ContentForge's local stdin/stdout JSON CLI. ContentForge
returns evidence and `pass`, `warn`, or `fail`; it does not change campaign
policy. Campaign Factory combines that evidence with approval, lineage,
assignment, collision, publishability, and contract checks.

Draft payloads validate against Pipeline Contracts before an HMAC-signed request
to ThreadsDashboard's draft-ingest endpoint. HMAC tests cover signature,
timestamp, and rejection behavior without sending real drafts. The supported
root command forces draft schedule mode and exposes explicit `--dry-run` versus
`--apply`; it has no scheduling or publishing command.

## Learning Return Path

The pinned performance launcher:

1. clears inherited virtualenv/Python state and pins PATH;
2. loads the private performance-sync environment;
3. verifies the exact campaign scope and SQLite database;
4. imports bounded ThreadsDashboard metric history;
5. runs `scripts/learning_fanout.py` into Campaign, Reel, and Reference ledgers.

`learning_fanout.py` remains active. A successful command or queue receipt is
not equivalent to real metric history; learning proof requires measured rows.

Reference Factory exports the versioned knowledge pack without mutating its
database. Campaign Factory validates its contract and content fingerprint,
preserves the pack's human labels and recommendation status verbatim, and
stores the imported pack in its canonical ledger. Campaign
`performance_snapshots` remains the only operational measured-facts source.
Reference-pattern evidence stays advisory and requires operator approval until
Campaign has at least three eligible measured examples for that pattern.

## Operator Command Surface

`scripts/creator-os` is the supported operator entrypoint:

| Command | Boundary |
|---|---|
| `status` | read-only live source/runtime/config/DB report; unprobed systems are `NOT_RUN` |
| `doctor` | read-only fixture-backed integrity audit |
| `reference-refresh --dry-run|--apply` | local Reference/Audio database and export workflow |
| `generate --list-modes` | read-only canonical mode catalog with cost and gates |
| `generate --mode <mode> --dry-run|--apply` | the only generation workflow; mode is mandatory and no mode may schedule or publish |
| `readiness` | read-only campaign readiness |
| `draft-export --dry-run|--apply` | bounded validated drafts only; never schedule/publish |
| `performance-sync --dry-run|--apply` | pinned metrics and learning workflow |

Package-local CLIs remain thin implementation boundaries:

- `campaign-factory`
- `python -m reference_factory.cli`
- `python -m reel_factory.<module>`
- `packages/contentforge/cli.mjs`

`CampaignFactory` is only the connection/settings composition root. Callers use
`factory.domains.<repository>` directly; it has no forwarding facade or dynamic
compatibility fallback. Repositories receive explicit callbacks/context rather
than a full `CampaignFactory` instance.

Deleted `scripts/run/*` aliases and flat Reel module facades no longer create
wrapper-calling-wrapper chains. The root surface deliberately has no generic
package escape hatch: advanced package CLIs are invoked directly by developers,
so scheduling and publishing operations cannot be hidden behind a normal
Creator OS operator command.

## Repository And Automation Entrypoints

- Make: `install`, `reel-models`, `test`, `verify`, `backup-runtime`, and local
  Campaign API/Reference review development targets.
- pnpm: contract sync/check, static checks, architecture, artifacts, Graphify,
  secret scan, and the root operator command.
- LaunchAgent-facing scripts retained because machine automation calls them:
  `run_threadsdash_performance_sync.sh`, `run_learning_cohort_daily.sh`,
  `run_weekly_improvement_digest.sh`, and `run_campaign_factory.sh`.
- The real LaunchAgents and private environment files are machine-local and are
  not stored or modified here.

## Runtime And Configuration Resolution

`creator_os_core.runtime_paths` is the canonical resolver for source,
workspace, runtime, package, state, artifact, model, log, reference-data, and
ThreadsDashboard paths. Campaign, Reel, and Reference configuration reuse it.
Environment overrides remain explicit.

```text
/Users/aderdesouza/Developer/creator-os          source integration checkout
/Users/aderdesouza/Developer/creator-os-runtime  pinned runtime checkout
/Users/aderdesouza/Developer/ThreadsDashboard    external product checkout
~/.creator-os/state/                             canonical SQLite state
~/.creator-os/artifacts/                         generated media and identity evidence
~/.creator-os/models/                            local model files
~/.creator-os/logs/                              runtime logs
~/.creator-os/                                   private config and migration evidence
```

`CAMPAIGN_FACTORY_DB`, `REFERENCE_FACTORY_DB`, `REEL_FACTORY_MANIFEST_DB`, and
`REEL_FACTORY_RENDER_QUEUE_DB` remain explicit rollback overrides. New defaults
never search worktrees for a database. `scripts/migrate_runtime_state.py`
copies with SQLite `VACUUM INTO`, checks integrity and row counts, records
hashes and permissions, proves a clean temporary restore, and never deletes the
source. Runtime launchers keep deterministic checkout/database selection.
Repository changes never update or restart the runtime automatically.

## Browser Surfaces

- ContentForge has no browser application or HTTP server.
- Campaign Factory retains an authenticated headless JSON API for tested local
  integrations, but no committed HTML/CSS/JS dashboard. `/` identifies the
  service as headless.
- Reference Factory retains `review-server` because gold/maybe/ignore labeling
  is an active human workflow. It is not a product or publishing dashboard.
- Reel Factory has no operator HTTP/browser surface.
- Reel Factory has no posting ledger. Its manifest is limited to generation,
  render, cache, and derived-media evidence; Campaign Factory owns asset
  lifecycle and assignment, while ThreadsDashboard owns real post state.
- ThreadsDashboard remains the only product UI.

## Active, Compatibility, And Legacy Generation Code

### Active

- `generate_assets.py`: direct reference-image Soul generation, lineage, paid
  quote/reservation/consumption gates, optional Kling.
- `generate_variants.py`: captured-prompt original/sexy candidate contract.
- `static_mp4.py` and motion-edit modules: local fallback/upgrade.
- `reel_motion_prompt.py`: deterministic accepted-still Kling prompt.
- `placement.py`, `caption_render.py`, and caption-bank modules: safe overlays.
- ContentForge and Campaign readiness/export adapters.

### Compatibility-required or legacy-but-called

- `deprecated_generators.py`: active fail-closed guard; do not delete.
- selected Grok/prompt helpers imported by anatomy/reference compatibility;
  hidden from the root operator command.
- grid crop utilities with active tests/imports; not a default generation path.
- FFmpeg-dependent probe/render/QC paths; active infrastructure.
- root `pipeline_contracts/__init__.py`: import shim for current callers.

### Removed

- flat Reel package facades and delegation-only tests;
- Reel `operator_tools`, metrics HTTP routes, and unserved static browser assets;
- Campaign static dashboard assets;
- unused ContentForge golden-capture script;
- orphaned overnight-grid, reference-grid-production, visual benchmark, and
  Reel-owned outcome/orchestrator/approval harnesses, tests, and docs.

## State, Artifacts, And Contracts

| Kind | Owner/location | Git policy |
|---|---|---|
| Campaign decisions and learning | configured Campaign SQLite and campaign directories | machine/runtime state; ignored |
| Reference corpus and labels | configured Reference SQLite/data root | machine/operator state; ignored |
| media, provider receipts, render queues, lineage sidecars | Reel data/output directories | generated/runtime; ignored except curated source fixtures |
| ContentForge reports | request-scoped output | generated/runtime; ignored except sanitized seam fixtures |
| machine config and logs | `~/.creator-os` | never committed |
| canonical schemas | `packages/pipeline_contracts/pipeline_contracts/schemas` | committed hand-edited source |
| generated TypeScript | `packages/pipeline_contracts/typescript/generated-schemas.ts` | committed generated output; regenerate only |
| ThreadsDashboard consumer snapshot | external repository | read-only parity check from this repo |

## Safety Coverage

Retained suites protect contracts, HMAC signing, paid quote/reservation/
consumption/cancellation, provider failures, global kill switch, QC and
distinctness, campaign readiness, legal state transitions, lineage, eligibility,
learning, poisoned/ambiguous rows, draft-export safety, runtime launchers, and
cross-package architecture. Deleted tests covered only removed facades or
orphaned experiments.

Use `make verify` for the full local matrix. Passing tests prove source behavior,
not provider readiness, production handshake, runtime promotion, or live
performance evidence.
