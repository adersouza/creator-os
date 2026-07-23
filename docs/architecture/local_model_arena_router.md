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
cohort, and at least four seeds per source: a fixed minimum of eight matched
samples per model arm. Smaller runs are explicitly exploratory.

Every competing model in a promotion-eligible comparison receives the exact
same creator, identity, intent, source, prompt, seed, duration, and resolution
grid. A model-specific subset is not described or analyzed as matched evidence.
The identity and intent fingerprints are not operator assertions. Every sample
embeds one schema-valid `CreatorIdentityProfileV1` and one schema-valid
`ContentIntentV1`. Arena recomputes both fingerprints, requires the profile
creator to match the sample creator, requires the intent to reference that
profile, and requires every exact typed-input SHA-256 to belong to the intent's
reviewed authorization cohort. The benchmark recipe remains narrower: it binds
the canonical role-preserving inputs for one execution cell. The immutable
plan store also writes content-addressed copies under
`creator_identity_profiles/` and `content_intents/`; missing or changed copies
make the plan unloadable.
Queue jobs, measured benchmark receipts, summaries, and Router decisions retain
the same IDs and fingerprints. Historical entries without these links remain
readable but cannot support promotion.

The six task families have a strict typed-input matrix. Text-to-video consumes
no model media. Its normalized prompt is stored as one canonical compact JSON
artifact whose file SHA-256 equals the task-plus-prompt fingerprint; the plan
binds it separately as `promptSource`. That artifact travels through Arena,
ContentForge finalization, Creative Approval, and Campaign lineage, but it is
never passed to the model as an image, treated as an identity reference, or
used as a static fallback. Image-to-video consumes one image; audio-driven
image-to-video consumes one image and one audio source; keyframe consumes first
and last images; Retake and Extend consume one source video with their
task-specific controls. Missing, extra, wrong-role, substituted, or drifted
inputs fail closed at record construction, plan load, admission, and execution.

New identity reference sets use local schema v4. Each image in the set must
resolve one-to-one to an exact fingerprint-bearing entry in the reviewed
`CreatorIdentityProfileV1.identityReferences` array. The binding is included in
the reference-set identity material and attestation. Duplicate reference
identities or fingerprints, unresolved or omitted reviewed images, creator or
profile mismatch, and changed source bytes are rejected. A non-file reference
without a media fingerprint may identify a creator model but cannot authorize
local image bytes. Historical v1-v3 reference sets remain readable and are
promotion-ineligible; no provenance is inferred for them.

Operators build these records from reviewed facts and exact media, not invented
fingerprints:

```bash
scripts/creator-os advanced arena --root "$ARENA_ROOT" build-records \
  --reviewed-identity-facts "$REVIEWED_FACTS_JSON" \
  --source "$EXACT_SOURCE_IMAGE" \
  --goal "subtle natural portrait motion" \
  --content-surface reel \
  --media-kind video \
  --style-lane subtle_motion \
  --concept-tag lifestyle \
  --produced-at "$UTC_TIMESTAMP" \
  --output-root "$ARENA_ROOT/record-builder"
```

`--source` remains the compatible single-image form. Keyframe, audio, Retake,
and Extend record construction uses repeatable typed inputs so every consumed
asset is fingerprinted in order. For example, pass `--input` once with
`source-video=/exact/input.mp4` and again with `audio=/exact/input.wav`.

The reviewed-facts file supplies the explicit creator key, display name, model
profile, identity references, reviewer, and review timestamp. The helper hashes
that file and source asset, validates timestamp order, emits canonical records,
and reports zero provider calls and zero production writes.

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
bound to the manifest, file metadata, pinned runtime executable and package
environment, OS build, MLX version, and exact FFmpeg/FFprobe executable hashes;
any change invalidates it, and the selected model is revalidated at execution.
The isolated child also receives `IMAGEIO_FFMPEG_EXE` set to that exact verified
FFmpeg binary. Before queue admission—and again immediately before generation—
the sandboxed pinned Python imports `imageio_ffmpeg` and proves
`get_ffmpeg_exe()` resolves the same exact path. Consumer discovery failure or
drift therefore blocks before model compute rather than failing during final
video encoding.
Arena samples, benchmark receipts, promotion cohorts, Router decisions, queue
jobs, and asset lineage retain that runtime fingerprint and the evaluated model
license policy. Mixed toolchains or noncompliant commercial use fail closed.

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

### Trusted-QC ownership and unavailable evidence

The terminal QC chain deliberately does not pretend that one analyzer measures
everything:

| Evidence | Canonical producer | Terminal behavior |
|---|---|---|
| exact bytes, container, codec, duration, dimensions, frame rate | ContentForge trusted media analysis | measured from a read-only snapshot with FFprobe; input and snapshot are rehashed after analysis |
| motion amount, discontinuity candidates/rate, frozen frames, loop seam, full-duration frame-set identity | ContentForge temporal analyzer | measured at 8 fps; missing coverage blocks analysis |
| audio stream integrity and container-level A/V start/duration offsets | ContentForge audio analyzer | measured only when an audio stream exists; missing audio remains unavailable |
| speaking lip-sync | ContentForge local face/mouth tracker plus decoded PCM | measured only with sufficient single-face coverage, speech activity, sample count, correlation, and bounded offset |
| creator identity and face stability | Reel Factory identity verification | separate ArcFace/reference-set receipt bound into Arena; ContentForge does not duplicate or synthesize it |
| anatomy, transient artifacts, realism, intent, conversion usefulness | authenticated blinded human review | human evidence; no automatic anatomy score is invented |
| no declared burned overlay | ContentForge sampled-pixel overlay analyzer | still inspects sampled pixels with OCR; only a completed scan with no detected text is `not_applicable`, while undeclared text or app UI blocks |
| declared burned overlay | ContentForge sampled-pixel overlay analyzer | caller-authored overlay JSON is rejected; canonical Apple Vision/Tesseract OCR records frame timestamps, text, boxes, confidence, full-duration sampling coverage, readability, platform safe-zone findings, timed text changes, and face overlap when canonical face geometry exists; semantic delivery is evaluated only for the declared overlay |

Every implementation is named in `AnalyzerRegistryV1` with an exact repository
path and SHA-256. The trusted analysis and final receipt are HMAC-authenticated;
`CREATOR_OS_EVIDENCE_AUTH_SECRET` must be configured locally. Registry or
implementation drift, a changed media hash, missing required evidence, an
unsupported/unavailable OCR tool, incomplete sampling, or a caller-authored
verdict fails closed. Pixel delivery/readability passing remains separate from
overlay semantic completeness: the measured timed sequence is passed to the
existing Pipeline Contracts semantic policy, so an unchanged setup such as
`men, stop doing this:` still blocks for a missing payoff.

An existing-media analyzer canary is allowed before model generation. It must
read one preserved MP4, use a temporary read-only snapshot, provide the expected
media SHA-256, and retain no canonical evidence unless the operator later
approves the Arena plan. The canary proves analyzer execution only. It does not
prove creator identity, anatomy, model quality, promotion eligibility, or
publishing readiness.

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

Content Intent may authorize several reviewed sources for matched planning,
but promotion does not cover that superset automatically. Admission resolves
the Router's winning exact Arena sample IDs back through the frozen plan,
reconstructs each sample's canonical role-preserving input bindings, and
requires the requested execution cell to be in that measured cohort. New
authorized-but-unbenchmarked inputs, wrong-role reuse, and cross-task sample
leakage fail closed.

Overrides may choose only an otherwise valid candidate. The decision records
the operator and reason and excludes that choice from benchmark learning.

The normal Campaign `create --mode local_wan` path is a Router consumer, not a
separate model selector. It must load the frozen Arena plan referenced by the
summary, bind the exact task-specific media inputs—or the zero-media T2V prompt
artifact—to the content intent and recipe, and carry the decision and admission
fingerprints into the local queue job and registered asset. Arena benchmarking
has a separate typed pre-promotion context; there is no generic missing-evidence
bypass.

## Commands

Use the operator launcher for Arena work. It selects an isolated, locked,
offline `reel-factory[identity]` environment (`insightface`, `onnxruntime`, and
OpenCV) instead of contaminating the default workspace environment. On a new
machine, the explicit one-time bootstrap below may download only the
lockfile-pinned Python packages into uv's cache without modifying the workspace
environment:

```bash
uv run --isolated --locked --all-packages --extra identity \
  python -c "import cv2, insightface, onnxruntime"
```

The launcher itself is offline and cannot fetch dependencies or model weights;
promotion-eligible commands must go through `scripts/creator-os`.

```bash
scripts/creator-os advanced analyzers
scripts/creator-os advanced identity identity-health \
  --creator <creator> --root <identity-root>
scripts/creator-os advanced arena --root <evidence-root> plan \
  --identity-root <identity-root> ...
scripts/creator-os advanced arena --root <evidence-root> generate \
  --plan-id <id> --sample-id <id> --mode local_wan \
  --identity-root <identity-root> --dry-run
scripts/creator-os advanced arena --root <evidence-root> finalize \
  --identity-root <identity-root> ...
scripts/creator-os advanced arena --root <evidence-root> summary --plan-id <id>
scripts/creator-os advanced router --request <json> --arena-summary <json>
```

Before a promotion-eligible plan is created, and again before each generation
and finalization, Arena initializes the real identity provider and verifies the
current ArcFace weights, signed v4 reference set, analyzer implementation, and
exact CreatorIdentityProfile binding for every creator in the plan. Missing
extras, missing or historical reference evidence, implementation drift, and
profile substitution therefore fail before queue or QC work. Exploratory plans
remain usable without identity setup but never become promotion evidence.

No command above schedules, publishes, downloads a model, or permits a provider
fallback.
