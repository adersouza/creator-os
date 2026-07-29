# Creator OS

Creator OS is the headless content-production system that turns approved creator
sources and intent into review-ready Reels with exact visual, audio, QC, and
lineage evidence. It hands approved drafts to ThreadsDashboard, which owns the
product UI, account health, scheduling, publication, and production analytics.

Start with:

- [`CREATOR_OS_SYSTEM_MAP.md`](./CREATOR_OS_SYSTEM_MAP.md) for the complete
  architecture and authority map;
- [`PIPELINE_STATE.md`](./PIPELINE_STATE.md) for the current dated
  source/runtime snapshot;
- [`docs/runbooks/creator_os_operator_journey.md`](./docs/runbooks/creator_os_operator_journey.md)
  for the normal operator sequence;
- [`docs/README.md`](./docs/README.md) for documentation ownership.

## Current Product

Normal production is intent-first and Higgsfield-only:

```text
approved creator source
  -> creator intent
  -> pinned Higgsfield Soul/passive recipe
  -> independent retained jobs
  -> technical QC
  -> Audio Radar selection and verified AAC
  -> operator exact-SHA approval
  -> validated HMAC draft
  -> ThreadsDashboard schedule/publish
  -> real Instagram metrics
  -> supervised learning
```

Stacey, Larissa, and Lola each resolve to a distinct completed Soul 2 identity.
Reference-Reel structural recreation additionally resolves the matching private
creator Element. Missing or mismatched identity bindings fail before quoting or
paid submission.

Supported:

- Higgsfield Soul 2 stills;
- deterministic static MP4s;
- operator-approved Higgsfield Kling 3 or Seedance 2 passive motion;
- strict existing-media intake;
- experimental one-output Seedance structural reference-Reel recreation;
- live private Audio Radar discovery, caching, segmenting, embedding, and final
  MP4 binding;
- ContentForge technical QC;
- supervised content planning and learning consumption.

Unresolved:

- exact supplied-voice talking Reels;
- motion copy and dance transfer;
- talking motion copy.

WaveSpeed, local Wan/LTX, Arena, and Router are not normal production routes or
fallbacks. Historical evidence and advanced research tools remain readable.

## Create Content

Dry-run first:

```bash
scripts/creator-os create \
  --creator stacey \
  --intent passive_selfie \
  --count 3 \
  --execution cloud \
  --accounts bennett_s33 \
  --audio embedded_trending \
  --max-credits 70
```

After reviewing the exact jobs and bounded quote, add `--apply`.

Normal create:

- resolves only approved creator-matched sources;
- checks source bytes and intent compatibility before paid submission;
- chooses the product-pinned Higgsfield recipe internally;
- creates one retained identity, seed, request, output, and receipt per job;
- preserves partial success;
- never blindly retries an ambiguous submission;
- disables provider-generated sound for passive motion;
- selects and embeds real Audio Radar audio;
- never exports, schedules, or publishes.

The passive recipe is selected by product configuration from:

- `higgsfield_kling3_i2v`;
- `higgsfield_seedance2_i2v`.

Provider and model identifiers are not normal operator inputs.

## Review, Approve, And Export

```bash
scripts/creator-os review --campaign <campaign>

scripts/creator-os approve \
  --campaign <campaign> \
  --rendered-asset-id <asset-id> \
  --user-id <threadsdashboard-user-id> \
  --approved-by <operator>

scripts/creator-os export \
  --dry-run \
  --campaign <campaign> \
  --user-id <threadsdashboard-user-id> \
  --rendered-asset-id <asset-id> \
  --max-drafts 1
```

Approval binds the exact final MP4 SHA. Export apply creates only validated,
signed draft handoff evidence. Creator OS deliberately has no scheduling or
publishing command.

## Existing Finished Media

Use the existing-media surface only when the final MP4 has retained Creator OS
source, generation, audio, QC, and final-media lineage:

```bash
scripts/creator-os media intake-existing \
  --manifest /absolute/private/path/video.intake.json \
  --dry-run
```

Dry-run writes nothing. Apply reconciles one canonical asset without copying,
re-encoding, replacing audio, generating, exporting, scheduling, or publishing.

## Audio Radar

```bash
scripts/creator-os audio status

scripts/creator-os audio refresh \
  --region US \
  --max-new 10 \
  --max-active 30 \
  --apply
```

The refresh uses SocialCrawl TikTok discovery, optional SocialCrawl Instagram,
optional Creative Center enrichment, and TikLiveAPI resolution. It is bounded
by `--max-new`, safely handles provider outages, and never creates a Reel or
publishes.

Production uses the active private cache. It selects a duration-compatible,
cooldown-safe track segment, embeds AAC, probes the streams, hashes the exact
processed segment and final MP4, and updates the canonical asset binding.

## Reference-Reel Intake And Planning

Reference URLs can be downloaded and analyzed without selecting or calling a
provider:

```bash
scripts/creator-os create \
  --creator stacey \
  --intent recreate_reel \
  --reference-url 'https://www.instagram.com/reel/...' \
  --recreate-mode auto \
  --through analyze \
  --audio auto
```

The dry-run uses private temporary media and makes no persistent reference or
audio-library mutation. `--apply --reference-authorized` persists one
deduplicated Reference Factory identity, receipt-linked frame derivatives, an
independently selected scene anchor, and exact reference-audio evidence. It
does not generate, export, schedule, or publish. Instagram, TikTok, YouTube
Shorts, direct HTTP(S) media, and the local-file fallback are supported through
Creator OS's own yt-dlp path; third-party downloader sites are not used.

Omit `--through analyze` to receive the deterministic recreation plan. Creator
OS classifies the source, chooses a bounded excerpt, proposes one or two
Soul 2 anchors, selects a truthful mode, applies `--audio auto`, and obtains
read-only quotes without submitting a paid request. AUTO never silently submits
Motion Control, structural Seedance, first/last, talking, multi-shot, or
multi-person work. Soul IDs and internal provider choices remain private.

The local-file recreation path uses the same planner and requires explicit
reference authorization. Supported mode truth is explicit: passive continues
through accepted Kling 3 motion after an approved anchor; Motion Control is
experimental; Seedance 2 is structural recreation rather than identity
replacement; first/last is a coherent transition rather than exact motion
copy; and talking remains blocked as `talking_route_not_entitled`. Every video
request remains blocked until the Soul anchor has human identity and
`WOULD_USE_AS_ANCHOR` approval.

## Supervised Planning

```bash
scripts/creator-os plan \
  --creator stacey \
  --horizon 7d \
  --accounts bennett_s33 \
  --goal growth \
  --mode shadow \
  --max-credits 70 \
  --dry-run
```

The Content Director is a Campaign Factory domain, not another service. It may
order approved inventory and patterns, propose account-local windows, and
delegate approved work to the normal create lane. ThreadsDashboard remains the
final scheduling authority.

Healthy eligible accounts target their configured daily cadence. Reduced
cadence is for warming, health/platform limits, inventory shortages, or an
explicit operator choice. Fixed three-asset cohorts propose three consecutive
eligible days and do not wait for one post's 72-hour observation before the
next post.

## Supervised Learning

```bash
scripts/creator-os learning-refresh --dry-run
scripts/creator-os learning-review list
```

Production influence requires at least three real, lineage-valid,
publication-linked outcomes in the same 24-hour or 72-hour observation cohort
and an explicit operator approval. One-hour evidence is advisory.

Learning may reorder:

- already-approved sources;
- imported approved prompt/hook patterns;
- Audio Radar soft ranking when exact publication-linked audio evidence exists.

Learning cannot change creator identity, Soul ID, provider, Kling/Seedance
configuration, source approval, hard QC, spend, account authorization, or
publication eligibility.

## One Operator Command

`scripts/creator-os` is the supported root surface:

```text
status
sources
media
plan
doctor
performance-sync
learning-refresh
learning-review
reference-refresh
audio
create
video-bakeoff
quality-benchmark
generate
review
approve
export
advanced
promote
```

Important boundaries:

- `status` is read-only;
- `status --live-read-only` may use network/provider probes but performs no
  generation or product writes;
- `create` is intent-first normal production;
- `generate` is an advanced explicit-mode compatibility surface;
- `advanced` contains local-model, queue, Arena, Router, benchmark, and analyzer
  diagnostics;
- `export` creates drafts only;
- `promote` changes only the pinned Creator OS runtime.

## Contracts

Canonical schemas live only at:

```text
packages/pipeline_contracts/pipeline_contracts/schemas
```

For a contract change:

```bash
pnpm sync:contracts
pnpm check:contracts
```

Never hand-edit
`packages/pipeline_contracts/typescript/generated-schemas.ts`. ThreadsDashboard
consumes the immutable released `@creator-os/pipeline-contracts` package; it
does not copy schemas from this repository.

## Runtime

Source and runtime are separate checkouts:

```text
/Users/aderdesouza/Developer/creator-os
/Users/aderdesouza/Developer/creator-os-runtime
```

Merging source does not promote runtime. Use the guarded promotion command only
with exact merged-main authorization and exact-SHA release/security evidence.
Promotion preserves canonical machine state under `~/.creator-os` and does not
generate, export, schedule, publish, or deploy ThreadsDashboard.

## Install And Verify

Use Node 24 and frozen dependencies:

```bash
pnpm install --frozen-lockfile
uv sync --all-extras --all-packages --frozen
```

Development verification:

```bash
make affected
pnpm check:all
pnpm security:secrets
```

Broader source verification:

```bash
make verify
```

Exact-SHA release and security workflows remain separate hosted evidence.
Passing source checks never proves runtime promotion, provider readiness,
publication, or real learning.
