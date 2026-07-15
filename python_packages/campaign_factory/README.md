# Campaign Factory

Campaign Factory is Creator OS's local campaign control brain. It owns creative
plans, inventory, account assignment, readiness, spend gates, QC requests,
draft payload construction, and performance-learning ingestion.

It does not own image/video provider implementation, ContentForge judgment,
the product UI, scheduling, or publishing.

## Supported Operator Path

Use the repository command from the monorepo root:

```bash
scripts/creator-os campaign-prepare --confirm-write \
  --folder /path/to/media --campaign campaign_slug --model model_slug

scripts/creator-os static-reel --dry-run \
  --campaign campaign_slug --still /path/to/accepted.png

scripts/creator-os readiness --campaign campaign_slug --user-id user_id

scripts/creator-os draft-export --dry-run \
  --campaign campaign_slug --user-id user_id --max-drafts 10
```

`campaign-prepare` never exports and disables auto-approval. `draft-export`
forces draft schedule mode; `--apply` may write validated drafts but cannot
schedule or publish.

## Package CLI

The installed `campaign-factory` CLI remains the package implementation
boundary. Developers can inspect it directly:

```bash
uv run --package campaign-factory campaign-factory --help
uv run --package campaign-factory campaign-factory control-check
uv run --package campaign-factory campaign-factory campaign-readiness \
  --campaign campaign_slug --user-id user_id
uv run --package campaign-factory campaign-factory export-threadsdash \
  --campaign campaign_slug --user-id user_id --dry-run --max-drafts 10
```

The authenticated FastAPI application is a headless JSON integration surface.
It serves no committed dashboard assets. ThreadsDashboard is the only product
UI.

## Generation And QC Boundaries

Campaign Factory delegates media work to canonical Reel Factory modules. The
active path is direct Higgsfield Soul still generation, a local static MP4 for
accepted stills, and optional explicitly approved motion. Paid execution
requires opt-in plus a finite credit cap.

ContentForge runs as a local stdin/stdout JSON CLI. Campaign Factory stages the
source and candidate, requests the `campaign_factory_v1` audit profile, and
stores the evidence. Only a clean `overallVerdict = pass` can become an
approved candidate automatically; warnings remain human-review outcomes and
failures block export.

The review-batch import path also requires Reel Factory guard evidence and a
matching ContentForge audit. Raw, stale, foreign, or self-attested packages are
rejected.

## State And Paths

`creator_os_core.runtime_paths` resolves the monorepo, package roots, reference
data, runtime checkout, and external ThreadsDashboard checkout. Explicit
environment variables override defaults:

- `CAMPAIGN_FACTORY_DB`
- `CAMPAIGN_FACTORY_ROOT`
- `REEL_FACTORY_ROOT`
- `REFERENCE_FACTORY_ROOT`
- `CONTENTFORGE_ROOT`
- `THREADSDASH_ROOT`

The SQLite database and campaign media directories are runtime/operator state
and must not be committed.

## Draft And Learning Safety

Draft payloads validate against Pipeline Contracts and preserve source,
rendered-asset, prompt, caption, recipe, QC, assignment, and lineage evidence.
HMAC signing is the draft-ingest boundary. ThreadsDashboard owns approval,
native-audio proof, schedule, publish, and analytics.

The pinned performance launcher imports bounded post metric history and invokes
`scripts/learning_fanout.py`. Real learning proof requires real platform rows;
command success alone is not sufficient.

## Test

```bash
uv run pytest python_packages/campaign_factory/tests
uv run pytest tests/integration
```

Safety coverage includes paid credit lifecycle, provider failures, global kill
switch, QC/readiness, lineage, state transitions, draft export/HMAC, poisoned or
ambiguous data, and performance-learning seams.
