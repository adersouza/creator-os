# Supervised Content Director

## Boundary

The Content Director is a Campaign Factory domain, not a service. It turns
approved sources, approved patterns, account projections, supervised learning,
and operator constraints into a versioned seven-day plan. It does not own
generation, scheduling, publishing, metrics, or a separate learning model.

Campaign Factory continues to decide and preserve lineage. The existing normal
Higgsfield production lane generates. Audio Radar resolves exact non-talking
audio near finishing. ThreadsDashboard remains final scheduling, publication,
and canonical metric-history authority.

## Domain records

- `creative_plan_versions`: immutable planning inputs, scope, objective,
  autonomy mode, spend estimate/ceiling, fingerprint, predecessor, receipt.
- `creative_plan_items`: creator, account, intent, approved source/pattern,
  audio profile, experiment, proposal, state, and generation-through-learning
  identities.
- `creative_plan_item_events`: append-only operator and reconciliation events.
- `creative_plan_experiments`: one changed variable, deterministic assignment,
  cohort, outcome links, and confidence limitation.
- `creative_plan_metric_cohorts`: 1h/24h/72h expected and actual observations;
  missing is never zero.

All plan lookups are scoped by plan, creator, account, intent, state, or due
time. Indexed bounded queries target correct operation first for one creator,
three accounts, ten creators, and one hundred accounts.

## States

```text
DRAFT -> REVIEWED -> APPROVED -> GENERATION_READY -> GENERATING
      -> RECONCILING -> REVIEW_READY -> CREATIVE_APPROVED -> EXPORT_READY
      -> EXPORTED -> SCHEDULE_READY -> SCHEDULED -> PUBLISHING
      -> PUBLISHED -> MEASURING -> LEARNED
```

`BLOCKED`, `REJECTED`, and `CANCELLED` are explicit. Invalid transitions fail.
A plan cannot be approved while any item has a blocking reason.
Explicit fixed-asset cohorts use
`APPROVED -> EXISTING_ASSET_READY -> CREATIVE_APPROVED`; they never enter a
generation-ready state.

## Decision authority

Planning may order only approved creator sources and imported approved prompt
patterns. Only current matching `SUPERVISED_ACTIVE` evidence may change an
ordering. It may softly describe audio intent for eligible non-talking content.
It cannot change creator identity, Soul ID, Higgsfield, Kling/Seedance policy,
approved status, QC, spend, account authorization, safety, or publication
eligibility.

## Cadence authority

Healthy eligible accounts target their configured daily cadence. Reduced
every-other-day cadence is valid only for warming, account health/platform
constraints, insufficient approved inventory, or an explicit operator choice.
Accounts advance independently and retain minimum-gap enforcement.

Campaign schedule windows are proposals with an explicit account-local
timezone. ThreadsDashboard reconciles pending/stale schedules and remains the
final scheduling authority. Metric workers calculate overlapping 1h/24h/72h
observations from each actual publication timestamp; they do not serialize
publication or compare unlike observation ages.

## Autonomy modes

- `SHADOW`: plan and explain only; no production mutation.
- `SUPERVISED`: operator approves the plan, signs spend, approves media, and
  hands final scheduling/publication to ThreadsDashboard.
- `APPROVED_PLAN_AUTOPILOT`: may execute only the immutable approved item set
  within signed bounds; it cannot add items, change identity/account/provider/
  experiment, retry ambiguity, or publish.

There is no unrestricted autonomous-publishing mode.

## Explicit fixed-asset cohorts

`FIXED_ASSET_COHORT` is a supervised, operator-requested Content Director mode
for attaching an exact set of already-approved canonical assets to one truthful
learning cohort. Every item retains its existing creator, account, intent,
source, generation, review, audio, and final-media lineage. Repeated intents
are permitted only because the operator supplied the exact assets and common
intent through `creator-os plan cohort`.

This mode does not alter ordinary seven-day planning or its content-mix,
cooldown, pattern, audio-uniqueness, and exploration rules. It does not
generate, export, schedule, or publish. Its experiment receipt is classified
`MECHANICAL_LEARNING_PROOF`: multiple creative and audio variables may differ,
so it supports mechanical lineage proof but no causal creative conclusion.
The exact assets propose consecutive eligible account-local dates at
approximately the same local time, with `learnedTiming=false`.

## Cost receipt

Each plan records estimated jobs and credits, signed maximum credits, unknown
costs, and cost evidence. Execution records quote, authorization, actual or
reconciled credits, variance, partial success, and refund evidence when the
provider exposes them. Unknown cost never becomes zero and the planner never
authorizes its own spend.

## Security

Public plan summaries contain stable IDs, not credentials, OAuth tokens, signed
URLs, raw private provider payloads, or private media paths. Detailed receipts
remain private and credential-scrubbed. Plan configuration contains no secrets.
