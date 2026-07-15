# Reference Video Structural Remix

## Purpose

This is an opt-in Campaign Factory workflow for an **operator-selected
OFM/reference video**. Reel Factory owns the validated plan and provider command;
Campaign Factory owns execution, spend gates, approvals, registration, and final
review state. It does not recreate the tutorial that explained the idea, and it
is not a literal clone workflow.

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
→ deterministic ffprobe + PySceneDetect one-shot validation
→ source endpoint extraction
→ Gemini motion-only analysis JSON
→ validate reference_video_motion_analysis.v1
→ quoted/reserved reference-conditioned Soul first and last frames
→ separate hash-bound operator approvals for both endpoint frames
→ free, silent, locked 9:16 static MP4 from the primary endpoint
→ deterministic Seedance/Kling routing
→ provider quote + atomic credit reservation + paid approval (still required)
→ generated video
→ eight blocking ContentForge checks + registered lineage and receipts
→ review-ready asset blocked on final operator approval
→ normal Campaign Factory handoff (separate step; never schedule/publish here)
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

The planner validates both contracts and emits a lineage seed. The Campaign
stage copies that evidence into `reference_video_remix_lineage.v1`, adds source
and endpoint hashes, provider jobs, redacted quote/reservation receipts, the
static fallback, ContentForge evidence, and the registered Campaign asset ID.

## Gemini Analysis Ingestion

`gemini_motion_analysis_instruction(reference_id)` returns the bounded provider
instruction. Gemini is an analysis provider here, not the active still-image
generator. Its response must be JSON only and must not contain a transcript,
source caption wording, creator identity, or a request to reproduce the source
literally.

The checked-in example is:

`packages/pipeline_contracts/pipeline_contracts/schemas/reference_video_motion_analysis.v1.example.json`

The Campaign stage calls Gemini through the environment-only
`CREATOR_OS_REFERENCE_REMIX_DRIVER` phase adapter. The response is validated
against the contract and cross-checked against ffprobe duration/aspect evidence.
No credential is accepted in argv or persisted in the lineage artifact.

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

The Reel Factory planner never executes its generated command. The Campaign
stage may execute only after all live gates pass. Every plan hard-codes:

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

## Canonical Operator Preflight

```bash
scripts/creator-os generate --mode reference_video_remix --dry-run \
  --campaign campaign_slug --reference-video /path/reference.mp4 \
  --target Stacey \
  --soul-id d63ea9c7-b2c7-439c-bf0c-edfdf9938a36 \
  --workspace "$PWD" --operator-selected --rights-confirmed --max-credits 3
```

This returns a provider-free preflight and performs no extraction or generation.
PySceneDetect runs locally before Campaign rows, output directories, or paid
seams. A detected cut rejects the source with scene-boundary evidence; the
workflow never guesses that a multi-shot video is safe.
An `--apply` additionally requires explicit paid confirmation, both endpoint
approval IDs, a finite cap, and the configured phase driver. A fake-provider E2E
proves the complete Campaign chain. A real provider smoke remains a separate
operator-approved action and has not been run by tests.

## Deliberate Non-Goals

- no Instagram tutorial recreation;
- no arbitrary multi-scene video decomposition;
- no private-platform scraping or login automation;
- no paid provider call without quote, atomic reservation, and confirmation;
- no automatic approval, draft export, schedule, or publish;
- no change to the default direct-reference still workflow;
- no bypass of ContentForge distinctness or final operator review.
