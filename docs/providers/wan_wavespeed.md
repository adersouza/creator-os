# Local Wan/LTX And WaveSpeed Motion Providers

Creator OS exposes one explicit motion surface with two independently gated
backends:

- pinned, offline Apple-silicon MLX models for zero-provider-cost generation;
- explicitly authorized WaveSpeed endpoints for paid remote generation.

No model is a silent fallback for another model. A local failure preserves the
static MP4 and honest failure lineage. It never calls WaveSpeed. A paid failure
never falls back to a different billable endpoint.

## Model Policy

| Creator OS model | Backend | Use it for | Output | Audio | Installed size estimate |
|---|---|---|---|---|---:|
| `local_wan22_ti2v_5b_mlx` | local MLX | volume still animation | 704x1280, 24 fps, 5-8 s | none | 19.6 GB |
| `local_wan22_i2v_a14b_q4_mlx` | local MLX | stronger image fidelity and motion | 704x1280, 16 fps, 5-8 s | none | 28.6 GB |
| `local_ltx23_distilled_mlx` | local MLX | fast image/audio-to-video and synchronized generated audio | 576x1024, 24 fps, 5-8 s | source or generated | 38.0 GB plus shared components |
| `local_ltx23_dev_hq_mlx` | local MLX | highest-quality local two-stage finish | 576x1024, 24 fps, 5-8 s | source or generated | 45.6 GB plus shared components |
| `wavespeed_wan27_i2v_pro` | WaveSpeed | best-quality paid still animation | 1080p, 5 s | none | remote |
| `wavespeed_wan27_i2v` | WaveSpeed | lower-cost remote control | 1080p, 5 s | none | remote |
| `wavespeed_wan27_reference` | WaveSpeed | 1-5 identity/style references | 1080p, 5 s | none | remote |
| `wavespeed_wan22_s2v` | WaveSpeed | speech-driven portrait video | 720p, audio length | source required | remote |

The local catalog is intentionally small:

- Wan 5B is the throughput tier.
- Wan A14B q4 is the quality tier that fits a 64 GB Apple-silicon machine more
  honestly than the q8 A14B build, whose publisher warns about heavy swapping
  at that memory size.
- LTX distilled is the fast synchronized audio/video tier.
- LTX dev two-stage HQ is the slowest, highest-quality local tier.

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
- exact Hugging Face revisions for every conversion and dependency;
- original official Wan/LTX source revisions in the installation receipt;
- file size and SHA-256 evidence for every installed model file.

Inspect the catalog and disk plan before accepting licenses or downloading:

```bash
scripts/creator-os local-models catalog
scripts/creator-os local-models plan
```

Install all four tiers:

```bash
scripts/creator-os local-models install --apply \
  --accept-license ltx-2-community-license-agreement \
  --accept-license gemma
```

The full stack currently plans approximately 165.4 GB of downloads and keeps a
30 GiB free-space safety margin. LTX shared VAE, audio VAE, vocoder, projection,
and upscaler files are downloaded once and symlinked into the two LTX model
directories instead of being duplicated.

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
```

The default locations are:

```text
~/.creator-os/runtimes/mlx-video
~/.creator-os/models
```

Override them only as an explicit setup decision with
`CREATOR_OS_LOCAL_MLX_RUNTIME` and `CREATOR_OS_LOCAL_MODELS_ROOT`. Model weights,
receipts, and generated media live outside Git.

## Local Generation

The stable Creator OS mode id remains `local_wan` for historical contract
compatibility, while the operator label is **Local Wan / LTX motion**. The model
selection is explicit on every run.

Wan volume dry-run:

```bash
scripts/creator-os generate --mode local_wan --dry-run \
  --campaign CAMPAIGN --accepted-still /absolute/still.jpg \
  --motion-model local_wan22_ti2v_5b_mlx \
  --motion-prompt "Subtle natural breathing and a gentle camera push" \
  --duration 6 --seed 42 --steps 40
```

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
  --motion-model local_ltx23_distilled_mlx --generate-audio \
  --motion-prompt "She smiles and speaks naturally in a quiet room" \
  --duration 6 --seed 42 --steps 8
```

LTX source-audio and first/last-frame conditioning are supported by the narrow
Reel Factory worker:

```bash
uv run --package reel-factory python -m reel_factory.motion_generate \
  --model local_ltx23_dev_hq_mlx --dry-run --campaign CAMPAIGN \
  --image /absolute/first.jpg --last-image /absolute/last.jpg \
  --audio /absolute/dialogue.wav \
  --prompt "Natural conversational delivery with stable facial identity" \
  --duration 6 --steps 15 --out /absolute/review-only.mp4
```

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
ContentForge, final human review, audio policy where applicable, and AI
disclosure where applicable. This integration cannot schedule, publish,
dispatch QStash, alter account state, or touch production.

## Primary References

- [Official Wan 2.2 repository](https://github.com/Wan-Video/Wan2.2)
- [Official Wan 2.2 I2V-A14B weights](https://huggingface.co/Wan-AI/Wan2.2-I2V-A14B)
- [Official LTX-2 repository](https://github.com/Lightricks/LTX-2)
- [MLX-Video Apple-silicon runtime](https://github.com/Blaizzy/mlx-video)
- [WaveSpeed REST API](https://wavespeed.ai/docs/rest-api)
- [Wan 2.7 Image-to-Video Pro API](https://wavespeed.ai/docs/docs-api/alibaba/alibaba-wan-2.7-image-to-video-pro)
- [Wan 2.2 Speech-to-Video API](https://wavespeed.ai/docs/docs-api/wavespeed-ai/wan-2.2-speech-to-video)
