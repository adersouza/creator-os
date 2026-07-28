# Pipeline State

**Last reconciled:** 2026-07-28
**Durable architecture:** [`CREATOR_OS_SYSTEM_MAP.md`](./CREATOR_OS_SYSTEM_MAP.md)

This is a dated source/runtime snapshot. Provider balances, account state,
schedule state, post identities, and metric counts still require fresh
read-only status before an operation.

## Current Git And Runtime Truth

| Layer | Current evidence |
|---|---|
| Creator OS source | clean reviewed source at `e9b05663718013dc4932c24cf9dd175b2c97fc00` when this snapshot was written |
| `origin/main` | matched the source SHA above |
| Hosted release | exact-SHA `release` and `sbom` succeeded |
| Hosted security | Secret scan, CodeQL JavaScript/TypeScript, CodeQL Python, Trivy, and Scorecard succeeded |
| Open Creator OS PRs | none at reconciliation time |
| Source worktrees | source `main` plus the active detached runtime only |
| Machine runtime | clean detached checkout at `649a3e8d0a198487a2ccbc110be75f5adfa0deb4` |
| Source/runtime alignment | **not aligned**; promotion was deliberately not part of the cleanup/docs work |

Run this before relying on the snapshot:

```bash
git fetch origin main
git rev-parse origin/main
scripts/creator-os status --json
/Users/aderdesouza/Developer/creator-os-runtime/scripts/creator-os status --json
```

## Current Read-Only Health Snapshot

The 2026-07-28 source and runtime status checks both confirmed:

- clean, known checkout identity;
- virtual-environment entrypoints bound to their checkout;
- generated contracts match canonical schemas;
- private machine configuration exists with mode `0600`;
- canonical state, artifact, model, and log roots exist outside Git;
- Campaign, Reference, Reel manifest, and render-queue databases resolve under
  `~/.creator-os/state`;
- the configured Campaign database is readable and contains the Stacey learning
  cohort campaign.

Provider readiness and the ThreadsDashboard handshake were `NOT_RUN` in this
snapshot because only local read-only status was requested. Do not infer a live
provider or product seam pass.

## Current Product Capability

### Supported

- intent-first `creator-os create`;
- Higgsfield as the only normal visual-generation provider;
- direct Soul 2 still generation with explicit identity and lineage;
- free deterministic static MP4;
- product-pinned Higgsfield Kling 3 or Seedance 2 passive motion;
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

- count-one structural `recreate_reel` through approved creator image plus
  authorized private reference video and pinned Seedance 2.

### Unresolved

- exact supplied-voice talking selfie;
- motion copy and dance transfer;
- talking motion copy.

### Historical or advanced only

- WaveSpeed normal execution;
- local Wan/LTX/LongCat;
- Arena and Router;
- retired Kling-only and motion-edit modes.

Historical receipts, rows, media, hashes, and lineage remain readable.

## Current Audio Snapshot

The read-only Audio Radar status at reconciliation time reported:

- 17 active/resolved active tracks;
- 25 playable cache objects;
- approximately 129 MB cached bytes;
- 126 catalog rows;
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

## Current Repository Weight

After the 2026-07-28 cleanup:

- source checkout: approximately 3.0 GB;
- tracked repository content: approximately 16.65 MiB;
- root `node_modules`: approximately 228 MB;
- Python environment: approximately 1.8 GB;
- retained root `tmp` evidence: approximately 72 MB;
- Reel/source/media/QC package data: approximately 759 MB.

The retained weight is primarily the active Python environment, QC models,
audio, canonical media, and referenced evidence. These are not dead source
code. The cleanup removed unreferenced scratch generations, an abandoned E2E
sandbox, an obsolete split-repository copy, stale dependency installs, merged
branches, and completed worktrees.

## Still Separate And Operator-Gated

- runtime promotion;
- paid provider apply;
- creative approval;
- draft export;
- ThreadsDashboard scheduling and publication;
- learning recommendation approval;
- real 24-hour/72-hour adaptive proof.

The repository contains no Creator OS schedule or publish command.

## Evidence Boundary

Use these exact claims:

- `make affected` or `pnpm check:all` proves source checks.
- A successful hosted release proves the exact merged source SHA.
- `creator-os promote` plus its receipt proves runtime promotion.
- A Higgsfield generation ID and output SHA prove one provider result.
- a Creative Approval proves operator acceptance of one exact final SHA.
- an HMAC draft receipt proves handoff only.
- a reconciled Instagram media ID proves publication.
- metric-history rows prove observations.
- an approved recommendation plus a changed decision receipt proves learning
  affected an allowed later choice.

Do not collapse them into a generic “working” status.
