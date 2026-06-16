# Campaign Factory Local Runbook

Current Creator OS note:

- Campaign Factory is the control brain; it does not own active image generation.
- Reel Factory's current still-image path is direct Higgsfield reference-image generation: reference image → Stacey Soul ID → one `9:16` still.
- Grok/Qwen/Ollama/Florence visual-schema, grids, cropped panels, and `_grok.json` prompt files are legacy Reel Factory experiments.
- Do not schedule, publish, export drafts, mutate account health, or mutate production inventory unless the user explicitly asks for that operation.

Copy these commands into separate terminals. Replace the values in `<>` before running.

## 1. Start services

Terminal A: ContentForge.

```bash
cd $CREATOR_OS_ROOT/contentforge
npm install
npm run dev -- --port 3100
```

Terminal B: Campaign Factory.

```bash
cd $CREATOR_OS_ROOT/campaign_factory
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
export CONTENTFORGE_BASE_URL=http://127.0.0.1:3100
export CONTENTFORGE_ROOT=$CREATOR_OS_ROOT/contentforge
export REEL_FACTORY_ROOT=$CREATOR_OS_ROOT/reel_factory
export REFERENCE_FACTORY_ROOT=$CREATOR_OS_ROOT/reference_factory
python3 -m campaign_factory.cli doctor --check-http \
  --contentforge-base-url http://127.0.0.1:3100
python3 -m campaign_factory.cli serve --host 127.0.0.1 --port 8877
```

Open the dashboard at `http://127.0.0.1:8877`.

## Fast path: make one full batch

Use this when you want the intended daily flow: import source videos, choose the
top reference pattern, render variants, audit them in ContentForge, approve
ready/warning-only outputs, and write a dry-run ThreadsDash export manifest.

```bash
cd $CREATOR_OS_ROOT/campaign_factory
. .venv/bin/activate

campaign-factory make-batch \
  --folder "<SOURCE_VIDEO_FOLDER>" \
  --campaign "<campaign_slug>" \
  --model "<model_slug>" \
  --format auto \
  --variant-count 8 \
  --reference-pattern auto \
  --contentforge-base-url http://127.0.0.1:3100 \
  --dry-run-export \
  --user-id "<supabase_user_id>"
```

Use `--format reel` for captioned video variants or `--format slideshow` for
the cheap carousel/reel pack. The dashboard has the same flow in **Pipeline Controls -> New Batch**. Live
Supabase writes are still separate and explicit; `make-batch` is draft-manifest
first.

## 2. Import finished source videos

Use the folder that contains the finished Higgsfield/Juno33 `.mp4` or `.mov` files.

```bash
cd $CREATOR_OS_ROOT/campaign_factory
. .venv/bin/activate

campaign-factory import-folder "<SOURCE_VIDEO_FOLDER>" \
  --campaign "<campaign_slug>" \
  --model "<model_slug>" \
  --platform instagram \
  --account "<instagram_account_or_handle>" \
  --notes "finished source videos"
```

Example:

```bash
campaign-factory import-folder "/Users/adercialonedesouza/Downloads" \
  --campaign downloads_test \
  --model downloads_model \
  --platform instagram \
  --notes "downloads source videos"
```

## 3. Prepare and render reels

Option A: prepare `reel_factory` inputs from manual hooks.

```bash
campaign-factory prepare-reel --campaign "<campaign_slug>" \
  --hook "Just cracked you in my head hope you feel better twin ✌️❤️" \
  --hook "If u got ts on your fyi ur high a nonchalant & chill ❤️‍🩹🥀" \
  --recipes v01_original v05_hflip v06_zoom \
  --caption-color auto
```

Option B: use the Reference Factory learning bank.

```bash
campaign-factory import-reference-bank
campaign-factory reference-patterns --limit 20

campaign-factory prepare-from-reference --campaign "<campaign_slug>" \
  --cluster-key "caption_led_visual::direct_response::question_hook" \
  --variant-count 5 \
  --recipes v01_original v05_hflip v06_zoom \
  --caption-color auto

campaign-factory reference-plan --campaign "<campaign_slug>"
```

`prepare-from-reference` creates fresh reel inputs by default so a new learned
pattern does not silently reuse older render jobs. Add `--reuse-existing` only
when you want to inspect the selected pattern without creating new clip sidecars.

The selected reference pattern also follows the campaign into ContentForge audit,
where it is used as a reference-match meter, not an export blocker.

Run `reel_factory` with the current Instagram caption defaults.
By default this renders only jobs in `prepared` or `failed` state; add
`--rerender-all` only when you intentionally want to regenerate older rendered
jobs too.

```bash
campaign-factory run-reel --campaign "<campaign_slug>" \
  --workers 3 \
  --band center \
  --color light \
  --style ig \
  --font "Instagram Sans Condensed"
```

Sync rendered outputs back into Campaign Factory.

```bash
campaign-factory sync-reel --campaign "<campaign_slug>"
```

Inspect the durable job records if rendering or sync fails.

```bash
campaign-factory jobs --campaign "<campaign_slug>" --limit 20
campaign-factory job --id "<pipeline_job_id>"
```

## 4. Audit, review, and approve

Run the ContentForge HTTP audit.

```bash
campaign-factory audit --campaign "<campaign_slug>" \
  --contentforge-base-url http://127.0.0.1:3100 \
  --min-score 85
```

Review videos in the dashboard, or approve/reject from CLI.

```bash
campaign-factory approve --rendered-asset-id "<rendered_asset_id>" \
  --notes "approved after dashboard review"

campaign-factory review-decision --rendered-asset-id "<rendered_asset_id>" \
  --decision rejected \
  --notes "bad caption placement"
```

Inspect recent operator activity.

```bash
campaign-factory activity-log --campaign "<campaign_slug>" --limit 20
```

Check campaign health, detail, and ranking.

```bash
campaign-factory campaign-health --campaign "<campaign_slug>"
campaign-factory asset-detail --rendered-asset-id "<rendered_asset_id>"
campaign-factory ranking --campaign "<campaign_slug>"
campaign-factory campaign-readiness --campaign "<campaign_slug>" \
  --user-id "<supabase_user_id>"
```

Assign approved variants to Instagram accounts before export. Planned windows
are metadata only; they do not schedule posts.

```bash
campaign-factory assign-account \
  --rendered-asset-id "<rendered_asset_id>" \
  --instagram-account-id "<instagram_account_id>" \
  --planned-window-start "2026-05-15T10:00:00-04:00" \
  --planned-window-end "2026-05-15T12:00:00-04:00" \
  --notes "morning review batch"

campaign-factory account-plan --campaign "<campaign_slug>" \
  --user-id "<supabase_user_id>"
```

## 5. Promote Reel Factory pilot ledger

If the 5-account pilot was planned in Reel Factory `posting_ledger.py`, promote
that local ledger into Campaign Factory before running the mass-production
readiness report.

Preview first:

```bash
campaign-factory promote-reel-ledger --campaign "<campaign_slug>"
```

Apply only after reviewing the preview:

```bash
campaign-factory promote-reel-ledger --campaign "<campaign_slug>" --apply
campaign-factory readiness-report --campaign-id "<campaign_slug>" --days 7
```

This writes Campaign Factory canonical `rendered_assets`,
`asset_account_assignments`, and `distribution_plans`. It does not write
ThreadsDash/Supabase posts, schedule posts, publish, or use Instagram private
APIs.

## 6. Check export readiness

Dry readiness check without Supabase credentials.

```bash
campaign-factory export-readiness --campaign "<campaign_slug>" \
  --user-id "<supabase_user_id>" \
  --content-pillar lifestyle \
  --cta-type profile_visit \
  --language en
```

Readiness check against real ThreadsDash/Supabase draft history.

```bash
export SUPABASE_URL="<supabase_url>"
export SUPABASE_SERVICE_ROLE_KEY="<fresh_service_role_key>"

campaign-factory export-readiness --campaign "<campaign_slug>" \
  --user-id "<supabase_user_id>" \
  --supabase-url "$SUPABASE_URL" \
  --supabase-service-role-key "$SUPABASE_SERVICE_ROLE_KEY" \
  --content-pillar lifestyle \
  --cta-type profile_visit \
  --language en
```

## 6. Export ThreadsDash drafts

Dry-run manifest only. This does not write to Supabase.

```bash
campaign-factory export-threadsdash --campaign "<campaign_slug>" \
  --user-id "<supabase_user_id>" \
  --dry-run \
  --content-pillar lifestyle \
  --cta-type profile_visit \
  --language en
```

Real draft write to Supabase. This uploads final approved media and creates `draft` posts only.

```bash
campaign-factory export-threadsdash --campaign "<campaign_slug>" \
  --user-id "<supabase_user_id>" \
  --supabase-url "$SUPABASE_URL" \
  --supabase-service-role-key "$SUPABASE_SERVICE_ROLE_KEY" \
  --supabase-storage-bucket media \
  --content-pillar lifestyle \
  --cta-type profile_visit \
  --language en \
  --allow-warnings
```

V1 never creates scheduled or published posts.

After a real export, verify what was written.

```bash
campaign-factory verify-threadsdash-export "<export_manifest_path>" \
  --supabase-url "$SUPABASE_URL" \
  --supabase-service-role-key "$SUPABASE_SERVICE_ROLE_KEY"
```

## 7. Sync performance feedback

After drafts are published manually in ThreadsDash and metrics are available, sync
performance back into Campaign Factory. Metrics are used for operator ranking
only; they do not schedule or publish anything.

```bash
campaign-factory sync-performance --campaign "<campaign_slug>" \
  --user-id "<supabase_user_id>" \
  --supabase-url "$SUPABASE_URL" \
  --supabase-service-role-key "$SUPABASE_SERVICE_ROLE_KEY"

campaign-factory performance-summary --campaign "<campaign_slug>"
```

## 8. One-command smoke run

This imports, prepares, optionally renders, syncs, audits, and writes a dry-run export manifest.

```bash
campaign-factory pipeline-smoke \
  --folder "<SOURCE_VIDEO_FOLDER>" \
  --campaign "<campaign_slug>" \
  --model "<model_slug>" \
  --user-id "<supabase_user_id>" \
  --hook "Just cracked you in my head hope you feel better twin ✌️❤️" \
  --recipes v01_original v05_hflip \
  --contentforge-base-url http://127.0.0.1:3100
```

Add `--run-reel` only when you want the smoke command to actually render videos.
