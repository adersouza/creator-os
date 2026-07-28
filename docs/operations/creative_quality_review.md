# Creative quality review

Creator OS keeps creative judgment attached to exact media bytes. It does not
infer a general model preference from a small review sample.

## Operator path

1. Normal intent-first create plans one job per requested output using the
   already pinned Higgsfield Kling 3 or Seedance 2 passive recipe.
2. Before a paid quote, the planner records an evidence-only compatibility
   assessment and a deterministic structured prompt card. Missing visual facts
   stay `unknown`. Only technical incompatibility can block; the assessment
   cannot switch models or authorize spend.
3. The prompt card compiles into the existing provider prompt. It preserves
   identity, outfit, setting, pose family, face/head visibility, restrained
   motion, and silent provider output.
4. Review the exact final bytes:

   ```bash
   scripts/creator-os media review-existing \
     --asset ASSET_ID \
     --final-sha FINAL_MP4_SHA256 \
     --reviewer OPERATOR \
     --verdict REJECT \
     --rejection-reason MOTION_UNNATURAL \
     --notes "optional context" \
     --apply
   ```

   Blank result and reason fields mean unknown. Re-embedding produces a new SHA
   and requires a new review.
5. Inspect transparent counts with
   `scripts/creator-os media review-summary`. Counts include only explicit
   rejection reasons and have no predictive claim.

## Small benchmark

`scripts/creator-os quality-benchmark --manifest MANIFEST --dry-run` validates
10–15 exact approved-source cases. It reports missing evidence and projected
paid jobs, performs no provider call or database write, and cannot change a
production default. Future execution requires separate spend authorization and
exact-output human review.

## Authenticated capability versus claim

An authenticated CLI/MCP schema proves only the parameters and account surfaces
it exposes. It does not prove output quality, voice fidelity, choreography
fidelity, or postability.

Current read-only findings:

- Seedance 2.0 exposes `audio_references` (maximum three), 4–15 second outputs,
  9:16, 480p/720p/1080p/4K, and `generate_audio=false`. A five-second 720p
  silent cost preflight returned 22.5 credits without submitting a job.
- The schema does not establish exact dialogue, supplied-voice preservation,
  audio-reference duration, or whether reference audio is copied, transformed,
  or used only as conditioning. It accepts an audio media reference, not a
  voice-identity parameter.
- MCP Motion Control exposes one character image, one driving video, 720p/1080p,
  and image/video scene control. The CLI maps this to
  `kling3_0_motion_control` with `background_source=input_image|input_video`.
  This is the same underlying rejected Kling Motion Control recipe, not a new
  implementation; it remains inactive. MCP exposes no read-only quote flag for
  that tool, while the CLI workflow advertises duration/mode cost inputs.
- Audio Radar replacement remains a downstream Creator OS media operation.
  The Seedance schema neither forbids that operation nor proves that replacing
  generated audio preserves provider-side audio semantics.
- Authenticated Elements access is present. Element creation accepts category
  `auto`, `character`, `environment`, or `prop`; completed elements can use the
  authenticated placeholder contract in Seedance 2.0. A Soul ID is not itself
  an Element input: an image/media or completed image job is required to create
  one. Element-creation cost is not exposed.

Talking and motion copy remain unresolved production capabilities.

## Reference-Reel recreation review

`recreate_reel` is EXPERIMENTAL. Seedance 2 receives one approved
Soul-generated creator image plus one private video reference; it is not an
exact-choreography or creator-voice claim. Review remains bound to the exact
final MP4 SHA and preserves separate judgments for creator identity, facial and
body consistency, hands/anatomy, clothing and background stability, broad
action fidelity, camera/framing fidelity, pacing fidelity, choreography
fidelity, social-native appearance, attractiveness, obvious AI artifacts,
audio synchronization, and would-post.

Duration ratio, frame-rate difference, shot-count difference, cut timing,
coarse motion energy, and framing progression are advisory measurements. They
cannot replace operator review or turn an unapproved source into an eligible
input. The intent remains experimental until a separately authorized paid
output receives exact-SHA `WOULD_POST` approval.
