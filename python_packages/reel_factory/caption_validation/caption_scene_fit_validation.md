# Caption Scene Compatibility v1 Validation

Run date: 2026-06-04

## Summary

Caption Scene Compatibility v1 was validated with synthetic `CaptionSet` rows through the real `apply_caption_fit_to_caption_set()` path. The validation does not edit caption text, caption banks, or bank weights.

## Validation Matrix

| Case | Reel scene tags | Expected | Result |
| --- | --- | --- | --- |
| indoor selfie | `bedroom_mirror`, `indoor_selfie` | blocks pool and gym-specific captions; allows general hook | PASS |
| mirror/full-body | `bedroom_mirror`, `indoor_selfie` | allows bedroom/mirror hook; blocks beach hook | PASS |
| gym/body | `gym_body` | allows gym hook; blocks bedroom-only hook | PASS |
| outdoor/beach | `beach_pool`, `indoor_selfie`, `outdoor_lifestyle` | allows beach hook; blocks gym hook, even with generic prompt word `room` | PASS |
| unknown | `unknown` | allows general hook; blocks explicit gym hook | PASS |

## Lineage Check

Selected hooks include:

- `captionSceneTags`
- `reelSceneTags`
- `sceneCompatibilityDecision`
- `sceneCompatibilityReason`
- `captionSceneFitVersion: v1`

Result: PASS

## Caption Bank Safety

This validation used synthetic caption rows and did not write to `caption_banks/`, `01_captions/`, or caption text sources.

Result: PASS for this change scope.

Note: the working tree already contains unrelated unstaged caption bank changes. They are intentionally excluded from the caption-scene-fit commit.
