# Creator OS System Overview

Purpose: give a new Codex session the operational map of Creator OS / Reel Factory in under 5 minutes.

## Current Truth As Of 2026-06-13

Reel Factory's active operator path is now:

```text
single-person reference image
→ Higgsfield direct reference-image still
→ Stacey Soul ID
→ one 9:16 still
→ captured Higgsfield prompt + lineage
→ optional append-only body emphasis
→ human/QC accepted still
→ deterministic Kling motion prompt
→ Kling image-to-video only when explicitly requested
→ stop before Campaign Factory registration
```

Grok, Qwen/Ollama/Florence, visual-schema, grid/fanout, cropped panels, and `_grok.json` are legacy/experimental for normal generation.

## Active Repo Paths

The active split repos on this machine are under `/Users/aderdesouza/Developer`.

- `reel_factory`: direct reference-image still generation, Higgsfield/Soul ID image jobs, Kling prompt handoff, render/QC/export sidecars, audio metadata selection, local posting ledger.
- `campaign_factory`: control brain for campaign batches, local campaign database, ContentForge audit orchestration, draft export to ThreadsDashboard/Supabase, performance learning.
- `contentforge`: transform/variant engine, FFmpeg processing, similarity/originality/readiness audit APIs.
- `ThreadsDashboard`: product app, account/data UI, Supabase-backed drafts, analytics, approvals, scheduled/auto-posting infrastructure.
- `pipeline_contracts`: shared JSON schemas and validators for payloads that move between repos.
- `reference_factory`: reference review, gold learning sets, pattern/audio learning exports.
- `creator-os`: repaired monorepo import branch; useful for reconciliation, not the deployable runtime baseline yet.

## Responsibility Split

Reel Factory owns creative asset creation:

- `generate_assets.py`: active direct reference-image still generation plus legacy prompt-json image/video flows.
- `reel_motion_prompt.py`: deterministic Kling prompt compiler for accepted stills.
- `asset_prompt_contract.py`: prompt contract parser/shape for legacy prompt-json flows.
- `generate_prompts.py`: legacy prompt generation and compatibility tests.
- `operator_tools.py`: reusable headless direct-reference and operator utilities.
- `reel_pipeline.py`, `qc_check.py`, `export_approved.py`: render, QC, and approved export sidecars.
- `audio_provider.py`, `audio_refresh.py`, `audio_intent.py`: audio metadata selection and sidecars.

Campaign Factory owns campaign control and learning:

- Settings and repo discovery in `campaign_factory/config.py`.
- Control-room checks in `campaign_factory/control.py`.
- Campaign state, recommendations, audio memory, performance learning, readiness, and exports in `campaign_factory/core.py`.
- ContentForge and ThreadsDashboard adapters in `campaign_factory/adapters/`.

ContentForge owns transform quality and originality audits.

ThreadsDashboard owns the product/data layer, draft storage, approvals, schedules, publishing infrastructure, and analytics.

Pipeline Contracts owns shared schemas and validators.

## Current Production Flow At A Glance

```text
reference image
  -> Reel Factory direct Higgsfield reference-image still
  -> Soul ID identity, 9:16, optional append-only body emphasis
  -> human/QC accepted still
  -> deterministic Kling prompt when video is requested
  -> Reel Factory render/QC/audio intent/approved export
  -> Campaign Factory imports/assigns/audits/exports draft payloads
  -> ThreadsDashboard stores drafts, approvals, schedules, analytics, and performance
```

## Things Future Codex Sessions Must Not Break

- Active still generation is direct reference-image Higgsfield generation.
- Active still aspect ratio is `9:16`.
- Stacey Soul ID is `d63ea9c7-b2c7-439c-bf0c-edfdf9938a36`.
- Do not make Grok/Qwen/Ollama/Florence the default path again.
- Do not reintroduce grid/cropped-panel language into active operator surfaces.
- Campaign Factory remains the control brain.
- No Instagram private API automation, login automation, or unauthorized publishing automation.
