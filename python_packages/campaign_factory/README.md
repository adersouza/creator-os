# Campaign Factory

Campaign Factory is Creator OS's local campaign control brain. It owns creative
plans, inventory, account assignment, readiness, spend gates, QC requests,
draft payload construction, and performance-learning ingestion.

It does not own image/video provider implementation, ContentForge judgment,
the product UI, scheduling, or publishing.

## Supported Operator Path

Use the repository command from the monorepo root:

```bash
scripts/creator-os generate --mode library_reuse --apply \
  --folder /path/to/media --campaign campaign_slug --model model_slug

scripts/creator-os generate --list-modes

scripts/creator-os generate --mode soul_static --dry-run \
  --campaign campaign_slug --accepted-still /path/to/accepted.png

scripts/creator-os readiness --campaign campaign_slug --user-id user_id

scripts/creator-os draft-export --dry-run \
  --campaign campaign_slug --user-id user_id --max-drafts 10
```

Library reuse never exports and disables auto-approval. `draft-export` forces
draft schedule mode; `--apply` may write validated drafts but cannot schedule
or publish.

Every new generation run uses `generate --mode <mode>`. The Campaign Factory
mode catalog is the only source for mode identifiers, costs, inputs, outputs,
and approval gates; no package or root command silently chooses a mode.
The five current modes are `library_reuse`, `soul_static`, `local_wan`,
`best_motion`, and `reference_video_remix`.

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
accepted stills, and optional local Wan or explicitly approved WaveSpeed motion. Paid execution
requires opt-in, an explicit Soul ID, a finite credit cap, and a machine-local
`CREATOR_OS_SPEND_AUTH_SECRET`. Campaign Factory owns provider quotes, balance
and budget policy, reservations, and the authoritative cost ledger. Reel
Factory receives a short-lived one-time signed authorization and records only
worker execution evidence; invoking its paid modes directly fails closed.

WaveSpeed spend is denominated in USD under the v2 provider authorization.
Every request binds the exact provider model, task, prompt hash, media hashes,
duration, resolution, seed, and other model parameters. A static fallback is
created before an apply. Generated motion is registered as review-only with
ContentForge, final-human-review, and native-audio blockers still unresolved.
No motion command schedules or publishes.

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
uv run python -m pytest python_packages/campaign_factory/tests
uv run python -m pytest tests/integration
```

Safety coverage includes paid credit lifecycle, provider failures, global kill
switch, QC/readiness, lineage, state transitions, draft export/HMAC, poisoned or
ambiguous data, and performance-learning seams.
