# Creator OS Complete Audit Map — Pre-Hardening Snapshot

> Historical evidence only. This snapshot was prepared against
> `47de1715b99f2d972cd118cf304b0825a151c0d4` before hardening PRs
> #567–#573. Those PRs are merged in `cb71b76b43d0ff49cfd3251394105d0d7b0b8167`.
> Use `CREATOR_OS_SYSTEM_MAP.md` and the current architecture/runbook files for
> operational decisions.

Point-in-time, ChatGPT-ready companion to `CREATOR_OS_SYSTEM_MAP.md`.

**Mapped:** 2026-07-30  
**Canonical merged source inspected:** `47de1715b99f2d972cd118cf304b0825a151c0d4`  
**Protected runtime inspected:** `71b1cf15af78c63b3023cc70647c8467502f83d9`

This document maps the remaining Creator OS surfaces without changing the
canonical ownership boundary:

```text
Campaign Factory authorizes and decides
→ Reel Factory generates and renders
→ ContentForge analyzes and blocks
→ Campaign Factory reviews, approves, registers, and exports
→ ThreadsDashboard schedules, publishes, reconciles, and measures
```

It is an audit map, not proof that every mapped capability is deployed or
operationally proven.

## Evidence language

Keep these states separate:

```text
implemented
→ connected
→ source verified
→ merged
→ promoted
→ started
→ healthy
→ operationally proven
```

Current evidence:

| State | Current fact |
|---|---|
| Merged | `origin/main` is `47de1715b99f2d972cd118cf304b0825a151c0d4`. |
| Local integration checkout | `62d98b4d8de0a76862e474ad053549f4fc301db2`, ahead 4 and behind 8, with untracked `.serena/`; it is not canonical source and was not modified by this audit. |
| Promoted runtime | Clean detached runtime at `71b1cf15af78c63b3023cc70647c8467502f83d9`, five commits behind canonical merged source. |
| Started | No persistent Creator OS application process was observed. Loaded launchd jobs were idle when inspected. |
| Healthy | Runtime status passed local repository, environment, contract, configuration, root, and database checks. Provider and ThreadsDashboard live probes were not run. |
| Operationally proven | Recent scheduled backup/sync activity and historical promotion evidence exist. No paid generation, draft handoff, scheduling, publication, or current metrics proof was performed for this map. |

## Executive verdict

The core creation path is already strongly mapped and implemented:

- exact creator/source/media lineage;
- three product modes;
- spend authorization;
- deterministic local rendering;
- caption placement and typed timed captions;
- Audio Radar and exact audio binding;
- ContentForge evidence;
- exact-SHA creative approval;
- HMAC draft handoff;
- immutable experiment assignment;
- supervised learning;
- guarded runtime promotion.

The most important remaining structural gaps are:

1. no formal creator lifecycle, consent ledger, or Soul-ID version history;
2. no canonical campaign lifecycle state machine;
3. no system-wide fair daily production orchestrator;
4. no complete field-level database writer and migration registry;
5. no universal database/filesystem reconciliation transaction;
6. incomplete all-provider cost accounting;
7. incomplete privacy, revocation, deletion, and legal-retention modeling;
8. no proven 1,000-creator or million-asset capacity envelope;
9. no complete Python dead-code conclusion;
10. current merged source is not the currently promoted runtime.

## 1. Repository census and execution topology — P0

### Package census

| Surface | Census | Classification | Owner |
|---|---:|---|---|
| `python_packages/campaign_factory` | 210 production Python modules plus tests/data | active production and operator tooling | Campaign Factory |
| `python_packages/campaign_factory/repurposer` | 12 modules | legacy but reachable | Campaign Factory compatibility path |
| `python_packages/reel_factory` | 100 production Python modules plus tests/fonts/data | active production and experimental internals | Reel Factory |
| `python_packages/reference_factory` | 36 Python modules and one Swift analyzer | active operator/knowledge tooling | Reference Factory |
| `packages/creator_os_core` | 17 Python modules | active production foundation | Creator OS Core |
| `packages/pipeline_contracts` | 5 Python modules, 2 TypeScript source files, 59 canonical schemas | active production foundation | Pipeline Contracts |
| `packages/contentforge` | 29 JavaScript modules and 6 Python helpers | active production QC plus legacy derivative support | ContentForge |
| `scripts` | 31 files | operator, scheduled, verification, migration, and release tooling | repository root |
| package/root tests and `evals` | test-only | test-only | package owners |
| `docs` and retained references | policy, runbook, evidence, or reviewed input | documentation-only unless explicitly imported | documented owner |

Canonical package boundaries are enforced by the root `pyproject.toml`,
import-linter, dependency-cruiser, the ownership registry, and
`pnpm check:arch`.

### Executable topology

| Entrypoint | Owner | Reads | Writes / external effects | Receipts | Consumer / recovery owner |
|---|---|---|---|---|---|
| `scripts/creator-os` | operator facade | environment, four canonical databases, approved files | delegates to domain commands; mutating paths may call providers or draft ingest | delegated receipts | command’s owning domain |
| `campaign-factory` CLI | Campaign Factory | Campaign state, Reel/Reference evidence, ContentForge reports, ThreadsDashboard observations | campaigns, assets, plans, reservations, spend, approvals, exports, learning | activity, job, lineage, approval, spend, export, experiment receipts | Campaign Factory |
| Campaign FastAPI | Campaign Factory | same Campaign state | authenticated local API reads/mutations | same domain receipts | Campaign Factory |
| `reference_factory.cli` | Reference Factory | source/reference files, archives, imported metrics | probes, frames, OCR, reviews, patterns, prompts, knowledge packs; optional provider analysis | reference/anchor/pattern/promotion evidence | Reference Factory |
| Reference FastAPI | Reference Factory | Reference database | local operator review/analysis writes | Reference evidence | Reference Factory |
| `reel_factory.worker` | Reel Factory | render queue | claims and executes exact queued subprocess commands | queue and render evidence | Reel Factory recovery |
| Campaign motion worker wrapper | Campaign/Reel | authorized plan/job | one isolated render subprocess | redacted worker/effect evidence | Campaign Factory |
| local prompt-expansion worker | Reel Factory | bounded JSON request | local expansion result | expansion receipt | experimental local lane |
| ContentForge CLI | ContentForge | exact media plus JSON request | analysis and bounded derivative output; no server or publisher | audit, trusted-analysis, motion-QC, variant manifests | Campaign Factory |
| scheduled wrappers | operator/launchd | private env plus canonical state | refresh/sync/cohort/digest work; never publish | run reports and reconciliation evidence | script/domain owner |
| contract generator | Pipeline Contracts | canonical schemas | generated TypeScript and package artifact | manifest/package hashes | all contract consumers |
| runtime promotion | Creator OS Core | exact Git/check/approval/state evidence | backup, detached checkout update, verification, rollback | signed promotion transaction/receipt | runtime promotion owner |

### Canonical public CLI

The public facade has these command paths:

```text
creator-os status
creator-os sources list|approve|reject
creator-os media intake-existing|review-existing|review-summary|freeze-caption
creator-os plan cohort|show|list|approve|schedule-propose|experiment|execute
  |review|export|status|replan|attach-existing
creator-os doctor
creator-os performance-sync
creator-os learning-refresh
creator-os learning-review
creator-os learning-reset
creator-os reference-refresh
creator-os audio refresh|status|explain
creator-os create
creator-os recreation explain|review|approve-anchor
creator-os asset explain|inventory|reservations reconcile|reservations cancel
creator-os quality-benchmark
creator-os review
creator-os approve
creator-os qc explain
creator-os export
creator-os advanced
creator-os promote
```

There is intentionally no `creator-os schedule` or `creator-os publish`.

Internal command census:

- public facade: 52 literal parser registrations including nesting and aliases;
- Campaign Factory: 308 literal registrations;
- Reference Factory: 53 literal registrations;
- direct Audio Radar: 5 registrations;
- ContentForge: `similarity`, `variant-pack`, `motion-qc`, `analyze-media`,
  and `analyzer-registry`.

The complete internal command registries are:

- `python_packages/campaign_factory/campaign_factory/cli_parser_core.py`;
- `python_packages/campaign_factory/campaign_factory/cli_parser_operations.py`;
- `python_packages/reference_factory/reference_factory/cli.py`;
- `python_packages/campaign_factory/campaign_factory/audio_radar/cli.py`;
- `packages/contentforge/cli.mjs`.

### Classification

**Active production**

- three-mode `creator-os create`;
- Campaign source, reuse, reservation, spend, production, QC, approval, export,
  metrics, and learning;
- Reel static rendering, caption placement/rendering, audio mux, provider
  execution, and exact lineage;
- Audio Radar;
- ContentForge trusted analysis, similarity, motion QC, and analyzer registry;
- Pipeline Contracts and Creator OS Core.

**Active operator tooling**

- reports, audits, readiness, repair, certification, review, approval;
- Reference Factory review and learning tools;
- derived-still enroll/harvest/edit/review;
- observed-profile experiments;
- runtime promotion, backup, doctor, and digests.

**Experimental**

- local model Arena/router/queue and Wan/LTX/LongCat paths;
- WaveSpeed and unselected talking/motion-copy providers;
- structural Seedance recreation until separately approved;
- Pango caption path;
- observed-profile experiments until operator interpretation.

**Legacy but reachable**

- `repurposer`;
- ContentForge `variant-pack` and explicit legacy temporal-PDQ comparison;
- compatibility aliases and `advanced` surfaces;
- older contract versions retained for historical reads;
- Reel legacy manifest import and old state-root compatibility;
- older Reference/Grok prompt compatibility.

**Migration-only**

- Campaign connect-time schema migration/backfill modules;
- Reference and Reel initializer backfills;
- `scripts/migrate_runtime_state.py`;
- compatibility conversion and retention helpers.

**Dead/unreachable**

- No repository-wide Python dead-code conclusion is currently justified.
- A previous ContentForge audit removed 43 proven zero-caller exports/helpers.
- A fresh import/call-graph audit is still required before deleting Python
  modules.

## 2. Runtime, promotion, and rollback — P0

### Runtime topology

```text
/Users/aderdesouza/Developer/creator-os
  local integration checkout; not the promoted runtime

/Users/aderdesouza/Developer/creator-os-runtime
  clean detached protected runtime

~/.creator-os/state
  canonical SQLite state

~/.creator-os/artifacts
  generated media and evidence

~/.creator-os/models
  retained QC/research model bytes

~/.creator-os/logs
  runtime and scheduled-job logs

~/.creator-os/*.env
  private machine configuration
```

### Promotion transaction

```text
exact merged commit
→ required trusted checks
→ signed promotion authority
→ runtime lock
→ incomplete-transaction recovery
→ verified Git bundle and state backup
→ checkout exact commit
→ reconstruct/fingerprint dependencies
→ full verification
→ semantic read-only health
→ signed receipt
→ retain previous SHA and rollback instructions
```

Promotion does not copy or roll back operational databases. Code rollback is
therefore separate from data recovery:

```text
code rollback
→ restore previous reviewed runtime SHA
→ retain current canonical state
→ verify schema compatibility
→ run status/read-only health

data restore
→ separate incident authority
→ restore to a new location first
→ verify integrity and row counts
→ reconcile receipts newer than the backup
→ never overwrite newer state blindly
```

### Current runtime proof

- runtime checkout is clean and detached;
- canonical roots and four databases exist outside Git;
- three private config files exist with mode `0600`;
- contracts match in the runtime;
- Campaign database is readable;
- provider and ThreadsDashboard live probes were not requested;
- current merged source is five commits ahead of the protected runtime.

### Runtime gaps

- current `origin/main` is not promoted;
- promotion-time health is not perpetual health;
- cross-version database compatibility is not automatically proved by code
  rollback;
- complete machine-loss recovery during a partial promotion has not been
  exercised;
- no currently running persistent Creator OS application process was observed.

## 3. Complete database and migration map — P0

### Canonical stores

| Store | Source-declared tables | Observed runtime tables | Owner |
|---|---:|---:|---|
| Campaign Factory | 81 | 83 | Campaign Factory |
| Reference Factory | 24 source-declared | 23 observed | Reference Factory |
| Reel manifest/evidence | 11 base/source groups | 26 observed including compatibility/evidence tables | Reel Factory |
| Reel render queue | 2 source-declared | 1 observed | Reel Factory |

The source/runtime differences are not automatically defects: the promoted
runtime is older than merged source and some tables are lazy-created or
compatibility tables. They are exactly why schema versions and migration
receipts must be explicit.

### Table families

Campaign Factory:

```text
identity/planning
  campaigns, models, accounts, creative plans, plan events, manager decisions

source/render/lineage/review
  source assets, rendered assets, jobs, attempts, blobs, lineage edges,
  variants, captions, components, audits, QC, approvals, rejection evidence

inventory/delivery/recovery
  assignments, reservations, reservation events, exports, pipeline jobs,
  activity events, promotion events, publication history

reference/audio
  patterns, knowledge packs, promotion receipts, catalogs, cache, segments,
  selections, refresh runs, publication history, performance rollups

learning/experiments/trust
  metric observations/projections, cohorts, recommendations, accuracy,
  experiments, item events, trust settings/exceptions, content graph

spend
  provider authorizations/reservations and cost events
```

Reference Factory:

```text
source files and authorization evidence
→ probes, frames, OCR, contact sheets, review labels
→ caption/reference/audio patterns
→ prompt cards and generated prompts
→ analysis jobs/results
→ learning runs/clusters and outcomes
→ exported knowledge
```

Reel Factory:

```text
videos and variations
→ render attempts and analysis cache
→ prompt runs and provider generations
→ campaign outputs
→ reference analysis, embeddings, features
→ experiments, outcomes, recommendations, reviews
→ render queue and provider execution evidence
```

### Migration governance

- Campaign enables WAL, busy timeout, and foreign keys.
- Campaign uses connect-time schema creation, `_ensure_*` backfills, and table
  rebuilds; it has no migration ledger or `PRAGMA user_version`.
- Some Campaign connection paths deduplicate rows before creating indexes.
- Reference creates/alters schema on connection and declares foreign keys but
  does not normally enable `PRAGMA foreign_keys=ON`.
- Reel manifest uses schema version 8 plus `schema_migrations` and
  `PRAGMA user_version`, while some columns still use `_ensure_columns`.
- Reel render queue has no schema version.

### Strong immutable evidence

Database triggers or equivalent immutable rules protect:

- generation blobs, attempts, and lineage edges;
- motion-QC receipts;
- terminal pipeline-job state;
- experiment assignment and arm identity;
- existing-media reviews and caption freezes;
- raw metric observations;
- reservation events and audio publication history;
- Reference anchor receipts.

Evidence-like records still mutable include:

- approval decisions;
- audit reports;
- activity events;
- reference-promotion receipts;
- audio-cache prune receipts;
- observed-experiment interpretation JSON.

### Database gaps

- no field-level legal-writer registry;
- more than 100 Campaign modules execute SQL directly;
- many status columns are unrestricted `TEXT`;
- application state transitions can be bypassed by direct SQL;
- JSON columns contain internal, incompletely declared contracts;
- no complete named migration history for Campaign/Reference/queue;
- no universal database/filesystem transaction or repair command;
- no formal retention/deletion semantics for every table.

## 4. Configuration, environment, and secrets — P0

### Configuration classes

**Provider and authentication secrets**

```text
OPENAI_API_KEY
GEMINI_API_KEY / GOOGLE_API_KEY
XAI_API_KEY / GROK_API_KEY
WAVESPEED_API_KEY
Supabase service credentials
CREATOR_OS_API_TOKEN
CREATOR_OS_SPEND_AUTH_SECRET
CREATOR_OS_EVIDENCE_AUTH_SECRET
CAMPAIGN_FACTORY_INGEST_SECRET
```

Higgsfield uses its authenticated CLI/account state rather than a committed
credential.

**Canonical roots and databases**

```text
CAMPAIGN_FACTORY_ROOT / CAMPAIGN_FACTORY_DB
REFERENCE_FACTORY_ROOT / REFERENCE_FACTORY_DB
REEL_FACTORY_ROOT / REEL_FACTORY_MANIFEST_DB / REEL_FACTORY_RENDER_QUEUE_DB
CONTENTFORGE_ROOT / CONTENTFORGE_OUTPUT_DIR / CONTENTFORGE_SSCD_MODEL_PATH
CREATOR_OS_LOCAL_MODELS_ROOT
THREADSDASH_ROOT
```

**Policy, budget, and capacity**

```text
HIGGSFIELD_MIN_BALANCE_CREDITS
CREATOR_OS_OPENAI_PROMPT_MODEL
CREATOR_OS_OPENAI_PROMPT_QUOTE_USD
REFERENCE_BANK_ACCOUNT_CAP
REFERENCE_BANK_CAPTION_SHARE
LEARNING_FANOUT_MAX_ATTEMPTS
campaign/provider daily, monthly, cohort, and run caps
```

**Safety and compatibility**

```text
CREATOR_OS_KILL_SWITCH
ALLOW_INSECURE_LOCAL
CAMPAIGN_FACTORY_ALLOW_LOCAL_THREADSDASH_INGEST
fixture/test switches
legacy-root/write compatibility switches
```

**ThreadsDashboard and scheduled jobs**

```text
CAMPAIGN_FACTORY_DRAFT_INGEST_URL
THREADSDASH_CAMPAIGN_FACTORY_INGEST_URL
THREADSDASH_ALLOWED_INGEST_HOSTS
THREADSDASH_USER_ID
THREADSDASH_WORKSPACE_ID
CAMPAIGN_FACTORY_SYNC_CAMPAIGNS
backup repository/password and notification settings
```

### Confirmed behavior

- private machine configuration files are outside Git and mode `0600`;
- missing paid-action caps block spend;
- missing/weak evidence-signing material blocks signed evidence;
- local API auth is required unless an explicit loopback-only insecure override
  is set;
- status redacts values.

### Configuration gaps

- no one typed registry documents every variable, owner, sensitivity, default,
  validation, rotation, and impact;
- `CREATOR_OS_KILL_SWITCH` defaults inactive when missing, so the emergency
  switch itself is fail-open even though paid routes retain other gates;
- Soul IDs are hard-coded in source instead of a versioned creator registry;
- startup does not centrally require every safety-critical value because
  validation remains operation-specific.

## 5. Creator identity, onboarding, and offboarding — P0

### Current lifecycle

```text
models row acts as creator record
→ account rows optionally bind model_id
→ approved source assets bind model_id
→ signed creator identity profile/reference binds exact bytes
→ hard-coded Soul ID resolves provider identity
→ production verifies expected creator and source SHA
```

Strong controls:

- exact expected-creator identity verification;
- source approval and SHA verification;
- symlink rejection at production gates;
- AI-derived stills cannot become canonical identity evidence;
- creator/identity fingerprints travel with plans and provider requests.

Missing controls:

- no canonical `active|suspended|departed|deleted` creator state;
- no consent, likeness, voice, scope, territory, expiry, or revocation record;
- no identity version or Soul-ID history;
- no offboarding/reactivation workflow;
- no disabled-creator spend invariant;
- `accounts.model_id` is nullable;
- Campaigns do not foreign-key to one creator;
- account-profile isolation can fail open when the profile is absent;
- creator rename/path migration is undefined.

Verdict: identity use is strongly bound per asset/request, but the creator’s
business/legal lifecycle is not modeled.

## 6. Campaign lifecycle and state machine — P0

The `campaigns` table stores ID, slug, name, platform, root path, and
timestamps. It has no canonical status.

Current behavior is distributed across:

- source/render status;
- creative-plan status;
- pipeline jobs;
- reservations;
- spend authorizations;
- approvals;
- exports;
- operator status calculated from child rows.

The proposed states:

```text
created
configured
reference_ready
source_ready
production_ready
producing
reviewing
approved
exporting
paused
blocked
completed
cancelled
archived
```

do not exist as one authoritative campaign state machine.

Consequences:

- pause does not structurally block spend or production;
- reservation behavior on pause/cancel/close is undefined;
- budget exhaustion is not a campaign transition;
- campaign closure does not govern later asset reuse;
- two campaigns rely on inventory reservation rules rather than campaign-level
  ownership to avoid collisions;
- a campaign is not relationally bound to one creator.

## 7. Daily production orchestration — P0

Current daily library lane:

```text
prepared fixed-cohort assignment
→ cataloged source selection
→ identity verification
→ recent caption text/payload exclusion
→ approved timed caption, else static fallback
→ Reel preparation/render
→ Campaign synchronization
→ ContentForge audit
→ review-state update
→ assignment-state update
```

It is bounded, deterministic, non-publishing, and non-paid. It currently targets
a Stacey learning cohort.

Missing system-wide orchestration:

- all-creator fairness;
- global campaign selection;
- starvation prevention;
- provider capacity arbitration;
- budget capacity arbitration;
- concurrency policy;
- blocked-campaign backoff;
- stale-reservation cleanup;
- campaign lifecycle integration;
- explicit next-run reasoning for every stopped batch.

The daily learning-cohort launchd wrapper is not a global production
orchestrator.

## 8. Source-asset intake and catalog — P1

Current flow:

```text
folder/local discovery
→ extension classification
→ SHA-256
→ campaign-scoped duplicate check
→ copy or external-reference storage
→ deterministic naming
→ source row and pipeline event
→ explicit creator-bound approval/rejection
→ later media/identity/QC gates
```

Current distinctions are real:

```text
file exists
≠ cataloged
≠ approved source
≠ canonical identity evidence
≠ approved production source
```

Gaps:

- initial classification is extension-based rather than MIME/probe-authoritative;
- no explicit source quarantine lifecycle;
- no replacement/version relation;
- no archive/delete/tombstone lifecycle;
- referenced external bytes may sit outside managed backup roots;
- duplicate protection is campaign-scoped, not global;
- symlinks can be cataloged and are rejected at later gates.

## 9. Filesystem and artifact storage — P1

Campaign layout:

```text
{campaigns}/{creator}/{campaign}/
  00_sources
  01_reel_inputs
  02_rendered
  03_contentforge_audits
  04_approved
  05_threadsdash_exports
```

Artifact families:

- imported and canonical references;
- provider raw outputs;
- clean still/video candidates;
- caption/cover/audio derivatives;
- exact final MP4s;
- ContentForge runs;
- approval and lineage sidecars;
- Reference frames/OCR/contact sheets/patterns/prompt cards;
- Campaign manifests/reports/exports;
- promotion and backup evidence.

Strong controls:

- atomic writes and locks exist in Creator OS Core;
- exact SHAs are retained;
- critical paths reject symlinks and escaped roots;
- originals are preserved for derived outputs;
- cleanup policy protects active and historical evidence.

Gaps:

- absolute paths are widely persisted;
- paths are not universally content-addressed;
- file and database commits are not one transaction;
- no universal orphan/missing-byte/conflicting-SHA/temp-file reconciler;
- disk quotas are not centrally enforced;
- campaign layout construction is duplicated in two modules;
- external-reference storage can escape backup coverage.

## 10. Prompt system and model governance — P1

Current prompt lineage:

```text
operator intent
→ campaign/creator/reference inputs
→ versioned prompt builder
→ optional cached OpenAI expansion
→ provider-specific compiled prompt
→ input and request fingerprints
→ quote/authorization
→ provider request and receipt
```

Existing controls:

- cache-first exact fingerprints;
- one bounded OpenAI prompt call where used;
- model ID and prompt-builder version in receipts;
- reference and identity SHA binding;
- prompt regression checks;
- no silent provider fallback;
- active provider recipes pinned by product mode.

Gaps:

- no one prompt registry owns approval, retirement, and compatibility across
  every prompt path;
- OpenAI prompt cost is not consistently written to the shared cost ledger;
- hard-coded prompt/identity data remains in production modules;
- Reference Grok/Gemini and production OpenAI prompt systems are separately
  governed;
- prompt changes are fingerprinted but not all have an explicit operator
  approval lifecycle.

## 11. Reference Factory internal lifecycle — P1

```text
explicitly authorized source
→ private acquisition and SHA
→ probe and frame sampling
→ OCR/caption/audio/motion analysis
→ confidence-bearing evidence
→ human review and labels
→ versioned pattern/prompt/knowledge output
→ immutable Campaign promotion receipt
→ Campaign may consult, never treat inference as approval
```

Evidence versus inference:

- source bytes, hashes, probes, OCR output, labels, and provider response IDs
  are evidence;
- pattern cards, motion descriptions, confidence, prompt proposals, and
  recommendations are inference;
- low-confidence inference cannot approve media or spend.

Gaps:

- `--reference-authorized` is an operator assertion, not a signed rights record;
- deletion/revocation propagation into promoted patterns is incomplete;
- contradictory references have analysis/review tools but no formal conflict
  state machine;
- Reference foreign keys are declared but not normally enabled;
- some connection paths backfill state from sidecars.

## 12. Reel Factory local-rendering engine — P1

Current engine owns:

- static MP4 generation;
- FFmpeg/FFprobe command construction;
- codec, pixel format, frame rate, dimensions, and output profiles;
- caption placement and rendering;
- Instagram Sans Condensed font assets;
- timed overlays;
- audio mux and verification;
- metadata stripping where requested;
- temp output and atomic finalization;
- render queue, attempts, and analysis cache;
- exact final SHA and lineage.

Output expectations:

- dimensions, aspect ratio, duration, frame rate, audio policy, and semantic
  QC are contractual;
- exact byte identity is required for approval and handoff;
- cross-FFmpeg/macOS/hardware renders are not assumed byte-identical;
- renderer equivalence requires pinned toolchain evidence and perceptual/stream
  qualification.

Gaps:

- no clean-Mac byte-for-byte reproducibility proof;
- FFmpeg and host font/native-tool versions are not fully pinned across
  machines;
- queue states are application-enforced rather than database-constrained.

## 13. ContentForge analyzer governance — P1

Active analyzer authority:

```text
exact immutable media snapshot
→ analyzer registry with tool/model fingerprints
→ trusted media analysis
→ human review where required
→ motion-QC/audit receipt
→ Campaign independently revalidates bindings
```

Active layers include:

- media integrity/probe;
- OCR and UI/burned-text checks;
- readability and semantic payoff;
- safe-zone/focal/body/face checks;
- PDQ/SSCD sibling/source similarity;
- watchability/audio fit;
- Apple Vision pose/hand/lip continuity where applicable;
- ContentForge audit policy.

Strong governance:

- model and implementation fingerprints;
- fail-closed trusted input snapshots;
- unavailable evidence cannot be invented;
- legacy temporal-PDQ is excluded from normal production authority;
- raw analyzer scores do not approve media.

Gaps:

- a bound receipt proves execution identity, not detector accuracy;
- no single production-authority renewal schedule is defined for every model;
- validation-set ownership, false-positive/negative budgets, threshold-change
  approval, and upgrade rollback are not one complete registry;
- the ContentForge export-hygiene document is stale about the current command
  count.

## 14. All-provider cost and budget map — P1

Strongest complete path:

```text
live Higgsfield quote/balance
→ signed authorization
→ atomic budget reservation
→ attempt
→ consume or cancel
→ actual or explicitly unknown cost
→ durable ledger
→ reconciliation
```

Derived-still edits also have finite USD caps, request fingerprints, cache,
quote, kill switch, authorization, consumption, and ledger events.

Incomplete:

- OpenAI recreation prompt cost is receipted but not inserted into the shared
  cost ledger;
- no unified all-provider budget;
- no complete creator-level cap;
- no refund/provider-credit reconciliation;
- no formal currency conversion policy;
- unknown-cost reporting can collapse to USD `0.0`;
- storage, transcription, reference analysis, and all external API costs are
  not consistently attributed.

## 15. Operator CLI, authority, and destructive actions — P1

Authority classes:

| Class | Examples | Required behavior |
|---|---|---|
| Read-only | `status`, `doctor`, `review`, `qc explain`, asset/audio explain, reports | no product writes |
| Local mutation | source/media review, plan approval/review, recommendation decisions, reservation reconciliation/cancel, final approval | durable operator attribution and idempotency |
| Paid external effect | `create --apply`, derived-still edits, advanced provider calls | quote, cap, signed authorization, attempt identity, reconciliation |
| Handoff external effect | `export --apply`, performance sync | HMAC/owner contract, idempotency, acknowledgment/reconciliation |
| Runtime mutation | `promote` | exact SHA, trusted checks, signed authority, backup, rollback |
| Destructive repair | learning reset, migration apply, removal/rejection, cleanup | narrow target, receipt, backup/recovery path |

Important finding:

- several durable mutations do not consistently use a wrapper-level `--apply`,
  including plan/review/approval and some learning/reservation actions;
- operator names often provide attribution rather than authenticated RBAC;
- there is no enforced single command-authority matrix;
- some internal command names understate their durable mutation power.

## 16. Observability, reconciliation, and incidents — P1

Current chain:

```text
SQLite and artifact evidence
→ activity/pipeline events
→ status/lifecycle/recovery reports
→ scheduled digests
→ failure runbooks
→ bounded reconciliation/repair commands
→ operator closure evidence
```

Loaded machine jobs observed:

```text
com.creator-os.backup
com.creator-os.offsite-backup
com.creator-os.offsite-check
com.creator-os.offsite-restore-drill
com.creator-os.audio-refresh
com.creator-os.learning-cohort-daily
com.creator-os.threadsdash-performance-sync
com.creator-os.ops-digest
com.creator-os.weekly-improvement
```

Loaded does not mean currently executing. A source wrapper does not prove a
LaunchAgent is installed.

Reporting defects found:

1. unknown lifecycle states can fall through to `approved`;
2. recovery status hard-codes an empty mapping-blocker list;
3. unknown non-USD cost can appear as USD `0.0`;
4. security documentation says CodeQL/Trivy run on PRs while their workflow
   guards exclude PRs.

The latest read-only operations digest reported:

```text
snapshots missing
sync healthy and recent
backup recent
audio snapshot missing
reference snapshot missing
```

This is a diagnostic snapshot, not a claim that the jobs themselves failed.

Gap: no centralized incident-severity, escalation, manual-hold, owner, and
closure-evidence state machine covers every failure domain.

## 17. Scale and capacity — P1

Current source includes fixture/staged acceptance, inventory, yield, capacity,
and 100/200-account reporting tools.

Evidence currently supports:

- one creator / three accounts as the known operating shape;
- staged 10-creator / 100-account planning;
- previous 25-account acceptance;
- a 50-account gate blocked by inventory buffer, not source correctness.

Not proven:

- 1,000 creators;
- 10K/100K/1M asset tiers;
- SQLite contention and query latency at those sizes;
- filesystem/receipt growth;
- ContentForge and FFmpeg throughput;
- provider outage backlog recovery;
- backup/restore duration;
- hard memory, disk, concurrency, and rate ceilings.

## 18. Learning and experiment lifecycle — P1

Observed-profile experiments have:

- predeclared hypotheses/metrics;
- immutable assignment;
- exact approved final SHA validation;
- atomic paired reservation;
- equal-age measurement;
- deterministic bootstrap;
- guardrails and sample tiers;
- operator-only recommendation;
- no automatic production expansion.

Metric storage separates immutable raw observation revisions from mutable
current projection.

Learning remains fragmented across:

1. generic recommendation tables;
2. creative-plan experiments and metric cohorts;
3. creator-specific fixed learning cohorts;
4. Reference learning runs/clusters/outcomes.

There is no single hypothesis-to-production-policy registry. Keep these
distinct:

```text
correlation
≠ experiment result
≠ operator preference
≠ production rule
```

Operator-removed media remains completed generation, creative rejection,
`operator_removed`, and learning-ineligible rather than a technical failure.

## 19. Multi-creator isolation — P1

Controls:

- model IDs on source/account records;
- expected-creator identity verification;
- creator/campaign path partitioning;
- identity profile fingerprints in plans and provider requests;
- creator/account cooldown validation;
- derived outputs cannot become canonical identity evidence.

Gaps:

- Campaigns have no creator foreign key;
- creator identity appears as repeated free text/slugs;
- Soul IDs are not versioned records;
- account/source scopes use JSON in several places;
- missing account profiles can fail open;
- shared Reference patterns/audio lack one explicit cross-creator policy;
- rename/path migration is undefined;
- similar-name, slug-collision, and renamed-creator tests are not established.

## 20. Security and local trust boundaries — P1

Existing protections:

- local API authentication;
- HMAC evidence and handoff;
- private `0600` configuration;
- path containment and symlink rejection in critical flows;
- atomic writes and file locks;
- argument-array subprocess construction;
- URL SSRF/public-host checks;
- staged downloads and hashing;
- schema validation;
- promotion environment filtering and redaction;
- secret scanning, CodeQL, Trivy, SBOM, and scorecard workflows.

Gaps:

- no proof every path/URL/subprocess/JSON/media consumer uses hardened helpers;
- CodeQL/Trivy do not currently gate pull requests;
- native CLI trusts Mac account/filesystem authority rather than command RBAC;
- monorepo CI uses floating major action tags while security actions are pinned;
- hardened-runner egress is audit-only.

## 21. Creator privacy, likeness rights, and retention — P1

Audio has the strongest rights model:

```text
rights status
→ source
→ territory
→ account scope
→ commercial permission
→ expiry
→ evidence receipt
→ fail-closed live-use decision
```

Reference-video intake requires an explicit authorization assertion and
preserves private exact-SHA evidence.

Missing:

- signed creator-likeness consent;
- voice authorization;
- commercial/geographic scope;
- consent expiry and revocation;
- creator departure/reactivation;
- deletion-request workflow;
- provider-retention tracking;
- backup purge/legal hold rules;
- proof consent was valid at generation time.

`--reference-authorized` is an operator assertion, not a consent ledger.

## 22. Backup, restore, and disaster recovery — P1

Implemented:

- SQLite `VACUUM INTO`;
- integrity and hash verification;
- credential exclusion;
- restore-copy verification;
- managed-root copy;
- migration to canonical roots with empty-destination enforcement;
- original preservation and rollback window;
- offsite backup/check/restore-drill jobs.

Observed:

- recent successful backup activity;
- loaded backup/check/restore jobs with last exit status zero;
- historical offsite check and restore-drill logs;
- protected runtime and state roots are separate.

Not proven now:

- complete-machine-loss restoration;
- restore on another Mac/path;
- restore after schema upgrades;
- complete asset/model/secret recovery;
- formal RPO/RTO;
- safe reconciliation of newer receipts after a stale restore.

## 23. Test architecture and release gates — P2

Current test tiers:

```text
focused package tests
make fast
make affected
pnpm check:all
make verify
make release
make exhaustive
runtime verification
live paid/operator-controlled pilot
```

CI surfaces:

- PR affected tests;
- hygiene;
- Secret scan;
- main release;
- SBOM and build provenance;
- CodeQL/Trivy on non-PR trusted runs;
- scheduled exhaustive checks.

Gaps:

- no enforced matrix maps change class to mandatory gates;
- CodeQL/Trivy documentation and workflow triggers disagree;
- no current exact-`origin/main` promotion/release proof was run for this map;
- live paid/provider/publication claims remain separate from source tests.

## 24. Dependency and supply chain — P2

Managed:

- `uv.lock`;
- `pnpm-lock.yaml`;
- pnpm 11.6.0;
- Node `22.x || 24.x || >=26`;
- Python package bounds;
- contract-package build and checksum;
- secret scanning, CodeQL, Trivy, scorecard, SBOM;
- promotion-time toolchain fingerprints.

Host/native tools:

- FFmpeg/FFprobe;
- Tesseract;
- Apple Vision/Swift;
- `fpcalc`;
- Git/GitHub CLI;
- optional local ML models and runtimes.

Gaps:

- Homebrew FFmpeg/Tesseract are not version-pinned in CI;
- some GitHub Actions use floating major tags;
- dependency review is not a hard gate;
- SBOM is not a complete production-runtime manifest;
- model/native/config state prevents proven byte-for-byte clean-Mac
  reproducibility.

## 25. Operator reporting and dashboard truth — P2

Authoritative reporting principles:

```text
submitted ≠ completed
locally approved ≠ publish authorized
draft accepted ≠ scheduled
QStash dispatched ≠ published
container created ≠ reconciled Instagram media
missing cost ≠ zero cost
unknown state ≠ approved
missing metric ≠ zero metric
```

Current sources:

- `creator-os status`;
- lifecycle and readiness reports;
- asset/audio explain commands;
- activity and pipeline events;
- ops digest;
- Campaign reports;
- runtime promotion receipts;
- ThreadsDashboard/Instagram evidence imported through owned boundaries.

Gap: there is no complete field-by-field report registry declaring source,
freshness, calculation, unknown/stale behavior, authority, drill-down, and
repair action. The reporting defects in section 16 must be fixed before the
affected fields can be called truthful.

## 26. Deprecation and legacy removal — P2

Still needed for active historical compatibility:

- Creative Approval v1 reads;
- draft payload v1/v2 reads;
- handshake v1;
- generated-lineage v1;
- provider-spend authorization v1;
- older Reel manifest/state paths;
- historical WaveSpeed/provider receipts;
- legacy Reference/audio evidence.

Legacy but still executable:

- `repurposer`;
- ContentForge derivative/temporal compatibility paths;
- advanced local-model and old provider commands;
- old prompt-analysis routes;
- deprecated CLI aliases.

Already removed:

- normal WaveSpeed routing;
- Grok/grid normal generation;
- duplicate schema mirrors and root shim;
- Redis/RQ queue;
- duplicate package-local workflows;
- unused ContentForge job/polling layer;
- proven unused ContentForge exports/helpers.

Unknown:

- complete Python dead/unreachable set;
- which compatibility readers are still required by retained production rows;
- safe removal dates for old contract versions.

## Completion scorecard

| Map | Current status |
|---|---|
| Repository census | Mapped at source level; Python dead-code proof pending |
| Runtime/promotion | Strongly implemented and mapped; current source not promoted |
| Database/migrations | Store/table families mapped; field-level ownership and named migrations incomplete |
| Configuration/secrets | Variables and behavior mapped; no unified typed registry |
| Creator lifecycle | Materially incomplete |
| Campaign lifecycle | Materially incomplete |
| Daily orchestration | Narrow cohort lane only |
| Source intake | Implemented with lifecycle gaps |
| Filesystem/storage | Strong SHA controls; no universal reconciler |
| Prompt governance | Strong fingerprints; fragmented approval/cost governance |
| Reference Factory | Strong analysis/promotion boundary; rights/deletion gaps |
| Reel Factory | Strong local engine; cross-machine reproducibility unproved |
| ContentForge | Strong receipt binding; analyzer-authority lifecycle incomplete |
| Costs/budgets | Higgsfield strong; all-provider ledger incomplete |
| Operator authority | Commands mapped; unified enforced authority matrix missing |
| Observability/incidents | Strong reports/runbooks; centralized incident lifecycle missing |
| Scale/capacity | Small/staged evidence only |
| Learning/experiments | Strong bounded experiments; fragmented learning domains |
| Multi-creator isolation | Strong request binding; relational isolation incomplete |
| Security | Strong local guards; systematic boundary proof incomplete |
| Privacy/rights | Audio strong; creator consent lifecycle missing |
| Backup/DR | Strong backups; full cross-Mac recovery unproved |
| Tests/release | Strong tiered system; release-class matrix incomplete |
| Supply chain | Locks/scans exist; clean-Mac reproducibility unproved |
| Reporting truth | Strong principles; known defects and no field registry |
| Legacy removal | Active compatibility known; full reachability audit pending |

## Priority order

Do not treat all gaps as equal. The smallest high-value sequence is:

```text
1. fix known reporting truth defects
2. add creator lifecycle/consent/Soul-version ownership
3. add canonical campaign lifecycle
4. name/version Campaign and Reference migrations
5. enforce campaign-to-creator and fail-closed account-profile isolation
6. add database/filesystem reconciliation
7. build a fair global daily orchestrator only after lifecycle states exist
8. unify paid-call cost and unknown-cost accounting
9. execute cross-Mac restore and scale gates
10. remove legacy code only after retained-row compatibility is measured
```

## Definition of “fully mapped”

Creator OS is fully mapped only when:

```text
every executable entrypoint is inventoried
every persistent field has one legal owner
every external effect has attempt and recovery identity
every byte has exact lineage
every approval binds exact bytes
every paid action is authorized and reconciled
every operator mutation is auditable
every failure has one repair owner
every creator is isolated
every runtime can be restored and rolled back
every report preserves unknown and stale truth
every active module belongs to one documented domain
```

This audit establishes the repository census and current gap ledger. It does
not claim the missing lifecycle, migration, reconciliation, privacy, scale, or
cross-machine recovery systems already exist.
