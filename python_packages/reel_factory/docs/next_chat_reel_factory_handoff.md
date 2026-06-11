# Reel Factory Next Chat Handoff

Use this doc first when continuing Reel Factory prompt/generation work in a new
chat. It captures the current operating rules so the next session does not
rediscover the same Higgsfield, Soul ID, Grok, and Gemini behavior.

## Read This First

For aspect-ratio and grid-size decisions, also read
`docs/aspect_ratio_grid_decision.md`.

Current direction:

- Image quality is the priority. Avoid 8-10 panel grids as the normal path.
- Use Stacey Soul ID on every Stacey image generation:
  `5828d958-91dd-4d6d-8909-934503f47644`.
- Reference images/reels are for Grok/Gemini analysis only. Do not pass
  reference images into Higgsfield image generation.
- Higgsfield prompt enhancement stays off.
- Current Soul image-grid aspect ratio default is `4:3`.
- Prefer `single`, `2x2`, or `3x2`/six-panel prompts. Treat `4x2`, `2x4`,
  `3x3`, and accidental 10-panel outputs as quality-risk experiments.
- If manually testing prompts, keep the exact prompt stable and change only one
  variable at a time.

## Current Production Path

The normal production prompt path is:

```text
reference image/reel
-> Grok writes the final Higgsfield image prompt
-> removal-only cleanup
-> save prompt + lineage
-> Higgsfield Soul ID image grid
-> crop grid panels
-> shared Kling motion prompt fanout, only when requested
```

The production prompt mode is `grok-direct`, reported in lineage as
`reference_factory_sexy_realistic`.

The Grok image prompt instruction is hardcoded in
`generate_prompts.py::build_direct_higgsfield_prompt_instruction`. It uses the
hot Reference Factory style: faithful scene/pose lock, strong body and garment
mechanics, outfit color/material variations, and old structured prompt voice.

Do not re-brief Grok from scratch unless the user explicitly asks to change the
prompt strategy.

## Default Settings To Use

For new quality-first image grid tests, use:

```text
aspect ratio: 4:3
grid layout: 2x2 or 3x2, depending on whether the user wants 4 or 6 panels
prompt enhancement: off
reference image passed to Higgsfield: no
Kling: off unless explicitly requested
Soul ID: Stacey / 5828d958-91dd-4d6d-8909-934503f47644
```

The GUI selector should default away from high-panel grids. If the user asks for
aspect-ratio comparisons, keep the same prompt and Soul ID across every job and
only change `--aspect_ratio`.

Important recent lesson: a 16:9 / 4x2 setup often preserved scene and pose
better, but it also encouraged 8-panel or 10-panel layouts and lower
per-panel detail. The current user preference is `4:3` only unless they
explicitly ask for aspect-ratio experiments.

## What Grok Should Do

Grok should write the final Higgsfield image prompt directly.

The prompt should keep:

- scene-first Reference Factory voice
- exact pose lock
- camera/framing/lighting lock
- S-curve, arched back, hip projection, torso twist, and weight-shift mechanics
- cleavage, pushed-up breasts, hourglass, wide hips, thick thighs, and round ass emphasis when supported by the reference
- garment cling/stretch/fit mechanics
- outfit color/material variants in the same garment style/cut
- amateur iPhone/selfie realism

The prompt should not spend budget on:

- hair, hair color, or hairstyle
- tattoos
- eye color
- freckles
- ethnicity
- perfect face language, unless the user explicitly asks to restore old prompt
  wording for a controlled comparison
- face quality polish
- skin texture/sheen polish

Cleanup is removal-only. It can remove forbidden identity/face-polish terms,
repair punctuation, and convert hair-contact pose phrases to `hand near head`
or `hand behind head`. It must not rewrite, soften, summarize, normalize,
optimize, or remove intense body/garment/pose language.

## Normal Commands

Prompt-only:

```bash
python3 generate_prompts.py \
  --reference-reel /path/to/reference.mp4 \
  --grid-layout 3x2 \
  --image-aspect-ratio 4:3 \
  --out prompts/clip_001_grok.json \
  --dry-run
```

Image-only dry run:

```bash
python3 generate_assets.py dry-run \
  --prompt-json prompts/clip_001_grok.json \
  --stem clip_001 \
  --soul-name Stacey \
  --image-aspect-ratio 4:3
```

Paid image generation, only after prompt review:

```bash
python3 generate_assets.py create \
  --prompt-json prompts/clip_001_grok.json \
  --stem clip_001 \
  --soul-name Stacey \
  --image-aspect-ratio 4:3 \
  --wait
```

Direct Higgsfield command shape, when a manual test is unavoidable:

```bash
higgsfield generate create text2image_soul_v2 \
  --prompt "..." \
  --custom_reference_id 5828d958-91dd-4d6d-8909-934503f47644 \
  --aspect_ratio 4:3 \
  --quality 2k \
  --wait \
  --json
```

Manual tests must still follow the core rules:

- include Stacey `--custom_reference_id`
- do not pass `--image` for the reference
- keep prompt enhancement off
- save the exact command/settings and output path

## Not Normal Paths

These are experiment/debug paths, not production generation:

- `grok_ab_experiment.py`
- `old_new_reference_factory_experiment.py`
- `benchmark_harness.py`
- `generate_prompts.py --prompt-mode compiled`
- manually edited prompt JSONs
- direct Higgsfield calls with hand-written prompts

Use these only when the user explicitly asks for experiments, comparisons, or
manual prompt tests.

## Common Mistakes To Avoid

Do not repeat these:

- Running `text2image_soul_v2` without Stacey `--custom_reference_id`; that
  creates generic women and invalidates the test.
- Passing a reference image into Higgsfield image generation; this can override
  the text prompt and defeats the Soul ID prompt workflow.
- Silently rewriting the user's manual prompt before testing it. If only a grid
  label changes, say exactly what changed.
- Using 8 or 10 panel grid prompts for image-quality tests. They often crush
  per-panel detail.
- Treating a completed job with missing local download as failed before
  inspecting raw lineage; `result_url` may be nested under `raw.image.items`.
- Using image-prompt cleanup on Gemini/Kling motion text. Motion cleanup is a
  separate path.

## Current Gemini/Kling Motion Rules

Gemini analyzes the reference reel/video for motion. Kling gets one shared
motion prompt for cropped panels. Do not generate panel-specific Kling prompts
unless the user explicitly asks for that feature.

Motion cleanup is minimal preservation, not deletion:

- `hands move through hair` -> `hands move near head`
- `hands moving through hair` -> `hands moving near head`
- `hands run through hair` -> `hands move near head`
- `raises both hands to touch her hair` -> `raises both hands near head`
- `raise both hands to touch hair` -> `raise both hands near head`
- `hair blows in wind` -> `subtle wind movement around subject`
- `hair blowing in wind` -> `subtle wind movement around subject`

Preserve camera motion, hip/body movement, hand/arm movement, head/expression
movement, timing, pacing, loop behavior, and pose stability. If Gemini says the
reference is static, preserve static/minimal-hold behavior instead of inventing
generic motion.

## Hard Constraints

- Do not automate Instagram/private APIs/logins/publishing.
- Keep audio simple: use `AudioProviderV1` metadata selection instead of audio
  matching AI, mood classification, recommendation engines, or beat sync.
- Do not pass the reference image into Higgsfield generation.
- Higgsfield prompt enhancement must stay disabled.
- Soul ID owns identity.
- Kling remains off unless the user explicitly asks for video generation.
- Do not change Gemini/Kling behavior while working on image prompt quality.
- Do not touch ContentForge or Campaign Factory for Reel Factory prompt changes
  unless the user explicitly asks.

## Before Paid Generation

For any new prompt strategy or uncertain reference, show:

- raw Grok prompt
- cleaned prompt
- cleanup diff
- lineage settings: prompt mode, aspect ratio, grid layout, prompt enhancement
  flag, and whether the reference image was passed

Then stop for review unless the user already approved paid generation.

## Useful Recent Audit Locations

- TikTok idea import:
  `project_data/idea_references/tiktok_idea_import_1780449644.json`
- Gemini/Kling 10-reel motion audit:
  `project_data/audits/gemini_motion/gemini_kling_motion_audit_20260602_194947.json`
- Valid Stacey aspect-ratio comparison:
  `project_data/generated_assets/aspect_ratio_prompt_test/fire_prompt_stacey_positive_20260603_020156/aspect_ratio_audit.json`
- Stacey aspect-ratio contact sheet:
  `project_data/generated_assets/aspect_ratio_prompt_test/fire_prompt_stacey_positive_20260603_020156/stacey_fire_aspect_ratio_contact_sheet.jpg`
