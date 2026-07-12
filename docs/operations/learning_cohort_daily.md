# Headless Learning Cohort Daily Controller

The daily controller advances only the due Stacey learning-cohort day. It is a
local state controller, not a generator or publisher:

- it never calls a provider or spends credits;
- it never creates a ThreadsDashboard draft;
- it never schedules or publishes;
- it keeps cohort autoposting disabled and preserves final approval;
- it refuses to queue a new day while an earlier approved handoff is still
  unconfirmed.

The refusal is intentional. It prevents unattended automation from building a
backlog after an operator skipped, abandoned, or could not complete a Notify
Publish handoff. Resolve the earlier post in ThreadsDashboard and record the
appropriate approval decision before the next daily run.

The launcher reuses `~/.creator-os/performance-sync.env`, including the exact
single-campaign scope and Campaign Factory database path:

```sh
scripts/run_learning_cohort_daily.sh
```

Install the launchd job outside the repository only after verifying the runtime
checkout and environment. The production installation runs daily at 8:30 AM
local time through `~/.creator-os/run-job.sh` and writes its latest structured
report to:

```text
~/.creator-os/reports/learning-cohort-daily-latest.json
```

An unresolved prior handoff produces a macOS/Discord warning. A safe queued or
idempotent day produces only the normal informational job heartbeat. A due day
whose assignments already moved beyond `planned` reports `day_already_started`;
it is not mislabeled as a new generation queue event.

## Zero-cost library production

`daily-library` is the bounded creative stage for the operator-owned Stacey
library. It is separate from the controller above: the controller decides which
day may advance, while this stage prepares exactly that day's regular/Trial
pair for review.

Always inspect the deterministic plan first:

```sh
campaign-factory daily-library --day 2
```

Then apply only when the selected paths are the intended files:

```sh
campaign-factory daily-library --day 2 --apply
```

The command:

- selects only real video files under `~/Documents/content/stacey` (override
  with `--library-root`);
- selects hooks from the weighted Stacey caption bank and applies the
  `stacey_static_center` visual preset;
- targets only the two selected source/render/audit IDs;
- emits a hash-verified operator-owned-source attestation so the external-copy
  SSCD gate does not require the optional Torch stack for owned media;
- still runs ContentForge and marks warning-only, upload-ready outputs
  `review_ready` while leaving blocking outputs in `draft`;
- never calls a provider, spends credits, approves, exports a draft, schedules,
  or publishes.

Historical catalog files without prompt and reference IDs remain formally
learning-ineligible. Their real publish metrics may be collected, but the
system does not fabricate lineage or count them toward the traceable learning
cohort. `review_ready` still requires an operator decision before any
ThreadsDashboard handoff.
