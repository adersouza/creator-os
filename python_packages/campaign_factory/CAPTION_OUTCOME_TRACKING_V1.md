# Caption Outcome Tracking v1

## Goal

Caption Outcome Tracking v1 hardens the measurement layer for captions across generated, approved, scheduled, posted, and metrics-imported states. It does not learn winners, promote captions into winner banks, rewrite caption text, alter prompt generation, or automate publishing.

## Canonical Ownership

- Reel Factory owns render-time caption lineage: caption text/hash, bank lineage, creator mix, source clip, render recipe, frame type, caption-fit suitability, and static caption shape.
- Campaign Factory owns canonical campaign/account/schedule/outcome joins after promotion.
- ThreadsDashboard owns platform post rows and metric collection surface.
- Campaign Factory `performance_snapshots` is the canonical measured outcome table once metrics are imported.

## Non-Goals

- No winner learning.
- No automatic winner-bank promotion.
- No prompt generation changes.
- No caption text, caption-bank, or caption-mix changes.
- No deletion, censoring, quarantine, suppression, or rewriting of captions.
- No Higgsfield, Grok, Kling, or audio-selection changes.
- No Instagram/private API login, publishing, or automation changes.

## Measurement Flow

1. Reel Factory renders an asset and emits caption lineage next to the rendered output.
2. Campaign Factory promotion copies Reel Factory lineage into Campaign Factory without changing caption text.
3. Campaign Factory stores additive nullable caption outcome context on `rendered_assets`.
4. Campaign Factory copies the same context to `distribution_plans` when an asset is assigned to an account/schedule slot.
5. Campaign Factory exports the context into ThreadsDashboard post `metadata.campaign_factory.caption_outcome_context`.
6. ThreadsDashboard continues to own post rows and metrics collection.
7. Campaign Factory syncs ThreadsDashboard metrics into `performance_snapshots`, copying the caption outcome context into explicit nullable columns and raw JSON.
8. Readiness/reporting warns when approved or measured assets are missing caption outcome context, but does not block old assets in v1.

## Caption Outcome Context

The v1 context is a denormalized measurement snapshot, not a decision object:

```json
{
  "schema": "campaign_factory.caption_outcome_context.v1",
  "caption_hash": "sha256-or-render-lineage-hash",
  "caption_text": "exact rendered caption text",
  "caption_bank": "primary_selected_or_source_bank",
  "caption_banks": ["primary_selected_or_source_bank"],
  "creator_mix": "Larissa | Stacey | Lola | null",
  "creator_model": "campaign/model slug when known",
  "frame_type": "mirror_fullbody",
  "length_class": "very_short",
  "format_class": "single_line",
  "caption_fit_version": "v1",
  "suitability_decision": "allowed",
  "suitability_reason": "caption-fit diagnostic",
  "render_recipe": "v01_original",
  "source_clip": "clip_010",
  "rendered_output": "/path/to/rendered.mp4"
}
```

Field precedence:

- Prefer Reel Factory render lineage and caption-bank lineage.
- Fall back to Campaign Factory `rendered_assets.caption`, `recipe`, `output_path`, and model/source fields.
- Leave missing fields nullable instead of synthesizing false precision.

## Additive Schema

Add nullable scalar columns plus a JSON payload column where the context needs to survive joins:

- `rendered_assets`: render-time caption outcome context.
- `distribution_plans`: account/schedule copy of the render-time context.
- `performance_snapshots`: measured outcome copy of the exported post context.

Keep existing columns as canonical where they already exist:

- `rendered_assets.caption` remains the rendered caption text.
- `rendered_assets.recipe` remains the render recipe.
- `rendered_assets.output_path` remains the rendered output path.
- `performance_snapshots.caption_hash` and `performance_snapshots.recipe` remain canonical metric grouping columns.

## Readiness Behavior

v1 reports missing caption outcome context as warning/risk coverage:

- Count rendered assets missing context.
- Count approved assets missing context.
- Count measured snapshots missing context.
- Add risks-losing-tracking warnings for missing context.

Missing context must not block old assets initially.

## Reporting Queries Enabled

The v1 schema supports manual analysis such as:

- performance by `caption_hash`
- performance by `caption_bank`
- performance by `creator_mix`
- performance by `creator_model`
- performance by `frame_type`
- performance by `length_class`
- performance by `format_class`
- performance by `caption_fit_version`
- account/campaign outcome comparison for the same caption context

These are reporting surfaces only. Any winner selection, caption-bank promotion, or generation change remains explicitly out of scope.
