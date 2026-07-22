# Wan And WaveSpeed Motion Providers

Creator OS has two explicit motion backends. They share one operator surface
but never silently substitute for one another.

## Model Policy

| Creator OS model | Backend | Purpose | Default output | Cost |
|---|---|---|---|---|
| `local_wan22_ti2v_5b_mlx` | local MLX | private/offline still animation | 704x1280, 24 fps, 6 s | free after local setup |
| `wavespeed_wan27_i2v_pro` | WaveSpeed | best-quality still animation | 1080p, 5 s | $0.60; 2K/4K are explicit |
| `wavespeed_wan27_i2v` | WaveSpeed | lower-cost control | 1080p, 5 s | $0.75 |
| `wavespeed_wan27_reference` | WaveSpeed | 1-5 identity/style references, including a video | 1080p, 5 s | $1.60 |
| `wavespeed_wan22_s2v` | WaveSpeed | speech-driven portrait video | 720p, audio length | $0.30 per 5 s block |

Wan 2.7 Pro is the `best_motion` default because WaveSpeed documents superior
motion/detail and exact resolution-duration pricing. Standard Wan 2.7 remains
available for controlled cost/quality comparison. The speaking route is not a
generic image-animation fallback: it requires an audio file and uses the S2V
endpoint explicitly.

## Local Wan Setup

Local generation uses the official `Wan-AI/Wan2.2-TI2V-5B` weights through the
community MLX-Video Apple-silicon runtime. Creator OS never clones code,
installs packages, converts weights, or downloads a model during a generation
run. Prepare a dedicated Python environment and converted model directory as a
separate operator action, then point Creator OS at them:

```bash
python3.12 -m venv "$HOME/.creator-os/runtimes/mlx-video"
"$HOME/.creator-os/runtimes/mlx-video/bin/pip" install \
  'git+https://github.com/Blaizzy/mlx-video.git@87db56a51758fefb748a359b90a5283bb8ba4837' \
  torch huggingface_hub
"$HOME/.creator-os/runtimes/mlx-video/bin/huggingface-cli" download \
  Wan-AI/Wan2.2-TI2V-5B \
  --local-dir "$HOME/.creator-os/models/Wan2.2-TI2V-5B"
"$HOME/.creator-os/runtimes/mlx-video/bin/python" -c \
  "from transformers import AutoTokenizer; AutoTokenizer.from_pretrained('google/umt5-xxl')"
"$HOME/.creator-os/runtimes/mlx-video/bin/python" -m \
  mlx_video.models.wan_2.convert \
  --checkpoint-dir "$HOME/.creator-os/models/Wan2.2-TI2V-5B" \
  --output-dir "$HOME/.creator-os/models/Wan2.2-TI2V-5B-MLX"

export CREATOR_OS_LOCAL_WAN_PYTHON=/absolute/path/to/mlx-video-venv/bin/python
export CREATOR_OS_LOCAL_WAN_MODEL_DIR="$HOME/.creator-os/models/Wan2.2-TI2V-5B-MLX"
```

The capability probe requires Apple silicon, imports both `mlx` and
`mlx_video`, verifies the pinned MLX-Video commit, proves the UMT5 tokenizer is
already cached, hashes all required converted weights, and verifies the config
is exactly Wan 2.2 TI2V-5B. Generation runs with Hugging Face and Transformers
offline flags, so it cannot turn into a network download. The worker renders
portrait 704x1280 at 24 fps, uses a deterministic non-negative seed, and
enforces the model's `4n+1` frame contract. It renders to a partial output,
validates dimensions, codec, frame rate, and duration, then atomically promotes
the MP4. Interrupted and failed runs retain an honest lineage state instead of
leaving a finished-looking output.

```bash
scripts/creator-os generate --mode local_wan --dry-run \
  --campaign CAMPAIGN --accepted-still /absolute/still.jpg \
  --motion-prompt "Subtle natural breathing and a gentle camera push" \
  --duration 6 --seed 42 --steps 40
```

## WaveSpeed Setup And Spend Gates

Set the API credential, the existing machine-local HMAC secret, and all four
budget limits. A missing limit blocks the request rather than assuming a
default.

```bash
# Load these two values from the machine's secret manager before running.
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

scripts/creator-os generate --mode best_motion --apply --confirm-paid \
  --workspace /absolute/creator-os-workspace --max-usd 0.60 \
  --campaign CAMPAIGN --accepted-still /absolute/still.jpg \
  --motion-model wavespeed_wan27_i2v_pro \
  --motion-prompt "Subtle natural breathing and a gentle camera push" \
  --resolution 1080p --duration 5 --seed 42
```

Campaign Factory prices and reserves one exact request, checks the live model
catalog, exact `unit_price`, and account balance,
and signs a short-lived v2 authorization. Reel Factory verifies that signature
before any upload. It records a durable submission intent before the paid POST,
never retries an ambiguous submit, retries only transient result GETs, and
downloads the temporary output immediately. Authorization and result evidence
contain hashes, not API keys or signed download URLs.

## Review Boundary

Every local or WaveSpeed apply creates the static MP4 fallback first. A motion
output enters Campaign Factory with `asset_state=approved_but_not_publishable`,
no burned caption claim, no burned audio claim, and blockers for ContentForge,
final human review, and native-audio resolution. This integration does not
schedule, publish, dispatch QStash, alter account state, or touch production.

## Primary References

- [Official Wan 2.2 repository](https://github.com/Wan-Video/Wan2.2)
- [Official Wan 2.2 TI2V-5B weights](https://huggingface.co/Wan-AI/Wan2.2-TI2V-5B)
- [MLX-Video Apple-silicon runtime](https://github.com/Blaizzy/mlx-video)
- [WaveSpeed REST API](https://wavespeed.ai/docs/rest-api)
- [WaveSpeed media upload API](https://wavespeed.ai/docs/upload-files-api)
- [Wan 2.7 Image-to-Video Pro API](https://wavespeed.ai/docs/docs-api/alibaba/alibaba-wan-2.7-image-to-video-pro)
- [Wan 2.7 Reference-to-Video API](https://wavespeed.ai/docs/docs-api/alibaba/alibaba-wan-2.7-reference-to-video)
- [Wan 2.2 Speech-to-Video API](https://wavespeed.ai/docs/docs-api/wavespeed-ai/wan-2.2-speech-to-video)
