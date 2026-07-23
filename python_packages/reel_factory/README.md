# Reel Factory

Reel Factory owns Creator OS media creation: direct Soul stills, local static
MP4s, local Wan/LTX/LongCat and WaveSpeed motion, safe caption placement/rendering,
audio intent, and asset lineage. Campaign Factory owns campaign decisions and ThreadsDashboard
owns publishing.

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
  -> optional pinned local Wan/LTX/LongCat MLX or authorized WaveSpeed motion
  -> machine-wide local worker lease + measured Mac memory admission
  -> motion/identity/anatomy/audio/lip-sync evidence gate
  -> placement.py -> caption_render.py when a safe lane exists
  -> audio_intent.v1 and generated_asset_lineage
  -> Campaign Factory
```

Soul identity, prompt evidence, provider receipts, accepted-still hashes, QC,
and downstream asset IDs remain in lineage. Motion is never the only output;
the static fallback survives a local or remote generation failure.

## Operator Commands

Use the monorepo command for normal work:

```bash
scripts/creator-os create --mode soul_static --dry-run \
  --campaign campaign_slug --accepted-still /path/to/accepted.png

scripts/creator-os create --mode soul_static --apply --confirm-paid \
  --target Stacey --workspace "$PWD" --campaign campaign_slug \
  --reference-image /path/to/reference.png --max-credits 2 --wait --download

scripts/creator-os create --mode local_wan --dry-run \
  --campaign campaign_slug --accepted-still /path/to/accepted.png \
  --motion-model local_wan22_ti2v_5b_mlx \
  --motion-prompt "Natural breathing and a gentle camera push"

scripts/creator-os create --mode local_wan --dry-run \
  --campaign campaign_slug --accepted-still /path/to/accepted.png \
  --motion-model local_ltx23_distilled_mlx \
  --motion-task image_to_video --generate-audio \
  --motion-prompt "Natural movement with synchronized room sound"

scripts/creator-os create --mode local_wan --dry-run \
  --campaign campaign_slug --accepted-still /path/to/portrait.png \
  --motion-model local_longcat_avatar15_q4_mlx \
  --motion-task audio_image_to_video --audio /path/to/dialogue.wav \
  --motion-prompt "Natural direct-to-camera delivery with stable identity"

scripts/creator-os create --mode best_motion --dry-run \
  --campaign campaign_slug --accepted-still /path/to/accepted.png \
  --motion-model wavespeed_wan27_i2v_pro --resolution 1080p --duration 5 \
  --motion-prompt "Natural breathing and a gentle camera push"
```

The second command requires confirmation, target identity, exact checkout, and
a finite native-credit cap. It still stops at local review-ready assets.

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

`motion_generate` is the narrow motion worker boundary. Local Wan/LTX/LongCat
can execute without provider authority; every WaveSpeed apply requires a
Campaign-issued, short-lived v2 spend authorization bound to exact input hashes
and parameters. Local tasks, LoRAs, inputs, and source audio are explicit; the
worker never silently changes the model or task.
The worker submits a paid prediction once, never automatically retries an
ambiguous POST, and downloads the temporary result immediately.

There are no flat top-level Python facade modules and no Reel browser/API
operator surface.

## Caption And Audio Rules

Burned overlay text and the Instagram post caption are different artifacts.
Overlay text must come from `caption_banks/` and pass through `placement.py` and
`caption_render.py`. The canonical font is Instagram Sans Condensed. A missing
safe lane means no burned overlay; the hook can remain the post caption.

LTX can mux source or generated audio into a review derivative and preserves a
hashed WAV sidecar. Experimental LongCat accepts a portrait plus source speech,
preserves the source-audio hash, derives a bounded PCM sidecar, and muxes an AAC
track from that sidecar. Those tracks are never represented as Instagram native audio.
Reel Factory still emits `audio_intent.v1`; ThreadsDashboard separately resolves
and verifies publishable native audio.

Local model setup is explicit and never occurs during generation:

```bash
scripts/creator-os advanced models plan
scripts/creator-os advanced models install --apply \
  --accept-license ltx-2-community-license-agreement \
  --accept-license gemma
scripts/creator-os advanced models status --deep

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
