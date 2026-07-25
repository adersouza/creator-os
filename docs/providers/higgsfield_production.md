# Authenticated Higgsfield Production Candidates

Higgsfield is a first-class paid production candidate alongside WaveSpeed.
Neither provider is the default until the operator reviews comparable outputs.
The ordinary `creator-os create --apply` path therefore remains blocked on
`intent_video_recipe_selection_pending_operator_visual_review`.

## Verified live surfaces

The contracts below were read from the authenticated account on 2026-07-24 by
using the official CLI and MCP discovery surfaces. Runtime discovery repeats
these checks instead of trusting this document:

- CLI `1.1.19`: account status, Soul list, model list/get, workflow list/get,
  generation cost/create/wait/get, local-media upload, result download, and
  credit transactions.
- MCP: ready Soul list, model catalog/schema discovery, video generation,
  Kling 3.0 motion control, voices, Marketplace app search/describe/invoke, and
  media upload.
- Ready trained identities: Stacey, Stacey1, Larissa, and Lola were visible to
  the authenticated account. IDs remain explicit runtime inputs and are not
  inferred from creator names.

The exact live video contracts used by the adapter are:

| Actual contract | Inputs used | Candidate |
| --- | --- | --- |
| `kling3_0` | start image, prompt, 9:16, duration, mode, sound | passive selfie |
| `seedance_2_0` | start image, prompt, 9:16, duration, resolution, mode, generated-audio flag | passive selfie |
| `kling3_0_motion_control` | image reference, video reference, mode | motion copy |
| `veo3_1` | start image, prompt/dialogue, 9:16, duration, quality, variant | talking selfie |

`Kling 3.0 Motion Control` is the actual callable name of the exposed
motion-transfer surface. The adapter records that name and does not relabel it
as the marketing product “Animate.”

## Unavailable exact features

The authenticated CLI/MCP did not expose callable tools named Replace or Speak,
and did not expose a standalone Higgsfield lip-sync operation. Marketplace app
search also returned no matching callable apps. Those three recipes are
represented in the candidate catalog but fail before quote or submission.

Veo 3.1 accepts dialogue text but the exposed contract has no supplied-voice
input. It is therefore a usable visual/dialogue candidate, not proof of exact
creator-voice preservation.

## Review-only command

Discovery is free:

```text
scripts/creator-os video-bakeoff capabilities
```

The comparison manifest accepts exactly three passive-selfie samples, two
motion-copy samples, two talking-selfie samples, and one combined
talking-motion-copy sample. Each local file is hashed once; every candidate for
that sample receives the same input fingerprint. A sample object uses
`creator`, `soulId`, `sourceImage`, and `sourceApproval`, plus:

- `drivingVideo` and `drivingApproval` for motion-copy samples;
- `speechAudio`, `speechApproval`, and the exact `script` for talking samples.

```text
scripts/creator-os video-bakeoff manifest \
  --spec <approved-input-spec.json> \
  --review-folder <private-review-folder> \
  --out <private-review-folder>/manifest.json
```

The manifest includes all usable Higgsfield and WaveSpeed candidates, accurately
marks unavailable Higgsfield features, and initializes the same operator review
fields for every planned output. It does not submit jobs or select defaults.

Every paid run requires the current explicit Creator OS mode, a ready Soul ID,
an approved source reference, `--confirm-paid`, and a finite `--max-credits`.
The adapter quotes through the authenticated CLI before submission, submits
once, polls by generation ID, downloads, probes, hashes, and records the result
under the chosen review folder. It never schedules or publishes.

```text
scripts/creator-os video-bakeoff run \
  --mode best_motion \
  --recipe higgsfield_passive_selfie \
  --creator stacey \
  --soul-id <ready-soul-id> \
  --source-approval <approval-reference> \
  --source-image <approved-still> \
  --model kling3_0 \
  --prompt <expanded-casual-motion-prompt> \
  --duration 5 \
  --output <review-folder>/higgsfield-kling.mp4 \
  --review-root <review-folder> \
  --max-credits <bounded-cap> \
  --confirm-paid
```

Receipts retain the generation ID, actual CLI job type, Soul source identity,
source/driving/audio SHA-256 values, quote and observed consumption when
exposed, elapsed time, output SHA-256, stream probe, evidence-store registration,
and empty operator-review fields for:

- identity preservation;
- body consistency;
- face stability;
- hand/anatomy quality;
- motion similarity;
- casual-phone appearance;
- lip-sync;
- expressiveness;
- attractiveness;
- generation time;
- credits consumed;
- dollar cost;
- would-post decision.

No automated identity or anatomy approval is claimed.
