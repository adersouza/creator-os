# Thin Evidence Foundation

Creator OS already has an orchestration owner: Campaign Factory. These records
do not create another workflow engine. They preserve the facts that explain a
run while the existing factories continue to own decisions and execution.

## Current-state overlap

| Proposed record | Existing ownership | Decision |
| --- | --- | --- |
| `CreatorIdentityProfileV1` | Campaign Factory `models` and `model_account_profiles`; explicit Soul IDs and Reel Factory identity-reference receipts already travel in existing generation lineage | Add one immutable snapshot that references those facts. Do not move account/OAuth state or identity-verification verdicts into it. |
| `ContentIntentV1` | `campaign_factory.creative_plan.v1`, concepts, surface fields, caption context, and `audio_intent.v1` | Add one small immutable intent snapshot. Do not copy Creative Plan progress/count state or audio policy. |
| `ExecutionPolicyV1` | Frozen `GenerationExecutionPlan` plus `campaign_factory.generation_execution_plan.v1` | Already exists. Reuse it under its current name and schema; no new record was added. |
| `BenchmarkRecipeV1` | Reel Factory `LocalGenerationJob` fingerprints and `BenchmarkReceipt` observations | Add only the comparable recipe inputs. Receipts, measurements, promotion policy, queue state, and model catalog remain unchanged. |
| `AnalyzerRegistryV1` | ContentForge audit/QC code accepts analyzer name/version evidence but has no versioned registration snapshot | Add a metadata snapshot of analyzer implementations and evidence kinds. It does not run analyzers or replace QC policy. |

Reference Factory remains the knowledge producer. Its `identity.py` helpers are
stable IDs and content hashes, not a creator identity registry. Creator OS Core
remains infrastructure-only and owns none of these business records.

## Record ownership and persistence

The four genuinely missing records are canonical JSON schemas, frozen Python
value objects, and generated TypeScript validators in Pipeline Contracts
`2.1.0`. This is the existing cross-component type boundary; no new package,
service, registry framework, or database was introduced.

Reel Factory remains independently installable: its queue/benchmark bridge
accepts the records through their canonical `to_dict()`/JSON serialization
shape and does not add Pipeline Contracts as a runtime dependency. Pipeline
Contracts remains the sole type and schema owner.

| Record | Producer | Consumer | Persistence |
| --- | --- | --- | --- |
| `CreatorIdentityProfileV1` | Campaign Factory `snapshot_creator_identity_profile()`, from `ModelRepository.model_account_profile()` plus explicit existing identity-reference IDs | Campaign compatibility compiler; downstream workers receive the serialized snapshot but still consume their existing explicit creator/Soul inputs | Exact snapshot in the existing generation-workflow evidence payload and, for applied Library Reuse, the existing `library_reuse_runs/<pipeline-job-id>.json` manifest |
| `ContentIntentV1` | Campaign Factory `snapshot_content_intent()`, from the current Creative Plan plus selected source fingerprints | Campaign compatibility compiler and later benchmark analysis | Same run evidence payload/Library Reuse manifest; mutable `creative_plans` remains source state |
| `campaign_factory.generation_execution_plan.v1` | Existing `build_generation_execution_plan()` | Existing Campaign stages and Reel Factory loader | Existing generation-plan sidecars/run payloads; unchanged |
| `BenchmarkRecipeV1` | Reel Factory benchmark planner when a comparable cohort is declared | Existing `LocalGenerationJob`, measured `BenchmarkReceipt`, and promotion evaluator | Exact recipe ID/fingerprint on linked queue jobs and new receipts; canonical recipe JSON beside the existing append-only benchmark journal |
| `AnalyzerRegistryV1` | ContentForge's deterministic `analyzer-registry.js` adapter | Campaign compatibility compiler and benchmark/QC readers | Exact registry ID/fingerprint on linked queue jobs and new receipts; canonical registry JSON beside the benchmark journal, not a mutable global plugin registry |

`run_generation_workflow()` accepts all four missing records as one optional,
all-or-none set. It combines them with the already-existing execution plan,
checks their references, and carries the five independent JSON objects under
`evidenceRecords`. Library Reuse then binds the creator key, ordered selected
MP4 SHA-256 list, execution-policy fingerprint, and actual workflow-parameter
fingerprint before returning a dry-run or writing an applied manifest. Applied
Library Reuse revalidates the transported records at its persistence boundary;
it cannot write an arbitrary evidence dictionary. No new table or migration is
required.

## Validation and compatibility

- Every added record has a literal `.v1` schema identifier; unknown versions
  fail closed.
- Every record requires producer, timestamp, and unambiguous source-reference
  objects pairing a record ID with its SHA-256 fingerprint through
  `evidence_provenance.v1`.
- Frozen dataclasses serialize only through their canonical schema shape.
- `ContentIntentV1.creatorIdentityProfileId` must match the identity snapshot.
- `ContentIntentV1.sourceAssetFingerprints` is the reviewed authorization
  cohort, not a claim that every authorized source was measured. A
  `BenchmarkRecipeV1` binds one exact, ordered execution cell whose
  role-preserving typed inputs must be a subset of that cohort.
- The recipe's execution-policy schema and canonical SHA-256 must match the
  existing execution plan; its parameter fingerprint must match the actual
  normalized format, variant count, and worker count.
- Every required analyzer ID/version must exist in the registry snapshot.
- Every analyzer registration includes both its implementation reference and
  immutable implementation SHA-256.
- Benchmark queue jobs accept recipe and registry records only as a pair. The
  recipe task and required analyzer versions must match before the job is
  journaled. The job retains its own exact aggregate input and parameter
  fingerprints while the recipe retains its ordered source fingerprints; the
  bridge does not reinterpret or collapse either identity.
- Promotion and Router admission remain narrower than Content Intent
  authorization: they bind the winning exact Arena sample IDs and reconstruct
  their canonical typed input cohort. An authorized but unbenchmarked source,
  a source reused under the wrong role, or a source measured under another task
  cannot inherit a promotion.
- New measured receipts require the same IDs and canonical fingerprints carried
  by the succeeded queue job. The benchmark store copies both canonical records
  into content-addressed local evidence paths before appending the receipt.
- Recording, promotion evaluation, and explicit promotion approval re-hash the
  registered implementation file under the trusted repository root and re-open
  every output-bound QC receipt. Changed code, changed registry content,
  substituted output, missing QC, or drifted analyzer policy fails closed.
- Library Reuse requires zero expected provider calls and the existing
  provider-free, non-paid execution plan.
- The records never authorize scheduling or publishing. ThreadsDashboard's
  boundary and contracts remain unchanged.

## Migration path

1. Emit snapshots only on new runs; do not rewrite historical evidence or infer
   missing provenance. Historical benchmark receipts deserialize with absent
   linkage fields and remain inspectable, but cannot become promotion-eligible.
2. Keep current Creative Plan, model/account profile, generation plan, queue,
   benchmark receipt, and ContentForge verdict stores authoritative.
3. New benchmark measurements are now additively linked to the exact recipe and
   analyzer-registry IDs and fingerprints carried by their queue job. No legacy
   receipt is backfilled.
4. ContentForge now snapshots its actual motion-QC policy ID/version, evidence
   kind, implementation path, and file SHA-256 through one deterministic
   producer adapter. It does not load plugins, dispatch analyzers, or run a
   daemon.
5. Release/pin Pipeline Contracts only when an external consumer needs these
   internal records. ThreadsDashboard does not consume them today.

## Provider-free benchmark evidence canary

`reel_factory.benchmark_evidence_canary` is a local-only acceptance path. It
requires a registry JSON emitted by ContentForge's `analyzer-registry` command
and an empty caller-selected root. It performs sixteen measured local copy jobs
(eight baseline and eight candidate) over a real locally generated FFmpeg MP4
under the existing machine queue,
runs the trusted ContentForge media-integrity and temporal analyzers against
each exact output SHA-256, records output-bound per-analyzer receipts and
sixteen linked benchmark receipts, and performs the existing matched promotion
evaluation. It does not approve a
promotion, call a provider, download a model, use a production database, or
touch scheduling/publishing state.

The regression suite asserts zero provider calls and zero production writes and
also covers recipe mismatch, changed implementation hashes, substituted output,
missing QC, duplicate receipt identity, and interrupted jobs.

## Rejected alternatives

- A universal run/god object: it would duplicate Campaign Factory orchestration.
- A second workflow engine or generic plugin framework: neither is needed to
  serialize evidence.
- Putting the records in Creator OS Core: Core owns infrastructure, not creator,
  creative, benchmark, or analyzer business facts.
- A duplicate `ExecutionPolicyV1`: the existing generation execution plan
  already covers provider/model authorization, approvals, lineage, QC,
  fallback, and output authority.
- Reusing `BenchmarkReceipt` as a recipe: a measured outcome is not a planned,
  comparable cohort.
- Reusing ContentForge verdicts as an analyzer registry: evaluation policy is
  not implementation registration.
- New database tables or legacy backfills: the initial records fit the existing
  append-only/local run evidence boundary, and historical provenance cannot be
  reconstructed honestly.
