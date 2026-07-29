# Reference-Video Creation Boundaries

Creator OS contains two deliberately different reference-video surfaces. They
must not be described as one workflow.

## Normal Experimental Intent: `recreate_reel`

`creator-os create --intent recreate_reel` is the current bounded experimental
production path.

### Purpose

Use one private, operator-authorized Reel as inspiration while preserving the
approved creator identity:

```text
Instagram/TikTok/Short/direct-media URL or local video
  -> private temporary download or local-file intake
  -> canonical platform/media identity + exact SHA
  -> full-source analysis, clean frame candidates, and reference-audio evidence
  -> timestamped OCR inventory kept outside the generation prompt
  -> timecoded motion/camera analysis when authenticated Gemini is available
  -> deterministic classification and bounded coherent excerpt
  -> one clean-opening-frame-matched Soul anchor or two endpoint anchors
  -> exact-SHA human anchor approval
  -> truthfully matched Higgsfield recreation mode
  -> provider-generated audio disabled or explicitly replaced
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

- exactly one `--reference-url` or `--reference-video`;
- explicit `--reference-authorized` before persistent apply;
- creator, account, `--recreate-mode`, audio policy, and finite credit cap;
- approved creator source inventory from which anchors may be planned;
- `count=1`.

`--through analyze` stops before a paid visual-generation request. The
authenticated Gemini CLI may make one read-only semantic-analysis call whose
cost is reported as unknown when the CLI does not expose it. Dry-run uses
temporary files and makes no database mutation. Authorized apply persists
private artifacts outside Git and remains idempotent for the same
platform/media identity and exact SHA.

### Provider binding

The planner exposes only contracts proven by the authenticated Higgsfield
catalog:

| Mode | Contract | Status |
|---|---|---|
| `passive` | approved Soul anchor to Kling 3, sound off | accepted after anchor approval |
| `structural` | opening-frame-matched Soul anchor in `image_references`, creator Element first in the prompt, Reel motion-only in `video_references`, Seedance 2 Fast at 480p/high bitrate, generated audio off | experimental structural recreation |
| `motion` | `kling3_0_motion_control`, image + video reference, Pro mode | experimental; never an automatic submission |
| `first_last` | two approved Soul endpoints to Kling 3 start/end, sound off | experimental transition |
| `talking` | exact supplied-voice entitlement required | blocked as `talking_route_not_entitled` |

Soul is the upstream still-identity system. Seedance receives the approved
Soul-generated anchor bytes plus the bound creator Element, not a raw Soul ID.
It does not mix `start_image`/`end_image` with reference-media mode. The source
writing inventory remains evidence only; the generation prompt starts with the
operator-proven creator replacement instruction and adds only the sanitized
motion/camera timeline.

Normal create never falls back to WaveSpeed or a local model. `AUTO` may
recommend a compatible route but may not silently submit experimental Motion
Control, structural Seedance, first/last, talking, multi-shot, or multi-person
work.

### Audio

`--audio auto` requires creator/reference speech for talking, requires reference
audio for synchronized dance, prefers an explicit comparison for eligible
structural or motion audio, and uses Audio Radar for passive work. Explicit
reference audio, embedded trending audio, and explicit silence remain separate
policies.

The final audio receipt binds the exact segment and final MP4 SHA. Talking
creator speech is unresolved and cannot be inferred from reference audio.

### Spend and ambiguity

Dry-run performs local analysis and may use authenticated read-only quoting.
Apply requires explicit reference authority, anchor approval, paid
authorization, and a finite credit ceiling. One invocation submits at most one
video request. An ambiguous submission is preserved for reconciliation and
never blindly retried.

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
- no browser-controlled third-party downloader websites;
- no copying captions/transcripts from the reference;
- no automatic paid fallback;
- no bypass of source approval, distinctness, or final review;
- no automatic draft export, schedule, or publication;
- no claim that structural recreation solves the unresolved motion-copy or
  talking products.
