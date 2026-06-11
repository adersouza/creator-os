# Pipeline Boundaries

This file documents what each system may do and what it must not do.

## Reel Factory Boundary

Allowed:

- Build Grok prompt requests from local reference images/reels.
- Use Grok to write the final Higgsfield image prompt.
- Clean Grok prompt output with removal-only forbidden-term cleanup.
- Generate Higgsfield Soul ID image grids.
- Crop image grids into panel start images.
- Generate Kling video only when explicitly requested.
- Write prompt, generation, crop, audio, QC, and export lineage.
- Select audio metadata from local CML/winner/watch-list caches.

Not allowed:

- Do not pass the reference image to Higgsfield image generation.
- Do not enable Higgsfield prompt enhancement.
- Do not make Gemini write image prompts.
- Do not use image-prompt forbidden-term cleanup on Gemini/Kling motion text.
- Do not automate Instagram/TikTok/Threads logins, private APIs, or publishing.
- Do not scrape TikTok logged-in Creative Center pages for audio.

## Campaign Factory Boundary

Allowed:

- Act as the control brain over local repos.
- Import source videos and campaign assets.
- Call Reel Factory render/prepare flows.
- Call ContentForge audit APIs.
- Store campaign state, recommendations, readiness, audio catalog/memory, and performance snapshots.
- Export draft payloads to ThreadsDashboard/Supabase.
- Enforce readiness gates before live draft writes.

Not allowed:

- Do not become the image prompt compiler.
- Do not bypass Reel Factory lineage.
- Do not publish to social platforms directly.
- Do not replace ThreadsDashboard's app/data ownership.

Key files:

- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/core.py`
- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/control.py`
- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/adapters/contentforge.py`
- `/Users/adercialonedesouza/Projects/campaign_factory/campaign_factory/adapters/threadsdash.py`

## ContentForge Boundary

Allowed:

- Transform videos/images into variants.
- Run FFmpeg processing.
- Score quality, difference, similarity, readiness, forensics, compression, provenance, and temporal signals.
- Produce variant-pack manifests and audit reports for Campaign Factory.

Not allowed:

- Do not own campaign strategy.
- Do not decide final posting.
- Do not mutate Reel Factory prompt or Higgsfield lineage.

Key files:

- `/Users/adercialonedesouza/Projects/contentforge/lib/pipeline.js`
- `/Users/adercialonedesouza/Projects/contentforge/lib/variant-engine.js`
- `/Users/adercialonedesouza/Projects/contentforge/lib/variant-pack.js`
- `/Users/adercialonedesouza/Projects/contentforge/app/api/similarity/route.js`
- `/Users/adercialonedesouza/Projects/contentforge/app/api/variant-pack/route.js`

## ThreadsDashboard Boundary

Allowed:

- Store drafts, media, analytics, account state, approvals, schedules, and performance data.
- Provide product UI and Supabase-backed data services.
- Run official/approved platform integrations already implemented in the app.
- Receive Campaign Factory draft payloads.
- Feed performance data back to Campaign Factory.

Not allowed for Creator OS/Reel Factory work:

- Do not add private Instagram API automation.
- Do not add login automation.
- Do not bypass approval/idempotency/kill-switch publishing guardrails.
- Do not move Reel Factory prompt generation into ThreadsDashboard.

Key areas:

- `/Users/adercialonedesouza/Projects/ThreadsDashboard/src/lib/campaignFactory.ts`
- `/Users/adercialonedesouza/Projects/ThreadsDashboard/api/_lib/handlers/posts/`
- `/Users/adercialonedesouza/Projects/ThreadsDashboard/api/_lib/handlers/auto-post/`
- `/Users/adercialonedesouza/Projects/ThreadsDashboard/src/services/autoPost/`

## Pipeline Contracts Boundary

Allowed:

- Define shared JSON schemas and validators.
- Add optional fields with compatibility.
- Validate Campaign Factory, Reference Factory, Reel Factory, and ThreadsDashboard payloads.

Not allowed:

- Do not put business logic in schemas.
- Do not silently change schema IDs for breaking changes.
- Do not treat stale vendored copies as authoritative over `/Users/adercialonedesouza/Projects/pipeline_contracts`.

Key paths:

- `/Users/adercialonedesouza/Projects/pipeline_contracts/pipeline_contracts/schemas/`
- `/Users/adercialonedesouza/Projects/pipeline_contracts/pipeline_contracts/validator.py`
- `/Users/adercialonedesouza/Projects/pipeline_contracts/typescript/index.ts`

## ig-pipeline Boundary

Current observed repo content is minimal and non-production:

```text
/Users/adercialonedesouza/Projects/ig-pipeline/.planning/
/Users/adercialonedesouza/Projects/ig-pipeline/data/profiles/.gitkeep
/Users/adercialonedesouza/Projects/ig-pipeline/docs/.gitkeep
/Users/adercialonedesouza/Projects/ig-pipeline/scripts/check_root.sh
```

Treat this repo as non-authoritative for Creator OS production. Do not use planning notes here as a reason to build private Instagram automation.

## Things Future Codex Sessions Must Not Break

- Prompt enhancement off.
- No reference image sent to Higgsfield.
- Soul ID owns identity.
- Grok writes image prompts.
- Gemini motion only.
- GridCropperV2 seam detection.
- Campaign Factory control brain.
- No Instagram private API automation.
