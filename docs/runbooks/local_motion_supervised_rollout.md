# Supervised Local Motion Rollout: 10 -> 25 -> 50 -> 100

This is a later operator-approved media rollout. It does not authorize social
publishing.

Immediately before the first local generation in a gate, the operator must
confirm exactly: **“Mode 3 — Local Wan / LTX motion — free.”** A confirmation
from an earlier gate or task does not carry forward.

At every gate, freeze a new `supervised_rollout` Arena plan containing exact
source/intent/model/recipe/analyzer/seed/output fingerprints. The plan must have
exactly 10, 25, 50, or 100 samples. Every rollout recipe is permanently marked
`promotionEvidenceAllowed: false`; rollout results cannot be reused to promote
a model. No silent retry, sample replacement, provider fallback, or escalation
is allowed.

The model evidence used by a rollout must already have completed the separate
promotion protocol. For each rollout sample, capture the immutable
promotion-plan, promotion-summary, authenticated review-packet, authenticated
unblinding-receipt, and Router-decision bundle. Each bundle declares its
`rolloutSampleIds`; those declarations must form an exact, non-overlapping
partition of the rollout plan. Approval and execution both revalidate the
bundle and require its promotion to be active. Every bundle must name the same
promotion hardware fingerprint. That exact fingerprint is copied into every
sample partition reference and gate approval, must match the current local
machine before execution, and must match every recorded queue execution.

Before freezing or running a gate, execute
`scripts/creator-os advanced models status --deep`. Cache-only Hugging Face
dependencies are ready only when the pinned snapshot hashes and the exact
runtime reference both verify. A missing canonical reference may be repaired
with `advanced models install --apply` only when the install plan reports
`repairRequired=true`, `estimatedDownloadBytes=0`, and
`requiredFreeBytes=0`. A conflicting, unsafe, substituted, or unverifiable
reference is a hold; never enable an online or provider fallback to make the
cohort run.

Before accepting any executed sample, verify its enforced-isolation evidence:
network denied, minimal secret-free environment, exact artifact write root,
bounded hashed log, and current deep model/runtime attestation. A bare
`providerCalls: 0` field is insufficient.

Before spending model compute on the first sample after a runtime/toolchain
change, run the explicit no-model encoder-discovery canary:

```bash
CREATOR_OS_RUN_REAL_LOCAL_PREFLIGHT=1 \
  uv run --package reel-factory pytest -q \
  python_packages/reel_factory/tests/test_local_video.py \
  -k real_pinned_wan_runtime_discovers_exact_ffmpeg_in_sandbox
```

It starts no queue job and generates no media. It proves the pinned Wan Python,
inside the active no-network/no-write sandbox, imports `imageio_ffmpeg` and
resolves the exact verified FFmpeg binary. A skip or failure is a hold, not
permission to render.

| Gate | Primary proof | Pass criteria | Holds/failures |
|---|---|---|---|
| 10 | identity, actual-media QC, lineage, review/export ergonomics | every sample terminal; no substitution; >=80% valid reviewed yield; zero provider/production writes | failed, interrupted, resource-blocked, unsupported, missing, QC-blocked |
| 25 | queue/resource stability and useful yield | one exact hardware fingerprint across the cohort; single-machine queue invariant; no terminal interrupted/resource-blocked sample; >=75% valid reviewed yield; no substitution/duplicate evidence | same exact classes; mixed or missing hardware identity; no hidden retry |
| 50 | Router distribution and failure recovery | only active promoted models selected; no fallback/override; every sample recovered to a valid reviewed success | any unrecovered failure is a hold |
| 100 | sustained throughput and evidence completeness | 100/100 valid reviewed successes; every execution has exact QC/review/benchmark, resource, and latency evidence | missing or unavailable evidence remains missing and holds the gate |

For each gate the operator reviews the exact input list, creator/model
assignments, sample count, intended capability cohorts, and prior-gate receipt.
Escalation requires a recorded approval tied to that gate's plan and summary
fingerprints. Any model/implementation/recipe/analyzer change starts a new plan
and invalidates comparison with the old cohort.

## Gate state machine

Use the existing Arena, queue, benchmark, and human-review stores. Do not create
a rollout database or a second scheduler. Each gate moves through these states:

1. **proposed** — prepare the exact request and verify its intended sample count
   is exactly 10, 25, 50, or 100;
2. **frozen** — persist one `supervised_rollout` Arena plan and record its
   `planId` and `planFingerprint`; no inputs or assignments may change and its
   benchmark recipes remain ineligible for promotion;
3. **approved-to-run** — the operator reviews the exact sample list, the exact
   Router evidence partition, and the current active promotions, then records
   an authenticated approval tied to that plan fingerprint;
4. **executing** — run only sample IDs in the frozen plan through the local
   queue; an interrupted lease may resume the same immutable job, but a new
   seed, model, source, output, or sample ID is a new plan rather than a retry;
5. **reviewing** — finalize actual-media QC, benchmark, and signed human-review
   evidence for every success. The review packet and unblinding receipt in the
   rollout approval belong to the earlier promotion evidence; do not create a
   promotion review packet from rollout outputs;
6. **terminal** — build the Arena summary only after every planned sample has an
   honest terminal classification;
7. **approved-to-escalate** or **held** — record the decision against the exact
   plan, Router evidence, and summary fingerprints. A held gate cannot be
   bypassed by starting a larger cohort.

Every transition is an HMAC-authenticated, append-only
`reel_factory.local_model_rollout_gate_receipt.v1` record. It contains the gate
size, plan ID and fingerprint, predecessor-gate
`approved_to_escalate` receipt fingerprint (null only for gate 10), exact
creator/model/capability counts, Router snapshot references and sample
partition, exact mode confirmation, operator identity, UTC timestamp, decision,
and reason. The terminal or held record additionally contains the summary
fingerprint, terminal counts, valid reviewed yield, explicit failed/held sample
IDs and classifications, and Arena-observed provider-call and production-write
totals. It also embeds a fingerprinted
`reel_factory.local_model_rollout_gate_criteria.v1` derivation with every
gate-specific check and blocking reason; escalation re-derives that record from
the persisted summary. Missing values stay missing; they are never serialized
as zero to satisfy a gate.

The caller's `decided-at` must be monotonic, no later than the Arena's trusted
current clock, and no more than five minutes old. Router activation is always
evaluated at that trusted current time, never at a caller-supplied backdated
timestamp. Every receipt read replays the complete per-plan and cross-gate state
machine; duplicate, skipped, reordered, or directly injected transitions make
the journal invalid. A supervised sample terminal event also requires the exact
current `approved_to_run` receipt and revalidated active Router promotion.
Terminal events are independently fingerprinted and authenticated, bind the
approval and promotion-hardware fingerprints, and are replay-checked against
the current exact queue job/event/evidence. The generic journal is not exposed
as a mutable Arena API; a raw terminal row injected into its file fails replay.

Each transition also requires four independently produced, signed read-only
observation receipts: provider cost events, schedules, publishes, and QStash
events. Each receipt binds a fixed observer issuer, store identity, query
identity, observed interval, source fingerprint, canonical record fingerprint,
and record count. Signatures are Ed25519 and the Arena is verifier-only: it has
no observer private key or receipt-minting function. Campaign Factory must own
the provider-cost observer private key; the external ThreadsDashboard
integration must independently own the schedule, publish, and QStash observer
private keys. Their reviewed public keys and fixed key IDs must be pinned in
`ROLLOUT_EXTERNAL_ACTIVITY_OBSERVER_BINDINGS`.

No canonical observer public keys are currently supplied by this repository,
so the production bindings intentionally remain unset and every rollout
approval fails closed as `observer_unavailable`. Do not replace those empty
slots with operator-generated keys. The gate becomes executable only after the
four external producers exist, keep their private keys outside Creator OS, and
a reviewed change pins their public keys. Unsigned JSON/JSONL exports,
self-asserted empty arrays, stale observations, and an unavailable trusted
observer are holds. Keep the receipts and their exact source files immutable
for the gate.

## Operator procedure

All diagnostic commands use the explicit advanced surface:

```bash
# Explicit one-time Python dependency bootstrap on a new machine. This may
# download only lockfile-pinned packages into uv's cache, does not change the
# workspace environment, and does not download model weights.
uv run --isolated --locked --all-packages --extra identity \
  python -c "import cv2, insightface, onnxruntime"

# The operator launcher selects an isolated, locked, offline identity
# environment for every identity/Arena command after bootstrap.

scripts/creator-os advanced models status --deep
scripts/creator-os advanced identity identity-health \
  --creator <creator> --root <identity-root>
# If health reports a missing reference set, build it only from the exact
# reviewed profile and its fingerprint:
scripts/creator-os advanced identity identity-reference-build \
  --creator <creator> --input-dir <reviewed-reference-directory> \
  --root <identity-root> --identity-profile <identity-profile.json> \
  --identity-profile-fingerprint <sha256>
scripts/creator-os advanced arena --root <arena-root> plan \
  --request <gate-request.json> \
  --contentforge-registry <analyzer-registry.json> \
  --repository-root <exact-clean-source-root>
```

The request must say `"purpose": "supervised_rollout"`. Each Router evidence JSON
passed to the next command contains exactly these keys:
`arenaPlan`, `arenaSummary`, `reviewPacket`, `unblindingReceipt`,
`routerDecision`, and `rolloutSampleIds`. The first five values are the complete
immutable records from the separate promotion/Router decision. The last value
lists the exact sample IDs covered by that decision.

Read the returned immutable plan before approving it. Repeat
`--router-evidence` for every bundle and use the exact mode sentence:

```bash
scripts/creator-os advanced arena --root <arena-root> rollout-approve \
  --plan-id <plan-id> --rollout-id <rollout-id> \
  --operator-identity <operator> --decided-at <utc-timestamp> \
  --reason <reviewed-reason> \
  --mode-confirmation "Mode 3 — Local Wan / LTX motion — free." \
  --router-evidence <router-bundle-1.json> \
  --router-evidence <router-bundle-2.json> \
  --external-activity-observation provider_cost=<provider-cost-observation.json> \
  --external-activity-observation schedule=<schedule-observation.json> \
  --external-activity-observation publish=<publish-observation.json> \
  --external-activity-observation qstash=<qstash-observation.json> \
  [--predecessor-receipt-fingerprint <prior-approved-to-escalate-fingerprint>]
```

The 10 gate forbids a predecessor. The 25, 50, and 100 gates require the
authenticated `approved_to_escalate` receipt from the immediately preceding
gate in the same rollout. An approval receipt or terminal receipt is not a valid
predecessor.

Then execute each exact sample ID; do not loop over a directory that can change
underneath the run. `generate` revalidates the approval, Router snapshots, and
active promotion immediately before entering the local generation path:

```bash
scripts/creator-os advanced arena --root <arena-root> generate \
  --plan-id <plan-id> --sample-id <sample-id> --mode local_wan \
  --apply
scripts/creator-os advanced arena --root <arena-root> author-review \
  --plan-id <plan-id> --sample-id <sample-id> \
  --form <downloaded-human-review-form.json> \
  --analysis <trusted-media-analysis.json> \
  --operator-identity <exact-reviewer> --issued-at <exact-reviewed-at> \
  --output <signed-human-review.json>
scripts/creator-os advanced arena --root <arena-root> finalize \
  --plan-id <plan-id> --sample-id <sample-id> --review <signed-review.json> \
  --repository-root <exact-clean-source-root> --identity-root <identity-root> \
  --produced-at <utc-timestamp>
```

Never pass the downloaded form directly to `finalize`. It contains only the
operator's inputs. `author-review` copies the supplied ratings and decisions
without defaults and derives only the exact plan, packet, analysis, sampling,
and attestation evidence. The explicit `--operator-identity` and `--issued-at`
must exactly match the completed form. The completed form must also echo the
exact sampled frame-set fingerprint and brief-outlier count and explicitly
confirm those outliers were reviewed. Trusted analysis must cover every exact
plan-registry analyzer with matching observation and verdict evidence.

This import command does not authenticate the human. Its output records the
claimed reviewer as identity-unverified, and the resulting QC receipt is
non-promotable even when every decision is positive. The HMAC protects content
integrity only. Do not use an imported form as promotion evidence until a
separate credential-backed operator-verification boundary exists.

`finalize` records successful samples with their exact output, benchmark, and
human-review evidence. Record every non-success explicitly; inferred queue
state is not sufficient for rollout reconciliation. The command verifies the
classification against the exact queue job and its latest append-only evidence;
a never-run job cannot be called failed, and a submitted job cannot be called
missing:

```bash
scripts/creator-os advanced arena --root <arena-root> rollout-sample-terminal \
  --plan-id <plan-id> --sample-id <sample-id> \
  --status <failed|interrupted|resource_blocked|unsupported|cancelled|missing> \
  --reason <exact-classification-reason>
```

After every planned sample has one explicit terminal event, record the
evidence-derived reconciliation:

```bash
scripts/creator-os advanced arena --root <arena-root> rollout-reconcile \
  --plan-id <plan-id> --decision <terminal|held> \
  --operator-identity <operator> --decided-at <utc-timestamp> \
  --reason <reviewed-reason> \
  --external-activity-observation provider_cost=<provider-cost-observation.json> \
  --external-activity-observation schedule=<schedule-observation.json> \
  --external-activity-observation publish=<publish-observation.json> \
  --external-activity-observation qstash=<qstash-observation.json>
```

`terminal` is rejected when documented pass criteria are not met. `held` is
always available as the conservative operator decision, including when the
measured thresholds pass but review identifies a reason not to proceed. A
missing terminal event blocks either transition. A held receipt cannot
escalate. For a terminal gate, re-read the saved summary and have the operator
authenticate the separate escalation:

```bash
scripts/creator-os advanced arena --root <arena-root> rollout-escalate \
  --plan-id <plan-id> --operator-identity <operator> \
  --decided-at <utc-timestamp> --reason <reviewed-reason> \
  --external-activity-observation provider_cost=<provider-cost-observation.json> \
  --external-activity-observation schedule=<schedule-observation.json> \
  --external-activity-observation publish=<publish-observation.json> \
  --external-activity-observation qstash=<qstash-observation.json>
scripts/creator-os advanced arena --root <arena-root> rollout-status \
  --plan-id <plan-id>
```

The 25 gate must cite the 10 escalation receipt, the 50 gate must cite the 25
escalation receipt, and the 100 gate must cite the 50 escalation receipt. Model
benchmark promotion and Router activation remain separate, evidence-gated
decisions; rollout data is contractually barred from promotion, and passing a
rollout gate does not silently perform a promotion or Router activation.

## Final zero-write reconciliation

For every gate record exact observed counts for provider calls, provider cost
events, production writes, schedules, publishes, and QStash activity. Query the
real evidence stores; do not rely on a request field that merely claims zero.
Accept only the fixed signed observation receipts described above; the Arena
cannot substitute an operator-created empty export. Any nonzero, stale,
substituted, unsigned, or unavailable production/provider observation holds the
gate for investigation. Social rollout, export to a publishing edge, and
runtime promotion require their own explicit approvals outside this protocol.
