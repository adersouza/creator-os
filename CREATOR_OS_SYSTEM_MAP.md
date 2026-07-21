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

## Current Operational Truth

Operational truth is intentionally not hard-coded in this durable document.
Source, runtime, account, queue, provider, and metric state all drift. Establish
them from fresh evidence every time:

```bash
git fetch origin main
git rev-parse origin/main
/Users/aderdesouza/Developer/creator-os-runtime/scripts/creator-os \
  status --live-read-only --json
```

Record the resulting source SHA, runtime SHA, trace ID, check counts, and dated
receipts in a run-specific audit report under `~/.creator-os/analysis/`. A
passing source verifier never proves runtime promotion. A passing read-only
status never proves that a post published. A QStash receipt never proves an
Instagram identity or metric row.

The minimum operational closure for a run is:

1. Exact source and runtime SHAs are recorded separately.
2. Read-only status/config/database/HMAC/provider probes pass without product
   writes, provider jobs, or cost events.
3. Every production action has its own exact account, media, caption, mode, and
   downstream receipt reconciliation.
4. Learning remains off until genuine Instagram publication identity and
   metric-history observations exist; missing observations are never zero.

Historical backup, deployment, publication, experiment, and metric evidence
belongs in dated audit artifacts, not in this map. Trial capability and OAuth
scope counts likewise come only from a fresh ThreadsDashboard account
projection.

## Lifecycle Overview

The system has three distinct bands: create and validate, publish, and return
real evidence. Creator OS Core and Pipeline Contracts are foundations shared by
the Creator OS stages, not additional workflow steps.

```mermaid
flowchart TB
    Operator["Operator"]
    Providers["Higgsfield<br/>Soul · Kling · Seedance"]

    subgraph CreatorOS["Creator OS<br/>Core + Pipeline Contracts underpin every stage"]
        direction LR
        Reference["Reference Factory<br/>Learn"]
        Plan["Campaign Factory<br/>Plan · assign · authorize"]
        Reel["Reel Factory<br/>Create · preserve lineage"]
        Quality["ContentForge<br/>Inspect · block"]
        Gate["Campaign Factory<br/>Approve · package · sign"]

        Reference -->|"knowledge pack"| Plan
        Plan -->|"work order"| Reel
        Reel --> Quality
        Quality -->|"QC verdict"| Gate
    end

    subgraph Production["Production edge"]
        direction LR
        Dashboard["ThreadsDashboard / Juno<br/>Review · schedule · publish"]
        Instagram["Instagram / Meta"]

        Dashboard -->|"approved publish"| Instagram
    end

    subgraph Evidence["Evidence return — real rows only"]
        direction RL
        DashboardMetrics["ThreadsDashboard metrics"]
        CampaignMetrics["Campaign performance"]
        ReferenceLearning["Reference learning"]

        DashboardMetrics -->|"performance sync"| CampaignMetrics
        CampaignMetrics -->|"measured provenance"| ReferenceLearning
    end

    Operator --> Reference
    Providers -.->|"generation only"| Reel
    Gate -->|"validated HMAC draft"| Dashboard
    Instagram -.->|"real metrics"| DashboardMetrics
    ReferenceLearning -.->|"knowledge refresh"| Reference
```

The next section records implementation ownership and foundational
dependencies separately from this lifecycle view.

## Ownership And Dependencies

| Component | Responsibility | Canonical source | Depends on | Primary state |
|---|---|---|---|---|
| Reference Factory | intake, human labels, winner patterns, prompt packs, audio recommendations, outcome learning | `python_packages/reference_factory/reference_factory` | Pipeline Contracts and Creator OS Core | `REFERENCE_FACTORY_DB`, `REFERENCE_FACTORY_DATA_ROOT` |
| Reel Factory | Soul stills, free static MP4s, optional motion/Kling, placement/rendering, worker media lineage | `python_packages/reel_factory/reel_factory` | Pipeline Contracts, Creator OS Core, FFmpeg and optional local models/providers | local media, render queue/cache, derived media features, caption banks, lineage sidecars |
| Campaign Factory | creative plans, inventory, assignment, approvals, provider-spend authorization/ledger, readiness, QC requests, draft construction, performance ingestion | `python_packages/campaign_factory/campaign_factory` | stable Reel Factory worker API and commands, ContentForge CLI, Pipeline Contracts, Creator OS Core | `CAMPAIGN_FACTORY_DB`, campaign artifact directories |
| ContentForge | PDQ/SSCD collision checks, sibling distinctness, OCR/safe-zone/readability/watchability, media evidence and blocking verdict | `packages/contentforge` | Node, FFmpeg/FFprobe and optional local OCR/fingerprint tools | request-scoped ignored local output |
| Pipeline Contracts | canonical schemas and validators | `packages/pipeline_contracts/pipeline_contracts` | standard validation libraries only | schemas and generated TypeScript |
| Creator OS Core | only shared auth, atomic file operations, SQLite, vectors, media probes, runtime paths, and global runtime guard | `packages/creator_os_core/creator_os_core` | foundational only; never imports factories | no owned business state |
| ThreadsDashboard | product UI, accounts, Supabase, approvals, scheduling, publishing, inbox, analytics, posting infrastructure | external `/Users/aderdesouza/Developer/ThreadsDashboard` | its own services and consumer contract snapshot | Supabase and deployed services |

## Repository Map

```text
scripts/creator-os
  operator CLI; selects one explicit workflow and never schedules or publishes

packages/creator_os_core/creator_os_core
  runtime paths, auth, SQLite/file safety, media probes, shared infrastructure

packages/pipeline_contracts/pipeline_contracts/schemas
  only hand-edited cross-component schemas
packages/pipeline_contracts/typescript/generated-schemas.ts
  generated TypeScript schema bundle
packages/pipeline_contracts/typescript/index.ts
  validator and semantic helper surface backed by the generated bundle

python_packages/reference_factory/reference_factory
  intake, human review, patterns, knowledge packs, learning provenance
python_packages/reel_factory/reel_factory
  placement, captions, rendering, provider workers, local SQLite render queue
python_packages/campaign_factory/campaign_factory
  plans, assignment, spend authority, readiness, handoff, metric ingestion
python_packages/campaign_factory/repurposer
  optional zero-provider-cost variation worker reached only through Campaign's
  explicit variation stage; not a lifecycle stage or second control plane

packages/contentforge
  direct headless CLI for media inspection, distinctness, and blocking QC

tests/integration
  cross-component, runtime-path, handoff, and operator-command evidence
```

The repository intentionally has no second control plane. TypeScript validators
consume generated canonical schemas rather than maintaining hand-written schema
mirrors. Reel Factory has one local SQLite render queue. ContentForge runs a
bounded command directly; it has no HTTP server, daemon, background job API, or
polling queue.

## Failure And Authority Map

| Failure | Owner that detects it | Required outcome |
|---|---|---|
| missing, substituted, or hash-mismatched source media | Reel/Campaign lineage checks | fail closed before QC or upload |
| unsafe or unreadable overlay, incomplete timed payoff, no safe lane | Reel placement/semantic proof and ContentForge | reject the derivative or ship clean media with post-caption text |
| duplicate or weakly distinct derivative | ContentForge plus Campaign readiness | block that derivative; never rewrite provenance |
| invalid asset state, missing approval, or contract drift | Campaign Factory | no upload and no draft ingest |
| stale account/OAuth/Trial capability | ThreadsDashboard projection consumed by Campaign | require a fresh projection; denied is never retried implicitly |
| queue delivery or publish failure | ThreadsDashboard | preserve exact attempt state; never treat dispatch as publication |
| missing Instagram identity or metric-history observation | ThreadsDashboard metrics and Campaign ingestion | exclude from learning; missing is not zero |
| provider, budget, or authorization failure | Campaign spend authority and Reel worker | create no paid job without a signed one-time authorization |

## Practical Value Of Each Component

| Component | Operational value | What becomes worse without it |
|---|---|---|
| Campaign Factory | **Essential control plane.** It turns goals, account policy, inventory, approvals, spend limits, and measured outcomes into one auditable decision. | Decisions fragment across scripts; cost, eligibility, and learning can disagree. |
| ThreadsDashboard | **Essential production edge.** It owns the real accounts and the only approved path to review, schedule, publish, and measure posts. | Creator OS can make assets but cannot safely operate Instagram accounts. |
| Reel Factory | **Essential media worker.** It converts accepted references or library assets into 9:16 still/static/motion Reels with exact lineage. | There is no repeatable asset-generation/rendering pipeline or reliable static fallback. |
| ContentForge | **High-value quality firewall.** It blocks collisions, unreadable overlays, unsafe placement, weak watchability, and broken media. | More visibly bad or duplicate-looking assets reach review and waste operator time. |
| Reference Factory | **High-value scaling memory.** It preserves human Gold labels and reusable prompt, visual, caption, and audio patterns. | The system can still make one Reel, but it relearns taste repeatedly and scales poorly. |
| Pipeline Contracts | **Essential connective tissue.** They make every handoff explicit and reject malformed or drifted payloads. | Components appear connected until a field or schema changes and silently breaks a seam. |
| Creator OS Core | **High-value reliability layer.** It centralizes private roots, SQLite safety, auth, file operations, spend primitives, and runtime guards. | Each factory reimplements fragile infrastructure and runtime paths drift back into checkouts. |

The useful simplification is therefore not to merge these packages. It is to
keep one operational brain, narrow workers, one production publisher, and
strict contracts between them.

Dependency direction is inward toward Pipeline Contracts and Creator OS Core.
Reel and Reference do not import Campaign ownership. Campaign may invoke
package-owned Reel/ContentForge commands but remains the only campaign brain.
The only in-process Reel dependency allowed from Campaign is the narrow
`reel_factory.worker_api` facade for pure caption-bank and remix-plan helpers;
generation and rendering continue through worker commands and lineage
contracts. Repository architecture checks reject imports of other Reel Factory
internals from Campaign.

`repurposer` is not a factory or lifecycle stage. It is an isolated optional
zero-cost variation utility packaged beside Campaign Factory and reached only
through the explicit variation stage. It does not own campaign state,
generation, providers, scheduling, or publishing, and it must not import Reel
Factory generation internals.

## Active End-To-End Flow

```text
reference intake
  -> Reference Factory local analysis and operator labels
  -> reference_factory.knowledge_pack.v1 (Gold references, prompt/pattern cards,
     caption/audio patterns, measured provenance)
  -> Campaign Factory creative plan and account assignment
  -> Campaign-issued, signed one-time spend authorization for paid modes
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
  -> Campaign performance_snapshots
  -> Reference measured provenance and versioned knowledge-pack refresh
  -> explicit advisory knowledge projection back into Campaign decisions
```

ThreadsDashboard is the only scheduling and publishing owner. Creator OS stops
at validated draft handoff.

## Creative Modes

- `library_reuse`: import an explicit media folder for an explicit model without
  provider generation. Folder and model are required; there is no proactive
  recommendation alias. ContentForge failures remain review-only but are
  reported honestly as `validated_with_failures`, never `validated`.
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

The handoff freezes one stable draft-key batch before readiness, usage, upload,
and ingest work. Every reused local or remote media object is materialized,
SHA-256 verified against its declared source fingerprint, and copied to an
immutable key without overwrite. Missing media, changed bytes, duplicate
source mappings, output collisions, invalid asset state, or a non-exportable
readiness verdict stops the batch before any external write.

Burned overlays carry the exact resolved render plan, including duration-bound
timed bands and the placement decision actually consumed by the renderer.
Explicit timestamps outside the media duration are invalid rather than silently
redistributed. Incomplete payoff text such as a standalone `before` label is
blocked unless the pixels provide a verified resolution with recorded human
semantic approval. `captionBurnedIn=true` means a successful render produced an
output from real caption inputs; metadata alone cannot make that claim.

ContentForge evidence identifies the local CLI execution surface and audited
file count. Its supported variants are limited to mild/editorial transforms;
strong distortion presets and platform-avoidance transformations are not part
of the production quality path. Readiness scores remain `null` or explicitly
unverified until backed by live operational evidence—fixture or simulated
results are never presented as production ratings.

Draft payloads validate against Pipeline Contracts before an HMAC-signed request
to ThreadsDashboard's draft-ingest endpoint. HMAC tests cover signature,
timestamp, and rejection behavior without sending real drafts. The supported
root command forces draft schedule mode and exposes explicit `--dry-run` versus
`--apply`; it has no scheduling or publishing command. `--dry-run` now returns
the exact proposed payload in memory with `path=null`, `pipelineJobId=null`, and
a non-written `wouldWritePath`; it creates no export row, pipeline job, activity
event, JSON file, dashboard request, or media upload. Durable export evidence is
created only by `--apply`.

Reel Factory's provider worker emits
`reel_factory.generation_worker_lineage.v1`, which intentionally lacks
Campaign-only identities. Campaign Factory is the only component allowed to
finalize that evidence as `reel_factory.generated_asset_lineage.v2` with the
rendered asset, reference, prompt, caption, audio, variant, and fingerprint
identities required at the ThreadsDashboard boundary. A provider-free active
`soul_static` integration test drives that full chain through the current
ThreadsDashboard consumer snapshot.

## Trial Reel Eligibility

ThreadsDashboard remains the capability authority. Its account projection into
Campaign Factory carries the exact OAuth granted scopes, verification time,
Trial capability (`unknown`, `eligible`, or `denied`), check time, and denial
reason. Trial eligibility also requires `projectionObservedAt` to be valid and
no more than 24 hours old. Campaign policy is fail-closed:

- `denied` is never selectable;
- known-missing publishing scope is never selectable;
- `unknown` requires an explicit per-plan `operator_canary` authorization;
- autonomous planning cannot supply that authorization and can select only an
  account projected as `eligible`.
- missing, invalid, or stale account projection evidence requires a new
  ThreadsDashboard account sync.

The root `draft-export` command exports one distribution surface at a time and
defaults to `regular_reel`. Use `--surface trial_reel` explicitly for a Trial
batch. An ineligible Trial destination cannot abort or contaminate a regular
Reel batch. `trial_reel` and `instagramTrialReels=true` are a bidirectional
invariant: either without the other is rejected before account gating. Explicit
Trial drafts carry a stored `MANUAL` or `SS_PERFORMANCE` graduation strategy
and `shareToFeed=false`; missing strategy data is rejected rather than silently
defaulted.
ThreadsDashboard rejects contradictory Trial-plus-Feed payloads before approval
or publishing.

The authorization and capability snapshot are stored on the distribution plan,
so a later account-sync change cannot rewrite what was authorized. Reconnecting
an account resets the external capability to `unknown`; the next normal account
sync projects the new evidence into Campaign Factory.

Current projected roster counts belong in read-only status evidence, not this
map. `unknown` permits only a separately authorized one-account operator
canary, never autonomous selection.

## Learning Return Path

The pinned performance launcher:

1. clears inherited virtualenv/Python state and pins PATH;
2. loads the private performance-sync environment;
3. verifies the exact campaign scope and SQLite database;
4. imports bounded ThreadsDashboard metric history;
5. runs `scripts/learning_fanout.py` from Campaign facts into the Reference
   provenance ledger; the former Reel projection is explicitly retired.

`learning_fanout.py` remains active. A successful command or queue receipt is
not equivalent to real metric history; learning proof requires measured rows.

Reference Factory exports the versioned knowledge pack without mutating its
database. Campaign Factory validates its contract and content fingerprint,
preserves the pack's human labels and recommendation status verbatim, and
stores the imported pack in its canonical ledger. Campaign
`performance_snapshots` remains the only operational measured-facts source.
Reel Factory has no posting, approval, experiment, winner, or cost ledger. Old
Reel rows remain available only through a SQLite read-only legacy evidence
exporter and cannot drive an active decision.
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

- GitHub Actions has one owner: repository-root `.github/workflows/` contains
  `monorepo-ci.yml`, `security.yml`, and `scorecard.yml`. Package-local workflow
  copies are intentionally absent because GitHub does not execute them in this
  monorepo and they drift from the canonical gates.
- Make: `install`, `reel-models`, `test`, `verify`, `backup-runtime`, and local
  Campaign API/Reference review development targets.
- pnpm: contract sync/check, static checks, architecture, artifacts, Graphify,
  secret scan, and the root operator command.
- LaunchAgent-facing scripts retained because machine automation calls them:
  `run_threadsdash_performance_sync.sh`, `run_learning_cohort_daily.sh`,
  `run_weekly_improvement_digest.sh`, and `run_campaign_factory.sh`.
- The real LaunchAgents and private environment files are machine-local and are
  not stored or modified here.

## Documentation Ownership

- `README.md` is the concise supported-entrypoint guide.
- This file is the durable architecture and ownership source of truth.
- `PIPELINE_STATE.md` records current source capability without freezing
  volatile operational counts or SHAs.
- `docs/architecture/` contains active implementation and promotion policy.
- `docs/archive/` and explicitly labelled historical snapshots are context only.
- Current runtime, provider, account, publication, and metric truth belongs in
  fresh status output and dated evidence under `~/.creator-os/analysis/`.

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

After cutover, `scripts/runtime_state_cleanup_eligibility.py` is the only
supported old-path cleanup preflight. It accepts legitimate live database drift
while requiring current SQLite integrity, private modes, a fresh verified
backup/restore, exact retained originals, zero active old-path references, the
recorded retention deadline, and explicit completed operating-cycle evidence.
Its output is report-only: it lists candidates but has no delete/apply mode.
Migration evidence and active log paths are never cleanup candidates.

The canonical Campaign artifact root is
`$CREATOR_OS_ARTIFACT_ROOT/campaign_factory/campaigns`. The compatibility
override `CAMPAIGN_FACTORY_CAMPAIGNS` remains explicit for rollback; Campaign
code no longer defaults generated exports back into a Git checkout.

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

- `generate_assets.py`: narrow command orchestration for direct reference-image
  Soul generation and optional Kling; provider, QC, lineage, and asset models
  live in focused `generation_*` modules.
- `reel_pipeline.py`: root Reel worker orchestration; rendering, selection, and
  support concerns live in focused `reel_pipeline_*` modules.
- `generate_variants.py`: captured-prompt original/sexy candidate contract.
- `static_mp4.py` and motion-edit modules: local fallback/upgrade.
- `reel_motion_prompt.py`: deterministic accepted-still Kling prompt.
- `placement.py`, `caption_render.py`, and caption-bank modules: safe overlays.
- `xai_vision.py`: narrow XAI transport retained only for anatomy/postability QC.
- ContentForge and Campaign readiness/export adapters.

### Compatibility-required or legacy-but-called

- narrow XAI vision helpers used by anatomy/postability QC;
- FFmpeg-dependent probe/render/QC paths; active infrastructure.
- root `pipeline_contracts/__init__.py`: import shim for current callers.

### Removed

- flat Reel package facades and delegation-only tests;
- Reel `operator_tools`, metrics HTTP routes, and unserved static browser assets;
- Campaign static dashboard assets;
- inert package-local GitHub workflows superseded by the root monorepo CI and
  security workflows;
- unused ContentForge golden-capture script;
- orphaned overnight-grid, reference-grid-production, visual benchmark, and
  Reel-owned outcome/orchestrator/approval harnesses, tests, and docs;
- legacy Reel prompt generation, six-pack generation, and manual grid-crop
  execution paths, including the empty experiments package and obsolete grid
  guide;
- redundant standalone Campaign smoke/proof wrappers whose supported behavior
  remains available through the package CLI and combined pipeline smoke.

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

Retained suites protect contracts, HMAC signing, paid quote/reservation/signed
one-time authorization/consumption/cancellation, provider failures, global kill
switch, QC and distinctness, campaign readiness, legal state transitions,
lineage, eligibility, learning, poisoned/ambiguous rows, draft-export safety,
runtime launchers, and cross-package architecture. Deleted tests covered only
removed facades and the retired Reel control-plane/outcome-ledger paths.

Use `make verify` for the full local matrix. Passing tests prove source behavior,
not provider readiness, production handshake, runtime promotion, or live
performance evidence.

## Remaining Complexity And Cleanup Order

Creator OS is large but no longer missing an architectural component. Remaining
complexity should be reduced only when caller and evidence checks prove a safe
cut:

1. `scripts/doctor.py`, the Campaign composition root, and several domain
   modules remain large. Split or delete behavior by ownership; do not add
   forwarding facades or another service.
2. Reference Grok compilation remains an explicit experimental CLI used by its
   own tests. Keep it isolated from the active Soul path unless the operator
   explicitly selects that experiment.
3. ContentForge retains direct FFmpeg variation utilities because they have an
   operator command and lineage/QC value. It does not retain an unserved job or
   polling layer.
4. Historical operational evidence, databases, models, and media are runtime
   assets, not source-code cleanup candidates. Their dated cleanup gates and
   retention decisions belong in run-specific reports.
5. Operational maturity still requires genuine publication and equal-age metric
   evidence. Source completeness must never be presented as performance proof.

Redis/RQ, Temporal, another dashboard, and a factory merge would increase—not
reduce—the current complexity. The supported architecture remains one Campaign
control plane, narrow workers, canonical generated contracts, one production
publisher, and evidence-gated learning.
