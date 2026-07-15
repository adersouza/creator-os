# Repo Map

## `/Users/aderdesouza/Developer/reel_factory`

Primary role: creative generation and local asset production.

Important files:

- `generate_assets.py`: active direct reference-image Higgsfield still generation; legacy prompt-json image/video wrappers.
- `reel_motion_prompt.py`: deterministic Kling motion prompts for accepted stills.
- `reference_video_remix.py`: dry-run planner for an operator-selected one-shot
  reference video, paired Higgsfield Soul endpoint frames, and deterministic
  Seedance/Kling routing.
- `operator_tools.py`: headless direct-reference and operator utilities.
- `asset_prompt_contract.py`: prompt contract parser/shape for legacy prompt-json flows.
- `generate_prompts.py`: legacy Grok/reference prompt generation and regression support.
- `grid_crop.py`: legacy grid crop/fanout helpers for explicit experiments.
- `reel_pipeline.py`: render pipeline.
- `qc_check.py`: QC checks.
- `export_approved.py`: approved export manifest generation.
- `audio_provider.py`: AudioProviderV1 metadata selector.
- `audio_refresh.py`: official CML/manual export importer.
- `audio_intent.py`: output sidecar for audio intent/selection.
- `posting_ledger.py`: account posting ledger and operator schedule package.
- `campaign_store.py`: local manifest SQLite and campaign/generation state.

Important docs:

- `AGENTS.md`
- `SYSTEM_OVERVIEW.md`
- `CURRENT_PRODUCTION_FLOW.md`
- `PIPELINE_BOUNDARIES.md`
- `DO_NOT_CHANGE.md`
- `docs/next_chat_reel_factory_handoff.md`

## `/Users/aderdesouza/Developer/campaign_factory`

Primary role: campaign control brain.

Important files:

- `campaign_factory/config.py`: default sibling repo paths.
- `campaign_factory/control.py`: operator control checks across repos.
- `campaign_factory/core.py`: campaign DB operations, imports, recommendations, readiness, exports, performance learning.
- `campaign_factory/db.py`: SQLite schema for assets, campaigns, creative plans, recommendations, audio, performance.
- `campaign_factory/app.py`: local FastAPI control-room API.
- `campaign_factory/cli.py`: CLI entrypoint.
- `campaign_factory/adapters/contentforge.py`: ContentForge audit adapter.
- `campaign_factory/adapters/threadsdash.py`: ThreadsDashboard/Supabase draft export adapter.
- `repurposer/`: isolated experimental module promoted from monorepo; not wired into scheduling/publishing/inventory.

## `/Users/aderdesouza/Developer/contentforge`

Primary role: transform/variant path and audit engine.

Important files:

- `lib/variant-engine.js`: quality/difference presets and gates.
- `lib/pipeline.js`: FFmpeg transformation pipeline and candidate report builder.
- `lib/variant-pack.js`: resumable variant-pack request normalization, scoring, and manifest.
- `app/api/variant-pack/route.js`: variant-pack API.
- `app/api/similarity/route.js`: similarity/originality audit API.

## `/Users/aderdesouza/Developer/ThreadsDashboard`

Primary role: product/data layer.

Important areas:

- `src/lib/campaignFactory.ts`: Campaign Factory payload mapping.
- `api/_lib/handlers/posts/`: posts, scheduling, publishing handlers.
- `api/_lib/handlers/auto-post/`: auto-post infrastructure.
- `src/services/autoPost/`: auto-post services.
- `api/go/[code].ts`: smart-link redirect/interstitial route.

## `/Users/aderdesouza/Developer/creator-os/packages/pipeline_contracts`

Primary role: shared schemas and validators.

Important areas:

- `packages/pipeline_contracts/pipeline_contracts/schemas/`
- `packages/pipeline_contracts/pipeline_contracts/validator.py`
- `packages/pipeline_contracts/typescript/index.ts`

## `/Users/aderdesouza/Developer/reference_factory`

Primary role: reference review, learning sets, pattern cards, audio snapshots, and campaign reference bank exports.

## `/Users/aderdesouza/Developer/creator-os`

Primary role: repaired monorepo import and reconciliation workspace.

Do not treat it as the deployable runtime baseline until split repos are intentionally merged/reconciled.
