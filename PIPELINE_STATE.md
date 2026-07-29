# Pipeline State

**Last reconciled:** 2026-07-29
**Durable architecture:** [`CREATOR_OS_SYSTEM_MAP.md`](./CREATOR_OS_SYSTEM_MAP.md)

This is the concise handoff document for a new ChatGPT or Codex session. Share
it together with [`CREATOR_OS_SYSTEM_MAP.md`](./CREATOR_OS_SYSTEM_MAP.md) and
[`docs/operations/creator_os_master_operating_spec.md`](./docs/operations/creator_os_master_operating_spec.md).
It is still a dated snapshot: provider balances, account state, schedule state,
post identities, and metric counts require fresh read-only status before an
operation.

## Current Git And Runtime Truth

| Layer | Current evidence |
|---|---|
| Three-mode feature baseline | PR [#557](https://github.com/adersouza/creator-os/pull/557) merged as `289dcf27ecca1a2ba81ddb6b7ddeb2c970d21983` |
| Authoritative current source | query `git rev-parse origin/main`; documentation-only commits may advance beyond the feature baseline |
| PR-head verification | affected, hygiene, and secret-scan checks succeeded |
| Exact current-SHA release/security | pending unless separately run against the final current source SHA |
| Machine runtime | clean detached checkout at prior SHA `817235bd1689e34e4f508c784a2251c3aa7fd16b` |
| Source/runtime alignment | not aligned; guarded promotion and runtime-health verification remain pending |
| Cleanup state | at reconciliation, no unrelated development worktrees or feature branches remained |

Run this before relying on the snapshot:

```bash
git fetch origin main
git rev-parse origin/main
scripts/creator-os status --json
/Users/aderdesouza/Developer/creator-os-runtime/scripts/creator-os status --json
```

## Pre-Promotion Runtime Health Snapshot

The 2026-07-29 local status check confirmed:

- clean, known checkout identity;
- virtual-environment entrypoints bound to their checkout;
- generated contracts match canonical schemas;
- private machine configuration exists with mode `0600`;
- canonical state, artifact, model, and log roots exist outside Git;
- Campaign, Reference, Reel manifest, and render-queue databases resolve under
  `~/.creator-os/state`;
- the configured Campaign database is readable and contains the Stacey learning
  cohort campaign;
- the latest focused state backup passed integrity verification, and runtime
  backup preserves historical symlinks without dereferencing retired targets;
- runtime remains clean at `817235bd1689e34e4f508c784a2251c3aa7fd16b`;
- merged source is now `289dcf27ecca1a2ba81ddb6b7ddeb2c970d21983`,
  so the next runtime operation is an explicit guarded promotion.

Provider readiness and the ThreadsDashboard handshake were `NOT_RUN` in this
snapshot because only local read-only status was requested. Do not infer a live
provider or product seam pass.

## Creator Identity And Inventory Snapshot

Authenticated read-only checks confirmed:

| Creator | Completed Soul 2 | Approved images | Imported images | Imported videos | Other |
|---|---:|---:|---:|---:|---:|
| Stacey | yes | 3 | 131 | 335 | 1 guarded review package |
| Larissa | yes | 3 | 0 | 208 | 0 |
| Lola | yes | 3 | 0 | 203 | 0 |

Stacey has one canonical Soul 2 identity and three approved creator images.
Older test Elements remain provider-side historical inventory but do not
participate in active three-mode routing.

Larissa and Lola now each have a deliberately small approved set: one close,
one mid-body, and one wider/full-body source. Every selected file is
creator-bound, byte-present, SHA-valid, and backed by a
`source_approval_decided` audit event. The older 208/203 imported rows are
videos, not still images; they were not bulk-approved.

## Implemented And Source-Verified Capability

### Supported

- three-mode `creator-os create`;
- Higgsfield as the only normal visual-generation provider;
- direct Soul 2 still generation with explicit identity and lineage;
- free deterministic static MP4;
- `calm_animation` through pinned Kling 3 Turbo at 720p;
- `recreate_reel` through approved calm Kling or structural Seedance 2 Fast
  routing;
- provider-generated sound disabled for passive motion;
- live private Audio Radar cache and verified embedded AAC;
- exact final MP4/audio receipt binding;
- ContentForge headless QC;
- exact-SHA human creative approval;
- validated HMAC draft handoff;
- existing finished-media reconciliation;
- fixed-asset learning cohorts;
- versioned knowledge refresh and supervised recommendation consumption;
- Content Director shadow/supervised planning;
- guarded exact-SHA runtime promotion.

### Experimental

- URL or local-file `recreate_reel` intake, exact audio retention, clean-frame
  analysis, OCR overlay inventory, timecoded structural motion/camera analysis,
  anchor planning, and bounded quote planning;
- OpenAI-authored Soul anchor, Kling 3 Turbo, and Seedance 2 Fast prompts bound
  to the approved creator image and sampled reference frames;
- prompt-only recreation behind anchor and operator approval gates. The private
  Reel remains hashed lineage/audio evidence and is not sent to the video model.

### Unresolved

- exact supplied-voice talking selfie;
- exact motion copy and dance transfer; prompt-authored dancing remains available;
- exact supplied-voice talking motion copy.

### Historical or advanced only

- WaveSpeed normal execution;
- local Wan/LTX/LongCat;
- Arena and Router;
- retired Kling-only and motion-edit modes.

Historical receipts, rows, media, hashes, and lineage remain readable.

## Current Audio Snapshot

The runtime read-only Audio Radar status at reconciliation time reported:

- 17 active/resolved active tracks;
- 38 playable cache objects;
- 130,559,347 cached bytes;
- 135 catalog rows;
- one retained production selection;
- zero publication-linked performance rollups.

The latest recorded refresh was partial because provider availability is
independent by design. A partial provider result does not falsely age or prune
the library.

Refresh before relying on these counts:

```bash
scripts/creator-os audio status
```

## Current Planning Snapshot

The Campaign database contained:

- an approved three-day Stacey fixed-asset learning-cohort plan;
- a separate draft Stacey growth plan.

This proves local Campaign state, not ThreadsDashboard drafts, schedules, or
Instagram publication. Fixed-cohort windows are proposals for consecutive
eligible account-local days with `learnedTiming=false`; ThreadsDashboard
remains final scheduling authority.

## Still Separate And Operator-Gated

- runtime promotion when source and runtime differ;
- paid provider apply;
- creative approval;
- draft export;
- ThreadsDashboard scheduling and publication;
- learning recommendation approval;
- real 24-hour/72-hour adaptive proof.

The repository contains no Creator OS schedule or publish command.

## Evidence Boundary

Use these exact claims:

- Passing local or PR-head checks proves source verification in that
  checkout/tree.
- The merge commit on `origin/main` proves merged status.
- Exact-target-SHA release and security workflows prove released status.
- `creator-os promote` plus its receipt proves runtime promotion.
- A Higgsfield generation ID and output SHA prove one provider result.
- a Creative Approval proves operator acceptance of one exact final SHA.
- an HMAC draft receipt proves handoff only.
- a reconciled Instagram media ID proves publication.
- metric-history rows prove observations.
- an approved recommendation plus a changed decision receipt proves learning
  affected an allowed later choice.

Do not collapse them into a generic “working” status.
