# Daily production orchestration

`scripts/run_daily_orchestrator.sh` is the recurring, non-publishing Creator OS
entrypoint. It keeps one idempotent run per UTC day and delegates all selection,
governance, spend, retry, and reservation behavior to Campaign Factory's
existing `orchestrate-daily` command.

The wrapper defaults to `preview`. Machine configuration may set:

```bash
CREATOR_OS_DAILY_ORCHESTRATOR_MODE=preview  # read-only
CREATOR_OS_DAILY_ORCHESTRATOR_MAX_ITEMS=3
CREATOR_OS_DAILY_ORCHESTRATOR_PER_CREATOR=1
CREATOR_OS_DAILY_ORCHESTRATOR_PER_CAMPAIGN=1
CREATOR_OS_DAILY_ORCHESTRATOR_PROVIDER_CAP=0
```

Use `plan` only after campaign governance is ready. It records the plan but
does not call a provider. Use `execute` only after the generation environment
contains the existing spend and operator-authority configuration. None of the
three modes schedules or publishes.

## LaunchAgent

Install this outside Git as
`~/Library/LaunchAgents/com.creator-os.daily-orchestrator.plist`, pointing
`CREATOR_OS_RUNTIME_ROOT` at the protected runtime:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.creator-os.daily-orchestrator</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/aderdesouza/Developer/creator-os-runtime/scripts/run_daily_orchestrator.sh</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>CREATOR_OS_RUNTIME_ROOT</key>
    <string>/Users/aderdesouza/Developer/creator-os-runtime</string>
    <key>CREATOR_OS_DAILY_ORCHESTRATOR_MODE</key>
    <string>preview</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>5</integer>
    <key>Minute</key>
    <integer>45</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/aderdesouza/.creator-os/logs/daily-orchestrator.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/aderdesouza/.creator-os/logs/daily-orchestrator.log</string>
</dict>
</plist>
```

Keep the installed job in `preview` until one supervised `plan` succeeds.
Promotion may replace the runtime checkout, but the stable runtime path and
wrapper remain unchanged.
