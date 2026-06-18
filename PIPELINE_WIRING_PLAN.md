# Creator OS Pipeline Wiring Plan

## Current Slice

The first mergeable pipeline-wiring slices are now on `main`: zero-cost,
draft-first per-account video variation before ThreadsDashboard draft export,
plus the E2 primitive for turning an accepted still into a review-ready MP4 by
local FFmpeg motion edit.

The current branch completes the first live Workstream E chain: accepted-still
Kling apply can register a downloaded local MP4 as a review-ready master reel
and, when explicitly requested, hand that one master into the existing variation
stage. Paid generation remains default-off and budget-gated.

Creator OS does not commit a dashboard mirror. Dashboard source, RLS, type
cleanup, visual regression, and deployment provenance live in the external
ThreadsDashboard repository.

## Implemented Behavior

- `repurposer` can create account-bound variants from an approved master asset.
- `campaign_factory.variant_assignment.v1` records the master asset, each
  account destination, the per-account variant path, and distinctness scores.
- `campaign-factory variation run --campaign <slug>` creates dry-run assignment
  manifests by default; `--apply` performs local FFmpeg variation.
- `export-threadsdash --enable-variation` runs the variation stage before draft
  payload construction and requires every destination to have an assignment.
- With variation disabled, export keeps using the current master asset path.
- `reel_factory.still_to_reel` renders a 9:16 `motion_edit` MP4 from a still,
  caption PNG overlay, and optional explicitly supplied local audio.
- `reel_factory.motion_edit_render.v1` records zero paid generation, FFmpeg
  command provenance, quality, audio intent, and generated-asset lineage.
- `campaign-factory animation motion-edit --campaign <slug>` previews the
  render by default; `--apply` registers a review-ready rendered asset without
  exporting, scheduling, or publishing.
- `campaign-factory generation front-link --campaign <slug>` previews the paid
  image-driven front path by default. It plans direct reference-image Soul still
  generation, preserves the still accept gate, and plans Kling only after an
  accepted still exists.
- Paid front generation fails closed unless `--enable-paid-generation` and
  `--budget-cap-usd` are both supplied. Dry-run projected-cost reports require
  no Higgsfield/Kling calls.
- `campaign-factory generation front-link --apply --accepted-still <path>
  --enable-paid-generation --budget-cap-usd <usd> --wait --download` submits the
  accepted still to Kling and registers the downloaded local video as a
  `review_ready` rendered asset with paid-generation lineage.
- `--enable-variation` on that live accepted-still path runs the variation stage
  in dry-run mode against only the newly registered Kling master asset. If the
  paid job did not yield a downloaded local video, variation fails closed instead
  of silently sharing the master or doing nothing.

## Safety Boundaries

- No Higgsfield, Kling, or other paid generation is called by default. Live paid
  generation requires explicit apply, paid-generation enablement, and a budget
  ceiling.
- No autonomous publishing or scheduling behavior is added.
- Motion edit is zero-cost and local only. Platform or trending audio is never
  burned into the MP4; it is recorded as an audio-intent sidecar unless an
  operator explicitly supplies licensed local audio.
- Applied motion-edit assets are `review_ready` and require human review before
  normal export/variation workflows can treat them as approved.
- Front generation is default-off and budget-gated. A still must be reviewed
  before live Kling animation is submitted.
- `MicroEngine` remains available only through explicit opt-in config and is
  disabled in default presets.
- `QualityGate` remains mandatory for accepted applied variants.
- `SimilarityGate` failures now raise instead of silently treating bad SSIM
  output as identical/safe.

## Next Slices

- Add performance-driven preset selection.
- Add proactive cycles only after the draft-first path is proven.
