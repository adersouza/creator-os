# Creator OS Pipeline Wiring Plan

## Current Slice

This branch implements the first mergeable pipeline-wiring slice:
zero-cost, draft-first per-account video variation before ThreadsDashboard
draft export.

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

## Safety Boundaries

- No Higgsfield, Kling, or other paid generation is called in this slice.
- No autonomous publishing or scheduling behavior is added.
- `MicroEngine` remains available only through explicit opt-in config and is
  disabled in default presets.
- `QualityGate` remains mandatory for accepted applied variants.
- `SimilarityGate` failures now raise instead of silently treating bad SSIM
  output as identical/safe.

## Next Slices

- Add a free still-to-reel motion-edit path.
- Add paid Soul/Kling generation behind explicit budget and review gates.
- Add performance-driven preset selection.
- Add proactive cycles only after the draft-first path is proven.
