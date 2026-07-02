# Creator OS Agent Notes

This monorepo is a repaired import/reconciliation workspace. The deployable runtime baseline is still the split repos under `/Users/aderdesouza/Developer` unless the user explicitly promotes the monorepo.

## Promotion Status

`creator-os/main` is the CI-green source integration baseline. It is not yet
the production runtime source. A non-mutating staged acceptance run from the
monorepo path against a copied Campaign Factory SQLite database certified the
25-account gate and blocked the 50-account gate on inventory buffer only.

Do not promote production deployments from this repo without an explicit
deployment instruction. ThreadsDashboard is external to this repo and remains
the dashboard production source unless the user explicitly changes that.

## Current Runtime Truth

- `reel_factory`: active creative generation path is direct Higgsfield reference-image generation, not Grok/grid.
- `campaign_factory`: campaign control brain, readiness, inventory, learning, draft export.
- `contentforge`: repurposing/distinctness + quality gate. It has legacy/advanced
  FFmpeg variant and capture-metadata tooling, but Campaign Factory's default use
  is detect-and-block: PDQ/SSCD collision checks, sibling distinctness,
  readability, safe-zone, and watchability gates. Do not strengthen spoof/evasion
  behavior during safety, docs, or pipeline work.
- `ThreadsDashboard`: product UI, Supabase data, drafts, scheduling, publishing infrastructure, analytics.
- `pipeline_contracts`: shared schemas and validators.
- `reference_factory`: reference review, gold learning set, pattern/audio exports.

## Contract Ownership

`packages/pipeline_contracts/schemas` is the ONLY hand-edited source for shared
schemas. Everything else is a generated mirror, kept byte-for-byte in sync:
- `packages/pipeline_contracts/pipeline_contracts/schemas` (in-package runtime copy)
- `pipeline_contracts/schemas` (root compatibility copy)
- `python_packages/campaign_factory/schemas` (campaign_factory runtime gate, see `control.py`)
- `*/typescript/generated-schemas.ts` and the root `pipeline_contracts/typescript/index.ts`

Workflow for ANY schema/contract change:
1. Edit only `packages/pipeline_contracts/schemas/<name>.schema.json`.
2. Run `pnpm sync:contracts` — regenerates every mirror + TypeScript from canonical.
3. Run `pnpm check:contracts` to verify (this is what CI's `contracts` job enforces).

NEVER hand-edit a mirror directory — `pnpm sync:contracts` overwrites it and
`pnpm check:contracts` (CI) fails on drift. ThreadsDashboard consumes contracts
from its own external checkout, not from a Creator OS mirror path.

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

## Reel Factory Active Path

```text
single-person reference image
→ Higgsfield direct reference-image still
→ Stacey Soul ID d63ea9c7-b2c7-439c-bf0c-edfdf9938a36
→ one 9:16 still
→ captured Higgsfield prompt + lineage
→ optional append-only body emphasis
→ accepted still
→ deterministic Kling motion prompt
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

For Stacey/Soul text prompts, do not mention app/UI concepts, even as negatives.
Avoid `phone`, `iPhone`, `smartphone`, `story`, `screenshot`, `social media`,
`interface`, `icons`, `watermark`, `caption`, `overlay text`, and "for later
text" wording. If room for future Reel Factory captions is needed, say "clean
open area in the composition" rather than naming text or overlays.

If a run adds fake UI, inspect the saved `.higgsfield.json` prompt before
retrying and remove the triggering words first. Do not keep repeating the same
prompt shape and hoping the next seed fixes it.

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
`4c86c548-7aa5-4ad1-bc03-b94aa4ce8385`. `campaign_store.py`
`DEFAULT_CREATORS` now maps "Stacey" to `d63ea9c7-b2c7-439c-bf0c-edfdf9938a36`;
still confirm the soul_id against Higgsfield before a paid run.

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
- **Native audio is never burned into the MP4.** Campaign Factory recommends via
  `audio_intent.v1`; ThreadsDashboard selects/verifies native audio. Publishing
  is blocked until ThreadsDashboard has native-audio + publishability proof.

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
