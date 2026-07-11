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
idempotent day produces only the normal informational job heartbeat.
