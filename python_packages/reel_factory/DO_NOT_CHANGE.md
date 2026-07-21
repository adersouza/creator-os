# Do Not Change

These are the current hard rules for Reel Factory and Creator OS handoffs.

## Active Generation Invariants

- Active still-image generation uses `generate_assets.py reference-image` / `reference-image-dry-run`.
- The active path passes a single-person reference image to Higgsfield with `--image <reference>`.
- Stacey generations use Soul ID `d63ea9c7-b2c7-439c-bf0c-edfdf9938a36`.
- Active stills are `9:16`.
- Soul ID owns identity.
- Optional body emphasis is append-only: `none`, `bust`, or `bust_hips`.
- Do not rewrite Higgsfield's own reference-image prompt; only append approved body emphasis when requested.
- Kling video generation is off unless explicitly requested.
- Accepted stills use `reel_motion_prompt.py` for deterministic motion prompts.

## Legacy Paths

Do not make these the default operator path again:

- Grok final prompt writing.
- Qwen/Ollama/Florence visual-schema extraction.
- `visual-schema`, `grok-direct`, or `json-structured` prompt modes.
- Grid generation, `2x3`/six-panel outputs, cropped-panel fanout, or `_grok.json` prompt files.

The legacy execution files, empty experiments package, and grid-generation
guide are removed. Do not recreate them; explicit reference-analysis
experiments belong in Reference Factory and must remain isolated from the
direct reference-image generation path.

## Platform And State Boundaries

- Do not automate Instagram/private APIs/logins/publishing.
- Do not register Campaign Factory assets from the direct still-image flow unless explicitly requested.
- Do not schedule, publish, export ThreadDash drafts, sync metrics, mutate account health, or mutate production inventory from Reel Factory generation work.
- Keep Campaign Factory as the control brain for campaign decisions, readiness, draft export, and learning.

## Audio Rules

Allowed:

- Use `AudioProviderV1` metadata selection.
- Use official TikTok Commercial Music Library / Commercial Sounds exports or manually saved official lists.
- Refresh local CML cache from JSON/CSV drop folder.
- Track selected audio by stable `track_id`.

Not allowed:

- Do not scrape TikTok Creative Center pages.
- Do not automate TikTok login.
- Do not call private TikTok APIs.
- Do not build audio matching AI, beat sync, or a recommendation engine until audio is proven to be a bottleneck.
