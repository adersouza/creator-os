# Reference Factory Gold Review Runbook

## Start Review

```bash
cd /Users/adercialonedesouza/Projects/reference_factory
python3 -m reference_factory.cli review-server --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765`.

## Review Batch

Use the UI **Guided 300 Batch** button, or inspect the batch in the terminal:

```bash
python3 -m reference_factory.cli review-batch --target 300 --mode balanced
```

Label examples:

- `gold`: strong style/caption/visual pattern worth learning from
- `maybe`: useful but not clearly top-tier
- `ignore`: broken, duplicate, weak, irrelevant, or low-value

Default target:

- `300` gold references
- at least `120` captioned examples
- at least `120` visual/no-caption examples
- max `30` gold items from one account in the first pass

## Export Gold Set

```bash
python3 -m reference_factory.cli export-gold
```

Outputs:

```text
/Users/adercialonedesouza/Projects/reference_reels/curated/gold_manifest.jsonl
/Users/adercialonedesouza/Projects/reference_reels/curated/gold_summary.json
```

## Verify

```bash
python3 -m pytest -q
python3 -m reference_factory.cli review-batch --target 300 --mode balanced
python3 -m reference_factory.cli export-gold
```

Source videos under `/Users/adercialonedesouza/Downloads/examples` are never moved,
edited, or deleted.

## Public Winners Learning Set

After Apify scrapes are saved, import metrics and export the top-300 learning
set:

```bash
python3 -m reference_factory.cli import-apify-metrics \
  --input /Users/adercialonedesouza/Projects/reference_reels/apify/ig_scrape_top30x50_detailed.json \
  --input /Users/adercialonedesouza/Projects/reference_reels/apify/ig_scrape_remaining_x50_detailed.json

python3 -m reference_factory.cli export-learning-set --limit 300
python3 -m reference_factory.cli analyze-patterns --limit 300
python3 -m reference_factory.cli analyze-audio-patterns --limit 300
python3 -m reference_factory.cli import-audio-snapshot-csv \
  --input /path/to/manual_audio_snapshots.csv
python3 -m reference_factory.cli export-patterns --limit 300
python3 -m reference_factory.cli build-learning-system --limit 300
```

Outputs:

```text
/Users/adercialonedesouza/Projects/reference_reels/learning/learning_set_top300.json
/Users/adercialonedesouza/Projects/reference_reels/learning/learning_set_top300.jsonl
/Users/adercialonedesouza/Projects/reference_reels/learning/prompt_cards_top300.jsonl
/Users/adercialonedesouza/Projects/reference_reels/learning/pattern_cards_top300.jsonl
/Users/adercialonedesouza/Projects/reference_reels/learning/pattern_summary_top300.json
/Users/adercialonedesouza/Projects/reference_reels/learning/audio_patterns_top300.json
/Users/adercialonedesouza/Projects/reference_reels/learning/audio_patterns_top300.jsonl
/Users/adercialonedesouza/Projects/reference_reels/learning/learning_clusters_top300.json
/Users/adercialonedesouza/Projects/reference_reels/learning/reference_playbook_top300.md
/Users/adercialonedesouza/Projects/reference_reels/learning/higgsfield_prompt_pack_top300.jsonl
/Users/adercialonedesouza/Projects/reference_reels/learning/campaign_reference_bank.json
/Users/adercialonedesouza/Projects/reference_reels/learning/caption_formula_bank.json
```

The `campaign_reference_bank.json` file is the bridge into Campaign Factory:
each cluster includes local reference paths, top examples, prompt templates,
caption formulas, audio recommendations, and the intended
`close_format_variation` match goal.

Pattern analysis writes machine labels without replacing your manual taste
labels. To intentionally copy machine suggestions into `gold/maybe/ignore`:

Audio trend snapshots are manual/operator-curated only. Record observations
from an official platform UI or another approved source with
`add-audio-snapshot` or `import-audio-snapshot-csv`; do not scrape or automate
platform audio discovery. Stale, fading, expired, or high-saturation audio is
sent to the advisory review queue and down-ranked, not auto-deleted.

```bash
python3 -m reference_factory.cli apply-pattern-labels --limit 300
```

Reference Factory is the learning/reference system. ContentForge is the audit
system: use it later to compare generated outputs against explicit references
for reference match and upload-readiness.

## TikTok Slideshow References

Use this when a local TikTok/myfaveTT archive is saved under
`/Users/adercialonedesouza/Downloads/tiktok`:

```bash
python3 -m reference_factory.cli import-tiktok-archive \
  --source /Users/adercialonedesouza/Downloads/tiktok \
  --top-limit 300
python3 -m reference_factory.cli probe --limit all
python3 -m reference_factory.cli thumbnail-batch --limit all
python3 -m reference_factory.cli analyze-patterns --limit 300 --provider heuristic
python3 -m reference_factory.cli analyze-audio-patterns --limit 300
python3 -m reference_factory.cli build-learning-system --limit 300
```

Expected outputs:

```text
/Users/adercialonedesouza/Projects/reference_reels/tiktok/top_300_public_posts_matched.jsonl
/Users/adercialonedesouza/Projects/reference_reels/tiktok/top_300_public_posts_matched_summary.json
/Users/adercialonedesouza/Projects/reference_reels/learning/campaign_reference_bank.json
/Users/adercialonedesouza/Projects/reference_reels/learning/higgsfield_prompt_pack_top300.jsonl
```

TikTok slideshow posts are marked as `tiktok_slideshow` patterns. Campaign
Factory can use those as slideshow-first reference patterns; ContentForge can
use the local MP4s as comparison references later.

## Higgsfield + Kling Daily Generation

Use this after Gemini/manual or Gemini API analysis has produced daily prompt
exports:

```bash
cd /Users/adercialonedesouza/Projects/reference_factory

.venv/bin/python -m reference_factory.cli \
  --data-root /Users/adercialonedesouza/Projects/reference_reels \
  generate-video-prompts \
  --tools higgsfield_soul,kling_3 \
  --model-profile Stacey \
  --limit 10
```

Check the exact commands and credit estimate before spending credits:

```bash
.venv/bin/python -m reference_factory.cli \
  --data-root /Users/adercialonedesouza/Projects/reference_reels \
  generate-with-higgsfield \
  --limit 1 \
  --soul-id Stacey \
  --kling-mode std \
  --wait \
  --dry-run
```

Run one real generation with a conservative cap:

```bash
.venv/bin/python -m reference_factory.cli \
  --data-root /Users/adercialonedesouza/Projects/reference_reels \
  generate-with-higgsfield \
  --limit 1 \
  --soul-id Stacey \
  --kling-mode std \
  --wait \
  --max-credits 8
```

The runner uses Higgsfield CLI directly:

- `text2image_soul_v2` for the Stacey Soul ID first-frame image
- `kling3_0` for image-to-video from that generated image
- `9:16`, Kling `std`, sound `off`

Outputs are written under:

```text
/Users/adercialonedesouza/Projects/reference_reels/reference_intake/generated/YYYY-MM-DD/<reference_id>/
```

Each run writes `run_manifest.json` and `generated_asset_lineage.json`. The
lineage is the handoff object Campaign Factory stores during finished-video
intake.

To generate and intake successful Kling videos into Campaign Factory as
draft-first assets:

```bash
.venv/bin/python -m reference_factory.cli \
  --data-root /Users/adercialonedesouza/Projects/reference_reels \
  run-daily-generation \
  --creative-plan stacey_daily \
  --campaign stacey_daily \
  --model stacey \
  --campaign-factory-root /Users/adercialonedesouza/Projects/campaign_factory \
  --limit 10 \
  --soul-id Stacey \
  --kling-mode std \
  --wait \
  --max-credits 80
```

This does not publish, schedule live, or attach trending audio. Campaign
Factory still exports drafts first, ContentForge remains human-review-first,
and ThreadsDashboard native-audio gates remain the final publishing lock.
