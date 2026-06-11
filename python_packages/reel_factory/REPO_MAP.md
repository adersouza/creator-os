# Repo Map

## `/Users/adercialonedesouza/Projects/reel_factory`

Primary role: creative generation and local asset production.

Important files:

- `/Users/adercialonedesouza/Projects/reel_factory/generate_prompts.py`: Grok/Gemini prompt generation, prompt cleanup, prompt lineage.
- `/Users/adercialonedesouza/Projects/reel_factory/asset_prompt_contract.py`: prompt contract parser/shape for Higgsfield and Kling prompt fields.
- `/Users/adercialonedesouza/Projects/reel_factory/generate_assets.py`: Higgsfield CLI orchestration for Soul ID images and Kling videos.
- `/Users/adercialonedesouza/Projects/reel_factory/grid_crop.py`: GridCropperV2 seam-aware panel cropper.
- `/Users/adercialonedesouza/Projects/reel_factory/reel_gui.py`: local FastAPI GUI and generation/fanout/posting-ledger endpoints.
- `/Users/adercialonedesouza/Projects/reel_factory/static/app.js`: local GUI client.
- `/Users/adercialonedesouza/Projects/reel_factory/reel_pipeline.py`: render pipeline.
- `/Users/adercialonedesouza/Projects/reel_factory/qc_check.py`: QC checks.
- `/Users/adercialonedesouza/Projects/reel_factory/export_approved.py`: approved export manifest generation.
- `/Users/adercialonedesouza/Projects/reel_factory/audio_provider.py`: AudioProviderV1 metadata selector.
- `/Users/adercialonedesouza/Projects/reel_factory/audio_refresh.py`: official CML/manual export importer.
- `/Users/adercialonedesouza/Projects/reel_factory/audio_intent.py`: output sidecar for audio intent/selection.
- `/Users/adercialonedesouza/Projects/reel_factory/posting_ledger.py`: account posting ledger and operator schedule package.
- `/Users/adercialonedesouza/Projects/reel_factory/campaign_store.py`: local manifest SQLite and campaign/generation state.

Important docs:

- `/Users/adercialonedesouza/Projects/reel_factory/AGENTS.md`
- `/Users/adercialonedesouza/Projects/reel_factory/docs/next_chat_reel_factory_handoff.md`
- `/Users/adercialonedesouza/Projects/reel_factory/docs/aspect_ratio_grid_decision.md`
- `/Users/adercialonedesouza/Projects/reel_factory/docs/audio_provider_v1.md`

## `/Users/adercialonedesouza/Projects/campaign_factory`

Primary role: campaign control brain.

Important files:

- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/config.py`: default sibling repo paths.
- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/control.py`: operator control checks across repos.
- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/core.py`: campaign DB operations, imports, recommendations, audio catalog/memory, readiness, exports, performance learning.
- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/db.py`: SQLite schema for assets, campaigns, creative plans, recommendations, audio, performance.
- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/app.py`: local FastAPI control-room API.
- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/cli.py`: CLI entrypoint.
- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/adapters/contentforge.py`: ContentForge audit adapter.
- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/adapters/threadsdash.py`: ThreadsDashboard/Supabase draft export adapter.

Key schemas:

- `/Users/adercialonedesouza/Projects/campaign_factory/schemas/campaign_draft_payload.v1.schema.json`
- `/Users/adercialonedesouza/Projects/campaign_factory/schemas/audio_intent.v1.schema.json`
- `/Users/adercialonedesouza/Projects/campaign_factory/schemas/audio_catalog_export.v1.schema.json`
- `/Users/adercialonedesouza/Projects/campaign_factory/schemas/performance_sync.v1.schema.json`

## `/Users/adercialonedesouza/Projects/contentforge`

Primary role: transform/variant path and audit engine.

Important files:

- `/Users/adercialonedesouza/Projects/contentforge/lib/variant-engine.js`: quality/difference presets and gates.
- `/Users/adercialonedesouza/Projects/contentforge/lib/pipeline.js`: FFmpeg transformation pipeline and candidate report builder.
- `/Users/adercialonedesouza/Projects/contentforge/lib/variant-pack.js`: batch variant-pack request normalization, scoring, and manifest.
- `/Users/adercialonedesouza/Projects/contentforge/lib/reels.js`: reel media validation.
- `/Users/adercialonedesouza/Projects/contentforge/lib/detector.js`: perceptual hash/similarity support.
- `/Users/adercialonedesouza/Projects/contentforge/lib/quality-metrics.js`: fast quality metrics.
- `/Users/adercialonedesouza/Projects/contentforge/lib/campaign-originality-audit.js`: Campaign Factory originality/readiness audit support.
- `/Users/adercialonedesouza/Projects/contentforge/app/api/variant-pack/route.js`: variant-pack API.
- `/Users/adercialonedesouza/Projects/contentforge/app/api/similarity/route.js`: similarity/originality audit API.

Variant presets:

- `quality`
- `light`
- `medium`
- `strong`
- `custom`

Variant-pack presets:

- `subtle`
- `balanced`
- `strong`

## `/Users/adercialonedesouza/Projects/ThreadsDashboard`

Primary role: product app, Supabase data, account UI, analytics, approvals, scheduling/publishing infrastructure.

Important Creator OS files:

- `/Users/adercialonedesouza/Projects/ThreadsDashboard/src/lib/campaignFactory.ts`: Campaign Factory client mapping.
- `/Users/adercialonedesouza/Projects/ThreadsDashboard/src/lib/campaignFactoryAudio.test.ts`: Campaign Factory audio contract coverage.
- `/Users/adercialonedesouza/Projects/ThreadsDashboard/api/_lib/handlers/posts/campaignFactoryAudio.ts`: Campaign Factory audio post handler.
- `/Users/adercialonedesouza/Projects/ThreadsDashboard/api/_lib/handlers/posts/campaignFactoryAudioEvents.ts`: audio event handler.
- `/Users/adercialonedesouza/Projects/ThreadsDashboard/api/_lib/handlers/posts/schedule.ts`: post scheduling handler.
- `/Users/adercialonedesouza/Projects/ThreadsDashboard/api/_lib/handlers/posts/publish.ts`: publish handler.
- `/Users/adercialonedesouza/Projects/ThreadsDashboard/api/_lib/handlers/auto-post/`: auto-post queue/control-plane code.
- `/Users/adercialonedesouza/Projects/ThreadsDashboard/src/services/autoPost/`: frontend/service auto-post code.
- `/Users/adercialonedesouza/Projects/ThreadsDashboard/docs/META_COMPLIANCE_VERIFICATION_2026.md`: Meta compliance notes.

Boundary reminder: Creator OS work must not add private Instagram API automation or login automation here.

## `/Users/adercialonedesouza/Projects/pipeline_contracts`

Primary role: shared contract source.

Important files:

- `/Users/adercialonedesouza/Projects/pipeline_contracts/pipeline_contracts/schemas/generated_asset_lineage.v1.schema.json`
- `/Users/adercialonedesouza/Projects/pipeline_contracts/pipeline_contracts/schemas/higgsfield_soul_image_prompt.v1.schema.json`
- `/Users/adercialonedesouza/Projects/pipeline_contracts/pipeline_contracts/schemas/kling_3_video_prompt.v1.schema.json`
- `/Users/adercialonedesouza/Projects/pipeline_contracts/pipeline_contracts/schemas/audio_intent.v1.schema.json`
- `/Users/adercialonedesouza/Projects/pipeline_contracts/pipeline_contracts/schemas/audio_catalog_export.v1.schema.json`
- `/Users/adercialonedesouza/Projects/pipeline_contracts/pipeline_contracts/schemas/campaign_draft_payload.v1.schema.json`
- `/Users/adercialonedesouza/Projects/pipeline_contracts/pipeline_contracts/schemas/performance_sync.v1.schema.json`
- `/Users/adercialonedesouza/Projects/pipeline_contracts/pipeline_contracts/validator.py`
- `/Users/adercialonedesouza/Projects/pipeline_contracts/typescript/index.ts`

## `/Users/adercialonedesouza/Projects/ig-pipeline`

Observed current content:

- `/Users/adercialonedesouza/Projects/ig-pipeline/.planning/`
- `/Users/adercialonedesouza/Projects/ig-pipeline/data/profiles/.gitkeep`
- `/Users/adercialonedesouza/Projects/ig-pipeline/docs/.gitkeep`
- `/Users/adercialonedesouza/Projects/ig-pipeline/scripts/check_root.sh`

No current production Creator OS implementation responsibility was found.
