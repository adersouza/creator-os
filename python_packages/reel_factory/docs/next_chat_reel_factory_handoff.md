# Reel Factory Handoff

Current default path:

```text
single-person reference image
→ Higgsfield direct reference-image still
→ Stacey Soul ID
→ one 9:16 generated still
→ captured Higgsfield prompt + lineage
→ optional append-only body emphasis
→ human/QC accepted still
→ deterministic Kling motion prompt
→ Kling image-to-video only when explicitly requested
→ stop before Campaign Factory registration
```

## Do This

Use the direct-reference commands:

```bash
python3 generate_assets.py reference-image-dry-run \
  --reference <reference-image> \
  --creator Stacey \
  --stem <clip_stem> \
  --body-emphasis none|bust|bust_hips \
  --wait
```

```bash
python3 generate_assets.py reference-image \
  --reference <reference-image> \
  --creator Stacey \
  --stem <clip_stem> \
  --body-emphasis none|bust|bust_hips \
  --wait
```

Required active defaults:

- Creator: `Stacey`
- Stacey Soul ID: `d63ea9c7-b2c7-439c-bf0c-edfdf9938a36`
- Higgsfield model: `text2image_soul_v2`
- Aspect ratio: `9:16`
- Quality: `2k`
- Reference image passed with `--image`
- Identity passed with `--custom_reference_id`

## Body Emphasis

Only append body emphasis. Do not rewrite Higgsfield's own reference-image prompt.

Allowed values:

- `none`
- `bust`
- `bust_hips`

The emphasis must preserve the same pose, outfit, setting, lighting, and 9:16 composition.

## Video Prompts

For accepted stills, use `reel_motion_prompt.py`.

Supported scene types:

- `mirror_selfie`
- `boat_bikini`
- `back_dress`
- `outdoor_standing`
- `outdoor_kneel`
- `room_selfie`

Motion prompts must keep the same outfit, identity, setting, framing, and full head/face visibility. They must not add text, logos, UI, captions, or overlays.

## Do Not Do This By Default

Do not use these as the normal production path:

- Grok final prompt writing
- Qwen/Ollama/Florence visual-schema extraction
- `visual-schema`
- `grok-direct`
- `json-structured`
- grid generation
- `2x3` or six-panel outputs
- cropped-panel fanout
- `_grok.json` prompt files

Those are legacy/experimental paths only.

## Boundary

This handoff stops at local generated stills and optional local Kling-ready motion prompts unless the user explicitly asks to animate.

Do not register Campaign Factory assets, schedule, publish, export ThreadDash drafts, sync metrics, mutate account health, or mutate production inventory from this flow.
