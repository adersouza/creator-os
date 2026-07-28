# Reference-Video Creation Boundaries

Creator OS contains two deliberately different reference-video surfaces. They
must not be described as one workflow.

## Normal Experimental Intent: `recreate_reel`

`creator-os create --intent recreate_reel` is the current bounded experimental
production path.

### Purpose

Use one private, operator-authorized short Reel as structural inspiration while
preserving the approved creator identity:

```text
private authorized reference Reel
  -> bounded local technical/motion analysis
  -> exact reference path and SHA
  -> rank already-approved same-creator images by framing compatibility
  -> select one approved Soul-generated creator image
  -> one pinned Higgsfield Seedance 2 request
  -> generated audio disabled
  -> reference audio, Audio Radar finishing, or explicit silence
  -> technical QC
  -> exact-SHA operator review
```

This path targets broad:

- shot structure;
- performance energy;
- action progression;
- pacing;
- camera/framing progression.

It does not claim:

- exact choreography;
- exact motion copy;
- performer replacement;
- voice preservation;
- talking-video support.

### Inputs

- exactly one local reference video;
- explicit `--reference-authorized`;
- source platform label;
- one already-approved same-creator image selected internally;
- creator, account, audio policy, and finite credit cap;
- `count=1`.

Talking references fail before quote or submission.

### Provider binding

The active recipe is pinned to Higgsfield Seedance 2:

- creator image in `image_references`;
- inspiration Reel in `video_references`;
- portrait 9:16 output;
- 720p standard mode;
- bounded 4–15 second duration;
- `generate_audio=false`.

Soul is the upstream identity system. Seedance consumes the approved
Soul-generated image bytes; it does not receive a raw Soul ID.

Normal create does not choose between providers and does not fall back to Kling
Motion Control, WaveSpeed, or a local model.

### Audio

The explicit policies are:

- `original_embedded` / `reference_audio_required` — select and embed the exact
  reference-video audio segment;
- `embedded_trending` — use canonical Audio Radar finishing;
- `silent_allowed` — explicit silence.

The final audio receipt binds the exact segment and final MP4 SHA. Talking
creator speech is unresolved and cannot be inferred from reference audio.

### Spend and ambiguity

Dry-run performs local analysis and authenticated read-only quoting. Apply
requires explicit authorization and a finite credit ceiling. One invocation
submits at most one request. An ambiguous submission is preserved for
reconciliation and never blindly retried.

### Review

Review the exact final SHA for:

- intended creator identity;
- face/body stability;
- hands/anatomy;
- broad action fidelity;
- camera/framing fidelity;
- pacing;
- social-native appearance;
- attractiveness;
- obvious AI artifacts;
- audio synchronization;
- would-post.

Technical similarity measurements are advisory and cannot replace operator
review.

## Advanced Manual Mode: `reference_video_remix`

The five-mode compatibility catalog also retains an older advanced/manual
`creator-os generate --mode reference_video_remix` contract. It uses
operator-selected endpoint-frame planning, motion analysis, explicit provider
selection policy, and additional approvals.

It is:

- not the normal `recreate_reel` intent;
- not called by intent-first create;
- not a fallback;
- not a production default;
- retained for historical evidence and explicit advanced work.

Its historical contracts remain:

- `reel_factory.reference_video_motion_analysis.v1`;
- `reel_factory.reference_video_remix_plan.v1`;
- endpoint image approvals;
- source/endpoint hashes;
- provider quote and atomic reservation;
- final ContentForge and human review.

The advanced planner does not execute its generated provider command by itself.
It grants no export, scheduling, or publishing authority.

## Shared Safety Rules

Both surfaces require:

- operator authority to use the private reference;
- exact local source hashes;
- approved creator identity;
- bounded duration and portrait compatibility;
- provider-generated sound disabled unless explicitly part of a reviewed
  advanced contract;
- finite spend authorization;
- no blind retry;
- retained source/provider/output lineage;
- ContentForge and media integrity checks;
- final exact-SHA operator review;
- separate export;
- no scheduling or publishing.

Neither surface registers the inspiration Reel as the creator's rendered asset.
Neither may present the reference performer as the intended creator.

## Deliberate Non-Goals

- no arbitrary multi-scene decomposition;
- no private-platform login automation;
- no copying captions/transcripts from the reference;
- no automatic paid fallback;
- no bypass of source approval, distinctness, or final review;
- no automatic draft export, schedule, or publication;
- no claim that structural recreation solves the unresolved motion-copy or
  talking products.
