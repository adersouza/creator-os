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

## Operator commands

```bash
creator-os state explain threadsdash_exports
creator-os bridge reconcile --export-id tdexp_...
```

Reconciliation attaches a matching durable acknowledgment automatically. Hash
mismatches, duplicate/ambiguous receipts, missing links, and owner
contradictions are reported; uncertain ownership conflicts are never silently
repaired.
