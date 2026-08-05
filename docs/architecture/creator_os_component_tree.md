# Creator OS Component Tree And Audit Coverage

This is the navigable tree for the Creator OS repository at
`662855b2573f4b868d1a086edf715e153d268859`. It complements the narrative
[`CREATOR_OS_SYSTEM_MAP.md`](../../CREATOR_OS_SYSTEM_MAP.md) and the
[`creator_os_complete_audit_map.md`](creator_os_complete_audit_map.md).

The tree separates five facts that must not be collapsed:

- **mapped**: the component, owner, inputs, writes, effects, receipts, consumer,
  and recovery owner are known;
- **source-verified**: the active caller and implementation were inspected;
- **runtime-verified**: the installed runtime exercised the component;
- **outcome-verified**: a real external result returned through the full chain;
- **qualified**: the output passed the applicable human, visual, scale, or
  restore proof.

## System tree

```text
Creator OS
├── Operator and recurring triggers
│   ├── creator-os public CLI
│   ├── Campaign Factory internal CLI and local API
│   ├── Reference Factory CLI and review server
│   ├── Reel Factory worker and direct tools
│   ├── ContentForge CLI
│   ├── launchd jobs
│   └── runtime promotion, backup, restore, and health tooling
│
├── Shared trust foundation
│   ├── Creator OS Core
│   │   ├── runtime paths and guards
│   │   ├── configuration and secret governance
│   │   ├── local authentication and evidence signatures
│   │   ├── atomic files and SQLite helpers
│   │   ├── media probing
│   │   └── provider spend and task identity
│   └── Pipeline Contracts
│       ├── canonical JSON schemas
│       ├── Python validators
│       ├── generated TypeScript validators
│       ├── ownership registry
│       └── versioned package consumed by ThreadsDashboard
│
├── Campaign Factory — sole Creator OS control plane
│   ├── creator, account, consent, and campaign governance
│   ├── source intake, lifecycle, catalog, and exact-byte inventory
│   ├── readiness, account eligibility, and distribution requirements
│   ├── Content Director, daily planning, and bounded orchestration
│   ├── reuse, reservation, duplicate, cooldown, and assignment gates
│   ├── three product-mode authorization
│   ├── provider quote, spend authorization, attempt, and reconciliation
│   ├── Reference/Recreation selection and approved-anchor binding
│   ├── visual generation and Reel Factory execution
│   ├── audio selection and exact-final media finalization
│   ├── ContentForge QC, human review, and exact-SHA approval
│   ├── variants, observed-profile experiments, and winner expansion
│   ├── Reel, Story, Carousel, and Reddit surface planning
│   ├── signed draft-only ThreadsDashboard export and reconciliation
│   ├── immutable metric ingestion, recommendations, and learning
│   └── incidents, privacy, recovery, cost, and operator reporting
│
├── Bounded creation and evidence domains
│   ├── Reel Factory
│   │   ├── prompt compilation and provider execution
│   │   ├── static MP4 and passive-motion rendering
│   │   ├── overlay bank, semantic matching, placement, and timed rendering
│   │   ├── audio mux and final-byte lineage
│   │   ├── identity, anatomy, perceptual, and media QC
│   │   ├── observed visual derivative profiles
│   │   ├── render queue and provider execution receipts
│   │   └── isolated local-model and bakeoff research tools
│   ├── Audio Radar
│   │   ├── discovery providers and normalization
│   │   ├── catalog, rights labels, cache, probe, and hash
│   │   ├── eligibility, fatigue, cooldown, and ranking
│   │   ├── segment selection and verified AAC embedding
│   │   └── publication history and outcome rollups
│   ├── Reference Factory
│   │   ├── authorized URL/file intake and lifecycle
│   │   ├── probe, frame sampling, OCR, and local/provider analysis
│   │   ├── operator review and identity-anchor evidence
│   │   ├── caption/audio/reference patterns and public metrics
│   │   ├── prompt cards, outcomes, and knowledge packs
│   │   └── immutable promotion into Campaign Factory
│   └── ContentForge
│       ├── exact-media probing and provenance checks
│       ├── PDQ/SSCD and sibling-distinctness checks
│       ├── OCR, overlay readability, safe zones, and watchability
│       ├── motion, lip-sync, pose, audio-fit, and creative-quality analyzers
│       ├── analyzer qualification and signed evidence
│       └── bounded editorial derivative tools
│
├── Persistent truth
│   ├── Campaign Factory SQLite
│   ├── Reference Factory SQLite
│   ├── Reel Factory evidence SQLite
│   ├── Reel Factory render-queue SQLite
│   ├── content-addressed JSON receipts and media artifacts
│   └── protected runtime, logs, backups, and rollback bundles
│
└── External ownership boundary
    ├── ThreadsDashboard/Juno33 — ingest, review UI, schedule, publish, reconcile
    ├── Supabase — ThreadsDashboard durable state
    ├── Meta/Instagram/Threads — publication and metric source of truth
    ├── Reddit — manual native-app publication and reconciliation
    ├── Higgsfield/OpenAI/Gemini/xAI — bounded provider effects
    └── authorized public/reference/audio sources — evidence inputs only
```

## Canonical end-to-end flow

```text
operator or launchd trigger
→ Campaign Factory reads creator/campaign governance, inventory, learning, and budget
→ Campaign Factory records a decision and exact generation/reuse plan
→ Reel Factory renders exact visual bytes
→ Audio Radar selects and embeds an eligible segment
→ ContentForge audits the exact final bytes
→ operator approves or rejects the exact final SHA
→ Campaign Factory signs a draft-only handoff
→ ThreadsDashboard accepts, schedules, publishes, and reconciles
→ ThreadsDashboard records equal-age outcomes
→ Campaign Factory imports immutable observations
→ an accepted recommendation changes a later recorded decision
```

The chain is **not** outcome-verified unless every arrow is evidenced by the
same asset family and exact bytes.

## Component ownership and execution

| Branch | Active implementation | Reads | Writes or external effect | Evidence and consumer | Recovery owner | Classification |
|---|---|---|---|---|---|---|
| Public operator facade | `scripts/creator-os` | runtime config and domain status | delegates bounded commands; can authorize provider/export/promotion operations | delegated domain receipts | command owner | active operator tooling |
| Campaign CLI | `campaign_factory/cli.py`, `cli_parser_*.py`, `cli_dispatch_*.py` | Campaign SQLite and bounded external projections | Campaign state, plans, approvals, exports, reconciliation | activity/job/domain receipts; public facade | Campaign Factory | active production/operator |
| Campaign local API | `campaign_factory/app.py`, `operator_authority_http.py` | same Campaign state | authenticated local mutations only | authority and domain receipts | Campaign Factory | active operator tooling |
| Creator/account governance | `creator_governance.py`, `account_eligibility.py`, `account_health.py` | creator identity, consent, accounts, platform projection | lifecycle and authorization events; eligibility decisions | governance reports; planning/export | Campaign Factory | active production |
| Campaign lifecycle/readiness | `lifecycle_reporting.py`, `campaign_overview.py`, `execution_readiness.py`, `readiness_report.py` | campaign, asset, job, QC, approval, destination state | calculated reports and blockers | operator and orchestrator | Campaign Factory | active production |
| Source intake/governance | `source_intake.py`, `source_governance.py`, `source_lifecycle_schema.py`, `asset_import.py` | files and creator/campaign authorization | source rows, SHA, lifecycle events, quarantine | inventory and creation modes | Campaign Factory | active production |
| Inventory/reuse/reservations | `asset_inventory.py`, `existing_media.py`, `inventory_reservations.py`, `assignment_eligibility.py` | approved assets, SHA, usage, cooldowns, accounts | atomic reservations and reuse decisions | export and scheduling reconciliation | Campaign Factory | active production |
| Content Director/daily plan | `content_director.py`, `daily_plan.py`, `daily_orchestrator.py`, `daily_library_production.py` | readiness, inventory, account demand, policies, learning | plan/run/item decisions and bounded jobs | production lane and operator | Campaign Factory | active production; current launchd is preview-only |
| Product modes | `creation_modes.py`, `production_lane.py` | approved source, content intent, mode, account, audio policy | reuse or generation plan | Reel Factory and finalizer | Campaign Factory | active production |
| Generation execution | `generation_execution_plan.py`, `reel_execution.py`, `front_generation_stage.py`, `production_lane.py`, `motion_review_asset.py` | authorized plan and spend receipt | Higgsfield provider effect and attempt state | Reel Factory receipt; reconciliation | Campaign/Reel Factory | active production for three modes |
| Provider spend | `provider_spend.py`, `all_provider_cost.py`, `production_higgsfield_authorization.py`, Core `provider_spend.py` | quote, budget, credential readiness | authorization, reservation, attempt, actual/unknown cost | ledger and reconciliation | Campaign Factory | active production |
| Recreation | `reference_url_workflow.py`, `recreation_*`, `recreate_reel.py` | authorized reference evidence and approved identity anchor | recreation plan, prompt, anchor approval | Reel Factory generation | Campaign/Reference Factory | active production within `recreate_reel` |
| Final media assembly | `production_lane.py`, `audio_operations.py`, `production_creative_evidence.py` | visual bytes, audio choice, caption decision | exact final MP4 and lineage | ContentForge then review | Campaign/Reel/Audio domains | active production |
| QC and approval | `contentforge_cli.py`, `motion_qc_publishability.py`, `creative_approval*.py`, `operator_review.py` | exact final bytes and analyzer registry | audit rows, review decision, exact-SHA approval/rejection | draft export | ContentForge/Campaign Factory | active production |
| Observed variants | `variation_stage.py`, `observed_variant_lineage.py`, `observed_experiment_reporting.py`, Reel `observed_profiles.py` | eligible clean parent | deterministic derivative bytes and experiment assignment | QC, review, paired outcome analysis | Campaign/Reel Factory | active supervised experiment |
| Winner expansion | `winner_expansion.py`, `variant_lineage.py`, `parent_factory_*` | accepted measured winners and eligible parents | bounded expansion plans/variants | inventory and later experiments | Campaign Factory | active supervised path |
| Stories/carousels/surfaces | `story_management.py`, `carousel_integrity.py`, `surface_*` | account demand and approved media | surface-specific plan, registration, draft evidence | ThreadsDashboard | Campaign Factory | active planning/handoff; publication external |
| Reddit | `reddit_weekly.py`, `reddit_library.py`, `reddit_handoff.py` | hot/top research evidence, rules, approved images/GIFs | weekly plan and exact approved manual handoff | ThreadsDashboard mobile/manual lane | Campaign Factory/ThreadsDashboard/operator | active manual-only lane |
| Draft export | `exports.py`, `threadsdash_draft_payload.py`, `threadsdash_export_saga.py`, `threadsdash_handoff_evidence.py` | exact approval, final SHA, destination, reservation | HMAC payload, manifest, acknowledgment or failure | ThreadsDashboard ingest | Campaign Factory | active production boundary |
| Metrics and learning | `threadsdash_metrics_ingestion.py`, `learning_*`, `recommendation_*`, `account_memory.py` | immutable publication/metric observations | snapshots, fanout ledger, recommendations, memory | later Campaign decisions | Campaign Factory | source-connected; outcome learning still data-starved |
| Incidents/privacy/recovery | `incident_privacy.py`, `reconciliation.py`, `learning_recovery.py`, `operator_status.py` | canonical rows, files, receipts, external observations | append-only incidents/repairs/retractions | operator and all domains | owning domain | active operator tooling |
| Reel provider/prompt layer | `generation_provider.py`, `higgsfield_production.py`, `asset_prompt_contract.py`, `prompt_registry.py` | exact request and creator identity | provider request/output receipt | Campaign registration | Reel Factory | active production for pinned providers |
| Reel static renderer | `static_mp4.py`, `still_to_reel.py`, `reel_pipeline_render.py`, `post_render.py` | approved still and render plan | deterministic MP4 and sidecars | finalizer/QC | Reel Factory | active production |
| Reel overlays | `caption_bank.py`, `caption_intake.py`, `caption_scene_fit.py`, `placement.py`, `caption_render.py` | approved typed overlay, media frames, placement policy | clean or burned-text video plus placement/timing lineage | finalizer/QC | Reel Factory | active production |
| Reel passive motion | `motion_generate.py`, `reel_motion_prompt.py`, `video_provider_models.py` | approved still, prompt, pinned provider recipe | Kling/Seedance output and receipt | QC and Campaign registration | Reel Factory | active only for approved passive recipes |
| Reel derivative engine | `generate_variants.py`, `variation_engine.py`, `observed_profiles.py` | eligible clean parent and deterministic seed | visual derivative and receipt | Campaign experiments/QC | Reel Factory | active supervised experiment |
| Reel identity/media QC | `identity_verification.py`, `anatomy_qc.py`, `ai_visual_qc.py`, `virality_qc.py`, `post_render_acceptance.py` | media and approved identity evidence | blocking QC/inspection results | Campaign review | Reel Factory | active bounded evidence |
| Reel queue/evidence | `render_queue.py`, `worker.py`, `evidence_store.py`, `generation_lineage.py` | explicitly enqueued authorized job | job events, attempt/receipt, lineage | Campaign reconciliation | Reel Factory | direct operator/research tooling; no installed worker daemon |
| Audio discovery | `audio_radar/providers.py`, `normalization.py`, `refresh.py` | authorized public/provider observations | trend snapshots and normalized catalog | ranking | Audio Radar | active operator/scheduled tooling |
| Audio cache | `audio_radar/acquisition.py`, `audio_cache_schema.py` | track locator and credentials | private bytes, SHA, probe, cache receipt | ranking/embedding | Audio Radar | active production support |
| Audio ranking | `audio_radar/ranking.py`, `audio_learning_policy.py`, `audio_recommendations.py` | eligibility, rights labels, cooldowns, history, rollups | deterministic selection and explanation | segment/embedding | Audio Radar/Campaign Factory | active, but real learned rollups are empty |
| Audio finalization | `audio_radar/segment.py`, `embedding.py`, `binding.py`, `pipeline.py` | selected cached bytes and visual | AAC-embedded exact final MP4 and receipt | ContentForge/review/export | Audio Radar | active production |
| Reference intake | `reference_intake.py`, `url_intake.py`, `scan.py`, `media.py`, `reference_lifecycle.py` | authorized files/URLs | source identity, rights/lifecycle evidence | analysis/review | Reference Factory | active operator tooling |
| Reference analysis | `ocr.py`, `scoring.py`, `reference_analysis.py`, `reference_local_analysis.py`, `reference_gemini.py`, `reference_grok.py` | source media | frame/OCR/analysis evidence | review/patterns | Reference Factory | active local path; paid routes explicit |
| Reference knowledge | `review.py`, `patterns.py`, `caption_archetypes.py`, `public_metrics.py`, `prompt_records.py`, `knowledge_pack.py` | reviewed references and measured outcomes | patterns, cards, packs, promotion receipt | Campaign Factory | Reference Factory | active, but current prompt-card/outcome inventory is empty |
| ContentForge exact-byte QC | `pipeline.js`, `trusted-media-analysis.js`, `similarity.js`, `overlay.js`, `motion-specific-qc.js` | exact media and qualified analyzer registry | blocking signed audit evidence | Campaign approval/readiness | ContentForge | active production |
| ContentForge derivatives | `variant-engine.js`, `variant-pack.js`, `editorial-derivatives.js`, `ffmpeg.js` | explicit derivative request | bounded derivative bytes/manifest | Campaign experiment path | ContentForge | reachable operator/experiment tooling |
| Analyzer governance | `analyzer-registry.js`, `analyzer-validation-manifest.js`, validation fixtures | pinned detector/model/tool evidence | qualification status and fingerprints | trusted analysis | ContentForge | source-complete; machine/corpus qualification is separate proof |
| Shared Core | `packages/creator_os_core/creator_os_core` | config, paths, trust inputs | atomic state/evidence and reusable validation | every Creator OS package | Core owner | active foundation |
| Pipeline Contracts | `packages/pipeline_contracts/pipeline_contracts/schemas`, `validator.py`, generated TypeScript | canonical schemas | validated payload/package artifact | Creator OS and ThreadsDashboard | contract owner | active foundation |
| Release and operations | `scripts/creator-os`, root `scripts`, `.github/workflows` | Git SHA, state, config, tests | promotion/rollback/backup/run evidence | protected runtime/operator | release owner | active operator tooling |

## Persistent-state tree

The canonical ownership registry currently validates **11 domains**, **151
persistent records**, **2,148 persistent fields**, **6 artifact families**, and
**8 authoritative reports**.

That registry is complete for freshly constructed schemas, not every retained
live compatibility table. The live Campaign database has 110 tables versus 106
in a fresh schema; the live Reel manifest has 27 versus 12. The 19 extra tables
are listed in the audit register below and remain readable until classified.

```text
Campaign Factory SQLite
├── campaign and production truth
│   ├── campaigns, models, plans, sources, rendered assets
│   ├── generation attempts/blobs/lineage
│   ├── audits, approvals, distribution, reservations
│   ├── incidents, privacy, retention, and exports
│   └── surface, Story, experiment, and operator state
└── learning truth
    ├── immutable performance observations
    ├── fanout/governance ledgers
    ├── recommendation runs/items/outcomes
    └── account memory, patterns, and posting windows

Reference Factory SQLite
├── sources, probes, frames, OCR, review labels
├── reference/caption/audio patterns
├── public-post metrics and learning runs
├── prompt cards/outcomes and knowledge packs
└── lifecycle, rights, analysis, and promotion evidence

Reel Factory evidence SQLite
├── prompts, generations, outputs, videos, variations
├── exact render attempts and analysis cache
└── retained legacy outcome/read models

Reel Factory render queue SQLite
├── mutable queue jobs/events through RenderQueue
└── append-only provider execution receipts

Persistent artifact roots
├── Campaign handoff manifests and acknowledgments
├── Reel manifests, lineage, caption, audio, and provider receipts
├── caption banks and structured approval sidecars
├── Reference intake, pattern, contact-sheet, and promotion evidence
├── Reddit research, plan, and handoff evidence
└── exact media bytes, quarantine, archive, backup, and rollback evidence
```

The field-level legal writers, mutability, deletion behavior, receipt binding,
and repair route are canonical in
`packages/pipeline_contracts/pipeline_contracts/ownership_registry.v1.json`.

## Entrypoint tree

### Public product and operator entrypoints

- `scripts/creator-os`: the only public facade. Its current commands are
  `status`, `sources`, `media`, `plan`, `doctor`, `capacity`,
  `performance-sync`, `learning-refresh`, `learning-review`, `learning-reset`,
  `reference-refresh`, `reference-paid`, `audio`, `create`, `recreation`,
  `asset`, `quality-benchmark`, `review`, `readiness`, `approve`, `qc`,
  `export`, `draft-export`, `advanced`, and `promote`. Its `advanced` surface is
  limited to `identity`, `analyzers`, `evidence-key`, `approval-import`, and
  `motion-qc-register`. It does not schedule or publish.
- `campaign-factory`: the internal Campaign CLI. Its large command registry is
  split across `cli_parser_core.py`, `cli_parser_operations.py`, and matching
  dispatch modules.
- `reference_factory.cli`: intake, analysis, review, patterns, prompts, audio,
  knowledge, and local review-server operations.
- `reel_factory.worker` and direct Reel modules: bounded queue execution and
  operator/research tools. Jobs enter only through explicit direct enqueue
  calls; no Reel worker LaunchAgent is installed. These are not alternate
  Campaign orchestrators.
- `packages/contentforge/cli.mjs`: direct bounded QC and derivative commands.

### Installed recurring jobs on this Mac

| Job | Frequency | Active effect | Current evidence state |
|---|---|---|---|
| `com.creator-os.daily-orchestrator` | daily 05:45 | preview-only planning, provider cap `0` | last run selected `0`; eligible inventory exhausted |
| `com.creator-os.threadsdash-performance-sync` | hourly | read/import publication metrics and refresh learning fanout | latest recorded run succeeded |
| `com.creator-os.audio-refresh` | Monday 04:00 | refresh bounded audio discovery/catalog | loaded; catalog freshness is currently an ops warning |
| `com.creator-os.learning-cohort-daily` | daily 08:30 and load | progress supervised cohort state | loaded; current cohort is paused |
| `com.creator-os.weekly-improvement` | Sunday 21:45 | summarize measured evidence-backed changes | loaded; only one measured snapshot and no learned change |
| `com.creator-os.ops-digest` | daily 21:30 | summarize freshness/failures/spend | last recorded run exited `1` because readiness warnings were present |
| backup/offsite/check/restore-drill jobs | daily/weekly/monthly | protect and verify canonical state | latest backup and restore-drill entries succeeded |

Loaded configuration is evidence of scheduling, not proof that a later run or
external effect succeeded. The append-only ops log and each job's receipt remain
the execution truth.

## Repository census

At this commit the source contains:

- 963 Graphify-classified code files;
- 411 non-test Python modules across Creator OS packages;
- 30 ContentForge library JavaScript files;
- 37 root scripts;
- 62 canonical Pipeline Contract schemas and 39 examples;
- 5 GitHub workflow files;
- 101 Python entrypoint roots reported by the legacy-reachability census.

Graphify produced 21,678 nodes, 52,593 relationships, and 957 communities from
845 source files that produced nodes. It warned that 117 code-classified files
produced no nodes and that three duplicated Swift import symbols were collapsed.
Graphify is therefore a relationship index, not proof that every data/config
file has been semantically audited.

## Audit coverage register

### Source areas still not fully audited or classified

These are the remaining source-level unknowns. They are not silently called
production-ready or safe to delete.

1. **Static module disposition is complete, but deletion proof is not.** The
   repository's `legacy_reachability.py` reports 450 Python modules: 434
   statically reachable, 12 research modules referenced only inside their
   disconnected subsystem, four statically unreferenced, and zero unclassified.
   Reachable modules are labeled `active_reachable` without claiming every
   path executes in production; known compatibility and research surfaces have
   narrower labels. No module is declared safe to remove.
2. **Compatibility/research retirement evidence remains unresolved:** the
   `reference_factory sample-frames --videos` alias, the `repurposer` package,
   and the Reel Factory local-model/Wan tool family are classified, but their
   external operator usage and retained evidence have not been completely
   inventoried.
3. **Four statically unreferenced modules remain intentionally retained:**
   `campaign_factory.adapters.threadsdash` is
   compatibility surfaces; `reel_factory.media_features` and
   `reel_factory.prompt_guidance` are experimental research utilities. Uvicorn
   string entrypoints and implicit package initializers are now represented in
   the graph instead of appearing as false-positive dead code.
4. **Off-repository callers remain only bounded, not exhaustive:** shell
   history, private operator scripts, arbitrary subprocess command assembly,
   non-literal dynamic imports, retained historical provider responses, and
   old external ThreadsDashboard consumers cannot be fully proven from this
   repository alone.
5. **Graphify does not semantically cover every non-code artifact.** Its current
   graph intentionally used the code-only project path, and 117 JSON/data/font
   or parser-empty files produced no AST nodes. Canonical schemas, ownership,
   and docs were separately inspected, but no claim is made that every retained
   media or historical receipt is represented as a graph node.
6. **Nineteen live SQLite tables are absent from the fresh-schema ownership
   census.** Campaign extras are `higgsfield_spend_reservations`,
   `learning_cohort_assignments`, `learning_cohorts`, and
   `tribev2_reel_scores`. Reel-manifest extras are `campaign_references`,
   `campaigns`, `cost_events`, `creators`, `experiment_assignments`,
   `experiments`, `operator_ratings`, `posting_slot_events`, `posting_slots`,
   `publish_metrics`, `recommendation_decisions`, `reel_outcomes`,
   `review_decision_history`, `review_decisions`, and `winner_dna`. Nine Reel
   tables are explicitly historical read-only compatibility; the remaining six
   and both active learning-cohort tables still need explicit ownership and
   retention classification.
7. **Lazy provider receipt storage is source-wired but not live-proven.** The
   queue schema defines `provider_execution_receipts`, but the current live
   queue database has not materialized that table because the paid execution
   route has not exercised it.
8. **Configuration classification is enforced.** The typed registry now covers
   every active Python and ContentForge environment read found by the regression
   inventory; host-process variables are explicitly separated from product
   configuration.
9. **Receipt ownership deliberately stops at the policy-family boundary.** Seven
   artifact families govern the exact fingerprinted writer-module set. Dynamic
   content-addressed filenames inherit their family policy instead of creating
   hundreds of duplicated filename rules.
10. **ThreadsDashboard migration and trust-boundary source are reproducible.**
    The production-ledger migration identity is pinned by a drift regression,
    and upload-ticket/post-link RLS plus role grants are asserted from the
    canonical migrations. Accepted live handoffs remain operational evidence,
    not a schema claim.

### Audited in source but not yet proven operationally

| Area | What is already connected | Missing production proof |
|---|---|---|
| Full Reel loop | source, render, audio, final QC, exact approval, handoff, metric import, learning consumers | one same-family real run through approved bytes → accepted draft → publication → equal-age 1h/24h/72h outcomes → changed later choice |
| Daily orchestration | fair bounded planner and loaded preview launchd job | a supervised execute run with eligible approved inventory; the live database has zero orchestrator runs/items and the current preview selected zero |
| Learning | immutable observations, governance, recommendation consumers, later-decision lineage | current Campaign DB has one observation, zero recommendation runs/items, and no proved changed decision |
| Audio intelligence | 147 catalog rows, 29 active, 43 resolved, 13 segments, 41 trend snapshots, and selection/cooldown/ranking/embedding code | one selection, zero publication history, zero performance rollups, zero audio recommendations, and a stale-refresh warning; no learned audio choice yet |
| Overlay intelligence | 491 unique payloads, typed static/timed selection, semantic matching, placement, and exact payload lineage | a 297-item timed review board now includes 17 legacy timed entries held for structured approval; production still falls back safely until the operator approves exact payloads |
| Current inventory | 887 source and 746 rendered rows with exact-byte review workflow | 703 rendered assets are `review_ready`, 36 draft, seven rejected, and none have `review_state='approved'`; representative visual qualification and enough exact approved schedule-safe finals are missing |
| Provider quality | live read-only Higgsfield account/model/balance/quote probe passes | fresh paid output from each active mode visually accepted for identity, clothing, hands, color, motion, and would-post quality |
| ContentForge authority | pinned analyzers, signed evidence, fixtures, and fail-closed calls | current-machine real-sample calibration and regression corpus representative of production media |
| Reference intelligence | 988 sources, 520 public-post rows, 339 review labels, 577 patterns, and review/promotion code | current DB has zero prompt cards, prompt outcomes, viral cards, video analyses, and audio trend snapshots; fresh references must produce a promoted pack that changes a later plan |
| Observed-profile experiments | deterministic control/treatment rendering, exact receipts, assignment and analysis | enough real paired outcomes to support any reach conclusion |
| Reddit handoff | rules, hot/top research logic, image-first/GIF-when-required planning, signed manual handoff | live Campaign state has zero Reddit activity/assets/proofs; one native handoff must be completed, permalink reconciled, moderation/outcome recorded, and the next weekly plan changed |
| Story/Instagram/carousel handoff | Story intent/CTA fields, multi-surface and carousel planning, draft contract, ThreadsDashboard ownership | live Campaign state contains only Reel surface records; one controlled native Story/Reel/carousel handoff and reconciliation is missing, and platform-native sticker behavior remains external/manual unless the API proves support |
| Restore | local backup, offsite backup/check, and current-Mac restore drill | restoration on a different Mac/path with current schema and secrets recovery procedure |
| Scale | the exact 10-creator/10k-asset tier passed all 12 mandatory lanes; indexes, bounded concurrency, backup/restore, FFmpeg, ContentForge and queue checks are receipt-bound | 100-creator/100k-asset and 1,000-creator/million-asset tiers |
| Research modes | isolated local-model, talking, motion-copy, and bakeoff tools | operator-approved recipes and active-product decision; they remain intentionally outside normal production |
| Current handoff contract | signed export saga, exact-byte gates, and live read-only HMAC/contract handshake | 176 historical export rows exist, but none records a current schema/version plus submitted, acknowledged, and media-preparation acknowledgment evidence in the inspected database |

### Audited current operational issues

These are known conditions, not unaudited areas:

- the protected runtime is clean and pinned to the current source SHA;
- the nine read-only runtime checks, including live provider readiness and the
  ThreadsDashboard HMAC/contract handshake, pass;
- the daily orchestrator is intentionally in preview mode with provider cap
  zero and currently has no eligible inventory to select;
- the ops digest currently reports insufficient outcome/audio freshness;
- no pytest or `tmp_path` subject remains under the canonical artifact JSON
  root; the previously reported test-artifact contamination is fixed;
- historical backup and Supabase 522 errors exist in old log files, while the
  latest backup, restore drill, and hourly performance-sync entries succeeded.

## Completion rule

The component map is complete at the domain and functional-subcomponent level.
It is not honest to call the repository or operation exhaustively audited until:

```text
all retained compatibility/research callers and evidence are inventoried
→ all live-only tables, unregistered configuration, and receipt filenames are classified
→ all off-repository callers and retained compatibility evidence are inventoried
→ one real exact-byte Reel closes the publication and 72-hour learning loop
→ audio, overlay, provider, ContentForge, Reference, Reddit, and Story proofs pass
→ different-Mac restore and declared scale tests pass
```
