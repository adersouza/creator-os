# Reference Video Structural Remix

## Purpose

This is an opt-in Reel Factory path for an **operator-selected OFM/reference
video**. It does not recreate the Instagram tutorial that explained the idea,
and it is not a literal clone workflow. It preserves a short source video's
motion structure while changing the creator identity and other visual details.

Initial scope is deliberately narrow:

- one continuous 9:16 shot;
- 5–12 seconds;
- no cuts or scene changes;
- local reference video and endpoint images;
- two operator-approved Stacey endpoint frames;
- one approval-gated Seedance or Kling animation;
- ContentForge distinctness/QC before final approval;
- no publishing from Reel Factory.

## Flow

```text
operator-selected reference video + rights confirmation
→ Gemini-style motion-only analysis JSON
→ validate reference_video_motion_analysis.v1
→ reference-conditioned Higgsfield Soul first frame (dry-run plan)
→ reference-conditioned Higgsfield Soul last frame (dry-run plan)
→ operator accepts both endpoint frames
→ deterministic Seedance/Kling routing
→ provider quote + atomic credit reservation + paid approval (still required)
→ generated video
→ ContentForge source/sibling distinctness + visual QC
→ final operator approval
→ normal Campaign Factory handoff (separate step)
```

The two endpoint-frame requests reuse Reel Factory's existing
`reference-image-dry-run` contract: Soul V2, direct reference conditioning,
9:16, no captured-prompt reuse, and no prompt append. The source first and last
frames preserve composition endpoints. They are not automatically accepted:
unchanged source frames are rejected, both generated endpoints require distinct
file hashes and approval IDs, and the final video remains blocked on
ContentForge source-master distinctness.

## Contracts

- `reel_factory.reference_video_motion_analysis.v1` is the only accepted
  Gemini/operator analysis shape. It requires one continuous 5–12 second shot,
  a fully covered timeline, motion-only source-text handling, identity/text
  transformation, and at least one additional visual transformation.
- `reel_factory.reference_video_remix_plan.v1` records source hashes, analysis
  hash, source/accepted endpoint hashes, chosen provider/model, QC requirements,
  approval boundaries, and the provider request that may be executed later.

The planner validates both contracts and emits a lineage seed. A later render
must copy that seed into the final `generated_asset_lineage.v2` metadata and add
the rendered content fingerprint, review evidence, and Campaign Factory IDs.

## Gemini Analysis Ingestion

`gemini_motion_analysis_instruction(reference_id)` returns the bounded provider
instruction. Gemini is an analysis provider here, not the active still-image
generator. Its response must be JSON only and must not contain a transcript,
source caption wording, creator identity, or a request to reproduce the source
literally.

The checked-in example is:

`packages/pipeline_contracts/pipeline_contracts/schemas/reference_video_motion_analysis.v1.example.json`

No Gemini API call is implemented in this slice. The operator or a future
provider adapter supplies the JSON, and the planner fails closed if it does not
match the contract.

## Deterministic Provider Routing

The default `auto` route is:

1. Choose Seedance when the analysis says reference-video conditioning is
   required and Seedance is available.
2. Otherwise choose Kling when Kling is available; it receives the accepted
   first/last frame pair and the structural motion prompt.
3. If only Seedance is available, use Seedance as the deterministic fallback.
4. An explicitly selected unavailable provider is an error. There is no silent
   provider substitution.

Seedance receives the accepted first and last frames, the local reference
video, and the structural motion prompt. Kling receives the accepted first and
last frames plus the prompt, without the source video. Both reuse
`generate_assets.build_video_cmd` and keep sound off.

The analysis and lineage preserve the exact source duration, including a
fraction such as `7.5`. Provider duration is a separate integer field because
both current video models require integer seconds. Reel Factory uses bounded
half-up rounding (`7.5 → 8`, always clamped to the supported 5–12 second
window), records both values, and passes only the integer to `--duration`.

## Spend, QC, And Approval Boundaries

The planner never executes its generated command. Every plan hard-codes:

- `paidGenerationAuthorized: false`;
- provider quote required;
- atomic credit reservation required;
- endpoint-frame approval required;
- paid-animation approval required;
- final-asset approval required;
- `publishingAllowed: false`.

After generation, ContentForge must block on source-master distinctness,
sibling distinctness, identity verification, endpoint continuity, readability,
safe zone, watchability, and visual QC. Any failure returns the asset to review.

## Dry-Run Planner

```bash
uv run --package reel-factory python -m reel_factory.reference_video_remix \
  --reference-video /path/reference.mp4 \
  --source-first-frame /path/reference.first.png \
  --source-last-frame /path/reference.last.png \
  --analysis-json /path/reference.motion-analysis.json \
  --creator Stacey \
  --soul-id d63ea9c7-b2c7-439c-bf0c-edfdf9938a36 \
  --operator-selected \
  --rights-confirmed \
  --out /path/reference.remix-plan.json
```

This first pass returns `awaiting_endpoint_frames` and only two Higgsfield
`reference-image-dry-run` commands. Supplying both accepted endpoint paths and
both approval decision IDs returns `ready_for_paid_animation_approval`; it does
not authorize or run the paid request.

## Deliberate Non-Goals

- no Instagram tutorial recreation;
- no arbitrary multi-scene video decomposition;
- no private-platform scraping or login automation;
- no paid provider call in the planner;
- no automatic approval, draft export, schedule, or publish;
- no change to the default direct-reference still workflow;
- no bypass of ContentForge distinctness or final operator review.
