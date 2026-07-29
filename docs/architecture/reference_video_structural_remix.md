# Reference-Video Creation Boundaries

Creator OS contains two deliberately different reference-video surfaces. They
must not be described as one workflow.

## Normal Experimental Intent: `recreate_reel`

`creator-os create --mode recreate_reel` is the current bounded experimental
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
  -> OpenAI watches the approved creator image and chronological Reel frames
  -> Soul and Seedance prompt pack plus a non-executable Kling planning prompt
  -> deterministic classification and bounded coherent excerpt
  -> one text-only Soul anchor from the OpenAI scene/composition prompt
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
- one approved creator image supplied with `--creator-image`;
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
| `calm` | approved Soul anchor plus OpenAI prompt through the Seedance 2 Fast recreation contract | experimental prompt-driven recreation |
| `structural` | approved Soul anchor plus OpenAI action/timing prompt through Seedance 2 Fast at 480p/high bitrate, generated audio off | experimental prompt-driven recreation |
| `auto` | selects the prompt shape from measured reference evidence, then uses Seedance | no Kling or Motion Control execution route |

Soul is the upstream still-identity system. The OpenAI anchor prompt omits hair
color, tattoos, and other permanent identity traits so the selected Soul owns
them. The executable Seedance request receives the approved Soul-generated
anchor as an image reference, the authorized reference Reel as a video
reference for broad motion/structure conditioning, and the resolved creator
Element as a prompt token. Seedance does not consume `soul_id` directly.
Source writing remains evidence only and is excluded from generation prompts.
The Kling prompt in the pack is planning evidence and is not wired to a paid
recreation request.

OpenAI prompt packs are cached by exact input hashes and prompt-builder
fingerprint. On a cache miss, Campaign Factory must persist and verify a signed,
five-minute, one-call authorization containing an operator-configured maximum
USD quote before the paid request. Receipts retain that authorization, model,
response ID, usage, and actual-cost status. The API currently exposes usage but
may omit dollar cost; omitted actual cost remains `not_exposed`.

Normal create never falls back to WaveSpeed or a local model. `AUTO` may plan
prompt-driven Seedance, but paid submission still requires anchor approval,
finite authorization, and final operator review.

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
