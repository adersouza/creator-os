# Creator OS 9/10 Professionalization Support Sprint

This plan adds acceptance discipline without adding automation, generation, scheduling, publishing, or runtime behavior.

## Acceptance Suite Plan

Each surface should have a repeatable dry-run acceptance test:

1. Register or load deterministic fixture asset.
2. Run surface-specific publishability/readiness gate.
3. Build handoff manifest v2.
4. Build ThreadDash-compatible draft payload preview.
5. Stop before export, scheduling, publishing, or metrics sync.

Surface coverage:

| Surface | Dry-run proof | Live-enabled extension |
| --- | --- | --- |
| `reel` | asset -> publishability -> handoff manifest -> draft payload -> stop | draft -> schedule -> publish -> metrics -> lifecycle/learning report |
| `story` | asset -> story quality gate -> handoff manifest -> draft payload -> stop | not live-enabled yet |
| `feed_single` | asset -> image readiness -> handoff manifest -> draft payload -> stop | draft -> schedule -> publish -> metrics -> lifecycle/learning report |
| `feed_carousel` | asset -> ordered components -> handoff manifest -> draft payload -> Meta child payload preview -> stop | pending carousel publish proof |
| `trial_reel` | reel asset -> explicit trial metadata -> handoff manifest -> draft payload -> stop | draft -> manual/strategy-specific graduation review only |

## Handoff Manifest v2 Fixtures

Reusable fixtures live in `tests/fixtures/manifest_v2/`:

- `reel_manifest_v2_valid.json`
- `story_manifest_v2_valid.json`
- `feed_single_manifest_v2_valid.json`
- `feed_carousel_manifest_v2_valid.json`
- `trial_reel_manifest_v2_valid.json`

Every fixture must preserve:

- `content_surface` and `contentSurface`
- `ig_media_type` and `igMediaType`
- non-empty `mediaItems[]`
- `content_hash`
- caption lineage when required
- `surfaceReadiness.canHandoff`
- `wouldWrite:false`

## Visual QC Fixtures

Reusable fixtures live in `tests/fixtures/visual_qc/`:

- valid `1080x1920` story
- story with black bars
- story with bad aspect ratio
- story with safe-zone violation
- valid feed image
- valid ordered carousel slides
- carousel with bad slide order

These are contract fixtures. They are intentionally small JSON descriptors so tests remain deterministic and do not require AI generation.

## Surface-Native Caption Family Plan

Use one caption family model with surface-specific optional fields:

| Surface | Burned caption | Instagram post caption | Caption version meaning |
| --- | --- | --- | --- |
| `reel` | required for captioned Reel variants | required | burned-caption plus IG caption pair |
| `feed_single` | not required | required | IG post caption version for one image |
| `feed_carousel` | not required by default | required | IG post caption version plus optional slide-level alt/label metadata |
| `story` | optional rendered text/CTA | not required by default | story overlay/intent version, not an IG post caption contract |

Keep the fields simple:

- `caption_family_id`
- `caption_version_id`
- `content_surface`
- `burned_caption_text`
- `burned_caption_hash`
- `instagram_post_caption`
- `instagram_post_caption_hash`
- `story_overlay_text`
- `story_cta_type`
- `caption_angle`
- `caption_source`
- `caption_family_index`

Do not force Reel burned-caption requirements onto image, carousel, or Story assets.

## Report Consolidation Compatibility Tests

Compatibility tests should prove old reports remain wrappers over canonical helpers:

- winner reports -> Creative Knowledge Base
- story reports -> surface inventory/status/readiness helpers
- decision-ledger-by-* -> decision-ledger-report filters
- lifecycle-dashboard -> lifecycle-report grouping

Do not remove or rename reports until old commands are thin wrappers and acceptance tests are stable.

## No Runtime Behavior Change

This sprint is fixtures, contracts, and test scaffolding only. It does not schedule, publish, generate content, export drafts, sync metrics, or mutate production data.
