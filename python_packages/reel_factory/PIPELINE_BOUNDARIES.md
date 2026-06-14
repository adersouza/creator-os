# Pipeline Boundaries

This file documents what each system may do and what it must not do.

## Reel Factory Boundary

Allowed:

- Use local single-person reference images to create one direct Higgsfield Soul ID still.
- Pass the reference image to Higgsfield still generation through the active direct-reference path.
- Use Stacey Soul ID for Stacey identity.
- Default active stills to `9:16`.
- Capture Higgsfield raw JSON, generated prompt, local output path, and lineage.
- Append optional body emphasis only when requested.
- Compile deterministic Kling motion prompts for accepted stills.
- Run Kling only when explicitly requested.
- Write local prompt, generation, motion, QC, and export lineage.
- Select audio metadata from local CML/winner/watch-list caches.

Not allowed:

- Do not use Grok, Qwen, Ollama, Florence, or visual-schema extraction as the normal operator path.
- Do not make prompt-json or grid/fanout workflows the default production path.
- Do not use stale `2x3`, six-panel, cropped-panel, or `_grok.json` language in active operator surfaces.
- Do not automate Instagram/TikTok/Threads logins, private APIs, or publishing.
- Do not scrape logged-in Creative Center pages for audio.
- Do not register Campaign Factory assets, schedule, publish, export drafts, sync metrics, or mutate account health from this still-image flow.

Legacy:

- Old Grok/grid/fanout modules may remain for explicit research or regression tests only.

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
- Do not move Reel Factory generation behavior into ThreadsDashboard.

## Pipeline Contracts Boundary

Allowed:

- Define shared JSON schemas and validators.
- Add optional fields with compatibility.
- Validate Campaign Factory, Reference Factory, Reel Factory, and ThreadsDashboard payloads.

Not allowed:

- Do not put business logic in schemas.
- Do not silently change schema IDs for breaking changes.
- Do not treat stale vendored copies as authoritative over `$CREATOR_OS_ROOT/pipeline_contracts`.

## Things Future Codex Sessions Must Not Break

- Active still generation is direct reference-image Higgsfield generation.
- Active still aspect ratio is `9:16`.
- Soul ID owns identity.
- Do not make Grok/Qwen/Ollama/Florence the default path again.
- Do not reintroduce grid/cropped-panel language into active operator surfaces.
- Campaign Factory remains the control brain.
- No Instagram private API automation.
