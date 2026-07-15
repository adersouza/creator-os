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

As of 2026-07-15, the current code-bearing baseline is merge `bd96be81` (PR
#444), and subsequent status-only documentation changes have been promoted to
the clean detached runtime in lockstep with `main`. `creator-os status
--live-read-only` is the authority for the exact current source/runtime SHA. The
canonical private roots, state migration, clean restore, fresh local backup,
live HMAC handshake, and Higgsfield account/workspace/model/balance/free-quote
probes are verified. The promoted code-bearing runtime also completed the
normal performance/learning sync at `2026-07-15T22:45:29Z`. A future source
repair must still earn its own merge, CI proof, and exact-SHA runtime promotion.

The operational learning loop is healthy but not yet statistically proven. A
post-promotion LaunchAgent run scanned four posts, imported/updated one eligible
snapshot, and completed one Reference fanout. Current eligible evidence is one
post with a real 1-hour row, zero with a 24-hour row, and zero with both. The
10-consecutive-post proof and 50-post autonomy gate remain intentionally closed.

## Ownership And Dependencies

| Component | Responsibility | Canonical source | Depends on | Primary state |
|---|---|---|---|---|
| Reference Factory | intake, human labels, winner patterns, prompt packs, audio recommendations, outcome learning | `python_packages/reference_factory/reference_factory` | Pipeline Contracts and Creator OS Core | `REFERENCE_FACTORY_DB`, `REFERENCE_FACTORY_DATA_ROOT` |
| Reel Factory | Soul stills, free static MP4s, optional motion/Kling, placement/rendering, worker media lineage | `python_packages/reel_factory/reel_factory` | Pipeline Contracts, Creator OS Core, FFmpeg and optional local models/providers | local media, render queue/cache, derived media features, caption banks, lineage sidecars |
| Campaign Factory | creative plans, inventory, assignment, approvals, provider-spend authorization/ledger, readiness, QC requests, draft construction, performance ingestion | `python_packages/campaign_factory/campaign_factory` | Reel Factory commands, ContentForge CLI, Pipeline Contracts, Creator OS Core | `CAMPAIGN_FACTORY_DB`, campaign artifact directories |
| ContentForge | PDQ/SSCD collision checks, sibling distinctness, OCR/safe-zone/readability/watchability, media evidence and blocking verdict | `packages/contentforge` | Node, FFmpeg/FFprobe and optional local OCR/fingerprint tools | request-scoped ignored local output |
| Pipeline Contracts | canonical schemas and validators | `packages/pipeline_contracts/pipeline_contracts` | standard validation libraries only | schemas and generated TypeScript |
| Creator OS Core | only shared auth, atomic file operations, SQLite, vectors, media probes, runtime paths, and global runtime guard | `packages/creator_os_core/creator_os_core` | foundational only; never imports factories | no owned business state |
| ThreadsDashboard | product UI, accounts, Supabase, approvals, scheduling, publishing, inbox, analytics, posting infrastructure | external `/Users/aderdesouza/Developer/ThreadsDashboard` | its own services and consumer contract snapshot | Supabase and deployed services |

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
reason. Campaign policy is fail-closed:

- `denied` is never selectable;
- known-missing publishing scope is never selectable;
- `unknown` requires an explicit per-plan `operator_canary` authorization;
- autonomous planning cannot supply that authorization and can select only an
  account projected as `eligible`.

The authorization and capability snapshot are stored on the distribution plan,
so a later account-sync change cannot rewrite what was authorized. Reconnecting
an account resets the external capability to `unknown`; the next normal account
sync projects the new evidence into Campaign Factory.

The current projected Stacey roster is 66 accounts: 0 `eligible`, 2 `denied`,
and 64 `unknown`. None currently has stored OAuth-scope verification. Trial
automation therefore remains closed; `unknown` permits only a separately
authorized one-account operator canary, never autonomous selection.

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

Creator OS is no longer architecturally tangled, but it is still a large
codebase. The remaining mess is bounded and is not a reason to merge the
factories or add another service:

1. `reel_pipeline.py` is about 3,500 lines and
   `reference_intake.py` is about 3,900 lines. Split them by existing stages
   only when changing those stages; do not create wrapper-only packages.
2. Campaign Factory is roughly 71,000 lines across many domain modules. Its
   largest active modules are now below 1,500 lines, so further reduction should
   remove dead workflows and duplicated policy rather than mechanically split
   files.
3. Static analysis reports 39 unused ContentForge exports. Remove them in a
   dedicated slice only after proving none are dynamic CLI/worker boundaries.
4. Legacy grid/six-pack helpers remain hidden from the root workflow but still
   have real imports/tests. Delete them only after zero-caller proof; they are
   not active generation defaults.
5. The source checkout still contains retained databases, models, media, and
   real-run evidence for rollback. The largest ignored temporary evidence tree
   is about 1.3 GB. Do not confuse retained evidence with source architecture or
   delete it before preservation and the applicable cleanup gate.

The practical next simplification order is therefore: finish the real 10-post
learning proof, pass the July 22 report-only cleanup gate, remove verified dead
exports/workflows, then split the two oversized worker modules when their tests
can preserve behavior. Redis/RQ, Temporal, another dashboard, and a factory
merge would increase—not reduce—the current complexity.
