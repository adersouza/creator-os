# Do Not Change

These are the current hard rules for Reel Factory and Creator OS handoffs.

## Active Generation Invariants

- Active still-image generation uses `generate_assets.py reference-image` / `reference-image-dry-run`.
- The active path passes a single-person reference image to Higgsfield with `--image <reference>`.
- Stacey, Larissa, and Lola generations use their distinct Campaign-selected
  pinned Soul IDs. Cross-creator substitution is forbidden.
- Active stills are `9:16`.
- Soul ID owns identity.
- Optional body emphasis is append-only: `none`, `bust`, or `bust_hips`.
- Do not rewrite Higgsfield's own reference-image prompt; only append approved body emphasis when requested.
- Paid video generation is off unless explicitly requested and authorized.
  Normal passive motion may use the product-pinned Higgsfield Kling 3 or
  Seedance 2 recipe; structural recreation uses Seedance 2 Fast only after its
  creator-matched anchor/Element review gates.
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

- Discover trends through SocialCrawl TikTok and optional Instagram.
- Treat Creative Center as optional best-effort enrichment only.
- Resolve selected TikTok music IDs through TikLiveAPI.
- Select a duration-compatible cached segment, embed verified AAC, and bind the
  exact segment and final MP4 hashes.
- Apply only supervised, publication-linked audio performance ranking.

Not allowed:

- Do not automate TikTok login or call private TikTok APIs.
- Do not treat provider failure or invalid empty results as valid absence.
- Do not invent historical audio attribution or replace exact embedded audio
  with an inferred native-platform selection.
