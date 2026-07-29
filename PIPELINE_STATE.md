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
| Reconciliation source before this local change | clean `main` and `origin/main` at `817235bd1689e34e4f508c784a2251c3aa7fd16b` |
| Authoritative source | query `git rev-parse origin/main`; this documentation commit necessarily advances the recorded baseline |
| Hosted release/security | required on the exact final merge SHA before runtime promotion |
| Machine runtime at reconciliation | clean checkout at `817235bd1689e34e4f508c784a2251c3aa7fd16b` |
| Alignment proof | source and runtime status both resolved to the exact same clean SHA |
| Current local work | prompt-driven recreation changes are uncommitted and not runtime-promoted |

Run this before relying on the snapshot:

```bash
git fetch origin main
git rev-parse origin/main
scripts/creator-os status --json
/Users/aderdesouza/Developer/creator-os-runtime/scripts/creator-os status --json
```

## Current Read-Only Health Snapshot

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
- the failed incomplete 8.3 GB runtime backup was removed after a focused
  source-approval database backup passed integrity verification;
- runtime backup preserves historical symlink records instead of dereferencing
  missing retired-media targets;
- source and runtime were clean and aligned at
  `817235bd1689e34e4f508c784a2251c3aa7fd16b` before the current local work.

Provider readiness and the ThreadsDashboard handshake were `NOT_RUN` in this
snapshot because only local read-only status was requested. Do not infer a live
provider or product seam pass.

## Creator Identity And Inventory Snapshot

Authenticated read-only checks confirmed:

| Creator | Completed Soul 2 | Completed private Element | Approved images | Imported images | Imported videos | Other |
|---|---:|---:|---:|---:|---:|---:|
| Stacey | yes | yes | 3 | 131 | 335 | 1 guarded review package |
| Larissa | yes | yes | 3 | 0 | 208 | 0 |
| Lola | yes | yes | 3 | 0 | 203 | 0 |

Stacey has one trained Soul and several old single-image Elements created during
earlier tests. Those numbered/test Elements are not extra trained identities.
Creator OS binds the canonical Stacey Element; the unused account objects do
not participate in routing.

Larissa and Lola now each have a deliberately small approved set: one close,
one mid-body, and one wider/full-body source. Every selected file is
creator-bound, byte-present, SHA-valid, and backed by a
`source_approval_decided` audit event. The older 208/203 imported rows are
videos, not still images; they were not bulk-approved.

## Current Product Capability

### Supported

- intent-first `creator-os create`;
- Higgsfield as the only normal visual-generation provider;
- direct Soul 2 still generation with explicit identity and lineage;
- free deterministic static MP4;
- product-pinned Higgsfield Kling 3 Turbo or Seedance 2 passive motion;
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

## Current Repository Weight

Tracked source was approximately 16.88 MiB before the current documentation
deduplication and 16.69 MiB afterward. Runtime environments, private media,
Audio Radar bytes, QC models, databases, receipts, and backups live outside
tracked source and must not be treated as repository bloat.

Repository cleanup removes merged development worktrees and their local/remote
branches after proving their PR or patch landed. It does not delete the runtime
checkout, canonical state, media, model files, receipts, databases, backups, or
rollback evidence.

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
