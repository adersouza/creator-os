# Reference Factory

Local video-first analyzer for high-performing reference reels.

Reference Factory turns `$HOME/Downloads/examples` into a structured
local corpus without modifying the source media. It probes videos, samples
frames, runs OCR through Apple Vision/Tesseract fallback, generates contact
sheets, and stores manual review labels for later prompt/style research.

## Quick Start

```bash
cd $CREATOR_OS_ROOT/reference_factory
python3 -m pytest -q
python3 -m reference_factory.cli scan --source $HOME/Downloads/examples
python3 -m reference_factory.cli probe --limit 50
python3 -m reference_factory.cli sample-frames --limit 20
python3 -m reference_factory.cli ocr --engine auto --limit 20
python3 -m reference_factory.cli contact-sheet --mode random --count 50
```

Derived data is written under:

```text
$CREATOR_OS_ROOT/reference_reels/
```

Source media remains in place and is never moved or deleted.

## Commands

```bash
python3 -m reference_factory.cli scan --source $HOME/Downloads/examples
python3 -m reference_factory.cli probe --limit all
python3 -m reference_factory.cli sample-frames --videos all
python3 -m reference_factory.cli ocr --engine auto --likely-captioned-only
python3 -m reference_factory.cli contact-sheet --mode random --count 100
python3 -m reference_factory.cli contact-sheet --mode top-accounts --per-account 25
python3 -m reference_factory.cli contact-sheet --mode captioned --count 100
python3 -m reference_factory.cli contact-sheet --mode visual --count 100
python3 -m reference_factory.cli contact-sheet --mode unreviewed --count 200
python3 -m reference_factory.cli thumbnail-batch --limit all
python3 -m reference_factory.cli review-server --host 127.0.0.1 --port 8765
python3 -m reference_factory.cli shortlist --target 300
python3 -m reference_factory.cli review-batch --target 300 --mode balanced
python3 -m reference_factory.cli label --reference-id ref_xxx --label gold --tags caption_style,mirror
python3 -m reference_factory.cli ocr-cleanup
python3 -m reference_factory.cli export-gold
python3 -m reference_factory.cli import-apify-metrics --input /path/to/apify.json
python3 -m reference_factory.cli import-tiktok-archive --source $HOME/Downloads/tiktok
python3 -m reference_factory.cli top-public-posts --limit 300
python3 -m reference_factory.cli generate-prompt-cards --limit 50
python3 -m reference_factory.cli export-learning-set --limit 300
python3 -m reference_factory.cli analyze-patterns --limit 300
python3 -m reference_factory.cli analyze-audio-patterns --limit 300
python3 -m reference_factory.cli export-patterns --limit 300
python3 -m reference_factory.cli build-learning-system --limit 300
```

The rebuild selector defaults to a 50/50 caption-driven versus visual-driven
mix and caps each source account at 60 references. Override deterministically
with `--caption-share` and `--account-cap`, or set
`REFERENCE_BANK_CAPTION_SHARE` and `REFERENCE_BANK_ACCOUNT_CAP`. When follower
counts are present, ranking uses `(likes + comments) / followers` before raw
reach; missing follower counts fall back to engagement-per-view and raw volume.
Use `--strict-balance` for a rebuild that leaves scarce bucket capacity empty
instead of padding the bank with the dominant signal type.

## Gemini App/Chrome Prompt Test

```bash
cd $CREATOR_OS_ROOT/reference_factory
.venv/bin/python -m reference_factory.cli queue-reference-analysis \
  --source $HOME/Downloads/examples \
  --platform instagram \
  --provider-target gemini_app \
  --prompt-style minimal \
  --media-kinds video \
  --limit 1
.venv/bin/python -m reference_factory.cli export-reference-analysis-queue \
  --provider-target gemini_app \
  --limit 1
```

Open Gemini in the installed app or the normal logged-in Chrome/Safari session,
switch the model picker to **Pro**, upload the queued source video, paste the
exported prompt, and copy Gemini's JSON answer. Do not use a Playwright/login
browser for Gemini; Google can reject it as an insecure browser. Import the
copied response straight from the macOS clipboard:

```bash
.venv/bin/python -m reference_factory.cli import-gemini-app-response \
  --queue $CREATOR_OS_ROOT/reference_reels/reference_intake/gemini_app_analysis_queue.json \
  --model-profile stacey
```

That writes:

```text
$CREATOR_OS_ROOT/reference_reels/reference_intake/gemini_app_import_latest.json
$CREATOR_OS_ROOT/reference_reels/reference_intake/daily_higgsfield_image_prompts.jsonl
$CREATOR_OS_ROOT/reference_reels/reference_intake/daily_kling_video_prompts.jsonl
$CREATOR_OS_ROOT/reference_reels/reference_intake/daily_prompt_review.md
```

For full automation without browser clicking, use the official Gemini API:

```bash
GEMINI_API_KEY=... .venv/bin/python -m reference_factory.cli analyze-reference-with-gemini-api \
  --source $HOME/Downloads/examples \
  --platform instagram \
  --prompt-style minimal \
  --limit 1
```

## Gold Review Sprint

The first review target is a balanced `300` item gold set: at least `120`
captioned examples, at least `120` visual/no-caption examples, and no more than
`30` gold picks from one account unless you intentionally override that later.

```bash
cd $CREATOR_OS_ROOT/reference_factory
python3 -m reference_factory.cli review-batch --target 300 --mode balanced
python3 -m reference_factory.cli review-server --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`, click **Guided 300 Batch**, and label in batches:

- `gold`: strong style/caption/visual pattern worth learning from
- `maybe`: useful but not clearly top-tier
- `ignore`: broken, duplicate, weak, irrelevant, or low-value

When done, export the usable set:

```bash
python3 -m reference_factory.cli export-gold
```

Outputs:

```text
$CREATOR_OS_ROOT/reference_reels/curated/gold_manifest.jsonl
$CREATOR_OS_ROOT/reference_reels/curated/gold_summary.json
```

## OCR

`--engine auto` tries Apple Vision first on macOS, then falls back to Tesseract.
Tesseract uses original, enhanced/upscaled, and thresholded frame variants.

OCR output is saved as caption pattern data for later analysis. Do not treat
reference captions as production copy; they are stored for style and structure
study.

## Public Performance + Prompt Cards

Apify public post scrapes can be imported as external performance references:

```bash
python3 -m reference_factory.cli import-apify-metrics \
  --input $CREATOR_OS_ROOT/reference_reels/apify/ig_scrape_top30x50_detailed.json \
  --input $CREATOR_OS_ROOT/reference_reels/apify/ig_scrape_remaining_x50_detailed.json
python3 -m reference_factory.cli top-public-posts --limit 300
python3 -m reference_factory.cli generate-prompt-cards --limit 50
python3 -m reference_factory.cli export-learning-set --limit 300
```

Important: Apify posts are matched to local files only when Instagram numeric
media IDs align with local filenames. Otherwise they are stored as
`external_only` public winners from the same account universe. Prompt cards use
the winning structure and public metrics; they do not copy captions directly.
When the scrape includes creator audience size, public winner ranking uses
play/view rate per follower before falling back to raw plays.

Campaign Factory measured outcomes can be imported after posts have actual
performance data:

```bash
python3 -m reference_factory.cli import-prompt-outcomes \
  --input $CREATOR_OS_ROOT/reference_reels/outcomes/campaign_prompt_outcomes.json
```

Outcome rows should include `referenceId` or `promptId`, `rewardScore`,
`confidence`, and `sampleCount`. Reference Factory stores those fields on
`generated_video_prompts`; `top-public-posts`, `analyze-patterns`, and
`build-learning-system` prefer measured reward evidence over public raw-volume
rankings when it exists.

TikTok/myfaveTT slideshow archives can be imported as slideshow reference
material:

```bash
python3 -m reference_factory.cli import-tiktok-archive \
  --source $HOME/Downloads/tiktok \
  --top-limit 300
python3 -m reference_factory.cli probe --limit all
python3 -m reference_factory.cli thumbnail-batch --limit all
python3 -m reference_factory.cli analyze-patterns --limit 300 --provider heuristic
python3 -m reference_factory.cli build-learning-system --limit 300
```

The importer preserves creator names, local MP4 paths, cover paths, captions,
likes, play counts, and the `tiktok_slideshow` source format. These references
are used as pattern data for slideshow layout, first-slide hooks, caption
formulas, and Higgsfield prompt inspiration.

`export-learning-set` writes the operational bundle used by the next pipeline:

```text
$CREATOR_OS_ROOT/reference_reels/learning/learning_set_top300.json
$CREATOR_OS_ROOT/reference_reels/learning/learning_set_top300.jsonl
$CREATOR_OS_ROOT/reference_reels/learning/prompt_cards_top300.jsonl
$CREATOR_OS_ROOT/reference_reels/learning/pattern_cards_top300.jsonl
$CREATOR_OS_ROOT/reference_reels/learning/pattern_summary_top300.json
$CREATOR_OS_ROOT/reference_reels/learning/learning_clusters_top300.json
$CREATOR_OS_ROOT/reference_reels/learning/reference_playbook_top300.md
$CREATOR_OS_ROOT/reference_reels/learning/higgsfield_prompt_pack_top300.jsonl
$CREATOR_OS_ROOT/reference_reels/learning/campaign_reference_bank.json
$CREATOR_OS_ROOT/reference_reels/learning/caption_formula_bank.json
```

`analyze-patterns` turns public winners into reusable pattern labels:
visual format, hook type, caption archetype, suggested review label, prompt
pattern, and reasons. It uses local heuristics by default. If Ollama is running
with an installed model, `--provider auto` upgrades to local LLM labeling; use
`--provider heuristic` for deterministic output.

Grok/xAI prompt compilation and Ollama labeling are experimental
Reference Factory analysis paths. They are useful for reference-learning and
prompt-pack research when explicitly invoked, but Reel Factory's active
production generation baseline remains direct Higgsfield reference-image stills,
not Grok/grid generation.

`build-learning-system` clusters the analyzed winners into reusable formats,
writes the operator playbook, creates a Higgsfield/Kling-style prompt pack,
exports caption formulas, and writes a Campaign Factory reference bank. The
Campaign Factory handoff includes `patternId`, local `referenceFiles`, caption
formula data, visual recipe hints, suggested reel recipes, suggested formats
(`reel`/`slideshow`), and public performance signals so batch generation can
pick better starting patterns.

By default, `build-learning-system` tries local DINOv2/timm image embeddings
for visual clusters and falls back to heuristic labels when the optional model
stack or usable media is unavailable. Use `--no-embedding-clusters` for the old
heuristic-only grouping, or tune with `--embedding-model` and
`--embedding-threshold`. Embeddings are cached under
`reference_reels/learning/embedding_cache/`.

`analyze-audio-patterns` extracts native audio signals from scraped references:
Instagram `musicInfo`, TikTok `audioId`, usage type, source platform, matching
visual format, total plays, and a plain-language recommendation. The learning
system includes these recommendations in:

```text
$CREATOR_OS_ROOT/reference_reels/learning/audio_patterns_top300.json
$CREATOR_OS_ROOT/reference_reels/learning/audio_patterns_top300.jsonl
$CREATOR_OS_ROOT/reference_reels/learning/higgsfield_prompt_pack_top300.jsonl
$CREATOR_OS_ROOT/reference_reels/learning/campaign_reference_bank.json
```

Audio guidance is intentionally native-audio-first: it tells the operator what
sound or sound style to choose in Instagram/TikTok/ThreadsDash instead of
hard-burning unknown copyrighted audio into generated files.

The audio catalog also supports manual trend snapshots. Operators can record
freshness, usage, saturation, and velocity observations from an official/manual
platform review without scraping or automating platform access:

```bash
python3 -m reference_factory.cli import-audio-snapshot-csv --input audio_snapshots.csv
python3 -m reference_factory.cli add-audio-snapshot \
  --platform instagram \
  --native-audio-id ig_123 \
  --trend-status trending \
  --usage-count 42000 \
  --saturation-score 0.35 \
  --velocity-score 0.8 \
  --source "manual operator review"
python3 -m reference_factory.cli list-audio-snapshots --platform instagram
```

Snapshot updates refresh the catalog's current trend status and usage count,
but stale or saturated audio remains advisory: it appears in the review queue
and is down-ranked in recommendations rather than automatically deleted.

```bash
python3 -m reference_factory.cli export-patterns --limit 300 --for-campaign-factory
```

Use `--copy-media` only when you intentionally want to stage matched local
videos into `reference_reels/learning/contentforge_references/` for a
ContentForge reference match comparison. Reference Factory learns from winners;
ContentForge audits generated outputs so they are technically ready and records
how closely they match explicit references.
