# Reel Factory Orchestrator

The Reel Factory orchestrator records asset pipeline state and emits tick
reports. State processing and paid generation have independent gates. It never
publishes, schedules, or invokes ThreadsDashboard runtime work.

## State

The state table lives in `python_packages/reel_factory/manifest.sqlite`:

```sql
asset_pipeline_state(asset_id, campaign, run_id, state, state_updated_at, ...)
```

Current supported states:

```text
planned -> prompted -> generated -> qc_passed -> ranked -> captioned
  -> export_ready -> awaiting_approval -> approved -> exported
```

The approval state can also move to `rejected` or loop through `regenerate`.
Regenerate loops back to `planned` and is capped at two attempts. Stale
in-flight states are marked `error` by the tick.

## Local Config

Create `python_packages/reel_factory/project_data/orchestrator.toml` only when
you want the tick to touch the SQLite state table:

```toml
enabled = false
paid_generation_enabled = false
daily_candidate_target = 10
top_k_for_approval = 3
campaign = "stacey"
creator = "Stacey"
reference_image = "/absolute/path/to/reference.jpg"
estimated_cost_per_asset_usd = 0.50
caption_mix = "Stacey"
```

`enabled = false` is the default. In that mode the tick writes a JSON status
report but does not create or mutate the database.

`enabled = true` permits state recovery, ingestion, ranking, approval promotion,
and dry-run planning. It does not grant spending authority. Paid generation also
requires `paid_generation_enabled = true`, the per-invocation
`--allow-paid-generation` flag, and a positive `--max-total-cost-usd` ceiling.
The tick also refuses paid generation unless `campaign`, `creator`, one reference
path, and `estimated_cost_per_asset_usd` are set and the existing Higgsfield cost
preflight allows the run. It then calls the existing
`pipeline_run` flow for the daily shortfall, ingests `pipeline_run.json` evidence
into `asset_pipeline_state`, and promotes the top ranked export-ready assets into
the approval inbox. It does not schedule or publish.

The emergency kill switch disables all writes, including tick reports:

```bash
CREATOR_OS_ORCHESTRATOR_DISABLED=1 uv run python -m reel_factory.orchestrator tick \
  --root python_packages/reel_factory
```

## Manual Commands

Initialize the state table:

```bash
uv run python -m reel_factory.orchestrator init --root python_packages/reel_factory
```

Run one tick:

```bash
uv run python -m reel_factory.orchestrator tick --root python_packages/reel_factory
```

That command cannot spend. A paid tick requires all persistent and
per-invocation gates:

```bash
uv run python -m reel_factory.orchestrator tick --root python_packages/reel_factory \
  --allow-paid-generation --max-total-cost-usd 1.00
```

Tick reports are written to
`python_packages/reel_factory/project_data/orchestrator_ticks/`.

Inspect the headless operator state and approval inbox:

```bash
uv run python -m reel_factory.orchestrator status --root python_packages/reel_factory
uv run python -m reel_factory.orchestrator inbox --root python_packages/reel_factory
```

Record an operator decision;
`rejected` also writes `asset_rejection_evidence` in the campaign factory DB
as training signal):

```bash
uv run python -m reel_factory.orchestrator decide --root python_packages/reel_factory \
  --asset-id <stem> --decision approved|rejected|regenerate [--reason "..."]
```

`inbox` returns ranked `awaiting_approval` records as JSON. `decide` remains
the only mutation path, preserving the single-writer and legal-transition
rules. Creator OS has no approval web UI; ThreadsDashboard remains the only
product UI.

## Launchd Template

Install only after the operator explicitly wants the dark tick scheduled:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.creator-os.reel-factory-orchestrator</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/aderdesouza/.creator-os/run-job.sh</string>
    <string>reel-orchestrator</string>
    <string>uv</string>
    <string>run</string>
    <string>python</string>
    <string>-m</string>
    <string>reel_factory.orchestrator</string>
    <string>tick</string>
    <string>--root</string>
    <string>python_packages/reel_factory</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/aderdesouza/Developer/creator-os</string>
  <key>StartInterval</key>
  <integer>1800</integer>
  <key>StandardOutPath</key>
  <string>/Users/aderdesouza/.creator-os/reel-orchestrator.out.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/aderdesouza/.creator-os/reel-orchestrator.err.log</string>
</dict>
</plist>
```

Do not add scheduling or publishing
to this launchd job.
