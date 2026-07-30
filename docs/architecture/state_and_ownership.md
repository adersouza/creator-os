# State and write ownership

The machine-readable source is
`packages/pipeline_contracts/pipeline_contracts/ownership_registry.v1.json`.
CI validates it with `pnpm check:ownership`.

## Canonical boundary

| Fact | Canonical owner | Canonical store | Other system's copy |
|---|---|---|---|
| Campaigns, source/rendered assets, lineage, creative approval, reservations | Creator OS / Campaign Factory | Campaign Factory SQLite | Handoff context only |
| Reference observations | Creator OS / Reference Factory | Reference Factory evidence | Promoted Campaign knowledge with an immutable receipt |
| Render attempts and local caches | Creator OS / Reel Factory | Reel Factory evidence | Registered Campaign asset after receipt/SHA validation |
| Drafts and delivery media | ThreadsDashboard | Supabase `posts`, `media`, bridge tables | Creator OS outbound intent and acknowledgment |
| Scheduling and publishing | ThreadsDashboard reconciled with Meta | Supabase schedule/publication tables | Imported downstream observation |
| Timed platform metrics | ThreadsDashboard reconciled with Meta | `post_metric_history` | Campaign Factory snapshot bound to the exact history row |
| Campaign learning | Creator OS | Campaign Factory learning tables | Never written by ThreadsDashboard |
| Autoposter learning | ThreadsDashboard | Autoposter fact/recommendation tables | Never written by Creator OS |
| Payload structure | Pipeline Contracts | Canonical JSON Schema and reviewed package release | No runtime state |

An ID present in both repositories is a join key, not shared write authority.
Creator OS does not possess a general Supabase write credential for draft
delivery. ThreadsDashboard does not write Campaign Factory SQLite.

## Handoff saga

```text
Creator OS prepares export
→ persists threadsdash_exports intent
→ requests an owner-issued delivery-media upload ticket
→ uploads the exact approved bytes
→ submits one signed export identity
→ ThreadsDashboard verifies bytes and Creative Approval evidence
→ ThreadsDashboard creates/reuses the draft and persists campaign_factory_post_links
→ ThreadsDashboard returns a durable acknowledgment
→ Creator OS records acceptance
→ Creator OS commits the pending inventory reservation
```

Creator OS export knowledge uses `prepared`, `submitted`,
`acceptance_unknown`, `accepted`, `rejected`, and `superseded`. These are not
dashboard draft states. A timeout after submission retains the reservation and
requires `creator-os bridge reconcile`; it must not create a new logical
export.

The handoff identity binds the export/idempotency key, campaign, rendered and
source asset IDs, final SHA-256, Creative Approval v2 fingerprint, contract
fingerprint, destination, surface, and reservation. Shared payloads contain no
absolute local paths.

## Approval and account terminology

Creator OS Creative Approval is an exact-SHA creative decision.
ThreadsDashboard workflow approval/rejection is downstream operational state;
API/UI language should call it `dashboardWorkflowApprovedBy` or
`dashboardWorkflowRejectedBy`. It cannot create or rewrite Creator OS approval.

Creator OS owns creative account targeting and preferences. ThreadsDashboard
owns platform IDs, OAuth/token health, connection/publishing capability,
scheduling, restrictions, and operational health. Meta owns actual account,
publication, and metric facts. Synchronization is field-directed through the
bridge identity, never whole-record synchronization.

## Evidence levels

Always report these separately:

1. source change exists;
2. committed or merged;
3. migration CI passed;
4. migration deployed;
5. runtime constraint/row verified;
6. external platform fact reconciled.

A committed migration is not a deployed schema. HTTP success, a QStash
receipt, or an Instagram container is not reconciled publication. A current
`posts` counter is not a timed metric-history observation.

## Authoritative report truth

The ownership registry also names the bounded read-only reports that are
allowed to describe canonical Creator OS state. Each entry identifies a real
repo-relative emitter and explicit report fields with their source, freshness,
unknown behavior, evidence, and repair action. Wildcard field rules are
forbidden because they would let a new field inherit authority without review.

Discovery is intentionally limited to the report-only source files listed in
`authoritativeReportDiscovery.sourceFiles`. Within those files,
`pnpm check:ownership` discovers literal schemas ending in `_status`,
`_report`, `_dashboard`, `_summary`, or `_readiness` and requires every one to
be registered. This catches new authoritative projections without treating
plans, operation contexts, receipts, or other incidental payloads as reports.
The checker also fails when a registered emitter file or named function does
not exist, when the emitter does not contain the registered schema, or when an
explicit `/schema` field rule is missing.

`campaign_factory.creator_governance_status.v1` is the authoritative local
projection for creator lifecycle, slug history, identity profiles, platform
accounts, and authorization events. It does not prove external provider state
or downstream publication.

## Persistent field ownership

`persistenceOwnership` in the registry covers the four local SQLite stores and
the persistent JSON artifact families. The field inventory is derived from
fresh temporary databases created by the real Campaign Factory, Reference
Factory, Reel manifest/evidence, and Reel render-queue initializers:

```bash
uv run python scripts/inventory-persistence.py
```

The inventory records every table field's SQLite type, nullability, default,
primary-key status, unique constraint, foreign keys, and table immutability
triggers. Registry policy then supplies the owner, legal readers/writers,
mutability, allowed-value authority, transition owner, retention, deletion or
tombstone behavior, receipt binding, and repair path. Primary keys and
`created_at` fields are immutable after insert; explicit record rules make
evidence/event records append-only and state-machine records transition-only.

`pnpm check:ownership` rebuilds this inventory and scans production Python SQL.
A direct `INSERT`, `UPDATE`, `DELETE`, or `REPLACE` against a known record is
legal only from the reviewed exact record/table writer set. The canonical
fingerprint changes even when a new writer is added inside the owning package,
so package membership alone is not write authority. A newly initialized table
or field is covered immediately by the store policy; an unregistered store,
writer, artifact family, or record rule fails closed.

Persistent JSON is registered by artifact family because its exact fields are
owned by the producer payload or versioned Pipeline Contract, not SQLite. The
families cover Campaign handoff manifests/receipts, Reel manifest and lineage
sidecars, analysis/provider receipts, caption banks/review sidecars, and
Reference intake/pattern artifacts. Each family names its legal writers,
readers, mutation policy, retention, byte/receipt binding, and repair owner.
The checker also fingerprints producer modules and their literal `.json` or
`.jsonl` families. Adding a new persistent JSON producer or filename family
requires an ownership review instead of silently inheriting authority.

Campaign-managed intake and reconciliation copies use the shared
`artifact_storage.atomic_copy` path. It rejects traversal, symlink components,
and byte collisions; removes failed temporary files; preserves root-keyed paths
across runtime-root changes; and reserves the incoming byte count before the
copy. The default minimum remaining free space is 512 MiB. Operators may set
`CREATOR_OS_ARTIFACT_MIN_FREE_BYTES` and
`CREATOR_OS_ARTIFACT_QUOTA_BYTES`; malformed or exceeded limits fail closed.

## Operator commands

```bash
creator-os state explain threadsdash_exports
creator-os bridge reconcile --export-id tdexp_...
```

Reconciliation attaches a matching durable acknowledgment automatically. Hash
mismatches, duplicate/ambiguous receipts, missing links, and owner
contradictions are reported; uncertain ownership conflicts are never silently
repaired.
