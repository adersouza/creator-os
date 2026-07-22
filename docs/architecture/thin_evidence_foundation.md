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

| Record | Producer | Consumer | Persistence |
| --- | --- | --- | --- |
| `CreatorIdentityProfileV1` | Campaign Factory `snapshot_creator_identity_profile()`, from `ModelRepository.model_account_profile()` plus explicit existing identity-reference IDs | Campaign compatibility compiler; downstream workers receive the serialized snapshot but still consume their existing explicit creator/Soul inputs | Exact snapshot in the existing generation-workflow evidence payload and, for applied Library Reuse, the existing `library_reuse_runs/<pipeline-job-id>.json` manifest |
| `ContentIntentV1` | Campaign Factory `snapshot_content_intent()`, from the current Creative Plan plus selected source fingerprints | Campaign compatibility compiler and later benchmark analysis | Same run evidence payload/Library Reuse manifest; mutable `creative_plans` remains source state |
| `campaign_factory.generation_execution_plan.v1` | Existing `build_generation_execution_plan()` | Existing Campaign stages and Reel Factory loader | Existing generation-plan sidecars/run payloads; unchanged |
| `BenchmarkRecipeV1` | Reel Factory benchmark planner when a comparable cohort is declared | Existing local benchmark path can link it to `LocalGenerationJob.task_fingerprint` and `BenchmarkReceipt` in the migration phase | Same run evidence payload initially; future receipt linkage is additive to the existing append-only benchmark journal |
| `AnalyzerRegistryV1` | ContentForge when it snapshots the analyzer implementations configured for a run | Campaign compatibility compiler and benchmark/QC readers | Same run evidence payload initially; it is a per-run snapshot, not a mutable global plugin registry |

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
- `BenchmarkRecipeV1.contentIntentId` and ordered input fingerprints must match
  the intent snapshot and the exact ordered Library Reuse selection.
- The recipe's execution-policy schema and canonical SHA-256 must match the
  existing execution plan; its parameter fingerprint must match the actual
  normalized format, variant count, and worker count.
- Every required analyzer ID/version must exist in the registry snapshot.
- Every analyzer registration includes both its implementation reference and
  immutable implementation SHA-256.
- Library Reuse requires zero expected provider calls and the existing
  provider-free, non-paid execution plan.
- The records never authorize scheduling or publishing. ThreadsDashboard's
  boundary and contracts remain unchanged.

## Migration path

1. Emit snapshots only on new runs; do not rewrite historical evidence or infer
   missing provenance.
2. Keep current Creative Plan, model/account profile, generation plan, queue,
   benchmark receipt, and ContentForge verdict stores authoritative.
3. Link new benchmark receipts to `BenchmarkRecipeV1.recipeId` only in a future
   additive receipt version after real benchmark consumers need it.
4. Add a ContentForge producer adapter when analyzer implementations are
   configured dynamically; do not turn the registry snapshot into a plugin
   loader.
5. Release/pin Pipeline Contracts only when an external consumer needs these
   internal records. ThreadsDashboard does not consume them today.

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
