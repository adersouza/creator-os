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
