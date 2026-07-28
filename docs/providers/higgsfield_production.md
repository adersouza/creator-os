# Higgsfield Production

Higgsfield is the only visual-generation provider in normal Creator OS
production. The authenticated contract, not product-page language, determines
what Creator OS can offer.

## Supported recipes

| Intent | Pinned implementation | Product status |
| --- | --- | --- |
| `soul_static` | Soul 2.0 still plus deterministic local static MP4 | SUPPORTED |
| `passive_selfie` | Kling 3 (`kling3_0`) or Seedance 2 (`seedance_2_0`) | SUPPORTED |
| `recreate_reel` | Seedance 2 (`seedance_2_0`) with one approved creator image and one private video reference | EXPERIMENTAL |
| `talking_selfie` | No exact supplied-audio contract exposed | UNRESOLVED |
| `motion_copy` / `dance` | No operator-approved distinct transfer recipe | UNRESOLVED |
| `talking_motion` | Requires both approved motion and supplied-audio lip-sync | UNRESOLVED |

The passive recipe is pinned by product configuration. Ordinary operators give
creator intent, not provider/model identifiers. A failed or ambiguous
Higgsfield call is retained for reconciliation and is never silently retried
or routed to WaveSpeed.

`recreate_reel` is a bounded structural recreation, not precision motion copy.
It retains the private reference path and SHA in an analysis receipt, ranks only
already-approved same-creator images, and sends the selected image through
Seedance's `image_references` role and the inspiration Reel through
`video_references`. Soul remains the upstream identity system; the authenticated
Seedance contract accepts the resulting image bytes, not a raw Soul ID.
Generation is fixed to 9:16, 720p, 4–15 seconds, standard mode, and
`generate_audio=false`. The prompt asks Seedance to closely follow broad
structure, performance, and camera progression without claiming identical
choreography.

Kling 3 runs with `sound=off`; Seedance 2 runs with
`generate_audio=false`. Creator OS then selects a duration-compatible Audio
Radar segment, embeds and verifies AAC, and binds the audio receipt to the exact
final MP4 SHA.

## Authenticated contract snapshot

The detailed read-only reconciliation is
[`HIGGSFIELD_CAPABILITY_AUDIT_2026-07-27.md`](./HIGGSFIELD_CAPABILITY_AUDIT_2026-07-27.md).
The installed CLI exposed authenticated account/Soul inspection,
model/workflow list/get, generation cost/create/get/wait, upload, download, and
credit transactions. The production adapter quotes the exact plan before
submission, checks the batch credit cap and balance, submits once, polls by
generation ID, downloads, probes, hashes, registers, and records immutable
lineage.

The exposed Veo 3.1 contract accepts dialogue text but no supplied creator-audio
file. It is EXPERIMENTAL as a visual/dialogue capability and must not be
presented as creator-voice preservation. The exposed Kling 3 Motion Control
combination is a REJECTED RECIPE after operator review; that decision does not
declare all future Higgsfield motion-transfer capabilities permanently closed.

Speak v2 has an official SDK contract at `/v1/speak/higgsfield`: an image URL,
WAV audio URL, prompt, `mid`/`high` quality, and a 5/10/15-second duration. The
current SDK type map supports the V2 subscribe client, while its README also
shows the deprecated V1 generate client. Account entitlement, cost, exact 9:16
dimensions, voice fidelity, re-encoding behavior, and ambient-audio behavior
remain unproved. It accepts an uploaded Soul-generated image structurally, not a
Soul ID directly, and is not an active production recipe.

Lipsync Studio, Kling Avatar, Higgsfield Animate/Recast/Character Swap, UGC
Factory, AI Influencer, relight, and inpaint were visible in UI/marketing or
requested for investigation but had no authenticated callable contract through
the inspected CLI, MCP, SDK, or Marketplace manifests. They are not production
recipes.

## Paid execution boundary

Normal production remains intent-first:

```bash
scripts/creator-os create \
  --creator stacey \
  --intent passive_selfie \
  --count 3 \
  --execution cloud \
  --accounts bennett_s33 \
  --audio embedded_trending \
  --max-credits 100 \
  --apply
```

Every job binds its creator, Soul ID, source asset/SHA, expanded prompt, pinned
model/tool, seed, quote, authorization, generation ID, provider receipt, output
SHA, technical QC, and final audio-bound media SHA. The command cannot schedule
or publish.

Historical WaveSpeed models, receipts, rows, hashes, and media remain readable
for audit and migration. They are absent from normal create, active paid
routing, fallbacks, help, and runtime credential requirements.

Reference URL intake and analysis use the same intent-first surface and stop
before any provider:

```bash
scripts/creator-os create \
  --creator stacey \
  --intent recreate_reel \
  --reference-url 'https://www.instagram.com/reel/...' \
  --recreate-mode auto \
  --through analyze \
  --audio auto
```

Dry-run media and derivatives are temporary. Authorized apply persists the
canonical Reference Factory source/anchor receipt and the Campaign Audio Radar
audio identity/occurrence. It makes no Higgsfield call. Creator OS never sends
the URL to a third-party downloader website.

The local-file recreation compatibility path remains:

```bash
scripts/creator-os create \
  --creator stacey \
  --intent recreate_reel \
  --reference-video /private/path/reference.mp4 \
  --reference-platform instagram \
  --reference-authorized \
  --count 1 \
  --execution cloud \
  --accounts bennett_s33 \
  --audio embedded_trending
```

The dry-run performs bounded local reference analysis and an authenticated
read-only quote, but issues no spend authorization and submits no generation.
`--apply` additionally requires `--reference-authorized`, an explicit finite
credit ceiling, and the existing signed spend authorization. One invocation is
limited to one reference, one output, and one Seedance request. Ambiguous
submission is retained for reconciliation and never retried blindly.

`reference_audio_required` deterministically selects and embeds the exact
reference-video audio segment, `embedded_trending` uses Audio Radar finishing,
and `silent_allowed` is explicit. A talking reference fails before quoting or
submission because supplied creator-voice preservation is not qualified.

## Future exact-voice validation plan

No paid validation was executed in this change. Seedance 2 accepts an audio
reference through the authenticated catalog, and Speak v2 accepts WAV
structurally through the official SDK, but neither fact proves that output
preserves the supplied creator voice unchanged. Both remain unproved and neither
is an active talking recipe.

A future operator-authorized validation may use one approved Stacey Soul still,
one 5-8 second script, and one exact creator-voice WAV. It must hash the still,
script, and WAV; obtain the live Seedance quote before submission; submit once
under a finite credit cap; retain ambiguous calls without retry; and leave
identity, lip-sync, voice preservation, naturalness, and would-post ratings
blank for operator review. Fewer than two comparable supplied-audio candidates
are currently exposed, so no honest multi-model comparison can yet be planned.
