# Higgsfield CLI

Use this skill when the user asks to generate image or video assets, analyze a finished video for virality, train or reuse a Soul ID, inspect Higgsfield models, or run Higgsfield Marketing Studio workflows from this project.

## Tooling

- Prefer the installed CLI: `higgsfield`.
- `higgs` is also available as an alias.
- Check installation with `higgsfield version`.
- Check authentication with `higgsfield auth token` or `higgsfield auth login` when needed.
- Use `--json` for machine-readable output when integrating with scripts.

## Core Workflow

1. Confirm the requested output type: image, video, video analysis, Soul ID, or Marketing Studio asset.
2. Inspect the model schema before using an unfamiliar model:
   ```bash
   higgsfield model get <model> --json
   ```
3. Estimate cost when the user is exploring options:
   ```bash
   higgsfield generate cost <model> --prompt "..." --json
   ```
4. Generate with `--wait` only when the user wants the result in the current turn:
   ```bash
   higgsfield generate create <model> --prompt "..." --wait --json
   ```
5. Store generated media URLs or job IDs in the response. Do not publish generated assets automatically; route them through the app's media library, posting preflight, schedule, or approval workflow first.

## Useful Commands

Image:
```bash
higgsfield generate create nano_banana_2 \
  --prompt "modern product ad, clean lighting" \
  --aspect_ratio 9:16 \
  --resolution 2k \
  --wait
```

Video:
```bash
higgsfield generate create kling3_0 \
  --prompt "slow camera push through a polished studio set" \
  --start-image ./first.png \
  --duration 5 \
  --mode pro \
  --sound off \
  --wait
```

Virality analysis:
```bash
higgsfield generate create brain_activity --video ./finished-video.mp4 --wait --json
```

Upload local media:
```bash
higgsfield upload ./asset.png --json
```

Soul ID:
```bash
higgsfield soul-id create --name <name> --soul-2 \
  --image ./one.jpg --image ./two.jpg --image ./three.jpg
higgsfield soul-id wait <soul_id>
```

## App Integration Rules

- Treat Higgsfield as an async creative asset provider, not as a posting system.
- Never bypass this app's Instagram/Threads publish preflight.
- For Reels, generate or select media first, then validate dimensions, duration, caption, collaborators, paid partnership fields, token health, and media URL accessibility through the app.
- For analysis results, label them as Higgsfield/Virality Predictor output and avoid presenting scores as Meta-native metrics.
- For user-owned likenesses or brand assets, ask for explicit source images/files before generating.
