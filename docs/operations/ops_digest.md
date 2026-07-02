# Creator OS Ops Digest

`scripts/ops_digest.py` emits a single local health line for the operator:

```text
outcomes 42(+5) | sync ok 30m old | backup 607MB 1h old | gen planned 0 inbox 0 | audio 2d old | refs 123
```

It is read-only. It checks:

- `reel_outcomes` total and 24-hour delta from
  `python_packages/reel_factory/manifest.sqlite`.
- Last `performance-sync` status from `~/.creator-os/ops.log`.
- Latest backup under `backups/runtime/`.
- Latest orchestrator tick under
  `python_packages/reel_factory/project_data/orchestrator_ticks/`.
- Reference Factory audio catalog age from `audio_catalog`.
- Reference Factory database row count.

The digest exits non-zero and notifies at `error` level when:

- Performance sync is missing, failed, or older than 3 hours.
- Runtime backup is missing or older than 26 hours.
- Audio catalog is missing or older than 14 days.

## Manual Command

```bash
uv run python scripts/ops_digest.py --dry-run
```

Without `--dry-run`, the script calls `~/.creator-os/notify.sh` if it exists.

## Launchd Template

Schedule after the operator confirms the local notification wrapper exists:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.creator-os.ops-digest</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/aderdesouza/.creator-os/run-job.sh</string>
    <string>ops-digest</string>
    <string>uv</string>
    <string>run</string>
    <string>python</string>
    <string>scripts/ops_digest.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/aderdesouza/Developer/creator-os</string>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>21</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/Users/aderdesouza/.creator-os/ops-digest.out.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/aderdesouza/.creator-os/ops-digest.err.log</string>
</dict>
</plist>
```
