# Local Model Arena And Router v1

## Purpose

The Arena answers a narrow question: which installed local model configuration
is useful for one creator intent on this machine? It does not schedule work or
replace Campaign Factory. Generation still uses `LocalGenerationQueue`; timing,
memory, QC, and promotion still use `LocalModelBenchmarkStore`.

## Frozen plan

Every plan records exact creator/intent fingerprints, source and optional audio
SHA-256 values, prompt, seed, duration, resolution, model revision and manifest,
output path, queue-job fingerprint, benchmark recipe, analyzer registry, blind
candidate ID, and the planned denominator. Promotion-eligible designs require
Stacey, Larissa, and Lola, at least two safe sources per creator/model/intent
cohort, and at least two seeds per source. Smaller runs are explicitly
exploratory.

Every competing model in a promotion-eligible comparison receives the exact
same creator, identity, intent, source, prompt, seed, duration, and resolution
grid. A model-specific subset is not described or analyzed as matched evidence.
The execution plan remains private evidence because it contains the model
mapping. Reviewers receive only a separately shuffled, HMAC-authenticated
`local_model_arena_review_packet.v1` with model-free candidate identifiers and
media hashes. After every candidate has exactly one valid signed blinded review,
Arena locks the review-set fingerprint and emits a separate authenticated
`local_model_arena_unblinding_receipt.v1`. Promotion-eligible summaries bind
both records; no review may be added or changed after unblinding.

Supported terminal classes are `succeeded`, `failed`, `interrupted`,
`resource_blocked`, `unsupported`, and `missing`. There is no implicit retry or
sample replacement. Interrupted queue jobs use the existing explicit queue
recovery command and retain their original evidence.

Queue evidence distinguishes an admission block from a real execution attempt.
Every sample summary carries attempt count, retry count, admission-block count,
stable failure class, measured duration/peak memory when available, and an
explicit local-cost observation. Local compute cost remains unavailable until a
real meter exists; it is never represented as zero.

Promotion-eligible workers execute inside the supported macOS sandbox with
network denied, an allowlisted environment, no provider/production secrets,
and writes limited to the exact artifact workspace. Isolation is measured and
recorded; `providerCalls: 0` is not accepted as a bare assertion. Worker output
streams to an append-only bounded log (16 MiB maximum) whose path, SHA-256, and
diagnostic tail are evidence, avoiding unbounded 12-hour stdout/stderr buffers.
Model identity uses a content-addressed deep-verification attestation cache
bound to the manifest, file metadata, runtime source, and environment; any
change invalidates it, and the selected model is revalidated at execution.

## Evidence production

ContentForge samples the actual output with FFprobe/FFmpeg and produces raw
observations separately from verdicts. Missing audio, overlays, identity,
anatomy, or lip-sync are unavailable/not-applicable, never numeric zero. Exact
per-analyzer receipts, automated identity evidence, structured human review,
and final motion QC are copied into benchmark evidence by SHA-256. Changed
media, code, registry, recipe, queue job, or receipt fails closed.

The final motion receipt is v2 and self-contained: it embeds the canonical
trusted analysis, exact registry snapshot, and complete human review and binds
their IDs and fingerprints. Neither the public ContentForge CLI nor benchmark
ingestion accepts a hand-authored `passed: true` object. Each supported QC
policy has an explicit receipt validator; unknown policies are ineligible.

Structured review captures reviewer, timestamp, rubric version, blinded ID,
source/output hashes, realism, attractiveness, resemblance, face stability,
motion naturalness, anatomy/artifact scores, intent adherence, conversion
usefulness, and explicit decisions. It is required for promotion; it is not
invented by automation.

Speaking-video lip-sync uses the registered local ContentForge face/mouth
tracker and decoded PCM audio envelope. Promotion requires sufficient speech,
face-track coverage, samples, confidence, and bounded offset; missing or
ambiguous evidence blocks the cohort. Temporal analysis samples the full video
at 8 fps and 180x320, binds a deterministic frame-set fingerprint, and requires
the blinded human review to confirm the exact brief-frame outlier set.

## Router v1

Router input is a creator identity, content intent, required task/capability,
resource budget, exact Arena summary, benchmark store, and active promotion
state. Candidate exclusion reasons are machine-readable. Selection is
deterministic and quality-first: human quality and valid yield dominate, with
smaller latency/resource tie-breakers.

The Router rejects:

- paid, missing, unready, drifted, stale, or unapproved models;
- capability/task mismatch;
- insufficient memory;
- historical receipts without recipe/registry linkage;
- missing/failed QC or human quality;
- expired or revoked promotions.

The active promotion must name the exact candidate benchmark IDs for the
creator/identity/intent cohort and the same hardware fingerprint observed by
the Router. Aggregate performance from another creator, intent, or machine
cannot authorize selection.

Overrides may choose only an otherwise valid candidate. The decision records
the operator and reason and excludes that choice from benchmark learning.

The normal Campaign `create --mode local_wan` path is a Router consumer, not a
separate model selector. It must load the frozen Arena plan referenced by the
summary, bind the accepted still/audio to the content intent and recipe, and
carry the decision and admission fingerprints into the local queue job and
registered asset. Arena benchmarking has a separate typed pre-promotion
context; there is no generic missing-evidence bypass.

## Commands

```bash
scripts/creator-os advanced analyzers
scripts/creator-os advanced arena --root <evidence-root> plan ...
scripts/creator-os advanced arena --root <evidence-root> generate \
  --plan-id <id> --sample-id <id> --mode local_wan --dry-run
scripts/creator-os advanced arena --root <evidence-root> finalize ...
scripts/creator-os advanced arena --root <evidence-root> summary --plan-id <id>
scripts/creator-os advanced router --request <json> --arena-summary <json>
```

No command above schedules, publishes, downloads a model, or permits a provider
fallback.
