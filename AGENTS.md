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

`packages/pipeline_contracts` is the canonical source for shared schemas,
Python validators, and TypeScript exports inside this monorepo. Compatibility
copies under `pipeline_contracts/` and `python_packages/campaign_factory/schemas/`
must stay byte-for-byte synced with the package source. ThreadsDashboard
consumes contracts from its own external checkout/package path, not from a
Creator OS mirror path. Run `pnpm check:contracts` after any contract or payload
change.

## Tooling And PR Safety

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

### Higgsfield Reference Prompting Rule

If the user asks to recreate from a Twitter/X, Instagram, or local reference, the
reference media must be passed into Higgsfield as media. Do **not** switch to
text-only Soul prompting when a clean source image exists; that causes fake UI,
wrong framing, and recycled-looking generations.

Correct still command shape:

```bash
higgsfield --json generate create text2image_soul_v2 \
  --image "$CLEAN_REFERENCE_IMAGE" \
  --custom_reference_id d63ea9c7-b2c7-439c-bf0c-edfdf9938a36 \
  --aspect_ratio 9:16 \
  --quality 2k \
  --prompt "Use the attached image as composition reference only. Replace the person with the trained Stacey Soul character. Keep the pose, crop, camera distance, lighting, outfit category, and setting. Output a clean full-bleed vertical camera photo."
```

Prompt rules:

- Say "attached image" or "reference image"; do not describe the source from memory
  if the image can be attached.
- For Stacey/Soul text-only generations, do **not** use negative-prompt language.
  Do not write clauses like "no UI", "no text", "no watermark", "without
  interface", or long lists of forbidden artifacts. Soul ID often turns those
  words into fake app UI. Use positive camera/scene language only.
- Do not use generic "clean portrait" prompts for Stacey winners. The proven
  prompt shape is detailed positive camera language: adult woman in her mid-20s,
  close-up intimate camera portrait, low-angle or slightly elevated front-facing
  crop, dark bedroom/night setting, one warm yellow bedside lamp, clean
  low-light camera look, sharp face detail, natural skin texture, thick opaque
  low-cut top, deep cleavage/curvy silhouette, confident seductive expression,
  centered face and chest framing, moody amber shadows.
- If a Soul text-only run adds app/story UI, the retry should remove literal
  `phone`, `iPhone`, `smartphone`, and `selfie` tokens and keep the same look
  with positive wording like "clean intimate low-light camera portrait",
  "arm's-length front-facing portrait", "centered face and chest framing", and
  "soft warm lamp glow with sharp face detail".
- Do not dilute the genre into sterile fashion/editorial copy. Sensual cues such
  as seductive expression, cleavage, curvy silhouette, low-cut opaque top,
  bedroom lamp light, and intimate late-night phone-photo realism are part of the
  Stacey winning style.
- Keep all sexualized Stacey prompts adult-coded, e.g. "adult woman in her
  mid-20s"; do not use teen, barely-legal, schoolgirl, or minor-coded wording.
- For attached references, keep prompts concrete: pose, crop, lighting, outfit
  category, setting.
- For each strong reference, make a paired still set by default:
  1. `faithful`: the clean reference-driven prompt above.
  2. `amplified`: the same prompt plus one append-only body-emphasis clause, e.g.
     "Make the Stacey model version slightly more seductive with fuller cleavage,
     a more pronounced waist/hip curve, and stronger confident body pose, while
     preserving the original composition."
  Do not rewrite the whole prompt for the amplified pass; build on the same
  attached-image prompt so pose, crop, lighting, and setting stay locked.
- If the output adds UI/text anyway, reject it and try a different clean reference
  or model. Do not use social UI outputs as Reel Factory inputs.
- Stacey1 (`5828d958-91dd-4d6d-8909-934503f47644`) is an experimental fallback
  for specific failed Stacey generations, not the default.
- Never feed contact sheets, social screenshots, grids, thumbnails, or previous
  Higgsfield outputs as references unless the user explicitly asks for that.

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
  selfie imagery with engagement-bait overlay text near the visual center, but
  below the face and away from the main body focal point. For Stacey/Larissa
  caption-bank renders, use Reel Factory's `--creator-style-preset
  stacey_static_center` behavior: static image MP4s stay locked still, overlay
  text defaults to `lower_center`, Instagram Sans Condensed, white text with
  black stroke/shadow, no background plate. Timed captions should move slightly
  between beats inside this same lower-center family: `lower_center` first, then
  `center` only when the scorer says center is safe, otherwise
  `lower_center_alt`. Do not move these hooks to generic top/bottom lanes just
  because safe-zone scoring slightly prefers them.
- **Overlay text comes from the caption bank, never freehand and never the
  Higgsfield prompt text.** Source: `python_packages/reel_factory/caption_banks/`
  (`banks.json` = hooks with `caption_hash` + bank membership, `mixes.json` =
  per-creator weights Larissa/Stacey/Lola, `performance.json` = perf metadata).
  Selection/rotation logic: `caption_bank.py`; rendering: `caption_render.py`;
  fit-to-frame: `caption_scene_fit.py` (`reel_pipeline.py --caption-fit auto`).
- **Native/platform catalog audio is never burned into the MP4.** Campaign
  Factory recommends it via `audio_intent.v1`; ThreadsDashboard selects/verifies
  native audio. Explicitly licensed local audio may be muxed before publish only
  when the MP4 has matching `audio_intent.v1` evidence
  (`mode=licensed_music`, `selection_source=embedded_licensed_audio`, track id,
  license/source sidecar). Anything else stays blocked.

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
