# reel_factory

Local silent-reel rendering pipeline for Mac Studio / Apple Silicon.

Drop a vertical source video plus matching caption hooks into the project, then
render silent captioned MP4 variations for posting workflows where audio is
attached later in-app or by a downstream muxer.

## Layout

```text
project_root/
├── reel_pipeline.py
├── reel_gui.py
├── graph_builder.py            # deterministic FFmpeg filter/encode command builder
├── render_plan.py              # typed render plan passed into graph_builder
├── recipe_loader.py            # strict recipe JSON loader
├── requirements.txt
├── setup.sh
├── recipes/default.json        # active recipe matrix
├── 00_source_videos/         # source .mp4 files, e.g. clip_001.mp4
├── 01_captions/              # matching .txt or .json sidecars
├── 02_processed/             # rendered outputs per source clip
├── fonts/                    # bundled caption fonts
├── manifest.sqlite           # SQLite cache/audit trail, created on first render
└── manifest.json             # compatibility export for reports/tools
```

## Setup

```bash
chmod +x setup.sh
./setup.sh
```

`setup.sh` checks ffmpeg, installs Python packages from `requirements.txt`, and
prepares the project folders. The renderer expects an ffmpeg build with
`h264_videotoolbox`; Homebrew ffmpeg works for the current PNG-overlay caption
path.

## GUI

```bash
python3 reel_gui.py
```

The local GUI opens at `http://localhost:8765`. It supports uploading clips,
editing hooks, spinning hook variants, choosing exact captions versus slang
variants, running the pipeline, and previewing outputs. The hook editor warns
when blocks are near-duplicates, supports up/down reordering, and can save or
insert reusable hooks from the local hook library.

Timed hooks are edited as JSON blocks, for example:

```json
{
  "segments": [
    {"text": "I don't do situationships", "end": 3.0},
    {"text": "...define situationship", "start": 3.0}
  ]
}
```

## CLI

```bash
python3 reel_pipeline.py --root . --dry-run
python3 reel_pipeline.py --root .
```

Useful options:

```bash
python3 reel_pipeline.py --root . --max-hooks 10 --hook-select random --seed 99
python3 reel_pipeline.py --root . --workers 4
python3 reel_pipeline.py --root . --recipes v01_original v05_hflip
python3 reel_pipeline.py --root . --color dark
python3 reel_pipeline.py --root . --text-variation auto
python3 reel_pipeline.py --root . --text-variation auto --variation-pack default
python3 reel_pipeline.py --root . --pack-render
python3 reel_pipeline.py --root . --mezzanine
python3 reel_pipeline.py --root . --placement-debug
python3 reel_pipeline.py --root . --placement-signals pose
python3 reel_pipeline.py --root . --placement-mode segment
python3 reel_pipeline.py --root . --caption-renderer pillow
python3 caption_render.py --compare-renderers --text "caption test"
python3 reel_pipeline.py --root . --output-profile mac_h264_videotoolbox
python3 reel_pipeline.py --root . --mux-audio --audio-tag trending
python3 reel_pipeline.py --root . --qc
python3 qc_check.py --root . --upload-ready
python3 metrics_import.py --root . --csv metrics.csv
python3 hook_ai.py --backend ollama --model llama3.2:3b --base "base hook" --n 20 --strict
python3 hook_ai.py --caption-library
python3 hook_ai.py --rank-existing --clip clip_010 --top 20
python3 asset_prompt_contract.py --print-system-prompt
python3 slideshow_factory.py --media-dir ~/Downloads/slideshow_sources --out-dir 02_processed/slideshow_pack --title "Claude = 550 videos/day" --count 12
python3 hook_library.py --root . --reindex --embedding-model all-MiniLM-L6-v2
python3 thumbnail_gen.py --root . --clip clip_001
python3 audio_mux.py --root . --clip clip_001 --audio-tag trending
python3 qc_check.py --root . --compare-golden --golden-dir golden_outputs
python3 reel_pipeline.py --root . --enqueue-only
python3 worker.py --root . --workers 3
python3 queue_admin.py --root . --status
REDIS_URL=redis://127.0.0.1:6379/0 python3 worker.py --root . --queue-backend redis
```

## Caption Inputs

Plain text sidecar:

```text
01_captions/clip_001.txt
POV you wear oversized clothes
and he still notices everything
```

JSON sidecar:

```json
{
  "hooks": [
    "POV you wear oversized clothes",
    "the way he locks in even when i'm in three hoodies"
  ],
  "recipes": ["v01_original", "v05_hflip"],
  "caption_color": "auto"
}
```

`hooks` may contain strings or timed hook objects with `segments`.

## AI Asset Prompts

For a concise handoff to the next chat, start with
[`docs/next_chat_reel_factory_handoff.md`](docs/next_chat_reel_factory_handoff.md).

The production image prompt path is Grok-direct. Reel Factory sends the
reference image/reel to Grok so Grok can write the final Higgsfield Soul image
prompt in the old Reference Factory style: scene first, exact pose lock, strong
body and garment mechanics, outfit variations, and same room/camera/framing/
lighting lock.

The saved prompt contract still has two runtime strings:

```json
{
  "higgsfieldGridPrompt": "One Grok-written prompt for the Higgsfield Soul ID grid...",
  "klingMotionPrompt": "One shared Kling motion prompt for every cropped panel...",
  "notes": "Short operator note."
}
```

Print the fallback Prompt Builder contract with:

```bash
python3 asset_prompt_contract.py --print-system-prompt
```

The required runtime contract is:

- one Higgsfield/Soul ID grid prompt for a native grid or standalone image
- one shared Kling motion prompt derived from the reference motion timeline
- no `negative_prompt` field
- no identity description; Soul ID handles identity externally
- no panel-specific Kling prompt generation in this version

Grok should write the final `higgsfieldGridPrompt` directly. The system then
performs removal-only cleanup for forbidden identity/face-polish terms and
records lineage:

- raw Grok prompt
- cleaned prompt
- cleanup diff
- prompt mode
- aspect ratio
- grid layout
- prompt enhancement flag
- whether the reference image was passed to Higgsfield

Reference images are only for Grok prompt creation. Soul ID owns identity, and
Higgsfield image generation does not receive the reference image.

Generate prompt JSON from a reference reel/image with:

```bash
export XAI_API_KEY="your_xai_key"
python3 generate_prompts.py \
  --reference-reel /path/to/reference.mp4 \
  --grid-layout 3x2 \
  --image-aspect-ratio 4:3 \
  --out prompts/clip_001_grok.json \
  --dry-run
```

For quality-first tests, prefer `single`, `2x2`, or `3x2`. Avoid using `4x2`,
`2x4`, or `3x3` as the normal path: high-panel-count prompts often lower
per-panel detail and can cause Higgsfield to return 8-10 small panels.

You can also store the key locally in ignored `project_data/secrets.toml` as
`xai_api_key = "..."`. The prompt script samples reference frames, calls Grok in
`grok-direct` mode, writes the prompt contract, and saves
`prompts/clip_001_grok.json.grok_lineage.json`.

Create a blank prompt file manually when needed:

```bash
python3 asset_prompt_contract.py --new prompts/clip_001_grok.json
```

Validate a returned JSON string before storing or using it:

```bash
python3 asset_prompt_contract.py --validate-response '{"higgsfieldGridPrompt":"...","klingMotionPrompt":"...","notes":"..."}'
```

Use the operator-controlled Higgsfield wrapper when you want the local project
to create jobs and preserve real upload/job IDs:

```bash
python3 generate_assets.py dry-run --prompt-json prompts/clip_001_grok.json --stem clip_001 --soul-name Stacey --image-aspect-ratio 4:3
python3 generate_assets.py create --prompt-json prompts/clip_001_grok.json --stem clip_001 --soul-name Stacey --image-aspect-ratio 4:3 --wait
python3 generate_assets.py status --lineage 00_source_videos/clip_001.generated_asset_lineage.json
python3 generate_assets.py wait --lineage 00_source_videos/clip_001.generated_asset_lineage.json
```

The wrapper uses `higgsfield generate create text2image_soul_v2`,
`higgsfield generate create kling3_0`, `higgsfield generate wait`, and
`higgsfield generate get`. It writes one source-level lineage file beside the
eventual source video: `00_source_videos/clip_001.generated_asset_lineage.json`.
Soul V2 renders must include `--soul-id <uuid>` or `--soul-name <name>` so
Higgsfield receives `--custom_reference_id` for the trained creator identity.
Reference frames are for Grok prompt creation only; Soul image generation does
not pass the reference image to Higgsfield.

When rendering a generated Kling clip, pass that prompt JSON to preserve
prompt lineage. If source-level lineage already exists beside the source clip,
per-output sidecars reference it instead of duplicating prompts:

```bash
python3 reel_pipeline.py --root . --asset-prompt-json prompts/clip_001_grok.json
python3 reel_pipeline.py --root . --asset-prompt-json prompts/clip_001_grok.json --ai-qc
```

Recommended file convention:

```text
prompts/clip_001_grok.json
00_source_videos/clip_001.mp4
01_captions/clip_001.json
```

## Account Posting Ledger

The Account Posting Ledger is a Campaign Factory-compatible local pilot ledger
between approved Reel Factory outputs and operator scheduling. It proves the
slot, duplicate, review, audio-gate, and schedule-export workflow before that
control state is promoted into the canonical Campaign Factory repo. It does not
post to Instagram, TikTok, Threads, or any private platform API.

Important ownership rule: this ledger is local tooling only. It is not the
canonical account schedule, posted-status store, metrics store, or campaign
control graph. Campaign Factory remains the control brain through its
`distribution_plans`, `asset_account_assignments`, `threadsdash_exports`,
`performance_snapshots`, and content graph tables. If `posting_ledger.py` is
used during a pilot, its slot/account state must be mirrored or migrated into
Campaign Factory before the campaign is treated as production-ready.

Create the 5-account / 7-day Stacey pilot plan:

```bash
python3 posting_ledger.py create-plan \
  --root . \
  --creator Stacey \
  --campaign-id stacey_pilot \
  --accounts stacey_01,stacey_02,stacey_03,stacey_04,stacey_05 \
  --start-date 2026-06-03 \
  --days 7
```

Assign approved Reel Factory outputs into planned slots:

```bash
python3 posting_ledger.py assign-approved-reels \
  --root . \
  --campaign-id stacey_pilot \
  --approved-export 04_exports/approved_ig_stacey_2026-06-03.json
```

Inspect the operator queue, conflicts, and schedule package:

```bash
python3 posting_ledger.py review-queue --root . --campaign-id stacey_pilot
python3 posting_ledger.py print-conflicts --root . --campaign-id stacey_pilot
python3 posting_ledger.py export-schedule-package --root . --campaign-id stacey_pilot --date-from 2026-06-03 --date-to 2026-06-10
```

Each ledger slot stores a `content_fingerprint`, computed from rendered video
bytes, so copied or renamed reels still register as duplicate content. Missing
native audio intent is allowed during review, but schedule export requires
resolved audio metadata or an explicit manual-audio-needed marker.

## Daily Cockpit Workflow

The GUI Generate panel is the normal operator path for new AI clips:

```text
campaign → reference reel/image → Grok final image prompt + Gemini motion → Soul ID grid → crop panels → shared Kling motion fanout → compare/select → source clip → render pack
```

Pick a campaign, select the reference clip, then use Generate. Paid Higgsfield
steps stay behind explicit buttons: `create Stacey Soul image` and
`create Kling video`. Stacey is the default creator and maps to Soul ID
`5828d958-91dd-4d6d-8909-934503f47644`.

To recreate from a social URL, paste the Reels/TikTok URL into `import
reference reel` in the GUI and click `Import + recreate`. The app downloads the
URL with `yt-dlp`, saves it as the next `00_source_videos/clip_NNN.mp4`, writes
`00_source_videos/clip_NNN.reel_url_import.json`, creates a caption stub,
attaches it to the selected campaign, and builds the Grok prompt preview when
the prompt option is checked. Paid Soul/Kling generation still requires the
explicit cockpit buttons.

The reference sampler extracts frames from the reference reel for Grok prompt
creation. The saved first visible frame
(`prompts/_references/<prompt_stem>/reference_00_first_visible.jpg`) is not
passed to Higgsfield image generation. If the reel starts on black or a
transition, the extractor scans forward to the first non-blank frame. Soul ID is
the identity lock.

After the Soul image returns, the normal path crops the native grid into
individual panel start images. Each cropped panel is sent to Kling as a
separate run using the same shared `klingMotionPrompt`. Panel-specific Kling
prompts are not generated unless that feature is explicitly added later.

After Kling returns, the GUI stores `videoResultUrl`, so `download video` uses
the saved URL automatically. The manual URL prompt is only a fallback when no
stored result URL exists.

Old compiler-style fields such as `soul_id_2x3_prompt`,
`kling_video_prompt`, `kling_negative_prompt`, `structured_breakdown`, and
`confidence_score` are rejected by the runtime prompt contract. The saved/usable
contract stays focused on the two real artifacts: one image-grid prompt and one
motion prompt.

The local Higgsfield CLI is available as `higgsfield`/`higgs`/`hf`. The current
workflow remains manual, but the relevant CLI shape is:

```bash
python3 generate_assets.py capabilities --root .
python3 generate_prompts.py --reference-reel reference.mp4 --reference-frame-mode first-visible --grid-layout 3x2 --out prompts/clip_001_grok.json --dry-run
python3 generate_assets.py dry-run --prompt-json prompts/clip_001_grok.json --stem clip_001 --creator Stacey --image-aspect-ratio 4:3
higgsfield model list --image --json
higgsfield model list --video --json
higgsfield generate create text2image_soul_v2 --prompt "$(jq -r .higgsfieldGridPrompt prompts/clip_001_grok.json)" --wait
higgsfield generate create kling3_0 --prompt "$(jq -r .klingMotionPrompt prompts/clip_001_grok.json)" --start-image <cropped_panel_upload_or_path> --wait
```

Use `higgsfield generate create --help` for the current accepted media flags.

Heuristic AI visual QA can also run standalone after rendering:

```bash
python3 ai_visual_qc.py --root . --clip clip_001
```

It writes `02_processed/clip_001/_ai_qc.json` with non-blocking warnings for
blur/low detail, abrupt frame jumps, likely text/watermarks, and face-count
inconsistency when local dependencies are available. The GUI surfaces those
warnings as tags and can overlay Reels/TikTok safe-zone bands on previews and
output tiles without baking them into the video.

Run warn-only platform readiness aggregation with:

```bash
python3 readiness_check.py --root . --clip clip_001 --platform instagram_reels
python3 readiness_check.py --root . --clip clip_001 --platform tiktok
python3 reel_pipeline.py --root . --ai-qc --readiness
```

Readiness writes `02_processed/clip_001/_readiness.json` and combines technical
metadata, AI visual QA, safe-zone scoring, audio intent, review state, target
ratio, and generated lineage into `ready`, `warn`, or `not_ready` records.
This pass is intentionally warn-only: approval and export still succeed, but
the GUI and export manifest show missing audio intent, missing lineage,
non-preferred ratios, low resolution, text/watermark risk, and safe-zone risks.

Audio intent is stored beside each output as
`<output>.audio_intent.json`. The GUI can set one of:
`native_trending_audio`, `original_voiceover`, `licensed_music`,
`silent_by_design`, or `platform_auto_music`.

AudioProviderV1 is the simple selection layer for posting audio metadata. Use
`AUTO_TRENDING` for the default 60% TikTok CML primary pool, 30% local winners,
and 10% watch-list mix; use `SAFE_LIBRARY` for curated winners only; use
`CUSTOM` for manual overrides. See
[`docs/audio_provider_v1.md`](docs/audio_provider_v1.md). This is metadata only:
it does not automate TikTok login/publishing and does not replace the visual
pipeline as the priority.

## Recipe Matrix

The active recipe set is intentionally focused:

| Name | Effect |
|---|---|
| `v01_original` | captioned render with a tiny tail trim |
| `v05_hflip` | mirrored render with a small head trim |
| `v06_zoom` | subtle reframing with head/tail trim |
| `v07_tilt` | subtle tilted reframe |
| `v08_colorgrade_bright` | bright/poppy color preset |
| `v09_caption_bg` | centered bubble-style caption background |
| `v10_colorgrade_warm` | warm color preset |
| `v11_colorgrade_cool` | cool color preset |

Every recipe also uses light camera-style variation: small crop, rotation,
color balance, sharpening, and grain. Parameters are deterministic per source
and recipe, so reruns stay stable.

Recipes live in `recipes/default.json` and are validated before rendering. A
typo in a recipe field fails fast instead of building a broken FFmpeg command.
The pipeline resolves each job through a `RenderPlan`, then `graph_builder.py`
builds one labeled filter graph plus encode arguments from that plan.

## Text Variation

By default captions render exactly as written:

```bash
python3 reel_pipeline.py --root . --text-variation off
```

To apply deterministic slang/case changes per recipe:

```bash
python3 reel_pipeline.py --root . --text-variation auto
```

Examples include `you → u`, `your → ur`, `because → bc/cuz`, and occasional
lowercasing. The same source, caption, recipe, and variation pack always
produce the same text. Variation packs are versioned in `variation_engine.py`
so future packs can be added without silently changing old job keys.

## Outputs

Outputs are silent (`-an`) and written under `02_processed/<clip>/`.

Each output is keyed by source hash, caption hash, and recipe parameters.
`manifest.sqlite` is the source of truth for completed jobs, render history,
timing, failures, and render attempts. SQLite runs with foreign keys enabled
and WAL mode, with a `schema_migrations` table and `PRAGMA user_version` for
explicit upgrades. `manifest.json` is exported after each run so existing
reporting tools can keep reading the old format.

FFmpeg writes to `02_processed/<clip>/.tmp/<job>/` first. The final MP4 is only
promoted into the clip folder after the encoder exits cleanly and the temp file
exists with nonzero size, so interrupted renders do not look complete. The
pipeline records stale temp outputs on the next startup as interrupted attempts.
It skips completed jobs when the output file still exists, and it removes
duplicate jobs before launch if the same hook appears more than once in a
sidecar.

Use `--mezzanine` to write optional ProRes LT `.mov` files beside the normal
social MP4s. The GUI exposes the same option as the `ProRes` checkbox. These
files are intended for review/editing, not direct social upload.

Encoder profiles are selected with `--output-profile`. The default is
`mac_h264_videotoolbox`; `cpu_h264_x264` is available for portability, and
`linux_nvenc` / `linux_vaapi` are documented profile targets for later local
Linux machines. The VAAPI profile is declared but not runnable until the graph
adds the needed hardware upload stage.

Caption rendering defaults to Pillow/Pilmoji. `--caption-renderer pango` uses
Pango/Cairo when those native dependencies are installed and falls back to
Pillow when they are not. Use `caption_render.py --compare-renderers` to
generate side-by-side renderer PNGs.

Caption placement defaults to one stable source-level decision per clip.
`--placement-mode segment` opt-in scores timed caption segments independently
and smooths adjacent choices so text only moves when the segment window clearly
has a better safe zone.

Outputs have a lightweight review state: `draft`, `approved`, or `rejected`.
The GUI can filter outputs by review state and writes that state back to
`manifest.sqlite` and the JSON export.

Manual upload metrics can be imported from a CSV keyed by `filename`. Supported
columns are `platform`, `account`, `uploaded_at`, `views`, `likes`, `comments`,
`shares`, `saves`, `manual_score`, and `notes`. Unknown filenames are ignored
and reported by the importer.

After rendering, the project writes an index CSV and contact sheet for each clip.

## Slideshow / Carousel Factory

`slideshow_factory.py` creates the low-lift IG carousel/reel format where a
folder of stills or source videos becomes a stack of vertical slides, a grid
preview, and an optional stitched silent MP4:

```bash
python3 slideshow_factory.py \
  --media-dir ~/Downloads/slideshow_sources \
  --out-dir 02_processed/slideshow_pack \
  --title "Claude = 550 videos/day" \
  --count 12 \
  --reference-pattern-id caption_led_visual
```

Outputs:

```text
02_processed/slideshow_pack/
├── slides/slide_001.jpg
├── slides/slide_002.jpg
├── grid_preview.jpg
├── slideshow_reel.mp4
└── slideshow_manifest.json
```

The generator uses bundled Instagram-style fonts, small top hooks, optional
view-count styling, and carousel cues. Video inputs are converted to one still
frame first. Source media is read-only; all derived assets stay in the output
folder. The manifest records `format`, source hashes, caption hashes,
reference pattern id, and optional generation id. Use `--no-video` when you
only need carousel slides and a grid preview.

This format is intended for volume-friendly slideshow posts, style testing, and
future Campaign Factory batch ingestion. It is separate from `reel_pipeline.py`
so the motion-reel renderer stays deterministic and focused.
Use `--qc` to run a technical output check. `qc_check.py --compare-golden` adds
SSIM/PSNR encode regression checks against matching files in a golden directory.
MP4 outputs are phone-finalized by default: FFmpeg normalizes faststart, color,
creation time, and handler metadata, then macOS `avconvert` passthrough removes
remaining FFmpeg container signatures when available. Use
`--no-phone-finalize` only for debugging raw encoder output.

Thumbnails are manual-first: run `thumbnail_gen.py` or click `make thumbnails`
in the GUI. Generated PNGs sit beside their MP4s and appear on output cards.

Audio muxing is derivative-only. Put local audio files in `03_audio_library/`
and optional metadata in matching `.json` files, for example
`{"tags":["trending"]}`. `audio_mux.py` and `--mux-audio` write
`*_audio_<audio_id>.mp4` files and never replace silent originals. QC defaults
to silent output checks; use `qc_check.py --audio-mode auto` when checking both
silent and muxed derivatives.

Optional AI hook rewriting uses local Ollama. If Ollama is unavailable, the CLI
and GUI return a clear error without affecting the normal hook editor. Strict
mode rejects malformed, duplicate, too-short/long, missing-term, and low
semantic-similarity variants. The hook library can use optional
`sentence-transformers` embeddings and falls back to deterministic `hash-v1`.
Every Ollama batch appends generation metadata to
`project_data/caption_generations.jsonl`. Use `hook_ai.py --caption-library` to
inspect accepted/rejected captions, hashes, model, prompt hash, and quality
warnings. Use `hook_ai.py --rank-existing --clip clip_010 --top 20` to rank the
current sidecar captions by local quality and any supplied performance summary.

Optional MediaPipe Pose support is used only with `--placement-signals pose`.
Pose summaries are cached in `manifest.sqlite`; if MediaPipe is absent, auto
placement keeps using YuNet face coverage, frame busyness, and motion.

Optional dependency installs:

```bash
REEL_FACTORY_OPTIONAL_DEPS=1 ./setup.sh
```

## Portability Notes

To run on another local machine, install Python dependencies, copy the project
folder, install ffmpeg, and choose an encoder profile that matches the host:

```bash
python3 reel_pipeline.py --root . --output-profile cpu_h264_x264
python3 reel_pipeline.py --root . --output-profile linux_nvenc
```

For local queued rendering, `--enqueue-only` writes command jobs to
`render_queue.sqlite`, `worker.py` claims/runs them, and `queue_admin.py`
reports status or recovers stale jobs. Optional Redis/RQ-compatible queue mode
uses `REDIS_URL` and `--queue-backend redis`/`rq`; install `redis` separately.
Distributed/cloud machines need shared storage or copied inputs/outputs; do not
place SQLite WAL databases on a network filesystem.

## Tests

```bash
python3 -m unittest discover -s tests
```

The tests cover the variation engine, pack versioning, timed hook parsing, job
key stability, recipe loading, graph-builder output paths, failed render
tracking, interrupted temp recovery, render attempt tracking, ProRes command
generation, caption PNG fitting, fuzzy hook duplicate detection, placement
scoring, AI hook validation/parsing, semantic hook grouping, thumbnail naming,
encoder profiles, manual metrics import, review states, and the SQLite manifest
JSON export path.
