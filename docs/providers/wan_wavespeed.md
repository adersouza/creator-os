# Local Wan/LTX/LongCat And WaveSpeed Motion Providers

Creator OS exposes one explicit motion surface with two independently gated
backends:

- pinned, offline Apple-silicon MLX models for zero-provider-cost generation;
- explicitly authorized WaveSpeed endpoints for paid remote generation.

No model is a silent fallback for another model. A local failure preserves the
static MP4 and honest failure lineage. It never calls WaveSpeed. A paid failure
never falls back to a different billable endpoint.

The Mac-specific adoption and deferral record lives in
[`docs/architecture/MAC_LOCAL_VIDEO_STACK_2026.md`](../architecture/MAC_LOCAL_VIDEO_STACK_2026.md).

## Model Policy

| Creator OS model | Backend | Use it for | Output | Audio | Installed size estimate |
|---|---|---|---|---|---:|
| `local_wan22_ti2v_5b_mlx` | local MLX | volume still animation | 704x1280, 24 fps, 5-8 s | none | 19.6 GB |
| `local_wan22_i2v_a14b_q4_mlx` | local MLX | stronger image fidelity and motion | 704x1280, 16 fps, 5-8 s | none | 28.6 GB |
| `local_ltx23_distilled_mlx` | local MLX | fast image motion with jointly generated audio | 576x1024, 24 fps, 5-8 s | generated | 20 GB plus 8.1 GB shared Gemma |
| `local_ltx23_dev_hq_mlx` | local MLX | HQ motion, source audio, keyframes, retake, and extension | 576x1024, 24 fps, 5-8 s | source, generated, or explicitly preserved retake audio | 37 GB plus 8.1 GB shared Gemma |
| `local_longcat_avatar15_q4_mlx` | local MLX | experimental speech-driven portrait video | 480x832, 25 fps, 3-6 s | source required | 25.0 GB |
| `wavespeed_wan27_i2v_pro` | WaveSpeed | best-quality paid still animation | 1080p, 5 s | none | remote |
| `wavespeed_wan27_i2v` | WaveSpeed | lower-cost remote control | 1080p, 5 s | none | remote |
| `wavespeed_wan27_reference` | WaveSpeed | 1-5 identity/style references | 1080p, 5 s | none | remote |
| `wavespeed_wan22_s2v` | WaveSpeed | speech-driven portrait video | 720p, audio length | source required | remote |

The local catalog is intentionally small:

- Wan 5B is the throughput tier.
- Wan A14B q4 is the quality tier that fits a 64 GB Apple-silicon machine more
  honestly than the q8 A14B build, whose publisher warns about heavy swapping
  at that memory size.
- LTX distilled is a Q4 generated-audio tier. It cannot accept source audio,
  final-frame conditioning, or editing tasks.
- LTX dev/HQ is a Q8 tier with low-RAM block streaming and spatial tiling. It
  owns source-audio animation, first/last frames, keyframe interpolation, beta
  retake, and beta extension. Those beta edits remain review-only until their
  motion and audio receipts pass.
- LongCat Avatar 1.5 q4 is the only Mac-native talking-avatar tier. It is
  isolated in its own runtime and remains experimental until a 64 GB M4 Max
  canary passes identity, lip-sync, anatomy, audio alignment, and memory review.

Wan-Dancer is not in this catalog. Its supported inference path requires eight
CUDA GPUs and its weights are roughly 80 GiB, so presenting it as a runnable
Mac mode would be misleading.

## Pinned Local Installation

`scripts/creator-os local-models` is the only supported networked installation
surface. Generation itself sets `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`, verifies exact model receipts, and refuses to download
or repair anything.

The installer pins:

- MLX-Video runtime commit `87db56a51758fefb748a359b90a5283bb8ba4837`;
- native LTX MLX runtime commit `d2ad8e9948157c14a063aca54e510d3d80c2c463`;
- exact Hugging Face revisions for every conversion and dependency;
- original official Wan/LTX source revisions in the installation receipt;
- file size and SHA-256 evidence for every installed model file.

Wan I2V prompt expansion has its own smaller, independently pinned install:

- `mlx-community/Qwen2.5-VL-7B-Instruct-4bit` at revision
  `fdcc572e8b05ba9daeaf71be8c9e4267c826ff9b`;
- Apache-2.0 model licensing;
- MLX-VLM `0.6.7` at commit
  `b739dfa4b681951acd4a2d439f343e002e6b3013`;
- exact file hashes, runtime environment, worker implementation hash, and a
  cached deep-verification receipt invalidated by any file metadata drift.

The 3B Qwen2.5-VL variant is intentionally not installed because its upstream
license is not appropriate for this commercial workflow. The 7B Apache-2.0
variant is the supported Mac prompt-expansion model.

Inspect the catalog and disk plan before accepting licenses or downloading:

```bash
scripts/creator-os local-models catalog
scripts/creator-os local-models plan
```

Install all five tiers:

```bash
scripts/creator-os local-models install --apply \
  --accept-license ltx-2-community-license-agreement \
  --accept-license gemma
```

The installer computes the exact current download plan and keeps a 30 GiB
free-space safety margin. The LTX tiers use separate Q4 and Q8 repositories plus
one shared 4-bit Gemma text encoder. Legacy BF16 directories are never deleted
by installation or status checks.

The LTX community license requires intelligible disclosure of machine-generated
output and a separate commercial license for entities with at least USD 10
million in annual revenue. The installer requires explicit license
acknowledgement, and LTX lineage carries `aiDisclosureRequired=true`. This is an
operational safeguard, not legal advice.

Verify the runtime and receipts after installation. `--deep` recomputes all
recorded SHA-256 hashes and can take several minutes:

```bash
scripts/creator-os local-models status
scripts/creator-os local-models status --deep

scripts/creator-os advanced prompt-expander install --dry-run
scripts/creator-os advanced prompt-expander install --apply
scripts/creator-os advanced prompt-expander status --deep
```

The default locations are:

```text
~/.creator-os/runtimes/mlx-video
~/.creator-os/runtimes/ltx-2-mlx
~/.creator-os/runtimes/longcat-avatar-mlx
~/.creator-os/models
```

Override them only as an explicit setup decision with
`CREATOR_OS_LOCAL_MLX_RUNTIME`, `CREATOR_OS_LOCAL_LTX_RUNTIME`, and
`CREATOR_OS_LOCAL_MODELS_ROOT`. Model weights, receipts, and generated media
live outside Git. Wan and LTX intentionally use separate pinned Python runtimes.

Inspect legacy BF16 storage without deleting it:

```bash
scripts/creator-os local-models storage-report
```

The command has no deletion mode. Removal remains blocked until the quantized
replacement passes deep verification, a real visual canary, and a reference
audit against queued/recoverable evidence.

## Local Generation

The stable Creator OS mode id remains `local_wan` for historical contract
compatibility, while the operator label remains **Local Wan / LTX motion**.
The model and task are explicit on every run.

Text-to-video is available only for non-identity B-roll. It has no creator-image
conditioning, so Campaign Factory blocks a raw T2V output from being assigned or
published as Stacey, Larissa, Lola, or another creator identity.

Wan volume dry-run:

```bash
scripts/creator-os generate --mode local_wan --dry-run \
  --campaign CAMPAIGN --accepted-still /absolute/still.jpg \
  --motion-model local_wan22_ti2v_5b_mlx \
  --motion-task image_to_video \
  --motion-prompt "She shifts her posture, turns toward the camera, and adjusts her hair" \
  --enable-prompt-expansion \
  --duration 6 --seed 42 --steps 40
```

`--enable-prompt-expansion` invokes the pinned local Qwen-VL preprocessor before
Router admission. It inspects the exact source image and describes a plausible
primary action sequence, secondary motion, camera behavior when useful, and the
stable scene/identity constraints expected by Wan. This follows Wan's official
I2V guidance: describe dynamic action instead of relying on a generic
"blink/breathe" prompt or over-describing a static frame.

The expander is deterministic (`temperature=0`), provider-free, and offline.
Generation never downloads a missing model. Its receipt binds:

- exact input path and SHA-256;
- operator motion intent and expanded text;
- Qwen model/revision/license and deep-verification fingerprint;
- MLX-VLM revision/environment and worker implementation SHA-256;
- local producer authentication and deterministic output-normalization evidence;
- macOS sandbox proof with network denied and writes restricted to temporary
  storage.

Campaign Factory expands first, then builds the exact benchmark/Router
admission from the expanded prompt. The receipt is carried into the queue job
and final asset lineage. A changed image, prompt, model, runtime, implementation
or receipt fingerprint blocks execution. Historical local-motion jobs without
prompt expansion remain readable and keep their original fingerprints.

Wan A14B quality dry-run:

```bash
scripts/creator-os generate --mode local_wan --dry-run \
  --campaign CAMPAIGN --accepted-still /absolute/still.jpg \
  --motion-model local_wan22_i2v_a14b_q4_mlx \
  --motion-prompt "Natural posture shift, realistic hair motion, locked identity" \
  --duration 6 --seed 42 --steps 20
```

LTX synchronized generated-audio dry-run:

```bash
scripts/creator-os generate --mode local_wan --dry-run \
  --campaign CAMPAIGN --accepted-still /absolute/still.jpg \
  --motion-model local_ltx23_distilled_mlx \
  --motion-task image_to_video --generate-audio \
  --motion-prompt "She smiles and speaks naturally in a quiet room" \
  --duration 6 --seed 42 --steps 8
```

LTX source-audio and first/last-frame conditioning are supported by the narrow
Reel Factory worker:

```bash
uv run --package reel-factory python -m reel_factory.motion_generate \
  --model local_ltx23_dev_hq_mlx --dry-run --campaign CAMPAIGN \
  --task audio_image_to_video \
  --image /absolute/first.jpg --last-image /absolute/last.jpg \
  --audio /absolute/dialogue.wav \
  --prompt "Natural conversational delivery with stable facial identity" \
  --duration 6 --steps 15 --out /absolute/review-only.mp4
```

Q8 keyframe interpolation, retake, and extension are explicit tasks rather than
hidden post-processing fallbacks:

```bash
uv run --package reel-factory python -m reel_factory.motion_generate \
  --model local_ltx23_dev_hq_mlx --dry-run --campaign CAMPAIGN \
  --task keyframe_interpolation --image /absolute/start.jpg \
  --last-image /absolute/end.jpg --generate-audio \
  --prompt "A coherent natural transition with stable identity" \
  --duration 6 --out /absolute/keyframe-review.mp4

uv run --package reel-factory python -m reel_factory.motion_generate \
  --model local_ltx23_dev_hq_mlx --dry-run --campaign CAMPAIGN \
  --task video_retake --source-video /absolute/source.mp4 \
  --retake-start-frame 2 --retake-end-frame 5 --preserve-audio \
  --prompt "Repair the selected segment while preserving the scene" \
  --out /absolute/retake-review.mp4

uv run --package reel-factory python -m reel_factory.motion_generate \
  --model local_ltx23_dev_hq_mlx --dry-run --campaign CAMPAIGN \
  --task video_extend --source-video /absolute/source.mp4 \
  --extend-frames 3 --extend-direction after --generate-audio \
  --prompt "Continue the same camera motion and performance" \
  --out /absolute/extended-review.mp4
```

LongCat talking-avatar dry-run:

```bash
scripts/creator-os generate --mode local_wan --dry-run \
  --campaign CAMPAIGN --accepted-still /absolute/portrait.jpg \
  --motion-model local_longcat_avatar15_q4_mlx \
  --motion-task audio_image_to_video --audio /absolute/dialogue.wav \
  --motion-prompt "Natural direct-to-camera delivery with stable identity" \
  --duration 4 --seed 42 --steps 8
```

The adapter accepts the exact portrait, source audio, and prompt; computes the
Whisper features offline; derives synchronized PCM/AAC audio for the MP4 while
preserving the exact source-audio hash; retains a hashed WAV sidecar; and fails
if either artifact is absent. It does not call the
upstream demo CLI, use its hard-coded sample media, or accept a silent MP4 as a
success. A dry-run proves routing only. It does not prove this experimental
model can produce acceptable output on the current Mac.

Source audio and generated audio are mutually exclusive. Wan does not accept
audio. LTX audio is muxed into the derivative MP4 and retained as a hashed WAV
sidecar for review, but it is **not** Instagram native audio. Campaign Factory
records `nativeAudioResolved=false`, requires human audio review, and keeps the
asset unpublishable until downstream policy is satisfied.

Every run preserves the input image SHA-256, optional last-image and audio
SHA-256 values, exact model revision, installation-manifest SHA-256, seed,
prompt, dimensions, frame rate, duration, output SHA-256, and FFprobe evidence.
It renders to named partial files and atomically promotes only a valid MP4.
Interrupted work remains recoverable evidence rather than a finished-looking
asset.

## Local Lease Journal, LoRAs, Benchmarks, And Motion QC

All local models share one machine-wide nonblocking worker lease and admission
journal; this is not a background executable queue or daemon. Before an exact
synchronous run starts on macOS, admission checks the model's conservative
memory profile against the static machine ceiling and current `vm_stat`
availability while retaining a 6 GiB default reserve for macOS and other local
workloads. A missing current-memory measurement fails closed. This is resource
admission, not proof that a profile is fast or visually good.

The Q4/Q8 catalog estimates remain conservative for queue admission even though
the LTX runtime can stream transformer blocks and tile spatially. A successful
installation is not a quality claim. Both tiers require measured Mac canaries,
and the Q8 editing tasks additionally require output-bound motion/audio QC.

Jobs are fully fingerprinted before execution; state is an append-only,
hash-chained, fsynced JSONL journal. A busy or resource-blocked invocation does
not occupy its requested output/lineage namespace and can be retried exactly.
An abandoned running job becomes `interrupted` on the next lease. Recovery
cryptographically binds the lineage to the queued model/input/task/parameters,
moves existing final/partial/sidecar/lineage artifacts into an immutable queue
recovery folder, records their hashes, and only then returns the same request to
`queued`. Creator OS never deletes this evidence, rotates workers, starts an
unowned backlog request, or silently retries a model failure.

```bash
scripts/creator-os local-queue status
scripts/creator-os local-queue cancel-queued \
  --job-id LOCAL_JOB_ID \
  --reason "operator retired the resource-blocked request"
scripts/creator-os local-queue recover-interrupted \
  --job-id local_video_0123456789abcdef01234567 \
  --lineage /absolute/path/reel.mp4.local_video.json \
  --reason "operator verified exact source and request"
scripts/creator-os local-queue recover-empty-interruption \
  --job-id local_video_0123456789abcdef01234567 \
  --lineage /absolute/path/reel.mp4.local_video.json \
  --reason "operator verified crash occurred before any artifact write"
scripts/creator-os local-queue recover-completed-interruption \
  --job-id local_video_0123456789abcdef01234567 \
  --lineage /absolute/path/reel.mp4.local_video.json \
  --reason "operator verified completed output and lineage after power loss"
```

Wan and LTX LoRAs are accepted only after explicit registration records the
file SHA-256, base-model revision, source revision, family, and license. A LoRA
from another family or revision is rejected. Creator OS deliberately does not
install Wan Lightning by default: applying its high/low pair to the q4 A14B
runtime may dequantize enough layers to exceed a 64 GB machine's safe memory
budget. LTX camera-control and IC-LoRAs are also not installed because the
published artifacts target a different LTX architecture or pipeline than the
pinned 2.3 MLX runtime.

Measured model promotions require matched task fingerprints on identical
hardware, real wall-time and peak-memory observations, output SHA-256 values,
verifiable QC receipt hashes, and an explicit human approval. Missing QC is not
converted into a pass.

The local runner writes wall time and peak RSS into the hash-chained successful
job event; the benchmark command cannot accept operator-supplied measurements.
`record` verifies the completed lineage and output, imports exact QC receipts
bound to that output SHA-256, and stores immutable copies. `evaluate` only
compares recorded matched evidence. `approve` reloads the persisted eligible
evaluation and re-verifies its QC evidence; it performs no inference.

```bash
scripts/creator-os local-benchmarks record \
  --job-id local_video_0123456789abcdef01234567 \
  --lineage /absolute/path/reel.mp4.local_video.json \
  --qc contentforge.motion_specific_qc=/absolute/path/motion-qc.json

scripts/creator-os local-benchmarks evaluate \
  --candidate-benchmark-id CANDIDATE_A \
  --candidate-benchmark-id CANDIDATE_B \
  --baseline-benchmark-id BASELINE_A \
  --baseline-benchmark-id BASELINE_B

scripts/creator-os local-benchmarks approve \
  --evaluation-id EVALUATION_ID \
  --approved-by operator@example.com \
  --reason "reviewed matched output-bound QC and measured resource evidence"
```

ContentForge's `motion-qc` command evaluates supplied real evidence for motion
amount, temporal discontinuities, freezes, loops, anatomy, identity, lip-sync,
and audio alignment. Missing or invalid evidence blocks the asset. Campaign
Factory registers every generated motion asset with
`motion_specific_qc_required`; audio motion also requires
`audio_video_alignment_qc_required`, and LongCat additionally requires
`lip_sync_qc_required`.

## Accurate 2026 Capability Boundary

| Capability | Current Creator OS status |
|---|---|
| Wan still animation | installed: TI2V-5B q8 volume and I2V-A14B q4 quality |
| Local text-to-video | exposed explicitly through Wan TI2V and LTX |
| LTX source/generated synchronized audio | Q4 generated and Q8 source/generated paths are explicit; review-only, never native Instagram audio |
| LTX first/last-frame and keyframe conditioning | Q8 only; exact start/end SHA-256 values are retained |
| LTX Retake and Extend | Q8 beta tasks exposed with source-video fingerprinting, bounded ranges, collision checks, and output validation |
| LTX generation-time spatial 2x | part of the distilled/HQ generation pipeline; not misrepresented as an arbitrary-video upscaler |
| Multiple quality tiers | Wan volume/quality plus LTX Q4 fast and Q8 HQ; all require measured canaries before promotion |
| Generic Wan/LTX LoRA inputs | implemented with provenance registration and family/revision checks |
| Local talking from image and audio | installed as experimental LongCat Avatar 1.5 q4; visual canary still required |
| Machine-wide lease, Mac memory admission, and recovery journal | implemented and operator-integrated; intentionally not a daemon |
| Measured benchmark/promotions | implemented; promotion is evidence-bound and manual |
| Motion-specific QC contract | implemented as a fail-closed evidence evaluator |
| LTX camera-control LoRAs | deferred: official artifacts do not match the pinned LTX-2.3 22B MLX path |
| Wan Lightning LoRAs | deferred: unsafe q4 merge-memory behavior has not passed a 64 GB canary |
| Wan FLF2V/VACE/Animate/S2V, pose speaking, Wan-Dancer | deferred: no proven supported Mac MLX runtime |
| LTX arbitrary multi-keyframe graphs and LipDub | deferred: two-endpoint keyframes are supported; arbitrary graphs and experimental LipDub lack a production Mac contract |
| LivePortrait face motion | deferred: the default detector weights carry a non-commercial restriction and cannot enter this commercial pipeline |
| Phosphene HTTP queue | not adopted: Creator OS keeps one durable queue, resource lock, and provenance owner instead of splitting recovery state |

Deferred means Creator OS refuses to claim or route the capability. It is not a
hidden fallback to WaveSpeed or another paid provider.

## WaveSpeed Setup And Spend Gates

Set the API credential, the machine-local HMAC secret, and all four budget
limits. A missing limit blocks the request instead of assuming a default.

```bash
# Load these values from the machine's secret manager before running.
export WAVESPEED_API_KEY
export CREATOR_OS_SPEND_AUTH_SECRET # at least 32 bytes
export WAVESPEED_DAILY_BUDGET_USD=20
export WAVESPEED_MONTHLY_BUDGET_USD=100
export WAVESPEED_COHORT_MAX_USD=10
export WAVESPEED_MIN_BALANCE_USD=2
```

Always dry-run first. Apply additionally requires `--confirm-paid`, an existing
`--workspace`, and a finite `--max-usd` for that exact request.

```bash
scripts/creator-os generate --mode best_motion --dry-run \
  --campaign CAMPAIGN --accepted-still /absolute/still.jpg \
  --motion-model wavespeed_wan27_i2v_pro \
  --motion-prompt "Subtle natural breathing and a gentle camera push" \
  --resolution 1080p --duration 5 --seed 42
```

Campaign Factory prices and reserves one exact request, checks the live model
catalog and account balance, and signs a short-lived authorization. Reel Factory
verifies that signature before upload, records a durable submission intent
before the paid POST, never retries an ambiguous submit, retries only transient
result GETs, and downloads temporary output immediately.

## Review Boundary

Every local or WaveSpeed apply retains the static MP4 fallback. A new motion
output enters Campaign Factory as review-only with explicit blockers for
motion-specific ContentForge evidence, final human review, audio/lip-sync policy
where applicable, and AI disclosure where applicable. This integration cannot
schedule, publish, dispatch QStash, alter account state, or touch production.

ContentForge's current `motion-qc` command is an evidence evaluator, not the
analyzer suite itself. It verifies supplied temporal, freeze, anatomy, identity,
audio-alignment, and lip-sync analyzer evidence against the exact media SHA-256;
it does not invent measurements or call a model/provider. Until those analyzers
have produced a complete passing receipt, generated motion remains blocked.
Register a finished receipt through the supported local boundary:

```bash
scripts/creator-os motion-qc-register \
  --rendered-asset-id ASSET_ID \
  --receipt /absolute/path/to/motion-qc.json \
  --operator OPERATOR_ID
```

Campaign Factory re-hashes both the media and receipt, stores an append-only
immutable record, and rechecks the media hash on every publishability decision.
A generic ContentForge audit or human approval cannot clear the motion,
audio-alignment, lip-sync, or text-only identity-assignment gates.

## Primary References

- [Official Wan 2.2 repository](https://github.com/Wan-Video/Wan2.2)
- [Official Wan 2.2 TI2V-5B model](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B-Diffusers)
- [Official Wan 2.2 I2V-A14B weights](https://huggingface.co/Wan-AI/Wan2.2-I2V-A14B)
- [MLX-VLM Apple-silicon runtime](https://github.com/Blaizzy/mlx-vlm)
- [Qwen2.5-VL 7B MLX 4-bit model](https://huggingface.co/mlx-community/Qwen2.5-VL-7B-Instruct-4bit)
- [Official LTX-2 repository](https://github.com/Lightricks/LTX-2)
- [MLX-Video Apple-silicon runtime](https://github.com/Blaizzy/mlx-video)
- [LongCat Avatar 1.5](https://github.com/meituan-longcat/LongCat-Video)
- [LongCat Avatar MLX runtime](https://github.com/xocialize/longcat-avatar-mlx)
- [WaveSpeed REST API](https://wavespeed.ai/docs/rest-api)
- [Wan 2.7 Image-to-Video Pro API](https://wavespeed.ai/docs/docs-api/alibaba/alibaba-wan-2.7-image-to-video-pro)
- [Wan 2.2 Speech-to-Video API](https://wavespeed.ai/docs/docs-api/wavespeed-ai/wan-2.2-speech-to-video)
