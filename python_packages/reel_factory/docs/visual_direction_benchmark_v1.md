# Visual Direction Benchmark V1

Goal: compare neutral reconstruction prompts against Grok enhanced visual
direction prompts on real reference reels, using the same shared Kling motion
prompt for both conditions.

This benchmark does not change architecture. Soul ID owns identity. Reference
images are used for prompt writing only and are not passed into Higgsfield image
generation. Saved prompt files still use the runtime contract:

```json
{
  "higgsfieldGridPrompt": "...",
  "klingMotionPrompt": "..."
}
```

## Conditions

Condition A: neutral baseline

- Uses the same reference reel.
- Uses a reconstruction-first prompt.
- Describes outfit, fit, pose, camera, framing, lighting, and environment.
- Does not add sexier visual direction beyond what is directly useful for reconstruction.

Condition B: Grok enhanced visual direction

- Uses the same reference reel.
- Uses Grok-written final image prompt text.
- May push stronger curves, deeper cleavage, fuller breasts, rounder ass, wider hips, tighter waist, tighter fabric cling, confident pose, stronger framing, and better lighting.
- Still contains no identity traits and no negative prompt field.

Condition C: shared motion

- Both A and B must use the exact same `klingMotionPrompt`.
- The same motion prompt is applied to every cropped panel from both grids.

## Reel Set

Use 10 real reels for the first benchmark pass.

Choose references that cover:

- 2 mirror/selfie-style reels
- 2 simple indoor front-camera reels
- 2 dress/bodycon/fashion reels
- 2 movement-heavy reels
- 2 wildcards from recent high-performing references

For each reel, assign a stable ID:

```text
reel_001
reel_002
...
reel_010
```

## Prompt Files

Each reel needs two prompt JSON files:

```text
prompts/benchmarks/reel_001_neutral.json
prompts/benchmarks/reel_001_enhanced.json
```

Both files must share the exact same `klingMotionPrompt`.

Example neutral:

```json
{
  "higgsfieldGridPrompt": "2x3 grid with black fitted mini dress, centered vertical framing, soft indoor lighting, confident standing pose, simple minimal room, polished photorealistic style",
  "klingMotionPrompt": "slow push in, subtle hip shift, small hand movement near waist, steady handheld pacing, smooth loop feel"
}
```

Example enhanced:

```json
{
  "higgsfieldGridPrompt": "2x3 grid with black fitted mini dress, deeper cleavage, fuller breasts, rounder ass, wider hips, tighter waist, tight fabric cling, centered vertical framing, soft indoor lighting, confident standing pose, simple minimal room, polished photorealistic style",
  "klingMotionPrompt": "slow push in, subtle hip shift, small hand movement near waist, steady handheld pacing, smooth loop feel"
}
```

## Reels JSON

Create:

```text
project_data/benchmarks/visual_direction_v1/reels.json
```

Format:

```json
[
  {
    "reel_id": "reel_001",
    "reference_path": "/absolute/path/to/reference_001.mp4",
    "neutral_prompt_json": "/Users/adercialonedesouza/Projects/reel_factory/prompts/benchmarks/reel_001_neutral.json",
    "enhanced_prompt_json": "/Users/adercialonedesouza/Projects/reel_factory/prompts/benchmarks/reel_001_enhanced.json"
  }
]
```

## Initialize Plan

Run:

```bash
python3 benchmark_harness.py init \
  --root /Users/adercialonedesouza/Projects/reel_factory \
  --reels-json /Users/adercialonedesouza/Projects/reel_factory/project_data/benchmarks/visual_direction_v1/reels.json \
  --benchmark-id visual_direction_v1 \
  --creator Stacey \
  --soul-name Stacey \
  --max-panels 6
```

Output:

```text
project_data/benchmarks/visual_direction_v1/benchmark_plan.json
```

The plan validates:

- both prompt files use the v1 final prompt contract
- neutral/enhanced use identical `klingMotionPrompt`
- both conditions have six planned panel animation stems
- prompt contracts contain no legacy prompt fields
- Higgsfield image dry-runs do not pass the reference image

## Generation Run

For each reel:

1. Generate neutral Higgsfield 2x3 grid.
2. Generate enhanced Higgsfield 2x3 grid.
3. Crop neutral grid into six panels.
4. Crop enhanced grid into six panels.
5. Animate neutral panels using the shared `klingMotionPrompt`.
6. Animate enhanced panels using the same shared `klingMotionPrompt`.
7. Compare outputs side by side.
8. Record winner and reason.

For first pass, animate all panels when budget allows. If budget is tight, crop all panels and animate the best 1-2 panels from each condition, but record which panels were animated.

## Review Criteria

Score each condition from 1-5:

- outfit reconstruction
- garment fit and placement
- curve/body emphasis
- pose strength
- framing/camera
- lighting/environment
- motion fit
- overall appeal
- generation cleanliness

Winner values:

```text
neutral
enhanced
tie
reject_both
```

Reason should be concrete:

```text
enhanced wins: better dress fit, stronger curves, cleaner centered framing, panel 5 had best motion
```

## Record Result

Run:

```bash
python3 benchmark_harness.py record \
  --root /Users/adercialonedesouza/Projects/reel_factory \
  --benchmark-id visual_direction_v1 \
  --reel-id reel_001 \
  --winner enhanced \
  --reason "better dress fit, stronger curves, cleaner centered framing" \
  --selected-panels-json '{"neutral":2,"enhanced":5}' \
  --scores-json '{"neutral":3,"enhanced":5}'
```

Output:

```text
project_data/benchmarks/visual_direction_v1/results.jsonl
```

## Decision Rule

After the benchmark set:

- If enhanced wins clearly: make enhanced Grok direction the default.
- If neutral wins 5 or more: keep neutral as default and inspect enhancement overreach.
- If ties/rejects dominate: fix prompt compilation and visual QA before running live volume.

## What Not To Change During Benchmark

- Do not change final prompt contract.
- Do not add `negative_prompt`.
- Do not add identity fields.
- Do not add panel-specific Kling prompts.
- Do not change Soul ID identity handling.
- Do not add new intelligence modules.
- Do not pass the reference image into Higgsfield image generation.
