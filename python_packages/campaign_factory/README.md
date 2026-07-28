# Campaign Factory

Campaign Factory is Creator OS's local campaign control brain. It owns creative
plans, inventory, account assignment, readiness, spend gates, QC requests,
draft payload construction, and performance-learning ingestion.

It does not own image/video provider implementation, ContentForge judgment,
the product UI, scheduling, or publishing.

## Supported Operator Path

Use the repository command from the monorepo root:

```bash
scripts/creator-os create \
  --creator stacey \
  --intent passive_selfie \
  --count 3 \
  --execution cloud \
  --accounts bennett_s33 \
  --audio embedded_trending

scripts/creator-os generate --mode library_reuse --apply \
  --folder /path/to/media --campaign campaign_slug --model model_slug

scripts/creator-os generate --list-modes

scripts/creator-os generate --mode soul_static --dry-run \
  --campaign campaign_slug --accepted-still /path/to/accepted.png

scripts/creator-os review --campaign campaign_slug --user-id user_id

scripts/creator-os export --dry-run \
  --campaign campaign_slug --user-id user_id --max-drafts 10
```

Library reuse never exports and disables auto-approval. `draft-export` forces
draft schedule mode; `--apply` may write validated drafts but cannot schedule
or publish.

Ordinary production uses `create --creator --intent --count --execution`; it
does not expose the provider, model, recipe, source path, seed, task ID, Arena,
or Router. The older mode catalog remains the advanced/manual generation
surface for library, still, and research workflows.
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
accepted stills, and a pinned operator-approved Higgsfield Kling 3 or Seedance
2 passive recipe. Normal `create` cannot select WaveSpeed or local Wan and has
no paid-provider fallback. Paid execution requires opt-in, an internally
resolved explicit Soul ID, a finite native-credit cap, and a machine-local
`CREATOR_OS_SPEND_AUTH_SECRET`. Campaign Factory owns provider quotes, balance
and budget policy, reservations, and the authoritative cost ledger. Reel
Factory receives a short-lived one-time signed authorization and records only
worker execution evidence; invoking its paid modes directly fails closed.

Higgsfield spend is denominated in native credits. Every request binds the
exact provider model/tool, prompt hash, media hashes, duration, resolution,
seed, quote, and authorization. Provider soundtrack is disabled. Audio Radar
then selects and embeds a live cached track and binds its receipt to the exact
final MP4 SHA. Exact supplied-voice talking and motion-copy fail with precise
unresolved-capability errors before provider submission. No motion command
schedules or publishes.

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
HMAC signing is the draft-ingest boundary. Campaign Factory owns the verified
embedded-audio binding for the normal finished-Reel path. ThreadsDashboard
validates the declared audio policy and exact completed media, then owns final
account approval, schedule, publish, and analytics. Native platform audio
remains a separate explicit policy.

The pinned performance launcher imports bounded post metric history and invokes
`scripts/learning_fanout.py`. Real learning proof requires real platform rows;
command success alone is not sufficient.

`scripts/creator-os learning-refresh --dry-run|--apply` reuses the versioned
Reference knowledge pack and stores creator/account/intent/age-scoped measured
recommendations. `learning-review` is the only activation surface. Normal
intent-first `create` consults the current pack automatically, applies only an
operator-approved `SUPERVISED_ACTIVE` match, and records whether approved source
or prompt ordering actually changed. With no valid match, create keeps the
existing deterministic behavior.

## Test

```bash
uv run python -m pytest python_packages/campaign_factory/tests
uv run python -m pytest tests/integration
```

Safety coverage includes paid credit lifecycle, provider failures, global kill
switch, QC/readiness, lineage, state transitions, draft export/HMAC, poisoned or
ambiguous data, and performance-learning seams.
