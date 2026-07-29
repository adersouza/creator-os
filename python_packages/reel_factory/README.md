# Reel Factory

Reel Factory owns Creator OS media creation: direct Soul stills, local static
MP4s, pinned Higgsfield passive motion, safe caption placement/rendering, audio
finishing, and asset lineage. Campaign Factory owns campaign decisions and
ThreadsDashboard owns publishing. Historical local/WaveSpeed workers remain
advanced evidence readers, not normal production routing.

Reel Factory does not initialize or maintain a posting ledger. Its pipeline ends
at a ranked approved-export artifact for Campaign Factory intake.

## Active Path

```text
single-person reference image
  -> Higgsfield Soul V2 with explicit Soul ID
  -> reference-conditioned original + captured composition prompt
  -> optional text-only body-emphasis candidate
  -> QC and human acceptance
  -> local zero-provider-cost static MP4
  -> optional pinned Higgsfield Kling 3 or Seedance 2 passive motion
  -> one-submit authorization, polling, download, probe, and output hash
  -> motion/identity/anatomy evidence gate
  -> Audio Radar segment -> verified AAC -> final MP4 SHA binding
  -> placement.py -> caption_render.py when a safe lane exists
  -> embedded audio_intent.v1 and generated_asset_lineage
  -> Campaign Factory
```

Soul identity, prompt evidence, provider receipts, accepted-still hashes, QC,
and downstream asset IDs remain in lineage. Motion is never the only output;
the static fallback survives a local or remote generation failure.

The count-one `recreate_reel` planner may provide a reviewed Soul anchor plus a
private reference excerpt to a truthfully matched Higgsfield recipe. Calm
recreation uses Kling 3 Turbo; structural recreation uses Seedance Fast.
Motion Control is not part of the product path.

## Operator Commands

Creator OS automatically reuses an exact approved, audited, audio-complete Reel
without changing its bytes before it calls OpenAI, Soul, Kling, or Seedance.
Use `--reuse-policy require_fresh` to bypass reuse. Otherwise choose one of the
three product modes:

```bash
scripts/creator-os create \
  --creator stacey --mode static_reel --style passive_selfie --count 3 \
  --execution cloud --accounts bennett_s33 \
  --audio embedded_trending

scripts/creator-os create \
  --creator stacey --mode calm_animation --style passive_selfie \
  --count 1 --audio embedded_trending

scripts/creator-os create \
  --creator stacey --mode recreate_reel \
  --reference-video /path/to/reference.mp4 \
  --creator-image /path/to/approved-creator.png \
  --recreate-mode auto --reference-authorized --audio auto
```

Generation still stops at local review-ready assets. It does not schedule or
publish.

Package modules remain available for development and focused inspection:

```bash
uv run --package reel-factory python -m reel_factory.generate_assets --help
uv run --package reel-factory python -m reel_factory.reel_pipeline --help
uv run --package reel-factory python -m reel_factory.caption_bank --help
uv run --package reel-factory python -m reel_factory.pipeline_run --help
uv run --package reel-factory python -m reel_factory.review_batch_guard --help
```

`reel_pipeline.py` remains the real command boundary: it owns argument parsing,
run coordination, audio-intent finalization, and watch mode. Its heavy worker
responsibilities are split by stage: `reel_pipeline_render.py` renders one
output, `reel_pipeline_selection.py` discovers and fits captions/recipes, and
`reel_pipeline_support.py` owns shared render policy and lineage helpers. The
entrypoint exposes only the caller-proven compatibility names in `__all__`;
new internal callers import the owning module directly.

`pipeline_run` never calculates campaign strategy. It requires `--plan` with a
validated `campaign_factory.recommendations.next_batch.v1` export and preserves
that Campaign Factory payload in the run state as its decision provenance.

`motion_generate` remains the narrow historical/advanced local and WaveSpeed
worker boundary. The normal intent-first path does not call it. Active paid
motion goes through the authenticated Higgsfield adapter with a Campaign-issued
one-time native-credit authorization. It submits once, never blindly retries an
ambiguous create, downloads the temporary result, and records exact provider
and output evidence. Historical receipts and lineage remain readable and are
never rewritten.

There are no flat top-level Python facade modules and no Reel browser/API
operator surface.

## Caption And Audio Rules

Burned overlay text and the Instagram post caption are different artifacts.
Overlay text must come from `caption_banks/` and pass through `placement.py` and
`caption_render.py`. The canonical font is Instagram Sans Condensed. A missing
safe lane means no burned overlay; the hook can remain the post caption.

LTX can mux source or generated audio into an advanced review derivative and
preserves a hashed WAV sidecar. Experimental LongCat accepts a portrait plus
source speech, preserves the source-audio hash, derives a bounded PCM sidecar,
and muxes an AAC track from that sidecar. Those tracks are never represented as
Instagram native audio.

Normal non-talking production uses Audio Radar finishing: select one active
track and duration-compatible segment, embed AAC, verify the streams, and bind
`audio_intent.v1` to the exact final MP4 SHA. ThreadsDashboard publishes that
completed MP4 unchanged. Native platform audio is a separate explicit policy.

Local model setup is explicit and never occurs during generation:

```bash
scripts/creator-os advanced models plan
scripts/creator-os advanced models install --apply \
  --accept-license ltx-2-community-license-agreement \
  --accept-license gemma
scripts/creator-os advanced models status --deep

scripts/creator-os advanced prompt-expander install --dry-run
scripts/creator-os advanced prompt-expander install --apply
scripts/creator-os advanced prompt-expander status --deep

scripts/creator-os advanced queue status
scripts/creator-os advanced queue cancel-queued \
  --job-id LOCAL_JOB_ID \
  --reason "operator retired the resource-blocked request"
scripts/creator-os advanced queue recover-interrupted \
  --job-id LOCAL_JOB_ID \
  --lineage /absolute/path/reel.mp4.local_video.json \
  --reason "operator verified exact source and request"
scripts/creator-os advanced queue recover-empty-interruption \
  --job-id LOCAL_JOB_ID \
  --lineage /absolute/path/reel.mp4.local_video.json \
  --reason "operator verified crash occurred before any artifact write"
scripts/creator-os advanced queue recover-completed-interruption \
  --job-id LOCAL_JOB_ID \
  --lineage /absolute/path/reel.mp4.local_video.json \
  --reason "operator verified completed output and lineage after power loss"

scripts/creator-os advanced benchmarks record \
  --job-id LOCAL_JOB_ID \
  --lineage /absolute/path/reel.mp4.local_video.json \
  --qc contentforge.motion_specific_qc=/absolute/path/motion-qc.json
scripts/creator-os advanced benchmarks evaluate \
  --candidate-benchmark-id CANDIDATE_A \
  --candidate-benchmark-id CANDIDATE_B \
  --baseline-benchmark-id BASELINE_A \
  --baseline-benchmark-id BASELINE_B
scripts/creator-os advanced benchmarks approve \
  --evaluation-id EVALUATION_ID \
  --approved-by operator@example.com \
  --reason "reviewed exact matched evidence"
```

Treat `advanced models status --deep` as an execution preflight, not merely an
inventory check. Cache-only Hugging Face dependencies are ready only when their
pinned snapshot hashes and exact runtime reference verify. Apply a metadata-only
repair only when `advanced models plan` reports `repairRequired=true`,
`estimatedDownloadBytes=0`, and `requiredFreeBytes=0`; a conflicting, unsafe,
substituted, or unverifiable reference remains blocked with no online fallback.

Installed does not mean resource-admitted. On this 64 GiB Mac, LTX distilled
remains canary-pending and only runs when the live memory gate passes; the
current dev/HQ profile is an installed research tier that is not practically
runnable until a measured lower-memory or compatible quantized path exists.

Local Wan I2V prompt expansion is a separate, narrow preprocessing capability.
It uses the pinned Apache-2.0 Qwen2.5-VL 7B 4-bit conversion through a pinned
MLX-VLM runtime on Apple silicon. The expander inspects the exact accepted still
and turns the operator's motion intent into a detailed, image-aware Wan prompt.
It must include a real primary action; blinking and breathing can be secondary
motion but can never be the whole clip. Expansion runs offline in a macOS
no-network sandbox, records zero provider calls, and emits an authenticated
immutable receipt binding the source SHA-256, original and expanded prompts,
model revision, runtime, and implementation hash. Campaign Factory expands
before Router admission so the signed task and generation lineage bind the
exact expanded prompt. Missing, substituted, forged, or drifted evidence fails
closed.

`local-queue` is an admission lease and recovery journal, not a daemon that can
execute serialized requests later. Busy and current-memory-blocked attempts do
not claim the output namespace. Interrupted recovery preserves every exact
artifact under the queue evidence root before the request becomes retryable.
Benchmark timing and RSS come only from the successful job event; QC receipts
must identify their schema/policy, match the requested check id, and bind to the
exact output SHA-256. Promotion is always a separate explicit approval and does
not run inference.

See [`../../docs/providers/wan_wavespeed.md`](../../docs/providers/wan_wavespeed.md)
for the pinned model matrix, disk budget, licensing, and offline execution
contract.

## Legacy Boundary

The normal root command does not expose Grok/grid/cropped-panel/Qwen/Ollama/
Florence/visual-schema generation. The legacy prompt-generation, six-pack, and
manual grid-crop execution paths were removed after repository and runtime
caller proof. The narrow XAI vision transport remains only for fail-closed
anatomy/postability QC. FFmpeg/FFprobe paths remain active rendering and
evidence infrastructure.

The old FFmpeg pan/zoom motion mode and Kling-only operator mode are retired;
their identifiers remain schema-valid only for historical evidence.

## State And Source

Canonical code is under `reel_factory/`. Its manifest retains render attempts,
prompt/asset lineage, operator ratings, output links, metrics evidence, and
derived media intelligence only; it does not create campaigns, creators,
references, or next-batch plans. Generated media, model weights, provider
receipts, render queues, manifests, and local lineage output remain outside Git.
Curated caption banks, font files, schemas/examples, and sanitized fixtures are
committed source.

See [`PIPELINE_BOUNDARIES.md`](PIPELINE_BOUNDARIES.md) for ownership constraints,
[`CANONICAL_DATA_OWNERS.md`](CANONICAL_DATA_OWNERS.md) for data ownership, and
the root [`CREATOR_OS_SYSTEM_MAP.md`](../../CREATOR_OS_SYSTEM_MAP.md) for the
whole pipeline.

## Test

```bash
uv run python -m pytest python_packages/reel_factory/tests
```

The suite protects provider spend/reservation behavior, identity/QC, lineage,
caption placement, rendering, state transitions, failure handling, review
packages, and active Campaign/ContentForge seams.
