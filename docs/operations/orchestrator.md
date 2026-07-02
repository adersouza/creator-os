# Reel Factory Orchestrator

The Reel Factory orchestrator is currently a dark state machine. It records
asset pipeline state and emits tick reports, but it does not start generation,
publishing, scheduling, or ThreadsDashboard runtime work.

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
daily_candidate_target = 10
top_k_for_approval = 3
campaign = "stacey"
creator = "Stacey"
```

`enabled = false` is the default. In that mode the tick writes a JSON status
report but does not create or mutate the database.

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

Tick reports are written to
`python_packages/reel_factory/project_data/orchestrator_ticks/`.

Record an operator decision (the approval inbox calls this under the hood;
`rejected` also writes `asset_rejection_evidence` in the campaign factory DB
as training signal):

```bash
uv run python -m reel_factory.orchestrator decide --root python_packages/reel_factory \
  --asset-id <stem> --decision approved|rejected|regenerate [--reason "..."]
```

## Approval Inbox

The operator UI lives in `apps/command-center` (port 4100): `/inbox` lists
`awaiting_approval` assets with media preview, caption, and rank; keyboard
flow is `j`/`k` navigate, `a` approve, `r` reject, `g` regenerate (reason
optional, submitted with Enter). API routes: `GET /api/inbox`,
`POST /api/inbox/:assetId/decision`, `GET /api/inbox/history`,
`GET /api/inbox/:assetId/media` — same auth model as `/api/state`
(`CREATOR_OS_API_TOKEN` or `ALLOW_INSECURE_LOCAL=1` on loopback). All writes
go through the Python `decide` CLI so the single-writer discipline and legal
transitions stay in one place. This inbox IS the operator UI — no general
dashboard.

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

Do not add generation stage wiring, approval inbox UI, scheduling, or publishing
to this launchd job.
