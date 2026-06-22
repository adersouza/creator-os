# campaign_factory

Local control layer for turning finished Higgsfield/Juno33 source videos into campaign-ready reel assets.

V1 is folder-import based:

```text
finished videos folder
  -> campaign_factory import
  -> reel_factory caption/render inputs
  -> ContentForge HTTP audit reports
  -> human approval
  -> ThreadsDash/Supabase draft export/import
```

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

## Common Commands

For the full local end-to-end workflow, see [RUNBOOK.md](RUNBOOK.md).

```bash
campaign-factory init
campaign-factory doctor
campaign-factory serve

campaign-factory import-folder /path/to/higgsfield/videos \
  --campaign may_launch \
  --model model_a \
  --model-name "Model A" \
  --account ig_account_1

campaign-factory prepare-reel --campaign may_launch \
  --hooks hooks.json \
  --recipes v01_original v05_hflip

campaign-factory import-reference-bank
campaign-factory reference-patterns --limit 20
campaign-factory make-batch \
  --folder /path/to/videos \
  --campaign may_launch \
  --model model_a \
  --format auto \
  --variant-count 8 \
  --reference-pattern auto \
  --dry-run-export \
  --user-id <supabaseUserId>
campaign-factory prepare-from-reference --campaign may_launch \
  --cluster-key "caption_led_visual::direct_response::question_hook" \
  --variant-count 5 \
  --recipes v01_original v05_hflip

campaign-factory run-reel --campaign may_launch --workers 3
campaign-factory sync-reel --campaign may_launch
campaign-factory audit --campaign may_launch --contentforge-base-url http://127.0.0.1:3000
campaign-factory approve --rendered-asset-id <id>
campaign-factory activity-log --campaign may_launch --limit 20
campaign-factory jobs --campaign may_launch --limit 20
campaign-factory campaign-health --campaign may_launch
campaign-factory asset-detail --rendered-asset-id <id>
campaign-factory assign-account --rendered-asset-id <id> --instagram-account-id <igAccountId>
campaign-factory account-plan --campaign may_launch --user-id <supabaseUserId>
campaign-factory ranking --campaign may_launch
campaign-factory campaign-readiness --campaign may_launch --user-id <supabaseUserId>
campaign-factory promote-reel-ledger --campaign may_launch
campaign-factory readiness-report --campaign-id may_launch --days 7
campaign-factory export-threadsdash --campaign may_launch --user-id <supabaseUserId> --dry-run
campaign-factory export-readiness --campaign may_launch --user-id <supabaseUserId>
```

`run-reel` renders only `prepared` or `failed` jobs by default. Use
`--rerender-all` for an intentional full rerender.

The default local paths are:

- `../reel_factory`
- `../contentforge`
- `../ThreadsDashboard`

Override them with environment variables:

```bash
REEL_FACTORY_ROOT=/path/to/reel_factory
CONTENTFORGE_ROOT=/path/to/contentforge
CONTENTFORGE_BASE_URL=http://127.0.0.1:3000
THREADSDASH_ROOT=/path/to/ThreadsDashboard
REFERENCE_FACTORY_ROOT=/path/to/reference_factory
CAMPAIGN_FACTORY_DB=/path/to/campaign_factory.sqlite
```

Use `campaign-factory doctor --check-http --contentforge-base-url http://127.0.0.1:3100`
to confirm Campaign Factory can see the local repos, renderer entrypoints,
reference handoff file, and optional running ContentForge server before a batch.

ContentForge audit expects the ContentForge dev server to be running. The adapter
stages each source into ContentForge's `uploads/`, stages each rendered asset
into ContentForge's `output/final/`, then calls `POST /api/similarity` with:

```json
{
  "source": "<staged source filename>",
  "targetFile": "<staged rendered filename>",
  "auditProfile": "campaign_factory_v1",
  "layers": ["pdq", "sscd", "audio", "forensics", "compression", "provenance", "reference", "temporal", "ssim"]
}
```

The full report is stored under `03_contentforge_audits`. Campaign Factory reads
`readinessSummary.summaryText`, `topWarnings`, `blockingReasons`, and
`recommendedAction` for operator review. Only a clean `overallVerdict = pass`
maps automatically to `approved_candidate`; `warn` remains upload-ready but
requires human review.

For a Reel Factory review batch, create the batch-level Campaign Factory audit
before importing the package:

```bash
creator-os review-batch-contentforge-audit \
  --manifest /path/to/review_manifest.json \
  --source /path/to/master_or_pre_overlay.mp4 \
  --contentforge-base-url http://127.0.0.1:3100
```

This calls ContentForge with `auditProfile: "campaign_factory_v1"`, writes a
guard-compatible audit JSON next to the review manifest, and records
`contentForgeAuditPath` in the manifest. `import-folder` then refuses raw review
batches without a guard-passed package and promotes each accepted row into
`rendered_assets` as `review_ready`; export still requires an explicit operator
approval.

Supabase import is optional. Without `--supabase-url` and `--supabase-service-role-key`, `export-threadsdash` writes a manifest only.
Campaign Factory stores lineage metadata in draft payloads and ThreadsDash
`posts.metadata.campaign_factory`, including source/rendered IDs, content hashes,
caption hashes, recipe, audit status, optional `content_pillar`, `cta_type`, and
`language`.

Before live writes, Campaign Factory evaluates export readiness. It blocks missing
audits, rejected/unapproved assets, failed audit checks, unavailable usage
checks, and exact renders that were already published. It warns on already queued
renders, source-family reuse, repeated captions, batch volume, and ContentForge
`warn` verdicts. Warnings require `--allow-warnings` for live writes.

Campaign Factory also records local operator history. `activity-log` shows the
append-only event trail for imports, renders, audits, approvals, exports, and
performance syncs. `jobs` shows durable synchronous job records with inputs,
results, errors, attempts, and timestamps so failed work can be inspected later.
Secrets are redacted before job or event metadata is stored.

Reference Factory integration is local-first. `import-reference-bank` imports
the learning system's `campaign_reference_bank.json` plus the Higgsfield prompt
pack. `prepare-from-reference` selects a winning cluster and writes fresh
reference-derived hook sidecars for `reel_factory` by default; pass
`--reuse-existing` only when you intentionally want to avoid creating new reel
inputs for sources that already have render jobs. When a campaign has a selected
reference pattern, ContentForge audit stages those local reference videos and
sends them to its `originality` layer as an informational reference-match meter.

The operator control-room APIs and CLI expose campaign health, asset detail,
account planning, campaign readiness, and performance-aware ranking. Explicit
account assignments are preferred during draft export; if no assignment exists,
Campaign Factory falls back to the source import account metadata. Planned
posting windows are stored as review metadata only and never become scheduled
posts.

For the 5-account pilot, Reel Factory may create local pilot slots in its
`posting_ledger.py`. Promote those slots into Campaign Factory before judging
mass-production readiness:

```bash
campaign-factory promote-reel-ledger --campaign may_launch
campaign-factory promote-reel-ledger --campaign may_launch --apply
campaign-factory readiness-report --campaign-id may_launch --days 7
```

The first command is a dry-run preview. `--apply` is required to write canonical
Campaign Factory `rendered_assets`, `asset_account_assignments`, and
`distribution_plans`. ThreadsDash remains downstream; this command does not
write Supabase posts, schedule posts, publish, or use Instagram private APIs.

To write real draft rows:

```bash
campaign-factory export-threadsdash --campaign may_launch \
  --user-id <supabaseUserId> \
  --supabase-url "$SUPABASE_URL" \
  --supabase-service-role-key "$SUPABASE_SERVICE_ROLE_KEY" \
  --supabase-storage-bucket media \
  --content-pillar lifestyle \
  --cta-type profile_visit \
  --language en \
  --allow-warnings
```

The Supabase writer uploads videos to the `media` storage bucket, inserts `media`
rows, then inserts Instagram `posts` rows with `status = 'draft'`. It does not
schedule or publish.
