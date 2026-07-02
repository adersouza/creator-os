# Creator OS System Map

This is the durable operator map. Keep this file aligned with `AGENTS.md`,
`creator_os_map.html`, and `ARCHITECTURE.md`.

## Repos

- `/Users/aderdesouza/Developer/creator-os`: Creator OS runtime source for
  Campaign Factory, Reel Factory, Reference Factory, ContentForge, Pipeline
  Contracts, docs, maps, and local generated evidence.
- `/Users/aderdesouza/Developer/ThreadsDashboard`: real dashboard product and
  runtime. Owns composer, drafts, native audio selection, scheduling,
  publishing, analytics, and Supabase runtime behavior.
- Creator OS has no committed `apps/dashboard` source mirror. Do not restore it.

## Components

- Reference Factory teaches: reference intake, winner DNA, pattern cards, audio
  catalog exports, measured outcome signals.
- Reel Factory creates: Higgsfield/Stacey stills, Kling or motion-edit videos,
  burned overlay text, caption rendering, readiness evidence.
- Campaign Factory decides: planning, account assignment, readiness, variation,
  quality gates, draft export, learning, execution proof.
- ContentForge judges and blocks: Campaign Factory uses it for PDQ/SSCD
  collisions, sibling distinctness, OCR safe zones, readability, watchability,
  and quality-floor evidence. Do not use safety work to strengthen spoofing or
  evasion behavior.
- Pipeline Contracts validate: shared JSON schemas and Python/TypeScript
  validators for cross-repo payloads.
- ThreadsDashboard publishes: operator UI, native audio proof, schedule,
  publish, publish proof, metrics, and feedback sync.

## Main Flow

```text
Reference Factory
  -> pattern cards / prompt packs / audio catalog
  -> Campaign Factory

Reel Factory
  -> guarded review package + generated_asset_lineage.v1 + audio_intent.v1
  -> Campaign Factory

Campaign Factory
  -> ContentForge campaign_factory_v1 audit + rendered_assets promotion
  -> passing draft payloads
  -> ThreadsDashboard

ThreadsDashboard
  -> operator review + native audio verification
  -> schedule/publish
  -> performance_sync.v1 back to Campaign Factory / Reference Factory
```

## Reel Text And Audio Rules

- Burned overlay text is visible text inside the video. Reel Factory owns it.
- Post captions are Instagram captions under the post. Campaign Factory and
  ThreadsDashboard own them.
- Overlay text comes from
  `python_packages/reel_factory/caption_banks/`, never from freehand chat text
  or Higgsfield prompt text.
- Canonical overlay font is Instagram Sans Condensed:
  `python_packages/reel_factory/fonts/InstagramSansCondensed-Bold.woff2`.
- Native platform audio is not burned into MP4s. Campaign Factory recommends via
  `audio_intent.v1`; ThreadsDashboard selects/verifies native audio and blocks
  publish until proof exists.

## Hard Boundary

Creator OS can create, validate, recommend, and export drafts. ThreadsDashboard
is the only production surface for scheduling and publishing unless the user
explicitly changes that boundary.

## Contract Source Of Truth

Shared schemas live in ONE hand-edited place: `packages/pipeline_contracts/schemas`.
Three mirror dirs and the generated TypeScript are produced from it, so several
runtime paths (including `campaign_factory/control.py`'s required-schema health
gate) can resolve schemas from their own root.

Editing a schema: change only `packages/pipeline_contracts/schemas/*.schema.json`,
then run `pnpm sync:contracts` to regenerate every mirror. `pnpm check:contracts`
(CI `contracts` job) fails on any drift. Never hand-edit a mirror — see
`AGENTS.md` "Contract Ownership" for the full mirror list.
