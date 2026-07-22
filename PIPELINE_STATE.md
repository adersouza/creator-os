# Pipeline State

**Last updated:** 2026-07-21.

This page records current source capability and the evidence boundary. The
durable ownership map is [`CREATOR_OS_SYSTEM_MAP.md`](./CREATOR_OS_SYSTEM_MAP.md).
Volatile source/runtime SHAs, account state, provider balances, post receipts,
and metric counts belong in fresh status output or dated run evidence—not in
this file.

## Current Architecture

Creator OS is the canonical headless production-source monorepo:

```text
Reference Factory teaches
Reel Factory creates
Campaign Factory decides
ContentForge judges and blocks
Pipeline Contracts validates
ThreadsDashboard receives drafts, publishes, and reports performance
```

Campaign Factory is the sole Creator OS control plane. Reel Factory,
Reference Factory, and ContentForge remain narrow workers. ThreadsDashboard is
an external product repository and the only owner of the product UI, accounts,
approvals, scheduling, publishing, and production analytics.

The pinned machine runtime remains a separate checkout. Merging Creator OS
source does not update, restart, or prove that runtime. Runtime promotion is an
explicit, separately verified operation.

## Supported Source Capability

- `scripts/creator-os` is the supported operator surface. Package CLIs are
  developer implementation boundaries, not alternate control planes.
- Direct Higgsfield reference-image Soul generation with explicit identity and
  lineage is the active still path.
- Accepted stills can receive a free static MP4. Other motion modes require
  explicit mode selection and their declared cost/approval gates.
- Overlay text is placement-scored, rendered by Reel Factory, and fails closed
  when no safe lane exists. Post captions remain a separate Campaign/
  ThreadsDashboard artifact.
- ContentForge is the direct headless QC and evidence boundary for collision,
  OCR, placement, readability, watchability, and media integrity.
- Campaign Factory is the only owner of campaign state, spend authorization,
  asset readiness, assignment, draft construction, and measured learning.
- Draft payloads are contract-validated and HMAC-signed. Creator OS stops at
  draft handoff and has no scheduling or publishing command.
- Performance sync accepts genuine ThreadsDashboard/Instagram observations.
  Missing publication identity or metrics are never converted to zero.
- Canonical schemas exist only under
  `packages/pipeline_contracts/pipeline_contracts/schemas`; generated
  TypeScript is packaged as the immutable `@creator-os/pipeline-contracts`
  consumer artifact. External repositories do not copy the schema tree.

## Repository Hygiene

- GitHub Actions workflows live only in repository-root `.github/workflows/`.
  Package-local workflow copies were inert in the monorepo and are removed.
- Retired Reel grid, six-panel, cropped-panel, and prompt-generation execution
  paths are removed rather than hidden behind flags. Their history remains in
  Git.
- The empty Reel `experiments` package and obsolete grid guide are removed.
  Explicit reference-analysis experiments belong in Reference Factory and
  remain isolated from active generation.
- Redundant standalone Campaign wrappers are removed when the supported package
  CLI or combined smoke path owns the same behavior.
- Operational databases, media, model weights, receipts, backups, and migration
  evidence are not source-code cleanup candidates.

## Runtime And Operational Evidence

Use fresh commands for current truth:

```bash
git fetch origin main
git rev-parse origin/main
/Users/aderdesouza/Developer/creator-os-runtime/scripts/creator-os status --json
/Users/aderdesouza/Developer/creator-os-runtime/scripts/creator-os \
  status --live-read-only --json
```

Record source SHA, runtime SHA, checkout cleanliness, database integrity,
provider-probe results, and live-seam trace IDs separately. A source verifier
does not prove runtime promotion. A read-only handshake does not prove a draft,
schedule, post, or metric row.

## Still Operator-Gated

- Paid generation requires an explicit mode, target, workspace, confirmation,
  and finite credit cap.
- Reference Gold/Maybe/Ignore labels remain human decisions.
- Draft export requires explicit apply and remains draft-only.
- ThreadsDashboard approval, native-audio proof, scheduling, and publishing are
  external product actions.
- Trial Reel eligibility requires current account projection and OAuth/capability
  evidence; `unknown` is not autonomous eligibility.
- Learning closure requires genuine publication identity and equal-age metric
  history—not command, upload, queue, or dispatch success.
- Scale, outage, provider-console, OAuth, and deployment proofs remain separate
  operational work.

## Verification Boundary

`make verify`, contract checks, architecture checks, artifact checks, and secret
scans prove the checked source tree. CI proves the exact PR SHA. Neither proves
paid-provider readiness, runtime promotion, production handshake, publishing,
notification delivery, or metric collection unless those checks are separately
and explicitly run.
