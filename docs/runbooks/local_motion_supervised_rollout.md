# Supervised Local Motion Rollout: 10 -> 25 -> 50 -> 100

This is a later operator-approved media rollout. It does not authorize social
publishing.

Immediately before the first local generation in a gate, the operator must
confirm exactly: **“Mode 3 — Local Wan / LTX motion — free.”** A confirmation
from an earlier gate or task does not carry forward.

At every gate, freeze a new Arena plan containing exact source/intent/model/
recipe/analyzer/seed/output fingerprints. No silent retry, sample replacement,
provider fallback, or escalation is allowed.

Promotion comparisons must use the identical source/prompt/seed/intent grid
for every model. Create the model-free authenticated review packet, complete and
lock every signed blinded review, and only then create the authenticated
unblinding receipt. The promotion summary must bind both records.

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
| 25 | queue/resource stability and useful yield | one machine lease; recoverable interruptions; >=75% valid reviewed yield; no duplicate jobs/receipts | same exact classes; no hidden retry |
| 50 | Router distribution and failure recovery | only active promoted models selected; every exclusion explained; overrides separately recorded | no-valid-model is a hold, never paid fallback |
| 100 | sustained throughput and evidence completeness | 100/100 terminal classifications; all successes have exact QC/review/benchmark records; resource and latency report complete | missing remains missing, never zero |

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
2. **frozen** — persist one `promotion_eligible` Arena plan and record its
   `planId` and `planFingerprint`; no inputs or assignments may change;
3. **approved-to-run** — the operator reviews the exact sample list and records
   approval tied to that plan fingerprint;
4. **executing** — run only sample IDs in the frozen plan through the local
   queue; an interrupted lease may resume the same immutable job, but a new
   seed, model, source, output, or sample ID is a new plan rather than a retry;
5. **reviewing** — finalize actual-media evidence, create the model-free blinded
   review packet, lock every signed review, then create the unblinding receipt;
6. **terminal** — build the Arena summary only after every planned sample has an
   honest terminal classification;
7. **approved-to-escalate** or **held** — record the decision against the exact
   plan, review packet, unblinding receipt, and summary fingerprints. A held gate
   cannot be bypassed by starting a larger cohort.

The operator record for states 3 and 7 must contain the gate size, plan ID and
fingerprint, predecessor-gate receipt fingerprint (null only for gate 10), exact
creator/model/capability counts, operator identity, UTC timestamp, decision,
and reason. The terminal record additionally contains the summary fingerprint,
review-packet fingerprint, unblinding-receipt fingerprint, terminal counts,
promotion-eligible yield, explicit failed/held sample IDs and classifications,
and the observed provider-call and production-write totals. Missing values stay
missing; they are never serialized as zero to satisfy a gate.

## Operator procedure

All diagnostic commands use the explicit advanced surface:

```bash
scripts/creator-os advanced models status --deep
scripts/creator-os advanced arena --root <arena-root> plan \
  --request <gate-request.json> \
  --contentforge-registry <analyzer-registry.json> \
  --repository-root <exact-clean-source-root>
```

Read the returned immutable plan before approving it. Then execute each exact
sample ID; do not loop over a directory that can change underneath the run:

```bash
scripts/creator-os advanced arena --root <arena-root> generate \
  --plan-id <plan-id> --sample-id <sample-id> --mode local_wan --apply
scripts/creator-os advanced arena --root <arena-root> finalize \
  --plan-id <plan-id> --sample-id <sample-id> --review <signed-review.json> \
  --repository-root <exact-clean-source-root> --identity-root <identity-root> \
  --produced-at <utc-timestamp>
```

After every sample is terminal, preserve blinding order:

```bash
scripts/creator-os advanced arena --root <arena-root> review-packet \
  --plan-id <plan-id> --created-at <utc-timestamp>
# Complete and lock every signed blinded review before the next command.
scripts/creator-os advanced arena --root <arena-root> unblind \
  --plan-id <plan-id> --created-at <later-utc-timestamp>
scripts/creator-os advanced arena --root <arena-root> summary --plan-id <plan-id>
```

Before escalation, re-read the plan and summary from their canonical stores,
verify every bound fingerprint, compare the result with the gate table above,
and have the operator sign the terminal decision. The 25 gate must cite the 10
terminal record, the 50 gate must cite the 25 record, and the 100 gate must cite
the 50 record. Model benchmark promotion and Router activation remain separate,
evidence-gated decisions; passing a rollout gate does not silently perform either.

## Final zero-write reconciliation

For every gate record exact observed counts for provider calls, provider cost
events, production writes, schedules, publishes, and QStash activity. Query the
real evidence stores; do not rely on a request field that merely claims zero.
Any nonzero or unavailable production/provider result holds the gate for
investigation. Social rollout, export to a publishing edge, and runtime
promotion require their own explicit approvals outside this protocol.
