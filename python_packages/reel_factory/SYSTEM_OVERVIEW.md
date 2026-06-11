# Creator OS System Overview

Purpose: give a new Codex session the operational map of Creator OS / Reel Factory in under 5 minutes.

## Active Repo Paths

The active checkouts on this machine are under `/Users/adercialonedesouza/Projects`.

- `/Users/adercialonedesouza/Projects/reel_factory`: image prompt generation, Higgsfield/Soul ID image jobs, grid crop fanout, Kling handoff, render/QC/export sidecars, audio metadata selection, local posting ledger.
- `/Users/adercialonedesouza/Projects/campaign_factory`: control brain for multi-repo campaign batches, local campaign database, ContentForge audit orchestration, draft export to ThreadsDashboard/Supabase, performance learning.
- `/Users/adercialonedesouza/Projects/contentforge`: transform/variant engine, FFmpeg processing, similarity/originality/readiness audit APIs.
- `/Users/adercialonedesouza/Projects/ThreadsDashboard`: product app, account/data UI, Supabase-backed drafts, analytics, approvals, scheduled/auto-posting infrastructure.
- `/Users/adercialonedesouza/Projects/pipeline_contracts`: shared JSON schemas and validators for payloads that move between repos.
- `/Users/adercialonedesouza/Projects/ig-pipeline`: currently a minimal planning/guard repo with `.planning/`, placeholder data/docs folders, and `/Users/adercialonedesouza/Projects/ig-pipeline/scripts/check_root.sh`; no production Creator OS implementation was found. Do not expand this into private Instagram automation.

Older handoff paths under `/Users/adercialonedesouza/Projects` are not present in this environment.

## Responsibility Split

Reel Factory owns creative asset creation:

- Grok image prompt creation in `/Users/adercialonedesouza/Projects/reel_factory/generate_prompts.py`.
- Higgsfield/Soul ID and Kling CLI orchestration in `/Users/adercialonedesouza/Projects/reel_factory/generate_assets.py`.
- Grid crop fanout in `/Users/adercialonedesouza/Projects/reel_factory/grid_crop.py`.
- GUI/API control surface in `/Users/adercialonedesouza/Projects/reel_factory/reel_gui.py`.
- Audio metadata selection in `/Users/adercialonedesouza/Projects/reel_factory/audio_provider.py` and `/Users/adercialonedesouza/Projects/reel_factory/audio_refresh.py`.
- Approved export and lineage sidecars in `/Users/adercialonedesouza/Projects/reel_factory/export_approved.py`, `/Users/adercialonedesouza/Projects/reel_factory/audio_intent.py`, and `/Users/adercialonedesouza/Projects/reel_factory/posting_ledger.py`.

Campaign Factory owns campaign control and learning:

- Settings and repo discovery in `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/config.py`.
- Control-room checks in `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/control.py`.
- Campaign state, recommendations, audio memory, performance learning, readiness, and exports in `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/core.py`.
- HTTP control surface in `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/app.py`.
- ContentForge and ThreadsDashboard adapters in `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/adapters/`.

ContentForge owns transform quality and originality audits:

- Variant presets and quality gates in `/Users/adercialonedesouza/Projects/contentforge/lib/variant-engine.js`.
- FFmpeg processing and candidate reports in `/Users/adercialonedesouza/Projects/contentforge/lib/pipeline.js`.
- Variant packs in `/Users/adercialonedesouza/Projects/contentforge/lib/variant-pack.js`.
- Similarity/originality/readiness endpoints under `/Users/adercialonedesouza/Projects/contentforge/app/api/`.

ThreadsDashboard owns the product/data layer:

- Campaign Factory payload mapping in `/Users/adercialonedesouza/Projects/ThreadsDashboard/src/lib/campaignFactory.ts`.
- Campaign Factory audio tests in `/Users/adercialonedesouza/Projects/ThreadsDashboard/src/lib/campaignFactoryAudio.test.ts`.
- Posts, schedule, publishing, and Campaign Factory audio handlers under `/Users/adercialonedesouza/Projects/ThreadsDashboard/api/_lib/handlers/posts/`.
- Auto-post infrastructure under `/Users/adercialonedesouza/Projects/ThreadsDashboard/api/_lib/handlers/auto-post/` and `/Users/adercialonedesouza/Projects/ThreadsDashboard/src/services/autoPost/`.

Pipeline Contracts owns shared schemas:

- Canonical schemas in `/Users/adercialonedesouza/Projects/pipeline_contracts/pipeline_contracts/schemas/`.
- Python validator in `/Users/adercialonedesouza/Projects/pipeline_contracts/pipeline_contracts/validator.py`.
- TypeScript exports in `/Users/adercialonedesouza/Projects/pipeline_contracts/typescript/index.ts`.

## Production Flow At A Glance

```text
reference image/reel
  -> Reel Factory sends reference to Grok/Gemini analysis only
  -> Grok writes final Higgsfield Soul image prompt
  -> removal-only prompt cleanup
  -> prompt JSON + Grok lineage sidecar
  -> Higgsfield Soul ID image grid, prompt enhancement off, no reference image passed
  -> GridCropperV2 seam-aware panel crops
  -> selected cropped panel becomes Kling start image when video is requested
  -> Reel Factory render/QC/audio intent/approved export
  -> Campaign Factory control brain imports/assigns/audits/exports draft payloads
  -> ThreadsDashboard stores drafts, approvals, schedules, analytics, and performance
```

## Things Future Codex Sessions Must Not Break

- Prompt enhancement stays off.
- No reference image is sent to Higgsfield image generation.
- Soul ID owns identity.
- Grok writes image prompts.
- Gemini is motion only.
- GridCropperV2 seam detection stays in the crop path.
- Campaign Factory remains the control brain.
- No Instagram private API automation, no login automation, and no unauthorized publishing automation.
