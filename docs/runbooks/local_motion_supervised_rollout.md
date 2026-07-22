# Supervised Local Motion Rollout: 10 -> 25 -> 50 -> 100

This is a later operator-approved media rollout. It does not authorize social
publishing.

At every gate, freeze a new Arena plan containing exact source/intent/model/
recipe/analyzer/seed/output fingerprints. No silent retry, sample replacement,
provider fallback, or escalation is allowed.

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
