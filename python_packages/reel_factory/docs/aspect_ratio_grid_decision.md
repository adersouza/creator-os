# Aspect Ratio + Grid Size Decision Guide

Use this guide when choosing Reel Factory Higgsfield Soul image settings.

## Core Principle

Judge the cropped panel, not the full contact sheet.

The Soul grid is only an intermediate artifact. The real output is:

```text
Soul grid -> cropped panel image -> Kling start frame -> final animation
```

So a setting wins only if the individual cropped panels look good.

## Panel Aspect Ratio Formula

```text
panel_aspect_ratio = canvas_aspect_ratio * rows / columns
```

Examples:

| Canvas | Grid | Panel Ratio | Meaning |
| --- | --- | --- | --- |
| `4:3` | 3 columns x 2 rows | `8:9` | slightly vertical, good general six-panel default |
| `3:2` | 3 columns x 2 rows | `1:1` | square panels |
| `16:9` | 3 columns x 2 rows | `32:27` | slightly wide panels |
| `3:4` | 3 columns x 2 rows | `1:2` | very vertical panels, more crop pressure |
| `4:3` | 2 columns x 2 rows | `4:3` | wide-ish panels |
| `3:4` | 2 columns x 2 rows | `3:4` | vertical panels |
| `1:1` | 2 columns x 2 rows | `1:1` | square panels |

Important wording rule:

- Say `three columns and two rows` for six-panel horizontal contact sheets.
- Avoid ambiguous shorthand like `2x3` unless the UI stores columns/rows
  separately.

## Current Best Hypotheses

Use these as working hypotheses, not permanent truth:

- `single`: best raw image quality, no outfit comparison.
- `2x2`: likely best balance of panel detail and variation.
- `2-panel` and `3-panel` tests may be worth adding for quality-first prompt
  research because every added panel reduces the model budget per image.
- `3 columns x 2 rows`: best six-variant workflow, but lower panel detail than
  `2x2`.
- `4x2`, `2x4`, `3x3`, and accidental 10-panel outputs: quality risk. Use only
  for experiments.
- `4:3` canvas with 3 columns x 2 rows gives useful slightly vertical panels
  without pushing Higgsfield into huge grids.
- `16:9` often preserves room/scene better but may encourage 8-10 panel outputs.
- Tall canvases can help vertical panel shape but may reduce room context and
  compress the scene.

Important current direction:

- Lower the grid size and variation count when image quality is weak.
- Do not treat six variants as mandatory during prompt-quality research.
- First find the prompt/aspect/layout combination that produces beautiful
  Stacey panels; increase variation count only after quality is proven.

## Reference-Type Aspect Hypotheses

Use our own generated examples as the source of truth. External aspect-ratio
advice can suggest tests, but it should not override what wins in this project.

Working hypotheses to test against saved Reel Factory outputs:

| Reference Type | First Candidate | Why |
| --- | --- | --- |
| Mirror selfie | `4:3` with `2x2` or `3x2` | tighter subject framing and pose fidelity |
| Bathroom selfie | `4:3` with `2x2` or `3x2` | subject and mirror mechanics matter more than wide scene |
| Bedroom selfie | `4:3` or `3:4` with `2x2` | vertical phone-shot feel, higher panel detail |
| Gym selfie | `4:3` with `2x2` | pose and body mechanics matter most |
| Chair/seated indoor | `4:3` with `2x2` | pose fidelity and subject size |
| Outdoor beach/boat | `16:9` with `2x2` or low variation count | environment and scene context matter |
| Balcony/travel/luxury exterior | `16:9` with low variation count | background and lifestyle context carry the image |
| Luxury interior/environment-heavy | `16:9` or `4:3`, tested case-by-case | scene fidelity vs panel compliance tradeoff |

If the model starts returning 8-10 panels, reduce grid count before changing the
prompt.

## Evaluation Rubric

Score each cropped panel from 1-10:

| Metric | What To Look For |
| --- | --- |
| Face realism | Natural Stacey look, not plastic or generic AI face |
| Soul ID consistency | Looks like the trained Soul ID across panels |
| Panel detail | Clean face/body/garment after cropping |
| Pose fidelity | Keeps the intended pose mechanics |
| Scene fidelity | Room/context survives, not plain catalog backdrop |
| Outfit variation | Colors/materials differ clearly at thumbnail size |
| Body/garment mechanics | Cleavage, curves, fabric cling, pose geometry survive |
| Crop usability | Panel can be used as a Kling start image |
| Grid compliance | Requested panel count/layout is followed |

Recommended weighted score:

```text
score =
  2.0 * panel_detail
  + 2.0 * face_realism
  + 1.5 * soul_id_consistency
  + 1.5 * pose_fidelity
  + 1.0 * scene_fidelity
  + 1.0 * outfit_variation
  + 1.0 * body_garment_mechanics
  + 1.0 * crop_usability
  + 0.5 * grid_compliance
```

Grid compliance matters, but it should not outrank image quality.

## Clean Test Matrix

Run this only when the user wants a real comparison.

Use one exact prompt, one Soul ID, one model, prompt enhancement off, no
reference image passed to Higgsfield.

Minimum matrix:

| Test | Canvas | Grid |
| --- | --- | --- |
| A | `4:3` | single |
| B | `4:3` | 2 columns x 2 rows |
| C | `3:4` | 2 columns x 2 rows |
| D | `16:9` | 2 columns x 2 rows |
| E | `4:3` | 3 columns x 2 rows |
| F | `16:9` | 3 columns x 2 rows |

For each result:

1. Save exact prompt and command.
2. Download full grid.
3. Crop panels.
4. Make a panel contact sheet grouped by setting.
5. Score the cropped panels using the rubric.
6. Pick the setting with the best cropped-panel score, not the prettiest full
   grid.

## Decision Rule

Default recommendation should be data-driven:

- If `single` or `2x2` is much sharper, lower variation count until the prompt
  quality is solved.
- If `2x2` panels look much sharper, use `2x2` for image quality tests.
- If six variations are needed and `3 columns x 2 rows` remains usable, use
  six panels.
- If `16:9` keeps scene but causes 8-10 panels, do not use it as default.
- If the best full grid creates bad crops, reject it.

Current user preference:

```text
Use 4:3 from now on unless explicitly testing aspect ratios.
Avoid 8-10 panel grids.
```

## Cropping Rule Before Kling

Always crop and inspect panel thumbnails before paid Kling animation.

Do not assume the generated grid matches the prompt. Higgsfield can return:

- 6 panels from a six-panel prompt
- 8 panels from a six-panel prompt
- 9 panels from a square prompt
- 10 panels from high-panel-count prompts

Use the actual visible grid, not only the requested prompt layout.

Safe workflow:

1. Generate Soul grid.
2. Inspect the full image and determine visible columns/rows.
3. Select the matching grid layout in the GUI.
4. Run `Crop existing grid` as dry-run.
5. Inspect cropped panel thumbnails.
6. Only then animate selected panels.

Recent verified examples:

- Beige bedroom 2x3 output cropped cleanly as `3 columns x 2 rows`.
- Black bikini bedroom output visually returned 8 panels and cropped cleanly as
  `4 columns x 2 rows`, even though the prompt requested six panels.

Automatic detection is useful, but seamless low-light grids can be ambiguous.
When confidence is `review`, operator inspection is required.
