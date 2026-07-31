# Creator OS Agent Notes

This monorepo is the Creator OS runtime source for Campaign Factory, Reel
Factory, Reference Factory, ContentForge, Pipeline Contracts, local docs, and
local generated evidence. ThreadsDashboard remains an external repo and is the
dashboard production source unless the user explicitly changes that boundary.

## Runtime Status

`creator-os/main` is the CI-green integration baseline for Creator OS local
pipeline code. A non-mutating staged acceptance run from the monorepo path
against a copied Campaign Factory SQLite database certified the 25-account gate
and blocked the 50-account gate on inventory buffer only.

Do not promote production deployments or scheduling/publishing behavior from
this repo without an explicit deployment instruction.

## Current Runtime Truth

- `reel_factory`: active creative generation path is direct Higgsfield reference-image generation, not Grok/grid.
- `campaign_factory`: campaign control brain, readiness, inventory, learning, draft export.
- `contentforge`: repurposing/distinctness + quality gate. It has legacy/advanced
  FFmpeg variant and capture-metadata tooling, but Campaign Factory's default use
  is detect-and-block: PDQ/SSCD collision checks, sibling distinctness,
  readability, safe-zone, and watchability gates. Do not add platform-avoidance
  behavior during safety, docs, or pipeline work.
- `ThreadsDashboard`: product UI, Supabase data, drafts, scheduling, publishing infrastructure, analytics.
- `pipeline_contracts`: shared schemas and validators.
- `reference_factory`: reference review, gold learning set, pattern/audio exports.

## Current Creative Product Decision

The operator reviewed the real paid-motion bakeoff on 2026-07-26. Treat this
human would-post decision as the creative source of truth until the operator
explicitly reopens model evaluation:

- Higgsfield Kling 3 and Higgsfield Seedance 2 are the only accepted passive
  selfie-motion candidates.
- WaveSpeed Kling O3 Pro and Vidu Q3 Pro are rejected for production quality.
- The tested Higgsfield and WaveSpeed Kling Motion Control recipes are rejected.
  Motion copy itself remains unresolved, not permanently closed. Do not use
  either rejected output as a lip-sync base.
- WaveSpeed InfiniteTalk is rejected because the voice sounded robotic and the
  result was not postable.
- Higgsfield Veo 3.1 produced no reviewable output. There is no accepted talking
  or motion-copy recipe.
- LongCat and Sync Lipsync 2/3 remain unselected, not defaults. Do not run them
  merely to complete a matrix.
- Wan/LTX and the Arena/Router research surfaces are not active production
  defaults.

Do not average technical scores over the operator's would-post judgment. The
supported creative scope is Soul still/static Reel plus explicitly authorized
passive motion using one of the two accepted Higgsfield candidates. Talking,
motion-copy, dance transfer, and talking-motion-copy are UNRESOLVED production
intents unless an authenticated contract and later operator-approved bakeoff
change this decision.

## Contract Ownership

`packages/pipeline_contracts/pipeline_contracts/schemas` is the ONLY hand-edited
source for shared schemas. The generated TypeScript bundle lives at
`packages/pipeline_contracts/typescript/generated-schemas.ts`. Python imports
resolve directly to the uv workspace package; there is no root-level shim. The
compiled `@creator-os/pipeline-contracts` tarball is the only supported
ThreadsDashboard consumer artifact.

Workflow for ANY schema/contract change:
1. Edit only `packages/pipeline_contracts/pipeline_contracts/schemas/<name>.schema.json`.
2. Run `pnpm sync:contracts` — regenerates TypeScript from the canonical schemas.
3. Run `pnpm check:contracts` to verify (this is what CI's `contracts` job enforces).

NEVER hand-edit generated TypeScript — `pnpm sync:contracts` overwrites it and
`pnpm check:contracts` (CI) fails on drift. Release a reviewed package tag after
merging a contract change, then update ThreadsDashboard's pinned tarball URL and
lockfile integrity. Never copy schemas or TypeScript into ThreadsDashboard.

## Tooling And PR Safety

- One command verifies everything locally, mirroring CI: `make verify` (static
  gates + all test suites) or `pnpm check:all` (static gates only: contracts,
  ruff lint/format, mypy, contentforge eslint, arch boundaries, artifacts). Run
  one of these before pushing instead of guessing which individual check to run.
- Use GitHub Actions logs/checks before guessing at PR failures.
- CodeQL and TruffleHog run from `.github/workflows/security.yml`.
- Use `pnpm security:secrets` for local secret scanning when `gitleaks` or
  `trufflehog` is installed.
- Use `pnpm check:artifacts` before committing tooling or generated-output
  changes.
- Use `pnpm check:arch` before merging changes that cross app/package
  boundaries. It runs dependency-cruiser for TypeScript and import-linter for
  Python.
- See `docs/architecture/tooling_hardening.md` for dependency-update, Sentry,
  and Graphify operating rules. Dashboard visual regression belongs upstream in
  ThreadsDashboard.
- See `docs/architecture/github_protection_settings.md` for GitHub rulesets,
  merge queue, protected environments, and Secret Protection settings that must
  be configured outside the repo.

## Graphify

If `graphify-out/graph.json` exists and the task is an architecture or
codebase-relationship question, query Graphify before broad source browsing:

```bash
graphify query "How does Campaign Factory hand off to ThreadsDashboard?"
```

Run `pnpm graphify:update` after code changes. `graphify-out/` is local
architecture output and must not be committed unless explicitly approved.

## Creator OS Product Modes

`creator-os create` exposes exactly three product modes:

1. `static_reel` — deterministic static MP4 from an approved creator still;
2. `calm_animation` — OpenAI-authored calm motion prompt with pinned Kling or
   Seedance production behavior;
3. `recreate_reel` — analyze one authorized Reel and build the creator-specific
   Soul anchor and model-specific recreation prompt.

Library reuse is automatic and fail-closed before new generation: only exact
approved, audited, creator/intent-matched MP4s with verified bytes and required
audio are eligible. Local models and retired advanced generation modes are not
Creator OS product surfaces. Provider/model identifiers remain internal.

## Reel Factory Active Path

```text
single-person reference image
→ Higgsfield direct reference-image still
→ Campaign-selected Stacey, Larissa, or Lola Soul ID
→ one 9:16 still
→ captured Higgsfield prompt + lineage
→ optional append-only body emphasis
→ accepted still
→ local static MP4, or explicitly authorized Higgsfield Kling 3/Seedance 2
  passive animation
→ technical QC + operator would-post review
→ Audio Radar track/segment selection and verified AAC embedding
→ final MP4 SHA bound to Campaign and audio receipts
→ validated draft handoff
```

Grok, Qwen/Ollama/Florence, visual-schema, grids, cropped panels, and `_grok.json` are legacy/experimental unless explicitly requested.

### Higgsfield UI Artifact Salvage

Do not automatically throw away a strong Stacey/Larissa generation just because
Higgsfield added fake Instagram/story/app chrome around the edges. If the
subject, face, pose, and setting are good and the UI is confined to cropable
margins, make a non-destructive `__cropped_clean` derivative and use that file
for static MP4, Kling, Reel Factory, and review boards. Preserve the original
for audit/reference.

Reject only when UI/text covers the face, body focal area, hands, or the crop
would ruin the composition. Never feed a UI-laden original into Reel Factory
when a clean cropped derivative exists.

### Higgsfield Prompt UI Trigger Rule

For creator/Soul text prompts, do not mention app/UI concepts, even as negatives.
Avoid `phone`, `iPhone`, `smartphone`, `story`, `screenshot`, `social media`,
`interface`, `icons`, `watermark`, `caption`, `overlay text`, and "for later
text" wording. If room for future Reel Factory captions is needed, say "clean
open area in the composition" rather than naming text or overlays.

If a run adds fake UI, inspect the saved `.higgsfield.json` prompt before
retrying and remove the triggering words first. Do not keep repeating the same
prompt shape and hoping the next seed fixes it.

### Low-Effort Reel Visual Direction

For Soul stills intended for `static_reel` or generic `calm_animation`, default
to an intentionally casual, believable handheld selfie rather than a polished
editorial image:

- close arm-length selfies and mirror self-portraits;
- ordinary bedrooms, bathrooms, cars, couches, living rooms, balconies, or
  simple outdoor settings;
- cute fitted everyday tops, tanks, tees, hoodies, dresses, gym sets, shorts,
  or skirts;
- playful, coy, pouty, warm, or teasing expressions and attractive,
  flirtatious poses within the approved wardrobe/exposure policy;
- natural household or window light, slight off-center framing, mild snapshot
  imperfection, and lived-in background detail.

Selected static mirror compositions may place the handheld camera in front of
part of the face when enough identity evidence remains visible. Keep the words
`phone`, `iPhone`, and app/UI language out of Higgsfield prompts; describe this
as "the camera held in front of part of the face." If that composition is not a
safe motion anchor, use it as a locked `static_reel` instead of forcing
animation. Overlay copy remains a separate Reel Factory step and never belongs
in the Higgsfield prompt.

### Reference → Soul Variant Generation (Original + Sexy)

Settled house recipe for turning one reference image into postable
Stacey/Stacey1 stills. Do NOT re-derive this each session.

1. **Crop the reference UI-free first** — status bar AND bottom nav. Leftover
   chrome makes Higgsfield render fake app UI (see "Higgsfield UI Artifact
   Salvage"). For a media-centric screenshot (black bars / phone bezel around the
   photo), `reel_factory/generate_variants.py autocrop_reference()` trims them by
   brightness; pass `bottom_trim` for a video timer/mute overlay sitting on the
   photo. A full profile screenshot must first be cropped to the post region.
2. **Pass 1 — reference-conditioned:** Soul V2 (`model soul_2`) with `medias`
   role `image` (the crop) + the creator `soul_id`. A reference image ALWAYS
   force-enhances; `enhance_prompt` is not toggleable on Soul 2.0. Higgsfield
   rewrites the prompt from the image and **discards any text you pass**, so you
   cannot inject a body/sexy edit here. Capture the returned `params.prompt` —
   that is the composition description.
3. **Clean the captured prompt:** strip identity descriptors (hair color,
   ethnicity, piercings — they fight the Soul) and every UI/screenshot word (see
   "Higgsfield Prompt UI Trigger Rule").
4. **Original variant** = the Pass-1 output.
5. **Sexy variant** = cleaned prompt + append-only body emphasis, regenerated
   **TEXT-ONLY** (no `medias`) + `soul_id`. Text-only does NOT force-enhance, so
   the edit sticks and no UI leaks; composition is preserved by the detailed
   captured text. Regenerating WITH the reference image re-enhances and wipes the
   edit — that is why this step must be text-only.
6. Both variants → `reel_factory/virality_select.py` predict-and-select → post
   the winner (per-post approval required; never auto-publish).

**Body-emphasis ceiling (house style):** spicy/implied — bikini/lingerie, more
skin, teasing, NO explicit nudity. Amp EXACTLY two things and nothing else:
fuller chest/cleavage and rounder butt. Adding pose/expression/lighting/extra
descriptors degrades Soul V2 quality — keep scene/pose/outfit/light identical to
the original.

**Aspect ratio per shot:** portrait/selfie/close-up `3:4`; full-body
(legs/butt visible) `2:3`; reels/stories `9:16`.

**Soul IDs (verify against Higgsfield `show_characters` before trusting):**
Stacey `d63ea9c7-b2c7-439c-bf0c-edfdf9938a36`, Stacey1
`5828d958-91dd-4d6d-8909-934503f47644`, Larissa
`44326567-b12c-410c-95b7-31891bb0629b`, Lola
`4c86c548-7aa5-4ad1-bc03-b94aa4ce8385`. Campaign Factory must pass the
selected Soul ID explicitly to Reel Factory; still confirm it against
Higgsfield before a paid run.

## Reel Captions, Overlay Text, And Fonts (Source Of Truth)

Do not relearn or invent these each task. Read this section, then the named files.

- **Burned overlay text** = visible text inside the MP4. Reel Factory owns it.
  **Post caption** = the Instagram caption under the post. Campaign Factory /
  ThreadsDashboard own it. Never confuse the two.
- **Default / canonical font is `Instagram Sans Condensed`** (Bold variant for
  meme-style high-contrast frames). Allowed font set is defined in
  `python_packages/reel_factory/recipe_loader.py`. Font files live in
  `python_packages/reel_factory/fonts/` (`InstagramSansCondensed-Regular.woff2`,
  `InstagramSansCondensed-Bold.woff2`). Do not substitute another font unless the
  user explicitly asks.
- **Placement is decided by `placement.py`, NEVER by hand.** It samples frames,
  scores face/body/text-safe zones, picks a safe caption lane + style + font
  (stddev → style; falls back to `("top", "ig", "Instagram Sans Condensed")`),
  and emits a `captionPlacementDecision` (`placement_scorer.py`) carried in the
  asset lineage and consumed by Campaign Factory (`reel_factory_reports.py`).
  Hard rules:
  - If overlay text is burned, it MUST go through `placement.py` →
    `caption_render.py`. Never choose x/y by eye, never burn with raw Pillow,
    never patch placement metadata after a manual render.
  - No manual x/y unless `placement.py` explicitly returns that position.
  - **No safe lane found → do NOT force overlay.** Ship the still clean and put
    the hook in the post caption, or regenerate a still with negative space.
    A centered face/body with no negative space is a no-overlay outcome, not a
    "guess somewhere" outcome.
  - An asset missing a valid `captionPlacementDecision` is not review-ready —
    Campaign Factory must reject it or keep it in review.
- **Stacey/Larissa Instagram reel style is a special preset, not generic
  safe-zone placement.** The observed account format is static/near-static
  selfie imagery with engagement-bait overlay text near the visual center but
  below the face. For Stacey/Larissa caption-bank renders, use Reel Factory's
  `--creator-style-preset stacey_static_center` behavior: static image MP4s stay
  locked still, overlay text defaults to `lower_center`, Instagram Sans
  Condensed, white text with black stroke/shadow, no background plate. Timed
  captions alternate only inside the lower-center family
  (`lower_center`/`lower_center_alt`). Never place a Stacey/Larissa overlay on
  the face; if the lower-center family cannot fit, ship the clean MP4 and put
  the hook in the post caption.
- **Overlay text comes from the caption bank, never freehand and never the
  Higgsfield prompt text.** Source: `python_packages/reel_factory/caption_banks/`
  (`banks.json` = hooks with `caption_hash` + bank membership, `mixes.json` =
  per-creator weights Larissa/Stacey/Lola, `performance.json` = perf metadata).
  Selection/rotation logic: `caption_bank.py`; rendering: `caption_render.py`;
  fit-to-frame: `caption_scene_fit.py` (`reel_pipeline.py --caption-fit auto`).
- **The normal finished-Reel path embeds verified trending audio.** Campaign
  Factory selects an Audio Radar track and duration-compatible segment, embeds
  AAC after the visual render, verifies the streams, and binds the audio
  receipt to the exact final MP4 SHA. ThreadsDashboard publishes that completed
  MP4 unchanged. Native platform audio remains a separate explicitly selected
  policy; do not describe an embedded-audio Reel as native audio.

## Durable System Map

If the architecture gets confusing, update `CREATOR_OS_SYSTEM_MAP.md` first.
Short version: Reference Factory teaches, Reel Factory creates, Campaign Factory
decides, ContentForge judges/blocks, Pipeline Contracts validate, and
ThreadsDashboard publishes.

## Do Not Touch During Docs/Integration Work

- Scheduling
- Publishing
- QStash
- Account health
- Metrics sync
- Production inventory state
- ThreadsDashboard runtime posting paths
