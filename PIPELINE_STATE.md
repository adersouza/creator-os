# Pipeline State

**Last updated:** 2026-07-15.

This ledger separates source capability from runtime and live proof. The
durable architecture is in [`CREATOR_OS_SYSTEM_MAP.md`](./CREATOR_OS_SYSTEM_MAP.md).

## Source Architecture

Creator OS is a headless monorepo:

```text
Reference Factory teaches
Reel Factory creates
Campaign Factory decides
ContentForge judges and blocks
Pipeline Contracts validates
ThreadsDashboard receives drafts, publishes, and reports performance
```

ThreadsDashboard is a separate product repository. Creator OS has no product
dashboard and no scheduling or publishing command.

The supported operator surface is `scripts/creator-os`. Flat Reel module
facades, `scripts/run/*` aliases, orphaned browser/operator code, and unused
grid/benchmark experiments have been removed. Campaign Factory retains a
headless authenticated JSON API; Reference Factory retains its manual labeling
review server.

## Capability State

- Direct Higgsfield reference-image Soul generation and asset lineage remain
  the active still path.
- Every accepted still can receive a local zero-provider-cost static MP4.
- Motion edit is local and optional. Kling is separately approved, paid, and
  capped.
- Caption overlays remain placement-scored and fail closed when no safe lane
  exists.
- ContentForge remains the separate headless QC/evidence boundary.
- Campaign Factory remains the only campaign control brain.
- Draft payloads remain contract-validated and HMAC-signed; export stops at
  draft handoff.
- Performance sync and `learning_fanout.py` remain the measured return path.
- Canonical schemas remain only under
  `packages/pipeline_contracts/pipeline_contracts/schemas`; the root Python
  package is an import shim only.

## Runtime Snapshot At This Update

The cleanup work is source-only and is not a runtime promotion.

- Source base `origin/main`: `2d605a3bc2ce7bd9997d55517c1f3fcb03647dcb`.
- Pinned runtime checkout observed at the same SHA.
- Latest recorded performance sync observed successful at
  `2026-07-15T07:42:38Z`.
- The configured Campaign SQLite database was readable in read-only mode and
  contained `stacey_learning_cohort_v1`.
- Provider readiness was **not run**.
- A live ThreadsDashboard handshake was **not run**.
- No runtime checkout, LaunchAgent, environment file, database, provider,
  draft, schedule, publish state, or production service was changed.

Use `scripts/creator-os status` for a fresh report. This snapshot will become
stale; do not use it as later runtime proof.

## Still Operator-Gated

- Paid generation and provider smokes require an explicit target, workspace,
  confirmation, and finite credit cap.
- Reference gold/maybe/ignore labels remain human decisions.
- Draft export requires explicit apply and remains draft-only.
- ThreadsDashboard approval, native-audio proof, scheduling, and publishing
  remain external product actions.
- Real performance-learning closure requires measured platform rows, not only
  queue or command success.
- Scale, outage, OAuth/provider-console, and other production proofs remain
  separate operational work.

## Verification Boundary

`make verify`, contract checks, architecture checks, artifact checks, and secret
scans prove the source tree. CI proves the exact PR SHA. Neither proves paid
providers, runtime promotion, production handshake, publishing, or metric
collection unless those checks are separately and explicitly run.
