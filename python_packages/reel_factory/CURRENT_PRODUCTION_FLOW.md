# Current Production Flow

This is the active Reel Factory operator path as of 2026-06-13. Treat this as the default unless the user explicitly asks for a legacy experiment.

## Active Path

```text
single-person reference image
→ Higgsfield direct reference-image generation
→ Stacey Soul ID
→ one 9:16 still image
→ captured Higgsfield prompt + lineage
→ optional append-only body emphasis
→ human/QC accepted still
→ deterministic Kling motion prompt
→ Kling image-to-video
→ stop before Campaign Factory registration
```

The active still-image command is:

```bash
python3 generate_assets.py reference-image \
  --reference <reference-image> \
  --creator Stacey \
  --stem <clip_stem> \
  --body-emphasis none|bust|bust_hips \
  --wait
```

Dry-run first with:

```bash
python3 generate_assets.py reference-image-dry-run \
  --reference <reference-image> \
  --creator Stacey \
  --stem <clip_stem> \
  --body-emphasis none|bust|bust_hips \
  --wait
```

## Active Defaults

- Creator: `Stacey`
- Stacey Soul ID: `d63ea9c7-b2c7-439c-bf0c-edfdf9938a36`
- Image model: `text2image_soul_v2`
- Image aspect ratio: `9:16`
- Image quality: `2k`
- Higgsfield input: direct `--image <reference-image>`
- Identity: Soul ID via `--custom_reference_id`
- Prompt strategy: use Higgsfield's reference-image understanding; only append body emphasis when requested.

Do not use Grok, Qwen, Ollama, Florence, visual-schema extraction, grids, panel crops, or prompt-json generation for the normal operator still-image path.

## Body Emphasis

Body emphasis is append-only. It must not rewrite Higgsfield's captured/reference prompt.

Allowed values:

- `none`
- `bust`
- `bust_hips`

The emphasis text must preserve the same pose, outfit, setting, lighting, and 9:16 composition.

## Video Prompt Path

After a still is accepted, use `reel_motion_prompt.py` to create the deterministic Kling prompt for the scene type.

Supported scene types:

- `mirror_selfie`
- `boat_bikini`
- `back_dress`
- `outdoor_standing`
- `outdoor_kneel`
- `room_selfie`

Every Kling prompt must preserve:

- 9:16
- 5 seconds
- same identity
- same outfit
- same setting
- full head and face visible
- no new text, logos, UI, captions, or overlays

## Photo-To-Reel Utility

For an Edits-style simple reel from one accepted still, use `photo_reel.py`. This path creates a local 9:16 MP4 with a subtle still-image motion treatment and either:

- writes a native trending audio intent sidecar for later in-app/platform attachment, or
- muxes a local audio file into the MP4 when a real local audio file is provided.

Examples:

```bash
python3 photo_reel.py \
  --image <accepted-still.jpg> \
  --out output/photo_reel.mp4 \
  --audio-mode native_trending \
  --motion slow_zoom
```

```bash
python3 photo_reel.py \
  --image <accepted-still.jpg> \
  --out output/photo_reel_with_audio.mp4 \
  --audio-mode local_mux \
  --audio-file 03_audio_library/example.wav \
  --motion slow_zoom
```

This utility does not register assets, schedule posts, publish posts, export drafts, sync metrics, or mutate production inventory.

## Legacy Experiments

The following systems are historical or experimental only:

- `grok-direct`
- `json-structured`
- `visual-schema`
- Qwen/Ollama/Florence extraction
- grid/fanout/cropped-panel workflows
- `_grok.json` prompt files
- `grok_ab_experiment.py`

They may remain in the repo for old tests and research, but they are not the active production guidance.

## Boundaries

This flow stops before Campaign Factory registration. It must not schedule, publish, export drafts, sync metrics, mutate account health, or mutate production inventory.
