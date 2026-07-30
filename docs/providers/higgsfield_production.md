# Higgsfield Production

Higgsfield is the only visual-generation provider in normal Creator OS
production. The authenticated contract, not product-page language, determines
what Creator OS can offer.

## Supported recipes

| Intent | Pinned implementation | Product status |
| --- | --- | --- |
| `soul_static` | Soul 2.0 still plus deterministic local static MP4 | SUPPORTED |
| `passive_selfie` | Kling 3 Turbo (`kling3_0_turbo`) or Seedance 2 (`seedance_2_0`) with an OpenAI-authored model-specific prompt | SUPPORTED |
| `recreate_reel` | Seedance 2 Fast (`seedance_2_0`, `mode=fast`) with one approved creator anchor and an OpenAI-authored action/timing prompt | EXPERIMENTAL |
| `talking_selfie` | No exact supplied-audio contract exposed | UNRESOLVED |
| `motion_copy` / `dance` | No operator-approved distinct transfer recipe | UNRESOLVED |
| `talking_motion` | Requires both approved motion and supplied-audio lip-sync | UNRESOLVED |

The passive recipe is pinned by product configuration. Ordinary operators give
creator intent, not provider/model identifiers. A failed or ambiguous
Higgsfield call is retained for reconciliation and is never silently retried
or routed to WaveSpeed.

`recreate_reel` is a bounded prompt-driven recreation, not precision motion copy.
It retains the private reference path and SHA, extracts clean frames for analysis,
records source writing separately with timestamped OCR evidence, and obtains a
contract-shaped motion-only timeline. OpenAI observes the approved creator
image and chronological Reel frames, then writes the Soul anchor prompt, the
executable Seedance prompt, and a non-executable Kling planning prompt. The
Seedance request receives the approved anchor as an image reference, the
authorized inspiration Reel as a video reference for broad motion/structure
conditioning, and the creator reference Element through its prompt token. It
does not consume the Soul ID directly. Soul generation is text-only so its
prompt is not discarded by reference-image force enhancement.

The authenticated CLI contract exposes `seedance_2_0` with `mode=fast`; Fast is
a mode of that model, not a separate model ID. Recreation is fixed to 9:16,
480p, high bitrate, 4–15 seconds, and `generate_audio=false`. The prompt
explicitly binds the approved anchor as the exact person and includes the
timestamped motion/camera breakdown. OCR-recognized source writing remains
evidence and is stripped from the generation prompt so the clean video can use
different Reel Factory overlays later. Seedance Mini remains blocked for
identity-critical recreation after two operator-rejected Stacey outputs.

The authenticated account currently has completed Soul 2 identities and
completed character Elements for Stacey, Larissa, and Lola. Creator OS resolves
those private bindings by creator name and fails closed if either identity
binding is absent or mismatched.

Kling 3 Turbo output is treated as silent; Seedance 2 runs with
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
  --mode calm_animation \
  --style passive_selfie \
  --count 3 \
  --execution cloud \
  --accounts bennett_s33 \
  --audio embedded_trending_required \
  --max-credits 100 \
  --apply
```

Every job binds its creator, Soul ID, source asset/SHA, expanded prompt, pinned
model/tool, seed, quote, authorization, generation ID, provider receipt, output
SHA, technical QC, and final audio-bound media SHA. The command cannot schedule
or publish.

OpenAI prompt planning is cached before Higgsfield quoting by exact input hashes,
model, intent, builder version, instruction, and response schema. Its receipt
retains token usage and dollar-cost status separately from Higgsfield credits;
an unexposed dollar cost remains unknown. Cache misses require the current
create operation's explicit `--apply` authorization, are limited to one prompt
call, and record that authorization plus the current-run call count.

Historical WaveSpeed models, receipts, rows, hashes, and media remain readable
for audit and migration. They are absent from normal create, active paid
routing, fallbacks, help, and runtime credential requirements.

Reference URL intake and analysis use the same intent-first surface and stop
before any paid visual-generation request:

```bash
scripts/creator-os create \
  --creator stacey \
  --mode recreate_reel \
  --reference-url 'https://www.instagram.com/reel/...' \
  --creator-image /private/path/approved-creator.png \
  --recreate-mode auto \
  --through analyze \
  --audio auto
```

Dry-run media and derivatives are temporary. A locally authenticated Gemini CLI
may make one read-only video-analysis call to produce the timestamped structural
contract; its cost is recorded as unknown when the CLI does not expose it.
Unavailable or invalid semantic analysis remains explicit and never invents
actions. Authorized apply persists the
canonical Reference Factory source/anchor receipt and the Campaign Audio Radar
audio identity/occurrence. It makes no Higgsfield generation call. Creator OS never sends
the URL to a third-party downloader website.

Without `--through analyze`, the same command adds a zero-paid-call recreation
plan: stable run ID, classification evidence, bounded excerpt, one/two
scene-matched Soul 2 anchor requests, audio decision, exact/bounded quotes,
mode-specific request, review package, and explicit blockers. The configured
Soul identity is represented only by a fingerprint; the Soul ID is never
printed.

The local-file recreation path is identical:

```bash
scripts/creator-os create \
  --creator stacey \
  --mode recreate_reel \
  --reference-video /private/path/reference.mp4 \
  --creator-image /private/path/approved-creator.png \
  --reference-platform instagram \
  --reference-authorized \
  --recreate-mode auto \
  --audio auto
```

The recreation contracts are:

- `calm`: Kling 3 Turbo at 720p from the approved anchor and OpenAI prompt;
- `structural`: Seedance 2 Fast at 480p/high bitrate from the approved anchor and
  OpenAI prompt, with generated audio off;
- `auto`: select between those two from the reference analysis. Motion Control
  and old compatibility aliases are not exposed.

Dry-run may call authenticated cost/catalog surfaces but creates no spend
authorization and submits no generation. Paid steps require the existing
finite-credit authorization and are never blindly retried after ambiguity.

`--audio auto` requires creator/reference audio for talking, requires reference
audio for synchronized dance, prefers an explicit comparison for eligible
structural/motion reference audio, and defaults passive work to Audio Radar.
Provider-generated audio remains off. Final audio still requires exact segment,
canonical PCM, final MP4 SHA, and AAC binding evidence.

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
