# Creator OS Artifact Retention Policy

Creator OS retains evidence before bytes. Unknown or referenced objects are
never automatic cleanup targets. A filename, duplicate hash, or age alone does
not authorize deletion.

## Protection rules

An artifact is protected while any of these conditions applies:

- it is approved, exported, scheduled, pending publication, published, measured,
  learned from, manually pinned, or linked to an active plan;
- it records provider billing, an ambiguous submission, publication
  reconciliation, release/security evidence, or rollback evidence;
- it is required to read historical WaveSpeed, local-model, audio, learning, or
  plan records;
- its reference graph or operational status is incomplete.

Canonical databases and the detached runtime are never automatic cleanup
targets. Database `VACUUM`, state rewriting, and media deduplication require a
separate backup-backed operation.

## Retention by class

| Class | Metadata | Bytes | Earliest prune consideration |
| --- | --- | --- | --- |
| Approved/exported/published finals | Indefinite | Indefinite | Never automatic |
| Provider/spend/publication receipts | Indefinite | Indefinite | Never automatic |
| Metrics, learning, recommendations, plans | Indefinite with versions | Indefinite for linked artifacts | Never automatic |
| Successful or ambiguous provider outputs | Indefinite | Indefinite while billed or referenced | 180 days only after complete reference proof |
| Rejected sources/review derivatives | Indefinite decision record | While referenced or pinned | 90–180 days with reviewed prune manifest |
| Audio catalog metadata | Indefinite | Governed by Audio Radar retention | Only after two valid absence observations and all protections pass |
| Processed audio segments | Indefinite lineage | While final/review/publication evidence uses them | 90 days if unreferenced and reproducible |
| Fixtures | While unique coverage exists | While unique coverage exists | After replacement coverage is proven |
| Operational logs | Receipt-dependent | Active/failure/reconciliation logs retained | 30 days for unreferenced debug-only logs |
| Release/security/rollback evidence | Indefinite | Indefinite | Never automatic |
| Test/compiler/package caches | None | Until the owning process completes | Immediately when reproducible and inactive |

Duplicate media remains `DUPLICATE_REFERENCED` until every consumer supports a
single canonical object. Hard-linking or content-addressed storage is a future
optimization, not an implicit deletion policy.

## Safe cleanup workflow

1. Capture source/runtime revisions and active processes.
2. Build a path-and-size cleanup plan with one retention class per candidate.
3. Verify references, active schedules, and database lineage.
4. Remove only `SAFE_EPHEMERAL` or proven `REGENERABLE_DERIVED` content.
5. Write a receipt containing exact targets, commands, failures, and before/after
   state.
6. Re-run Git, runtime, database, audio, contract, architecture, artifact, and
   secret checks appropriate to the change.

Private manifests may contain machine paths and hashes. Public reports must use
aggregates and must not include credentials, signed URLs, or private-media
paths.
