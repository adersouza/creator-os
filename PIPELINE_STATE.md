# Pipeline State

**Last reconciled:** 2026-07-28
**Durable architecture:** [`CREATOR_OS_SYSTEM_MAP.md`](./CREATOR_OS_SYSTEM_MAP.md)

This is a dated source/runtime snapshot. Provider balances, account state,
schedule state, post identities, and metric counts still require fresh
read-only status before an operation.

## Current Git And Runtime Truth

| Layer | Current evidence |
|---|---|
| `origin/main` | `f844f4b6da87bb50c67582179ffce77e512bd14a` |
| Hosted release/security | exact-SHA evidence authorized the recorded promotion; not re-run during this docs cleanup |
| Machine runtime | clean detached checkout at `f844f4b6da87bb50c67582179ffce77e512bd14a` |
| Source/runtime alignment | **aligned** at the snapshot SHA |
| Runtime health | the promotion recorded 9/9 read-only health; this reconciliation reran 7 local checks successfully and left 2 network probes `NOT_RUN` |
| Development worktrees | multiple retained development worktrees exist; their presence is not runtime state |

Run this before relying on the snapshot:

```bash
git fetch origin main
git rev-parse origin/main
scripts/creator-os status --json
/Users/aderdesouza/Developer/creator-os-runtime/scripts/creator-os status --json
```

## Current Read-Only Health Snapshot

The 2026-07-28 runtime status check confirmed:

- clean, known checkout identity;
- virtual-environment entrypoints bound to their checkout;
- generated contracts match canonical schemas;
- private machine configuration exists with mode `0600`;
- canonical state, artifact, model, and log roots exist outside Git;
- Campaign, Reference, Reel manifest, and render-queue databases resolve under
  `~/.creator-os/state`;
- the configured Campaign database is readable and contains the Stacey learning
  cohort campaign;
- source and runtime are aligned at the exact SHA above.

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

- URL or local-file `recreate_reel` intake, analysis, anchor planning, and
  bounded quote planning;
- passive, structural Seedance, experimental Motion Control, and first/last
  recreation modes behind their explicit approval gates.

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

The runtime read-only Audio Radar status at reconciliation time reported:

- 17 active/resolved active tracks;
- 26 playable cache objects;
- approximately 129 MB cached bytes;
- 127 catalog rows;
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

Tracked source was approximately 16.88 MiB before the current documentation
deduplication and 16.69 MiB afterward. Runtime environments, private media,
Audio Radar bytes, QC models, databases, receipts, and backups live outside
tracked source and must not be treated as repository bloat.

This cleanup removes only redundant tracked plans/audits and duplicated
documentation. It does not delete local environments, canonical state, media,
model files, receipts, worktrees, or rollback evidence.

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
