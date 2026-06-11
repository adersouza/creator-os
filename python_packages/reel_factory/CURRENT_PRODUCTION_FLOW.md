# Current Production Flow

This is the current approved Reel Factory production path. Treat it as the default unless the user explicitly asks for an experiment.

## 1. Reference Intake

Inputs are reference images or reels from local files, commonly under `/Users/aderdesouza/Downloads/examples/` or generated project data.

Reel Factory samples reference frames in `/Users/adercialonedesouza/Projects/reel_factory/generate_prompts.py`.

- `extract_first_visible_frame()` avoids black intro frames.
- `extract_reference_frames()` samples additional frames.
- Reference frames are sent to Grok for prompt creation.
- Reference reels can be sent to Gemini for motion analysis.
- Reference frames are not sent to Higgsfield image generation.

## 2. Grok Image Prompt Architecture

Production image prompt mode is compatibility mode `grok-direct`, reported in lineage as:

```text
reference_factory_sexy_realistic
```

The hardcoded production instruction lives in:

```text
/Users/adercialonedesouza/Projects/reel_factory/generate_prompts.py
build_direct_higgsfield_prompt_instruction()
```

Current behavior:

- Grok receives the reference image/reel frames.
- Grok writes the final Higgsfield image prompt directly.
- The system does not restructure, summarize, or optimize Grok's prompt.
- Cleanup is removal-only for forbidden identity/face-polish terms.
- Hair-contact pose phrases may be replaced only with `hand near head` or `hand behind head`.
- Body/pose/garment intensity is preserved.

Cleanup lives in:

```text
/Users/adercialonedesouza/Projects/reel_factory/generate_prompts.py
clean_direct_higgsfield_prompt()
```

Lineage is written by:

```text
/Users/adercialonedesouza/Projects/reel_factory/generate_prompts.py
write_prompt_lineage()
```

Lineage records:

- `prompt_mode`
- raw Grok prompt
- cleaned prompt
- cleanup diff
- aspect ratio
- grid layout
- prompt enhancement flag
- whether a reference image was passed to Higgsfield
- prompt fields
- reference analysis
- Grok response metadata and usage

## 3. Current Prompt Defaults

Current image-prompt defaults:

- Grok model: `grok-4.3`
- Prompt mode: `grok-direct`, reported as `reference_factory_sexy_realistic`
- Grid layout default: `3x2`
- Image aspect ratio default: `4:3`
- Prompt enhancement: `False`
- Reference image passed to Higgsfield: `False`

The current winning prompt direction is the hot Reference Factory style:

- strong pose lock
- scene/camera/framing/lighting fidelity
- arched back
- S-curve
- hip projection
- torso twist
- waist-to-hip contrast
- cleavage emphasis
- garment cling/stretch
- outfit color/material variation while keeping the same garment style/cut
- amateur iPhone/selfie realism when the reference supports it

Do not re-brief Grok from scratch unless the user asks to change the prompt strategy.

## 4. Higgsfield Soul Image Generation

Higgsfield orchestration lives in:

```text
/Users/adercialonedesouza/Projects/reel_factory/generate_assets.py
```

Current defaults:

- Image model: `text2image_soul_v2`
- Video model: `kling3_0`
- Image aspect ratio: `4:3`
- Image quality: `2k`
- Video aspect ratio: `9:16`
- Video duration: `5`
- Video sound: `off`

Critical invariant:

```text
build_image_cmd(..., reference=None, soul_id=<Soul ID>, ...)
```

Soul ID is passed by `--custom_reference_id` or the resolved image identity flag. The reference image is intentionally not passed as `--image`.

For Stacey, the current documented Soul ID is:

```text
5828d958-91dd-4d6d-8909-934503f47644
```

## 5. Grid CropperV2 Fanout

After a Soul grid returns, Reel Factory crops panels before Kling.

Core file:

```text
/Users/adercialonedesouza/Projects/reel_factory/grid_crop.py
```

GUI fanout API:

```text
/Users/adercialonedesouza/Projects/reel_factory/reel_gui.py
/api/assets/fanout-panels
```

GridCropperV2 behavior:

- Detect visible content box.
- Infer likely grid layout if not forced.
- Detect seams using projection-profile seam detection.
- Snap crop lines to detected seams when confidence is high.
- Apply adaptive inset.
- Emit manifest with `seamDetection`, `cropInset`, `confidence`, `reviewRequired`, and `panelCrops`.

Manifest schema:

```text
reel_factory.image_grid_fanout.v1
```

Always inspect cropped panels before paid Kling generation.

## 6. Kling Motion Path

Kling is off unless explicitly requested.

Motion rules:

- Gemini can analyze reference reel/video motion.
- Gemini/Kling cleanup is not the same as image-prompt cleanup.
- Kling gets one shared motion prompt for cropped panels.
- Do not create panel-specific Kling prompts by default.
- The cropped panel image is the Kling start image.

Relevant files:

- `/Users/adercialonedesouza/Projects/reel_factory/generate_prompts.py`
- `/Users/adercialonedesouza/Projects/reel_factory/generate_assets.py`
- `/Users/adercialonedesouza/Projects/reel_factory/reel_gui.py`

## 7. Render, QC, Export, And Ledger

Reel render and export files:

- `/Users/adercialonedesouza/Projects/reel_factory/reel_pipeline.py`
- `/Users/adercialonedesouza/Projects/reel_factory/qc_check.py`
- `/Users/adercialonedesouza/Projects/reel_factory/export_approved.py`
- `/Users/adercialonedesouza/Projects/reel_factory/posting_ledger.py`

Approved export includes:

- rendered output path
- hook/caption metadata
- campaign metadata
- generated asset lineage sidecar
- audio intent sidecar
- content fingerprint

The local posting ledger is an operator-control layer. It does not post to Instagram, TikTok, Threads, or private platform APIs.

